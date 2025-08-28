"""
Listing crawler for CDON category pages using Playwright
"""

import asyncio
import logging
from typing import Any

from playwright.async_api import Browser, Page, async_playwright

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class ListingCrawler:
    """Crawler for CDON category pages to collect product URLs"""

    def __init__(self) -> None:
        self.base_url = "https://cdon.fi"

    async def create_browser(self) -> tuple[Browser, Any, Page]:
        """Create and configure Playwright browser instance (reuse existing logic)"""
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-features=VizDisplayCompositor",
                "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            ],
        )

        # Create context with better stealth settings
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="fi-FI",
            timezone_id="Europe/Helsinki",
        )

        # Add stealth scripts
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
        """)

        page = await context.new_page()
        return browser, context, page

    async def crawl_category(self, category_url: str, max_pages: int = 10) -> list[str]:
        """Crawl multiple pages of a category and return list of product URLs"""
        browser, context, page = await self.create_browser()

        all_urls = set()  # Use set to avoid duplicates
        empty_page_count = 0

        try:
            for page_num in range(1, max_pages + 1):
                # Construct page URL
                if page_num == 1:
                    # First page uses base URL without page parameter
                    url = category_url
                else:
                    # Subsequent pages add page parameter
                    if "?" in category_url:
                        url = f"{category_url}&page={page_num}"
                    else:
                        url = f"{category_url}?page={page_num}"

                logger.info(f"Crawling page {page_num}: {url}")
                urls = await self._extract_product_urls_from_page(page, url)

                if not urls:
                    empty_page_count += 1
                    logger.info(
                        f"No URLs found on page {page_num} (empty count: {empty_page_count})"
                    )
                    # Only stop after 3 consecutive empty pages
                    if empty_page_count >= 3:
                        logger.info("3 consecutive empty pages found, stopping")
                        break
                else:
                    empty_page_count = 0  # Reset counter when we find URLs
                    all_urls.update(urls)
                    logger.info(
                        f"Found {len(urls)} URLs on page {page_num}, total: {len(all_urls)}"
                    )

                # Respectful delay between pages
                await asyncio.sleep(2)

        except Exception as e:
            logger.error(f"Error during crawling: {e}")
        finally:
            await browser.close()

        return list(all_urls)

    async def _extract_product_urls_from_page(self, page: Page, url: str) -> list[str]:
        """Extract product URLs from a single listing page with retry logic"""
        max_retries = 3
        base_delay = 2  # seconds

        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    delay = base_delay * (2 ** (attempt - 1))  # exponential backoff: 2s, 4s, 8s
                    logger.info(f"Retrying page load (attempt {attempt + 1}/{max_retries + 1}) after {delay}s delay...")
                    await asyncio.sleep(delay)

                logger.debug(f"Navigating to {url}")
                await page.goto(url, wait_until="networkidle", timeout=20000)

                # Wait for product links to appear with improved stability detection
                try:
                    await page.wait_for_selector('a[href*="/tuote/"]', timeout=15000, state="visible")
                    logger.debug("Found product links")
                except Exception as e:
                    logger.warning(f"Product links not found: {e}, trying alternative selectors")
                    try:
                        await page.wait_for_selector(
                            'main, [data-testid="product-grid"], .products', timeout=15000
                        )
                        logger.debug("Found main content area")
                    except Exception as e:
                        logger.warning(f"No specific selectors found: {e}, proceeding with page scrape")

                # Add small delay to ensure content is settled after dynamic loading
                await asyncio.sleep(1)

                # Find all product links
                product_links = await page.query_selector_all('a[href*="/tuote/"]')

                if not product_links:
                    logger.warning("No product links found on page")
                    return []

                urls = []
                for link in product_links:
                    try:
                        href = await link.get_attribute("href")
                        if href:
                            # Convert relative URLs to absolute
                            if href.startswith("/"):
                                href = f"{self.base_url}{href}"

                            # Only include URLs that look like product pages
                            if "/tuote/" in href:
                                urls.append(href)
                    except Exception as e:
                        logger.debug(f"Error extracting href: {e}")
                        continue

                # Remove duplicates and sort
                unique_urls = list(set(urls))
                logger.info(f"Extracted {len(unique_urls)} unique product URLs")
                return unique_urls

            except Exception as e:
                # Check for network-related errors that should trigger retry
                error_str = str(e).lower()
                is_network_error = any(error_type in error_str for error_type in [
                    'net::err_network_changed',
                    'net::err_internet_disconnected',
                    'net::err_connection_refused',
                    'net::err_connection_reset',
                    'net::err_connection_timed_out',
                    'timeout',
                    'navigation timeout'
                ])

                if is_network_error and attempt < max_retries:
                    logger.warning(f"Network error detected (attempt {attempt + 1}/{max_retries + 1}): {e}")
                    continue  # Try again with exponential backoff
                else:
                    # Non-network error or max retries reached
                    if attempt >= max_retries:
                        logger.error(f"Max retries ({max_retries}) reached for {url}: {e}")
                    else:
                        logger.error(f"Non-network error for {url}: {e}")
                    return []

        # If we get here, all retries failed
        logger.error(f"All retry attempts failed for {url}")
        return []


# Example usage and testing
async def main() -> None:
    """Test the listing crawler"""
    crawler = ListingCrawler()

    # Test with Blu-ray category
    category_url = "https://cdon.fi/elokuvat/?facets=property_preset_media_format%3Ablu-ray&q="

    print("Testing listing crawler...")
    urls = await crawler.crawl_category(category_url, max_pages=3)

    print(f"\nFound {len(urls)} product URLs:")
    for i, url in enumerate(urls[:10], 1):  # Show first 10
        print(f"{i}. {url}")

    if len(urls) > 10:
        print(f"... and {len(urls) - 10} more URLs")


if __name__ == "__main__":
    asyncio.run(main())
