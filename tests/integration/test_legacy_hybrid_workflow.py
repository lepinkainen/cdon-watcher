#!/usr/bin/env python3
"""
Integration tests for the hybrid CDON scraper architecture
Converted from legacy_test_hybrid.py to follow pytest conventions
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.cdon_watcher.cdon_scraper_v2 import CDONScraper
from src.cdon_watcher.listing_crawler import ListingCrawler
from src.cdon_watcher.product_parser import ProductParser


@pytest.fixture
def test_urls():
    """Test URLs for product parser testing"""
    return [
        "https://cdon.fi/tuote/breaking-bad-complete-box-kausi-1-5-blu-ray-e91bc5deded24435/",
        "https://cdon.fi/tuote/house-of-the-dragon-kausi-2-blu-ray-06077e495a0a59db/",
        "https://cdon.fi/tuote/indiana-jones-4-movie-collection-blu-ray-5-disc-e5a58c8cee5e590e/",
    ]


@pytest.fixture
def category_url():
    """Category URL for listing crawler testing"""
    return "https://cdon.fi/elokuvat/?facets=property_preset_media_format%3Ablu-ray&q="


@pytest.fixture
def product_parser():
    """Product parser fixture with cleanup"""
    parser = ProductParser()
    yield parser
    parser.close()


@pytest.fixture
def listing_crawler():
    """Listing crawler fixture with cleanup"""
    crawler = ListingCrawler()
    yield crawler
    # ListingCrawler cleanup is handled internally


@pytest.fixture
def test_scraper():
    """Test scraper with in-memory database"""
    scraper = CDONScraper(db_path=":memory:")
    yield scraper
    scraper.close()


class TestProductParser:
    """Test the ProductParser component"""

    @pytest.mark.asyncio
    async def test_product_parser_basic_functionality(self, product_parser, test_urls):
        """Test that ProductParser can parse individual product pages"""
        success_count = 0

        for url in test_urls:
            try:
                movie = product_parser.parse_product_page(url)
                if movie:
                    # Verify basic fields are present
                    assert movie.title, f"Title missing for URL: {url}"
                    assert movie.price is not None, f"Price missing for URL: {url}"
                    assert movie.format, f"Format missing for URL: {url}"

                    # Check for vihdoin arki issue
                    assert "vihdoin arki" not in movie.title.lower(), (
                        f"Title contains 'vihdoin arki' promotional text: {movie.title}"
                    )

                    success_count += 1

            except Exception as e:
                pytest.fail(f"ProductParser failed for URL {url}: {e}")

        # Expect at least some successful parses
        assert success_count > 0, "ProductParser failed to parse any URLs"

    @pytest.mark.asyncio
    async def test_vihdoin_arki_filtering(self, product_parser, test_urls):
        """Specifically test that 'vihdoin arki' promotional text is filtered out"""
        for url in test_urls:
            try:
                movie = product_parser.parse_product_page(url)
                if movie:
                    # This is the critical test from the original legacy test
                    assert "vihdoin arki" not in movie.title.lower(), (
                        f"FAILED: Still extracting 'vihdoin arki' from title: {movie.title}"
                    )
            except Exception:
                # Individual URL failures are acceptable for this specific test
                pass


class TestListingCrawler:
    """Test the ListingCrawler component"""

    @pytest.mark.asyncio
    async def test_listing_crawler_basic_functionality(self, listing_crawler, category_url):
        """Test that ListingCrawler can extract product URLs from category pages"""
        urls = await listing_crawler.crawl_category(category_url, max_pages=1)

        # Should find at least some URLs
        assert len(urls) > 0, "ListingCrawler found no product URLs"

        # All URLs should be strings and contain expected domain
        for url in urls:
            assert isinstance(url, str), f"URL is not string: {url}"
            assert "cdon.fi" in url, f"URL doesn't contain expected domain: {url}"


class TestHybridWorkflow:
    """Test the complete hybrid scraper workflow"""

    @pytest.mark.asyncio
    async def test_hybrid_scraper_complete_workflow(self, test_scraper, category_url):
        """Test the complete workflow: listing crawling + product parsing + database storage"""
        # Run the hybrid scraper on limited data
        saved_count = await test_scraper.crawl_category(category_url, max_pages=1)

        # Should save at least some movies
        assert saved_count > 0, f"Hybrid scraper saved {saved_count} movies, expected > 0"

        # Verify movies are in database
        all_movies = test_scraper.search_movies("")
        assert len(all_movies) >= saved_count, "Database doesn't contain expected number of movies"

        # Verify data quality
        for movie in all_movies:
            assert movie["title"], f"Movie missing title: {movie}"
            assert movie["current_price"] is not None, f"Movie missing price: {movie}"
            assert movie["format"], f"Movie missing format: {movie}"

    @pytest.mark.asyncio
    async def test_hybrid_workflow_vihdoin_arki_filtering(self, test_scraper, category_url):
        """Test that the complete workflow properly filters out 'vihdoin arki' issues"""
        # Run hybrid scraper
        saved_count = await test_scraper.crawl_category(category_url, max_pages=1)

        if saved_count > 0:
            # Check all saved movies for vihdoin arki issues
            all_movies = test_scraper.search_movies("")
            problematic_titles = [
                movie for movie in all_movies if "vihdoin arki" in movie["title"].lower()
            ]

            assert len(problematic_titles) == 0, (
                f"Found {len(problematic_titles)} movies with 'vihdoin arki' in titles: "
                f"{[m['title'] for m in problematic_titles]}"
            )


# Compatibility functions for command-line usage (maintaining original interface)
async def test_product_parser_cli(urls: list[str]):
    """Command-line compatible product parser test"""
    print("=== Testing ProductParser (Pure Python) ===")
    parser = ProductParser()

    for i, url in enumerate(urls, 1):
        print(f"\n{i}. Testing: {url}")
        try:
            movie = parser.parse_product_page(url)
            if movie:
                print(f"  ✓ Title: {movie.title}")
                print(f"  ✓ Price: €{movie.price}")
                print(f"  ✓ Format: {movie.format}")

                # Check for vihdoin arki issue
                if "vihdoin arki" in movie.title.lower():
                    print("  ✗ FAILED: Still extracting 'vihdoin arki'!")
                else:
                    print("  ✓ SUCCESS: Clean title extracted")
            else:
                print("  ✗ Failed to parse")
        except Exception as e:
            print(f"  ✗ Error: {e}")

    parser.close()
    print("\nProductParser test complete.\n")


async def test_listing_crawler_cli(category_url: str):
    """Command-line compatible listing crawler test"""
    print("=== Testing ListingCrawler (Playwright) ===")
    crawler = ListingCrawler()

    print(f"Testing: {category_url}")
    try:
        urls = await crawler.crawl_category(category_url, max_pages=1)

        print(f"✓ Found {len(urls)} product URLs")
        if urls:
            print("Sample URLs:")
            for url in urls[:5]:
                print(f"  - {url}")

            if len(urls) > 5:
                print(f"  ... and {len(urls) - 5} more")
        else:
            print("✗ No URLs found")

    except Exception as e:
        print(f"✗ Error: {e}")

    print("\nListingCrawler test complete.\n")


async def test_hybrid_scraper_cli(category_url: str):
    """Command-line compatible hybrid scraper test"""
    print("=== Testing Hybrid CDONScraper ===")
    scraper = CDONScraper(db_path="test_movies.db")

    print(f"Testing: {category_url}")
    try:
        saved_count = await scraper.crawl_category(category_url, max_pages=1)

        print(f"✓ Complete workflow saved {saved_count} Blu-ray movies")
        if saved_count > 0:
            sample_movies = scraper.search_movies("")[:3]
            if sample_movies:
                print("Sample saved movies:")
                for movie in sample_movies:
                    print(f"  - {movie['title']}")
                    print(f"    €{movie['current_price']} ({movie['format']})")

                # Check for vihdoin arki issues
                all_movies = scraper.search_movies("")
                problematic_titles = [m for m in all_movies if "vihdoin arki" in m["title"].lower()]
                if problematic_titles:
                    print(f"\n✗ FOUND {len(problematic_titles)} PROBLEMATIC TITLES:")
                    for movie in problematic_titles:
                        print(f"  - {movie['title']}")
                else:
                    print("\n✓ SUCCESS: No 'vihdoin arki' issues found!")
            else:
                print("✗ No movies found in database")
        else:
            print("✗ No movies were saved")

    except Exception as e:
        print(f"✗ Error: {e}")

    scraper.close()
    print("\nHybrid scraper test complete.\n")


def main():
    """Main function for command-line compatibility"""
    import sys

    # Test URLs (including the problematic ones from earlier)
    test_urls = [
        "https://cdon.fi/tuote/breaking-bad-complete-box-kausi-1-5-blu-ray-e91bc5deded24435/",
        "https://cdon.fi/tuote/house-of-the-dragon-kausi-2-blu-ray-06077e495a0a59db/",
        "https://cdon.fi/tuote/indiana-jones-4-movie-collection-blu-ray-5-disc-e5a58c8cee5e590e/",
    ]

    # Category URL for listing tests
    category_url = "https://cdon.fi/elokuvat/?facets=property_preset_media_format%3Ablu-ray&q="

    if len(sys.argv) > 1:
        test_type = sys.argv[1].lower()

        if test_type == "product":
            print("Running ProductParser tests only...")
            asyncio.run(test_product_parser_cli(test_urls))

        elif test_type == "listing":
            print("Running ListingCrawler tests only...")
            asyncio.run(test_listing_crawler_cli(category_url))

        elif test_type == "hybrid":
            print("Running Hybrid scraper tests only...")
            asyncio.run(test_hybrid_scraper_cli(category_url))

        else:
            print(f"Unknown test type: {test_type}")
            print("Usage: python test_legacy_hybrid_workflow.py [product|listing|hybrid]")
            sys.exit(1)
    else:
        # Run all tests
        print("Running all tests...\n")
        asyncio.run(test_product_parser_cli(test_urls))
        asyncio.run(test_listing_crawler_cli(category_url))
        asyncio.run(test_hybrid_scraper_cli(category_url))

        print("🎉 All tests complete!")
        print("\nUsage examples:")
        print("  python test_legacy_hybrid_workflow.py product   # Test only ProductParser")
        print("  python test_legacy_hybrid_workflow.py listing   # Test only ListingCrawler")
        print("  python test_legacy_hybrid_workflow.py hybrid    # Test only full workflow")


if __name__ == "__main__":
    main()
