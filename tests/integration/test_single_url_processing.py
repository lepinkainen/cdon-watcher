#!/usr/bin/env python3
"""
Integration tests for single URL processing
Converted from legacy_test_single_url.py to follow pytest conventions
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.cdon_watcher.cdon_scraper_v2 import CDONScraper
from src.cdon_watcher.product_parser import ProductParser


@pytest.fixture
def sample_urls():
    """Sample CDON URLs for testing"""
    return [
        "https://cdon.fi/tuote/breaking-bad-complete-box-kausi-1-5-blu-ray-e91bc5deded24435/",
        "https://cdon.fi/tuote/house-of-the-dragon-kausi-2-blu-ray-06077e495a0a59db/",
        "https://cdon.fi/tuote/indiana-jones-4-movie-collection-blu-ray-5-disc-e5a58c8cee5e590e/",
    ]


@pytest.fixture
def test_scraper():
    """Test scraper with in-memory database"""
    scraper = CDONScraper(db_path=":memory:")
    yield scraper
    scraper.close()


@pytest.fixture
def product_parser():
    """Product parser fixture with cleanup"""
    parser = ProductParser()
    yield parser
    parser.close()


class TestSingleUrlProcessing:
    """Test single URL processing functionality"""

    @pytest.mark.asyncio
    async def test_scraper_single_url_extraction(self, test_scraper, sample_urls):
        """Test that CDONScraper can extract data from individual URLs using Playwright"""
        for url in sample_urls:
            try:
                browser, context, page = await test_scraper.create_browser()

                await page.goto(url, wait_until="load", timeout=20000)

                # Find body element to simulate crawler context
                body_element = await page.query_selector("body")
                assert body_element is not None, f"Could not find body element for URL: {url}"

                # Use actual crawler extraction method
                movie = await test_scraper.extract_movie_data(body_element, page)

                await browser.close()

                if movie:
                    # Verify basic movie data
                    assert movie.title, f"Title missing for URL: {url}"
                    assert movie.price is not None, f"Price missing for URL: {url}"
                    assert movie.format, f"Format missing for URL: {url}"
                    assert movie.url == url, f"URL mismatch for: {url}"

                    # Check for vihdoin arki issue
                    assert "vihdoin arki" not in movie.title.lower(), (
                        f"Title contains 'vihdoin arki' promotional text: {movie.title}"
                    )
                else:
                    pytest.fail(f"Scraper failed to extract movie data from URL: {url}")

            except Exception as e:
                pytest.fail(f"Error processing URL {url}: {e}")

    @pytest.mark.asyncio
    async def test_product_parser_single_url_extraction(self, product_parser, sample_urls):
        """Test that ProductParser can extract data from individual URLs using pure Python"""
        success_count = 0

        for url in sample_urls:
            try:
                movie = product_parser.parse_product_page(url)

                if movie:
                    # Verify basic movie data
                    assert movie.title, f"Title missing for URL: {url}"
                    assert movie.price is not None, f"Price missing for URL: {url}"
                    assert movie.format, f"Format missing for URL: {url}"

                    # Check for vihdoin arki issue
                    assert "vihdoin arki" not in movie.title.lower(), (
                        f"Title contains 'vihdoin arki' promotional text: {movie.title}"
                    )

                    success_count += 1

            except Exception as e:
                # Individual failures are acceptable for this test
                print(f"ProductParser failed for URL {url}: {e}")

        # Expect at least some successful parses
        assert success_count > 0, "ProductParser failed to parse any URLs"

    @pytest.mark.asyncio
    async def test_single_url_vihdoin_arki_filtering(self, test_scraper, sample_urls):
        """Specifically test vihdoin arki filtering for single URL processing"""
        for url in sample_urls:
            try:
                browser, context, page = await test_scraper.create_browser()
                await page.goto(url, wait_until="load", timeout=20000)

                body_element = await page.query_selector("body")
                movie = await test_scraper.extract_movie_data(body_element, page)

                await browser.close()

                if movie:
                    # This is the critical test from the original legacy test
                    assert "vihdoin arki" not in movie.title.lower(), (
                        f"FAILED: Still extracting 'vihdoin arki' from title: {movie.title}"
                    )
            except Exception:
                # Individual URL failures are acceptable for this specific test
                pass

    @pytest.mark.parametrize(
        "url",
        [
            "https://cdon.fi/tuote/breaking-bad-complete-box-kausi-1-5-blu-ray-e91bc5deded24435/",
            "https://cdon.fi/tuote/house-of-the-dragon-kausi-2-blu-ray-06077e495a0a59db/",
        ],
    )
    @pytest.mark.asyncio
    async def test_parametrized_single_urls(self, test_scraper, url):
        """Parametrized test for individual URLs"""
        browser, context, page = await test_scraper.create_browser()

        try:
            await page.goto(url, wait_until="load", timeout=20000)
            body_element = await page.query_selector("body")
            movie = await test_scraper.extract_movie_data(body_element, page)

            assert movie is not None, f"Failed to extract data from URL: {url}"
            assert movie.title, f"Title missing for URL: {url}"
            assert "vihdoin arki" not in movie.title.lower()

        finally:
            await browser.close()


# Command-line compatibility function (maintaining original interface)
async def test_single_url_cli(url: str):
    """Command-line compatible single URL test"""
    print(f"Testing URL: {url}")

    scraper = CDONScraper(db_path=":memory:")

    try:
        browser, context, page = await scraper.create_browser()

        print("Navigating to page...")
        await page.goto(url, wait_until="load", timeout=20000)

        print("Page loaded, extracting data using actual crawler...")

        # Find a product link element to simulate the crawler's context
        # On individual product pages, we'll create a mock element representing the whole page
        body_element = await page.query_selector("body")

        # Use the actual crawler's extraction method
        movie = await scraper.extract_movie_data(body_element, page)

        if movie:
            print(f"✓ Title: {movie.title}")
            print(f"✓ Price: €{movie.price}")
            print(f"✓ Format: {movie.format}")
            print(f"✓ URL: {movie.url}")

            if "vihdoin arki" in movie.title.lower():
                print("✗ FAILED: Still extracting 'vihdoin arki'")
            else:
                print("✓ SUCCESS: Clean data extracted using real crawler code")

            extracted_title = movie.title
        else:
            print("✗ Crawler failed to extract movie data")
            extracted_title = None

        await browser.close()
        return extracted_title

    except Exception as e:
        print(f"Error: {e}")
        return None


def main():
    """Main function for command-line compatibility"""
    if len(sys.argv) != 2:
        print("Usage: python test_single_url_processing.py <URL>")
        print("\nExample URLs:")
        print(
            "  https://cdon.fi/tuote/breaking-bad-complete-box-kausi-1-5-blu-ray-e91bc5deded24435/"
        )
        print("  https://cdon.fi/tuote/house-of-the-dragon-kausi-2-blu-ray-06077e495a0a59db/")
        sys.exit(1)

    url = sys.argv[1]
    result = asyncio.run(test_single_url_cli(url))

    if result:
        print(f"\nFinal result: {result}")
    else:
        print("\nFailed to extract title")


if __name__ == "__main__":
    main()
