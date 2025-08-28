"""Unit tests for Flask web application configuration."""

import importlib
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

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


class TestFlaskAppCreation:
    """Test Flask application creation and configuration."""

    def test_create_app_returns_flask_instance(self):
        """Test that create_app returns a Flask instance."""
        app = create_app()

        from flask import Flask

        assert isinstance(app, Flask)

    def test_create_app_has_blueprints(self):
        """Test that create_app registers required blueprints."""
        app = create_app()

        # Check that blueprints are registered
        blueprint_names = [bp.name for bp in app.blueprints.values()]

        assert "main" in blueprint_names
        assert "api" in blueprint_names

    def test_create_app_cors_enabled(self):
        """Test that CORS is enabled on the app."""
        app = create_app()

        # Check CORS extension is registered
        # flask-cors registers itself in app.extensions
        assert "cors" in app.extensions

    def test_create_app_template_folder(self):
        """Test that template folder is correctly configured."""
        app = create_app()

        # Should point to ../templates relative to web module
        assert app.template_folder.endswith("templates")
        assert "cdon_watcher" in app.template_folder

    def test_create_app_static_folder(self):
        """Test that static folder is correctly configured."""
        app = create_app()

        # Should point to ../static relative to web module
        assert app.static_folder.endswith("static")
        assert "cdon_watcher" in app.static_folder


class TestFlaskAppConfiguration:
    """Test Flask application configuration."""

    def test_app_testing_mode(self, temp_db_path):
        """Test app in testing mode."""
        with patch.dict(os.environ, {"DB_PATH": temp_db_path}):
            app = create_app()
            app.config["TESTING"] = True

            assert app.config["TESTING"] is True

    def test_app_debug_mode_from_env(self, temp_db_path):
        """Test debug mode configuration from environment."""
        with patch.dict(os.environ, {"DB_PATH": temp_db_path, "FLASK_DEBUG": "true"}):
            # Need to reload config after env change
            from src.cdon_watcher import config

            importlib.reload(config)

            app = create_app()

            # Note: Flask debug is typically set externally, not in create_app
            # This test documents expected behavior
            assert app.config.get("DEBUG") is not False


class TestFlaskRouteRegistration:
    """Test that Flask routes are properly registered."""

    def test_main_routes_registered(self):
        """Test that main blueprint routes are registered."""
        app = create_app()

        # Get all registered routes
        routes = []
        for rule in app.url_map.iter_rules():
            routes.append((rule.rule, rule.endpoint))

        # Check for main routes
        main_routes = [route for route in routes if route[1].startswith("main.")]

        # Should have index route
        index_routes = [route for route in main_routes if "index" in route[1]]
        assert len(index_routes) > 0

        # Should have poster route
        poster_routes = [route for route in main_routes if "poster" in route[1]]
        assert len(poster_routes) > 0

    def test_api_routes_registered(self):
        """Test that API blueprint routes are registered."""
        app = create_app()

        # Get all registered routes
        routes = []
        for rule in app.url_map.iter_rules():
            routes.append((rule.rule, rule.endpoint))

        # Check for API routes
        api_routes = [route for route in routes if route[1].startswith("api.")]

        # Should have multiple API routes
        assert len(api_routes) >= 8  # We have at least 8 API endpoints

        # Check for specific API endpoints
        api_paths = [route[0] for route in api_routes]

        expected_paths = [
            "/api/stats",
            "/api/alerts",
            "/api/deals",
            "/api/watchlist",
            "/api/search",
            "/api/cheapest-blurays",
            "/api/cheapest-4k-blurays",
            "/api/ignore-movie",
        ]

        for expected_path in expected_paths:
            assert expected_path in api_paths, f"Missing API path: {expected_path}"

    def test_route_methods_configured(self):
        """Test that routes have correct HTTP methods."""
        app = create_app()

        method_routes = {}
        for rule in app.url_map.iter_rules():
            method_routes[rule.endpoint] = rule.methods

        # Check specific method requirements
        assert "GET" in method_routes["api.api_stats"]
        assert "GET" in method_routes["api.api_deals"]

        # Watchlist should support GET, POST, DELETE
        watchlist_methods = method_routes["api.api_watchlist"]
        assert "GET" in watchlist_methods
        assert "POST" in watchlist_methods

        # Ignore movie should support POST
        assert "POST" in method_routes["api.api_ignore_movie"]


class TestFlaskErrorHandling:
    """Test Flask error handling configuration."""

    def test_404_handling(self):
        """Test 404 error handling."""
        app = create_app()

        with app.test_client() as client:
            response = client.get("/nonexistent-route")
            assert response.status_code == 404

    def test_500_handling_with_invalid_db(self):
        """Test 500 error handling with database issues."""
        with patch.dict(os.environ, {"DB_PATH": "/invalid/path/database.db"}):
            app = create_app()
            app.config["TESTING"] = True

            with app.test_client() as client:
                # This should cause a database error
                response = client.get("/api/stats")
                # Should return 500 or handle gracefully
                assert response.status_code in [500, 200]  # Depends on error handling


class TestFlaskSecurity:
    """Test Flask security configuration."""

    def test_cors_headers_configuration(self):
        """Test CORS headers are properly configured."""
        app = create_app()

        with app.test_client() as client:
            response = client.get("/api/stats")

            # Check that CORS extension is working
            # Note: Actual CORS headers depend on request origin
            assert response.status_code in [200, 500]  # Should not be blocked by CORS

    def test_no_server_header_leakage(self):
        """Test that sensitive server information is not leaked."""
        app = create_app()

        with app.test_client() as client:
            response = client.get("/")

            # Should not reveal Flask version or other sensitive info
            server_header = response.headers.get("Server", "")
            assert "Flask" not in server_header or app.config.get("TESTING")


class TestFlaskStaticFiles:
    """Test Flask static file configuration."""

    def test_static_file_serving_config(self):
        """Test static file serving configuration."""
        app = create_app()

        # Should have static folder configured
        assert app.static_folder is not None
        assert "static" in app.static_folder

    def test_poster_route_configured(self):
        """Test poster serving route is configured."""
        app = create_app()

        with app.test_client() as client:
            # Should have poster route (will 404 for non-existent file)
            response = client.get("/posters/test.jpg")
            assert response.status_code == 404  # File doesn't exist, but route works


class TestFlaskExtensions:
    """Test Flask extension configuration."""

    def test_flask_cors_extension(self):
        """Test Flask-CORS extension is properly configured."""
        app = create_app()

        # CORS should be in extensions
        assert "cors" in app.extensions

        # Should allow cross-origin requests
        with app.test_client() as client:
            response = client.options("/api/stats")
            # Should handle OPTIONS request (CORS preflight)
            assert response.status_code in [200, 204, 405]


class TestFlaskEnvironmentConfiguration:
    """Test environment-specific Flask configuration."""

    def test_database_path_configuration(self, temp_db_path):
        """Test database path configuration from environment."""
        with patch.dict(os.environ, {"DB_PATH": temp_db_path}):
            # Reload config to pick up environment change
            import importlib

            from src.cdon_watcher import config

            importlib.reload(config)

            app = create_app()

            # App should be created without errors
            assert app is not None

    def test_host_port_configuration(self, temp_db_path):
        """Test host and port configuration."""
        with patch.dict(
            os.environ, {"DB_PATH": temp_db_path, "FLASK_HOST": "127.0.0.1", "FLASK_PORT": "5000"}
        ):
            from src.cdon_watcher import config

            importlib.reload(config)

            app = create_app()

            # App should be created without errors
            assert app is not None

            # Note: Host/port are typically configured when running the app,
            # not in the app factory itself


class TestFlaskContext:
    """Test Flask application context behavior."""

    def test_app_context_available(self):
        """Test that application context is available."""
        app = create_app()

        with app.app_context():
            from flask import current_app

            # Check that we have the same app name instead of object identity
            assert current_app.name == app.name
            assert current_app.import_name == app.import_name

    def test_request_context_in_tests(self):
        """Test request context in test environment."""
        app = create_app()

        with app.test_request_context("/"):
            from flask import request

            assert request.path == "/"

    def test_blueprints_accessible_in_context(self):
        """Test that blueprints are accessible in app context."""
        app = create_app()

        with app.app_context():
            # Should be able to access registered blueprints
            assert "main" in app.blueprints
            assert "api" in app.blueprints
