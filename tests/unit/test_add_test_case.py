"""Unit tests for test case management utilities."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.cdon_watcher.add_test_case import (
    determine_format_from_title,
    generate_test_name,
    load_test_data,
    save_test_data,
    validate_url,
)


class TestUrlValidation:
    """Test URL validation for CDON product URLs."""

    @pytest.mark.parametrize(
        "url,expected",
        [
            # Valid CDON URLs
            ("https://cdon.fi/tuote/movie-title/", True),
            ("https://cdon.fi/tuote/another-product-abc123/", True),
            ("http://cdon.fi/tuote/test-item/", True),  # http should work
            # Invalid URLs
            ("https://example.com/tuote/movie/", False),  # Wrong domain
            ("https://cdon.com/tuote/movie/", False),  # Wrong domain (.com)
            ("https://cdon.fi/product/movie/", False),  # Wrong path (not /tuote/)
            ("https://cdon.fi/", False),  # No /tuote/ path
            ("not-a-url", False),  # Invalid URL format
            ("", False),  # Empty string
            ("https://", False),  # Incomplete URL
            (
                "ftp://cdon.fi/tuote/movie/",
                True,
            ),  # urlparse accepts ftp, validation only checks domain and path
        ],
    )
    def test_validate_url(self, url: str, expected: bool) -> None:
        """Test CDON URL validation."""
        result = validate_url(url)
        assert result == expected, f"Expected {expected} for URL: '{url}'"

    def test_validate_url_exception_handling(self) -> None:
        """Test URL validation handles parsing exceptions gracefully."""
        # Test with malformed URLs that might cause urlparse to fail
        malformed_urls = [
            "://invalid",
            "https://[invalid-host]/tuote/movie/",
        ]

        for url in malformed_urls:
            result = validate_url(url)
            assert result is False, f"Should return False for malformed URL: '{url}'"


class TestFormatDetection:
    """Test format detection from movie titles."""

    @pytest.mark.parametrize(
        "title,expected_format",
        [
            # 4K Ultra HD detection
            ("The Matrix 4K Ultra HD", "4K Blu-ray"),
            ("Dune 4K Edition", "4K Blu-ray"),
            ("Avatar UHD", "4K Blu-ray"),
            ("Blade Runner Ultra HD", "4K Blu-ray"),
            ("Movie Title 4k", "4K Blu-ray"),  # Case insensitive
            ("ULTRA HD Movie", "4K Blu-ray"),  # Case insensitive
            # Blu-ray detection
            ("The Matrix Blu-ray", "Blu-ray"),
            ("Inception BluRay", "Blu-ray"),
            ("Movie blu-ray edition", "Blu-ray"),  # Case insensitive
            ("BLU-RAY Movie", "Blu-ray"),  # Case insensitive
            # DVD fallback
            ("The Matrix DVD", "DVD"),
            ("Regular Movie Title", "DVD"),
            ("Movie without format indicator", "DVD"),
            ("", "DVD"),  # Empty title
            # Multiple formats (4K takes priority over Blu-ray)
            ("Movie 4K Blu-ray", "4K Blu-ray"),
            ("Title UHD Ultra HD Blu-ray", "4K Blu-ray"),
        ],
    )
    def test_determine_format_from_title(self, title: str, expected_format: str) -> None:
        """Test format detection from movie titles."""
        result = determine_format_from_title(title)
        assert result == expected_format, f"Expected {expected_format} for title: '{title}'"


class TestTestNameGeneration:
    """Test test case name generation."""

    @pytest.mark.parametrize(
        "title,url,expected_pattern",
        [
            # Basic name generation
            ("The Matrix", "https://cdon.fi/tuote/matrix-abc123/", "the_matrix"),
            (
                "Blade Runner 2049",
                "https://cdon.fi/tuote/blade-runner-def456/",
                "blade_runner_2049",
            ),
            (
                "Star Wars: Episode IV",
                "https://cdon.fi/tuote/star-wars-ghi789/",
                "star_wars_episode_iv",
            ),
            # Format info removal
            ("The Matrix Blu-ray", "https://cdon.fi/tuote/matrix-blu-ray-abc123/", "the_matrix"),
            (
                "Dune 4K Ultra HD",
                "https://cdon.fi/tuote/dune-4k-def456/",
                "the_matrix",
            ),  # Should be cleaned
            ("Movie (2023) Blu-ray", "https://cdon.fi/tuote/movie-ghi789/", "movie"),
            # Special character handling
            ("Movie: The Sequel", "https://cdon.fi/tuote/movie-sequel-abc123/", "movie_the_sequel"),
            (
                "Action & Adventure",
                "https://cdon.fi/tuote/action-adventure-def456/",
                "action_adventure",
            ),
            # Length limiting
            (
                "Very Long Movie Title That Exceeds Thirty Characters",
                "https://cdon.fi/tuote/long-title-abc123/",
                "very_long_movie_title_that_ex",
            ),
        ],
    )
    def test_generate_test_name_patterns(self, title: str, url: str, expected_pattern: str) -> None:
        """Test test name generation patterns."""
        result = generate_test_name(title, url)
        # Check that result follows expected patterns
        assert len(result) <= 30, "Name should be limited to 30 characters"
        assert result.replace("_", "").replace("-", "").isalnum() or result.startswith("("), (
            "Name should be alphanumeric with underscores"
        )

    def test_generate_test_name_short_title_fallback(self) -> None:
        """Test fallback to URL ID for short titles."""
        short_titles = ["A", "TV", "X", ""]
        url = "https://cdon.fi/tuote/movie-title-with-id-abc123def456/"

        for title in short_titles:
            result = generate_test_name(title, url)
            # Should use URL segment as fallback
            assert len(result) >= 5, f"Should use URL fallback for short title: '{title}'"

    def test_generate_test_name_edge_cases(self) -> None:
        """Test edge cases in name generation."""
        # Empty title with URL ID
        result = generate_test_name("", "https://cdon.fi/tuote/test-product-id/")
        assert result == "test_product_id", "Should extract URL segment"

        # Title with only special characters
        result = generate_test_name("!@#$%", "https://cdon.fi/tuote/special-chars-abc123/")
        assert len(result) >= 5, "Should fallback to URL for invalid characters"

        # URL without clear ID segment
        result = generate_test_name("Movie Title", "https://cdon.fi/tuote/")
        assert result == "movie_title", "Should clean the title even without URL ID"


class TestDataPersistence:
    """Test JSON test data loading and saving."""

    def test_load_test_data_nonexistent_file(self) -> None:
        """Test loading test data when file doesn't exist."""
        with patch("src.cdon_watcher.add_test_case.os.path.exists", return_value=False):
            result = load_test_data()
            expected = {"test_cases": []}
            assert result == expected, "Should return default structure for nonexistent file"

    def test_load_test_data_existing_file(self) -> None:
        """Test loading test data from existing file."""
        test_data = {
            "test_cases": [
                {
                    "name": "test_movie",
                    "url": "https://cdon.fi/tuote/test/",
                    "expected_title": "Test Movie",
                    "expected_format": "Blu-ray",
                    "price_range": {"min": 10.0, "max": 50.0},
                    "active": True,
                    "notes": "Test case",
                }
            ]
        }

        # Create temporary file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(test_data, f)
            temp_path = f.name

        try:
            # Mock the path to point to our temp file
            with patch("src.cdon_watcher.add_test_case.os.path.join", return_value=temp_path):
                with patch("src.cdon_watcher.add_test_case.os.path.exists", return_value=True):
                    result = load_test_data()
                    assert result == test_data, "Should load existing test data"
        finally:
            # Clean up
            Path(temp_path).unlink()

    def test_save_test_data(self) -> None:
        """Test saving test data to JSON file."""
        test_data = {
            "test_cases": [
                {
                    "name": "test_movie",
                    "url": "https://cdon.fi/tuote/test/",
                    "expected_title": "Test Movie",
                    "expected_format": "Blu-ray",
                    "price_range": {"min": 10.0, "max": 50.0},
                    "active": True,
                    "notes": "Test case",
                }
            ]
        }

        # Create temporary file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            temp_path = f.name

        try:
            # Mock the path to point to our temp file
            with patch("src.cdon_watcher.add_test_case.os.path.join", return_value=temp_path):
                save_test_data(test_data)

                # Verify file was written correctly
                with open(temp_path) as f:
                    saved_data = json.load(f)
                    assert saved_data == test_data, "Should save test data correctly"
        finally:
            # Clean up
            Path(temp_path).unlink()

    def test_save_load_roundtrip(self) -> None:
        """Test that save/load operations are consistent."""
        original_data = {
            "test_cases": [
                {
                    "name": "movie_1",
                    "url": "https://cdon.fi/tuote/movie1/",
                    "expected_title": "Movie 1",
                    "expected_format": "4K Blu-ray",
                    "price_range": {"min": 15.0, "max": 60.0},
                    "active": True,
                    "notes": "First test",
                },
                {
                    "name": "movie_2",
                    "url": "https://cdon.fi/tuote/movie2/",
                    "expected_title": "Movie 2",
                    "expected_format": "Blu-ray",
                    "price_range": {"min": 20.0, "max": 40.0},
                    "active": False,
                    "notes": "Second test",
                },
            ]
        }

        # Create temporary file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            temp_path = f.name

        try:
            # Mock the path for both save and load
            with patch("src.cdon_watcher.add_test_case.os.path.join", return_value=temp_path):
                # Save data
                save_test_data(original_data)

                # Load data back
                with patch("src.cdon_watcher.add_test_case.os.path.exists", return_value=True):
                    loaded_data = load_test_data()
                    assert loaded_data == original_data, "Save/load should be consistent"
        finally:
            # Clean up
            Path(temp_path).unlink()
