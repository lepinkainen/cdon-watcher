"""Live shape tests against the real stores. Skip when unreachable.

Run with: task test-live
These catch site-structure drift early: an adapter that discovers nothing, a
parser that returns only errors, or a challenge page that never resolves.
"""

import pytest
import requests

from cdon_watcher.ingestion.ax_parser import AxParser
from cdon_watcher.ingestion.cdon_parser import CdonParser
from cdon_watcher.ingestion.crawler import HttpFetcher
from cdon_watcher.ingestion.stores import AxAdapter, CdonAdapter


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
    from cdon_watcher.ingestion.browser import BrowserFetcher

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
