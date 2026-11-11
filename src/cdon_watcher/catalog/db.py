"""Engine creation and versioned schema migrations for the catalog.

Migrations fail loudly. A database newer than this code is refused rather than
silently used.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, inspect, text
from sqlmodel import Session, create_engine, select

from . import models

Migration = Callable[[Engine], None]


def _v1_create_tables(engine: Engine) -> None:
    models.CatalogModel.metadata.create_all(
        engine,
        tables=[
            models.SchemaVersion.__table__,  # type: ignore[attr-defined]
            models.Store.__table__,  # type: ignore[attr-defined]
            models.CrawlRun.__table__,  # type: ignore[attr-defined]
            models.StoreProduct.__table__,  # type: ignore[attr-defined]
            models.PriceObservation.__table__,  # type: ignore[attr-defined]
        ],
    )


def _v2_matching_tables(engine: Engine) -> None:
    models.CatalogModel.metadata.create_all(
        engine,
        tables=[
            models.MovieMetadata.__table__,  # type: ignore[attr-defined]
            models.MatchState.__table__,  # type: ignore[attr-defined]
        ],
    )


def _v3_user_preferences(engine: Engine) -> None:
    models.CatalogModel.metadata.create_all(
        engine,
        tables=[models.UserPreference.__table__],  # type: ignore[attr-defined]
    )


def _v4_catalogue_and_searches(engine: Engine) -> None:
    """Phase 2: catalogue sync, wishlist searches, discovery source; watch is gone."""
    # v1 creates tables from the current models, so a fresh database already has these.
    columns = {
        table: {c["name"] for c in inspect(engine).get_columns(table)}
        for table in ("store_products", "crawl_runs")
    }
    additions = [
        ("store_products", "category_member", "BOOLEAN NOT NULL DEFAULT 1"),
        ("store_products", "category_run_id", "INTEGER"),
        ("crawl_runs", "scope", "VARCHAR NOT NULL DEFAULT 'category'"),
    ]
    with engine.begin() as connection:
        for table, column, definition in additions:
            if column not in columns[table]:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
        connection.execute(
            text(
                "UPDATE store_products SET category_run_id = last_seen_run_id "
                "WHERE category_run_id IS NULL AND category_member"
            )
        )
        # The catalogue's wishlist replaces watch; only ignores remain.
        connection.execute(text("DELETE FROM user_preferences WHERE kind = 'watch'"))
    models.CatalogModel.metadata.create_all(
        engine,
        tables=[
            models.CatalogueSync.__table__,  # type: ignore[attr-defined]
            models.WishSearch.__table__,  # type: ignore[attr-defined]
            models.SearchHit.__table__,  # type: ignore[attr-defined]
        ],
    )


MIGRATIONS: list[tuple[int, Migration]] = [
    (1, _v1_create_tables),
    (2, _v2_matching_tables),
    (3, _v3_user_preferences),
    (4, _v4_catalogue_and_searches),
]
CURRENT_VERSION = MIGRATIONS[-1][0]


class SchemaError(RuntimeError):
    """The database schema cannot be brought to the version this code expects."""


def create_catalog_engine(path: Path | str) -> Engine:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}")


def current_version(engine: Engine) -> int:
    if not inspect(engine).has_table("schema_version"):
        return 0
    with Session(engine) as session:
        versions = session.exec(select(models.SchemaVersion.version)).all()
    return max(versions, default=0)


def migrate(engine: Engine) -> int:
    """Apply pending migrations in order and return the resulting version."""
    version = current_version(engine)
    if version > CURRENT_VERSION:
        raise SchemaError(
            f"Database schema version {version} is newer than supported {CURRENT_VERSION}"
        )
    for target, migration in MIGRATIONS:
        if target <= version:
            continue
        try:
            migration(engine)
            with Session(engine) as session:
                session.add(models.SchemaVersion(version=target, applied_at=datetime.now(UTC)))
                session.commit()
        except Exception as error:
            raise SchemaError(f"Migration to schema version {target} failed: {error}") from error
        version = target
    return version


def open_catalog(path: Path | str) -> Engine:
    """Create the engine and ensure the schema is current. Never drops data."""
    engine = create_catalog_engine(path)
    migrate(engine)
    return engine
