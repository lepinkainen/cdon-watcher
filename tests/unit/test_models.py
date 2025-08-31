"""Unit tests for SQLModel database models."""

from datetime import datetime

from src.cdon_watcher.models import (
    DealMovie,
    IgnoredMovie,
    Movie,
    MovieWithPricing,
    PriceAlert,
    PriceHistory,
    Watchlist,
    WatchlistMovie,
)


class TestMovieModel:
    """Test cases for the Movie SQLModel."""

    def test_movie_creation_with_production_year(self) -> None:
        """Test creating a Movie with production year."""
        movie = Movie(
            product_id="abc123",
            title="Batman (1989)",
            format="4K Blu-ray",
            url="https://cdon.fi/tuote/batman-abc123/",
            image_url="https://example.com/image.jpg",
            production_year=1989,
            tmdb_id=268,
            content_type="movie",
        )

        assert movie.product_id == "abc123"
        assert movie.title == "Batman (1989)"
        assert movie.format == "4K Blu-ray"
        assert movie.production_year == 1989
        assert movie.tmdb_id == 268
        assert movie.content_type == "movie"

    def test_movie_creation_without_production_year(self) -> None:
        """Test creating a Movie without production year (None)."""
        movie = Movie(
            product_id="xyz789",
            title="Unknown Movie",
            format="Blu-ray",
        )

        assert movie.product_id == "xyz789"
        assert movie.title == "Unknown Movie"
        assert movie.production_year is None  # Should default to None

    def test_movie_creation_minimal_fields(self) -> None:
        """Test creating a Movie with only required fields."""
        movie = Movie(
            product_id="minimal123",
            title="Minimal Movie",
        )

        assert movie.product_id == "minimal123"
        assert movie.title == "Minimal Movie"
        assert movie.format is None
        assert movie.production_year is None
        assert movie.tmdb_id is None

    def test_movie_defaults(self) -> None:
        """Test that Movie model has correct default values."""
        movie = Movie(
            product_id="default123",
            title="Default Movie",
        )

        assert movie.id is None  # Primary key starts as None
        assert movie.content_type == "movie"  # Default value
        assert isinstance(movie.first_seen, datetime)
        assert isinstance(movie.last_updated, datetime)


class TestViewModels:
    """Test cases for view-specific model variants."""

    def test_movie_with_pricing_includes_production_year(self) -> None:
        """Test that MovieWithPricing includes production_year field."""
        movie = MovieWithPricing(
            id=1,
            product_id="pricing123",
            title="Batman Returns",
            format="4K Blu-ray",
            url="https://example.com",
            image_url="https://example.com/image.jpg",
            production_year=1992,
            tmdb_id=364,
            content_type="movie",
            first_seen=datetime.utcnow(),
            last_updated=datetime.utcnow(),
            current_price=19.99,
            lowest_price=15.99,
            highest_price=29.99,
        )

        assert movie.production_year == 1992
        assert movie.current_price == 19.99

    def test_deal_movie_includes_production_year(self) -> None:
        """Test that DealMovie includes production_year field."""
        deal = DealMovie(
            id=2,
            product_id="deal456",
            title="The Dark Knight",
            format="Blu-ray",
            url="https://example.com",
            image_url="https://example.com/image.jpg",
            production_year=2008,
            tmdb_id=155,
            current_price=12.99,
            previous_price=19.99,
            price_change=-7.00,
            lowest_price=12.99,
            highest_price=24.99,
        )

        assert deal.production_year == 2008
        assert deal.price_change == -7.00

    def test_watchlist_movie_includes_production_year(self) -> None:
        """Test that WatchlistMovie includes production_year field."""
        watchlist_movie = WatchlistMovie(
            id=3,
            product_id="watch789",
            title="Batman Begins",
            format="4K Blu-ray",
            url="https://example.com",
            image_url="https://example.com/image.jpg",
            production_year=2005,
            tmdb_id=272,
            content_type="movie",
            first_seen=datetime.utcnow(),
            last_updated=datetime.utcnow(),
            target_price=15.00,
            current_price=18.99,
            lowest_price=14.99,
            highest_price=22.99,
        )

        assert watchlist_movie.production_year == 2005
        assert watchlist_movie.target_price == 15.00

    def test_view_models_with_none_production_year(self) -> None:
        """Test view models when production_year is None."""
        movie_with_pricing = MovieWithPricing(
            id=4,
            product_id="none123",
            title="Unknown Year Movie",
            format="DVD",
            url="https://example.com",
            image_url=None,
            production_year=None,  # Explicitly None
            tmdb_id=None,
            content_type="movie",
            first_seen=datetime.utcnow(),
            last_updated=datetime.utcnow(),
        )

        assert movie_with_pricing.production_year is None
        assert movie_with_pricing.title == "Unknown Year Movie"


class TestRelatedModels:
    """Test that related models work correctly with production_year field."""

    def test_price_history_relationship(self) -> None:
        """Test that PriceHistory can be created independently."""
        price_entry = PriceHistory(
            movie_id=1,
            product_id="abc123",
            price=19.99,
            availability="In Stock",
        )

        assert price_entry.movie_id == 1
        assert price_entry.price == 19.99
        assert isinstance(price_entry.checked_at, datetime)

    def test_watchlist_relationship(self) -> None:
        """Test that Watchlist can be created independently."""
        watchlist_entry = Watchlist(
            movie_id=1,
            product_id="abc123",
            target_price=15.00,
            notify_on_availability=True,
        )

        assert watchlist_entry.movie_id == 1
        assert watchlist_entry.target_price == 15.00
        assert watchlist_entry.notify_on_availability is True

    def test_price_alert_relationship(self) -> None:
        """Test that PriceAlert can be created independently."""
        alert = PriceAlert(
            movie_id=1,
            product_id="abc123",
            old_price=29.99,
            new_price=19.99,
            alert_type="price_drop",
            notified=False,
        )

        assert alert.movie_id == 1
        assert alert.old_price == 29.99
        assert alert.new_price == 19.99
        assert alert.alert_type == "price_drop"

    def test_ignored_movie_relationship(self) -> None:
        """Test that IgnoredMovie can be created independently."""
        ignored = IgnoredMovie(
            movie_id=1,
            product_id="abc123",
        )

        assert ignored.movie_id == 1
        assert ignored.product_id == "abc123"
        assert isinstance(ignored.ignored_at, datetime)


class TestProductionYearValidation:
    """Test production year field behavior and edge cases."""

    def test_production_year_valid_ranges(self) -> None:
        """Test various valid production year values."""
        # Test boundary values
        movie_1900 = Movie(product_id="1900", title="Old Movie", production_year=1900)
        movie_2030 = Movie(product_id="2030", title="Future Movie", production_year=2030)
        movie_current = Movie(product_id="current", title="Current Movie", production_year=2024)

        assert movie_1900.production_year == 1900
        assert movie_2030.production_year == 2030
        assert movie_current.production_year == 2024

    def test_production_year_none_handling(self) -> None:
        """Test that None values are handled correctly."""
        movie = Movie(product_id="none", title="No Year Movie", production_year=None)
        assert movie.production_year is None

        # Test that we can update from None to a value
        movie.production_year = 1989
        assert movie.production_year == 1989

        # Test that we can update back to None
        movie.production_year = None
        assert movie.production_year is None

    def test_production_year_type_flexibility(self) -> None:
        """Test that production year accepts proper integer types."""
        # Test with different ways of specifying integers
        movie1 = Movie(product_id="int1", title="Movie 1", production_year=1989)
        movie2 = Movie(product_id="int2", title="Movie 2", production_year=1989)

        assert movie1.production_year == 1989
        assert movie2.production_year == 1989
        assert isinstance(movie1.production_year, int)
        assert isinstance(movie2.production_year, int)
