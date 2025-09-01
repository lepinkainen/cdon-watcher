"""Price monitoring service for CDON Watcher."""

import asyncio
import hashlib
from datetime import UTC
from datetime import datetime as dt

from sqlmodel import select

from .database.connection import AsyncSessionLocal
from .models import Movie as SQLMovie
from .models import PriceHistory, Watchlist
from .notifications import NotificationService
from .product_parser import Movie as ParsedMovie
from .product_parser import ProductParser


class PriceMonitor:
    """Monitor prices and send notifications."""

    def __init__(self) -> None:
        self.product_parser = ProductParser()
        self.notification_service = NotificationService()

    async def check_watchlist_prices(self) -> None:
        """Check prices for all watchlist items using SQLModel."""
        async with AsyncSessionLocal() as session:
            # Get all watchlist items with their URLs
            query = select(Watchlist, SQLMovie.url, SQLMovie.title).join(
                SQLMovie,
                Watchlist.movie_id == SQLMovie.id,  # type: ignore
            )
            result = await session.execute(query)
            watchlist_items = result.all()

        if not watchlist_items:
            print("No items in watchlist")
            return

        print(f"Checking {len(watchlist_items)} watchlist items...")

        # Check each item using the product parser
        for _watchlist_item, url, title in watchlist_items:
            print(f"Checking: {title}")

            try:
                # Parse the specific product page
                movie = self.product_parser.parse_product_page(url)
                if movie:
                    await self._save_single_movie(movie)

                # Small delay between requests
                await asyncio.sleep(2)

            except Exception as e:
                print(f"Error checking {title}: {e}")

        # Get and process alerts
        alerts = await self._get_price_alerts()
        if alerts:
            await self.notification_service.send_notifications(alerts)
            await self._mark_alerts_notified([a["id"] for a in alerts])

    async def _save_single_movie(self, movie: ParsedMovie) -> bool:
        """Save a single movie to database using SQLModel (simplified version)"""
        async with AsyncSessionLocal() as session:
            try:
                # Generate a unique product_id if None
                product_id = movie.product_id
                if not product_id:
                    unique_string = f"{movie.title}_{movie.format}_{movie.url}".lower().replace(
                        " ", "_"
                    )
                    product_id = hashlib.md5(unique_string.encode()).hexdigest()[:16]

                # Check if movie already exists
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
                    # Get current price from latest price history
                    current_price_result = await session.execute(
                        select(PriceHistory.price)
                        .where(PriceHistory.movie_id == existing_movie.id)
                        .order_by(PriceHistory.checked_at.desc())  # type: ignore
                        .limit(1)
                    )
                    current_price = current_price_result.scalar_one_or_none()

                    # Update existing movie
                    existing_movie.image_url = movie.image_url or existing_movie.image_url
                    existing_movie.last_updated = dt.now(UTC)

                    # Add price history if price changed
                    if current_price is None or current_price != movie.price:
                        if existing_movie.id is not None:
                            price_history = PriceHistory(
                                movie_id=existing_movie.id,
                                product_id=existing_movie.product_id,
                                price=movie.price,
                                availability=movie.availability,
                                checked_at=dt.now(UTC),
                            )
                            session.add(price_history)
                else:
                    # Create new movie
                    sql_movie = SQLMovie(
                        title=movie.title,
                        url=movie.url,
                        image_url=movie.image_url,
                        format=movie.format,
                        product_id=product_id,
                        last_updated=dt.now(UTC),
                        production_year=movie.production_year,
                    )
                    session.add(sql_movie)
                    await session.flush()  # Get the ID

                    # Add initial price history
                    if sql_movie.id is not None:
                        price_history = PriceHistory(
                            movie_id=sql_movie.id,
                            product_id=product_id,
                            price=movie.price,
                            availability=movie.availability,
                            checked_at=dt.now(UTC),
                        )
                        session.add(price_history)

                await session.commit()
                return True

            except Exception as e:
                await session.rollback()
                print(f"Error saving movie '{movie.title}': {e}")
                return False

    async def _get_price_alerts(self) -> list[dict]:
        """Get price alerts (simplified implementation)"""
        # For now, return empty list - this would need proper implementation
        # based on the original CDONScraper.get_price_alerts method
        return []

    async def _mark_alerts_notified(self, alert_ids: list[int]) -> None:
        """Mark alerts as notified (simplified implementation)"""
        # For now, do nothing - this would need proper implementation
        # based on the original CDONScraper.mark_alerts_notified method
        _ = alert_ids  # Silence unused parameter warning
        pass
