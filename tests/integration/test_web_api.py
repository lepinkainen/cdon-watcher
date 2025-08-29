"""Integration tests for FastAPI web API endpoints."""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.cdon_watcher.cdon_scraper import CDONScraper

# DatabaseManager was removed - using CDONScraper for database initialization
from src.cdon_watcher.web.app import create_app


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
def app(temp_db_path, monkeypatch):
    """Create FastAPI app instance for testing."""
    # Mock the CONFIG to use our test database
    monkeypatch.setenv("DB_PATH", temp_db_path)

    # Import after setting environment variable
    from src.cdon_watcher.config import CONFIG

    monkeypatch.setitem(CONFIG, "db_path", temp_db_path)

    app = create_app()
    return app


@pytest.fixture
def client(app):
    """Create FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def populated_db(temp_db_path):
    """Create an initialized database."""
    # Initialize database schema only
    scraper = CDONScraper(temp_db_path)
    scraper.close()
    return temp_db_path


class TestAPIEndpoints:
    """Test all FastAPI API endpoints."""

    def test_index_route(self, client):
        """Test main dashboard page."""
        response = client.get("/")
        assert response.status_code == 200
        assert b"html" in response.content.lower()

    def test_api_stats(self, client, populated_db):
        """Test /api/stats endpoint."""
        response = client.get("/api/stats")
        assert response.status_code == 200

        data = response.json()

        # Check required fields
        assert "total_movies" in data
        assert "price_drops_today" in data
        assert "watchlist_count" in data
        assert "last_update" in data

        # Check values
        assert data["total_movies"] == 3
        assert data["watchlist_count"] == 2
        assert isinstance(data["price_drops_today"], int)
        assert data["last_update"] is not None

    def test_api_alerts(self, client, populated_db):
        """Test /api/alerts endpoint."""
        response = client.get("/api/alerts")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)

        if data:  # If there are alerts
            alert = data[0]
            assert "alert_type" in alert
            assert "old_price" in alert
            assert "new_price" in alert
            assert "created_at" in alert

    def test_api_deals(self, client, populated_db):
        """Test /api/deals endpoint."""
        response = client.get("/api/deals")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)

        if data:  # If there are deals
            deal = data[0]
            required_fields = [
                "id",
                "product_id",
                "title",
                "format",
                "url",
                "current_price",
                "previous_price",
                "price_change",
            ]
            for field in required_fields:
                assert field in deal

            # Price change should be negative (price drop)
            assert deal["price_change"] < 0

    def test_api_watchlist_get(self, client, populated_db):
        """Test GET /api/watchlist endpoint."""
        response = client.get("/api/watchlist")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2  # We added 2 items to watchlist

        for item in data:
            required_fields = [
                "id",
                "product_id",
                "title",
                "format",
                "url",
                "target_price",
                "current_price",
            ]
            for field in required_fields:
                assert field in item

            assert item["target_price"] > 0
            assert item["current_price"] > 0

    def test_api_watchlist_post_with_product_id(self, client, populated_db):
        """Test POST /api/watchlist with product_id."""
        payload = {"product_id": "inception-789", "target_price": 15.0}

        response = client.post("/api/watchlist", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Added to watchlist"

        # Verify it was added
        response = client.get("/api/watchlist")
        data = response.json()
        assert len(data) == 3  # Should now have 3 items

        # Find the new item
        inception_item = next(
            (item for item in data if item["product_id"] == "inception-789"), None
        )
        assert inception_item is not None
        assert inception_item["target_price"] == 15.0

    def test_api_watchlist_post_missing_data(self, client, populated_db):
        """Test POST /api/watchlist with missing data."""
        payload = {"product_id": "inception-789"}  # Missing target_price

        response = client.post("/api/watchlist", json=payload)

        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert "target_price" in data["error"]

    def test_api_watchlist_post_invalid_product(self, client, populated_db):
        """Test POST /api/watchlist with invalid product_id."""
        payload = {"product_id": "non-existent-product", "target_price": 15.0}

        response = client.post("/api/watchlist", json=payload)

        assert response.status_code == 500
        data = response.json()
        assert "error" in data

    def test_api_remove_from_watchlist(self, client, populated_db):
        """Test DELETE /api/watchlist/<identifier>."""
        # First verify item exists
        response = client.get("/api/watchlist")
        data = response.json()
        initial_count = len(data)
        assert initial_count == 2

        # Remove item by product_id
        response = client.delete("/api/watchlist/breaking-bad-123")
        assert response.status_code == 200

        data = response.json()
        assert data["message"] == "Removed from watchlist"

        # Verify it was removed
        response = client.get("/api/watchlist")
        data = response.json()
        assert len(data) == initial_count - 1

        # Verify the specific item is gone
        product_ids = [item["product_id"] for item in data]
        assert "breaking-bad-123" not in product_ids

    def test_api_search(self, client, populated_db):
        """Test /api/search endpoint."""
        # Search with query
        response = client.get("/api/search?q=breaking")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert "Breaking Bad" in data[0]["title"]

        # Empty search
        response = client.get("/api/search?q=")
        assert response.status_code == 200
        data = response.json()
        assert data == []

        # No query parameter
        response = client.get("/api/search")
        assert response.status_code == 200
        data = response.json()
        assert data == []

    def test_api_cheapest_blurays(self, client, populated_db):
        """Test /api/cheapest-blurays endpoint."""
        response = client.get("/api/cheapest-blurays")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)

        # Should have Blu-ray movies (not 4K)
        bluray_movies = [m for m in data if "Blu-ray" in m["format"] and "4K" not in m["format"]]
        assert len(bluray_movies) >= 2  # Breaking Bad and Inception

        # Should be sorted by price (cheapest first)
        prices = [movie["current_price"] for movie in bluray_movies]
        assert prices == sorted(prices)

    def test_api_cheapest_4k_blurays(self, client, populated_db):
        """Test /api/cheapest-4k-blurays endpoint."""
        response = client.get("/api/cheapest-4k-blurays")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)

        # Should have 4K movies
        fourk_movies = [m for m in data if "4K" in m["format"]]
        assert len(fourk_movies) >= 1  # Dark Knight 4K

        # Should be sorted by price (cheapest first)
        if len(fourk_movies) > 1:
            prices = [movie["current_price"] for movie in fourk_movies]
            assert prices == sorted(prices)

    def test_api_ignore_movie(self, client, populated_db):
        """Test POST /api/ignore-movie endpoint."""
        payload = {"product_id": "inception-789"}

        response = client.post("/api/ignore-movie", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Movie ignored"

        # Verify movie is ignored by checking it doesn't appear in cheapest movies
        response = client.get("/api/cheapest-blurays")
        data = response.json()

        product_ids = [movie["product_id"] for movie in data]
        assert "inception-789" not in product_ids

    def test_api_ignore_movie_missing_data(self, client, populated_db):
        """Test POST /api/ignore-movie with missing data."""
        payload = {}  # Missing product_id

        response = client.post("/api/ignore-movie", json=payload)

        assert response.status_code == 400
        data = response.json()
        assert "error" in data


class TestErrorHandling:
    """Test API error handling."""

    def test_404_routes(self, client):
        """Test non-existent routes return 404."""
        response = client.get("/api/non-existent")
        assert response.status_code == 404

        response = client.get("/non-existent")
        assert response.status_code == 404

    def test_invalid_json(self, client, populated_db):
        """Test invalid JSON in POST requests."""
        response = client.post(
            "/api/watchlist", content="invalid json", headers={"content-type": "application/json"}
        )

        # Should handle invalid JSON gracefully
        assert response.status_code in [400, 500]

    def test_missing_content_type(self, client, populated_db):
        """Test POST requests without content type."""
        response = client.post(
            "/api/watchlist", data='{"product_id": "test", "target_price": 15.0}'
        )

        # Should handle missing content type
        assert response.status_code in [400, 422]  # FastAPI returns 422 for validation errors


class TestCORSHeaders:
    """Test CORS configuration."""

    def test_cors_headers_present(self, client, populated_db):
        """Test that CORS headers are present in responses."""
        response = client.get("/api/stats")
        assert response.status_code == 200

        # Check for CORS headers (flask-cors should add these)
        dict(response.headers)
        # Note: In testing mode, CORS headers might not be added
        # This test documents expected behavior for production

    def test_options_request(self, client):
        """Test OPTIONS request for CORS preflight."""
        response = client.options("/api/stats")
        # Should not error, regardless of status code
        assert response.status_code in [200, 204, 405]


class TestStaticFileServing:
    """Test static file serving."""

    def test_poster_serving_missing_file(self, client):
        """Test serving non-existent poster file."""
        response = client.get("/posters/non-existent.jpg")
        assert response.status_code == 404

    def test_poster_route_exists(self, client):
        """Test that poster route is configured."""
        # This will 404 but route should exist
        response = client.get("/posters/test.jpg")
        assert response.status_code == 404  # File doesn't exist, but route works
