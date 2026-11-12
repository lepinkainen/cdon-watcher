"""Minimal TMDB v3 client for movie matching. One search request per query."""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.themoviedb.org/3"


@dataclass
class Candidate:
    tmdb_id: int
    title: str
    original_title: str | None = None
    release_year: int | None = None
    popularity: float = 0.0
    poster_path: str | None = None
    overview: str | None = None


@dataclass
class MovieDetails:
    tmdb_id: int
    title: str
    original_title: str | None = None
    release_year: int | None = None
    imdb_id: str | None = None
    poster_path: str | None = None
    overview: str | None = None
    director: str | None = None
    cast: list[str] = field(default_factory=list)


class TmdbError(RuntimeError):
    """TMDB was unreachable or answered with an error. Retry later."""


class TmdbClient(Protocol):
    def search_movies(self, query: str, year: int | None = None) -> list[Candidate]: ...

    def movie_details(self, tmdb_id: int) -> MovieDetails: ...


def _year(date: Any) -> int | None:
    if isinstance(date, str) and len(date) >= 4 and date[:4].isdigit():
        return int(date[:4])
    return None


class HttpTmdbClient:
    def __init__(self, api_key: str, *, min_interval: float = 0.05) -> None:
        if not api_key:
            raise ValueError("TMDB_API_KEY is required for matching")
        self.api_key = api_key
        self.session = requests.Session()
        self.min_interval = min_interval
        self._last = 0.0

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        try:
            response = self.session.get(
                f"{BASE_URL}{path}", params={"api_key": self.api_key, **params}, timeout=15
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as error:
            raise TmdbError(f"TMDB request {path} failed: {error}") from error
        if not isinstance(data, dict):
            raise TmdbError(f"TMDB request {path} returned an unexpected payload")
        return data

    def search_movies(self, query: str, year: int | None = None) -> list[Candidate]:
        params: dict[str, Any] = {"query": query, "include_adult": "false", "language": "en-US"}
        if year:
            params["primary_release_year"] = year
        data = self._get("/search/movie", **params)
        candidates = []
        for item in data.get("results", [])[:10]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), int):
                continue
            candidates.append(
                Candidate(
                    tmdb_id=item["id"],
                    title=str(item.get("title") or ""),
                    original_title=item.get("original_title"),
                    release_year=_year(item.get("release_date")),
                    popularity=float(item.get("popularity") or 0.0),
                    poster_path=item.get("poster_path"),
                    overview=item.get("overview"),
                )
            )
        return candidates

    def movie_details(self, tmdb_id: int) -> MovieDetails:
        data = self._get(f"/movie/{tmdb_id}", append_to_response="credits,external_ids")
        crew = data.get("credits", {}).get("crew", [])
        directors = [c["name"] for c in crew if isinstance(c, dict) and c.get("job") == "Director"]
        cast = [
            c["name"] for c in data.get("credits", {}).get("cast", [])[:3] if isinstance(c, dict)
        ]
        return MovieDetails(
            tmdb_id=tmdb_id,
            title=str(data.get("title") or ""),
            original_title=data.get("original_title"),
            release_year=_year(data.get("release_date")),
            imdb_id=data.get("external_ids", {}).get("imdb_id") or data.get("imdb_id"),
            poster_path=data.get("poster_path"),
            overview=data.get("overview"),
            director=", ".join(directors[:2]) or None,
            cast=cast,
        )
