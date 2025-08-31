"""
Hybrid CDON scraper combining listing crawler (Playwright) and product parser (pure Python)
"""

import asyncio
import logging
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from .config import CONFIG
from .database.connection import AsyncSessionLocal, init_db
from .listing_crawler import ListingCrawler
from .models import Movie as SQLMovie
from .models import MovieWithPricing, PriceAlert, PriceHistory, Watchlist
from .product_parser import Movie as ParsedMovie
from .product_parser import ProductParser
from .tmdb_service import TMDBService

# Load environment variables first
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class CDONScraper:
    """Hybrid scraper combining listing crawler and product parser"""

    def __init__(self) -> None:
        self.listing_crawler = ListingCrawler()
        self.product_parser = ProductParser()

        # Initialize TMDB service if API key is available
        self.tmdb_service: TMDBService | None = None
        if CONFIG["tmdb_api_key"]:
            try:
                self.tmdb_service = TMDBService(
                    api_key=CONFIG["tmdb_api_key"], poster_dir=CONFIG["poster_dir"]
                )
                logger.info("TMDB service initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize TMDB service: {e}")
        else:
            logger.info("TMDB API key not found - poster fetching disabled")

        # Database initialization is now handled by FastAPI app lifecycle
        # or called explicitly when needed

    async def init_database(self) -> None:
        """Initialize database using SQLModel."""
        await init_db()
        logger.info(f"Database initialized using SQLModel at {CONFIG['db_path']}")

    async def crawl_category(self, category_url: str, max_pages: int = 5) -> int:
        """Main crawl workflow: get URLs then parse products, returns count of saved movies"""
        logger.info(f"Starting hybrid crawl of {category_url}")

        # Step 1: Use listing crawler to get product URLs
        logger.info("Phase 1: Collecting product URLs with Playwright...")
        product_urls = await self.listing_crawler.crawl_category(category_url, max_pages)

        if not product_urls:
            logger.warning("No product URLs found")
            return 0

        logger.info(f"Found {len(product_urls)} product URLs")

        # Step 2: Use product parser to extract details and save incrementally
        logger.info("Phase 2: Parsing product details and saving incrementally...")
        saved_count = 0

        for i, url in enumerate(product_urls, 1):
            try:
                logger.info(f"Processing {i}/{len(product_urls)}: {url}")
                movie = self.product_parser.parse_product_page(url)

                if movie and self.is_bluray_format(movie.title, movie.format):
                    # Save immediately after successful parsing
                    if await self.save_single_movie(movie):
                        saved_count += 1
                        logger.info(f"✓ Saved ({saved_count}): {movie.title} - €{movie.price}")

                        # Progress report every 10 movies
                        if saved_count % 10 == 0:
                            logger.info(f"Progress: {saved_count} movies saved so far")
                    else:
                        logger.warning(f"✗ Failed to save: {movie.title}")
                else:
                    logger.debug("✗ Skipped: not a Blu-ray or parsing failed")

            except Exception as e:
                logger.error(f"Error parsing {url}: {e}")
                continue

        logger.info(f"Crawl complete: saved {saved_count} Blu-ray movies to database")
        return saved_count

    def is_bluray_format(self, title: str, format: str) -> bool:
        """Check if the item is a Blu-ray or 4K Blu-ray (reuse existing logic)"""
        return "Blu-ray" in format or "blu-ray" in title.lower() or "bluray" in title.lower()

    async def save_single_movie(self, movie: ParsedMovie) -> bool:
        """Save a single movie to database using SQLModel and return success status"""
        async with AsyncSessionLocal() as session:
            try:
                # Try to fetch TMDB data if service is available
                tmdb_id = None
                local_poster_path = None
                content_type = "movie"  # Default to movie

                if self.tmdb_service and movie.title:
                    try:
                        # Detect if it's a TV series
                        if self.tmdb_service._is_tv_series(movie.title):
                            content_type = "tv"

                        # Prioritize production_year from parsed page data over title extraction
                        year = movie.production_year or self.tmdb_service.extract_year_from_title(movie.title)
                        tmdb_id, local_poster_path = self.tmdb_service.get_movie_data_and_poster(
                            movie.title, year
                        )
                    except Exception as e:
                        logger.debug(f"TMDB lookup failed for '{movie.title}': {e}")

                # Use local poster path if available, otherwise fall back to original image_url
                final_image_url = local_poster_path if local_poster_path else movie.image_url

                # Check if movie already exists
                existing_movie = None
                if movie.product_id:
                    result = await session.execute(
                        select(SQLMovie).where(SQLMovie.product_id == movie.product_id)
                    )
                    existing_movie = result.scalar_one_or_none()
                else:
                    result = await session.execute(
                        select(SQLMovie).where(
                            SQLMovie.title == movie.title, SQLMovie.format == movie.format
                        )
                    )
                    existing_movie = result.scalar_one_or_none()

                if existing_movie:
                    # Update existing movie
                    existing_movie.last_updated = datetime.utcnow()
                    # Update production year if we have it and it's not set
                    if movie.production_year and not existing_movie.production_year:
                        existing_movie.production_year = movie.production_year
                    db_movie = existing_movie
                else:
                    # Create new movie
                    db_movie = SQLMovie(
                        product_id=movie.product_id,
                        title=movie.title,
                        format=movie.format,
                        url=movie.url,
                        image_url=final_image_url,
                        production_year=movie.production_year,
                        tmdb_id=tmdb_id,
                        content_type=content_type,
                        first_seen=datetime.utcnow(),
                        last_updated=datetime.utcnow(),
                    )
                    session.add(db_movie)

                # Commit to get the movie ID
                await session.commit()
                await session.refresh(db_movie)

                # Add price history
                price_entry = PriceHistory(
                    movie_id=db_movie.id,
                    product_id=movie.product_id,
                    price=movie.price,
                    availability=movie.availability,
                    checked_at=datetime.utcnow(),
                )
                session.add(price_entry)

                # Check for price drops
                if db_movie.id is not None:
                    await self.check_price_alerts(session, db_movie.id, movie.price)

                await session.commit()
                logger.debug(f"✓ Saved: {movie.title} - €{movie.price}")
                return True

            except Exception as e:
                logger.error(f"Error saving movie {movie.title}: {e}")
                await session.rollback()
                return False

    async def save_movies(self, movies: list[ParsedMovie]) -> None:
        """Save movies to database using SQLModel"""
        for movie in movies:
            await self.save_single_movie(movie)
        logger.info(f"Saved {len(movies)} movies to database")

    async def check_price_alerts(
        self, session: AsyncSession, movie_id: int, new_price: float
    ) -> None:
        """Check if price has dropped and create alerts using SQLModel"""
        # Get product_id for this movie
        movie_result = await session.execute(
            select(SQLMovie.product_id).where(SQLMovie.id == movie_id)
        )
        product_id = movie_result.scalar_one_or_none()

        if not product_id:
            logger.warning(f"No product_id found for movie {movie_id}")
            return

        # Get last two prices
        result = await session.execute(
            select(PriceHistory.price)
            .where(PriceHistory.movie_id == movie_id)
            .order_by(PriceHistory.checked_at.desc())  # type: ignore
            .limit(2)
        )
        prices = result.scalars().all()

        if len(prices) >= 2:
            old_price = prices[1]  # Second most recent price
            if new_price < old_price:
                # Price dropped!
                price_alert = PriceAlert(
                    movie_id=movie_id,
                    product_id=product_id,
                    old_price=old_price,
                    new_price=new_price,
                    alert_type="price_drop",
                    created_at=datetime.utcnow(),
                    notified=False,
                )
                session.add(price_alert)
                logger.info(
                    f"Price drop detected for movie {movie_id}: €{old_price} -> €{new_price}"
                )

        # Check watchlist targets
        result = await session.execute(
            select(Watchlist.target_price).where(Watchlist.movie_id == movie_id)
        )
        watchlist_target = result.scalar_one_or_none()

        if watchlist_target and new_price <= watchlist_target:
            target_alert = PriceAlert(
                movie_id=movie_id,
                product_id=product_id,
                old_price=new_price,
                new_price=new_price,
                alert_type="target_reached",
                created_at=datetime.utcnow(),
                notified=False,
            )
            session.add(target_alert)
            logger.info(f"Target price reached for movie {movie_id}: €{new_price}")

    async def add_to_watchlist(self, product_id: str, target_price: float) -> bool:
        """Add a movie to the watchlist using product_id"""
        async with AsyncSessionLocal() as session:
            try:
                # Find movie by product_id
                result = await session.execute(
                    select(SQLMovie).where(SQLMovie.product_id == product_id)
                )
                movie = result.scalar_one_or_none()

                if movie:
                    # Check if already in watchlist
                    existing_result = await session.execute(
                        select(Watchlist).where(Watchlist.movie_id == movie.id)
                    )
                    existing_watchlist = existing_result.scalar_one_or_none()

                    if existing_watchlist:
                        # Update existing entry
                        existing_watchlist.target_price = target_price
                        existing_watchlist.created_at = datetime.utcnow()
                    else:
                        # Create new entry
                        watchlist_item = Watchlist(
                            movie_id=movie.id,
                            product_id=movie.product_id,
                            target_price=target_price,
                            created_at=datetime.utcnow(),
                        )
                        session.add(watchlist_item)

                    await session.commit()
                    logger.info(
                        f"Added movie {movie.id} to watchlist with target price €{target_price}"
                    )
                    return True

                logger.warning(f"Movie with product_id '{product_id}' not found in database")
                return False

            except Exception as e:
                logger.error(f"Error adding to watchlist: {e}")
                await session.rollback()
                return False

    async def get_price_alerts(self) -> list[dict]:
        """Get unnotified price alerts using SQLModel"""
        async with AsyncSessionLocal() as session:
            query = (
                select(PriceAlert, SQLMovie.title, SQLMovie.url)
                .join(SQLMovie)
                .where(not PriceAlert.notified)
                .order_by(PriceAlert.created_at.desc())  # type: ignore
            )

            result = await session.execute(query)
            alerts = []

            for alert, title, url in result.all():
                alerts.append(
                    {
                        "id": alert.id,
                        "movie_id": alert.movie_id,
                        "old_price": alert.old_price,
                        "new_price": alert.new_price,
                        "alert_type": alert.alert_type,
                        "created_at": alert.created_at,
                        "title": title,
                        "url": url,
                    }
                )

            return alerts

    async def mark_alerts_notified(self, alert_ids: list[int]) -> None:
        """Mark alerts as notified using SQLModel"""
        async with AsyncSessionLocal() as session:
            try:
                for alert_id in alert_ids:
                    result = await session.execute(
                        select(PriceAlert).where(PriceAlert.id == alert_id)
                    )
                    alert = result.scalar_one_or_none()
                    if alert:
                        alert.notified = True

                await session.commit()
            except Exception as e:
                logger.error(f"Error marking alerts as notified: {e}")
                await session.rollback()

    async def search_movies(self, query: str) -> list[MovieWithPricing]:
        """Search for movies in the database using SQLModel"""
        async with AsyncSessionLocal() as session:
            from .database.repository import DatabaseRepository

            repo = DatabaseRepository(session)
            return await repo.search_movies(query, 20)

    def close(self) -> None:
        """Clean up resources"""
        self.product_parser.close()


async def main() -> None:
    """Demonstrate the hybrid scraper"""
    scraper = CDONScraper()

    # Test with limited pages for demo
    bluray_url = "https://cdon.fi/elokuvat/?facets=property_preset_media_format%3Ablu-ray&q="
    logger.info("Starting hybrid crawl demo...")

    saved_count = await scraper.crawl_category(bluray_url, max_pages=2)  # Just 2 pages for demo
    logger.info(f"Demo complete: saved {saved_count} Blu-ray movies to database")

    # Show some recent results from database
    recent_movies = (await scraper.search_movies(""))[:5]  # Get last 5 movies
    if recent_movies:
        print("\nRecent movies added to database:")
        for movie in recent_movies:
            print(f"- {movie.title} - €{movie.current_price} ({movie.format})")
    else:
        print("\nNo movies found in database")

    scraper.close()


if __name__ == "__main__":
    asyncio.run(main())
