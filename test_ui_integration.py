#!/usr/bin/env python3
"""Test TMDB integration in the web UI using Playwright."""

import asyncio

from playwright.async_api import async_playwright


async def test_web_interface():
    """Test the web interface and TMDB integration."""
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        try:
            print("🌐 Testing web interface at http://localhost:8080")

            # Navigate to the web interface
            await page.goto("http://localhost:8080")

            # Wait for page to load
            await page.wait_for_selector("h1", timeout=10000)

            # Check if the page title is correct
            title = await page.title()
            print(f"✓ Page loaded: {title}")

            # Check if stats cards are visible
            stats = await page.query_selector_all(".stat-card")
            print(f"✓ Found {len(stats)} stat cards")

            # Wait for API calls to complete
            await asyncio.sleep(3)

            # Check if movie sections are present
            sections = await page.query_selector_all(".section")
            print(f"✓ Found {len(sections)} sections")

            # Look for movie cards
            movie_cards = await page.query_selector_all(".movie-card")
            print(f"✓ Found {len(movie_cards)} movie cards")

            if movie_cards:
                # Check movie cards for posters
                posters_found = 0
                for i, card in enumerate(movie_cards):
                    poster = await card.query_selector(".movie-poster")
                    if poster:
                        poster_img = await poster.query_selector("img")
                        if poster_img:
                            src = await poster_img.get_attribute("src")
                            # Check if image actually loads
                            is_visible = await poster_img.is_visible()
                            if is_visible:
                                print(f"✓ Movie {i + 1}: Poster image loaded: {src}")
                                posters_found += 1
                            else:
                                print(f"⚠ Movie {i + 1}: Poster image not visible: {src}")
                        else:
                            placeholder = await poster.query_selector(".poster-placeholder")
                            if placeholder:
                                print(f"✓ Movie {i + 1}: Poster placeholder shown")
                            else:
                                print(f"✗ Movie {i + 1}: No poster or placeholder found")
                    else:
                        print(f"✗ Movie {i + 1}: No poster container found")

                print(
                    f"📊 Summary: {posters_found}/{len(movie_cards)} movie cards have loaded poster images"
                )
            else:
                print("ℹ️  No movie cards found (database might be empty)")

            # Take a screenshot for verification
            screenshot_path = "web_interface_test.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"✓ Screenshot saved: {screenshot_path}")

            print("🎉 Web interface test completed successfully!")

        except Exception as e:
            print(f"❌ Test failed: {e}")
            # Take screenshot on error
            try:
                await page.screenshot(path="error_screenshot.png", full_page=True)
                print("🔍 Error screenshot saved: error_screenshot.png")
            except Exception:
                pass

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(test_web_interface())
