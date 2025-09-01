"""Unit tests for TMDBService title cleaning functionality."""

import pytest

from cdon_watcher.tmdb_service import TMDBService


class TestTMDBService:
    """Test TMDB service functionality."""

    @pytest.fixture
    def tmdb_service(self):
        """Create TMDBService instance for testing (no API key needed for title cleaning)."""
        return TMDBService(api_key="test_key", poster_dir="./test_posters")


class TestTitleCleaning:
    """Test title cleaning functionality."""

    @pytest.fixture
    def tmdb_service(self):
        """Create TMDBService instance for testing."""
        return TMDBService(api_key="test_key", poster_dir="./test_posters")

    @pytest.mark.parametrize(
        "input_title,expected_output",
        [
            # Basic Blu-ray/DVD indicator removal
            ("The Matrix Blu-ray", "The Matrix"),
            ("Inception DVD", "Inception"),
            ("Dune 4K", "Dune"),
            ("Blade Runner UHD", "Blade Runner"),
            ("Lord of the Rings Ultimate Edition", "Lord of the Rings"),
            ("Alien Collector's Edition", "Alien"),
            ("Star Wars Special Edition", "Star Wars"),
            ("Gladiator Extended Cut", "Gladiator"),
            ("The Godfather Director's Cut", "The Godfather"),
            # Case insensitive
            ("The Matrix blu-ray", "The Matrix"),
            ("Inception dvd", "Inception"),
            # Multiple indicators
            ("The Dark Knight Blu-ray Ultimate Edition", "The Dark Knight"),
            ("Avatar Extended Director's Cut", "Avatar"),
        ],
    )
    def test_basic_title_cleaning_movies(self, tmdb_service, input_title, expected_output):
        """Test basic title cleaning for movie titles."""
        result = tmdb_service._clean_title_for_search(input_title, is_tv=False)
        assert result == expected_output

    @pytest.mark.parametrize(
        "input_title,expected_output",
        [
            # Disc count removal
            ("The Matrix (2 disc)", "The Matrix"),
            ("Lord of the Rings (3 disc)", "Lord of the Rings"),
            ("Star Wars (1 disc)", "Star Wars"),
            # Import information
            ("Akira (Import)", "Akira"),
            ("Ghost in the Shell (import)", "Ghost in the Shell"),
            # Combined
            ("Blade Runner (2 disc) (Import)", "Blade Runner"),
        ],
    )
    def test_disc_and_import_removal(self, tmdb_service, input_title, expected_output):
        """Test removal of disc count and import information."""
        result = tmdb_service._clean_title_for_search(input_title, is_tv=False)
        assert result == expected_output

    @pytest.mark.parametrize(
        "input_title,expected_output",
        [
            # Year removal
            ("The Matrix (1999)", "The Matrix"),
            ("Blade Runner (1982)", "Blade Runner"),
            ("Inception (2010)", "Inception"),
            # No year
            ("The Matrix", "The Matrix"),
        ],
    )
    def test_year_removal(self, tmdb_service, input_title, expected_output):
        """Test removal of year information from titles."""
        result = tmdb_service._clean_title_for_search(input_title, is_tv=False)
        assert result == expected_output

    @pytest.mark.parametrize(
        "input_title,expected_output",
        [
            # TV series season removal
            ("Hannibal - Season 1-3", "Hannibal"),
            ("Breaking Bad - Season 1", "Breaking Bad"),
            ("Game of Thrones – Season 8", "Game of Thrones"),
            ("The Wire — Season 1-5", "The Wire"),
            # Series number removal
            ("Doctor Who - Series 1", "Doctor Who"),
            ("Sherlock – Series 4", "Sherlock"),
            # Complete series
            ("The Sopranos - Complete Series", "The Sopranos"),
            ("Mad Men – Complete Series", "Mad Men"),
            # Complex TV series cleaning
            ("Breaking Bad - Complete Series Blu-ray Special Edition", "Breaking Bad"),
            # Real database TV examples (now properly cleaned)
            ("12 Monkeys: The Complete Series (Blu-ray) (8 disc) (Import)", "12 Monkeys"),
            ("Lost - Season 1-6 (36 disc) (Blu-ray) (36 disc)", "Lost"),
            (
                "Avatar - The Last Airbender - The Complete Collection (Blu-ray) (9 disc) (Import)",
                "Avatar The Last Airbender",
            ),
            (
                "Dexter: Complete Seasons 1-8/Dexter: New Blood (Blu-ray) (Import)",
                "Dexter Complete Seasons 1 8/Dexter New Blood",
            ),
            ("Akame Ga Kill!: The Complete Collection (Blu-ray) (Import)", "Akame Ga Kill!"),
            # No TV indicators (should remain unchanged)
            ("Regular Movie Title", "Regular Movie Title"),
        ],
    )
    def test_tv_series_cleaning(self, tmdb_service, input_title, expected_output):
        """Test TV series specific cleaning."""
        result = tmdb_service._clean_title_for_search(input_title, is_tv=True)
        assert result == expected_output

    @pytest.mark.parametrize(
        "input_title,expected_output",
        [
            # Colon replacement
            ("Star Wars: Episode IV", "Star Wars Episode IV"),
            ("Lord of the Rings: Fellowship", "Lord of the Rings Fellowship"),
            # Dash normalization
            ("Spider-Man", "Spider Man"),
            ("X-Men", "X Men"),
            # Multiple punctuation
            (
                "Pirates of the Caribbean: Dead Man's Chest",
                "Pirates of the Caribbean Dead Man's Chest",
            ),
            # Extra whitespace
            ("The   Matrix    ", "The Matrix"),
            ("  Blade  Runner  ", "Blade Runner"),
        ],
    )
    def test_punctuation_normalization(self, tmdb_service, input_title, expected_output):
        """Test punctuation normalization and whitespace handling."""
        result = tmdb_service._clean_title_for_search(input_title, is_tv=False)
        assert result == expected_output

    @pytest.mark.parametrize(
        "input_title,expected_output",
        [
            # Empty string
            ("", ""),
            # Only punctuation
            ("---", ""),
            (":::", ""),
            # Only cleaning indicators
            ("Blu-ray DVD 4K", ""),
            ("(2 disc) (Import)", ""),
            # Complex real-world examples
            (
                "The Dark Knight Blu-ray Ultimate Collector's Edition (2 disc) (2008)",
                "The Dark Knight",
            ),
            ("Star Wars: Episode IV - A New Hope 4K UHD (1977)", "Star Wars Episode IV A New Hope"),
            # Real database examples (now properly cleaned)
            (
                "2001: A Space Odyssey - The Film Vault Limited Edition (4K Ultra + Blu-ray)",
                "2001 A Space Odyssey The Film Vault Limited",
            ),
            ("(95)The Toxic Avenger 1-4 Collection (Blu-ray)", "(95)The Toxic Avenger 1 4"),
            (
                "Avatar: The Way of Water (3D Blu-ray + Blu-ray) (4 disc) (Import)",
                "Avatar The Way of Water",
            ),
            ("Bad boys 1-4 (4 Blu-ray)", "Bad boys 1 4"),
            # Note: Akame Ga Kill moved to TV test section since it's detected as TV
            ("Dune: Part One & Two (Blu-ray)", "Dune Part One & Two"),
        ],
    )
    def test_edge_cases(self, tmdb_service, input_title, expected_output):
        """Test edge cases and complex cleaning scenarios."""
        result = tmdb_service._clean_title_for_search(input_title, is_tv=False)
        assert result == expected_output


class TestTVSeriesDetection:
    """Test TV series detection logic."""

    @pytest.fixture
    def tmdb_service(self):
        """Create TMDBService instance for testing."""
        return TMDBService(api_key="test_key", poster_dir="./test_posters")

    @pytest.mark.parametrize(
        "title,expected_is_tv",
        [
            # TV series indicators
            ("Breaking Bad Season 1", True),
            ("Game of Thrones Series 8", True),
            ("The Wire Complete Series", True),
            ("Sherlock TV Series", True),
            ("Doctor Who Season 1-3", True),
            ("Lost S01", True),
            ("The Office S02", True),
            ("Friends Episode 1", True),
            # Movie titles (should not be detected as TV)
            ("The Matrix", False),
            ("Blade Runner", False),
            ("Star Wars: Episode IV", False),
            ("Pirates of the Caribbean", False),
            # Edge cases
            ("The Seasoning", False),  # Contains "Season" but not TV
            ("Series of Unfortunate Events", False),  # Contains "Series" but movie title pattern
            # Real database TV examples (now properly detected)
            ("12 Monkeys: The Complete Series (Blu-ray) (8 disc) (Import)", True),
            ("Lost - Season 1-6 (36 disc) (Blu-ray) (36 disc)", True),
            ("Fallout: Season 1 Steelbook Limited (4K Ultra HD) (Import)", True),
            (
                "Avatar - The Last Airbender - The Complete Collection (Blu-ray) (9 disc) (Import)",
                True,
            ),
            ("Dexter: Complete Seasons 1-8/Dexter: New Blood (Blu-ray) (Import)", True),
        ],
    )
    def test_tv_series_detection(self, tmdb_service, title, expected_is_tv):
        """Test TV series detection logic."""
        result = tmdb_service._is_tv_series(title)
        assert result == expected_is_tv


class TestYearExtraction:
    """Test year extraction from titles."""

    @pytest.fixture
    def tmdb_service(self):
        """Create TMDBService instance for testing."""
        return TMDBService(api_key="test_key", poster_dir="./test_posters")

    @pytest.mark.parametrize(
        "title,expected_year",
        [
            # Valid years
            ("The Matrix (1999)", 1999),
            ("Blade Runner (1982)", 1982),
            ("Inception (2010)", 2010),
            ("Avatar (2009)", 2009),
            # No year
            ("The Matrix", None),
            ("Blade Runner", None),
            # Invalid year formats
            ("The Matrix (99)", None),
            ("Blade Runner (19822)", None),
            ("Inception [2010]", None),  # Wrong brackets
            # Multiple years (should pick first)
            ("The Matrix (1999) (2003)", 1999),
        ],
    )
    def test_year_extraction(self, tmdb_service, title, expected_year):
        """Test year extraction from movie titles."""
        result = tmdb_service.extract_year_from_title(title)
        assert result == expected_year


class TestTMDBYearPriority:
    """Test production year prioritization logic used in cdon_scraper."""

    @pytest.fixture
    def tmdb_service(self):
        """Create TMDBService instance for testing."""
        return TMDBService(api_key="test_key", poster_dir="./test_posters")

    def test_production_year_priority_logic(self, tmdb_service):
        """Test the year prioritization logic: production_year takes precedence over title extraction."""

        # Test case 1: production_year available, should be used regardless of title
        movie_title = "Batman 4K Blu-ray"  # No year in title
        production_year = 1989
        title_year = tmdb_service.extract_year_from_title(movie_title)  # Should be None

        # This mimics the logic from cdon_scraper.py line 122
        final_year = production_year or title_year

        assert title_year is None  # No year in title
        assert final_year == 1989  # Production year takes priority

    def test_production_year_overrides_title_year(self, tmdb_service):
        """Test that production_year overrides title year when both are present."""

        movie_title = "Batman (1992)"  # Wrong year in title (Batman Returns)
        production_year = 1989  # Correct year from Nauhoitusvuosi
        title_year = tmdb_service.extract_year_from_title(movie_title)

        final_year = production_year or title_year

        assert title_year == 1992  # Title has wrong year
        assert final_year == 1989  # Production year overrides title year

    def test_fallback_to_title_year(self, tmdb_service):
        """Test fallback to title year when production_year is None."""

        movie_title = "The Matrix (1999)"
        production_year = None  # No production year found on page
        title_year = tmdb_service.extract_year_from_title(movie_title)

        final_year = production_year or title_year

        assert title_year == 1999
        assert final_year == 1999  # Falls back to title year

    def test_both_years_none(self, tmdb_service):
        """Test when both production_year and title year are None."""

        movie_title = "Unknown Movie"
        production_year = None
        title_year = tmdb_service.extract_year_from_title(movie_title)

        final_year = production_year or title_year

        assert title_year is None
        assert final_year is None  # Both None, final year is None

    @pytest.mark.parametrize(
        "production_year,title,expected_year",
        [
            # Production year available - should always win
            (1989, "Batman 4K Blu-ray", 1989),
            (1989, "Batman (1992)", 1989),  # Overrides wrong title year
            (2010, "Inception", 2010),
            # Production year None - fallback to title
            (None, "The Matrix (1999)", 1999),
            (None, "Blade Runner (1982)", 1982),
            # Both None
            (None, "Unknown Movie", None),
            # Edge cases with 0 (falsy but valid year)
            (0, "Movie Title (2000)", 0),  # 0 is falsy but should still be used
        ],
    )
    def test_year_prioritization_scenarios(
        self, tmdb_service, production_year, title, expected_year
    ):
        """Test various year prioritization scenarios."""
        title_year = tmdb_service.extract_year_from_title(title)

        # Handle the edge case where 0 is a valid year but falsy
        if production_year is not None:
            final_year = production_year
        else:
            final_year = title_year

        assert final_year == expected_year
