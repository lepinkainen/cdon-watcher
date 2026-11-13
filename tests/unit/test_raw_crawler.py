"""Archive and discovery tests use saved responses, never the network."""

import gzip
import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from shelfwatch.ingestion.archive import RawArchive, RunManifest, StoreBusyError
from shelfwatch.ingestion.browser import BrowserFetcher
from shelfwatch.ingestion.crawler import Crawler, FetchError, HttpFetcher, Response
from shelfwatch.ingestion.stores import AxAdapter

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ax"
URL = AxAdapter().page_url("blu", 1)


def page_url(page, media_filter="blu"):
    return AxAdapter().page_url(media_filter, page)


def fixture(name="page-1"):
    return gzip.decompress((FIXTURES / f"offers-{name}.html.gz").read_bytes())


def small_page(page=1, pages=1, product_id="1120921", media="2 Blu-ray", media_filter="blu"):
    """Reduce a captured page to one real row with controlled pagination."""
    soup = BeautifulSoup(fixture("blu-page-1"), "html.parser")
    row = soup.select_one("li.hproduct")
    row["id"] = f"p-{product_id}"
    row.select_one("a.fn")["href"] = f"/movie/example/#{product_id}"
    row.select_one("span.type").string = media
    return (
        f'<h1>{AxAdapter.passes[media_filter]}</h1><ul class="list-products">'
        + str(row)
        + f'</ul><ul class="pagination"><li class="active"><span>{page}</span></li>'
        + f'<li><a href="./?p2={pages}&amp;f2={media_filter}&amp;o2=p">{pages}</a></li></ul>'
    ).encode()


def first_page_of_pass(url):
    """A one-page listing for any format pass, with a product id unique to the pass."""
    product_id = str(1 + AxAdapter().start_urls.index(url))
    return small_page(product_id=product_id, media_filter=AxAdapter().page_number(url)[0])


def blu_only(max_pages=10):
    """An adapter that crawls only the Blu-ray pass, so tests control every response."""
    adapter = AxAdapter(max_pages)
    adapter.start_urls = adapter.start_urls[:1]
    return adapter


def crawler(tmp_path, fetch, **kwargs):
    return Crawler(RawArchive(tmp_path), fetch, sleep=Mock(), **kwargs)


def test_captured_pagination_is_capped_per_format_pass():
    body = fixture("blu-page-1")
    listing = AxAdapter().discover(body, URL, URL)
    assert listing.pages == [page_url(n) for n in range(1, 11)]
    assert AxAdapter(200).discover(body, URL, URL).pages[-1] == page_url(181)
    assert len(listing.products) == 100
    assert all(
        p.edition_url.startswith("https://www.levykauppax.fi/movie/") for p in listing.products
    )
    single = page_url(1, "blusb")
    steelbooks = AxAdapter().discover(fixture("blusb-page-1"), single, single)
    assert steelbooks.pages == [single]
    assert len(steelbooks.products) == 35


def test_four_cheapest_first_format_passes():
    assert AxAdapter().start_urls == tuple(
        f"https://www.levykauppax.fi/leffat/offer/?f2={f}&o2=p"
        for f in ("blu", "uhd", "ultrasb", "blusb")
    )
    assert page_url(3, "uhd") == "https://www.levykauppax.fi/leffat/offer/?p2=3&f2=uhd&o2=p"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.levykauppax.fi/leffat/offer/",
        "https://www.levykauppax.fi/leffat/offer/?p2=2",
        "https://www.levykauppax.fi/leffat/offer/?f2=dvd&o2=p",
        "https://www.levykauppax.fi/leffat/offer/?f2=blu",
        "https://www.levykauppax.fi/leffat/offer/?f2=blu&o2=p&pr2=0-10",
        "https://www.levykauppax.fi/leffat/offer/?f2=blu&f2=uhd&o2=p",
    ],
)
def test_unfiltered_or_unexpected_listing_urls_are_rejected(url):
    with pytest.raises(ValueError):
        AxAdapter().page_number(url)


def test_generic_offer_heading_is_accepted_after_page_two():
    # Seen live on 2026-11-13: ?p2=3&f2=blu&o2=p is filtered and sorted but says "Tarjoukset".
    body = small_page(3, 5).replace(b"Elokuvat - Blu-Ray", b"Elokuvat - Tarjoukset")
    assert len(AxAdapter().discover(body, page_url(3), page_url(3)).products) == 1


def test_pagination_must_stay_in_its_format_pass():
    body = small_page(pages=2).replace(b"f2=blu&amp;o2=p", b"f2=uhd&amp;o2=p")
    with pytest.raises(ValueError, match="left the blu filter"):
        AxAdapter().discover(body, URL, URL)


def test_crawl_runs_every_pass_up_to_the_page_cap(tmp_path):
    fetched = []

    def fetch(url):
        fetched.append(url)
        media_filter, page = AxAdapter().page_number(url)
        product_id = str(1000 * (list(AxAdapter.passes).index(media_filter) + 1) + page)
        return Response(url, 200, small_page(page, 50, product_id, media_filter=media_filter))

    run = crawler(tmp_path, fetch).crawl(AxAdapter(max_pages=3))
    assert run.manifest.complete
    assert run.manifest.listing_count == 12
    assert fetched[:4] == list(AxAdapter().start_urls)
    assert {AxAdapter().page_number(u) for u in fetched} == {
        (f, n) for f in AxAdapter.passes for n in (1, 2, 3)
    }


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
    result = blu_only().discover(small_page(media=media), URL, URL)
    assert bool(result.products) == eligible


def test_archive_bodies_hashes_run_ids_and_polite_listing_only_fetches(tmp_path):
    bodies = {
        URL: small_page(pages=3),
        page_url(2): small_page(2, 3, "222"),
        page_url(3): small_page(3, 3, "333"),
    }
    fetch = Mock(side_effect=lambda url: Response(url, 200, bodies[url]))
    worker = crawler(tmp_path, fetch)
    run = worker.crawl(blu_only())
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
    second = worker.crawl(blu_only())
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
    run = crawler(tmp_path, fetch).crawl(blu_only())
    assert run.manifest.complete
    assert [s.status for s in run.manifest.snapshots] == [503, None, 200]
    assert [s.attempt for s in run.manifest.snapshots] == [1, 2, 3]
    assert run.manifest.snapshots[1].body_ref is None
    assert gzip.decompress((run.path / "000001.html.gz").read_bytes()) == b"unavailable"


def test_missing_page_preserves_partial_run_and_continues(tmp_path):
    def fetch(url):
        if "p2=2&" in url:
            return Response(url, 500, b"error")
        return Response(
            url, 200, small_page(3, 3, "333") if "p2=3&" in url else small_page(pages=3)
        )

    run = crawler(tmp_path, fetch, attempts=2).crawl(blu_only())
    assert not run.manifest.complete
    assert run.manifest.listing_count == 2
    assert len(run.manifest.snapshots) == 4
    assert "p2=2" in run.manifest.failures[0]


@pytest.mark.parametrize(
    "body",
    [
        b"<html>Temporary error</html>",
        b'<h1>Elokuvat - Blu-Ray</h1><ul class="list-products"></ul>',
        small_page().replace(b"Elokuvat - Blu-Ray", b"Elokuvat - 4K Ultra HD"),
        small_page().replace(b"#1120921", b"#999"),
        small_page().replace(b"./?p2=1", b"/leffat/?p2=2"),
    ],
)
def test_unrecognized_or_out_of_scope_pages_are_incomplete(tmp_path, body):
    run = crawler(tmp_path, lambda url: Response(url, 200, body), attempts=2).crawl(blu_only())
    assert not run.manifest.complete
    assert run.manifest.product_count == 0
    assert len(run.manifest.snapshots) == 2


@pytest.mark.parametrize("active_page", [1, 2])
def test_pagination_loop_detection(tmp_path, active_page):
    fetch = Mock(
        side_effect=lambda url: Response(url, 200, small_page(1 if url == URL else active_page, 2))
    )
    run = crawler(tmp_path, fetch, attempts=1).crawl(blu_only())
    assert not run.manifest.complete
    assert "Pagination loop" in run.manifest.failures[0]


def test_same_document_different_editions_preserves_fragments(tmp_path):
    body = small_page().replace(
        b"</ul><ul",
        small_page(product_id="222").split(b'<ul class="list-products">')[1].split(b"</ul>")[0]
        + b"</ul><ul",
        1,
    )
    run = crawler(tmp_path, lambda url: Response(url, 200, body)).crawl(blu_only())
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
    from shelfwatch.cli import main

    monkeypatch.setattr(
        "sys.argv", ["shelfwatch", "crawl-raw", "--store", "ax", "--raw-dir", str(tmp_path)]
    )
    monkeypatch.setattr(
        "shelfwatch.ingestion.crawler.HttpFetcher.__call__",
        lambda self, url: Response(url, 200, first_page_of_pass(url)),
    )
    main()
    assert "4 pages, 4 eligible editions" in capsys.readouterr().out
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
    from shelfwatch.cli import main

    monkeypatch.setattr(
        "sys.argv",
        [
            "shelfwatch",
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
        "shelfwatch.ingestion.crawler.HttpFetcher.__call__",
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
    run = crawler(tmp_path, fetch).crawl(blu_only())
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
    monkeypatch.setattr("shelfwatch.ingestion.browser.time.sleep", Mock())
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


def test_debug_log_per_page_and_failed_attempt(tmp_path, caplog):
    fetch = Mock(
        side_effect=[
            Response(URL, 503, b"unavailable"),
            Response(URL, 200, small_page(pages=2)),
            Response(page_url(2), 200, small_page(2, 2, "222")),
        ]
    )
    with caplog.at_level("DEBUG", logger="shelfwatch.ingestion.crawler"):
        crawler(tmp_path, fetch).crawl(blu_only())
    assert caplog.messages == [
        f"ax attempt 1/3 failed: HTTP 503 ({URL})",
        f"ax page 1: 1 products, 1 editions so far ({URL})",
        f"ax page 2: 1 products, 2 editions so far ({page_url(2)})",
    ]


@pytest.mark.parametrize(("flag", "level"), [([], "NOTSET"), (["-v"], "DEBUG")])
def test_verbose_flag_enables_debug_for_project_loggers(tmp_path, monkeypatch, flag, level):
    import logging

    from shelfwatch.cli import main

    project = logging.getLogger("shelfwatch")
    monkeypatch.setattr(project, "level", logging.NOTSET)
    monkeypatch.setattr(
        "sys.argv",
        ["shelfwatch", "crawl-raw", "--store", "ax", "--raw-dir", str(tmp_path), *flag],
    )
    monkeypatch.setattr(
        "shelfwatch.ingestion.crawler.HttpFetcher.__call__",
        lambda self, url: Response(url, 200, first_page_of_pass(url)),
    )
    main()
    assert logging.getLevelName(project.level) == level
