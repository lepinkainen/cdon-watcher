"""moviecatalog sync: stored lists, failure handling, HTTP client. No network."""

from datetime import datetime
from unittest.mock import Mock

import pytest
import requests
from sqlalchemy import inspect
from sqlmodel import Session

from cdon_watcher.catalog.catalogue import (
    CatalogueError,
    HttpCatalogueClient,
    SyncPayload,
    WantedMovie,
    load_catalogue,
    remember_want,
    sync_catalogue,
)
from cdon_watcher.catalog.db import CURRENT_VERSION, migrate, open_catalog

PAYLOAD = {
    "owned": [
        {"tmdb_id": 1, "formats": ["Blu-ray"]},
        {"tmdb_id": 2, "formats": ["DVD"]},
        {"tmdb_id": 3, "formats": ["DVD", "UHD"]},
    ],
    "wanted": [
        {
            "tmdb_id": 9874,
            "title": "Cobra",
            "original_title": "Cobra",
            "year": 1986,
            "formats": ["UHD"],
            "max_price_cents": 2000,
        }
    ],
}


class FakeCatalogue:
    def __init__(self, payload=PAYLOAD, error=None):
        self.payload, self.error = payload, error
        self.wants: list[dict] = []

    def fetch_sync(self):
        if self.error:
            raise CatalogueError(self.error)
        return SyncPayload.model_validate(self.payload)

    def create_want(self, body):
        self.wants.append(body)
        return True


def test_sync_stores_lists_and_classifies_ownership(tmp_path):
    engine = open_catalog(tmp_path / "c.db")
    catalogue = sync_catalogue(engine, FakeCatalogue(), now=datetime(2026, 11, 11, 6))
    assert catalogue.fetched_at == datetime(2026, 11, 11, 6)
    assert catalogue.last_error is None
    assert catalogue.owns_disc(1) and not catalogue.owns_dvd_only(1)
    assert catalogue.owns_dvd_only(2) and not catalogue.owns_disc(2)
    assert catalogue.owns_disc(3)
    assert not catalogue.owns_disc(4) and not catalogue.owns_dvd_only(None)
    cobra = catalogue.wanted[9874]
    assert cobra.accepts("4k") and not cobra.accepts("bd")


def test_failed_sync_keeps_previous_lists_and_records_error(tmp_path):
    engine = open_catalog(tmp_path / "c.db")
    sync_catalogue(engine, FakeCatalogue(), now=datetime(2026, 11, 10))
    catalogue = sync_catalogue(
        engine, FakeCatalogue(error="connection refused"), now=datetime(2026, 11, 11)
    )
    assert catalogue.last_error == "connection refused"
    assert catalogue.fetched_at == datetime(2026, 11, 10)
    assert catalogue.last_attempt_at == datetime(2026, 11, 11)
    assert set(catalogue.wanted) == {9874}


def test_never_synced_is_empty(tmp_path):
    engine = open_catalog(tmp_path / "c.db")
    with Session(engine) as session:
        catalogue = load_catalogue(session)
    assert catalogue.owned == {} and catalogue.wanted == {} and catalogue.fetched_at is None


def test_remember_want_adds_once(tmp_path):
    engine = open_catalog(tmp_path / "c.db")
    sync_catalogue(engine, FakeCatalogue())
    heat = WantedMovie(tmdb_id=949, title="Heat", year=1995, formats=["Blu-ray", "UHD"])
    with Session(engine) as session:
        remember_want(session, heat)
        remember_want(session, heat)
        session.commit()
        assert set(load_catalogue(session).wanted) == {9874, 949}


def test_migration_is_current_and_idempotent(tmp_path):
    engine = open_catalog(tmp_path / "c.db")
    assert migrate(engine) == CURRENT_VERSION == 4
    tables = set(inspect(engine).get_table_names())
    assert {"catalogue_sync", "wish_searches", "search_hits"} <= tables
    columns = {c["name"] for c in inspect(engine).get_columns("store_products")}
    assert {"category_member", "category_run_id"} <= columns


def _response(status, payload=None, text=""):
    response = Mock(status_code=status, text=text)
    response.json.return_value = payload
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status}")
    return response


def test_http_client_sync_and_wants():
    client = HttpCatalogueClient("http://catalogue:8080/")
    client.session = Mock()
    client.session.get.return_value = _response(200, PAYLOAD)
    assert len(client.fetch_sync().owned) == 3
    client.session.get.assert_called_with("http://catalogue:8080/api/sync", timeout=10.0)

    client.session.post.return_value = _response(201, {})
    assert client.create_want({"title": {}}) is True
    client.session.post.return_value = _response(409, {"error": "already on the wishlist"})
    assert client.create_want({"title": {}}) is False
    client.session.post.return_value = _response(400, {"error": "a wish needs a title"})
    with pytest.raises(CatalogueError, match="a wish needs a title"):
        client.create_want({"title": {}})


@pytest.mark.parametrize(
    "failure",
    [requests.ConnectionError("refused"), _response(500), _response(200, {"owned": "nope"})],
)
def test_http_client_sync_failures_become_catalogue_errors(failure):
    client = HttpCatalogueClient("http://catalogue:8080")
    client.session = Mock()
    if isinstance(failure, Exception):
        client.session.get.side_effect = failure
    else:
        client.session.get.return_value = failure
    with pytest.raises(CatalogueError):
        client.fetch_sync()
