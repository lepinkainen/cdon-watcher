"""Unit tests for ProductParser."""

import pytest

from src.cdon_watcher.product_parser import ProductParser


class TestProductParser:
    """Test cases for ProductParser functionality."""

    def test_parse_product_page_success(
        self, product_parser: ProductParser, sample_product_urls: list[str]
    ) -> None:
        """Test successful parsing of product pages."""
        for url in sample_product_urls:
            movie = product_parser.parse_product_page(url)

            assert movie is not None, f"Failed to parse {url}"
            assert movie.title, "Title should not be empty"
            assert movie.price > 0, "Price should be greater than 0"
            assert movie.format, "Format should not be empty"
            assert movie.url == url, "URL should match input"

            # Check that we don't extract promotional text
            assert "vihdoin arki" not in movie.title.lower(), (
                f"Title contains promotional text: {movie.title}"
            )

    def test_parse_product_page_invalid_url(self, product_parser: ProductParser) -> None:
        """Test parsing with invalid URL."""
        invalid_url = "https://invalid-url-that-does-not-exist.com/product/"
        movie = product_parser.parse_product_page(invalid_url)
        assert movie is None, "Should return None for invalid URL"

    def test_parse_product_page_non_cdon_url(self, product_parser: ProductParser) -> None:
        """Test parsing with non-CDON URL."""
        non_cdon_url = "https://example.com/some-product/"
        movie = product_parser.parse_product_page(non_cdon_url)
        assert movie is None, "Should return None for non-CDON URL"

    @pytest.mark.parametrize(
        "url",
        [
            "",
            "not-a-url",
            "https://",
            "ftp://cdon.fi/tuote/something/",
        ],
    )
    def test_parse_product_page_malformed_urls(
        self, product_parser: ProductParser, url: str
    ) -> None:
        """Test parsing with malformed URLs."""
        movie = product_parser.parse_product_page(url)
        assert movie is None, f"Should return None for malformed URL: {url}"
