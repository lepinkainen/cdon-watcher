"""Watch and ignore preferences. Mutually exclusive per target, latest wins."""

from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlmodel import Session, select

from .models import StoreProduct, UserPreference

KINDS = ("watch", "ignore")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _target(product: StoreProduct) -> tuple[int | None, int | None]:
    """Movie-level target when matched and not a collection, else product-level."""
    assert product.id is not None
    if product.tmdb_id is not None and not product.is_collection:
        return product.tmdb_id, None
    return None, product.id


def _existing(
    session: Session, kind: str, tmdb_id: int | None, product_id: int | None
) -> UserPreference | None:
    query = select(UserPreference).where(UserPreference.kind == kind)
    if tmdb_id is not None:
        query = query.where(UserPreference.tmdb_id == tmdb_id)
    else:
        query = query.where(UserPreference.store_product_id == product_id)
    return session.exec(query).first()


def set_preference(
    session: Session, product: StoreProduct, kind: str, *, now: datetime | None = None
) -> UserPreference:
    """Apply watch or ignore to the product's target, removing the opposite kind."""
    if kind not in KINDS:
        raise ValueError(f"Unknown preference kind {kind!r}")
    now = now or _now()
    tmdb_id, product_id = _target(product)
    other = "ignore" if kind == "watch" else "watch"
    opposite = _existing(session, other, tmdb_id, product_id)
    if opposite is not None:
        session.delete(opposite)
    current = _existing(session, kind, tmdb_id, product_id)
    if current is None:
        current = UserPreference(
            kind=kind,
            tmdb_id=tmdb_id,
            store_product_id=product_id,
            origin_store_product_id=product.id,
            created_at=now,
        )
        session.add(current)
    session.flush()
    return current


def clear_preference(session: Session, product: StoreProduct, kind: str) -> bool:
    tmdb_id, product_id = _target(product)
    current = _existing(session, kind, tmdb_id, product_id)
    if current is None:
        return False
    session.delete(current)
    session.flush()
    return True


def transfer_product_preferences(session: Session, product: StoreProduct) -> None:
    """Move product-level preferences onto the movie once the product is matched.

    On conflict with an existing movie-level preference the latest explicit
    action wins. Collections keep product-level preferences.
    """
    if product.tmdb_id is None or product.is_collection:
        return
    assert product.id is not None
    product_level = session.exec(
        select(UserPreference).where(UserPreference.store_product_id == product.id)
    ).all()
    for pref in product_level:
        other = "ignore" if pref.kind == "watch" else "watch"
        same = _existing(session, pref.kind, product.tmdb_id, None)
        opposite = _existing(session, other, product.tmdb_id, None)
        if opposite is not None and opposite.created_at > pref.created_at:
            session.delete(pref)
            continue
        if opposite is not None:
            session.delete(opposite)
        if same is None:
            session.add(
                UserPreference(
                    kind=pref.kind,
                    tmdb_id=product.tmdb_id,
                    store_product_id=None,
                    origin_store_product_id=pref.origin_store_product_id,
                    created_at=pref.created_at,
                )
            )
        session.delete(pref)
    session.flush()


def preference_sets(session: Session) -> tuple[set[int], set[int], set[int], set[int]]:
    """(watched tmdb ids, watched product ids, ignored tmdb ids, ignored product ids)."""
    watched_movies: set[int] = set()
    watched_products: set[int] = set()
    ignored_movies: set[int] = set()
    ignored_products: set[int] = set()
    for pref in session.exec(select(UserPreference)).all():
        movies, products = (
            (watched_movies, watched_products)
            if pref.kind == "watch"
            else (ignored_movies, ignored_products)
        )
        if pref.tmdb_id is not None:
            movies.add(pref.tmdb_id)
        elif pref.store_product_id is not None:
            products.add(pref.store_product_id)
    return watched_movies, watched_products, ignored_movies, ignored_products


def apply(engine: Engine, store_product_id: int, action: str) -> dict[str, object]:
    """Entry point for the web actions: watch, unwatch, ignore, unignore."""
    with Session(engine) as session:
        product = session.get(StoreProduct, store_product_id)
        if product is None:
            raise LookupError(f"No store product {store_product_id}")
        if action in KINDS:
            set_preference(session, product, action)
        elif action in ("unwatch", "unignore"):
            clear_preference(session, product, action.removeprefix("un"))
        else:
            raise ValueError(f"Unknown action {action!r}")
        session.commit()
        tmdb_id, product_id = _target(product)
        return {"action": action, "tmdb_id": tmdb_id, "store_product_id": product_id}
