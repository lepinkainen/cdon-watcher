"""Read queries behind the web pages. Pure database reads, no crawling."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, func
from sqlmodel import Session, select

from ..ingestion.contract import SEARCH_SCOPE, Availability
from .catalogue import Catalogue, WantedMovie, load_catalogue
from .models import (
    CrawlRun,
    MatchState,
    MovieMetadata,
    PriceObservation,
    Store,
    StoreProduct,
    WishSearch,
)
from .preferences import Ignored, ignored_sets

MAX_BD_CENTS = 1000
MAX_4K_CENTS = 2000
FRESHNESS_HOURS = 48
UNDECIDED_STATUSES = ("pending", "ambiguous", "unmatched", "error")
TMDB_POSTER_URL = "https://image.tmdb.org/t/p/w154{path}"
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
    cover_url: str | None
    """The store's edition cover, else the matched movie's TMDB poster."""
    is_collection: bool
    tmdb_id: int | None
    match_status: str
    stock_quantity: int | None
    last_seen_at: datetime
    ignored: bool = False
    wished: bool = False
    """The movie is on the catalogue's wishlist (in any format)."""
    deal: bool = False
    """Wished for in this format and at or under the wish's price cap."""
    own_dvd: bool = False
    """Owned on DVD only: an upgrade candidate."""

    @property
    def can_wish(self) -> bool:
        return self.tmdb_id is not None and not self.is_collection and not self.wished


@dataclass
class MainPage:
    wishlist: list[Row]
    rows: list[Row]
    filters: Filters
    stores: list[Store]
    last_refresh: datetime | None
    catalogue: Catalogue
    hidden_owned: int = 0


@dataclass
class WishEntry:
    wish: WantedMovie
    offers: list[Row] = field(default_factory=list)
    searches: list[tuple[str, WishSearch]] = field(default_factory=list)

    @property
    def has_deal(self) -> bool:
        return any(o.deal for o in self.offers)


@dataclass
class StoreStatus:
    store: Store
    last_run: CrawlRun | None
    product_count: int
    in_stock_count: int
    fresh: bool
    last_search: CrawlRun | None = None


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
    *,
    ignored: bool = False,
    catalogue: Catalogue | None = None,
) -> Row:
    assert product.id is not None
    row = Row(
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
        cover_url=product.image_url
        or (TMDB_POSTER_URL.format(path=meta.poster_path) if meta and meta.poster_path else None),
        is_collection=product.is_collection,
        tmdb_id=product.tmdb_id,
        match_status=status or ("not_applicable" if product.is_collection else "pending"),
        stock_quantity=product.current_stock_quantity,
        last_seen_at=product.last_seen_at,
        ignored=ignored,
    )
    if catalogue is not None and not product.is_collection and product.tmdb_id is not None:
        wish = catalogue.wanted.get(product.tmdb_id)
        row.wished = wish is not None
        row.deal = (
            wish is not None
            and wish.accepts(product.format)
            and wish.max_price_cents is not None
            and product.current_price_cents <= wish.max_price_cents
        )
        row.own_dvd = catalogue.owns_dvd_only(product.tmdb_id)
    return row


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


def _rows(  # type: ignore[no-untyped-def]
    session: Session, query, ignored: Ignored, catalogue: Catalogue | None = None
) -> list[Row]:
    return [
        _row(
            product,
            store,
            meta,
            state.status if state else None,
            ignored=product in ignored,
            catalogue=catalogue,
        )
        for product, store, meta, state in session.exec(query).all()
    ]


def _in_wishlist_section(row: Row, catalogue: Catalogue) -> bool:
    wish = catalogue.wanted.get(row.tmdb_id) if row.tmdb_id is not None else None
    return wish is not None and not row.is_collection and wish.accepts(row.format)


def _passes(row: Row, filters: Filters) -> bool:
    cap = filters.max_4k_cents if row.format == "4k" else filters.max_bd_cents
    if row.price_cents > cap:
        return False
    if filters.format and row.format != filters.format:
        return False
    if filters.store and row.store_key != filters.store:
        return False
    if filters.condition and row.condition != filters.condition:
        return False
    if filters.q:
        needle = filters.q.casefold()
        return needle in row.title.casefold() or needle in row.raw_title.casefold()
    return True


def _price_sort(row: Row) -> tuple[int, str, str]:
    return (row.price_cents, row.title.casefold(), row.product_id)


def main_page(engine: Engine, filters: Filters, *, now: datetime | None = None) -> MainPage:
    """Wished-for offers first, regardless of limits; then browsing, minus what I own."""
    now = now or _now()
    with Session(engine) as session:
        catalogue = load_catalogue(session)
        query = _shoppable(session, now)
        rows = [r for r in _rows(session, query, ignored_sets(session), catalogue) if not r.ignored]
        wishlist = sorted((r for r in rows if _in_wishlist_section(r, catalogue)), key=_price_sort)
        shown = {r.id for r in wishlist}
        rest, hidden_owned = [], 0
        for row in rows:
            if row.id in shown or not _passes(row, filters):
                continue
            if not row.wished and catalogue.owns_disc(row.tmdb_id):
                hidden_owned += 1
                continue
            rest.append(row)
        rest.sort(key=_price_sort)
        stores = session.exec(select(Store).order_by(Store.key)).all()
        last = session.exec(
            select(func.max(CrawlRun.imported_at)).where(CrawlRun.scope == "category")
        ).one()
        session.expunge_all()
    return MainPage(
        wishlist=wishlist,
        rows=rest,
        filters=filters,
        stores=list(stores),
        last_refresh=last,
        catalogue=catalogue,
        hidden_owned=hidden_owned,
    )


def ignored_page(engine: Engine) -> list[Row]:
    with Session(engine) as session:
        ignored = ignored_sets(session)
        query = (
            select(StoreProduct, Store, MovieMetadata, MatchState)
            .join(Store, Store.id == StoreProduct.store_id)  # type: ignore[arg-type]
            .outerjoin(MovieMetadata, MovieMetadata.tmdb_id == StoreProduct.tmdb_id)  # type: ignore[arg-type]
            .outerjoin(MatchState, MatchState.store_product_id == StoreProduct.id)  # type: ignore[arg-type]
            .where(
                (StoreProduct.tmdb_id.in_(ignored.movies))  # type: ignore[union-attr]
                | (StoreProduct.id.in_(ignored.products))  # type: ignore[union-attr]
            )
        )
        rows = _rows(session, query, ignored)
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
        ignored = ignored_sets(session)
        query = _shoppable(session, now).where(
            StoreProduct.is_collection == False,  # noqa: E712
            (MatchState.id.is_(None)) | (MatchState.status.in_(UNDECIDED_STATUSES)),  # type: ignore[attr-defined,union-attr]
        )
        items = []
        for product, store, meta, state in session.exec(query).all():
            if product in ignored:
                continue
            row = _row(product, store, meta, state.status if state else None)
            candidates = (
                json.loads(state.candidates_json) if state and state.candidates_json else []
            )
            items.append((row, candidates))
        session.expunge_all()
    items.sort(key=lambda item: (item[0].match_status != "ambiguous", item[0].title.casefold()))
    return items


def wishlist_page(engine: Engine, *, now: datetime | None = None) -> list[WishEntry]:
    """Each wish with its in-stock offers here (any format) and its latest searches."""
    now = now or _now()
    with Session(engine) as session:
        catalogue = load_catalogue(session)
        wanted = list(catalogue.wanted)
        query = _shoppable(session, now).where(
            StoreProduct.tmdb_id.in_(wanted),  # type: ignore[union-attr]
            StoreProduct.is_collection == False,  # noqa: E712
        )
        offers = _rows(session, query, Ignored(frozenset(), frozenset()), catalogue)
        searches = session.exec(
            select(WishSearch, Store)
            .join(Store, Store.id == WishSearch.store_id)  # type: ignore[arg-type]
            .where(WishSearch.tmdb_id.in_(wanted))  # type: ignore[attr-defined]
        ).all()
        entries = []
        for tmdb_id, wish in catalogue.wanted.items():
            entry = WishEntry(
                wish,
                sorted((o for o in offers if o.tmdb_id == tmdb_id), key=_price_sort),
                sorted((st.key, ws) for ws, st in searches if ws.tmdb_id == tmdb_id),
            )
            entries.append(entry)
        session.expunge_all()
    entries.sort(key=lambda e: (not e.has_deal, not e.offers, e.wish.title.casefold()))
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
        row = _row(
            product,
            store,
            meta,
            state.status if state else None,
            ignored=product in ignored_sets(session),
            catalogue=load_catalogue(session),
        )
        history = session.exec(
            select(PriceObservation)
            .where(PriceObservation.store_product_id == product.id)
            .order_by(PriceObservation.observed_at.desc())  # type: ignore[attr-defined]
        ).all()
        session.expunge_all()
    return row, list(history)


def _iso_utc(value: datetime | None) -> str | None:
    """Naive UTC from the database as ISO 8601 with a Z, as the catalogue expects."""
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value is not None else None


def offers_for(
    engine: Engine, tmdb_ids: list[int], *, now: datetime | None = None
) -> dict[str, dict[str, object]]:
    """The read API for moviecatalog: current offers and last search per movie.

    Every requested id is a key. Items are active, single-movie bd/4k listings
    within the freshness limit, in every availability, cheapest first then by id.
    searched_at is the newest successful search for the movie at any store.
    """
    now = now or _now()
    wanted = sorted(set(tmdb_ids))
    result: dict[str, dict[str, object]] = {
        str(t): {"searched_at": None, "items": []} for t in wanted
    }
    if not wanted:
        return result
    with Session(engine) as session:
        rows = session.exec(
            select(StoreProduct, Store)
            .join(Store, Store.id == StoreProduct.store_id)  # type: ignore[arg-type]
            .where(
                StoreProduct.tmdb_id.in_(wanted),  # type: ignore[union-attr]
                StoreProduct.active == True,  # noqa: E712
                StoreProduct.is_collection == False,  # noqa: E712
                StoreProduct.format.in_(("bd", "4k")),  # type: ignore[attr-defined]
                StoreProduct.last_seen_at >= _fresh_after(now),
            )
            .order_by(StoreProduct.current_price_cents, StoreProduct.id)  # type: ignore[arg-type]
        ).all()
        for product, store in rows:
            items = result[str(product.tmdb_id)]["items"]
            assert isinstance(items, list)
            items.append(
                {
                    "id": product.id,
                    "store_key": store.key,
                    "store": store.name,
                    "title": product.raw_title,
                    "format": product.format,
                    "condition": product.condition,
                    "price_cents": product.current_price_cents,
                    "regular_price_cents": product.current_regular_price_cents,
                    "currency": product.currency,
                    "availability": product.current_availability,
                    "url": product.edition_url,
                    "image_url": product.image_url,
                    "last_seen_at": _iso_utc(product.last_seen_at),
                }
            )
        searched = session.exec(
            select(WishSearch.tmdb_id, func.max(WishSearch.searched_at))
            .where(
                WishSearch.tmdb_id.in_(wanted),  # type: ignore[attr-defined]
                WishSearch.searched_at.is_not(None),  # type: ignore[union-attr]
            )
            .group_by(WishSearch.tmdb_id)  # type: ignore[arg-type]
        ).all()
        for tmdb_id, searched_at in searched:
            result[str(tmdb_id)]["searched_at"] = _iso_utc(searched_at)
    return result


def catalogue_status(engine: Engine) -> Catalogue:
    with Session(engine) as session:
        return load_catalogue(session)


def status_page(engine: Engine, *, now: datetime | None = None) -> list[StoreStatus]:
    now = now or _now()
    with Session(engine) as session:
        statuses = []
        for store in session.exec(select(Store).order_by(Store.key)).all():
            last_run = session.exec(
                select(CrawlRun)
                .where(CrawlRun.store_id == store.id, CrawlRun.scope == "category")
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
            last_search = session.exec(
                select(CrawlRun)
                .where(CrawlRun.store_id == store.id, CrawlRun.scope == SEARCH_SCOPE)
                .order_by(CrawlRun.run_id.desc())  # type: ignore[attr-defined]
            ).first()
            statuses.append(
                StoreStatus(store, last_run, int(total), int(in_stock), fresh, last_search)
            )
        session.expunge_all()
    return statuses
