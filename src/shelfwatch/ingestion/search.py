"""Targeted store searches for wished-for movies. Archives responses only.

One search per wished movie per store, by title, falling back to the original
title when the title finds nothing. First results page only, never product
pages; the same politeness delay as the category crawl. What counts as a hit
for the wished movie is decided later, by matching.
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote, quote_plus, urlsplit

import requests
from bs4 import BeautifulSoup

from .archive import ArchivedRun, RawArchive
from .contract import SEARCH_SCOPE
from .crawler import FetchError, Response
from .mymovies import ANY_AVAILABILITY, page_url, parse_url, read_results

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchTask:
    tmdb_id: int
    title: str
    original_title: str | None = None

    @property
    def queries(self) -> list[str]:
        queries = [self.title.strip()]
        original = (self.original_title or "").strip()
        if original and original.casefold() != queries[0].casefold():
            queries.append(original)
        return [q for q in queries if q]


class SearchAdapter(Protocol):
    key: str

    def search_url(self, query: str) -> str: ...

    def result_count(self, body: bytes, final_url: str) -> int:
        """Results on the page; raises ValueError when it is not a results page."""
        ...


class AxSearchAdapter:
    key = "ax"

    def search_url(self, query: str) -> str:
        return f"https://www.levykauppax.fi/v2/search/?q={quote_plus(query)}"

    def result_count(self, body: bytes, final_url: str) -> int:
        parsed = urlsplit(final_url)
        if parsed.netloc != "www.levykauppax.fi" or parsed.path != "/v2/search/":
            raise ValueError(f"Search left the results page: {final_url}")
        soup = BeautifulSoup(body, "html.parser")
        heading = soup.select_one("h1")
        if heading is None or heading.get_text(" ", strip=True) != "Haku":
            raise ValueError("Missing search heading; possible error page")
        return len(soup.select("ul.list-products > li.hproduct"))


class CdonSearchAdapter:
    """cdon.fi/s?q= through the browser; the body is the page's own result JSON."""

    key = "cdon"

    def search_url(self, query: str) -> str:
        return f"https://cdon.fi/s?q={quote(query)}"

    def result_count(self, body: bytes, final_url: str) -> int:
        try:
            data = json.loads(body)
        except (ValueError, UnicodeDecodeError) as error:
            raise ValueError(f"Malformed search result: {error}") from error
        articles = data.get("articles") if isinstance(data, dict) else None
        if not isinstance(articles, list):
            raise ValueError("Search result has no articles")
        return len(articles)


class MyMoviesSearchAdapter:
    """The MyMovies search endpoint, any availability; the body is its result JSON."""

    key = "mymovies"

    def search_url(self, query: str) -> str:
        return page_url(query, ANY_AVAILABILITY)

    def result_count(self, body: bytes, final_url: str) -> int:
        request = parse_url(final_url)
        if request.availability != ANY_AVAILABILITY or not request.query:
            raise ValueError(f"Not a wishlist search URL: {final_url}")
        return len(read_results(body).cards)


class Searcher:
    def __init__(
        self,
        archive: RawArchive,
        fetch: Callable[[str], Response],
        adapter: SearchAdapter,
        *,
        attempts: int = 3,
        delay: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if attempts < 1 or not 0 < delay < float("inf"):
            raise ValueError("Attempts and request delay must be positive and finite")
        self.archive = archive
        self.fetch = fetch
        self.adapter = adapter
        self.attempts = attempts
        self.delay = delay
        self.sleep = sleep

    def search(self, tasks: list[SearchTask]) -> ArchivedRun:
        with self.archive.start(self.adapter.key, SEARCH_SCOPE) as run:
            for task in tasks:
                for query in task.queries:
                    count = self._query(run, task, query)
                    if count != 0:  # None (failed) or results: no fallback
                        break
            run.manifest.complete = not run.manifest.failures
        return run

    def _query(self, run: ArchivedRun, task: SearchTask, query: str) -> int | None:
        """Search once with retries. Result count, or None when every attempt failed."""
        url = self.adapter.search_url(query)
        error = "not attempted"
        for attempt in range(1, self.attempts + 1):
            self.sleep(self.delay)
            body: bytes | None = None
            final_url: str | None = None
            status: int | None = None
            rendered = False
            try:
                response = self.fetch(url)
                body, final_url, status = response.body, response.final_url, response.status
                rendered = response.rendered
                if status != 200:
                    raise ValueError(f"HTTP {status}")
                count = self.adapter.result_count(body, final_url)
            except (requests.RequestException, FetchError, ValueError) as failure:
                error = str(failure)
                run.record(
                    url,
                    final_url=final_url,
                    status=status,
                    body=body,
                    attempt=attempt,
                    rendered=rendered,
                    error=error,
                    search_tmdb_id=task.tmdb_id,
                    search_query=query,
                )
                logger.debug(
                    "%s search %r attempt %d failed: %s", run.manifest.store, query, attempt, error
                )
                continue
            run.record(
                url,
                final_url=final_url,
                status=status,
                body=body,
                attempt=attempt,
                rendered=rendered,
                search_tmdb_id=task.tmdb_id,
                search_query=query,
            )
            run.manifest.listing_count += 1
            run.manifest.product_count += count
            run.save()
            logger.debug("%s search %r: %d results", run.manifest.store, query, count)
            return count
        run.manifest.failures.append(f"{query!r}: {error} after {self.attempts} attempts")
        run.save()
        return None


def make_search_adapter(store: str) -> SearchAdapter:
    if store == "cdon":
        return CdonSearchAdapter()
    if store == "ax":
        return AxSearchAdapter()
    if store == "mymovies":
        return MyMoviesSearchAdapter()
    raise ValueError(f"No search adapter for store {store!r}")
