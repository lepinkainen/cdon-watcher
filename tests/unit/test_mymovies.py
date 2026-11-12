"""MyMovies crawl, search and parser tests against saved responses. No network."""

import gzip
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlmodel import Session, select

from shelfwatch.catalog.db import open_catalog
from shelfwatch.catalog.importer import import_run
from shelfwatch.catalog.models import StoreProduct
from shelfwatch.ingestion.archive import RawArchive
from shelfwatch.ingestion.contract import Availability, Condition, Format
from shelfwatch.ingestion.crawler import Crawler, Response
from shelfwatch.ingestion.mymovies import (
    AJAX_URL,
    USER_AGENT,
    MyMoviesAdapter,
    MyMoviesFetcher,
    form_fields,
    page_url,
    parse_url,
)
from shelfwatch.ingestion.mymovies_parser import MyMoviesParser
from shelfwatch.ingestion.parse import parse_run
from shelfwatch.ingestion.search import MyMoviesSearchAdapter, make_search_adapter

FIXTURES = Path(__file__).parents[1] / "fixtures" / "mymovies"
START = MyMoviesAdapter.start_url
BLOCKED = b"<html><body>Access to this resource on the server is denied!</body></html>"


def fixture(name):
    return gzip.decompress((FIXTURES / f"{name}.json.gz").read_bytes())


def by_id(products, product_id):
    return next(p for p in products if p.product_id == product_id)


def listing(page, pages, source="listing-page-1"):
    """A captured page's cards under a paginator for `pages` pages, `page` active."""
    data = json.loads(fixture(source))
    data["pagination"] = "".join(
        f'<button class="btn btn-sm {"btn-primary" if n == page else "btn-outline-secondary"}'
        f' sivu-linkki" data-page="{n}">{n}</button>'
        for n in range(1, pages + 1)
    )
    return json.dumps(data).encode()


def test_request_urls_carry_query_availability_and_page():
    url = page_url("The Dead Don't Die", "0")
    request = parse_url(url)
    assert (request.query, request.availability, request.page) == ("The Dead Don't Die", "0", 1)
    fields = form_fields(parse_url(page_url("", "1", 7)))
    assert ("page", "7") in fields and ("saatavuus", "1") in fields
    assert [v for k, v in fields if k == "formaatti[]"] == ["2", "3"]  # no DVD
    assert ("hakukentta", "elokuva") in fields and ("tyyppi", "3") in fields


@pytest.mark.parametrize(
    "url",
    [
        "https://mymovies.fi/tuotteet.php?q=&saatavuus=1",
        "https://www.mymovies.fi/tuotetiedot.php?id=1",
        "https://www.mymovies.fi/tuotteet.php?q=&saatavuus=2",
        "https://www.mymovies.fi/tuotteet.php?q=&saatavuus=1&sort=x",
        "https://www.mymovies.fi/tuotteet.php?q=&saatavuus=1&page=0",
    ],
)
def test_parse_url_rejects_other_urls(url):
    with pytest.raises(ValueError):
        parse_url(url)


def test_fetcher_posts_the_form_as_a_desktop_browser():
    fetcher = MyMoviesFetcher()
    try:
        fetcher.session.post = Mock(return_value=Mock(status_code=200, content=b"{}"))
        url = page_url("Looper", "0")
        response = fetcher(url)
        assert (response.final_url, response.status, response.body) == (url, 200, b"{}")
        assert fetcher.session.headers["User-Agent"] == USER_AGENT
        args, kwargs = fetcher.session.post.call_args
        assert args == (AJAX_URL,)
        assert kwargs["allow_redirects"] is False
        assert ("q", (None, "Looper")) in kwargs["files"]
    finally:
        fetcher.close()


def test_search_results_split_into_one_product_per_condition():
    products, errors = MyMoviesParser().parse_search(fixture("search-looper-all-formats"))
    assert errors == []
    uhd_new, uhd_used = by_id(products, "36119:new"), by_id(products, "36119:used")
    assert (uhd_new.format, uhd_new.condition, uhd_new.price_cents) == (
        Format.UHD,
        Condition.NEW,
        3000,
    )
    assert uhd_new.availability is Availability.IN_STOCK
    assert (uhd_used.price_cents, uhd_used.availability) == (1500, Availability.OUT_OF_STOCK)
    assert uhd_new.edition_note == "Kiinteä hinta"
    url = "https://www.mymovies.fi/tuotetiedot.php?id=36119"
    assert uhd_new.edition_url == uhd_used.edition_url == url
    assert (uhd_new.cleaned_title, uhd_new.release_year) == ("Looper", 2012)

    bd_used = by_id(products, "14092:used")
    assert (bd_used.format, bd_used.price_cents, bd_used.availability) == (
        Format.BLURAY,
        800,
        Availability.IN_STOCK,
    )
    assert bd_used.edition_note is None
    dvd = by_id(products, "4836:used")
    assert dvd.format is Format.DVD and not dvd.eligible


def test_a_dash_price_means_the_condition_is_not_offered():
    products, _ = MyMoviesParser().parse_search(fixture("search-looper-all-formats"))
    ids = {p.product_id for p in products}
    assert "22281:used" in ids and "22281:new" not in ids


def test_empty_and_blocked_searches():
    parser = MyMoviesParser()
    assert parser.parse_search(fixture("search-no-match")) == ([], [])
    products, errors = parser.parse_search(BLOCKED)
    assert products == [] and errors[0].product_id is None

    adapter = MyMoviesSearchAdapter()
    url = adapter.search_url("zzqxnotamovie")
    assert adapter.result_count(fixture("search-no-match"), url) == 0
    assert adapter.result_count(fixture("search-looper"), url) == 2
    with pytest.raises(ValueError):
        adapter.result_count(BLOCKED, url)
    with pytest.raises(ValueError):
        adapter.result_count(fixture("search-looper"), START)  # the crawl, not a search
    assert isinstance(make_search_adapter("mymovies"), MyMoviesSearchAdapter)


def test_listing_page_parses_every_card():
    products, errors = MyMoviesParser().parse(fixture("listing-page-1"))
    assert errors == []
    assert len({p.product_id.split(":")[0] for p in products}) == 60
    assert all(p.eligible for p in products)
    assert MyMoviesParser().parse(fixture("search-no-match"))[1][0].product_id is None


def test_adapter_discovers_every_page_from_the_paginator():
    adapter = MyMoviesAdapter()
    result = adapter.discover(fixture("listing-page-1"), START, START)
    assert len(result.products) == 60
    assert result.pages[0] == START and len(result.pages) == 50
    last = page_url("", "1", 50)
    assert adapter.discover(fixture("listing-page-50"), last, last).pages[-1] == last


@pytest.mark.parametrize(
    "body,url",
    [
        (fixture("listing-page-1"), page_url("", "1", 2)),  # active page 1 at page 2
        (fixture("search-no-match"), START),  # past the last page
        (BLOCKED, START),
        (fixture("listing-page-1"), page_url("Looper", "1")),  # a search, not the listing
        (fixture("listing-page-1"), page_url("", "0")),  # out-of-stock items too
    ],
)
def test_adapter_rejects_wrong_pages(body, url):
    with pytest.raises(ValueError):
        MyMoviesAdapter().discover(body, url, url)


def test_crawl_parse_and_import_keep_both_conditions(tmp_path):
    bodies = {START: listing(1, 2), page_url("", "1", 2): listing(2, 2, "listing-page-50")}
    run = Crawler(RawArchive(tmp_path), lambda url: Response(url, 200, bodies[url]), sleep=Mock())
    manifest = run.crawl(MyMoviesAdapter()).manifest
    assert manifest.complete and manifest.listing_count == 2

    parsed = parse_run(tmp_path, MyMoviesParser(), search=False)
    assert parsed.expire_unseen
    engine = open_catalog(tmp_path / "catalog.db")
    import_run(engine, parsed)
    with Session(engine) as session:
        rows = {p.product_id: p for p in session.exec(select(StoreProduct)).all()}
    assert len(rows) == len(parsed.products)
    avp = [r for r in rows.values() if r.edition_url.endswith("id=36834")]
    assert {r.condition for r in avp} == {"new", "used"}
