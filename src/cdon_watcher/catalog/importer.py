"""Idempotent import of a parsed run into the catalog.

Guarantees:
- Replaying the same run never duplicates observations or moves observed_at.
- Importing an older run never overwrites current state set by a newer run.
- Only a complete run expires products it did not see, and only for its own
  store. Products whose rows failed to parse are not treated as gone.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlmodel import Session, select

from ..ingestion.contract import ParsedProduct, ParsedRun, ParsedSnapshot
from .models import CrawlRun, PriceObservation, Store, StoreProduct

STORE_NAMES = {"ax": "Levykauppa Äx", "cdon": "CDON"}


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
    product.is_collection = parsed.is_collection
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
        )
        _apply_current_state(product, item, run_id, fetched_at)
        session.add(product)
        session.flush()
        result.products_created += 1
    elif run_id >= product.last_seen_run_id:
        _apply_current_state(product, item, run_id, fetched_at)
        product.first_seen_at = min(product.first_seen_at, fetched_at)
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


def _expire_unseen(
    session: Session, store_id: int, parsed: ParsedRun, now: datetime, result: ImportResult
) -> None:
    if not (parsed.complete and parsed.expire_unseen):
        return
    errored_ids = {e.product_id for e in parsed.errors if e.product_id is not None}
    unseen = session.exec(
        select(StoreProduct).where(
            StoreProduct.store_id == store_id,
            StoreProduct.active == True,  # noqa: E712
            StoreProduct.last_seen_run_id < parsed.run_id,
        )
    ).all()
    for product in unseen:
        if product.product_id in errored_ids:
            continue
        product.active = False
        product.inactive_since = now
        result.expired += 1


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


def import_run(engine: Engine, parsed: ParsedRun, *, now: datetime | None = None) -> ImportResult:
    now = utc_naive(now or datetime.now(UTC))
    result = ImportResult(parsed.store, parsed.run_id, parsed.complete, errors=len(parsed.errors))
    seen: set[str] = set()

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
                    session, store.id, item, parsed.run_id, fetched_at, result
                )
                assert product.id is not None
                _upsert_observation(session, product.id, item, parsed, snapshot, fetched_at, result)
        _expire_unseen(session, store.id, parsed, now, result)
        _upsert_crawl_run(session, store.id, parsed, now, result)
        session.commit()
    return result
