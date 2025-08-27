"""Price monitoring service for CDON Watcher."""

import asyncio
import sqlite3

from .cdon_scraper_v2 import CDONScraper
from .notifications import NotificationService


class PriceMonitor:
    """Monitor prices and send notifications."""

    def __init__(self, scraper: CDONScraper):
        self.scraper = scraper
        self.db_path = scraper.db_path
        self.notification_service = NotificationService()

    async def check_watchlist_prices(self) -> None:
        """Check prices for all watchlist items."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get all watchlist items with their URLs
        cursor.execute("""
            SELECT w.*, m.url, m.title
            FROM watchlist w
            JOIN movies m ON w.movie_id = m.id
        """)

        watchlist_items = cursor.fetchall()
        conn.close()

        if not watchlist_items:
            print("No items in watchlist")
            return

        print(f"Checking {len(watchlist_items)} watchlist items...")

        # Check each item using the product parser
        for item in watchlist_items:
            movie_id, _, target_price, _, _, url, title = item
            print(f"Checking: {title}")

            try:
                # Parse the specific product page
                movie = self.scraper.product_parser.parse_product_page(url)
                if movie:
                    self.scraper.save_movies([movie])

                # Small delay between requests
                await asyncio.sleep(2)

            except Exception as e:
                print(f"Error checking {title}: {e}")

        # No browser to close in new hybrid approach

        # Get and process alerts
        alerts = self.scraper.get_price_alerts()
        if alerts:
            await self.notification_service.send_notifications(alerts)
            self.scraper.mark_alerts_notified([a["id"] for a in alerts])
