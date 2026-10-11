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


STORES = ("ax", "cdon")


def _store_parser(store: str) -> Any:
    from .ingestion.ax_parser import AxParser
    from .ingestion.cdon_parser import CdonParser

    return {"ax": AxParser, "cdon": CdonParser}[store]()


def _cmd_crawl_raw(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    from .ingestion.archive import RawArchive, StoreBusyError
    from .ingestion.crawler import Crawler, HttpFetcher
    from .ingestion.stores import AxAdapter, CdonAdapter

    fetcher: Any
    adapter: Any
    if args.store == "cdon":
        from .ingestion.browser import BrowserFetcher

        fetcher = BrowserFetcher()
        adapter = CdonAdapter(max_pages=args.max_pages)
    else:
        fetcher = HttpFetcher()
        adapter = AxAdapter()
    try:
        crawler = Crawler(
            RawArchive(args.raw_dir), fetcher, attempts=args.attempts, delay=args.delay
        )
        run = crawler.crawl(adapter)
    except (ValueError, StoreBusyError) as error:
        parser.exit(2, f"{error}\n")
    finally:
        fetcher.close()
    print(run.path / "manifest.json")
    print(f"{run.manifest.listing_count} pages, {run.manifest.product_count} eligible editions")
    if not run.manifest.complete:
        parser.exit(1, "Incomplete crawl; saved responses remain available for offline import.\n")


def _cmd_parse_raw(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    from .ingestion.parse import PARSED_FILENAME, parse_run

    try:
        parsed = parse_run(
            args.raw_dir, _store_parser(args.store), args.run, eligible_only=not args.all_formats
        )
    except (FileNotFoundError, ValueError) as error:
        parser.exit(2, f"{error}\n")
    print(args.raw_dir / parsed.store / str(parsed.run_id) / PARSED_FILENAME)
    print(
        f"run {parsed.run_id}: {len(parsed.products)} products, "
        f"{len(parsed.errors)} row errors, "
        f"{'complete' if parsed.complete else 'incomplete'} crawl"
    )


def _cmd_import_run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    from .catalog.db import SchemaError, open_catalog
    from .catalog.importer import import_run
    from .ingestion.parse import latest_run_id, load_parsed

    try:
        run_id = args.run if args.run is not None else latest_run_id(args.raw_dir, args.store)
        parsed = load_parsed(args.raw_dir, args.store, run_id)
    except FileNotFoundError as error:
        parser.exit(2, f"{error}\nRun parse-raw first.\n")
    try:
        engine = open_catalog(args.db or CONFIG["db_path"])
    except SchemaError as error:
        parser.exit(2, f"{error}\n")
    result = import_run(engine, parsed)
    print(
        f"run {result.run_id} ({'complete' if result.complete else 'incomplete'}): "
        f"{result.products_seen} products ({result.products_created} new), "
        f"{result.observations_created} observations added, "
        f"{result.observations_updated} updated, {result.expired} expired, "
        f"{result.errors} row errors"
    )


def _cmd_match(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    from .catalog.db import SchemaError, open_catalog
    from .catalog.matching import match_pending
    from .catalog.tmdb import HttpTmdbClient

    try:
        client = HttpTmdbClient(CONFIG["tmdb_api_key"])
        engine = open_catalog(args.db or CONFIG["db_path"])
    except (ValueError, SchemaError) as error:
        parser.exit(2, f"{error}\n")
    result = match_pending(engine, client, store=args.store, limit=args.limit)
    print(
        f"considered {result.considered}: {result.auto} auto, {result.reused} reused, "
        f"{result.ambiguous} ambiguous, {result.unmatched} unmatched, "
        f"{result.not_applicable} collections, {result.errors} errors"
    )


INGESTION_COMMANDS = {
    "crawl-raw": _cmd_crawl_raw,
    "parse-raw": _cmd_parse_raw,
    "import-run": _cmd_import_run,
    "match": _cmd_match,
}


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
    raw_parser.add_argument("--store", choices=STORES, required=True)
    raw_parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    raw_parser.add_argument("--attempts", type=int, default=3)
    raw_parser.add_argument(
        "--max-pages",
        type=int,
        default=int(os.environ.get("MAX_PAGES_PER_CATEGORY", 10)),
        help="CDON only: listing pages to fetch (default: 10)",
    )
    raw_parser.add_argument("--delay", type=float, default=2.0, help="Seconds between requests")

    parse_parser = subparsers.add_parser(
        "parse-raw", help="Parse an archived run offline, writing parsed.json next to it"
    )
    parse_parser.add_argument("--store", choices=STORES, required=True)
    parse_parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parse_parser.add_argument("--run", type=int, default=None, help="Run number (default: latest)")
    parse_parser.add_argument(
        "--all-formats", action="store_true", help="Keep DVD and unknown formats too"
    )

    import_parser = subparsers.add_parser(
        "import-run", help="Import a parsed run into the catalog database"
    )
    import_parser.add_argument("--store", choices=STORES, required=True)
    import_parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    import_parser.add_argument("--run", type=int, default=None, help="Run number (default: latest)")
    import_parser.add_argument(
        "--db", type=Path, default=None, help="Catalog SQLite path (default: DB_PATH)"
    )

    match_parser = subparsers.add_parser(
        "match", help="Match unmatched single-movie products against TMDB"
    )
    match_parser.add_argument("--store", choices=STORES, default=None)
    match_parser.add_argument("--limit", type=int, default=None)
    match_parser.add_argument(
        "--db", type=Path, default=None, help="Catalog SQLite path (default: DB_PATH)"
    )

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

    if args.command in INGESTION_COMMANDS:
        INGESTION_COMMANDS[args.command](args, parser)
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
