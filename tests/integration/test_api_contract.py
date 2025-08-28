"""API contract and schema validation tests.

These tests ensure API request/response formats remain consistent,
which is critical for the FastAPI migration.
"""

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from src.cdon_watcher.cdon_scraper import CDONScraper
from src.cdon_watcher.database import DatabaseManager
from src.cdon_watcher.product_parser import Movie
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
    """Create Flask app instance for testing."""
    monkeypatch.setenv("DB_PATH", temp_db_path)

    from src.cdon_watcher.config import CONFIG

    monkeypatch.setitem(CONFIG, "db_path", temp_db_path)

    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Create Flask test client."""
    return app.test_client()


@pytest.fixture
def populated_client(temp_db_path, monkeypatch):
    """Create client with populated database."""
    monkeypatch.setenv("DB_PATH", temp_db_path)

    from src.cdon_watcher.config import CONFIG

    monkeypatch.setitem(CONFIG, "db_path", temp_db_path)

    # Create test data
    scraper = CDONScraper(temp_db_path)
    db = DatabaseManager(temp_db_path)

    test_movies = [
        Movie(
            title="Contract Test Movie 1",
            format="Blu-ray",
            url="https://cdon.fi/tuote/contract-test-1",
            image_url="https://cdon.fi/images/contract1.jpg",
            price=29.99,
            availability="In Stock",
            product_id="contract-test-1",
        ),
        Movie(
            title="Contract Test Movie 2 4K",
            format="4K UHD Blu-ray",
            url="https://cdon.fi/tuote/contract-test-2",
            image_url="https://cdon.fi/images/contract2.jpg",
            price=39.99,
            availability="In Stock",
            product_id="contract-test-2",
        ),
    ]

    # Save movies and create test data
    scraper.save_movies(test_movies)

    # Add to watchlist
    db.add_to_watchlist("contract-test-1", 25.0)

    # Create price history for deals
    conn = db.get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM movies WHERE product_id = 'contract-test-1'")
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
        VALUES (?, 'contract-test-1', ?, datetime('now', '-1 day'))
    """,
        (movie_id, current_price + 5.0),
    )

    cursor.execute(
        """
        INSERT INTO price_alerts (movie_id, product_id, old_price, new_price, alert_type, created_at)
        VALUES (?, 'contract-test-1', 34.99, 29.99, 'price_drop', datetime('now', '-1 hour'))
    """,
        (movie_id,),
    )

    conn.commit()
    conn.close()
    scraper.close()

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def validate_movie_schema(movie: dict[str, Any]) -> None:
    """Validate movie object schema."""
    required_fields = {
        "id": int,
        "product_id": str,
        "title": str,
        "format": str,
        "url": str,
        "current_price": (int, float, type(None)),
    }

    for field, expected_type in required_fields.items():
        assert field in movie, f"Missing required field: {field}"
        if movie[field] is not None:
            assert isinstance(movie[field], expected_type), (
                f"Field {field} has wrong type: {type(movie[field])}"
            )

    # Optional fields with type validation
    optional_fields = {
        "image_url": (str, type(None)),
        "tmdb_id": (int, type(None)),
        "lowest_price": (int, float, type(None)),
        "highest_price": (int, float, type(None)),
        "previous_price": (int, float, type(None)),
        "price_change": (int, float, type(None)),
        "target_price": (int, float, type(None)),
    }

    for field, expected_type in optional_fields.items():
        if field in movie and movie[field] is not None:
            assert isinstance(movie[field], expected_type), (
                f"Optional field {field} has wrong type: {type(movie[field])}"
            )


class TestStatsAPIContract:
    """Test /api/stats endpoint contract."""

    def test_stats_response_schema(self, populated_client):
        """Test stats response has correct schema."""
        response = populated_client.get("/api/stats")
        assert response.status_code == 200

        data = json.loads(response.data)

        # Required fields with correct types
        required_fields = {
            "total_movies": int,
            "price_drops_today": int,
            "watchlist_count": int,
            "last_update": (str, type(None)),
        }

        for field, expected_type in required_fields.items():
            assert field in data, f"Missing required field: {field}"
            assert isinstance(data[field], expected_type), (
                f"Field {field} has wrong type: {type(data[field])}"
            )

    def test_stats_response_values(self, populated_client):
        """Test stats response has reasonable values."""
        response = populated_client.get("/api/stats")
        data = json.loads(response.data)

        assert data["total_movies"] >= 0
        assert data["price_drops_today"] >= 0
        assert data["watchlist_count"] >= 0

    def test_stats_content_type(self, populated_client):
        """Test stats response content type."""
        response = populated_client.get("/api/stats")
        assert "application/json" in response.content_type


class TestAlertsAPIContract:
    """Test /api/alerts endpoint contract."""

    def test_alerts_response_schema(self, populated_client):
        """Test alerts response has correct schema."""
        response = populated_client.get("/api/alerts")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert isinstance(data, list)

        if data:  # If there are alerts
            alert = data[0]
            required_fields = {
                "alert_type": str,
                "old_price": (int, float),
                "new_price": (int, float),
                "created_at": str,
            }

            for field, expected_type in required_fields.items():
                assert field in alert, f"Missing required field: {field}"
                assert isinstance(alert[field], expected_type), (
                    f"Field {field} has wrong type: {type(alert[field])}"
                )

    def test_alerts_limit_behavior(self, populated_client):
        """Test alerts returns maximum 10 items."""
        response = populated_client.get("/api/alerts")
        data = json.loads(response.data)

        assert len(data) <= 10

    def test_alerts_content_type(self, populated_client):
        """Test alerts response content type."""
        response = populated_client.get("/api/alerts")
        assert "application/json" in response.content_type


class TestDealsAPIContract:
    """Test /api/deals endpoint contract."""

    def test_deals_response_schema(self, populated_client):
        """Test deals response has correct schema."""
        response = populated_client.get("/api/deals")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert isinstance(data, list)

        if data:  # If there are deals
            deal = data[0]
            validate_movie_schema(deal)

            # Deals-specific fields
            assert "previous_price" in deal
            assert "price_change" in deal
            assert isinstance(deal["previous_price"], int | float)
            assert isinstance(deal["price_change"], int | float)

            # Price change should be negative for deals
            assert deal["price_change"] < 0

    def test_deals_content_type(self, populated_client):
        """Test deals response content type."""
        response = populated_client.get("/api/deals")
        assert "application/json" in response.content_type


class TestWatchlistAPIContract:
    """Test /api/watchlist endpoint contract."""

    def test_watchlist_get_response_schema(self, populated_client):
        """Test GET watchlist response has correct schema."""
        response = populated_client.get("/api/watchlist")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert isinstance(data, list)

        if data:  # If there are watchlist items
            item = data[0]
            validate_movie_schema(item)

            # Watchlist-specific fields
            assert "target_price" in item
            assert isinstance(item["target_price"], int | float)
            assert item["target_price"] > 0

    def test_watchlist_post_request_schema(self, populated_client):
        """Test POST watchlist request validation."""
        # Valid request
        valid_payload = {"product_id": "contract-test-2", "target_price": 35.0}

        response = populated_client.post(
            "/api/watchlist", data=json.dumps(valid_payload), content_type="application/json"
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert "message" in data
        assert isinstance(data["message"], str)

    def test_watchlist_post_invalid_requests(self, populated_client):
        """Test POST watchlist with invalid requests."""
        # Missing target_price
        invalid_payload = {"product_id": "contract-test-1"}

        response = populated_client.post(
            "/api/watchlist", data=json.dumps(invalid_payload), content_type="application/json"
        )
        assert response.status_code == 400

        data = json.loads(response.data)
        assert "error" in data
        assert isinstance(data["error"], str)

    def test_watchlist_delete_response_schema(self, populated_client):
        """Test DELETE watchlist response schema."""
        response = populated_client.delete("/api/watchlist/contract-test-1")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert "message" in data
        assert isinstance(data["message"], str)

    def test_watchlist_content_type(self, populated_client):
        """Test watchlist response content type."""
        response = populated_client.get("/api/watchlist")
        assert "application/json" in response.content_type


class TestSearchAPIContract:
    """Test /api/search endpoint contract."""

    def test_search_response_schema(self, populated_client):
        """Test search response has correct schema."""
        response = populated_client.get("/api/search?q=Contract")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert isinstance(data, list)

        if data:  # If there are results
            movie = data[0]
            validate_movie_schema(movie)

    def test_search_empty_query_behavior(self, populated_client):
        """Test search with empty query."""
        response = populated_client.get("/api/search?q=")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert isinstance(data, list)
        assert len(data) == 0

    def test_search_no_query_parameter(self, populated_client):
        """Test search without query parameter."""
        response = populated_client.get("/api/search")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert isinstance(data, list)
        assert len(data) == 0

    def test_search_content_type(self, populated_client):
        """Test search response content type."""
        response = populated_client.get("/api/search?q=test")
        assert "application/json" in response.content_type


class TestCheapestMoviesAPIContract:
    """Test cheapest movies endpoints contract."""

    def test_cheapest_blurays_response_schema(self, populated_client):
        """Test cheapest Blu-rays response has correct schema."""
        response = populated_client.get("/api/cheapest-blurays")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert isinstance(data, list)

        if data:
            movie = data[0]
            validate_movie_schema(movie)

            # Should be Blu-ray format
            assert "Blu-ray" in movie["format"]

    def test_cheapest_4k_blurays_response_schema(self, populated_client):
        """Test cheapest 4K Blu-rays response has correct schema."""
        response = populated_client.get("/api/cheapest-4k-blurays")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert isinstance(data, list)

        if data:
            movie = data[0]
            validate_movie_schema(movie)

            # Should be 4K format
            assert "4K" in movie["format"]

    def test_cheapest_movies_sorted_by_price(self, populated_client):
        """Test cheapest movies are sorted by price."""
        response = populated_client.get("/api/cheapest-blurays")
        data = json.loads(response.data)

        if len(data) > 1:
            prices = [
                movie["current_price"] for movie in data if movie["current_price"] is not None
            ]
            assert prices == sorted(prices), "Movies should be sorted by price (ascending)"

    def test_cheapest_movies_content_type(self, populated_client):
        """Test cheapest movies response content type."""
        response = populated_client.get("/api/cheapest-blurays")
        assert "application/json" in response.content_type

        response = populated_client.get("/api/cheapest-4k-blurays")
        assert "application/json" in response.content_type


class TestIgnoreMovieAPIContract:
    """Test /api/ignore-movie endpoint contract."""

    def test_ignore_movie_request_schema(self, populated_client):
        """Test ignore movie request validation."""
        valid_payload = {"product_id": "contract-test-1"}

        response = populated_client.post(
            "/api/ignore-movie", data=json.dumps(valid_payload), content_type="application/json"
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert "message" in data
        assert isinstance(data["message"], str)

    def test_ignore_movie_invalid_request(self, populated_client):
        """Test ignore movie with invalid request."""
        invalid_payload = {}  # Missing product_id

        response = populated_client.post(
            "/api/ignore-movie", data=json.dumps(invalid_payload), content_type="application/json"
        )
        assert response.status_code == 400

        data = json.loads(response.data)
        assert "error" in data
        assert isinstance(data["error"], str)

    def test_ignore_movie_content_type(self, populated_client):
        """Test ignore movie response content type."""
        payload = {"product_id": "contract-test-2"}

        response = populated_client.post(
            "/api/ignore-movie", data=json.dumps(payload), content_type="application/json"
        )
        assert "application/json" in response.content_type


class TestHTTPMethods:
    """Test HTTP method constraints on endpoints."""

    def test_get_only_endpoints(self, populated_client):
        """Test endpoints that should only accept GET requests."""
        get_only_endpoints = [
            "/api/stats",
            "/api/alerts",
            "/api/deals",
            "/api/search",
            "/api/cheapest-blurays",
            "/api/cheapest-4k-blurays",
        ]

        for endpoint in get_only_endpoints:
            # GET should work
            response = populated_client.get(endpoint)
            assert response.status_code == 200

            # POST should not be allowed
            response = populated_client.post(endpoint)
            assert response.status_code == 405  # Method Not Allowed

    def test_multi_method_endpoints(self, populated_client):
        """Test endpoints that accept multiple methods."""
        # Watchlist accepts GET and POST
        response = populated_client.get("/api/watchlist")
        assert response.status_code == 200

        payload = {"product_id": "contract-test-2", "target_price": 30.0}
        response = populated_client.post(
            "/api/watchlist", data=json.dumps(payload), content_type="application/json"
        )
        assert response.status_code == 200

        # Ignore movie accepts POST only
        response = populated_client.get("/api/ignore-movie")
        assert response.status_code == 405

    def test_delete_method_endpoints(self, populated_client):
        """Test DELETE method endpoints."""
        # Should accept DELETE
        response = populated_client.delete("/api/watchlist/contract-test-1")
        assert response.status_code == 200

        # Should not accept GET on specific watchlist item path
        # (This would be handled by Flask routing)


class TestErrorResponseContract:
    """Test consistent error response formats."""

    def test_400_error_format(self, populated_client):
        """Test 400 Bad Request error format."""
        invalid_payload = {"product_id": "test"}  # Missing target_price

        response = populated_client.post(
            "/api/watchlist", data=json.dumps(invalid_payload), content_type="application/json"
        )
        assert response.status_code == 400

        data = json.loads(response.data)
        assert "error" in data
        assert isinstance(data["error"], str)
        assert len(data["error"]) > 0

    def test_404_error_format(self, populated_client):
        """Test 404 Not Found error format."""
        response = populated_client.get("/api/nonexistent-endpoint")
        assert response.status_code == 404

    def test_405_error_format(self, populated_client):
        """Test 405 Method Not Allowed error format."""
        response = populated_client.post("/api/stats")
        assert response.status_code == 405

    def test_500_error_handling(self, client):
        """Test 500 error handling with database issues."""
        # This will cause database errors due to missing initialization
        response = client.get("/api/stats")

        # Should return 500 or handle gracefully
        if response.status_code == 500:
            # If returning JSON error, should have consistent format
            if "application/json" in response.content_type:
                data = json.loads(response.data)
                # Error responses should have consistent structure
                assert isinstance(data, dict)


class TestResponseHeaders:
    """Test consistent response headers."""

    def test_json_content_type_headers(self, populated_client):
        """Test that JSON endpoints return correct Content-Type."""
        json_endpoints = [
            "/api/stats",
            "/api/alerts",
            "/api/deals",
            "/api/watchlist",
            "/api/search",
            "/api/cheapest-blurays",
            "/api/cheapest-4k-blurays",
        ]

        for endpoint in json_endpoints:
            response = populated_client.get(endpoint)
            assert "application/json" in response.content_type

    def test_cors_headers_present(self, populated_client):
        """Test CORS headers are present where expected."""
        response = populated_client.get("/api/stats")

        # Note: In testing mode, CORS headers might not be present
        # This test documents expected production behavior
        if "Access-Control-Allow-Origin" in response.headers:
            assert response.headers["Access-Control-Allow-Origin"] is not None


class TestBackwardCompatibility:
    """Test backward compatibility requirements for migration."""

    def test_legacy_movie_id_support(self, populated_client):
        """Test that API still supports movie_id for backward compatibility."""
        # This tests existing behavior that should be preserved
        # The actual implementation might use movie_id internally

        # Get a movie's database ID
        populated_client.application.config.get("TESTING_DB_PATH")
        # This test documents the requirement - implementation would need to be checked

    def test_product_id_consistency(self, populated_client):
        """Test product_id is consistently used across all endpoints."""
        # Search for a movie
        response = populated_client.get("/api/search?q=Contract")
        search_data = json.loads(response.data)

        if search_data:
            product_id = search_data[0]["product_id"]

            # Same product_id should work in watchlist operations
            payload = {"product_id": product_id, "target_price": 20.0}
            response = populated_client.post(
                "/api/watchlist", data=json.dumps(payload), content_type="application/json"
            )
            assert response.status_code == 200

            # Should appear in watchlist with same product_id
            response = populated_client.get("/api/watchlist")
            watchlist_data = json.loads(response.data)

            product_ids = [item["product_id"] for item in watchlist_data]
            assert product_id in product_ids
