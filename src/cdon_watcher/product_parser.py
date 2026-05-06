"""
Product parser for individual CDON product pages using pure Python (no Playwright)
"""

import logging
import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

from .page_cache import PageCache, get_page_cache

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class Movie:
    """Data class for movie information"""

    title: str
    price: float
    url: str
    format: str  # 'Blu-ray' or '4K Blu-ray'
    availability: str
    image_url: str | None
    product_id: str | None
    production_year: int | None = None


class ProductParser:
    """Parser for individual CDON product pages using HTTP requests + BeautifulSoup"""

    def __init__(
        self, cache: PageCache | None = None, *, use_cache: bool = True
    ) -> None:
        """Initialize the product parser.

        Args:
            cache: Optional page cache instance. If None, uses the global cache.
            use_cache: Whether to use caching. Set to False to disable caching entirely.
        """
        self.session = requests.Session()
        # Set up realistic headers to avoid blocking
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "fi-FI,fi;q=0.8,en;q=0.6",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
            }
        )
        # Initialize cache
        if not use_cache:
            self._cache: PageCache | None = None
        else:
            self._cache = cache if cache is not None else get_page_cache()

    def _fetch_page_content(self, url: str) -> bytes | None:
        """Fetch page content, using cache if available.

        Args:
            url: The URL to fetch.

        Returns:
            Page content as bytes, or None if fetch failed.
        """
        # Check cache first
        if self._cache:
            cached_content = self._cache.get(url)
            if cached_content is not None:
                logger.info(f"Using cached page: {url}")
                return cached_content

        # Fetch from network
        logger.info(f"Fetching product page: {url}")
        response = self.session.get(url, timeout=10)
        response.raise_for_status()

        # Store in cache
        if self._cache:
            self._cache.set(url, response.content)

        return response.content

    def parse_product_page(self, url: str) -> Movie | None:
        """Parse a single product page and extract movie information"""
        try:
            content = self._fetch_page_content(url)
            if content is None:
                return None

            soup = BeautifulSoup(content, "html.parser")

            # Extract components
            title = self._extract_title(soup)
            if not title:
                logger.warning(f"No title found for {url}")
                return None

            price = self._extract_price(soup)
            if price is None:
                logger.warning(f"No price found for {url}")
                return None

            format_type = self._determine_format(title, url)
            availability = self._extract_availability(soup)
            image_url = self._extract_image_url(soup)
            product_id = self._extract_product_id(url)
            production_year = self._extract_production_year(soup)

            return Movie(
                title=title,
                price=price,
                url=url,
                format=format_type,
                availability=availability,
                image_url=image_url,
                product_id=product_id,
                production_year=production_year,
            )

        except requests.RequestException as e:
            logger.error(f"HTTP error fetching {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error parsing {url}: {e}")
            return None

    def _extract_title(self, soup: BeautifulSoup) -> str | None:
        """Extract movie title with anti-promotional filtering.

        og:title is preferred — CDON populates it with the canonical product
        name even on pages where the visible h1 is a marketing banner
        (box-set landing pages cycle through banners like
        "Elokuvaboksit, jotka luovat ikimuistoisia elokuvailtoja").
        """
        og_candidate = self._title_from_og(soup)
        if og_candidate:
            return og_candidate

        for selector in ("h1", "h2", '[data-testid*="title"]', ".product-title", ".title"):
            for element in soup.select(selector):
                candidate = element.get_text(strip=True)
                if self._is_valid_title(candidate):
                    logger.debug(f"Found title with selector '{selector}': {candidate}")
                    return str(candidate)

        return self._title_from_page_title(soup)

    def _title_from_og(self, soup: BeautifulSoup) -> str | None:
        from bs4.element import Tag

        og_title = soup.find("meta", attrs={"property": "og:title"})
        if not isinstance(og_title, Tag):
            return None
        content = og_title.get("content")
        if not isinstance(content, str):
            return None
        candidate = content.strip()
        if " | " in candidate:
            candidate = candidate.split(" | ")[0].strip()
        if self._is_valid_title(candidate):
            logger.debug(f"Found title from og:title: {candidate}")
            return candidate
        return None

    def _title_from_page_title(self, soup: BeautifulSoup) -> str | None:
        page_title = soup.find("title")
        if not page_title:
            return None
        title_text = page_title.get_text(strip=True)
        if " | " not in title_text:
            return None
        candidate = title_text.split(" | ")[0].strip()
        if self._is_valid_title(candidate):
            logger.debug(f"Found title from page title: {candidate}")
            return candidate
        return None

    # Finnish words/phrases that strongly indicate a sentence-style banner
    # rather than a product title. Movie/box titles never contain these.
    _BANNER_MARKERS = (
        "vihdoin arki",
        "myyty tänään",
        "elokuvaboksit, jotka",
        "elokuvailtoja",
        "ikimuistoisia",
        "tarjouksessa",
        "valitut tuotteet",
        "kaikki tuotteet",
        " jotka ",
        " joka luo",
        " joiden ",
    )

    def _is_valid_title(self, title: str) -> bool:
        """Reject obvious banners and noise; accept anything else."""
        if not title or len(title) < 10:
            return False

        lowered = title.lower()

        if any(marker in lowered for marker in self._BANNER_MARKERS):
            return False

        # Promotional fragments and currency lines.
        if "€" in lowered or "osta" in lowered or lowered.endswith("%"):
            return False

        # Pure-number garbage.
        if title.replace(".", "").replace(",", "").replace(" ", "").isdigit():
            return False

        return True

    def _extract_price(self, soup: BeautifulSoup) -> float | None:
        """Extract current price from the page"""
        # Try specific high-priority selectors first
        priority_selectors = [
            "h2",  # CDON seems to put main price in h2
            '[class*="price"]',
            ".price",
            '[data-testid*="price"]',
            '[class*="product-price"]',
        ]

        # Try priority selectors first
        for selector in priority_selectors:
            elements = soup.select(selector)
            for element in elements:
                text = element.get_text(strip=True)
                if "€" in text:
                    price = self._extract_price_from_text(text)
                    if price is not None and price > 5.0:  # Reasonable movie price
                        # Skip obvious non-product prices
                        if "toimitus" not in text.lower() and "shipping" not in text.lower():
                            logger.debug(f"Found price with selector '{selector}': €{price}")
                            return price

        # Fallback: look for any element containing € but filter better
        all_elements = soup.find_all(string=re.compile(r"\d+[,.]?\d*\s*€"))

        for element in all_elements:
            if element.parent:
                price_text = element.strip()
                # Skip shipping/delivery messages
                if "toimitus" in price_text.lower() or "shipping" in price_text.lower():
                    continue

                price = self._extract_price_from_text(price_text)
                if price is not None and price > 5.0:  # Reasonable movie price
                    logger.debug(f"Found price in text: €{price}")
                    return price

        return None

    def _extract_price_from_text(self, price_text: str) -> float | None:
        """Extract numeric price from text (reuse existing logic)"""
        try:
            # Remove currency symbols and spaces
            price_text = (
                price_text.replace("€", "").replace("EUR", "").replace(" ", "").replace("\xa0", "")
            )
            # Handle Finnish decimal separator
            price_text = price_text.replace(",", ".")
            # Extract first number
            match = re.search(r"(\d+\.?\d*)", price_text)
            if match:
                return float(match.group(1))
        except (ValueError, AttributeError):
            pass
        return None

    def _extract_availability(self, soup: BeautifulSoup) -> str:
        """Extract availability status"""
        availability_selectors = [
            ".availability",
            ".stock-status",
            '[class*="availability"]',
            '[class*="stock"]',
        ]

        for selector in availability_selectors:
            element = soup.select_one(selector)
            if element:
                availability = element.get_text(strip=True)
                if availability:
                    return str(availability)

        return "In Stock"  # Default assumption

    def _extract_image_url(self, soup: BeautifulSoup) -> str | None:
        """Extract product image URL"""
        # Look for product images
        img_selectors = [
            ".product-image img",
            ".product-photo img",
            '[class*="product"] img',
            "main img",
        ]

        for selector in img_selectors:
            img = soup.select_one(selector)
            if img:
                src = img.get("src") or img.get("data-src")
                if src:
                    # Convert relative URLs to absolute
                    if isinstance(src, str) and src.startswith("/"):
                        src = "https://cdon.fi" + src
                    return src if isinstance(src, str) else None

        return None

    def _extract_product_id(self, url: str) -> str | None:
        """Extract product ID from URL"""
        # CDON URLs typically end with product ID
        # e.g., /tuote/movie-title-abc123def456/
        match = re.search(r"/tuote/[^/]+-([a-f0-9]+)/?$", url)
        if match:
            return match.group(1)

        # Fallback: try to extract any ID-like string from URL
        match = re.search(r"([a-f0-9]{8,})/?$", url.rstrip("/"))
        if match:
            return match.group(1)

        return None

    def _extract_production_year(self, soup: BeautifulSoup) -> int | None:
        """Extract production year from the product details section"""
        try:
            # Method 1: Find next sibling of "Nauhoitusvuosi" label
            year = self._extract_year_from_sibling(soup)
            if year:
                return year

            # Method 2: Look for year in container with "Nauhoitusvuosi"
            year = self._extract_year_from_container(soup)
            if year:
                return year

            logger.debug("No production year found")
            return None

        except (ValueError, AttributeError, TypeError) as e:
            logger.debug(f"Error extracting production year: {e}")
            return None

    def _extract_year_from_sibling(self, soup: BeautifulSoup) -> int | None:
        """Extract year from sibling element of Nauhoitusvuosi label"""
        nauhoitusvuosi_element = soup.find(string=re.compile(r"Nauhoitusvuosi", re.IGNORECASE))
        if not nauhoitusvuosi_element:
            return None

        label_p = nauhoitusvuosi_element.parent
        if not (label_p and label_p.name == "p"):
            return None

        next_sibling = label_p.find_next_sibling()
        if not (next_sibling and next_sibling.name == "p"):
            return None

        return self._extract_valid_year(next_sibling.get_text(strip=True))

    def _extract_year_from_container(self, soup: BeautifulSoup) -> int | None:
        """Extract year from any div containing Nauhoitusvuosi"""
        divs = soup.find_all("div")
        for div in divs:
            text = div.get_text()
            if "nauhoitusvuosi" in text.lower():
                year = self._extract_valid_year(text)
                if year:
                    return year
        return None

    def _extract_valid_year(self, text: str) -> int | None:
        """Extract and validate a 4-digit year from text"""
        year_match = re.search(r"(\d{4})", text)
        if not year_match:
            return None

        year = int(year_match.group(1))
        if 1900 <= year <= 2030:  # Reasonable range for movies
            logger.debug(f"Found production year: {year}")
            return year

        return None

    def _determine_format(self, title: str, url: str = "") -> str:
        """Determine if movie is Blu-ray, 4K Blu-ray, or DVD.

        Considers both the parsed title and the product URL slug. The URL
        slug is the more reliable signal (CDON's slugs always include the
        media format), so titles that drop the format tag (common on box
        sets) still classify correctly.
        """
        haystack = f"{title} {url}".lower()
        if "4k" in haystack or "uhd" in haystack or "ultra hd" in haystack:
            return "4K Blu-ray"
        if (
            "blu-ray" in haystack
            or "bluray" in haystack
            or "blu_ray" in haystack
            or re.search(r"\bbd\b", haystack)
        ):
            return "Blu-ray"
        return "DVD"  # Default fallback

    def is_bluray_format(self, title: str, format: str) -> bool:
        """Check if the item is a Blu-ray or 4K Blu-ray (reuse existing logic)"""
        return "Blu-ray" in format or "blu-ray" in title.lower() or "bluray" in title.lower()

    def close(self) -> None:
        """Clean up the session"""
        self.session.close()


# Example usage and testing
if __name__ == "__main__":
    parser = ProductParser()

    # Test URLs
    test_urls = [
        "https://cdon.fi/tuote/indiana-jones-4-movie-collection-blu-ray-5-disc-e5a58c8cee5e590e/",
        "https://cdon.fi/tuote/a-quiet-place-day-one-blu-ray-c36f6b36e44751c4/",
        "https://cdon.fi/tuote/penguin-the-blu-ray-ee2194c5ba0057c7/",
    ]

    for url in test_urls:
        print(f"\n=== Testing: {url} ===")
        movie = parser.parse_product_page(url)
        if movie:
            print(f"Title: {movie.title}")
            print(f"Price: €{movie.price}")
            print(f"Format: {movie.format}")
            print(f"Production Year: {movie.production_year}")
        else:
            print("Failed to parse")

    parser.close()
