"""Refresh orchestration tests with fake fetchers. No network."""

import gzip
from pathlib import Path

import pytest

from shelfwatch import refresh
from shelfwatch.catalog.db import open_catalog
from shelfwatch.catalog.models import StoreProduct
from shelfwatch.ingestion.crawler import Response
from shelfwatch.ingestion.stores import AxAdapter, CdonAdapter

FIXTURES = Path(__file__).parents[1] / "fixtures"


def ax_page(media_filter):
    return gzip.decompress((FIXTURES / "ax" / f"offers-{media_filter}-page-1.html.gz").read_bytes())


def cdon_page(n):
    return gzip.decompress((FIXTURES / "cdon" / f"elokuvat-page-{n}.html.gz").read_bytes())


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.closed = False

    def __call__(self, url):
        body = self.pages(url)
        return Response(url, 200 if body else 503, body or b"down", rendered=True)

    def close(self):
        self.closed = True


def one_page_ax(url):
    """First page of the URL's format pass, with the paginator pointing at page 1 only."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(ax_page(AxAdapter().page_number(url)[0]), "html.parser")
    for a in soup.select(".pagination a[href]"):
        a.decompose()
    return str(soup).encode()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(refresh, "make_fetcher", lambda store: fetchers[store])
    monkeypatch.setattr(refresh.Crawler, "__init__", _no_sleep_init)
    fetchers = {
        "ax": FakeFetcher(one_page_ax),
        "cdon": FakeFetcher(lambda url: cdon_page(2 if url.endswith("=2") else 1)),
    }
    return tmp_path, fetchers


_real_init = refresh.Crawler.__init__


def _no_sleep_init(self, *args, **kwargs):
    from unittest.mock import Mock

    kwargs["sleep"] = Mock()
    _real_init(self, *args, **kwargs)


def count_products(db):
    from sqlmodel import Session, select

    with Session(open_catalog(db)) as session:
        return len(session.exec(select(StoreProduct)).all())


def test_refresh_all_runs_every_stage_and_skips_matching_without_key(env):
    tmp_path, fetchers = env
    db = tmp_path / "c.db"
    reports = refresh.refresh_all(
        ["ax", "cdon"], raw_dir=tmp_path / "raw", db_path=db, max_pages=2, tmdb_api_key=""
    )
    assert [r.store for r in reports] == ["ax", "cdon"]
    assert all(r.ok for r in reports)
    assert all(r.matched is None for r in reports)
    assert any("TMDB_API_KEY" in n for n in reports[0].notes)
    assert fetchers["ax"].closed and fetchers["cdon"].closed
    assert count_products(db) == 334 + 72  # four Äx passes: 100 + 100 + 99 + 35
    assert (tmp_path / "raw" / "cdon" / "1" / "parsed.json").exists()
    assert "imported" in refresh.describe(reports[1])


def test_parse_import_and_search_stages_log_summaries(env, caplog):
    tmp_path, _ = env
    with caplog.at_level("DEBUG", logger="shelfwatch.refresh"):
        refresh.refresh_store(
            "ax", raw_dir=tmp_path / "raw", db_path=tmp_path / "c.db", tmdb_api_key=""
        )
    assert caplog.messages == [
        "ax category run 1 parsed: 334 products, 1 row errors",
        "ax category run 1 imported: 334 products (334 new), 0 expired, 0 search hits",
        "ax: 0 wishlist searches due",
    ]


def test_incomplete_crawl_still_imports(env):
    tmp_path, fetchers = env
    fetchers["cdon"].pages = lambda url: None if url.endswith("=2") else cdon_page(1)
    report = refresh.refresh_store(
        "cdon",
        raw_dir=tmp_path / "raw",
        db_path=tmp_path / "c.db",
        max_pages=2,
        attempts=1,
        tmdb_api_key="",
    )
    assert report.crawl is not None and not report.crawl.complete
    assert report.ok and report.imported is not None
    assert report.imported.products_seen == 44
    assert any("incomplete" in n for n in report.notes)


def test_crawl_that_saves_no_run_does_not_reimport_an_old_run(env, monkeypatch):
    tmp_path, _ = env
    kwargs = dict(raw_dir=tmp_path / "raw", db_path=tmp_path / "c.db", tmdb_api_key="")
    assert refresh.refresh_store("ax", **kwargs).ok

    def no_browser(store):
        raise RuntimeError("browser failed to launch")

    monkeypatch.setattr(refresh, "make_fetcher", no_browser)
    report = refresh.refresh_store("ax", searches=False, **kwargs)
    assert not report.ok and report.crawl_failed
    assert report.crawl is None and report.parsed is None and report.imported is None
    assert any("browser failed to launch" in n for n in report.notes)


def test_aborted_crawl_imports_its_partial_run_but_fails(env):
    tmp_path, fetchers = env

    def crash_on_page_2(url):
        if url.endswith("=2"):
            raise RuntimeError("browser crashed")
        return cdon_page(1)

    fetchers["cdon"].pages = crash_on_page_2
    report = refresh.refresh_store(
        "cdon", raw_dir=tmp_path / "raw", db_path=tmp_path / "c.db", max_pages=2, tmdb_api_key=""
    )
    assert report.crawl_failed and not report.ok
    assert report.crawl is not None and report.crawl.run_id == 1
    assert report.imported is not None and report.imported.products_seen == 44


def test_skip_crawl_reprocesses_latest_run(env):
    tmp_path, _ = env
    kwargs = dict(raw_dir=tmp_path / "raw", db_path=tmp_path / "c.db", tmdb_api_key="")
    refresh.refresh_store("ax", **kwargs)
    report = refresh.refresh_store("ax", skip_crawl=True, **kwargs)
    assert report.crawl is None
    assert report.imported is not None and report.imported.observations_updated == 334


def test_nothing_to_parse_is_reported_not_raised(tmp_path):
    report = refresh.refresh_store(
        "ax", raw_dir=tmp_path / "raw", db_path=tmp_path / "c.db", skip_crawl=True, tmdb_api_key=""
    )
    assert not report.ok
    assert any("Nothing to parse" in n for n in report.notes)


def test_refresh_lock_is_per_store(tmp_path):
    with refresh.refresh_lock(tmp_path, "ax"):
        with pytest.raises(refresh.RefreshBusyError):
            with refresh.refresh_lock(tmp_path, "ax"):
                pass
        with refresh.refresh_lock(tmp_path, "cdon"):
            pass


def test_unknown_store_rejected(tmp_path):
    with pytest.raises(ValueError):
        refresh.refresh_store("nope", raw_dir=tmp_path)


def test_cli_refresh_reports(tmp_path, monkeypatch, capsys):
    from shelfwatch.cli import main

    monkeypatch.setattr(refresh, "make_fetcher", lambda store: FakeFetcher(one_page_ax))
    monkeypatch.setattr(refresh.Crawler, "__init__", _no_sleep_init)
    monkeypatch.setattr(
        "sys.argv",
        [
            "x",
            "refresh",
            "--store",
            "ax",
            "--raw-dir",
            str(tmp_path / "raw"),
            "--db",
            str(tmp_path / "c.db"),
        ],
    )
    monkeypatch.setitem(refresh.CONFIG, "tmdb_api_key", "")
    main()
    out = capsys.readouterr().out
    assert "[ax] crawl run 1 complete" in out and "imported 334 (334 new)" in out


def test_cli_refresh_search_only_skips_categories(monkeypatch, capsys):
    from shelfwatch import cli

    calls = []
    monkeypatch.setattr(cli, "refresh_all", lambda stores, **kw: calls.append((stores, kw)) or [])
    monkeypatch.setattr("sys.argv", ["x", "refresh", "--search-only"])
    cli.main()
    assert calls[0][0] is None
    assert calls[0][1]["categories"] is False and calls[0][1]["searches"] is True


def test_cli_refresh_search_only_conflicts_with_no_search(monkeypatch):
    from shelfwatch import cli

    monkeypatch.setattr("sys.argv", ["x", "refresh", "--search-only", "--no-search"])
    with pytest.raises(SystemExit):
        cli.main()


def test_adapters_and_parsers_by_store():
    assert isinstance(refresh.make_adapter("ax", 5), AxAdapter)
    assert isinstance(refresh.make_adapter("cdon", 5), CdonAdapter)
    assert refresh.make_adapter("cdon", 5).max_pages == 5
    assert refresh.make_parser("cdon").store == "cdon"


def test_a_dead_browser_on_close_does_not_mask_the_outcome(caplog):
    from shelfwatch.refresh import _LazyFetcher

    class Dead:
        def close(self):
            raise RuntimeError("Target page, context or browser has been closed")

    fetcher = _LazyFetcher("cdon")
    fetcher.fetcher = Dead()
    fetcher.close()
    assert "closing the cdon fetcher failed" in caplog.text
