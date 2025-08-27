"""Integration tests for ListingCrawler."""

import pytest

from src.cdon_watcher.listing_crawler import ListingCrawler


class TestListingCrawler:
    """Test cases for ListingCrawler functionality."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(120)  # 2 minutes for this integration test
    async def test_crawl_category_success(
        self, listing_crawler: ListingCrawler, sample_category_url: str
    ) -> None:
        """Test successful crawling of category pages."""
        urls = await listing_crawler.crawl_category(sample_category_url, max_pages=1)

        assert isinstance(urls, list), "Should return a list of URLs"
        assert len(urls) > 0, "Should find at least some product URLs"

        # Check that all URLs are valid CDON product URLs
        for url in urls:
            assert isinstance(url, str), "Each URL should be a string"
            assert url.startswith("https://cdon.fi/tuote/"), f"Invalid URL format: {url}"
            assert url.endswith("/"), f"URL should end with slash: {url}"

    @pytest.mark.asyncio
    @pytest.mark.timeout(180)  # 3 minutes for multi-page test
    async def test_crawl_category_limited_pages(
        self, listing_crawler: ListingCrawler, sample_category_url: str
    ) -> None:
        """Test crawling with page limit."""
        urls_1_page = await listing_crawler.crawl_category(sample_category_url, max_pages=1)
        urls_2_pages = await listing_crawler.crawl_category(sample_category_url, max_pages=2)

        assert len(urls_1_page) > 0, "Should find URLs on first page"
        assert len(urls_2_pages) >= len(urls_1_page), (
            "Two pages should have at least as many URLs as one page"
        )

    @pytest.mark.asyncio
    async def test_crawl_category_invalid_url(self, listing_crawler: ListingCrawler) -> None:
        """Test crawling with invalid category URL."""
        invalid_url = "https://invalid-url-that-does-not-exist.com/"

        with pytest.raises((ConnectionError, TimeoutError, ValueError)):
            await listing_crawler.crawl_category(invalid_url, max_pages=1)

    @pytest.mark.asyncio
    async def test_crawl_category_zero_pages(
        self, listing_crawler: ListingCrawler, sample_category_url: str
    ) -> None:
        """Test crawling with zero max_pages."""
        urls = await listing_crawler.crawl_category(sample_category_url, max_pages=0)
        assert urls == [], "Should return empty list for max_pages=0"
