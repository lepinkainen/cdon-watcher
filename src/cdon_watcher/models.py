"""SQLModel database models for CDON Watcher."""

from datetime import UTC, datetime
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class TMDBMovie(SQLModel, table=True):
    """Verified TMDB movie metadata cache."""

    __tablename__ = "tmdb_movies"

    tmdb_id: int = Field(primary_key=True)  # TMDB ID is the primary key
    imdb_id: str | None = None  # tt1234567 format
    title: str
    original_title: str | None = None
    release_year: int | None = None
    poster_path: str | None = None
    overview: str | None = None
    director: str | None = None
    cast: str | None = None  # Top 3 actors, comma-separated
    content_type: str = Field(default="movie")  # "movie" or "tv"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Relationships
    watchlist_entry: Optional["Watchlist"] = Relationship(back_populates="tmdb_movie")
    ignored_entry: Optional["IgnoredMovie"] = Relationship(back_populates="tmdb_movie")
    movies: list["Movie"] = Relationship(back_populates="tmdb_movie_ref")


class Movie(SQLModel, table=True):
    """Movie model representing the movies table."""

    __tablename__ = "movies"

    id: int | None = Field(default=None, primary_key=True)
    product_id: str = Field(unique=True, index=True)
    title: str
    format: str | None = None
    url: str | None = None
    image_url: str | None = None
    production_year: int | None = None
    tmdb_id: int | None = Field(default=None, foreign_key="tmdb_movies.tmdb_id")
    tmdb_status: str = Field(default="pending")  # "pending", "verified", "no_match"
    content_type: str = Field(default="movie")
    is_box_set: bool = Field(default=False)
    available: bool = Field(default=True)
    first_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Relationships
    price_history: list["PriceHistory"] = Relationship(back_populates="movie")
    price_alerts: list["PriceAlert"] = Relationship(back_populates="movie")
    match_queue_entry: Optional["MatchQueue"] = Relationship(back_populates="movie")
    tmdb_movie_ref: Optional["TMDBMovie"] = Relationship(back_populates="movies")


class PriceHistory(SQLModel, table=True):
    """Price history model representing the price_history table."""

    __tablename__ = "price_history"

    id: int | None = Field(default=None, primary_key=True)
    movie_id: int = Field(foreign_key="movies.id", index=True)
    product_id: str = Field(index=True)
    price: float
    availability: str | None = None
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Relationships
    movie: Optional["Movie"] = Relationship(back_populates="price_history")


class Watchlist(SQLModel, table=True):
    """Watchlist model - tracks movies by TMDB ID (all versions)."""

    __tablename__ = "watchlist"

    id: int | None = Field(default=None, primary_key=True)
    tmdb_id: int = Field(foreign_key="tmdb_movies.tmdb_id", unique=True, index=True)
    target_price: float
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Relationships
    tmdb_movie: Optional["TMDBMovie"] = Relationship(back_populates="watchlist_entry")


class BoxSetWatchlist(SQLModel, table=True):
    """Watchlist for box sets - tracks by movie_id directly (no TMDB)."""

    __tablename__ = "box_set_watchlist"

    id: int | None = Field(default=None, primary_key=True)
    movie_id: int = Field(foreign_key="movies.id", unique=True, index=True)
    target_price: float
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IgnoredMovie(SQLModel, table=True):
    """Ignored movie model - ignores by TMDB ID (all versions)."""

    __tablename__ = "ignored_movies"

    id: int | None = Field(default=None, primary_key=True)
    tmdb_id: int = Field(foreign_key="tmdb_movies.tmdb_id", unique=True, index=True)
    ignored_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Relationships
    tmdb_movie: Optional["TMDBMovie"] = Relationship(back_populates="ignored_entry")


class MatchQueue(SQLModel, table=True):
    """Queue for movies pending TMDB confirmation."""

    __tablename__ = "match_queue"

    id: int | None = Field(default=None, primary_key=True)
    movie_id: int = Field(foreign_key="movies.id", unique=True, index=True)
    action: str  # "watchlist" or "ignore"
    target_price: float | None = None  # For watchlist action
    candidate_tmdb_ids: str | None = None  # JSON array of top candidate IDs
    skipped: bool = Field(default=False)  # User skipped, show later
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Relationships
    movie: Optional["Movie"] = Relationship(back_populates="match_queue_entry")


class PriceAlert(SQLModel, table=True):
    """Price alert model representing the price_alerts table."""

    __tablename__ = "price_alerts"

    id: int | None = Field(default=None, primary_key=True)
    movie_id: int = Field(foreign_key="movies.id", index=True)
    product_id: str = Field(index=True)
    old_price: float
    new_price: float
    alert_type: str  # 'price_drop', 'back_in_stock', 'target_reached'
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    notified: bool = Field(default=False)

    # Relationships
    movie: Optional["Movie"] = Relationship(back_populates="price_alerts")


# View-specific model variants for API responses
class MovieWithPricing(SQLModel):
    """Movie model with pricing information for API responses."""

    id: int
    product_id: str
    title: str
    format: str | None = None
    url: str | None = None
    image_url: str | None = None
    production_year: int | None = None
    tmdb_id: int | None = None
    tmdb_status: str = "pending"
    content_type: str = "movie"
    is_box_set: bool = False
    first_seen: datetime
    last_updated: datetime
    current_price: float | None = None
    lowest_price: float | None = None
    highest_price: float | None = None


class DealMovie(SQLModel):
    """Movie model specifically for deals with price change information."""

    id: int
    product_id: str
    title: str
    format: str | None = None
    url: str | None = None
    image_url: str | None = None
    production_year: int | None = None
    tmdb_id: int | None = None
    is_box_set: bool = False
    current_price: float
    previous_price: float
    price_change: float
    lowest_price: float
    highest_price: float


class TMDBMovieResponse(SQLModel):
    """TMDB movie data for API responses."""

    tmdb_id: int
    imdb_id: str | None = None
    title: str
    original_title: str | None = None
    release_year: int | None = None
    poster_path: str | None = None
    overview: str | None = None
    director: str | None = None
    cast: str | None = None
    content_type: str = "movie"


class WatchlistItem(SQLModel):
    """Watchlist item with TMDB movie and all format versions."""

    tmdb_movie: TMDBMovieResponse
    target_price: float
    created_at: datetime
    versions: list[MovieWithPricing]  # All format versions of this movie


class WatchlistMovie(SQLModel):
    """Legacy: Movie model for watchlist items with target price."""

    id: int
    product_id: str
    title: str
    format: str | None = None
    url: str | None = None
    image_url: str | None = None
    production_year: int | None = None
    tmdb_id: int | None = None
    content_type: str = "movie"
    first_seen: datetime
    last_updated: datetime
    target_price: float
    current_price: float | None = None
    lowest_price: float | None = None
    highest_price: float | None = None


class MatchQueueItem(SQLModel):
    """Match queue item for API responses."""

    queue_id: int
    movie: MovieWithPricing
    action: str
    target_price: float | None = None
    skipped: bool = False
    created_at: datetime


class TMDBCandidate(SQLModel):
    """TMDB candidate for disambiguation."""

    tmdb_id: int
    imdb_id: str | None = None
    title: str
    original_title: str | None = None
    release_year: int | None = None
    poster_url: str | None = None
    overview: str | None = None
    director: str | None = None
    cast: list[str] | None = None
    popularity: float = 0.0
    content_type: str = "movie"
    confidence_score: float = 0.0


class MatchQueueResponse(SQLModel):
    """Response for match queue endpoint."""

    total: int
    current_index: int
    movie: MovieWithPricing | None = None
    candidates: list[TMDBCandidate] = []
    queue_id: int | None = None


class PriceAlertWithTitle(SQLModel):
    """Price alert model with movie title included."""

    id: int
    movie_id: int
    product_id: str
    old_price: float
    new_price: float
    alert_type: str
    created_at: datetime
    notified: bool
    movie_title: str


class BoxSetWatchlistItem(SQLModel):
    """Box set watchlist item for API responses."""

    movie: MovieWithPricing
    target_price: float
    created_at: datetime


class StatsData(SQLModel):
    """Dashboard statistics data model."""

    total_movies: int
    price_drops_today: int
    watchlist_count: int
    box_set_watchlist_count: int = 0
    match_queue_count: int = 0  # Pending TMDB matches
    last_update: str | None = None
