"""Store-aware catalog schema for the multi-store rewrite.

Table names are distinct from the proof-of-concept tables so both can live in
one SQLite file until the old pipeline is removed.
"""

from pydantic import NaiveDatetime
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import registry
from sqlmodel import Field, SQLModel


class CatalogModel(SQLModel, registry=registry()):
    """Base with its own metadata, independent of the legacy SQLModel tables."""


class SchemaVersion(CatalogModel, table=True):
    __tablename__ = "schema_version"

    version: int = Field(primary_key=True)
    applied_at: NaiveDatetime


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
    parsed_at: NaiveDatetime
    imported_at: NaiveDatetime
    snapshot_count: int
    product_count: int
    error_count: int
    expired_count: int = 0
    scope: str = "category"
    """category for the listing crawl, search for wishlist searches."""


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
    """A box set: the title patterns or Jev say it holds several different films."""
    box_set_probability: float | None = None
    """Jev's answer for the current raw title; None until checked."""
    marked_box_set: bool = False
    """A person tagged it as a box set in the queue; outlasts imports and Jev re-checks."""
    tmdb_id: int | None = Field(default=None, index=True)

    current_price_cents: int = Field(index=True)
    current_regular_price_cents: int | None = None
    currency: str = "EUR"
    current_availability: str = Field(index=True)
    current_availability_raw: str | None = None
    current_stock_quantity: int | None = None

    first_seen_at: NaiveDatetime
    last_seen_at: NaiveDatetime
    last_seen_run_id: int
    active: bool = Field(default=True, index=True)
    inactive_since: NaiveDatetime | None = None
    category_member: bool = True
    """Seen by the newest category crawl. Search-only products are not members."""
    category_run_id: int | None = None


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
    observed_at: NaiveDatetime = Field(index=True)
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
    fetched_at: NaiveDatetime


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
    last_attempt_at: NaiveDatetime | None = None
    last_error: str | None = None
    decided_at: NaiveDatetime | None = None
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
    created_at: NaiveDatetime


class CatalogueSync(CatalogModel, table=True):
    """The last successful /api/sync response from moviecatalog (a single row, id 1)."""

    __tablename__ = "catalogue_sync"

    id: int = Field(default=1, primary_key=True)
    payload_json: str | None = None
    fetched_at: NaiveDatetime | None = None
    last_attempt_at: NaiveDatetime | None = None
    last_error: str | None = None


class WishSearch(CatalogModel, table=True):
    """Targeted searches for one wished-for movie at one store.

    searched_at is the last successful search; error and failed_at describe a
    later failure, which keeps the previous hits and searched_at.
    """

    __tablename__ = "wish_searches"
    __table_args__ = (UniqueConstraint("store_id", "tmdb_id", name="uq_wish_searches_store_tmdb"),)

    id: int | None = Field(default=None, primary_key=True)
    store_id: int = Field(foreign_key="stores.id", index=True)
    tmdb_id: int = Field(index=True)
    query: str
    run_id: int
    searched_at: NaiveDatetime | None = None
    hit_count: int = 0
    error: str | None = None
    failed_at: NaiveDatetime | None = None


class SearchHit(CatalogModel, table=True):
    """A product the latest search for a wished-for movie found."""

    __tablename__ = "search_hits"
    __table_args__ = (
        UniqueConstraint("store_product_id", "tmdb_id", name="uq_search_hits_product_tmdb"),
    )

    id: int | None = Field(default=None, primary_key=True)
    store_product_id: int = Field(foreign_key="store_products.id", index=True)
    tmdb_id: int = Field(index=True)
    run_id: int
    first_found_at: NaiveDatetime
    last_found_at: NaiveDatetime
