"""Archive and discovery tests use saved responses, never the network."""

import gzip
import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from cdon_watcher.ingestion.archive import RawArchive, RunManifest, StoreBusyError
from cdon_watcher.ingestion.browser import BrowserFetcher
from cdon_watcher.ingestion.crawler import Crawler, FetchError, HttpFetcher, Response
from cdon_watcher.ingestion.stores import AxAdapter

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ax"
URL = AxAdapter.start_url


def fixture(page=1):
    return gzip.decompress((FIXTURES / f"offers-page-{page}.html.gz").read_bytes())


def small_page(page=1, pages=1, product_id="1120921", media="2 Blu-ray"):
    """Reduce a captured page to one real row with controlled pagination."""
    soup = BeautifulSoup(fixture(), "html.parser")
    row = soup.select_one("li.hproduct")
    row["id"] = f"p-{product_id}"
    row.select_one("a.fn")["href"] = f"/movie/example/#{product_id}"
    row.select_one("span.type").string = media
    return (
        '<h1>Elokuvat - Tarjoukset</h1><ul class="list-products">'
        + str(row)
        + f'</ul><ul class="pagination"><li class="active"><span>{page}</span></li>'
        + f'<li><a href="./?p2={pages}">{pages}</a></li></ul>'
    ).encode()


def crawler(tmp_path, fetch, **kwargs):
    return Crawler(RawArchive(tmp_path), fetch, sleep=Mock(), **kwargs)


def test_captured_pagination_and_edition_scope():
    adapter = AxAdapter()
    first = adapter.discover(fixture(), URL, URL)
    last = adapter.discover(fixture(14), URL + "?p2=14", URL + "?p2=14")
    assert len(first.pages) == 14
    assert len(last.pages) == 14
    assert first.products[0].product_id == "1120921"
    assert first.products[0].edition_url.endswith(
        "/mission_impossible_the_final_reckoning/#1120921"
    )
    assert "1185326" not in {p.product_id for p in first.products}  # DVD
    assert "1149002" in {p.product_id for p in first.products}  # Combined UHD/Blu-ray


@pytest.mark.parametrize(
    "media,eligible",
    [
        ("DVD", False),
        ("4DVD", False),
        ("Blu-Ray", True),
        ("2 Blu-ray", True),
        ("4K Ultra HD", True),
        ("4K ULTRA HD + 2BLU", True),
        ("3ULTRAHD + BLU", True),
    ],
)
def test_eligible_format_discovery(media, eligible):
    result = AxAdapter().discover(small_page(media=media), URL, URL)
    assert bool(result.products) == eligible


def test_archive_bodies_hashes_run_ids_and_polite_listing_only_fetches(tmp_path):
    bodies = {
        URL: small_page(pages=3),
        URL + "?p2=2": small_page(2, 3, "222"),
        URL + "?p2=3": small_page(3, 3, "333"),
    }
    fetch = Mock(side_effect=lambda url: Response(url, 200, bodies[url]))
    worker = crawler(tmp_path, fetch)
    run = worker.crawl(AxAdapter())
    assert run.manifest.complete
    assert run.manifest.product_count == 3
    assert run.manifest.listing_count == 3
    assert [c.args[0] for c in fetch.call_args_list] == list(bodies)
    assert worker.sleep.call_count == 2
    saved = RunManifest.model_validate_json((run.path / "manifest.json").read_text())
    assert saved.finished_at is not None
    for snapshot in saved.snapshots:
        body = gzip.decompress((run.path / snapshot.body_ref).read_bytes())
        assert body == bodies[snapshot.requested_url]
        assert snapshot.sha256 == hashlib.sha256(body).hexdigest()
        assert snapshot.fetched_at.tzinfo is not None
    manifest_before = (run.path / "manifest.json").read_bytes()
    second = worker.crawl(AxAdapter())
    assert second.manifest.run_id == 2
    assert (run.path / "manifest.json").read_bytes() == manifest_before


def test_retry_archives_http_errors_and_transport_errors(tmp_path):
    fetch = Mock(
        side_effect=[
            Response(URL, 503, b"unavailable"),
            requests.Timeout("timed out"),
            Response(URL, 200, small_page()),
        ]
    )
    run = crawler(tmp_path, fetch).crawl(AxAdapter())
    assert run.manifest.complete
    assert [s.status for s in run.manifest.snapshots] == [503, None, 200]
    assert [s.attempt for s in run.manifest.snapshots] == [1, 2, 3]
    assert run.manifest.snapshots[1].body_ref is None
    assert gzip.decompress((run.path / "000001.html.gz").read_bytes()) == b"unavailable"


def test_missing_page_preserves_partial_run_and_continues(tmp_path):
    def fetch(url):
        if url.endswith("=2"):
            return Response(url, 500, b"error")
        return Response(
            url, 200, small_page(3, 3, "333") if url.endswith("=3") else small_page(pages=3)
        )

    run = crawler(tmp_path, fetch, attempts=2).crawl(AxAdapter())
    assert not run.manifest.complete
    assert run.manifest.listing_count == 2
    assert len(run.manifest.snapshots) == 4
    assert "p2=2" in run.manifest.failures[0]


@pytest.mark.parametrize(
    "body",
    [
        b"<html>Temporary error</html>",
        b'<h1>Elokuvat - Tarjoukset</h1><ul class="list-products"></ul>',
        small_page().replace(b"#1120921", b"#999"),
        small_page().replace(b"./?p2=1", b"/leffat/?p2=2"),
    ],
)
def test_unrecognized_or_out_of_scope_pages_are_incomplete(tmp_path, body):
    run = crawler(tmp_path, lambda url: Response(url, 200, body), attempts=2).crawl(AxAdapter())
    assert not run.manifest.complete
    assert run.manifest.product_count == 0
    assert len(run.manifest.snapshots) == 2


@pytest.mark.parametrize("active_page", [1, 2])
def test_pagination_loop_detection(tmp_path, active_page):
    fetch = Mock(
        side_effect=lambda url: Response(url, 200, small_page(1 if url == URL else active_page, 2))
    )
    run = crawler(tmp_path, fetch, attempts=1).crawl(AxAdapter())
    assert not run.manifest.complete
    assert "Pagination loop" in run.manifest.failures[0]


def test_same_document_different_editions_preserves_fragments(tmp_path):
    body = small_page().replace(
        b"</ul><ul",
        small_page(product_id="222").split(b'<ul class="list-products">')[1].split(b"</ul>")[0]
        + b"</ul><ul",
        1,
    )
    run = crawler(tmp_path, lambda url: Response(url, 200, body)).crawl(AxAdapter())
    assert run.manifest.complete
    assert [p.edition_url for p in run.manifest.snapshots[0].products] == [
        "https://www.levykauppax.fi/movie/example/#1120921",
        "https://www.levykauppax.fi/movie/example/#222",
    ]


def test_store_lock_and_interrupted_run(tmp_path):
    archive = RawArchive(tmp_path)
    with pytest.raises(KeyboardInterrupt), archive.start("ax", "offers") as run:
        with pytest.raises(StoreBusyError), archive.start("ax", "offers"):
            pytest.fail("Concurrent crawl acquired the same store lock")
        with archive.start("cdon", "pages"):
            pass
        raise KeyboardInterrupt
    saved = RunManifest.model_validate_json((run.path / "manifest.json").read_text())
    assert not saved.complete
    assert "KeyboardInterrupt" in saved.failures[0]
    with archive.start("ax", "offers") as next_run:
        assert next_run.manifest.run_id == 2


def test_raw_cli_does_not_start_legacy_crawl(tmp_path, monkeypatch, capsys):
    from cdon_watcher.cli import main

    monkeypatch.setattr(
        "sys.argv", ["cdon-watcher", "crawl-raw", "--store", "ax", "--raw-dir", str(tmp_path)]
    )
    monkeypatch.setattr(
        "cdon_watcher.ingestion.crawler.HttpFetcher.__call__",
        lambda self, url: Response(url, 200, small_page()),
    )
    main()
    assert "1 pages, 1 eligible editions" in capsys.readouterr().out
    assert (tmp_path / "ax" / "1" / "manifest.json").exists()


def test_http_fetcher_does_not_follow_redirects():
    fetcher = HttpFetcher()
    try:
        fetcher.session.get = Mock(return_value=Mock(url=URL, status_code=302, content=b"redirect"))
        response = fetcher(URL)
        assert response.status == 302
        fetcher.session.get.assert_called_once_with(URL, timeout=30, allow_redirects=False)
    finally:
        fetcher.close()


@pytest.mark.parametrize("attempts,delay", [(0, 2), (3, 0), (3, -1), (3, float("nan"))])
def test_invalid_request_settings(tmp_path, attempts, delay):
    with pytest.raises(ValueError):
        crawler(tmp_path, Mock(), attempts=attempts, delay=delay)


def test_raw_cli_incomplete_exit_preserves_archive(tmp_path, monkeypatch):
    from cdon_watcher.cli import main

    monkeypatch.setattr(
        "sys.argv",
        [
            "cdon-watcher",
            "crawl-raw",
            "--store",
            "ax",
            "--attempts",
            "1",
            "--raw-dir",
            str(tmp_path),
        ],
    )
    monkeypatch.setattr(
        "cdon_watcher.ingestion.crawler.HttpFetcher.__call__",
        lambda self, url: Response(url, 503, b"unavailable"),
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    saved = RunManifest.model_validate_json((tmp_path / "ax/1/manifest.json").read_text())
    assert not saved.complete
    assert saved.snapshots[0].status == 503


def test_browser_transport_errors_are_archived_and_retried(tmp_path):
    fetch = Mock(side_effect=[FetchError("Timeout 45000ms"), Response(URL, 200, small_page())])
    run = crawler(tmp_path, fetch).crawl(AxAdapter())
    assert run.manifest.complete
    assert [(s.status, s.error) for s in run.manifest.snapshots] == [
        (None, "Timeout 45000ms"),
        (200, None),
    ]


def browser(page):
    fetcher = BrowserFetcher.__new__(BrowserFetcher)
    fetcher._page = page
    fetcher.challenge_timeout, fetcher.content_timeout_ms, fetcher.settle_seconds = 5, 1, 0
    return fetcher


def test_browser_resolved_challenge_returns_final_page_as_ok(monkeypatch):
    monkeypatch.setattr("cdon_watcher.ingestion.browser.time.sleep", Mock())
    page = Mock(url=URL)
    page.goto.return_value = Mock(status=403)
    page.title.side_effect = ["Just a moment...", "Elokuvat"]
    page.content.return_value = "<html>real</html>"
    assert browser(page)(URL) == Response(URL, 200, b"<html>real</html>", True)


def test_browser_playwright_errors_become_fetch_errors():
    page = Mock()
    page.goto.side_effect = PlaywrightTimeoutError("Timeout 45000ms exceeded")
    with pytest.raises(FetchError, match="Timeout"):
        browser(page)(URL)
