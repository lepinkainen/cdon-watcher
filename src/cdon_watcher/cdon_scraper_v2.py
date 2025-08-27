"""
Hybrid CDON scraper combining listing crawler (Playwright) and product parser (pure Python)
"""

import asyncio
import logging
import os
import sqlite3
from typing import Any

from .listing_crawler import ListingCrawler
from .product_parser import Movie, ProductParser

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class CDONScraper:
    """Hybrid scraper combining listing crawler and product parser"""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path: str = (
            db_path if db_path is not None else os.environ.get("DB_PATH", "cdon_movies.db")
        )
        self.listing_crawler = ListingCrawler()
        self.product_parser = ProductParser()
        self.init_database()

    def init_database(self) -> None:
        """Initialize SQLite database with required tables (keep existing logic)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Movies table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT UNIQUE,
                title TEXT NOT NULL,
                format TEXT,
                url TEXT,
                image_url TEXT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Price history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                movie_id INTEGER,
                product_id TEXT,
                price REAL,
                availability TEXT,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (movie_id) REFERENCES movies (id)
            )
        """)

        # Watchlist table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                movie_id INTEGER,
                product_id TEXT,
                target_price REAL,
                notify_on_availability BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (movie_id) REFERENCES movies (id)
            )
        """)

        # Price alerts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS price_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                movie_id INTEGER,
                product_id TEXT,
                old_price REAL,
                new_price REAL,
                alert_type TEXT,  -- 'price_drop', 'back_in_stock', 'target_reached'
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notified BOOLEAN DEFAULT 0,
                FOREIGN KEY (movie_id) REFERENCES movies (id)
            )
        """)

        # Ignored movies table for cheapest views
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ignored_movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                movie_id INTEGER UNIQUE,
                product_id TEXT UNIQUE,
                ignored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (movie_id) REFERENCES movies (id)
            )
        """)

        # Create indexes for better performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_movies_product_id ON movies(product_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_product_id ON watchlist(product_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_history_product_id ON price_history(product_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_alerts_product_id ON price_alerts(product_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ignored_movies_product_id ON ignored_movies(product_id)")

        conn.commit()
        conn.close()
        logger.info(f"Database initialized at {self.db_path}")


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
                    if self.save_single_movie(movie):
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

    def save_single_movie(self, movie: Movie) -> bool:
        """Save a single movie to database and return success status"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Insert or update movie
            cursor.execute(
                """
                INSERT OR IGNORE INTO movies (product_id, title, format, url, image_url)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    movie.product_id,
                    movie.title,
                    movie.format,
                    movie.url,
                    movie.image_url,
                ),
            )

            # Get movie ID
            if movie.product_id:
                cursor.execute(
                    "SELECT id FROM movies WHERE product_id = ?",
                    (movie.product_id,),
                )
            else:
                cursor.execute(
                    "SELECT id FROM movies WHERE title = ? AND format = ?",
                    (movie.title, movie.format),
                )

            movie_id = cursor.fetchone()
            if movie_id:
                movie_id = movie_id[0]

                # Update last_updated timestamp
                cursor.execute(
                    "UPDATE movies SET last_updated = CURRENT_TIMESTAMP WHERE id = ?",
                    (movie_id,),
                )

                # Insert price history
                cursor.execute(
                    """
                    INSERT INTO price_history (movie_id, product_id, price, availability)
                    VALUES (?, ?, ?, ?)
                """,
                    (
                        movie_id,
                        movie.product_id,
                        movie.price,
                        movie.availability,
                    ),
                )

                # Check for price drops
                self.check_price_alerts(cursor, movie_id, movie.price)

                conn.commit()
                logger.debug(f"✓ Saved: {movie.title} - €{movie.price}")
                return True
            else:
                logger.warning(f"Could not find movie ID after insert for: {movie.title}")
                return False

        except Exception as e:
            logger.error(f"Error saving movie {movie.title}: {e}")
            return False
        finally:
            conn.close()

    def save_movies(self, movies: list[Movie]) -> None:
        """Save movies to database (keep existing logic)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        for movie in movies:
            try:
                # Insert or update movie
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO movies (product_id, title, format, url, image_url)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (
                        movie.product_id,
                        movie.title,
                        movie.format,
                        movie.url,
                        movie.image_url,
                    ),
                )

                # Get movie ID
                if movie.product_id:
                    cursor.execute(
                        "SELECT id FROM movies WHERE product_id = ?",
                        (movie.product_id,),
                    )
                else:
                    cursor.execute(
                        "SELECT id FROM movies WHERE title = ? AND format = ?",
                        (movie.title, movie.format),
                    )

                movie_id = cursor.fetchone()
                if movie_id:
                    movie_id = movie_id[0]

                    # Update last_updated timestamp
                    cursor.execute(
                        "UPDATE movies SET last_updated = CURRENT_TIMESTAMP WHERE id = ?",
                        (movie_id,),
                    )

                    # Insert price history
                    cursor.execute(
                        """
                        INSERT INTO price_history (movie_id, product_id, price, availability)
                        VALUES (?, ?, ?, ?)
                    """,
                        (
                            movie_id,
                            movie.product_id,
                            movie.price,
                            movie.availability,
                        ),
                    )

                    # Check for price drops
                    self.check_price_alerts(cursor, movie_id, movie.price)

            except Exception as e:
                logger.error(f"Error saving movie {movie.title}: {e}")

        conn.commit()
        conn.close()
        logger.info(f"Saved {len(movies)} movies to database")

    def check_price_alerts(self, cursor: Any, movie_id: int, new_price: float) -> None:
        """Check if price has dropped and create alerts (keep existing logic)"""
        # Get last price
        cursor.execute(
            """
            SELECT price FROM price_history
            WHERE movie_id = ?
            ORDER BY checked_at DESC
            LIMIT 2
        """,
            (movie_id,),
        )

        prices = cursor.fetchall()
        if len(prices) >= 2:
            old_price = prices[1][0]
            if new_price < old_price:
                # Price dropped!
                cursor.execute(
                    """
                    INSERT INTO price_alerts (movie_id, old_price, new_price, alert_type)
                    VALUES (?, ?, ?, 'price_drop')
                """,
                    (movie_id, old_price, new_price),
                )
                logger.info(
                    f"Price drop detected for movie {movie_id}: €{old_price} -> €{new_price}"
                )

        # Check watchlist targets
        cursor.execute("SELECT target_price FROM watchlist WHERE movie_id = ?", (movie_id,))
        watchlist = cursor.fetchone()
        if watchlist and new_price <= watchlist[0]:
            cursor.execute(
                """
                INSERT INTO price_alerts (movie_id, old_price, new_price, alert_type)
                VALUES (?, ?, ?, 'target_reached')
            """,
                (movie_id, new_price, new_price),
            )
            logger.info(f"Target price reached for movie {movie_id}: €{new_price}")

    def add_to_watchlist(self, title: str, target_price: float) -> bool:
        """Add a movie to the watchlist (keep existing logic)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Find movie
        cursor.execute("SELECT id FROM movies WHERE title LIKE ?", (f"%{title}%",))
        movie = cursor.fetchone()

        if movie:
            movie_id = movie[0]
            cursor.execute(
                """
                INSERT OR REPLACE INTO watchlist (movie_id, target_price)
                VALUES (?, ?)
            """,
                (movie_id, target_price),
            )
            conn.commit()
            conn.close()
            logger.info(f"Added movie {movie_id} to watchlist with target price €{target_price}")
            return True

        conn.close()
        logger.warning(f"Movie '{title}' not found in database")
        return False

    def get_price_alerts(self) -> list[dict]:
        """Get unnotified price alerts (keep existing logic)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT a.*, m.title, m.url
            FROM price_alerts a
            JOIN movies m ON a.movie_id = m.id
            WHERE a.notified = 0
            ORDER BY a.created_at DESC
        """)

        alerts = []
        for row in cursor.fetchall():
            alerts.append(
                {
                    "id": row[0],
                    "movie_id": row[1],
                    "old_price": row[2],
                    "new_price": row[3],
                    "alert_type": row[4],
                    "created_at": row[5],
                    "title": row[7],
                    "url": row[8],
                }
            )

        conn.close()
        return alerts

    def mark_alerts_notified(self, alert_ids: list[int]) -> None:
        """Mark alerts as notified (keep existing logic)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        for alert_id in alert_ids:
            cursor.execute("UPDATE price_alerts SET notified = 1 WHERE id = ?", (alert_id,))

        conn.commit()
        conn.close()

    def search_movies(self, query: str) -> list[dict]:
        """Search for movies in the database (keep existing logic)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT m.*,
                   (SELECT price FROM price_history WHERE movie_id = m.id ORDER BY checked_at DESC LIMIT 1) as current_price,
                   (SELECT MIN(price) FROM price_history WHERE movie_id = m.id) as lowest_price,
                   (SELECT MAX(price) FROM price_history WHERE movie_id = m.id) as highest_price
            FROM movies m
            WHERE m.title LIKE ?
            ORDER BY m.last_updated DESC
        """,
            (f"%{query}%",),
        )

        movies = []
        for row in cursor.fetchall():
            movies.append(
                {
                    "id": row[0],
                    "product_id": row[1],
                    "title": row[2],
                    "format": row[3],
                    "url": row[4],
                    "current_price": row[8],
                    "lowest_price": row[9],
                    "highest_price": row[10],
                }
            )

        conn.close()
        return movies

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
    recent_movies = scraper.search_movies("")[:5]  # Get last 5 movies
    if recent_movies:
        print("\nRecent movies added to database:")
        for movie in recent_movies:
            print(f"- {movie['title']} - €{movie['current_price']} ({movie['format']})")
    else:
        print("\nNo movies found in database")

    scraper.close()


if __name__ == "__main__":
    asyncio.run(main())
