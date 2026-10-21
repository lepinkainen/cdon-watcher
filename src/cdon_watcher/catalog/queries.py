"""Read queries behind the web pages. Pure database reads, no crawling."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, func
from sqlmodel import Session, select

from ..ingestion.contract import Availability
from .models import (
    CrawlRun,
    MatchState,
    MovieMetadata,
    PriceObservation,
    Store,
    StoreProduct,
)
from .preferences import preference_sets

MAX_BD_CENTS = 1000
MAX_4K_CENTS = 2000
FRESHNESS_HOURS = 48
UNDECIDED_STATUSES = ("pending", "ambiguous", "unmatched", "error")
FORMAT_LABELS = {"bd": "Blu-ray", "4k": "4K UHD", "dvd": "DVD", "unknown": "?"}


@dataclass
class Filters:
    max_bd_cents: int = MAX_BD_CENTS
    max_4k_cents: int = MAX_4K_CENTS
    format: str | None = None
    store: str | None = None
    condition: str | None = None
    q: str | None = None


@dataclass
class Row:
    id: int
    store_key: str
    store_name: str
    product_id: str
    title: str
    raw_title: str
    format: str
    format_label: str
    condition: str
    price_cents: int
    regular_price_cents: int | None
    edition_url: str
    image_url: str | None
    is_collection: bool
    tmdb_id: int | None
    match_status: str
    stock_quantity: int | None
    last_seen_at: datetime
    watched: bool = False
    ignored: bool = False


@dataclass
class MainPage:
    watchlist: list[Row]
    rows: list[Row]
    filters: Filters
    stores: list[Store]
    last_refresh: datetime | None


@dataclass
class WatchlistEntry:
    title: str
    tmdb_id: int | None
    store_product_id: int | None
    unwatch_product_id: int
    offers: list[Row] = field(default_factory=list)


@dataclass
class StoreStatus:
    store: Store
    last_run: CrawlRun | None
    product_count: int
    in_stock_count: int
    fresh: bool


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _fresh_after(now: datetime) -> datetime:
    return now - timedelta(hours=FRESHNESS_HOURS)


def _title(product: StoreProduct, meta: MovieMetadata | None) -> str:
    if product.is_collection or meta is None:
        return product.raw_title
    return meta.title


def _row(
    product: StoreProduct,
    store: Store,
    meta: MovieMetadata | None,
    status: str | None,
    watched: bool,
    ignored: bool,
) -> Row:
    assert product.id is not None
    return Row(
        id=product.id,
        store_key=store.key,
        store_name=store.name,
        product_id=product.product_id,
        title=_title(product, meta),
        raw_title=product.raw_title,
        format=product.format,
        format_label=FORMAT_LABELS.get(product.format, product.format),
        condition=product.condition,
        price_cents=product.current_price_cents,
        regular_price_cents=product.current_regular_price_cents,
        edition_url=product.edition_url,
        image_url=product.image_url,
        is_collection=product.is_collection,
        tmdb_id=product.tmdb_id,
        match_status=status or ("not_applicable" if product.is_collection else "pending"),
        stock_quantity=product.current_stock_quantity,
        last_seen_at=product.last_seen_at,
        watched=watched,
        ignored=ignored,
    )


def _shoppable(session: Session, now: datetime):  # type: ignore[no-untyped-def]
    """In-stock, active, fresh products joined with store, metadata and match state."""
    return (
        select(StoreProduct, Store, MovieMetadata, MatchState)
        .join(Store, Store.id == StoreProduct.store_id)  # type: ignore[arg-type]
        .outerjoin(MovieMetadata, MovieMetadata.tmdb_id == StoreProduct.tmdb_id)  # type: ignore[arg-type]
        .outerjoin(MatchState, MatchState.store_product_id == StoreProduct.id)  # type: ignore[arg-type]
        .where(
            StoreProduct.active == True,  # noqa: E712
            StoreProduct.current_availability == Availability.IN_STOCK.value,
            StoreProduct.last_seen_at >= _fresh_after(now),
        )
    )


def _rows(session: Session, query, prefs) -> list[Row]:  # type: ignore[no-untyped-def]
    watched_movies, watched_products, ignored_movies, ignored_products = prefs
    rows = []
    for product, store, meta, state in session.exec(query).all():
        watched = product.tmdb_id in watched_movies or product.id in watched_products
        ignored = product.tmdb_id in ignored_movies or product.id in ignored_products
        rows.append(_row(product, store, meta, state.status if state else None, watched, ignored))
    return rows


def _price_sort(row: Row) -> tuple[int, str, str]:
    return (row.price_cents, row.title.casefold(), row.product_id)


def main_page(engine: Engine, filters: Filters, *, now: datetime | None = None) -> MainPage:
    now = now or _now()
    with Session(engine) as session:
        prefs = preference_sets(session)
        rows = [r for r in _rows(session, _shoppable(session, now), prefs) if not r.ignored]
        watchlist = sorted((r for r in rows if r.watched), key=_price_sort)
        shown = {r.id for r in watchlist}
        rest = []
        for row in rows:
            if row.id in shown:
                continue
            cap = filters.max_4k_cents if row.format == "4k" else filters.max_bd_cents
            if row.price_cents > cap:
                continue
            if filters.format and row.format != filters.format:
                continue
            if filters.store and row.store_key != filters.store:
                continue
            if filters.condition and row.condition != filters.condition:
                continue
            if filters.q:
                needle = filters.q.casefold()
                if needle not in row.title.casefold() and needle not in row.raw_title.casefold():
                    continue
            rest.append(row)
        rest.sort(key=_price_sort)
        stores = session.exec(select(Store).order_by(Store.key)).all()
        last = session.exec(select(func.max(CrawlRun.imported_at))).one()
        session.expunge_all()
    return MainPage(
        watchlist=watchlist, rows=rest, filters=filters, stores=list(stores), last_refresh=last
    )


def ignored_page(engine: Engine) -> list[Row]:
    with Session(engine) as session:
        prefs = preference_sets(session)
        _, _, ignored_movies, ignored_products = prefs
        query = (
            select(StoreProduct, Store, MovieMetadata, MatchState)
            .join(Store, Store.id == StoreProduct.store_id)  # type: ignore[arg-type]
            .outerjoin(MovieMetadata, MovieMetadata.tmdb_id == StoreProduct.tmdb_id)  # type: ignore[arg-type]
            .outerjoin(MatchState, MatchState.store_product_id == StoreProduct.id)  # type: ignore[arg-type]
            .where(
                (StoreProduct.tmdb_id.in_(ignored_movies))  # type: ignore[union-attr]
                | (StoreProduct.id.in_(ignored_products))  # type: ignore[union-attr]
            )
        )
        rows = _rows(session, query, prefs)
        # One row per movie is enough on the ignored page; collections stay per product.
        seen: set[int] = set()
        unique = []
        for row in sorted(rows, key=lambda r: r.title.casefold()):
            if row.tmdb_id is not None and not row.is_collection:
                if row.tmdb_id in seen:
                    continue
                seen.add(row.tmdb_id)
            unique.append(row)
        session.expunge_all()
    return unique


def match_queue(
    engine: Engine, *, now: datetime | None = None
) -> list[tuple[Row, list[dict[str, object]]]]:
    """In-stock single-movie products without a confirmed match, with candidates."""
    import json

    now = now or _now()
    with Session(engine) as session:
        prefs = preference_sets(session)
        query = _shoppable(session, now).where(
            StoreProduct.is_collection == False,  # noqa: E712
            (MatchState.id.is_(None)) | (MatchState.status.in_(UNDECIDED_STATUSES)),  # type: ignore[attr-defined,union-attr]
        )
        items = []
        for product, store, meta, state in session.exec(query).all():
            row = _row(product, store, meta, state.status if state else None, False, False)
            if product.tmdb_id in prefs[2] or product.id in prefs[3]:
                continue
            candidates = (
                json.loads(state.candidates_json) if state and state.candidates_json else []
            )
            items.append((row, candidates))
        session.expunge_all()
    items.sort(key=lambda item: (item[0].match_status != "ambiguous", item[0].title.casefold()))
    return items


def watchlist_page(engine: Engine, *, now: datetime | None = None) -> list[WatchlistEntry]:
    now = now or _now()
    with Session(engine) as session:
        prefs = preference_sets(session)
        watched_movies, watched_products, _, _ = prefs
        offers = [r for r in _rows(session, _shoppable(session, now), prefs) if r.watched]
        entries: list[WatchlistEntry] = []
        for tmdb_id in sorted(watched_movies):
            meta = session.get(MovieMetadata, tmdb_id)
            any_product = session.exec(
                select(StoreProduct).where(StoreProduct.tmdb_id == tmdb_id)
            ).first()
            title = (
                meta.title
                if meta
                else (any_product.raw_title if any_product else f"TMDB {tmdb_id}")
            )
            movie_offers = sorted((o for o in offers if o.tmdb_id == tmdb_id), key=_price_sort)
            unwatch_id = (
                movie_offers[0].id if movie_offers else (any_product.id if any_product else None)
            )
            if unwatch_id is None:
                continue
            entries.append(WatchlistEntry(title, tmdb_id, None, unwatch_id, movie_offers))
        for product_id in sorted(watched_products):
            product = session.get(StoreProduct, product_id)
            if product is None:
                continue
            product_offers = sorted((o for o in offers if o.id == product_id), key=_price_sort)
            entries.append(
                WatchlistEntry(product.raw_title, None, product_id, product_id, product_offers)
            )
        session.expunge_all()
    entries.sort(key=lambda e: (not e.offers, e.title.casefold()))
    return entries


def product_history(
    engine: Engine, store_product_id: int
) -> tuple[Row, list[PriceObservation]] | None:
    with Session(engine) as session:
        product = session.get(StoreProduct, store_product_id)
        if product is None:
            return None
        store = session.get(Store, product.store_id)
        assert store is not None
        meta = session.get(MovieMetadata, product.tmdb_id) if product.tmdb_id else None
        state = session.exec(
            select(MatchState).where(MatchState.store_product_id == product.id)
        ).first()
        prefs = preference_sets(session)
        watched = product.tmdb_id in prefs[0] or product.id in prefs[1]
        ignored = product.tmdb_id in prefs[2] or product.id in prefs[3]
        row = _row(product, store, meta, state.status if state else None, watched, ignored)
        history = session.exec(
            select(PriceObservation)
            .where(PriceObservation.store_product_id == product.id)
            .order_by(PriceObservation.observed_at.desc())  # type: ignore[attr-defined]
        ).all()
        session.expunge_all()
    return row, list(history)


def status_page(engine: Engine, *, now: datetime | None = None) -> list[StoreStatus]:
    now = now or _now()
    with Session(engine) as session:
        statuses = []
        for store in session.exec(select(Store).order_by(Store.key)).all():
            last_run = session.exec(
                select(CrawlRun)
                .where(CrawlRun.store_id == store.id)
                .order_by(CrawlRun.run_id.desc())  # type: ignore[attr-defined]
            ).first()
            total = session.exec(
                select(func.count())
                .select_from(StoreProduct)
                .where(StoreProduct.store_id == store.id)
            ).one()
            in_stock = session.exec(
                select(func.count())
                .select_from(StoreProduct)
                .where(
                    StoreProduct.store_id == store.id,
                    StoreProduct.active == True,  # noqa: E712
                    StoreProduct.current_availability == Availability.IN_STOCK.value,
                    StoreProduct.last_seen_at >= _fresh_after(now),
                )
            ).one()
            fresh = last_run is not None and last_run.imported_at >= _fresh_after(now)
            statuses.append(StoreStatus(store, last_run, int(total), int(in_stock), fresh))
        session.expunge_all()
    return statuses
