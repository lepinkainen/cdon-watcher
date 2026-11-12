"""The refresh command: crawl, parse, import, match for one store at a time."""

import fcntl
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, func
from sqlmodel import Session, select

from .catalog.catalogue import CatalogueClient, HttpCatalogueClient, load_catalogue, sync_catalogue
from .catalog.db import open_catalog
from .catalog.importer import ImportResult, import_run
from .catalog.matching import MatchResult, match_pending
from .catalog.models import CrawlRun, Store, WishSearch
from .catalog.tmdb import HttpTmdbClient
from .config import CONFIG
from .ingestion.archive import RawArchive, RunManifest, StoreBusyError
from .ingestion.ax_parser import AxParser
from .ingestion.cdon_parser import CdonParser
from .ingestion.contract import SEARCH_SCOPE, ParsedRun
from .ingestion.crawler import Crawler, HttpFetcher, Response
from .ingestion.mymovies import MyMoviesAdapter, MyMoviesFetcher
from .ingestion.mymovies_parser import MyMoviesParser
from .ingestion.parse import parse_run
from .ingestion.search import Searcher, SearchTask, make_search_adapter
from .ingestion.stores import AxAdapter, CdonAdapter

logger = logging.getLogger(__name__)

STORES = ("ax", "cdon", "mymovies")


class RefreshBusyError(RuntimeError):
    """Another refresh for the same store is running."""


@dataclass
class RefreshReport:
    store: str
    crawl: RunManifest | None = None
    parsed: ParsedRun | None = None
    imported: ImportResult | None = None
    searched: RunManifest | None = None
    search_imported: ImportResult | None = None
    matched: MatchResult | None = None
    crawl_failed: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def imported_any(self) -> bool:
        return self.imported is not None or self.search_imported is not None

    @property
    def ok(self) -> bool:
        return self.imported_any and not self.crawl_failed


def make_parser(store: str) -> Any:
    return {"ax": AxParser, "cdon": CdonParser, "mymovies": MyMoviesParser}[store]()


def make_adapter(store: str, max_pages: int) -> Any:
    if store == "cdon":
        return CdonAdapter(max_pages=max_pages)
    if store == "mymovies":
        return MyMoviesAdapter()
    return AxAdapter()


def make_fetcher(store: str) -> Any:
    if store == "cdon":
        from .ingestion.browser import BrowserFetcher

        return BrowserFetcher()
    if store == "mymovies":
        return MyMoviesFetcher()
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


def search_fetch(store: str, fetcher: Any) -> Callable[[str], Response]:
    """CDON searches read the result JSON the search page loads; the others fetch directly."""
    return fetcher.search if store == "cdon" else fetcher  # type: ignore[no-any-return]


def search_tasks(
    engine: Engine,
    store: str,
    cap: int,
    *,
    min_interval_hours: float = 24.0,
    now: datetime | None = None,
) -> list[SearchTask]:
    """Wishes to search now: least recently searched first, within the daily cap.

    A wish searched successfully at this store in the last min_interval_hours is
    skipped: store prices don't move that fast. A failed search doesn't count, so
    it is retried on the next run. The cap counts search requests (fallbacks and
    retries included) archived for this store in the last 24 hours.
    """
    now = now or datetime.now(UTC).replace(tzinfo=None)
    fresh_since = now - timedelta(hours=min_interval_hours)
    with Session(engine) as session:
        wanted = load_catalogue(session).wanted
        store_row = session.exec(select(Store).where(Store.key == store)).first()
        used = 0
        last: dict[int, datetime] = {}
        fresh: set[int] = set()
        if store_row is not None:
            used = session.exec(
                select(func.coalesce(func.sum(CrawlRun.snapshot_count), 0)).where(
                    CrawlRun.store_id == store_row.id,
                    CrawlRun.scope == SEARCH_SCOPE,
                    CrawlRun.imported_at >= now - timedelta(hours=24),
                )
            ).one()
            for search in session.exec(
                select(WishSearch).where(WishSearch.store_id == store_row.id)
            ).all():
                attempted = max(t for t in (search.searched_at, search.failed_at) if t)
                last[search.tmdb_id] = attempted
                if search.searched_at is not None and search.searched_at > fresh_since:
                    fresh.add(search.tmdb_id)
    due = [w for w in wanted.values() if w.tmdb_id not in fresh]
    ordered = sorted(due, key=lambda w: (last.get(w.tmdb_id, datetime.min), w.tmdb_id))
    tasks = [SearchTask(w.tmdb_id, w.title, w.original_title) for w in ordered]
    return tasks[: max(cap - int(used), 0)]


class _LazyFetcher:
    """One fetcher (one browser for CDON) per refresh, opened on first use."""

    def __init__(self, store: str) -> None:
        self.store = store
        self.fetcher: Any = None

    def get(self) -> Any:
        if self.fetcher is None:
            self.fetcher = make_fetcher(self.store)
        return self.fetcher

    def close(self) -> None:
        if self.fetcher is not None:
            self.fetcher.close()


@dataclass
class _Settings:
    raw_dir: Path
    max_pages: int
    delay: float
    attempts: int
    search_cap: int
    search_interval_hours: float


def _crawl_stage(
    store: str, fetcher: _LazyFetcher, cfg: _Settings, report: RefreshReport
) -> int | None:
    """Crawl one store. The new run's id, or None when the crawl saved no run.

    An aborted crawl still returns its partial run so the pages it saved are
    imported, but it marks the report failed.
    """
    crawler: Crawler | None = None
    try:
        crawler = Crawler(
            RawArchive(cfg.raw_dir), fetcher.get(), attempts=cfg.attempts, delay=cfg.delay
        )
        run = crawler.crawl(make_adapter(store, cfg.max_pages))
    except StoreBusyError:
        raise
    except Exception as error:  # noqa: BLE001 - stage boundary, reported not raised
        logger.exception("Crawl failed for %s", store)
        report.notes.append(f"Crawl failed: {error}")
        report.crawl_failed = True
        partial = crawler.run if crawler is not None else None
        if partial is None:
            return None
        report.crawl = partial.manifest
        return partial.manifest.run_id
    report.crawl = run.manifest
    if not run.manifest.complete:
        report.notes.append(f"Crawl incomplete: {len(run.manifest.failures)} failures")
    return run.manifest.run_id


def _search_stage(
    store: str, engine: Engine, fetcher: _LazyFetcher, cfg: _Settings, report: RefreshReport
) -> int | None:
    tasks = search_tasks(
        engine, store, cfg.search_cap, min_interval_hours=cfg.search_interval_hours
    )
    if not tasks:
        return None
    try:
        searcher = Searcher(
            RawArchive(cfg.raw_dir),
            search_fetch(store, fetcher.get()),
            make_search_adapter(store),
            attempts=cfg.attempts,
            delay=cfg.delay,
        )
        run = searcher.search(tasks)
    except StoreBusyError:
        raise
    except Exception as error:  # noqa: BLE001 - stage boundary, reported not raised
        logger.exception("Wishlist search failed for %s", store)
        report.notes.append(f"Search failed: {error}")
        return None
    report.searched = run.manifest
    if run.manifest.failures:
        report.notes.append(f"{len(run.manifest.failures)} searches failed")
    return run.manifest.run_id


def _import(
    engine: Engine, cfg: _Settings, store: str, run_id: int | None, *, search: bool
) -> ImportResult | None:
    try:
        parsed = parse_run(cfg.raw_dir, make_parser(store), run_id, search=search)
    except FileNotFoundError:
        return None
    return import_run(engine, parsed)


def _category_stages(
    store: str,
    engine: Engine,
    fetcher: _LazyFetcher,
    cfg: _Settings,
    report: RefreshReport,
    *,
    skip_crawl: bool,
) -> None:
    run_id = None
    if not skip_crawl:
        run_id = _crawl_stage(store, fetcher, cfg, report)
        if run_id is None:
            # Parsing with no run id would pick an older, already imported run.
            return
    try:
        report.parsed = parse_run(cfg.raw_dir, make_parser(store), run_id, search=False)
    except FileNotFoundError as error:
        report.notes.append(f"Nothing to parse: {error}")
        return
    if report.parsed.errors:
        report.notes.append(f"{len(report.parsed.errors)} row parse errors")
    report.imported = import_run(engine, report.parsed)


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
    categories: bool = True,
    searches: bool = True,
    search_cap: int | None = None,
) -> RefreshReport:
    """Run every stage for one store. Stage failures are reported, not raised.

    Category crawl, parse, import; then one search per wished-for movie, parse,
    import; then matching. A failed crawl still parses and imports whatever it
    saved, but the report is not ok; a crawl that saved no run imports nothing,
    never an older run. skip_crawl reprocesses the latest saved runs without fetching. A
    missing TMDB key skips matching. The web app keeps serving committed data.
    """
    if store not in STORES:
        raise ValueError(f"Unknown store {store!r}")
    cfg = _Settings(
        raw_dir=raw_dir or CONFIG["raw_dir"],
        max_pages=max_pages or CONFIG["max_pages"],
        delay=delay or CONFIG["crawl_delay"],
        attempts=attempts or CONFIG["crawl_attempts"],
        search_cap=CONFIG["search_daily_cap"] if search_cap is None else search_cap,
        search_interval_hours=CONFIG["search_min_interval_hours"],
    )
    tmdb_api_key = CONFIG["tmdb_api_key"] if tmdb_api_key is None else tmdb_api_key
    engine = open_catalog(db_path or CONFIG["db_path"])
    report = RefreshReport(store=store)

    with refresh_lock(cfg.raw_dir, store):
        fetcher = _LazyFetcher(store)
        try:
            if categories:
                _category_stages(store, engine, fetcher, cfg, report, skip_crawl=skip_crawl)
            if searches:
                search_run = (
                    None if skip_crawl else _search_stage(store, engine, fetcher, cfg, report)
                )
                if search_run is not None or skip_crawl:
                    report.search_imported = _import(engine, cfg, store, search_run, search=True)
        except StoreBusyError as error:
            report.notes.append(str(error))
            return report
        finally:
            fetcher.close()

        if not report.imported_any:
            return report
        if not tmdb_api_key:
            report.notes.append("TMDB_API_KEY not set; matching skipped")
            return report
        report.matched = match_pending(engine, HttpTmdbClient(tmdb_api_key), store=store)
    return report


def catalogue_client() -> CatalogueClient | None:
    url = CONFIG["moviecatalog_url"]
    return HttpCatalogueClient(url) if url else None


def sync_from_catalogue(
    db_path: str | Path | None, client: CatalogueClient | None
) -> tuple[bool, str]:
    """Pull owned and wanted movies. A failure keeps the stored lists."""
    if client is None:
        return True, "MOVIECATALOG_URL not set; catalogue sync skipped"
    catalogue = sync_catalogue(open_catalog(db_path or CONFIG["db_path"]), client)
    if catalogue.last_error:
        return False, f"Catalogue sync failed, using stored lists: {catalogue.last_error}"
    return True, (f"Catalogue synced: {len(catalogue.owned)} owned, {len(catalogue.wanted)} wanted")


def refresh_all(
    stores: list[str] | None = None,
    *,
    catalogue: CatalogueClient | None = None,
    **kwargs: Any,
) -> list[RefreshReport]:
    """Sync the catalogue once, then refresh each store in turn."""
    client = catalogue if catalogue is not None else catalogue_client()
    logger.info(sync_from_catalogue(kwargs.get("db_path"), client)[1])
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
    if report.search_imported is not None:
        s = report.search_imported
        parts.append(
            f"searched {s.searches} wishes ({s.searches_failed} failed): {s.search_hits} results, "
            f"{s.hits_dropped} no longer found"
        )
    if report.matched is not None:
        m = report.matched
        parts.append(
            f"matched {m.auto} auto + {m.reused} reused + {m.searched} wished, "
            f"{m.ambiguous} ambiguous, {m.unmatched} unmatched, {m.errors} errors"
        )
    parts.extend(report.notes)
    return f"[{report.store}] " + "; ".join(parts)
