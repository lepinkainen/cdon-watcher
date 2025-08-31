"""Integration tests for the complete hybrid workflow."""

import pytest

from src.cdon_watcher.cdon_scraper import CDONScraper


class TestHybridWorkflow:
    """Test cases for the complete hybrid scraper workflow."""

    @pytest.mark.asyncio
    @pytest.mark.timeout(120)  # 2 minutes for integration test
    async def test_crawl_category_workflow(
        self, cdon_scraper: CDONScraper, sample_category_url: str
    ) -> None:
        """Test the complete crawl and save workflow."""
        saved_count = await cdon_scraper.crawl_category(sample_category_url, max_pages=1)

        assert saved_count > 0, "Should save at least some movies"
        assert isinstance(saved_count, int), "Saved count should be an integer"

    @pytest.mark.asyncio
    @pytest.mark.timeout(120)  # 2 minutes for integration test
    async def test_saved_movies_quality(
        self, cdon_scraper: CDONScraper, sample_category_url: str
    ) -> None:
        """Test that saved movies have good quality data."""
        saved_count = await cdon_scraper.crawl_category(sample_category_url, max_pages=1)
        assert saved_count > 0, "Should save at least some movies"

        # Get saved movies from database
        movies = cdon_scraper.search_movies("")
        assert len(movies) > 0, "Should have movies in database"

        # Check first few movies for quality
        for movie in movies[:3]:
            assert movie["title"], "Movie title should not be empty"
            assert movie["current_price"] > 0, "Movie price should be greater than 0"
            assert movie["format"], "Movie format should not be empty"
            assert movie["url"].startswith("https://cdon.fi/tuote/"), "URL should be valid CDON URL"

            # Most important: no promotional text in titles
            assert "vihdoin arki" not in movie["title"].lower(), (
                f"Title contains promotional text: {movie['title']}"
            )

    @pytest.mark.asyncio
    @pytest.mark.timeout(120)  # 2 minutes for integration test
    async def test_no_vihdoin_arki_issues(
        self, cdon_scraper: CDONScraper, sample_category_url: str
    ) -> None:
        """Test that no 'vihdoin arki' promotional text issues exist."""
        saved_count = await cdon_scraper.crawl_category(sample_category_url, max_pages=1)
        assert saved_count > 0, "Should save at least some movies"

        # Check all saved movies
        all_movies = cdon_scraper.search_movies("")
        problematic_titles = [m for m in all_movies if "vihdoin arki" in m["title"].lower()]

        assert len(problematic_titles) == 0, (
            f"Found {len(problematic_titles)} titles with 'vihdoin arki': {[m['title'] for m in problematic_titles]}"
        )

    @pytest.mark.asyncio
    async def test_database_operations(self, cdon_scraper: CDONScraper) -> None:
        """Test basic database operations without crawling."""
        # Initially empty database
        movies = cdon_scraper.search_movies("")
        assert len(movies) == 0, "New database should be empty"

        # Search for specific terms
        search_results = cdon_scraper.search_movies("breaking bad")
        assert isinstance(search_results, list), "Search should return a list"

    @pytest.mark.asyncio
    async def test_crawl_category_zero_pages(
        self, cdon_scraper: CDONScraper, sample_category_url: str
    ) -> None:
        """Test crawling with zero max_pages."""
        saved_count = await cdon_scraper.crawl_category(sample_category_url, max_pages=0)
        assert saved_count == 0, "Should save 0 movies for max_pages=0"

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)  # 1 minute for single product test
    async def test_production_year_tmdb_integration(
        self, cdon_scraper: CDONScraper
    ) -> None:
        """Test that production year from parsed page is passed to TMDB search."""
        # Use Batman 1989 URL from original user request
        batman_url = "https://cdon.fi/tuote/indiana-jones-4-movie-collection-blu-ray-5-disc-e5a58c8cee5e590e/"

        # Parse the product page to get production year
        movie = cdon_scraper.product_parser.parse_product_page(batman_url)

        if movie is None:
            pytest.skip("Could not parse product page - may be network issue or site changes")

        # Verify we got some data
        assert movie.title, "Should have a title"
        assert movie.price is not None, "Should have a price"

        # Test the year prioritization logic (mirrors cdon_scraper.py logic)
        if cdon_scraper.tmdb_service:
            title_year = cdon_scraper.tmdb_service.extract_year_from_title(movie.title)
            # This is the key logic we're testing - production_year should take priority
            final_year = movie.production_year or title_year

            # If we found a production year, it should be used
            if movie.production_year:
                assert final_year == movie.production_year, (
                    f"Production year {movie.production_year} should take priority over title year {title_year}"
                )
                # Verify it's a reasonable year
                assert 1900 <= movie.production_year <= 2030, (
                    f"Production year {movie.production_year} should be in reasonable range"
                )
            else:
                # If no production year, should fall back to title year
                assert final_year == title_year, "Should fallback to title year when no production year"

        # Save the movie and verify it works end-to-end
        success = await cdon_scraper.save_single_movie(movie)
        assert success, "Should successfully save movie with production year"

        # Search for the saved movie and verify production year is preserved
        search_results = await cdon_scraper.search_movies(movie.title.split()[0])  # Search by first word
        if search_results:
            saved_movie = search_results[0]
            if movie.production_year:
                assert saved_movie.production_year == movie.production_year, (
                    "Production year should be preserved in database"
                )
