"""Unit tests for ProductParser."""

from unittest.mock import Mock, patch

import pytest
from bs4 import BeautifulSoup

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

    @patch('src.cdon_watcher.product_parser.requests.Session.get')
    def test_parse_product_page_includes_production_year(self, mock_get: Mock) -> None:
        """Test that production year is included in parsed movie data."""
        # Mock HTML response similar to Batman CDON page
        mock_html = """
        <html>
            <head><title>Batman (1989) (4K Ultra HD + Blu-ray) | CDON</title></head>
            <body>
                <h1>Batman (1989) (4K Ultra HD + Blu-ray)</h1>
                <h2>13.95 €</h2>
                <div class="product-details">
                    <div class="detail-row">
                        <p class="label">Nauhoitusvuosi</p>
                        <p class="value">1989</p>
                    </div>
                    <div class="detail-row">
                        <p class="label">Format</p>
                        <p class="value">4K Ultra HD + Blu-ray</p>
                    </div>
                </div>
                <img src="/image.jpg" alt="Batman poster" />
            </body>
        </html>
        """

        # Mock response
        mock_response = Mock()
        mock_response.content = mock_html.encode('utf-8')
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # Create parser and test
        parser = ProductParser()
        url = "https://cdon.fi/tuote/batman-1989-4k-ultra-hd-blu-ray-5cb24b79a41d59c4/"

        movie = parser.parse_product_page(url)

        # Verify movie was parsed successfully
        assert movie is not None
        assert movie.title == "Batman (1989) (4K Ultra HD + Blu-ray)"
        assert movie.price == 13.95
        assert movie.format == "4K Blu-ray"
        assert movie.production_year == 1989  # This is the key test
        assert movie.url == url
        assert movie.product_id == "5cb24b79a41d59c4"

        # Verify HTTP call was made
        mock_get.assert_called_once_with(url, timeout=10)

    @patch('src.cdon_watcher.product_parser.requests.Session.get')
    def test_parse_product_page_no_production_year(self, mock_get: Mock) -> None:
        """Test parsing when no production year is available."""
        # Mock HTML response without Nauhoitusvuosi
        mock_html = """
        <html>
            <head><title>Some Movie (Blu-ray) | CDON</title></head>
            <body>
                <h1>Some Movie (Blu-ray)</h1>
                <h2>19.99 €</h2>
                <div class="product-details">
                    <div class="detail-row">
                        <p class="label">Director</p>
                        <p class="value">Unknown</p>
                    </div>
                </div>
            </body>
        </html>
        """

        # Mock response
        mock_response = Mock()
        mock_response.content = mock_html.encode('utf-8')
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # Create parser and test
        parser = ProductParser()
        url = "https://cdon.fi/tuote/some-movie-blu-ray-abc123/"

        movie = parser.parse_product_page(url)

        # Verify movie was parsed but production_year is None
        assert movie is not None
        assert movie.title == "Some Movie (Blu-ray)"
        assert movie.price == 19.99
        assert movie.production_year is None  # No year found


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

    @pytest.mark.parametrize(
        "text,expected_year",
        [
            # Valid years
            ("1989", 1989),
            ("2024", 2024),
            ("1950", 1950),
            ("2025", 2025),
            ("Movie from 1999", 1999),
            ("Released in 2010 was great", 2010),
            ("The year 1982 version", 1982),
            # Edge cases - boundary years
            ("1900", 1900),
            ("2030", 2030),
            # Invalid years (out of range)
            ("1899", None),  # Too old
            ("2031", None),  # Too new
            ("1800", None),  # Too old
            ("2050", None),  # Too new
            # Invalid formats
            ("123", None),  # 3 digits
            ("12345", None),  # 5 digits
            ("abc", None),  # Non-numeric
            ("", None),  # Empty
            ("not-a-year", None),  # Text
            ("19.89", None),  # Decimal
            ("The Matrix", None),  # No year
            # Multiple years - should get first one
            ("Made in 1999 and remade in 2021", 1999),
            ("1985 was before 1990", 1985),
        ],
    )
    def test_extract_valid_year(
        self, parser: ProductParser, text: str, expected_year: int | None
    ) -> None:
        """Test year extraction and validation from text."""
        result = parser._extract_valid_year(text)
        assert result == expected_year, f"Expected {expected_year} for text: '{text}'"

    def test_extract_year_from_sibling_success(self, parser: ProductParser) -> None:
        """Test successful year extraction from sibling element."""
        # HTML structure based on actual CDON layout
        html = """
        <div class="product-details">
            <div class="detail-row">
                <p class="label">Nauhoitusvuosi</p>
                <p class="value">1989</p>
            </div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = parser._extract_year_from_sibling(soup)
        assert result == 1989

    def test_extract_year_from_sibling_case_insensitive(self, parser: ProductParser) -> None:
        """Test case insensitive matching of Nauhoitusvuosi."""
        html = """
        <div>
            <p>nauhoitusvuosi</p>
            <p>2024</p>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = parser._extract_year_from_sibling(soup)
        assert result == 2024

    def test_extract_year_from_sibling_no_nauhoitusvuosi(self, parser: ProductParser) -> None:
        """Test when Nauhoitusvuosi label is not found."""
        html = """
        <div>
            <p>Some other label</p>
            <p>1989</p>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = parser._extract_year_from_sibling(soup)
        assert result is None

    def test_extract_year_from_sibling_no_next_sibling(self, parser: ProductParser) -> None:
        """Test when Nauhoitusvuosi has no next sibling."""
        html = """
        <div>
            <p>Nauhoitusvuosi</p>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = parser._extract_year_from_sibling(soup)
        assert result is None

    def test_extract_year_from_sibling_wrong_sibling_tag(self, parser: ProductParser) -> None:
        """Test when next sibling is not a p tag."""
        html = """
        <div>
            <p>Nauhoitusvuosi</p>
            <div>1989</div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = parser._extract_year_from_sibling(soup)
        assert result is None

    def test_extract_year_from_sibling_invalid_year_in_sibling(self, parser: ProductParser) -> None:
        """Test when sibling contains invalid year."""
        html = """
        <div>
            <p>Nauhoitusvuosi</p>
            <p>Not a year</p>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = parser._extract_year_from_sibling(soup)
        assert result is None

    def test_extract_year_from_sibling_parent_not_p_tag(self, parser: ProductParser) -> None:
        """Test when Nauhoitusvuosi parent is not a p tag."""
        html = """
        <div>
            <span>Nauhoitusvuosi</span>
            <p>1989</p>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = parser._extract_year_from_sibling(soup)
        assert result is None

    def test_extract_year_from_container_success(self, parser: ProductParser) -> None:
        """Test successful year extraction from container div."""
        html = """
        <div class="product-info">
            <div class="detail-section">
                <span>Nauhoitusvuosi: 1989</span>
            </div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = parser._extract_year_from_container(soup)
        assert result == 1989

    def test_extract_year_from_container_case_insensitive(self, parser: ProductParser) -> None:
        """Test case insensitive matching in container."""
        html = """
        <div>
            <div>nauhoitusvuosi 2024</div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = parser._extract_year_from_container(soup)
        assert result == 2024

    def test_extract_year_from_container_multiple_divs(self, parser: ProductParser) -> None:
        """Test extraction when multiple divs exist."""
        html = """
        <div>
            <div>Some other info</div>
            <div>Director: Tim Burton</div>
            <div>Nauhoitusvuosi 1982</div>
            <div>Format: Blu-ray</div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = parser._extract_year_from_container(soup)
        assert result == 1982

    def test_extract_year_from_container_no_nauhoitusvuosi(self, parser: ProductParser) -> None:
        """Test when no div contains Nauhoitusvuosi."""
        html = """
        <div>
            <div>Director: Someone</div>
            <div>Format: DVD</div>
            <div>Price: €19.99</div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = parser._extract_year_from_container(soup)
        assert result is None

    def test_extract_year_from_container_no_valid_year(self, parser: ProductParser) -> None:
        """Test when div has Nauhoitusvuosi but no valid year."""
        html = """
        <div>
            <div>Nauhoitusvuosi: Unknown</div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = parser._extract_year_from_container(soup)
        assert result is None

    def test_extract_year_from_container_invalid_year_range(self, parser: ProductParser) -> None:
        """Test when div has Nauhoitusvuosi with invalid year range."""
        html = """
        <div>
            <div>Nauhoitusvuosi: 1800</div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = parser._extract_year_from_container(soup)
        assert result is None

    def test_extract_year_from_container_first_match(self, parser: ProductParser) -> None:
        """Test that first matching div with valid year is returned."""
        html = """
        <div>
            <div>Nauhoitusvuosi 1995</div>
            <div>Also has Nauhoitusvuosi 2000</div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = parser._extract_year_from_container(soup)
        assert result == 1995

    def test_extract_production_year_sibling_method_success(self, parser: ProductParser) -> None:
        """Test successful production year extraction via sibling method."""
        # HTML structure similar to actual Batman CDON page
        html = """
        <div class="product-details">
            <div class="detail-row">
                <p class="sc-f7e20373-0 iszHzZ">Nauhoitusvuosi</p>
                <p class="sc-f7e20373-0 ikdKWF sc-c8a3ebe2-2 jwipLi">1989</p>
            </div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = parser._extract_production_year(soup)
        assert result == 1989

    def test_extract_production_year_container_fallback_success(self, parser: ProductParser) -> None:
        """Test production year extraction via container fallback method."""
        html = """
        <div>
            <div class="info">
                <span>Director: Tim Burton</span>
            </div>
            <div class="year-info">
                Nauhoitusvuosi: 2024
            </div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = parser._extract_production_year(soup)
        assert result == 2024

    def test_extract_production_year_no_year_found(self, parser: ProductParser) -> None:
        """Test when no production year is found by any method."""
        html = """
        <div>
            <div>Director: Someone</div>
            <div>Format: Blu-ray</div>
            <div>Price: €19.99</div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = parser._extract_production_year(soup)
        assert result is None

    def test_extract_production_year_sibling_fails_container_succeeds(self, parser: ProductParser) -> None:
        """Test fallback to container method when sibling method fails."""
        html = """
        <div>
            <span>Nauhoitusvuosi</span>  <!-- Parent is not p tag, sibling method fails -->
            <div>Some other content</div>
            <div>Movie info Nauhoitusvuosi 1995</div>  <!-- Container method succeeds -->
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = parser._extract_production_year(soup)
        assert result == 1995

    def test_extract_production_year_error_handling(self, parser: ProductParser) -> None:
        """Test error handling in production year extraction."""
        # Create malformed soup that could cause errors
        html = "<invalid><broken>Nauhoitusvuosi</broken>"
        soup = BeautifulSoup(html, "html.parser")
        # Should not raise exception, should return None
        result = parser._extract_production_year(soup)
        assert result is None

    def test_extract_production_year_empty_soup(self, parser: ProductParser) -> None:
        """Test with empty BeautifulSoup object."""
        soup = BeautifulSoup("", "html.parser")
        result = parser._extract_production_year(soup)
        assert result is None
