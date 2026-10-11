"""Command-line interface for CDON Watcher."""

import argparse
import asyncio
import os
import sys
from collections.abc import Coroutine
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import CONFIG


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
    from .monitoring_service import PriceMonitor

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

    raw_parser = subparsers.add_parser(
        "crawl-raw", help="Archive store responses without importing"
    )
    raw_parser.add_argument("--store", choices=["ax"], required=True)
    raw_parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    raw_parser.add_argument("--attempts", type=int, default=3)
    raw_parser.add_argument("--delay", type=float, default=2.0, help="Seconds between requests")

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

    if args.command == "crawl-raw":
        from .ingestion.archive import RawArchive, StoreBusyError
        from .ingestion.crawler import Crawler, HttpFetcher
        from .ingestion.stores import AxAdapter

        fetcher = HttpFetcher()
        try:
            crawler = Crawler(
                RawArchive(args.raw_dir), fetcher, attempts=args.attempts, delay=args.delay
            )
            run = crawler.crawl(AxAdapter())
        except (ValueError, StoreBusyError) as error:
            parser.exit(2, f"{error}\n")
        finally:
            fetcher.close()
        print(run.path / "manifest.json")
        print(f"{run.manifest.listing_count} pages, {run.manifest.product_count} eligible editions")
        if not run.manifest.complete:
            parser.exit(
                1, "Incomplete crawl; saved responses remain available for offline import.\n"
            )
    elif args.command == "crawl":
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
