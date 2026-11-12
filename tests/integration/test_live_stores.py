"""Live shape tests against the real stores. Skip when unreachable.

Run with: task test-live
These catch site-structure drift early: an adapter that discovers nothing, a
parser that returns only errors, or a challenge page that never resolves.
"""

import pytest
import requests

from shelfwatch.ingestion.ax_parser import AxParser
from shelfwatch.ingestion.cdon_parser import CdonParser
from shelfwatch.ingestion.crawler import HttpFetcher
from shelfwatch.ingestion.mymovies import MyMoviesAdapter, MyMoviesFetcher
from shelfwatch.ingestion.mymovies_parser import MyMoviesParser
from shelfwatch.ingestion.search import (
    AxSearchAdapter,
    CdonSearchAdapter,
    MyMoviesSearchAdapter,
)
from shelfwatch.ingestion.stores import AxAdapter, CdonAdapter


def _reachable(url: str) -> None:
    try:
        requests.get(url, timeout=10)
    except requests.RequestException as error:
        pytest.skip(f"{url} unreachable: {error}")


@pytest.mark.timeout(60)
def test_ax_first_offer_page_shape():
    _reachable(AxAdapter.start_url)
    fetcher = HttpFetcher()
    try:
        response = fetcher(AxAdapter.start_url)
    finally:
        fetcher.close()
    assert response.status == 200
    listing = AxAdapter().discover(response.body, AxAdapter.start_url, response.final_url)
    assert len(listing.pages) >= 2
    assert len(listing.products) >= 5
    products, errors = AxParser().parse(response.body)
    assert len(products) >= 20
    assert len(errors) <= len(products) // 10
    assert any(p.regular_price_cents for p in products)


@pytest.mark.timeout(180)
def test_cdon_first_listing_page_shape():
    _reachable("https://cdon.fi/")
    from shelfwatch.ingestion.browser import BrowserFetcher

    fetcher = BrowserFetcher()
    try:
        response = fetcher(CdonAdapter.start_url)
    finally:
        fetcher.close()
    assert response.status == 200, "Cloudflare challenge did not resolve"
    listing = CdonAdapter(max_pages=1).discover(
        response.body, CdonAdapter.start_url, response.final_url
    )
    assert len(listing.products) >= 10
    products, errors = CdonParser().parse(response.body)
    assert len(products) >= 30
    assert errors == []
    assert any(p.format.value == "4k" for p in products)


@pytest.mark.timeout(60)
def test_ax_search_page_shape():
    adapter = AxSearchAdapter()
    url = adapter.search_url("Oldboy")
    _reachable(url)
    fetcher = HttpFetcher()
    try:
        response = fetcher(url)
    finally:
        fetcher.close()
    assert response.status == 200
    assert adapter.result_count(response.body, response.final_url) >= 3
    products, errors = AxParser().parse_search(response.body)
    assert errors == []
    assert any(p.eligible and "oldboy" in p.raw_title.lower() for p in products)


@pytest.mark.timeout(180)
def test_cdon_search_page_shape():
    _reachable("https://cdon.fi/")
    from shelfwatch.ingestion.browser import BrowserFetcher

    adapter = CdonSearchAdapter()
    fetcher = BrowserFetcher()
    try:
        response = fetcher.search(adapter.search_url("Oldboy"))
    finally:
        fetcher.close()
    assert response.status == 200, "Search result request did not complete"
    assert adapter.result_count(response.body, response.final_url) >= 5
    products, errors = CdonParser().parse_search(response.body)
    assert errors == []
    assert any(p.eligible and "oldboy" in p.raw_title.lower() for p in products)


@pytest.mark.timeout(60)
def test_mymovies_first_listing_page_shape():
    _reachable("https://www.mymovies.fi/")
    fetcher = MyMoviesFetcher()
    try:
        response = fetcher(MyMoviesAdapter.start_url)
    finally:
        fetcher.close()
    assert response.status == 200, "Blocked: check the User-Agent"
    start = MyMoviesAdapter.start_url
    listing = MyMoviesAdapter().discover(response.body, start, response.final_url)
    assert len(listing.pages) >= 10
    assert len(listing.products) >= 30
    products, errors = MyMoviesParser().parse(response.body)
    assert errors == []
    assert all(p.eligible for p in products)
    assert any(p.availability.value == "in_stock" for p in products)


@pytest.mark.timeout(60)
def test_mymovies_search_shape():
    _reachable("https://www.mymovies.fi/")
    adapter = MyMoviesSearchAdapter()
    url = adapter.search_url("Looper")
    fetcher = MyMoviesFetcher()
    try:
        response = fetcher(url)
    finally:
        fetcher.close()
    assert response.status == 200, "Blocked: check the User-Agent"
    assert adapter.result_count(response.body, response.final_url) >= 2
    products, errors = MyMoviesParser().parse_search(response.body)
    assert errors == []
    assert any(p.release_year == 2012 and p.cleaned_title == "Looper" for p in products)
