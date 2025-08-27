"""Shared pytest fixtures for CDON Watcher tests."""

import asyncio
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from src.cdon_watcher.cdon_scraper_v2 import CDONScraper
from src.cdon_watcher.listing_crawler import ListingCrawler
from src.cdon_watcher.product_parser import ProductParser


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_db_path() -> Generator[str, None, None]:
    """Provide a temporary database path for tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        temp_path = tmp_file.name

    yield temp_path

    # Clean up
    temp_file_path = Path(temp_path)
    if temp_file_path.exists():
        temp_file_path.unlink()


@pytest.fixture
def product_parser() -> Generator[ProductParser, None, None]:
    """Provide a ProductParser instance for tests."""
    parser = ProductParser()
    yield parser
    parser.close()


@pytest.fixture
def listing_crawler() -> Generator[ListingCrawler, None, None]:
    """Provide a ListingCrawler instance for tests."""
    crawler = ListingCrawler()
    yield crawler
    # ListingCrawler manages its own browser lifecycle within each crawl operation


@pytest.fixture
def cdon_scraper(temp_db_path: str) -> Generator[CDONScraper, None, None]:
    """Provide a CDONScraper instance with temporary database for tests."""
    scraper = CDONScraper(db_path=temp_db_path)
    yield scraper
    scraper.close()


@pytest.fixture
def sample_product_urls() -> list[str]:
    """Provide sample product URLs for testing."""
    return [
        "https://cdon.fi/tuote/breaking-bad-complete-box-kausi-1-5-blu-ray-e91bc5deded24435/",
        "https://cdon.fi/tuote/house-of-the-dragon-kausi-2-blu-ray-06077e495a0a59db/",
        "https://cdon.fi/tuote/indiana-jones-4-movie-collection-blu-ray-5-disc-e5a58c8cee5e590e/",
    ]


@pytest.fixture
def sample_category_url() -> str:
    """Provide a sample category URL for testing."""
    return "https://cdon.fi/elokuvat/?facets=property_preset_media_format%3Ablu-ray&q="
