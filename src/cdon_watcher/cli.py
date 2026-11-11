"""Command-line interface: ingestion stages, refresh, and the web app."""

import argparse
import logging
from pathlib import Path
from typing import Any

from .config import CONFIG
from .refresh import STORES, describe, make_adapter, make_fetcher, make_parser, refresh_all


def _cmd_crawl_raw(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    from .ingestion.archive import RawArchive, StoreBusyError
    from .ingestion.crawler import Crawler

    fetcher: Any = make_fetcher(args.store)
    try:
        crawler = Crawler(
            RawArchive(args.raw_dir), fetcher, attempts=args.attempts, delay=args.delay
        )
        run = crawler.crawl(make_adapter(args.store, args.max_pages))
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
            args.raw_dir, make_parser(args.store), args.run, eligible_only=not args.all_formats
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


def _cmd_refresh(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    reports = refresh_all(
        args.store or None,
        raw_dir=args.raw_dir,
        db_path=args.db,
        max_pages=args.max_pages,
        skip_crawl=args.skip_crawl,
    )
    failed = False
    for report in reports:
        print(describe(report))
        failed = failed or not report.ok
    if failed:
        parser.exit(1, "One or more stores did not import.\n")


def _cmd_web(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    import uvicorn

    host = CONFIG["api_host"]
    port = CONFIG["api_port"]
    print(f"Starting web app on http://{host}:{port}")
    uvicorn.run(
        "cdon_watcher.web.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=CONFIG["api_debug"],
        access_log=True,
    )


COMMANDS = {
    "crawl-raw": _cmd_crawl_raw,
    "parse-raw": _cmd_parse_raw,
    "import-run": _cmd_import_run,
    "match": _cmd_match,
    "refresh": _cmd_refresh,
    "web": _cmd_web,
}


def _add_common(sub: argparse.ArgumentParser, *, store_required: bool) -> None:
    if store_required:
        sub.add_argument("--store", choices=STORES, required=True)
    else:
        sub.add_argument("--store", choices=STORES, action="append", default=[])
    sub.add_argument("--raw-dir", type=Path, default=CONFIG["raw_dir"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Movie offer tracker (CDON + Levykauppa Äx)")
    sub = parser.add_subparsers(dest="command", help="Available commands")

    crawl = sub.add_parser("crawl-raw", help="Archive store listing responses without importing")
    _add_common(crawl, store_required=True)
    crawl.add_argument("--attempts", type=int, default=CONFIG["crawl_attempts"])
    crawl.add_argument("--delay", type=float, default=CONFIG["crawl_delay"])
    crawl.add_argument("--max-pages", type=int, default=CONFIG["max_pages"], help="CDON only")

    parse = sub.add_parser("parse-raw", help="Parse an archived run offline into parsed.json")
    _add_common(parse, store_required=True)
    parse.add_argument("--run", type=int, default=None, help="Run number (default: latest)")
    parse.add_argument("--all-formats", action="store_true", help="Keep DVD and unknown formats")

    imp = sub.add_parser("import-run", help="Import a parsed run into the catalog database")
    _add_common(imp, store_required=True)
    imp.add_argument("--run", type=int, default=None, help="Run number (default: latest)")
    imp.add_argument("--db", type=Path, default=None, help="Catalog SQLite path (default: DB_PATH)")

    match = sub.add_parser("match", help="Match unmatched single-movie products against TMDB")
    match.add_argument("--store", choices=STORES, default=None)
    match.add_argument("--limit", type=int, default=None)
    match.add_argument(
        "--db", type=Path, default=None, help="Catalog SQLite path (default: DB_PATH)"
    )

    refresh = sub.add_parser(
        "refresh", help="Crawl, parse, import and match, one store at a time (default: all)"
    )
    _add_common(refresh, store_required=False)
    refresh.add_argument("--db", type=Path, default=None)
    refresh.add_argument("--max-pages", type=int, default=None, help="CDON only")
    refresh.add_argument("--skip-crawl", action="store_true", help="Reprocess the latest run")

    sub.add_parser("web", help="Start the web app")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args()
    command = COMMANDS.get(args.command)
    if command is None:
        parser.print_help()
        return
    command(args, parser)


if __name__ == "__main__":
    main()
