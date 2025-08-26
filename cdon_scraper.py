import asyncio
import sqlite3
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import json
import re
from dataclasses import dataclass
from playwright.async_api import async_playwright, Page, Browser
import logging
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class Movie:
    """Data class for movie information"""
    title: str
    price: float
    original_price: Optional[float]
    url: str
    format: str  # 'Blu-ray' or '4K Blu-ray'
    availability: str
    image_url: Optional[str]
    product_id: Optional[str]

class CDONScraper:
    """Main scraper class for CDON.fi Blu-ray movies"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or os.environ.get('DB_PATH', 'cdon_movies.db')
        self.base_url = "https://cdon.fi"
        self.init_database()
        
    def init_database(self):
        """Initialize SQLite database with required tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Movies table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT UNIQUE,
                title TEXT NOT NULL,
                format TEXT,
                url TEXT,
                image_url TEXT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Price history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                movie_id INTEGER,
                price REAL,
                original_price REAL,
                availability TEXT,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (movie_id) REFERENCES movies (id)
            )
        ''')
        
        # Watchlist table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                movie_id INTEGER,
                target_price REAL,
                notify_on_availability BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (movie_id) REFERENCES movies (id)
            )
        ''')
        
        # Price alerts table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS price_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                movie_id INTEGER,
                old_price REAL,
                new_price REAL,
                alert_type TEXT,  -- 'price_drop', 'back_in_stock', 'target_reached'
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notified BOOLEAN DEFAULT 0,
                FOREIGN KEY (movie_id) REFERENCES movies (id)
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info(f"Database initialized at {self.db_path}")
    
    async def create_browser(self) -> Browser:
        """Create and configure Playwright browser instance"""
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-features=VizDisplayCompositor',
                '--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
            ]
        )
        
        # Create context with better stealth settings
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='fi-FI',
            timezone_id='Europe/Helsinki'
        )
        
        # Add stealth scripts
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
        """)
        
        page = await context.new_page()
        return browser, context, page
    
    async def scrape_page(self, page: Page, url: str) -> List[Movie]:
        """Scrape a single page for movie information"""
        movies = []
        
        try:
            logger.info(f"Navigating to {url}")
            await page.goto(url, wait_until='networkidle', timeout=30000)
            
            # Wait for page to load - try different loading indicators
            try:
                await page.wait_for_selector('a[href*="/tuote/"]', timeout=15000, state='visible')
                logger.info("Found product links")
            except:
                logger.info("Product links not found, trying alternative selectors")
                try:
                    await page.wait_for_selector('main, [data-testid="product-grid"], .products', timeout=15000)
                    logger.info("Found main content area")
                except:
                    logger.info("No specific selectors found, proceeding with page scrape")
            
            # Try multiple possible selectors for products
            product_selectors = [
                'a[href*="/tuote/"]',  # CDON product links
                '[data-testid="product-card"]',
                '.product-card',
                '.product-item',
                'article[class*="product"]',
                'div[class*="ProductCard"]'
            ]
            
            products = None
            for selector in product_selectors:
                products = await page.query_selector_all(selector)
                if products:
                    logger.info(f"Found {len(products)} products using selector: {selector}")
                    break
            
            if not products:
                logger.warning("No products found on page")
                # Debug: check what we actually have on the page
                page_content = await page.content()
                if "/tuote/" in page_content:
                    logger.info("Page contains product URLs but selectors didn't find them")
                else:
                    logger.info("Page doesn't seem to contain any product URLs")
                logger.info(f"Page title: {await page.title()}")
                return movies
            
            for product in products:
                try:
                    movie = await self.extract_movie_data(product, page)
                    if movie and self.is_bluray_format(movie.title, movie.format):
                        movies.append(movie)
                        logger.info(f"Extracted: {movie.title} - €{movie.price}")
                except Exception as e:
                    logger.error(f"Error extracting product data: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error scraping page {url}: {e}")
            
        return movies
    
    async def extract_movie_data(self, element, page: Page) -> Optional[Movie]:
        """Extract movie data from a product element"""
        try:
            # Since element is now the link itself (a[href*="/tuote/"]), extract data accordingly
            title = None
            
            # Try to get title from link text or contained paragraphs
            try:
                # Get title from link inner text (should be the movie name)
                title = await element.inner_text()
                title = title.strip()
            except:
                pass
                
            if not title:
                # Try getting from paragraph inside the link
                title_elem = await element.query_selector('p, span, div')
                if title_elem:
                    title = await title_elem.inner_text()
                    title = title.strip()
            
            if not title:
                logger.debug("No title found for product")
                return None
            
            # Extract price - look for current price in paragraphs containing €
            price_text = None
            
            # Try to find price in paragraph elements
            price_elems = await element.query_selector_all('p')
            for p_elem in price_elems:
                p_text = await p_elem.inner_text()
                if '€' in p_text and any(char.isdigit() for char in p_text):
                    price_text = p_text.strip()
                    break
            
            if not price_text:
                logger.debug(f"No price found for product: {title}")
                return None
                
            # Extract numeric price
            price = self.extract_price(price_text)
            if price is None:
                return None
            
            # Extract original price (if on sale)
            original_price = None
            original_selectors = ['.original-price', '.old-price', '[class*="original"]']
            for selector in original_selectors:
                orig_elem = await element.query_selector(selector)
                if orig_elem:
                    orig_text = await orig_elem.inner_text()
                    original_price = self.extract_price(orig_text)
                    break
            
            # Extract URL - element is the link itself
            href = await element.get_attribute('href')
            url = href if href.startswith('http') else f"{self.base_url}{href}"
            
            # Extract image URL
            image_url = None
            img = await element.query_selector('img')
            if img:
                image_url = await img.get_attribute('src') or await img.get_attribute('data-src')
            
            # Determine format from title or metadata
            format_type = self.determine_format(title)
            
            # Extract availability
            availability = "In Stock"  # Default
            avail_selectors = ['.availability', '.stock-status', '[class*="availability"]']
            for selector in avail_selectors:
                avail_elem = await element.query_selector(selector)
                if avail_elem:
                    availability = await avail_elem.inner_text()
                    break
            
            # Try to extract product ID from URL or data attributes
            product_id = None
            if url:
                # Try to extract ID from URL pattern
                id_match = re.search(r'/(\d+)(?:/|$|\?)', url)
                if id_match:
                    product_id = id_match.group(1)
            
            return Movie(
                title=title.strip(),
                price=price,
                original_price=original_price,
                url=url,
                format=format_type,
                availability=availability,
                image_url=image_url,
                product_id=product_id
            )
            
        except Exception as e:
            logger.error(f"Error in extract_movie_data: {e}")
            return None
    
    def extract_price(self, price_text: str) -> Optional[float]:
        """Extract numeric price from text"""
        try:
            # Remove currency symbols and spaces
            price_text = price_text.replace('€', '').replace('EUR', '').replace(' ', '')
            # Handle Finnish decimal separator
            price_text = price_text.replace(',', '.')
            # Extract first number
            match = re.search(r'(\d+\.?\d*)', price_text)
            if match:
                return float(match.group(1))
        except:
            pass
        return None
    
    def determine_format(self, title: str) -> str:
        """Determine if movie is Blu-ray or 4K Blu-ray"""
        title_lower = title.lower()
        if '4k' in title_lower or 'uhd' in title_lower or 'ultra hd' in title_lower:
            return '4K Blu-ray'
        elif 'blu-ray' in title_lower or 'bluray' in title_lower or 'bd' in title_lower:
            return 'Blu-ray'
        return 'DVD'  # Default fallback
    
    def is_bluray_format(self, title: str, format: str) -> bool:
        """Check if the item is a Blu-ray or 4K Blu-ray"""
        return 'Blu-ray' in format or 'blu-ray' in title.lower() or 'bluray' in title.lower()
    
    def save_movies(self, movies: List[Movie]):
        """Save movies to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for movie in movies:
            try:
                # Insert or update movie
                cursor.execute('''
                    INSERT OR IGNORE INTO movies (product_id, title, format, url, image_url)
                    VALUES (?, ?, ?, ?, ?)
                ''', (movie.product_id, movie.title, movie.format, movie.url, movie.image_url))
                
                # Get movie ID
                if movie.product_id:
                    cursor.execute('SELECT id FROM movies WHERE product_id = ?', (movie.product_id,))
                else:
                    cursor.execute('SELECT id FROM movies WHERE title = ? AND format = ?', 
                                 (movie.title, movie.format))
                
                movie_id = cursor.fetchone()
                if movie_id:
                    movie_id = movie_id[0]
                    
                    # Update last_updated timestamp
                    cursor.execute('UPDATE movies SET last_updated = CURRENT_TIMESTAMP WHERE id = ?', 
                                 (movie_id,))
                    
                    # Insert price history
                    cursor.execute('''
                        INSERT INTO price_history (movie_id, price, original_price, availability)
                        VALUES (?, ?, ?, ?)
                    ''', (movie_id, movie.price, movie.original_price, movie.availability))
                    
                    # Check for price drops
                    self.check_price_alerts(cursor, movie_id, movie.price)
                    
            except Exception as e:
                logger.error(f"Error saving movie {movie.title}: {e}")
                
        conn.commit()
        conn.close()
        logger.info(f"Saved {len(movies)} movies to database")
    
    def check_price_alerts(self, cursor, movie_id: int, new_price: float):
        """Check if price has dropped and create alerts"""
        # Get last price
        cursor.execute('''
            SELECT price FROM price_history 
            WHERE movie_id = ? 
            ORDER BY checked_at DESC 
            LIMIT 2
        ''', (movie_id,))
        
        prices = cursor.fetchall()
        if len(prices) >= 2:
            old_price = prices[1][0]
            if new_price < old_price:
                # Price dropped!
                cursor.execute('''
                    INSERT INTO price_alerts (movie_id, old_price, new_price, alert_type)
                    VALUES (?, ?, ?, 'price_drop')
                ''', (movie_id, old_price, new_price))
                logger.info(f"Price drop detected for movie {movie_id}: €{old_price} -> €{new_price}")
        
        # Check watchlist targets
        cursor.execute('SELECT target_price FROM watchlist WHERE movie_id = ?', (movie_id,))
        watchlist = cursor.fetchone()
        if watchlist and new_price <= watchlist[0]:
            cursor.execute('''
                INSERT INTO price_alerts (movie_id, old_price, new_price, alert_type)
                VALUES (?, ?, ?, 'target_reached')
            ''', (movie_id, new_price, new_price))
            logger.info(f"Target price reached for movie {movie_id}: €{new_price}")
    
    async def crawl_category(self, category_url: str, max_pages: int = 5):
        """Crawl multiple pages of a category"""
        browser, context, page = await self.create_browser()
        
        all_movies = []
        
        try:
            for page_num in range(1, max_pages + 1):
                # Construct page URL (adjust based on CDON's pagination structure)
                if '?' in category_url:
                    url = f"{category_url}&page={page_num}"
                else:
                    url = f"{category_url}?page={page_num}"
                
                movies = await self.scrape_page(page, url)
                all_movies.extend(movies)
                
                # Save after each page
                if movies:
                    self.save_movies(movies)
                
                # Respectful delay between pages
                await asyncio.sleep(2)
                
                # Check if there's a next page
                has_next = await page.query_selector('[aria-label="Next page"], .pagination-next, a[rel="next"]')
                if not has_next:
                    logger.info("No more pages to crawl")
                    break
                    
        finally:
            await browser.close()
        
        return all_movies
    
    def add_to_watchlist(self, title: str, target_price: float) -> bool:
        """Add a movie to the watchlist"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Find movie
        cursor.execute('SELECT id FROM movies WHERE title LIKE ?', (f'%{title}%',))
        movie = cursor.fetchone()
        
        if movie:
            movie_id = movie[0]
            cursor.execute('''
                INSERT OR REPLACE INTO watchlist (movie_id, target_price)
                VALUES (?, ?)
            ''', (movie_id, target_price))
            conn.commit()
            conn.close()
            logger.info(f"Added movie {movie_id} to watchlist with target price €{target_price}")
            return True
        
        conn.close()
        logger.warning(f"Movie '{title}' not found in database")
        return False
    
    def get_price_alerts(self) -> List[Dict]:
        """Get unnotified price alerts"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT a.*, m.title, m.url 
            FROM price_alerts a
            JOIN movies m ON a.movie_id = m.id
            WHERE a.notified = 0
            ORDER BY a.created_at DESC
        ''')
        
        alerts = []
        for row in cursor.fetchall():
            alerts.append({
                'id': row[0],
                'movie_id': row[1],
                'old_price': row[2],
                'new_price': row[3],
                'alert_type': row[4],
                'created_at': row[5],
                'title': row[7],
                'url': row[8]
            })
        
        conn.close()
        return alerts
    
    def mark_alerts_notified(self, alert_ids: List[int]):
        """Mark alerts as notified"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for alert_id in alert_ids:
            cursor.execute('UPDATE price_alerts SET notified = 1 WHERE id = ?', (alert_id,))
        
        conn.commit()
        conn.close()
    
    def search_movies(self, query: str) -> List[Dict]:
        """Search for movies in the database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT m.*, 
                   (SELECT price FROM price_history WHERE movie_id = m.id ORDER BY checked_at DESC LIMIT 1) as current_price,
                   (SELECT MIN(price) FROM price_history WHERE movie_id = m.id) as lowest_price,
                   (SELECT MAX(price) FROM price_history WHERE movie_id = m.id) as highest_price
            FROM movies m
            WHERE m.title LIKE ?
            ORDER BY m.last_updated DESC
        ''', (f'%{query}%',))
        
        movies = []
        for row in cursor.fetchall():
            movies.append({
                'id': row[0],
                'product_id': row[1],
                'title': row[2],
                'format': row[3],
                'url': row[4],
                'current_price': row[8],
                'lowest_price': row[9],
                'highest_price': row[10]
            })
        
        conn.close()
        return movies

async def main():
    """Main function to demonstrate usage"""
    scraper = CDONScraper()
    
    # Example: Crawl Blu-ray category
    bluray_url = "https://cdon.fi/elokuvat/?facets=property_preset_media_format%3Ablu-ray&q="
    logger.info("Starting crawl of CDON Blu-ray section...")
    movies = await scraper.crawl_category(bluray_url, max_pages=3)
    logger.info(f"Crawled {len(movies)} Blu-ray movies")
    
    # Example: Add to watchlist
    scraper.add_to_watchlist("Oppenheimer", 15.00)
    
    # Example: Check for alerts
    alerts = scraper.get_price_alerts()
    for alert in alerts:
        logger.info(f"ALERT: {alert['title']} - Price dropped from €{alert['old_price']} to €{alert['new_price']}")
        print(f"View at: {alert['url']}")
    
    # Example: Search database
    results = scraper.search_movies("Star Wars")
    for movie in results:
        print(f"{movie['title']} ({movie['format']}) - Current: €{movie['current_price']}, Lowest: €{movie['lowest_price']}")

if __name__ == "__main__":
    asyncio.run(main())
