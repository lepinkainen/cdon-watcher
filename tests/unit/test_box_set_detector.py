"""Unit tests for box set detection."""

import pytest

from cdon_watcher.box_set_detector import is_box_set


class TestIsBoxSet:
    """Tests for is_box_set function."""

    # Collection patterns
    @pytest.mark.parametrize(
        "title",
        [
            "Indiana Jones 4-Movie Collection (Blu-ray)",
            "Star Wars 9-Movie Collection (4K Ultra HD)",
            "The Lord of the Rings 3-Film Collection",
            "Harry Potter 8-Movie Collection",
            "Fast & Furious 10-Movie Collection",
        ],
    )
    def test_movie_collection_patterns(self, title: str) -> None:
        """Test detection of N-movie collection patterns."""
        assert is_box_set(title) is True

    # Complete series/collection patterns
    @pytest.mark.parametrize(
        "title",
        [
            "Breaking Bad - Complete Series (Blu-ray)",
            "Game of Thrones - The Complete Collection (8 Seasons)",
            "Avatar - The Last Airbender - The Complete Collection (Blu-ray) (9 disc)",
            "Dexter: Complete Seasons 1-8 (Blu-ray)",
            "12 Monkeys: The Complete Series (Blu-ray) (8 disc)",
        ],
    )
    def test_complete_series_patterns(self, title: str) -> None:
        """Test detection of complete series patterns."""
        assert is_box_set(title) is True

    # Season range patterns
    @pytest.mark.parametrize(
        "title",
        [
            "Lost - Season 1-6 (Blu-ray)",
            "House of the Dragon Seasons 1 & 2 (4K Ultra HD)",
            "The Office - Seasons 1-9 (DVD)",
            "Friends - Season 1-10 Complete Box",
        ],
    )
    def test_season_range_patterns(self, title: str) -> None:
        """Test detection of season range patterns."""
        assert is_box_set(title) is True

    # Finnish patterns
    @pytest.mark.parametrize(
        "title",
        [
            "Breaking Bad - Kaudet 1-5 (Blu-ray)",
            "Dexter - kaudet 1-8 Complete Box",
            "Frendit - Kausi 1-10 (DVD)",
        ],
    )
    def test_finnish_patterns(self, title: str) -> None:
        """Test detection of Finnish season patterns."""
        assert is_box_set(title) is True

    # High disc count patterns
    @pytest.mark.parametrize(
        "title",
        [
            "Star Trek TNG (41 disc) (Blu-ray)",
            "The Sopranos (28 disc) (Blu-ray)",
            "Lost Complete Box (36 disc) (Import)",
            "James Bond Collection (5 disc)",
        ],
    )
    def test_high_disc_count_patterns(self, title: str) -> None:
        """Test detection of high disc count patterns."""
        assert is_box_set(title) is True

    # Named set patterns
    @pytest.mark.parametrize(
        "title",
        [
            "The Dark Knight Trilogy (Blu-ray)",
            "Alien Quadrilogy (Blu-ray)",
            "The Godfather Trilogy Box Set (4K Ultra HD)",
            "Star Wars Saga Collection (Blu-ray)",
            "Jurassic Park Anthology (Blu-ray)",
            "Alien Pentalogy (Blu-ray)",
            "Marvel Avengers 6-Pack (Blu-ray)",
        ],
    )
    def test_named_set_patterns(self, title: str) -> None:
        """Test detection of named set patterns (trilogy, etc.)."""
        assert is_box_set(title) is True

    # NOT box sets (individual movies)
    @pytest.mark.parametrize(
        "title",
        [
            "Avatar (2009) (Blu-ray)",
            "The Matrix (4K Ultra HD + Blu-ray)",
            "Inception (Blu-ray)",
            "Star Wars: A New Hope (4K Ultra HD)",
            "Breaking Bad - Season 1 (Blu-ray)",
            "House of the Dragon - Kausi 2 (Blu-ray)",
            "Lost - Season 3 (Blu-ray)",
            "The Office - Season 5 (DVD)",
            "Game of Thrones - Season 8 (Blu-ray)",
            "Batman Begins (2 disc) (Blu-ray)",  # Low disc count
            "Interstellar (3 disc) (4K Ultra HD)",  # Low disc count
        ],
    )
    def test_not_box_sets(self, title: str) -> None:
        """Test that individual movies are not detected as box sets."""
        assert is_box_set(title) is False

    # Edge cases
    def test_empty_title(self) -> None:
        """Test empty title returns False."""
        assert is_box_set("") is False

    def test_case_insensitivity(self) -> None:
        """Test that detection is case-insensitive."""
        assert is_box_set("COMPLETE SERIES") is True
        assert is_box_set("complete series") is True
        assert is_box_set("Complete Series") is True
        assert is_box_set("TRILOGY") is True
        assert is_box_set("trilogy") is True
