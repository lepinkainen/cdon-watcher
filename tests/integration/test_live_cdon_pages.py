"""Live regression tests against cdon.fi.

These tests hit the real CDON site and assert the *shape* of what comes back
from the listing crawler and product parser. They exist to catch site-level
breakage early — selector changes, anti-bot blocks, missing fields, etc.

Run with:
    PYTHONPATH=./src uv run pytest tests/integration/test_live_cdon_pages.py -v

The tests are intentionally tolerant of transient network failures (they
skip rather than fail) but strict about content shape (any structural drift
from CDON must fail loudly so the scheduler can be fixed before the daily
crawl on fly.io rots silently).
"""

from __future__ import annotations

import re

import pytest
import requests

from cdon_watcher.listing_crawler import ListingCrawler
from cdon_watcher.product_parser import ProductParser

CATEGORY_URL = "https://cdon.fi/elokuvat/"

PRODUCT_URL_PATTERN = re.compile(r"^https://cdon\.fi/tuote/[^/]+-[a-f0-9]{16}/$")
VALID_FORMATS = {"Blu-ray", "4K Blu-ray"}


def _skip_if_unreachable() -> None:
    """Skip the test if cdon.fi is unreachable from the runner."""
    try:
        resp = requests.get("https://cdon.fi", timeout=10)
    except requests.RequestException as exc:
        pytest.skip(f"cdon.fi unreachable: {exc}")
    if resp.status_code >= 500:
        pytest.skip(f"cdon.fi returned {resp.status_code}")


@pytest.fixture(autouse=True)
def _network_guard() -> None:
    _skip_if_unreachable()


class TestLiveListingPages:
    """Validates the shape of category listing pages on cdon.fi."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(120)
    @pytest.mark.parametrize(
        "format_filter", ["blu-ray", "4k"], ids=["bluray", "ultra-hd"]
    )
    async def test_listing_page_shape(
        self, listing_crawler: ListingCrawler, format_filter: str
    ) -> None:
        """Listing page must yield a healthy batch of well-formed product URLs."""
        urls = await listing_crawler.crawl_category(
            CATEGORY_URL, max_pages=1, format_filter=format_filter
        )

        assert isinstance(urls, list)
        assert len(urls) >= 5, (
            f"{format_filter} filter returned only {len(urls)} URLs on page 1 — "
            "selector drift, block, or filter regex too strict?"
        )

        # All URLs must match the canonical product URL pattern.
        bad = [u for u in urls if not PRODUCT_URL_PATTERN.match(u)]
        assert not bad, f"{format_filter}: malformed product URLs: {bad[:3]}"

        # No duplicates within a single page.
        assert len(set(urls)) == len(urls), f"{format_filter}: duplicate URLs in listing"

    @pytest.mark.asyncio
    @pytest.mark.timeout(180)
    async def test_pagination_increases_url_count(
        self, listing_crawler: ListingCrawler
    ) -> None:
        """Two pages must yield strictly more URLs than one."""
        one = await listing_crawler.crawl_category(CATEGORY_URL, max_pages=1)
        two = await listing_crawler.crawl_category(CATEGORY_URL, max_pages=2)

        assert len(two) > len(one), (
            "Pagination produced no new URLs — page 2 may not be loading "
            f"(page1={len(one)}, page2={len(two)})"
        )

    @pytest.mark.asyncio
    @pytest.mark.timeout(240)
    async def test_can_paginate_three_pages(
        self, listing_crawler: ListingCrawler
    ) -> None:
        """Crawler must navigate to at least 3 distinct pages.

        This is a regression guard for the original fly.io deployment bug:
        CDON's facet+page URL combo capped results at 15 products and the
        scheduler's `MAX_PAGES_PER_CATEGORY=10` setting was silently a no-op.
        Three pages must each contribute new product URLs to prove the
        crawler is actually navigating, not refetching page 1.
        """
        one = await listing_crawler.crawl_category(CATEGORY_URL, max_pages=1)
        three = await listing_crawler.crawl_category(CATEGORY_URL, max_pages=3)

        assert len(one) >= 10, f"Page 1 too small ({len(one)})"
        # Three pages should yield meaningfully more — allow some overlap from
        # always-shown header carousels but require concrete growth.
        assert len(three) >= len(one) + 20, (
            "3-page crawl must add at least 20 unique URLs over 1-page crawl. "
            f"page1={len(one)}, page1-3={len(three)} — pagination likely broken."
        )

        # And the 3-page set must strictly contain page 1.
        missing = set(one) - set(three)
        assert not missing, (
            f"3-page crawl is missing {len(missing)} URLs from page 1 — "
            "likely a session/cookie state regression."
        )


class TestLiveProductPages:
    """Validates the shape of individual product pages on cdon.fi."""

    @pytest.mark.timeout(60)
    @pytest.mark.parametrize(
        "product_url",
        [
            "https://cdon.fi/tuote/breaking-bad-complete-box-kausi-1-5-blu-ray-e91bc5deded24435/",
            "https://cdon.fi/tuote/house-of-the-dragon-kausi-2-blu-ray-06077e495a0a59db/",
            "https://cdon.fi/tuote/indiana-jones-4-movie-collection-blu-ray-5-disc-e5a58c8cee5e590e/",
        ],
    )
    def test_product_page_fields(
        self, product_parser: ProductParser, product_url: str
    ) -> None:
        """Each known-stable product page parses into a fully populated Movie."""
        movie = product_parser.parse_product_page(product_url)

        if movie is None:
            pytest.skip(f"Parser returned None for {product_url} (transient or removed item)")

        assert movie.title and len(movie.title) >= 2, f"Empty/short title for {product_url}"
        # Title should not contain promotional banner text observed historically.
        assert "vihdoin arki" not in movie.title.lower(), (
            f"Promo text leaked into title: {movie.title!r}"
        )

        assert movie.url == product_url
        assert movie.format in VALID_FORMATS, f"Unknown format {movie.format!r}"
        assert isinstance(movie.price, float), "Price must be numeric"
        assert 0.5 <= movie.price <= 1000.0, f"Price out of expected range: {movie.price}"

        assert movie.availability, "Availability string must be set"

        if movie.image_url is not None:
            assert movie.image_url.startswith(("http://", "https://")), (
                f"Bad image_url scheme: {movie.image_url}"
            )

        if movie.production_year is not None:
            assert 1900 <= movie.production_year <= 2030

    @pytest.mark.timeout(60)
    def test_invalid_product_url_returns_none(self, product_parser: ProductParser) -> None:
        """Parser returns None (not raises) for a URL that 404s on cdon.fi."""
        url = "https://cdon.fi/tuote/this-product-does-not-exist-0000000000000000/"
        movie = product_parser.parse_product_page(url)
        assert movie is None


class TestLiveEndToEnd:
    """Cross-component check: listing -> product parse on a fresh URL."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(180)
    async def test_listing_to_product_pipeline(
        self, listing_crawler: ListingCrawler, product_parser: ProductParser
    ) -> None:
        """Pick a random URL from today's listing and parse it end-to-end."""
        urls = await listing_crawler.crawl_category(
            CATEGORY_URL, max_pages=1, format_filter="blu-ray"
        )
        assert urls, "Listing crawler returned no URLs"

        # Try up to 3 URLs to cope with any single-product transient failure.
        last_error: str | None = None
        for url in urls[:3]:
            movie = product_parser.parse_product_page(url)
            if movie is None:
                last_error = f"None for {url}"
                continue

            assert movie.title
            assert movie.format in VALID_FORMATS
            assert movie.price > 0
            return  # Success on at least one URL — pipeline healthy.

        pytest.fail(f"All sampled product URLs failed to parse. Last: {last_error}")
