"""moviecatalog integration: pull what I own and want, push new wishes.

The catalogue owns everything about me. The watcher keeps its last successful
/api/sync response, so a refresh never fails because the catalogue is down.
The contract lives in moviecatalog's SPEC.md, "Connecting to the watcher".
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import requests
from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine
from sqlmodel import Session

from .models import CatalogueSync

logger = logging.getLogger(__name__)

CATALOGUE_FORMATS = {"bd": "Blu-ray", "4k": "UHD"}
"""Watcher format codes to the catalogue's format names. The catalogue also knows DVD."""
DISC_FORMATS = frozenset(CATALOGUE_FORMATS.values())


class OwnedMovie(BaseModel):
    tmdb_id: int
    formats: list[str]


class WantedMovie(BaseModel):
    tmdb_id: int
    title: str
    original_title: str | None = None
    year: int | None = None
    formats: list[str]
    max_price_cents: int | None = None

    def accepts(self, format_code: str) -> bool:
        return CATALOGUE_FORMATS.get(format_code) in self.formats


class SyncPayload(BaseModel):
    owned: list[OwnedMovie] = []
    wanted: list[WantedMovie] = []


class CatalogueError(RuntimeError):
    """The catalogue could not be reached or answered with an error."""


class CatalogueClient(Protocol):
    def fetch_sync(self) -> SyncPayload: ...

    def create_want(self, body: dict[str, Any]) -> bool:
        """Add a wish. True when created, False when it was already on the wishlist."""
        ...


class HttpCatalogueClient:
    def __init__(self, base_url: str, *, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def fetch_sync(self) -> SyncPayload:
        try:
            response = self.session.get(f"{self.base_url}/api/sync", timeout=self.timeout)
            response.raise_for_status()
            return SyncPayload.model_validate(response.json())
        except (requests.RequestException, ValueError, ValidationError) as error:
            raise CatalogueError(f"GET /api/sync failed: {error}") from error

    def create_want(self, body: dict[str, Any]) -> bool:
        try:
            response = self.session.post(
                f"{self.base_url}/api/wants", json=body, timeout=self.timeout
            )
        except requests.RequestException as error:
            raise CatalogueError(f"POST /api/wants failed: {error}") from error
        if response.status_code == 201:
            return True
        if response.status_code == 409:
            return False
        try:
            message = response.json().get("error") or response.text
        except ValueError:
            message = response.text
        raise CatalogueError(f"POST /api/wants returned {response.status_code}: {message}")


@dataclass
class Catalogue:
    """The stored catalogue lists, as the queries and searches use them."""

    owned: dict[int, set[str]] = field(default_factory=dict)
    wanted: dict[int, WantedMovie] = field(default_factory=dict)
    fetched_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_error: str | None = None

    def owns_disc(self, tmdb_id: int | None) -> bool:
        """Owned on Blu-ray or UHD: hidden while browsing unless wished for."""
        return tmdb_id is not None and bool(self.owned.get(tmdb_id, set()) & DISC_FORMATS)

    def owns_dvd_only(self, tmdb_id: int | None) -> bool:
        formats = self.owned.get(tmdb_id, set()) if tmdb_id is not None else set()
        return bool(formats) and not formats & DISC_FORMATS


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _row(session: Session) -> CatalogueSync:
    row = session.get(CatalogueSync, 1)
    if row is None:
        row = CatalogueSync(id=1)
        session.add(row)
    return row


def sync_catalogue(
    engine: Engine, client: CatalogueClient, *, now: datetime | None = None
) -> Catalogue:
    """Fetch and store the catalogue lists. On failure keep the previous ones."""
    now = now or _now()
    try:
        payload = client.fetch_sync()
        error = None
    except CatalogueError as failure:
        payload, error = None, str(failure)
        logger.warning("Catalogue sync failed, keeping the stored lists: %s", failure)
    with Session(engine) as session:
        row = _row(session)
        row.last_attempt_at = now
        row.last_error = error
        if payload is not None:
            row.payload_json = payload.model_dump_json()
            row.fetched_at = now
        session.commit()
        return load_catalogue(session)


def load_catalogue(session: Session) -> Catalogue:
    row = session.get(CatalogueSync, 1)
    if row is None:
        return Catalogue()
    payload = SyncPayload()
    if row.payload_json:
        payload = SyncPayload.model_validate(json.loads(row.payload_json))
    owned: dict[int, set[str]] = {}
    for movie in payload.owned:
        owned.setdefault(movie.tmdb_id, set()).update(movie.formats)
    return Catalogue(
        owned=owned,
        wanted={w.tmdb_id: w for w in payload.wanted},
        fetched_at=row.fetched_at,
        last_attempt_at=row.last_attempt_at,
        last_error=row.last_error,
    )


def remember_want(session: Session, want: WantedMovie) -> None:
    """Add a wish to the stored list right away, before the next sync confirms it."""
    row = _row(session)
    payload = SyncPayload()
    if row.payload_json:
        payload = SyncPayload.model_validate(json.loads(row.payload_json))
    if all(w.tmdb_id != want.tmdb_id for w in payload.wanted):
        payload.wanted.append(want)
        row.payload_json = payload.model_dump_json()
