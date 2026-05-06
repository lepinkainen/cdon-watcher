"""Command-line interface for CDON Watcher."""

import argparse
import asyncio
import os
import sys
from collections.abc import Coroutine
from datetime import datetime
from typing import Any

from .config import CONFIG
from .monitoring_service import PriceMonitor


def run_async_with_graceful_shutdown(coro: Coroutine[Any, Any, Any]) -> None:
    """Run an async coroutine with graceful handling of Ctrl+C."""
    try:
        asyncio.run(coro)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Shutting down...")
        sys.exit(0)


async def run_crawl(max_pages: int, scan_mode: str = "fast") -> None:
    """Run initial crawl of CDON categories."""
    print(f"Starting {scan_mode} initial crawl...")
    print(f"📄 Pages per category: {max_pages} (Total: {max_pages * 2} pages across 2 categories)")
    # Import CDONScraper only when needed for crawling
    from .cdon_scraper import CDONScraper
    from .database.connection import init_db

    # Initialize database (runs migrations for new columns)
    await init_db()

    scraper = CDONScraper()

    # CDON's facet+page combo is broken — crawl the plain category and filter
    # URLs by media-format slug client-side instead.
    await scraper.crawl_category(
        "https://cdon.fi/elokuvat/",
        max_pages=max_pages,
        scan_mode=scan_mode,
        format_filter="blu-ray",
    )

    await scraper.crawl_category(
        "https://cdon.fi/elokuvat/",
        max_pages=max_pages,
        scan_mode=scan_mode,
        format_filter="4k",
    )

    print("Crawl complete!")


async def run_monitor() -> None:
    """Run the price monitoring service."""
    from .database.connection import init_db

    # Initialize database (runs migrations for new columns)
    await init_db()

    print("Starting price monitor...")
    monitor = PriceMonitor()

    while True:
        print(f"\n🔄 Starting price check at {datetime.now()}")
        await monitor.check_watchlist_prices()

        print(f"✅ Check complete. Next check in {CONFIG['check_interval_hours']} hours")
        await asyncio.sleep(CONFIG["check_interval_hours"] * 3600)


def run_web() -> None:
    """Run the web dashboard."""
    import uvicorn

    host = CONFIG.get("api_host", "127.0.0.1")
    port = CONFIG.get("api_port", 8080)
    debug = CONFIG.get("api_debug", False)

    print(f"Starting web dashboard on http://{host}:{port}")

    # Create app factory function for Uvicorn
    uvicorn.run(
        "cdon_watcher.web.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=debug,
        access_log=True,
    )


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
    crawl_parser.add_argument(
        "--scan-mode",
        choices=["fast", "moderate", "slow"],
        default="fast",
        help="Scan mode: fast (quick), moderate (development), slow (production)",
    )

    # Update scan command
    update_parser = subparsers.add_parser(
        "update-scan", help="Development scan for quick database updates"
    )
    update_parser.add_argument(
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
        run_async_with_graceful_shutdown(run_crawl(args.max_pages, args.scan_mode))
    elif args.command == "update-scan":
        # Update scan uses moderate mode by default for development
        run_async_with_graceful_shutdown(run_crawl(args.max_pages, "moderate"))
    elif args.command == "monitor":
        run_async_with_graceful_shutdown(run_monitor())
    elif args.command == "web":
        run_web()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
