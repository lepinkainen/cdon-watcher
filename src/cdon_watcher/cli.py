"""Command-line interface for CDON Watcher."""

import argparse
import asyncio
import os
from datetime import datetime

from .cdon_scraper import CDONScraper
from .config import CONFIG
from .monitoring_service import PriceMonitor
from .web.app import create_app


async def run_crawl(max_pages: int) -> None:
    """Run initial crawl of CDON categories."""
    print("Starting initial crawl...")
    scraper = CDONScraper(CONFIG["db_path"])

    # Crawl Blu-ray category
    await scraper.crawl_category(
        "https://cdon.fi/elokuvat/?facets=property_preset_media_format%3Ablu-ray&q=",
        max_pages=max_pages,
    )

    # Crawl 4K Ultra HD category
    await scraper.crawl_category(
        "https://cdon.fi/elokuvat/?facets=property_preset_media_format%3A4k%20ultra%20hd&q=",
        max_pages=max_pages,
    )

    print("Crawl complete!")


async def run_monitor() -> None:
    """Run the price monitoring service."""
    print("Starting price monitor...")
    scraper = CDONScraper(CONFIG["db_path"])
    monitor = PriceMonitor(scraper)

    while True:
        print(f"\n🔄 Starting price check at {datetime.now()}")
        await monitor.check_watchlist_prices()

        print(f"✅ Check complete. Next check in {CONFIG['check_interval_hours']} hours")
        await asyncio.sleep(CONFIG["check_interval_hours"] * 3600)


def run_web() -> None:
    """Run the web dashboard."""
    print(f"Starting web dashboard on http://{CONFIG['flask_host']}:{CONFIG['flask_port']}")
    app = create_app()
    app.run(host=CONFIG["flask_host"], port=CONFIG["flask_port"], debug=CONFIG["flask_debug"])


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="CDON Blu-ray Price Tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Crawl command
    crawl_parser = subparsers.add_parser("crawl", help="Initial crawl of CDON")
    crawl_parser.add_argument(
        "--max-pages",
        type=int,
        default=int(os.environ.get("MAX_PAGES_PER_CATEGORY", 10)),
        help="Maximum pages to crawl per category (default: 10)",
    )

    # Monitor command
    subparsers.add_parser("monitor", help="Run price monitor (checks periodically)")

    # Web command
    subparsers.add_parser("web", help="Start web dashboard")

    args = parser.parse_args()

    if args.command == "crawl":
        asyncio.run(run_crawl(args.max_pages))
    elif args.command == "monitor":
        asyncio.run(run_monitor())
    elif args.command == "web":
        run_web()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
