"""Tag log records with the store being refreshed, so parallel store runs read apart."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_store: ContextVar[str | None] = ContextVar("shelfwatch_store", default=None)


@contextmanager
def store_context(store: str) -> Iterator[None]:
    """Log records from this thread carry the store until the block ends."""
    token = _store.set(store)
    try:
        yield
    finally:
        _store.reset(token)


class StoreFilter(logging.Filter):
    """Sets record.store to "[ax]" inside a store_context, "" outside, for %(store)s."""

    def filter(self, record: logging.LogRecord) -> bool:
        store = _store.get()
        record.store = f"[{store}]" if store else ""
        return True


def install(handler: logging.Handler, width: int) -> None:
    """Show the store as a fixed-width column between the level and the message."""
    handler.addFilter(StoreFilter())
    handler.setFormatter(
        logging.Formatter(f"%(asctime)s %(levelname)-7s %(store)-{width}s %(message)s")
    )
