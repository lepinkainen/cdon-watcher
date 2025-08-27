"""Tests for product_id functionality in database operations."""

import os
import sqlite3
import tempfile

import pytest

from cdon_watcher.cdon_scraper_v2 import CDONScraper
from cdon_watcher.database import DatabaseManager
from cdon_watcher.product_parser import Movie


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    os.unlink(path)


def test_watchlist_operations_with_product_id(temp_db):
    """Test adding and removing movies from watchlist using product_id."""
    # Initialize database
    scraper = CDONScraper(temp_db)
    db_manager = DatabaseManager(temp_db)

    # Create a test movie
    test_movie = Movie(
        title="Test Movie",
        format="Blu-ray",
        url="https://cdon.fi/test-movie",
        image_url="https://cdon.fi/test-image.jpg",
        price=25.99,
        availability="In Stock",
        product_id="test-product-123"
    )

    # Save the movie
    assert scraper.save_single_movie(test_movie) is True

    # Add to watchlist using product_id
    assert db_manager.add_to_watchlist("test-product-123", 20.0) is True

    # Get watchlist and verify
    watchlist = db_manager.get_watchlist()
    assert len(watchlist) == 1
    assert watchlist[0]["product_id"] == "test-product-123"
    assert watchlist[0]["title"] == "Test Movie"
    assert watchlist[0]["target_price"] == 20.0

    # Remove from watchlist using product_id
    assert db_manager.remove_from_watchlist("test-product-123") is True

    # Verify removal
    watchlist = db_manager.get_watchlist()
    assert len(watchlist) == 0


def test_ignore_movie_with_product_id(temp_db):
    """Test ignoring movies using product_id."""
    # Initialize database
    scraper = CDONScraper(temp_db)
    db_manager = DatabaseManager(temp_db)

    # Create a test movie
    test_movie = Movie(
        title="Test Movie to Ignore",
        format="Blu-ray",
        url="https://cdon.fi/test-ignore-movie",
        image_url="https://cdon.fi/test-ignore-image.jpg",
        price=30.99,
        availability="In Stock",
        product_id="test-ignore-123"
    )

    # Save the movie
    assert scraper.save_single_movie(test_movie) is True

    # Ignore the movie by product_id
    assert db_manager.ignore_movie_by_product_id("test-ignore-123") is True

    # Verify movie was ignored by checking it doesn't appear in cheapest movies
    cheapest = db_manager.get_cheapest_blurays(10)
    assert all(movie["product_id"] != "test-ignore-123" for movie in cheapest)


def test_product_id_columns_exist(temp_db):
    """Test that product_id columns are created in all tables."""
    # Initialize database
    CDONScraper(temp_db)

    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()

    # Check each table has product_id column
    tables_to_check = ['watchlist', 'price_history', 'price_alerts', 'ignored_movies']

    for table in tables_to_check:
        cursor.execute(f"PRAGMA table_info({table})")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]
        assert 'product_id' in column_names, f"product_id column missing from {table} table"

    conn.close()


def test_search_includes_product_id(temp_db):
    """Test that search results include product_id."""
    # Initialize database
    scraper = CDONScraper(temp_db)
    db_manager = DatabaseManager(temp_db)

    # Create a test movie
    test_movie = Movie(
        title="Searchable Test Movie",
        format="Blu-ray",
        url="https://cdon.fi/searchable-movie",
        image_url="https://cdon.fi/searchable-image.jpg",
        price=15.99,
        availability="In Stock",
        product_id="searchable-123"
    )

    # Save the movie
    assert scraper.save_single_movie(test_movie) is True

    # Search for the movie
    results = db_manager.search_movies("Searchable", 10)
    assert len(results) == 1
    assert results[0]["product_id"] == "searchable-123"
    assert results[0]["title"] == "Searchable Test Movie"


def test_price_history_includes_product_id(temp_db):
    """Test that price history entries include product_id."""
    # Initialize database
    scraper = CDONScraper(temp_db)

    # Create a test movie
    test_movie = Movie(
        title="Price History Test",
        format="Blu-ray",
        url="https://cdon.fi/price-history-movie",
        image_url="https://cdon.fi/price-history-image.jpg",
        price=29.99,
        availability="In Stock",
        product_id="price-history-123"
    )

    # Save the movie (this should create price history)
    assert scraper.save_single_movie(test_movie) is True

    # Check price history directly in database
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()

    cursor.execute("SELECT product_id, price FROM price_history WHERE product_id = ?", ("price-history-123",))
    result = cursor.fetchone()

    assert result is not None
    assert result[0] == "price-history-123"
    assert result[1] == 29.99

    conn.close()
