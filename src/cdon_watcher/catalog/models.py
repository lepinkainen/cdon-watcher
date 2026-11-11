"""Store-aware catalog schema for the multi-store rewrite.

Table names are distinct from the proof-of-concept tables so both can live in
one SQLite file until the old pipeline is removed.
"""

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import registry
from sqlmodel import Field, SQLModel


class CatalogModel(SQLModel, registry=registry()):
    """Base with its own metadata, independent of the legacy SQLModel tables."""


class SchemaVersion(CatalogModel, table=True):
    __tablename__ = "schema_version"

    version: int = Field(primary_key=True)
    applied_at: datetime


class Store(CatalogModel, table=True):
    __tablename__ = "stores"

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(unique=True, index=True)
    name: str


class CrawlRun(CatalogModel, table=True):
    """One archived run as imported. Re-importing updates this row in place."""

    __tablename__ = "crawl_runs"
    __table_args__ = (UniqueConstraint("store_id", "run_id", name="uq_crawl_runs_store_run"),)

    id: int | None = Field(default=None, primary_key=True)
    store_id: int = Field(foreign_key="stores.id", index=True)
    run_id: int
    complete: bool
    parser_version: str
    parsed_at: datetime
    imported_at: datetime
    snapshot_count: int
    product_count: int
    error_count: int
    expired_count: int = 0


class StoreProduct(CatalogModel, table=True):
    """One store edition. Current-state columns mirror the newest observation."""

    __tablename__ = "store_products"
    __table_args__ = (
        UniqueConstraint("store_id", "product_id", name="uq_store_products_store_product"),
    )

    id: int | None = Field(default=None, primary_key=True)
    store_id: int = Field(foreign_key="stores.id", index=True)
    product_id: str = Field(index=True)
    raw_title: str
    cleaned_title: str
    edition_url: str
    format: str = Field(index=True)
    format_raw: str
    disc_count: int | None = None
    condition: str = Field(index=True)
    condition_raw: str | None = None
    release_year: int | None = None
    publisher: str | None = None
    edition_note: str | None = None
    image_url: str | None = None
    is_collection: bool = Field(default=False, index=True)
    tmdb_id: int | None = Field(default=None, index=True)

    current_price_cents: int = Field(index=True)
    current_regular_price_cents: int | None = None
    currency: str = "EUR"
    current_availability: str = Field(index=True)
    current_availability_raw: str | None = None
    current_stock_quantity: int | None = None

    first_seen_at: datetime
    last_seen_at: datetime
    last_seen_run_id: int
    active: bool = Field(default=True, index=True)
    inactive_since: datetime | None = None


class PriceObservation(CatalogModel, table=True):
    """One product in one run. Replaying a run updates, never duplicates."""

    __tablename__ = "price_observations"
    __table_args__ = (
        UniqueConstraint("store_product_id", "run_id", name="uq_price_observations_product_run"),
    )

    id: int | None = Field(default=None, primary_key=True)
    store_product_id: int = Field(foreign_key="store_products.id", index=True)
    run_id: int = Field(index=True)
    snapshot_id: int
    observed_at: datetime = Field(index=True)
    price_cents: int
    regular_price_cents: int | None = None
    currency: str = "EUR"
    availability: str
    availability_raw: str | None = None
    stock_quantity: int | None = None
    parser_version: str


class MovieMetadata(CatalogModel, table=True):
    """TMDB identity and cached metadata shared across store products."""

    __tablename__ = "movie_metadata"

    tmdb_id: int = Field(primary_key=True)
    imdb_id: str | None = None
    title: str
    original_title: str | None = None
    release_year: int | None = None
    poster_path: str | None = None
    overview: str | None = None
    director: str | None = None
    cast: str | None = None
    fetched_at: datetime


class MatchState(CatalogModel, table=True):
    """Matching decision and evidence for one store product.

    status: pending, auto, manual, rejected, ambiguous, unmatched,
    not_applicable, error. Only pending and error are retried automatically.
    """

    __tablename__ = "match_states"

    id: int | None = Field(default=None, primary_key=True)
    store_product_id: int = Field(foreign_key="store_products.id", unique=True, index=True)
    status: str = Field(index=True)
    tmdb_id: int | None = Field(default=None, index=True)
    confidence: float | None = None
    candidates_json: str | None = None
    query: str | None = None
    query_year: int | None = None
    attempts: int = 0
    last_attempt_at: datetime | None = None
    last_error: str | None = None
    decided_at: datetime | None = None
    decided_by: str | None = None
    note: str | None = None


class UserPreference(CatalogModel, table=True):
    """Watch or ignore, keyed by movie (tmdb_id) or by a single store product.

    kind: "watch" or "ignore". Exactly one of tmdb_id / store_product_id is set.
    origin_store_product_id remembers which product the action was taken on,
    so a corrected match can be reconciled without losing user intent.
    """

    __tablename__ = "user_preferences"
    __table_args__ = (
        UniqueConstraint("kind", "tmdb_id", name="uq_user_preferences_kind_tmdb"),
        UniqueConstraint("kind", "store_product_id", name="uq_user_preferences_kind_product"),
    )

    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)
    tmdb_id: int | None = Field(default=None, index=True)
    store_product_id: int | None = Field(default=None, foreign_key="store_products.id", index=True)
    origin_store_product_id: int | None = None
    created_at: datetime
