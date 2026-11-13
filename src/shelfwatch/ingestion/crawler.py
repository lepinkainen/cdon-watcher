"""Standalone polite HTTP crawler that only writes fetch evidence."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import requests

from .archive import ArchivedRun, RawArchive, Snapshot
from .stores import StoreAdapter

logger = logging.getLogger(__name__)


@dataclass
class Response:
    final_url: str
    status: int
    body: bytes
    rendered: bool = False


class FetchError(Exception):
    """Transport failure from a non-requests fetcher; retried like a request error."""


class HttpFetcher:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "shelfwatch/0.1 (private movie offer archive)"

    def __call__(self, url: str) -> Response:
        # Archive redirects as failures instead of silently fetching outside the scope.
        response = self.session.get(url, timeout=30, allow_redirects=False)
        return Response(response.url, response.status_code, response.content)

    def close(self) -> None:
        self.session.close()


class Crawler:
    def __init__(
        self,
        archive: RawArchive,
        fetch: Callable[[str], Response],
        *,
        attempts: int = 3,
        delay: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if attempts < 1 or not 0 < delay < float("inf"):
            raise ValueError("Attempts and request delay must be positive and finite")
        self.archive = archive
        self.fetch = fetch
        self.attempts = attempts
        self.delay = delay
        self.sleep = sleep
        self.requested = False
        # The run being written, kept so a caller can import what an aborted crawl saved.
        self.run: ArchivedRun | None = None

    def _fetch(self, run: ArchivedRun, url: str, attempt: int) -> tuple[Snapshot, bytes | None]:
        if self.requested:
            self.sleep(self.delay)
        self.requested = True
        try:
            response = self.fetch(url)
        except (requests.RequestException, FetchError) as error:
            return run.record(
                url, final_url=None, status=None, body=None, attempt=attempt, error=str(error)
            ), None
        snapshot = run.record(
            url,
            final_url=response.final_url,
            status=response.status,
            body=response.body,
            attempt=attempt,
            rendered=response.rendered,
            error=None if response.status == 200 else f"HTTP {response.status}",
        )
        return snapshot, response.body if response.status == 200 else None

    def crawl(self, adapter: StoreAdapter) -> ArchivedRun:
        with self.archive.start(adapter.key, adapter.scope) as run:
            self.run = run
            pending = list(adapter.start_urls)
            visited: set[str] = set()
            signatures: set[tuple[str, ...]] = set()
            product_ids: set[str] = set()
            while pending:
                url = pending.pop(0)
                if url in visited:
                    continue
                visited.add(url)
                self._page(run, adapter, url, pending, signatures, product_ids)
            run.manifest.complete = not run.manifest.failures
        return run

    def _page(
        self,
        run: ArchivedRun,
        adapter: StoreAdapter,
        url: str,
        pending: list[str],
        signatures: set[tuple[str, ...]],
        product_ids: set[str],
    ) -> None:
        for attempt in range(1, self.attempts + 1):
            snapshot, body = self._fetch(run, url, attempt)
            if body is not None:
                try:
                    listing = adapter.discover(body, url, snapshot.final_url or url)
                    if listing.signature in signatures:
                        raise ValueError("Pagination loop: repeated listing products")
                except ValueError as error:
                    snapshot.error = str(error)
                else:
                    snapshot.products = listing.products
                    signatures.add(listing.signature)
                    pending.extend(p for p in listing.pages if p not in pending)
                    product_ids.update(p.product_id for p in listing.products)
                    run.manifest.listing_count += 1
                    run.manifest.product_count = len(product_ids)
                    run.save()
                    logger.debug(
                        "%s page %d: %d products, %d editions so far (%s)",
                        adapter.key,
                        run.manifest.listing_count,
                        len(listing.products),
                        len(product_ids),
                        url,
                    )
                    return
            logger.debug(
                "%s attempt %d/%d failed: %s (%s)",
                adapter.key,
                attempt,
                self.attempts,
                snapshot.error,
                url,
            )
            run.save()
        run.manifest.failures.append(f"{url}: {snapshot.error} after {self.attempts} attempts")
        run.save()
