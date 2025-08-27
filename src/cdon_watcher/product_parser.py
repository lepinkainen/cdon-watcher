"""
Product parser for individual CDON product pages using pure Python (no Playwright)
"""

import logging
import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class Movie:
    """Data class for movie information"""

    title: str
    price: float
    original_price: float | None
    url: str
    format: str  # 'Blu-ray' or '4K Blu-ray'
    availability: str
    image_url: str | None
    product_id: str | None


class ProductParser:
    """Parser for individual CDON product pages using HTTP requests + BeautifulSoup"""

    def __init__(self) -> None:
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

    def parse_product_page(self, url: str) -> Movie | None:
        """Parse a single product page and extract movie information"""
        try:
            logger.info(f"Fetching product page: {url}")
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, "html.parser")

            # Extract components
            title = self._extract_title(soup)
            if not title:
                logger.warning(f"No title found for {url}")
                return None

            price = self._extract_price(soup)
            if price is None:
                logger.warning(f"No price found for {url}")
                return None

            original_price = self._extract_original_price(soup)
            format_type = self._determine_format(title)
            availability = self._extract_availability(soup)
            image_url = self._extract_image_url(soup)
            product_id = self._extract_product_id(url)

            return Movie(
                title=title,
                price=price,
                original_price=original_price,
                url=url,
                format=format_type,
                availability=availability,
                image_url=image_url,
                product_id=product_id,
            )

        except requests.RequestException as e:
            logger.error(f"HTTP error fetching {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error parsing {url}: {e}")
            return None

    def _extract_title(self, soup: BeautifulSoup) -> str | None:
        """Extract movie title with anti-promotional filtering"""
        # Try different title selectors in order of preference
        title_selectors = [
            "h1",  # Most likely
            "h2",
            '[data-testid*="title"]',
            ".product-title",
            ".title",
        ]

        for selector in title_selectors:
            elements = soup.select(selector)
            for element in elements:
                candidate = element.get_text(strip=True)

                # Apply the same filtering logic from the original scraper
                if self._is_valid_title(candidate):
                    logger.debug(f"Found title with selector '{selector}': {candidate}")
                    return str(candidate)

        # Fallback: try to extract from page title
        page_title = soup.find("title")
        if page_title:
            title_text = page_title.get_text(strip=True)
            # Remove " | CDON" suffix if present
            if " | " in title_text:
                candidate = title_text.split(" | ")[0].strip()
                if self._is_valid_title(candidate):
                    logger.debug(f"Found title from page title: {candidate}")
                    return str(candidate)

        return None

    def _is_valid_title(self, title: str) -> bool:
        """Check if a title candidate is valid (not promotional text)"""
        if not title or len(title) < 10:
            return False

        # Filter out promotional text and other non-title content
        promotional_terms = ["vihdoin arki", "myyty tänään", "€", "osta"]

        if any(promo in title.lower() for promo in promotional_terms):
            return False

        if title.endswith("%"):
            return False

        # Filter out pure numbers
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

    def _extract_original_price(self, soup: BeautifulSoup) -> float | None:
        """Extract original/strikethrough price if on sale"""
        original_selectors = [
            ".original-price",
            ".old-price",
            '[class*="original"]',
            "del",
            "s",
            '[style*="line-through"]',
        ]

        for selector in original_selectors:
            elements = soup.select(selector)
            for element in elements:
                price_text = element.get_text(strip=True)
                price = self._extract_price_from_text(price_text)
                if price is not None:
                    logger.debug(f"Found original price: €{price}")
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

    def _determine_format(self, title: str) -> str:
        """Determine if movie is Blu-ray or 4K Blu-ray (reuse existing logic)"""
        title_lower = title.lower()
        if "4k" in title_lower or "uhd" in title_lower or "ultra hd" in title_lower:
            return "4K Blu-ray"
        elif "blu-ray" in title_lower or "bluray" in title_lower or "bd" in title_lower:
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
            if movie.original_price:
                print(f"Original Price: €{movie.original_price}")
        else:
            print("Failed to parse")

    parser.close()
