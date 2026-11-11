"""The refresh command: crawl, parse, import, match for one store at a time."""

import fcntl
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .catalog.db import open_catalog
from .catalog.importer import ImportResult, import_run
from .catalog.matching import MatchResult, match_pending
from .catalog.tmdb import HttpTmdbClient
from .config import CONFIG
from .ingestion.archive import RawArchive, RunManifest, StoreBusyError
from .ingestion.ax_parser import AxParser
from .ingestion.cdon_parser import CdonParser
from .ingestion.contract import ParsedRun
from .ingestion.crawler import Crawler, HttpFetcher
from .ingestion.parse import parse_run
from .ingestion.stores import AxAdapter, CdonAdapter

logger = logging.getLogger(__name__)

STORES = ("ax", "cdon")


class RefreshBusyError(RuntimeError):
    """Another refresh for the same store is running."""


@dataclass
class RefreshReport:
    store: str
    crawl: RunManifest | None = None
    parsed: ParsedRun | None = None
    imported: ImportResult | None = None
    matched: MatchResult | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.imported is not None


def make_parser(store: str) -> Any:
    return {"ax": AxParser, "cdon": CdonParser}[store]()


def make_adapter(store: str, max_pages: int) -> Any:
    if store == "cdon":
        return CdonAdapter(max_pages=max_pages)
    return AxAdapter()


def make_fetcher(store: str) -> Any:
    if store == "cdon":
        from .ingestion.browser import BrowserFetcher

        return BrowserFetcher()
    return HttpFetcher()


@contextmanager
def refresh_lock(raw_dir: Path, store: str) -> Iterator[None]:
    """One refresh per store at a time, across processes."""
    directory = raw_dir / store
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".refresh.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RefreshBusyError(f"A refresh is already running for {store}") from error
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def refresh_store(
    store: str,
    *,
    raw_dir: Path | None = None,
    db_path: str | Path | None = None,
    max_pages: int | None = None,
    delay: float | None = None,
    attempts: int | None = None,
    tmdb_api_key: str | None = None,
    skip_crawl: bool = False,
) -> RefreshReport:
    """Run every stage for one store. Stage failures are reported, not raised.

    A failed crawl still parses and imports whatever was saved. A missing TMDB
    key skips matching. The web app keeps serving committed data throughout.
    """
    if store not in STORES:
        raise ValueError(f"Unknown store {store!r}")
    raw_dir = raw_dir or CONFIG["raw_dir"]
    db_path = db_path or CONFIG["db_path"]
    max_pages = max_pages or CONFIG["max_pages"]
    delay = delay or CONFIG["crawl_delay"]
    attempts = attempts or CONFIG["crawl_attempts"]
    tmdb_api_key = CONFIG["tmdb_api_key"] if tmdb_api_key is None else tmdb_api_key
    report = RefreshReport(store=store)

    with refresh_lock(raw_dir, store):
        run_id: int | None = None
        if not skip_crawl:
            fetcher = None
            try:
                fetcher = make_fetcher(store)
                crawler = Crawler(RawArchive(raw_dir), fetcher, attempts=attempts, delay=delay)
                run = crawler.crawl(make_adapter(store, max_pages))
                report.crawl = run.manifest
                run_id = run.manifest.run_id
                if not run.manifest.complete:
                    report.notes.append(f"Crawl incomplete: {len(run.manifest.failures)} failures")
            except StoreBusyError as error:
                report.notes.append(str(error))
                return report
            except Exception as error:  # noqa: BLE001 - stage boundary, reported not raised
                logger.exception("Crawl failed for %s", store)
                report.notes.append(f"Crawl failed: {error}")
            finally:
                if fetcher is not None:
                    fetcher.close()

        try:
            report.parsed = parse_run(raw_dir, make_parser(store), run_id)
        except FileNotFoundError as error:
            report.notes.append(f"Nothing to parse: {error}")
            return report
        if report.parsed.errors:
            report.notes.append(f"{len(report.parsed.errors)} row parse errors")

        engine = open_catalog(db_path)
        report.imported = import_run(engine, report.parsed)

        if not tmdb_api_key:
            report.notes.append("TMDB_API_KEY not set; matching skipped")
            return report
        report.matched = match_pending(engine, HttpTmdbClient(tmdb_api_key), store=store)
    return report


def refresh_all(stores: list[str] | None = None, **kwargs: Any) -> list[RefreshReport]:
    reports = []
    for store in stores or CONFIG["stores"]:
        try:
            reports.append(refresh_store(store, **kwargs))
        except RefreshBusyError as error:
            reports.append(RefreshReport(store=store, notes=[str(error)]))
    return reports


def describe(report: RefreshReport) -> str:
    parts: list[str] = []
    if report.crawl is not None:
        state = "complete" if report.crawl.complete else "incomplete"
        parts.append(
            f"crawl run {report.crawl.run_id} {state}: {report.crawl.listing_count} pages, "
            f"{report.crawl.product_count} editions"
        )
    if report.parsed is not None:
        parts.append(f"parsed {len(report.parsed.products)} products")
    if report.imported is not None:
        i = report.imported
        parts.append(
            f"imported {i.products_seen} ({i.products_created} new), "
            f"{i.observations_created} observations, {i.expired} expired"
        )
    if report.matched is not None:
        m = report.matched
        parts.append(
            f"matched {m.auto} auto + {m.reused} reused, {m.ambiguous} ambiguous, "
            f"{m.unmatched} unmatched, {m.errors} errors"
        )
    parts.extend(report.notes)
    return f"[{report.store}] " + "; ".join(parts)
