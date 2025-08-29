"""Price monitoring service for CDON Watcher."""

import asyncio

from sqlmodel import select

from .cdon_scraper import CDONScraper
from .database.connection import AsyncSessionLocal
from .models import Movie, Watchlist
from .notifications import NotificationService


class PriceMonitor:
    """Monitor prices and send notifications."""

    def __init__(self, scraper: CDONScraper):
        self.scraper = scraper
        self.notification_service = NotificationService()

    async def check_watchlist_prices(self) -> None:
        """Check prices for all watchlist items using SQLModel."""
        async with AsyncSessionLocal() as session:
            # Get all watchlist items with their URLs
            query = select(Watchlist, Movie.url, Movie.title).join(
                Movie,
                Watchlist.movie_id == Movie.id,  # type: ignore
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
                movie = self.scraper.product_parser.parse_product_page(url)
                if movie:
                    await self.scraper.save_single_movie(movie)

                # Small delay between requests
                await asyncio.sleep(2)

            except Exception as e:
                print(f"Error checking {title}: {e}")

        # Get and process alerts
        alerts = await self.scraper.get_price_alerts()
        if alerts:
            await self.notification_service.send_notifications(alerts)
            await self.scraper.mark_alerts_notified([a["id"] for a in alerts])
