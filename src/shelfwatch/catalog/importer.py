"""Idempotent import of a parsed run into the catalog.

Guarantees:
- Replaying the same run never duplicates observations or moves observed_at.
- Importing an older run never overwrites current state set by a newer run.
- Only a complete category run ends category membership of products it did
  not see, and only for its own store. Products whose rows failed to parse are
  not treated as gone.
- A search run records which products each wishlist search found. A product
  stays active while it is a category member or a search still finds it.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlmodel import Session, select

from ..ingestion.contract import SEARCH_SCOPE, ParsedProduct, ParsedRun, ParsedSnapshot
from .jev import is_box_set
from .models import (
    CrawlRun,
    MatchState,
    PriceObservation,
    SearchHit,
    Store,
    StoreProduct,
    WishSearch,
)

STORE_NAMES = {"ax": "Levykauppa Äx", "cdon": "CDON", "mymovies": "MyMovies"}


def utc_naive(value: datetime) -> datetime:
    """SQLite stores naive datetimes; keep every stored timestamp as naive UTC."""
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


@dataclass
class ImportResult:
    store: str
    run_id: int
    complete: bool
    products_seen: int = 0
    products_created: int = 0
    observations_created: int = 0
    observations_updated: int = 0
    expired: int = 0
    skipped_ineligible: int = 0
    errors: int = 0
    searches: int = 0
    searches_failed: int = 0
    search_hits: int = 0
    hits_dropped: int = 0


def _get_or_create_store(session: Session, key: str) -> Store:
    store = session.exec(select(Store).where(Store.key == key)).first()
    if store is None:
        store = Store(key=key, name=STORE_NAMES.get(key, key))
        session.add(store)
        session.flush()
    return store


def _apply_current_state(
    product: StoreProduct, parsed: ParsedProduct, run_id: int, at: datetime
) -> None:
    if product.raw_title != parsed.raw_title:
        product.box_set_probability = None  # a new title gets a new box-set check
    product.raw_title = parsed.raw_title
    product.cleaned_title = parsed.cleaned_title
    product.edition_url = parsed.edition_url
    product.format = parsed.format.value
    product.format_raw = parsed.format_raw
    product.disc_count = parsed.disc_count
    product.condition = parsed.condition.value
    product.condition_raw = parsed.condition_raw
    product.release_year = parsed.release_year
    product.publisher = parsed.publisher
    product.edition_note = parsed.edition_note
    product.image_url = parsed.image_url
    product.is_collection = parsed.is_collection or is_box_set(product.box_set_probability)
    product.current_price_cents = parsed.price_cents
    product.current_regular_price_cents = parsed.regular_price_cents
    product.currency = parsed.currency
    product.current_availability = parsed.availability.value
    product.current_availability_raw = parsed.availability_raw
    product.current_stock_quantity = parsed.stock_quantity
    product.last_seen_at = at
    product.last_seen_run_id = run_id
    product.active = True
    product.inactive_since = None


def _upsert_product(
    session: Session,
    store_id: int,
    item: ParsedProduct,
    run_id: int,
    fetched_at: datetime,
    result: ImportResult,
    *,
    category: bool,
) -> StoreProduct:
    product = session.exec(
        select(StoreProduct).where(
            StoreProduct.store_id == store_id, StoreProduct.product_id == item.product_id
        )
    ).first()
    if product is None:
        product = StoreProduct(
            store_id=store_id,
            product_id=item.product_id,
            raw_title=item.raw_title,
            cleaned_title=item.cleaned_title,
            edition_url=item.edition_url,
            format=item.format.value,
            format_raw=item.format_raw,
            condition=item.condition.value,
            current_price_cents=item.price_cents,
            current_availability=item.availability.value,
            first_seen_at=fetched_at,
            last_seen_at=fetched_at,
            last_seen_run_id=run_id,
            category_member=category,
            category_run_id=run_id if category else None,
        )
        _apply_current_state(product, item, run_id, fetched_at)
        session.add(product)
        session.flush()
        result.products_created += 1
    else:
        if run_id >= product.last_seen_run_id:
            _apply_current_state(product, item, run_id, fetched_at)
            product.first_seen_at = min(product.first_seen_at, fetched_at)
        if category and run_id >= (product.category_run_id or 0):
            product.category_member, product.category_run_id = True, run_id
    return product


def _upsert_observation(
    session: Session,
    product_id: int,
    item: ParsedProduct,
    parsed: ParsedRun,
    snapshot: ParsedSnapshot,
    fetched_at: datetime,
    result: ImportResult,
) -> None:
    observation = session.exec(
        select(PriceObservation).where(
            PriceObservation.store_product_id == product_id,
            PriceObservation.run_id == parsed.run_id,
        )
    ).first()
    if observation is None:
        observation = PriceObservation(
            store_product_id=product_id,
            run_id=parsed.run_id,
            snapshot_id=snapshot.snapshot_id,
            observed_at=fetched_at,
            price_cents=item.price_cents,
            availability=item.availability.value,
            parser_version=parsed.parser_version,
        )
        session.add(observation)
        result.observations_created += 1
    else:
        result.observations_updated += 1
    observation.snapshot_id = snapshot.snapshot_id
    observation.price_cents = item.price_cents
    observation.regular_price_cents = item.regular_price_cents
    observation.currency = item.currency
    observation.availability = item.availability.value
    observation.availability_raw = item.availability_raw
    observation.stock_quantity = item.stock_quantity
    observation.parser_version = parsed.parser_version


def _searched_products(session: Session) -> set[int]:
    return set(session.exec(select(SearchHit.store_product_id).distinct()).all())


def _deactivate(product: StoreProduct, now: datetime, result: ImportResult) -> None:
    if product.active:
        product.active = False
        product.inactive_since = now
        result.expired += 1


def _expire_unseen(
    session: Session, store_id: int, parsed: ParsedRun, now: datetime, result: ImportResult
) -> None:
    """A complete category run ends membership of unseen products; searches may keep them."""
    if not (parsed.complete and parsed.expire_unseen):
        return
    errored_ids = {e.product_id for e in parsed.errors if e.product_id is not None}
    unseen = session.exec(
        select(StoreProduct).where(
            StoreProduct.store_id == store_id,
            StoreProduct.category_member == True,  # noqa: E712
            StoreProduct.category_run_id < parsed.run_id,  # type: ignore[operator]
        )
    ).all()
    searched = _searched_products(session)
    for product in unseen:
        if product.product_id in errored_ids:
            continue
        product.category_member = False
        if product.id not in searched:
            _deactivate(product, now, result)


def _record_search(
    session: Session,
    store_id: int,
    tmdb_id: int,
    run_id: int,
    *,
    query: str,
    at: datetime,
    hits: int | None,
    error: str | None,
) -> None:
    search = session.exec(
        select(WishSearch).where(WishSearch.store_id == store_id, WishSearch.tmdb_id == tmdb_id)
    ).first()
    if search is None:
        search = WishSearch(store_id=store_id, tmdb_id=tmdb_id, query=query, run_id=run_id)
        session.add(search)
    elif run_id < search.run_id:
        return
    search.run_id, search.query = run_id, query
    if error is None:
        search.searched_at, search.hit_count = at, hits or 0
        search.error = search.failed_at = None
    else:
        search.error, search.failed_at = error, at


def _link_hits(
    session: Session, tmdb_id: int, found: set[int], run_id: int, at: datetime
) -> list[int]:
    """Upsert hits for one search. Returns products linked for the first time."""
    existing = {
        hit.store_product_id: hit
        for hit in session.exec(select(SearchHit).where(SearchHit.tmdb_id == tmdb_id)).all()
    }
    new = []
    for product_id in sorted(found):
        hit = existing.get(product_id)
        if hit is None:
            session.add(
                SearchHit(
                    store_product_id=product_id,
                    tmdb_id=tmdb_id,
                    run_id=run_id,
                    first_found_at=at,
                    last_found_at=at,
                )
            )
            new.append(product_id)
        elif run_id >= hit.run_id:
            hit.run_id, hit.last_found_at = run_id, at
    return new


def _drop_stale_hits(
    session: Session,
    store_id: int,
    tmdb_id: int,
    found: set[int],
    run_id: int,
    now: datetime,
    result: ImportResult,
) -> None:
    """A later search that no longer finds a product ends that hit."""
    stale = session.exec(
        select(SearchHit, StoreProduct)
        .join(StoreProduct, StoreProduct.id == SearchHit.store_product_id)  # type: ignore[arg-type]
        .where(
            SearchHit.tmdb_id == tmdb_id,
            SearchHit.run_id < run_id,
            StoreProduct.store_id == store_id,
        )
    ).all()
    for hit, product in stale:
        if product.id in found:
            continue
        session.delete(hit)
        result.hits_dropped += 1
    session.flush()
    searched = _searched_products(session)
    for _, product in stale:
        if product.id not in found and not product.category_member and product.id not in searched:
            _deactivate(product, now, result)


def _rematch_new_hits(session: Session, product_ids: list[int]) -> None:
    """Undecided products a search just found get matched again, against the wish."""
    if not product_ids:
        return
    states = session.exec(
        select(MatchState).where(
            MatchState.store_product_id.in_(product_ids),  # type: ignore[attr-defined]
            MatchState.status.in_(("ambiguous", "unmatched")),  # type: ignore[attr-defined]
        )
    ).all()
    for state in states:
        state.status = "pending"


def _apply_searches(
    session: Session,
    store_id: int,
    parsed: ParsedRun,
    db_ids: dict[str, int],
    now: datetime,
    result: ImportResult,
) -> None:
    by_movie: dict[int, list[ParsedSnapshot]] = {}
    for snapshot in parsed.snapshots:
        if snapshot.search_tmdb_id is not None:
            by_movie.setdefault(snapshot.search_tmdb_id, []).append(snapshot)
    for tmdb_id, snapshots in by_movie.items():
        ok = [s for s in snapshots if s.search_failed is None]
        last = snapshots[-1]
        if not ok:
            result.searches_failed += 1
            _record_search(
                session,
                store_id,
                tmdb_id,
                parsed.run_id,
                query=last.search_query or "",
                at=utc_naive(last.fetched_at),
                hits=None,
                error=last.search_failed,
            )
            continue
        result.searches += 1
        found = {db_ids[p.product_id] for s in ok for p in s.products if p.product_id in db_ids}
        at = max(utc_naive(s.fetched_at) for s in ok)
        new = _link_hits(session, tmdb_id, found, parsed.run_id, at)
        _drop_stale_hits(session, store_id, tmdb_id, found, parsed.run_id, now, result)
        _rematch_new_hits(session, new)
        result.search_hits += len(found)
        _record_search(
            session,
            store_id,
            tmdb_id,
            parsed.run_id,
            query=ok[-1].search_query or "",
            at=at,
            hits=len(found),
            error=None,
        )


def _upsert_crawl_run(
    session: Session, store_id: int, parsed: ParsedRun, now: datetime, result: ImportResult
) -> None:
    crawl_run = session.exec(
        select(CrawlRun).where(CrawlRun.store_id == store_id, CrawlRun.run_id == parsed.run_id)
    ).first()
    if crawl_run is None:
        crawl_run = CrawlRun(
            store_id=store_id,
            run_id=parsed.run_id,
            complete=parsed.complete,
            parser_version=parsed.parser_version,
            parsed_at=utc_naive(parsed.parsed_at),
            imported_at=now,
            snapshot_count=0,
            product_count=0,
            error_count=0,
        )
        session.add(crawl_run)
    crawl_run.complete = parsed.complete
    crawl_run.parser_version = parsed.parser_version
    crawl_run.parsed_at = utc_naive(parsed.parsed_at)
    crawl_run.imported_at = now
    crawl_run.snapshot_count = len(parsed.snapshots)
    crawl_run.product_count = result.products_seen
    crawl_run.error_count = result.errors
    crawl_run.expired_count = result.expired
    crawl_run.scope = parsed.scope


def import_run(engine: Engine, parsed: ParsedRun, *, now: datetime | None = None) -> ImportResult:
    now = utc_naive(now or datetime.now(UTC))
    result = ImportResult(parsed.store, parsed.run_id, parsed.complete, errors=len(parsed.errors))
    search = parsed.scope == SEARCH_SCOPE
    seen: set[str] = set()
    db_ids: dict[str, int] = {}

    with Session(engine) as session:
        store = _get_or_create_store(session, parsed.store)
        assert store.id is not None
        for snapshot in parsed.snapshots:
            fetched_at = utc_naive(snapshot.fetched_at)
            for item in snapshot.products:
                if not item.eligible:
                    result.skipped_ineligible += 1
                    continue
                if item.product_id in seen:
                    continue
                seen.add(item.product_id)
                result.products_seen += 1
                product = _upsert_product(
                    session, store.id, item, parsed.run_id, fetched_at, result, category=not search
                )
                assert product.id is not None
                db_ids[item.product_id] = product.id
                _upsert_observation(session, product.id, item, parsed, snapshot, fetched_at, result)
        if search:
            _apply_searches(session, store.id, parsed, db_ids, now, result)
        else:
            _expire_unseen(session, store.id, parsed, now, result)
        _upsert_crawl_run(session, store.id, parsed, now, result)
        session.commit()
    return result
