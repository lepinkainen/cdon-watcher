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


class TestProductParserPureFunctions:
    """Test cases for ProductParser pure functions that don't require mocking."""

    @pytest.fixture
    def parser(self) -> ProductParser:
        """Create ProductParser instance for testing pure functions."""
        return ProductParser()

    @pytest.mark.parametrize(
        "title,expected",
        [
            # Valid titles
            ("The Matrix Blu-ray Edition", True),
            ("Inception 4K Ultra HD", True),
            ("Avatar Extended Cut", True),
            ("Star Wars Original Trilogy", True),
            ("Blade Runner 2049", True),
            # Invalid titles - too short
            ("Short", False),
            ("", False),
            ("Test", False),
            # Invalid titles - promotional text
            ("Vihdoin arki alkaa", False),
            ("Osta nyt vihdoin arki", False),
            ("Movie Title vihdoin arki edition", False),
            ("Myyty tänään 50€", False),
            ("Osta heti 19.99€", False),
            # Invalid titles - numbers or percentages
            ("50% ale", False),  # Ends with %
            ("19.99", False),  # Pure number
            ("123.45", False),  # Pure number
            # Valid titles with numbers (not pure numbers)
            ("100 pieces of movie", True),  # Contains text, not pure number
            # Edge cases - only titles ending with % are invalid
            ("Movie Title 100% Authentic", True),  # Doesn't end with %, just contains %
            ("Movie Title €19.99", False),  # Contains €
            ("Movie Title OSTA", False),  # Contains "osta"
        ],
    )
    def test_is_valid_title(self, parser: ProductParser, title: str, expected: bool) -> None:
        """Test title validation logic."""
        result = parser._is_valid_title(title)
        assert result == expected, f"Expected {expected} for title: '{title}'"

    @pytest.mark.parametrize(
        "price_text,expected",
        [
            # Standard price formats
            ("19.99€", 19.99),
            ("€29.50", 29.50),
            ("45,90 EUR", 45.90),
            ("EUR 12.99", 12.99),
            ("35€", 35.0),
            # With extra spaces and characters
            ("Price: 24.99€", 24.99),
            ("€\xa019.99", 19.99),  # Non-breaking space
            ("29,50 €", 29.50),
            ("  €  15.75  ", 15.75),
            # Finnish decimal separator
            ("19,99€", 19.99),
            ("45,90 EUR", 45.90),
            # Edge cases
            ("0€", 0.0),
            ("999.99€", 999.99),
            # Invalid formats
            ("No price here", None),
            ("", None),
            ("€", None),
            ("EUR", None),
            ("abc€def", None),
        ],
    )
    def test_extract_price_from_text(
        self, parser: ProductParser, price_text: str, expected: float | None
    ) -> None:
        """Test price extraction from text."""
        result = parser._extract_price_from_text(price_text)
        assert result == expected, f"Expected {expected} for text: '{price_text}'"

    @pytest.mark.parametrize(
        "title,expected_format",
        [
            # 4K Ultra HD detection
            ("The Matrix 4K Ultra HD", "4K Blu-ray"),
            ("Dune 4K Edition", "4K Blu-ray"),
            ("Avatar UHD", "4K Blu-ray"),
            ("Blade Runner Ultra HD", "4K Blu-ray"),
            ("Movie Title 4k", "4K Blu-ray"),  # Case insensitive
            # Blu-ray detection
            ("The Matrix Blu-ray", "Blu-ray"),
            ("Inception BluRay", "Blu-ray"),
            ("Star Wars BD", "Blu-ray"),
            ("Movie blu-ray edition", "Blu-ray"),  # Case insensitive
            # DVD fallback
            ("The Matrix DVD", "DVD"),
            ("Regular Movie Title", "DVD"),
            ("Movie without format", "DVD"),
            # Multiple formats (4K takes priority)
            ("Movie 4K Blu-ray", "4K Blu-ray"),
            ("Title UHD Ultra HD Blu-ray", "4K Blu-ray"),
        ],
    )
    def test_determine_format(
        self, parser: ProductParser, title: str, expected_format: str
    ) -> None:
        """Test format determination from title."""
        result = parser._determine_format(title)
        assert result == expected_format, f"Expected {expected_format} for title: '{title}'"

    @pytest.mark.parametrize(
        "title,format_str,expected",
        [
            # Blu-ray formats
            ("The Matrix Blu-ray", "Blu-ray", True),
            ("Movie Title", "4K Blu-ray", True),
            ("blu-ray movie", "DVD", True),  # Title contains blu-ray
            ("bluray edition", "DVD", True),  # Title contains bluray
            # Non-Blu-ray formats
            ("Movie Title", "DVD", False),
            ("Regular Movie", "DVD", False),
            ("4K Movie", "DVD", False),  # 4K alone doesn't make it Blu-ray
        ],
    )
    def test_is_bluray_format(
        self, parser: ProductParser, title: str, format_str: str, expected: bool
    ) -> None:
        """Test Blu-ray format detection."""
        result = parser.is_bluray_format(title, format_str)
        assert result == expected, (
            f"Expected {expected} for title: '{title}', format: '{format_str}'"
        )

    @pytest.mark.parametrize(
        "url,expected_id",
        [
            # Standard CDON URLs - regex extracts after last dash
            ("https://cdon.fi/tuote/movie-title-abc123def456/", "abc123def456"),
            (
                "https://cdon.fi/tuote/another-movie-xyz789abc123/",
                "789abc123",
            ),  # Extracts after last dash
            ("https://cdon.fi/tuote/test-product-deadbeef1234/", "deadbeef1234"),
            # URLs without trailing slash
            ("https://cdon.fi/tuote/movie-title-abc123def456", "abc123def456"),
            # Fallback ID extraction (hex strings)
            ("https://cdon.fi/product/abc123def456/", "abc123def456"),
            ("https://cdon.fi/item/deadbeef12345678/", "deadbeef12345678"),
            # No ID found
            ("https://cdon.fi/tuote/movie-title/", None),
            ("https://cdon.fi/", None),
            ("https://example.com/product/123/", None),
            ("invalid-url", None),
        ],
    )
    def test_extract_product_id(
        self, parser: ProductParser, url: str, expected_id: str | None
    ) -> None:
        """Test product ID extraction from URLs."""
        result = parser._extract_product_id(url)
        assert result == expected_id, f"Expected {expected_id} for URL: '{url}'"
