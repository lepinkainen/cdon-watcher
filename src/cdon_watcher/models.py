"""SQLModel database models for CDON Watcher."""

from datetime import UTC, datetime

from sqlmodel import Field, Relationship, SQLModel


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
    tmdb_id: int | None = None
    content_type: str = Field(default="movie")
    available: bool = Field(default=True)
    first_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Relationships
    price_history: list["PriceHistory"] = Relationship(back_populates="movie")
    watchlist_entries: list["Watchlist"] = Relationship(back_populates="movie")
    price_alerts: list["PriceAlert"] = Relationship(back_populates="movie")
    ignored_entries: list["IgnoredMovie"] = Relationship(back_populates="movie")


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
    movie: Movie | None = Relationship(back_populates="price_history")


class Watchlist(SQLModel, table=True):
    """Watchlist model representing the watchlist table."""

    __tablename__ = "watchlist"

    id: int | None = Field(default=None, primary_key=True)
    movie_id: int = Field(foreign_key="movies.id", unique=True)
    product_id: str = Field(unique=True, index=True)
    target_price: float
    notify_on_availability: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Relationships
    movie: Movie | None = Relationship(back_populates="watchlist_entries")


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
    movie: Movie | None = Relationship(back_populates="price_alerts")


class IgnoredMovie(SQLModel, table=True):
    """Ignored movie model representing the ignored_movies table."""

    __tablename__ = "ignored_movies"

    id: int | None = Field(default=None, primary_key=True)
    movie_id: int = Field(foreign_key="movies.id", unique=True)
    product_id: str = Field(unique=True, index=True)
    ignored_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Relationships
    movie: Movie | None = Relationship(back_populates="ignored_entries")


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
    content_type: str = "movie"
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
    current_price: float
    previous_price: float
    price_change: float
    lowest_price: float
    highest_price: float


class WatchlistMovie(SQLModel):
    """Movie model for watchlist items with target price."""

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


class StatsData(SQLModel):
    """Dashboard statistics data model."""

    total_movies: int
    price_drops_today: int
    watchlist_count: int
    last_update: str | None = None
