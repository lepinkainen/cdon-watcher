"""Unit tests for DatabaseManager class."""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.cdon_watcher.cdon_scraper import CDONScraper
from src.cdon_watcher.database import DatabaseManager
from src.cdon_watcher.product_parser import Movie


@pytest.fixture
def temp_db_path():
    """Provide a temporary database path for tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
        temp_path = tmp_file.name

    yield temp_path

    # Clean up
    temp_file_path = Path(temp_path)
    if temp_file_path.exists():
        temp_file_path.unlink()


@pytest.fixture
def db_manager(temp_db_path):
    """Provide DatabaseManager instance with test database."""
    # Initialize database schema first
    scraper = CDONScraper(temp_db_path)
    scraper.close()

    return DatabaseManager(temp_db_path)


@pytest.fixture
def populated_db_manager(temp_db_path):
    """Provide DatabaseManager with populated test data."""
    scraper = CDONScraper(temp_db_path)

    # Create test movies
    test_movies = [
        Movie(
            title="Test Movie 1",
            format="Blu-ray",
            url="https://cdon.fi/tuote/test-movie-1",
            image_url="https://cdon.fi/images/test1.jpg",
            price=25.99,
            availability="In Stock",
            product_id="test-1",
        ),
        Movie(
            title="Test Movie 2 4K",
            format="4K UHD Blu-ray",
            url="https://cdon.fi/tuote/test-movie-2",
            image_url="https://cdon.fi/images/test2.jpg",
            price=35.99,
            availability="In Stock",
            product_id="test-2",
        ),
        Movie(
            title="Test Movie 3",
            format="Blu-ray",
            url="https://cdon.fi/tuote/test-movie-3",
            image_url="https://cdon.fi/images/test3.jpg",
            price=15.99,
            availability="Out of Stock",
            product_id="test-3",
        ),
    ]

    # Save movies using the batch save method to ensure price history
    scraper.save_movies(test_movies)

    scraper.close()

    # Create database manager and add some test data
    db_manager = DatabaseManager(temp_db_path)

    # Add some watchlist items
    db_manager.add_to_watchlist("test-1", 20.0)
    db_manager.add_to_watchlist("test-2", 30.0)

    # Create price history with price drops
    conn = db_manager.get_connection()
    cursor = conn.cursor()

    # Add historical prices for deals testing
    # First get the movie_id and current price
    cursor.execute("SELECT id FROM movies WHERE product_id = 'test-1'")
    movie_id = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT price FROM price_history WHERE movie_id = ? ORDER BY checked_at DESC LIMIT 1
    """,
        (movie_id,),
    )
    current_price = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO price_history (movie_id, product_id, price, checked_at)
        VALUES (?, 'test-1', ?, datetime('now', '-1 day'))
    """,
        (movie_id, current_price + 5.0),
    )

    # Add price alerts
    cursor.execute(
        """
        INSERT INTO price_alerts (movie_id, product_id, old_price, new_price, alert_type, created_at)
        VALUES (?, 'test-1', 30.99, 25.99, 'price_drop', datetime('now', '-2 hours'))
    """,
        (movie_id,),
    )

    conn.commit()
    conn.close()

    return db_manager


class TestDatabaseManagerInit:
    """Test DatabaseManager initialization."""

    def test_init_with_default_path(self):
        """Test initialization with default database path."""
        with patch("src.cdon_watcher.database.CONFIG", {"db_path": "/test/default.db"}):
            db = DatabaseManager()
            assert db.db_path == "/test/default.db"

    def test_init_with_custom_path(self):
        """Test initialization with custom database path."""
        custom_path = "/test/custom.db"
        db = DatabaseManager(custom_path)
        assert db.db_path == custom_path

    def test_get_connection(self, db_manager):
        """Test database connection creation."""
        conn = db_manager.get_connection()
        assert isinstance(conn, sqlite3.Connection)

        # Test connection works
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        assert result[0] == 1

        conn.close()


class TestGetStats:
    """Test get_stats method."""

    def test_get_stats_empty_database(self, db_manager):
        """Test stats with empty database."""
        stats = db_manager.get_stats()

        assert isinstance(stats, dict)
        assert stats["total_movies"] == 0
        assert stats["price_drops_today"] == 0
        assert stats["watchlist_count"] == 0
        assert stats["last_update"] is None

    def test_get_stats_populated_database(self, populated_db_manager):
        """Test stats with populated database."""
        stats = populated_db_manager.get_stats()

        assert isinstance(stats, dict)
        assert stats["total_movies"] == 3
        assert stats["watchlist_count"] == 2
        assert stats["price_drops_today"] >= 0  # Depends on when alerts were created
        assert stats["last_update"] is not None

    def test_get_stats_return_types(self, populated_db_manager):
        """Test that stats returns correct data types."""
        stats = populated_db_manager.get_stats()

        assert isinstance(stats["total_movies"], int)
        assert isinstance(stats["price_drops_today"], int)
        assert isinstance(stats["watchlist_count"], int)
        # last_update can be None or string


class TestGetDeals:
    """Test get_deals method."""

    def test_get_deals_empty_database(self, db_manager):
        """Test deals with empty database."""
        deals = db_manager.get_deals()
        assert isinstance(deals, list)
        assert len(deals) == 0

    def test_get_deals_with_limit(self, populated_db_manager):
        """Test deals with custom limit."""
        deals = populated_db_manager.get_deals(limit=5)
        assert isinstance(deals, list)
        assert len(deals) <= 5

    def test_get_deals_structure(self, populated_db_manager):
        """Test deal object structure."""
        deals = populated_db_manager.get_deals()

        if deals:  # If there are any deals
            deal = deals[0]
            required_fields = [
                "id",
                "product_id",
                "title",
                "format",
                "url",
                "image_url",
                "current_price",
                "previous_price",
                "price_change",
                "lowest_price",
                "highest_price",
            ]

            for field in required_fields:
                assert field in deal, f"Missing field: {field}"

            # Price change should be negative (price drop)
            if deal["price_change"] is not None:
                assert deal["price_change"] < 0, "Price change should be negative for deals"

    def test_get_deals_sorted_by_price_drop(self, populated_db_manager):
        """Test that deals are sorted by biggest price drops."""
        # Add another movie with different price drop
        conn = populated_db_manager.get_connection()
        cursor = conn.cursor()

        # Create a bigger price drop for test-2
        cursor.execute("SELECT id FROM movies WHERE product_id = 'test-2'")
        movie_id_2 = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT price FROM price_history WHERE movie_id = ? ORDER BY checked_at DESC LIMIT 1
        """,
            (movie_id_2,),
        )
        current_price_2 = cursor.fetchone()[0]

        cursor.execute(
            """
            INSERT INTO price_history (movie_id, product_id, price, checked_at)
            VALUES (?, 'test-2', ?, datetime('now', '-1 day'))
        """,
            (movie_id_2, current_price_2 + 15.0),
        )

        conn.commit()
        conn.close()

        deals = populated_db_manager.get_deals()

        if len(deals) > 1:
            # Should be sorted by price change (most negative first)
            for i in range(len(deals) - 1):
                assert deals[i]["price_change"] <= deals[i + 1]["price_change"]


class TestWatchlistOperations:
    """Test watchlist-related methods."""

    def test_get_watchlist_empty(self, db_manager):
        """Test getting empty watchlist."""
        watchlist = db_manager.get_watchlist()
        assert isinstance(watchlist, list)
        assert len(watchlist) == 0

    def test_get_watchlist_populated(self, populated_db_manager):
        """Test getting populated watchlist."""
        watchlist = populated_db_manager.get_watchlist()

        assert isinstance(watchlist, list)
        assert len(watchlist) == 2

        # Check structure
        item = watchlist[0]
        required_fields = [
            "id",
            "product_id",
            "title",
            "format",
            "url",
            "image_url",
            "target_price",
            "current_price",
            "lowest_price",
            "highest_price",
        ]

        for field in required_fields:
            assert field in item, f"Missing field: {field}"

    def test_add_to_watchlist_success(self, populated_db_manager):
        """Test successfully adding to watchlist."""
        result = populated_db_manager.add_to_watchlist("test-3", 12.0)
        assert result is True

        # Verify it was added
        watchlist = populated_db_manager.get_watchlist()
        assert len(watchlist) == 3

        # Find the new item
        new_item = next((item for item in watchlist if item["product_id"] == "test-3"), None)
        assert new_item is not None
        assert new_item["target_price"] == 12.0

    def test_add_to_watchlist_invalid_product(self, populated_db_manager):
        """Test adding non-existent product to watchlist."""
        result = populated_db_manager.add_to_watchlist("non-existent", 15.0)
        assert result is False

        # Verify watchlist unchanged
        watchlist = populated_db_manager.get_watchlist()
        assert len(watchlist) == 2

    def test_add_to_watchlist_duplicate(self, populated_db_manager):
        """Test adding duplicate item to watchlist (should replace)."""
        # test-1 is already in watchlist with target_price 20.0
        result = populated_db_manager.add_to_watchlist("test-1", 18.0)
        assert result is True

        # Should still have 2 items
        watchlist = populated_db_manager.get_watchlist()
        assert len(watchlist) == 2

        # But target price should be updated
        item = next((item for item in watchlist if item["product_id"] == "test-1"), None)
        assert item["target_price"] == 18.0

    def test_remove_from_watchlist_success(self, populated_db_manager):
        """Test successfully removing from watchlist."""
        result = populated_db_manager.remove_from_watchlist("test-1")
        assert result is True

        # Verify it was removed
        watchlist = populated_db_manager.get_watchlist()
        assert len(watchlist) == 1

        # Verify the specific item is gone
        product_ids = [item["product_id"] for item in watchlist]
        assert "test-1" not in product_ids

    def test_remove_from_watchlist_not_found(self, populated_db_manager):
        """Test removing non-existent item from watchlist."""
        result = populated_db_manager.remove_from_watchlist("non-existent")
        assert result is True  # SQLite DELETE succeeds even if no rows affected

        # Verify watchlist unchanged
        watchlist = populated_db_manager.get_watchlist()
        assert len(watchlist) == 2


class TestSearchMovies:
    """Test search_movies method."""

    def test_search_movies_empty_query(self, populated_db_manager):
        """Test search with empty query."""
        results = populated_db_manager.search_movies("")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_search_movies_no_matches(self, populated_db_manager):
        """Test search with no matches."""
        results = populated_db_manager.search_movies("nonexistent movie")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_search_movies_partial_match(self, populated_db_manager):
        """Test search with partial title match."""
        results = populated_db_manager.search_movies("Test Movie")
        assert isinstance(results, list)
        assert len(results) == 3  # All test movies match

        # Check structure
        movie = results[0]
        required_fields = [
            "id",
            "product_id",
            "title",
            "format",
            "url",
            "image_url",
            "current_price",
            "lowest_price",
            "highest_price",
        ]

        for field in required_fields:
            assert field in movie, f"Missing field: {field}"

    def test_search_movies_case_insensitive(self, populated_db_manager):
        """Test search is case insensitive."""
        results_lower = populated_db_manager.search_movies("test movie")
        results_upper = populated_db_manager.search_movies("TEST MOVIE")
        results_mixed = populated_db_manager.search_movies("Test Movie")

        assert len(results_lower) == len(results_upper) == len(results_mixed)
        assert len(results_lower) > 0

    def test_search_movies_with_limit(self, populated_db_manager):
        """Test search with limit parameter."""
        results = populated_db_manager.search_movies("Test", limit=2)
        assert len(results) <= 2

    def test_search_movies_sorted(self, populated_db_manager):
        """Test search results are sorted by title."""
        results = populated_db_manager.search_movies("Test")

        if len(results) > 1:
            titles = [movie["title"] for movie in results]
            assert titles == sorted(titles)


class TestCheapestMovies:
    """Test cheapest movies methods."""

    def test_get_cheapest_blurays_empty(self, db_manager):
        """Test cheapest Blu-rays with empty database."""
        movies = db_manager.get_cheapest_blurays()
        assert isinstance(movies, list)
        assert len(movies) == 0

    def test_get_cheapest_blurays_populated(self, populated_db_manager):
        """Test cheapest Blu-rays with populated database."""
        movies = populated_db_manager.get_cheapest_blurays()

        assert isinstance(movies, list)
        # Should have 2 Blu-ray movies (not 4K)
        assert len(movies) >= 2

        # All should be Blu-ray format (not 4K)
        for movie in movies:
            assert "Blu-ray" in movie["format"]
            assert "4K" not in movie["format"]

        # Should be sorted by price (ascending)
        if len(movies) > 1:
            prices = [movie["current_price"] for movie in movies]
            assert prices == sorted(prices)

    def test_get_cheapest_4k_blurays_populated(self, populated_db_manager):
        """Test cheapest 4K Blu-rays with populated database."""
        movies = populated_db_manager.get_cheapest_4k_blurays()

        assert isinstance(movies, list)
        # Should have 1 4K movie
        assert len(movies) >= 1

        # All should be 4K format
        for movie in movies:
            assert "4K" in movie["format"]

    def test_cheapest_movies_exclude_ignored(self, populated_db_manager):
        """Test that ignored movies are excluded from cheapest lists."""
        # Ignore a movie
        populated_db_manager.ignore_movie_by_product_id("test-1")

        # Get cheapest Blu-rays
        movies = populated_db_manager.get_cheapest_blurays()

        # test-1 should not be in results
        product_ids = [movie["product_id"] for movie in movies]
        assert "test-1" not in product_ids

    def test_cheapest_movies_structure(self, populated_db_manager):
        """Test structure of cheapest movies results."""
        movies = populated_db_manager.get_cheapest_blurays()

        if movies:
            movie = movies[0]
            required_fields = [
                "id",
                "product_id",
                "title",
                "format",
                "url",
                "image_url",
                "current_price",
                "lowest_price",
                "highest_price",
            ]

            for field in required_fields:
                assert field in movie, f"Missing field: {field}"

    def test_cheapest_movies_with_limit(self, populated_db_manager):
        """Test cheapest movies with limit parameter."""
        movies = populated_db_manager.get_cheapest_blurays(limit=1)
        assert len(movies) <= 1

        movies = populated_db_manager.get_cheapest_4k_blurays(limit=1)
        assert len(movies) <= 1


class TestIgnoreMovie:
    """Test ignore movie methods."""

    def test_ignore_movie_by_product_id_success(self, populated_db_manager):
        """Test successfully ignoring a movie by product_id."""
        result = populated_db_manager.ignore_movie_by_product_id("test-1")
        assert result is True

        # Verify movie is ignored by checking cheapest movies
        movies = populated_db_manager.get_cheapest_blurays()
        product_ids = [movie["product_id"] for movie in movies]
        assert "test-1" not in product_ids

    def test_ignore_movie_by_product_id_not_found(self, populated_db_manager):
        """Test ignoring non-existent movie by product_id."""
        result = populated_db_manager.ignore_movie_by_product_id("non-existent")
        assert result is False

    def test_ignore_movie_by_movie_id_success(self, populated_db_manager):
        """Test successfully ignoring a movie by movie_id (legacy method)."""
        # Get movie_id first
        conn = populated_db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM movies WHERE product_id = ?", ("test-2",))
        movie_id = cursor.fetchone()[0]
        conn.close()

        result = populated_db_manager.ignore_movie(movie_id)
        assert result is True

        # Verify movie is ignored
        movies = populated_db_manager.get_cheapest_4k_blurays()
        product_ids = [movie["product_id"] for movie in movies]
        assert "test-2" not in product_ids

    def test_ignore_movie_duplicate(self, populated_db_manager):
        """Test ignoring same movie twice (should succeed due to OR IGNORE)."""
        result1 = populated_db_manager.ignore_movie_by_product_id("test-1")
        result2 = populated_db_manager.ignore_movie_by_product_id("test-1")

        assert result1 is True
        assert result2 is True


class TestDatabaseErrors:
    """Test error handling in database operations."""

    def test_database_connection_error(self):
        """Test behavior with invalid database path."""
        db = DatabaseManager("/invalid/path/database.db")

        # Should raise exception when trying to connect
        with pytest.raises(sqlite3.OperationalError):
            conn = db.get_connection()
            conn.execute("SELECT 1").fetchone()

    def test_add_to_watchlist_database_error(self, populated_db_manager):
        """Test watchlist operations with database errors."""
        # Close database to simulate error
        original_path = populated_db_manager.db_path
        populated_db_manager.db_path = "/invalid/path.db"

        result = populated_db_manager.add_to_watchlist("test-1", 15.0)
        assert result is False

        # Restore path
        populated_db_manager.db_path = original_path

    def test_remove_from_watchlist_database_error(self, populated_db_manager):
        """Test remove from watchlist with database errors."""
        # Close database to simulate error
        original_path = populated_db_manager.db_path
        populated_db_manager.db_path = "/invalid/path.db"

        result = populated_db_manager.remove_from_watchlist("test-1")
        assert result is False

        # Restore path
        populated_db_manager.db_path = original_path

    def test_ignore_movie_database_error(self, populated_db_manager):
        """Test ignore movie with database errors."""
        # Close database to simulate error
        original_path = populated_db_manager.db_path
        populated_db_manager.db_path = "/invalid/path.db"

        result = populated_db_manager.ignore_movie_by_product_id("test-1")
        assert result is False

        # Restore path
        populated_db_manager.db_path = original_path


class TestDatabaseIntegrity:
    """Test database integrity and constraints."""

    def test_product_id_indexes_exist(self, populated_db_manager):
        """Test that product_id indexes are properly created."""
        conn = populated_db_manager.get_connection()
        cursor = conn.cursor()

        # Check for indexes
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE '%product_id%'"
        )
        indexes = cursor.fetchall()

        expected_indexes = [
            "idx_movies_product_id",
            "idx_watchlist_product_id",
            "idx_price_history_product_id",
            "idx_price_alerts_product_id",
            "idx_ignored_movies_product_id",
        ]

        index_names = [idx[0] for idx in indexes]

        for expected_idx in expected_indexes:
            assert expected_idx in index_names, f"Missing index: {expected_idx}"

        conn.close()

    def test_foreign_key_constraints(self, populated_db_manager):
        """Test foreign key relationships work correctly."""
        conn = populated_db_manager.get_connection()
        cursor = conn.cursor()

        # Test that price_history references movies
        cursor.execute("SELECT COUNT(*) FROM price_history ph JOIN movies m ON ph.movie_id = m.id")
        price_history_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM price_history")
        total_price_history = cursor.fetchone()[0]

        # All price history entries should have valid movie references
        assert price_history_count == total_price_history

        conn.close()
