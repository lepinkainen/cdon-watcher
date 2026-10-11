"""Catalog UI tests through the FastAPI test client. Temporary SQLite, no network."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from cdon_watcher.catalog.db import open_catalog
from cdon_watcher.catalog.importer import import_run
from cdon_watcher.catalog.matching import set_manual_match
from cdon_watcher.catalog.models import MovieMetadata, StoreProduct
from cdon_watcher.catalog.preferences import apply
from cdon_watcher.catalog.tmdb import Candidate, MovieDetails
from cdon_watcher.config import CONFIG
from cdon_watcher.ingestion.contract import (
    Availability,
    Condition,
    Format,
    ParsedProduct,
    ParsedRun,
    ParsedSnapshot,
)
from cdon_watcher.web.app import create_app

NOW = datetime.now(UTC)


class FakeTmdb:
    def search_movies(self, query, year=None):
        return [Candidate(949, "Heat", release_year=1995, popularity=50)]

    def movie_details(self, tmdb_id):
        return MovieDetails(tmdb_id=tmdb_id, title="Heat", release_year=1995, imdb_id="tt0113277")


def product(
    pid,
    title,
    *,
    store="ax",
    price=999,
    fmt=Format.BLURAY,
    cond=Condition.NEW,
    avail=Availability.IN_STOCK,
    collection=False,
    regular=None,
):
    return ParsedProduct(
        store=store,
        product_id=pid,
        raw_title=title,
        cleaned_title=title,
        edition_url=f"https://{store}.test/{pid}#{pid}",
        format=fmt,
        format_raw=fmt.value,
        condition=cond,
        availability=avail,
        price_cents=price,
        regular_price_cents=regular,
        is_collection=collection,
    )


def seed(engine, products, *, store="ax", run_id=1, fetched=None):
    fetched = fetched or NOW
    import_run(
        engine,
        ParsedRun(
            store=store,
            run_id=run_id,
            parser_version="t",
            complete=True,
            parsed_at=fetched,
            snapshots=[
                ParsedSnapshot(
                    snapshot_id=1, requested_url="u", fetched_at=fetched, products=list(products)
                )
            ],
        ),
    )


def ids(engine):
    with Session(engine) as session:
        return {p.product_id: p.id for p in session.exec(select(StoreProduct)).all()}


@pytest.fixture
def engine(tmp_path, monkeypatch):
    path = tmp_path / "catalog.db"
    monkeypatch.setitem(CONFIG, "db_path", str(path))
    return open_catalog(path)


@pytest.fixture
def client(engine):
    app = create_app()
    app.state.tmdb_client = FakeTmdb()
    with TestClient(app) as client:
        yield client


def titles(html, section=None):
    """Titles of product rows, in page order; optionally only inside a section class."""
    import re

    if section:
        start = html.index(f'<section class="{section}">')
        end = html.index("</section>", start)
        html = html[start:end]
    return re.findall(r'<a href="https://[^"]+" target="_blank" rel="noopener">([^<]+)</a>', html)


def test_main_page_applies_default_caps_and_sorts_by_price(client, engine):
    seed(
        engine,
        [
            product("1", "Cheap BD", price=999),
            product("2", "Too dear BD", price=1001),
            product("3", "Cheap 4K", price=2000, fmt=Format.UHD),
            product("4", "Too dear 4K", price=2001, fmt=Format.UHD),
            product("5", "Cheapest", price=500),
            product("6", "Out of stock", price=100, avail=Availability.OUT_OF_STOCK),
            product("7", "Supplier", price=100, avail=Availability.SUPPLIER_ORDER),
            product("8", "DVD", price=100, fmt=Format.DVD),
        ],
    )
    html = client.get("/").text
    assert titles(html) == ["Cheapest", "Cheap BD", "Cheap 4K"]
    assert '<section class="watchlist">' not in html
    assert ">unmatched<" in html


@pytest.mark.parametrize(
    "query,expected",
    [
        ("", ["E used 5", "A bd 9", "B 4k 19"]),
        ("max_bd=10&max_4k=10", ["E used 5", "A bd 9"]),
        ("format=4k", ["B 4k 19"]),
        ("format=bd&max_bd=15&store=ax", ["E used 5", "A bd 9", "C bd 15 ax"]),
        ("format=bd&max_bd=15&store=cdon", ["D bd 15 cdon"]),
        ("condition=used", ["E used 5"]),
        ("q=cdon&max_bd=15", ["D bd 15 cdon"]),
        ("max_bd=5,00", ["E used 5", "B 4k 19"]),
    ],
)
def test_filter_table_questions(client, engine, query, expected):
    seed(
        engine,
        [
            product("1", "A bd 9", price=900),
            product("2", "B 4k 19", price=1900, fmt=Format.UHD),
            product("3", "C bd 15 ax", price=1500),
            product("5", "E used 5", price=500, cond=Condition.USED),
        ],
    )
    seed(engine, [product("x", "D bd 15 cdon", store="cdon", price=1500)], store="cdon")
    html = client.get(f"/?{query}").text
    assert titles(html) == expected


def test_filter_results_are_price_sorted(client, engine):
    seed(
        engine,
        [product("1", "Z", price=900), product("2", "A", price=950), product("3", "M", price=900)],
    )
    assert titles(client.get("/").text) == ["M", "Z", "A"]


def test_invalid_price_limit_is_400(client):
    assert client.get("/?max_bd=abc").status_code == 400


def test_watchlist_section_first_ignores_caps_and_is_not_duplicated(client, engine):
    seed(
        engine,
        [
            product("1", "Watched dear", price=5000),
            product("2", "Normal", price=900),
        ],
    )
    pid = ids(engine)["1"]
    assert client.post(f"/api/v2/products/{pid}/watch").json()["store_product_id"] == pid
    html = client.get("/?max_bd=1").text
    assert titles(html, "watchlist") == ["Watched dear"]
    assert titles(html) == ["Watched dear"]  # filter removed Normal, watched stays
    html = client.get("/").text
    assert titles(html) == ["Watched dear", "Normal"]
    assert html.index('<section class="watchlist">') < html.index('<form class="filters"')


def test_ignore_hides_everywhere_and_unignore_restores(client, engine):
    seed(engine, [product("1", "Hide me", price=900), product("2", "Keep", price=900)])
    pid = ids(engine)["1"]
    client.post(f"/api/v2/products/{pid}/ignore")
    assert titles(client.get("/").text) == ["Keep"]
    ignored = client.get("/ignored").text
    assert "Hide me" in ignored and "Keep" not in ignored
    client.post(f"/api/v2/products/{pid}/unignore")
    assert titles(client.get("/").text) == ["Hide me", "Keep"]


def test_ignore_matched_movie_hides_every_edition_across_stores(client, engine):
    seed(engine, [product("1", "Heat", price=900)], store="ax")
    seed(engine, [product("c1", "Heat Blu-ray", store="cdon", price=950)], store="cdon")
    product_ids = ids(engine)
    set_manual_match(engine, FakeTmdb(), product_ids["1"], 949)
    set_manual_match(engine, FakeTmdb(), product_ids["c1"], 949)
    html = client.get("/").text
    assert titles(html) == ["Heat", "Heat"]  # TMDB title replaces both raw titles
    result = client.post(f"/api/v2/products/{product_ids['1']}/ignore").json()
    assert result["tmdb_id"] == 949
    assert titles(client.get("/").text) == []
    assert len(titles(client.get("/ignored").text)) == 0  # ignored page lists one movie row
    assert client.get("/ignored").text.count("Heat") == 1


def test_watch_and_ignore_are_mutually_exclusive(client, engine):
    seed(engine, [product("1", "Flip", price=900)])
    pid = ids(engine)["1"]
    client.post(f"/api/v2/products/{pid}/ignore")
    client.post(f"/api/v2/products/{pid}/watch")
    html = client.get("/").text
    assert titles(html, "watchlist") == ["Flip"]
    assert "Flip" not in client.get("/ignored").text


def test_queue_lists_unmatched_in_stock_single_movies_and_manual_match(client, engine):
    seed(
        engine,
        [
            product("1", "Heat", price=900),
            product("2", "Box", price=900, collection=True),
            product("3", "Gone", price=900, avail=Availability.OUT_OF_STOCK),
        ],
    )
    html = client.get("/queue").text
    assert "Heat" in html and "Box" not in html and "Gone" not in html
    pid = ids(engine)["1"]
    assert client.post(f"/api/v2/products/{pid}/match", json={"tmdb_id": 949}).json() == {
        "status": "manual",
        "tmdb_id": 949,
    }
    assert "Heat" not in client.get("/queue").text
    assert client.get("/match", follow_redirects=False).status_code == 307
    with Session(engine) as session:
        assert session.get(MovieMetadata, 949) is not None
    assert client.post(f"/api/v2/products/{pid}/match", json={"tmdb_id": "x"}).status_code == 400
    assert client.post("/api/v2/products/999/match", json={"tmdb_id": None}).status_code == 404


def test_tmdb_search_endpoint(client):
    data = client.get("/api/v2/tmdb/search?q=heat").json()
    assert data[0]["tmdb_id"] == 949


def test_watchlist_page_shows_entries_without_offers(client, engine):
    seed(
        engine,
        [
            product("1", "Sold out watched", price=900, avail=Availability.OUT_OF_STOCK),
            product("2", "Available watched", price=900),
        ],
    )
    product_ids = ids(engine)
    apply(engine, product_ids["1"], "watch")
    apply(engine, product_ids["2"], "watch")
    html = client.get("/watchlist").text
    assert "Available watched" in html and "Sold out watched" in html
    assert "No in-stock offers" in html
    assert html.index("Available watched") < html.index("Sold out watched")
    assert titles(client.get("/").text, "watchlist") == ["Available watched"]


def test_stale_products_are_hidden(client, engine):
    seed(engine, [product("1", "Old", price=900)], fetched=NOW - timedelta(hours=49))
    seed(engine, [product("2", "Fresh", price=900)], run_id=2)  # run 2 complete: expires Old too
    assert titles(client.get("/").text) == ["Fresh"]
    status = client.get("/status").text
    assert "Levykauppa Äx" in status


def test_product_history_and_404(client, engine):
    seed(engine, [product("1", "Heat", price=900, regular=1200)])
    seed(engine, [product("1", "Heat", price=800, regular=1200)], run_id=2)
    pid = ids(engine)["1"]
    html = client.get(f"/products/{pid}").text
    assert "8,00 €" in html and "9,00 €" in html and "12,00 €" in html
    assert client.get("/products/999").status_code == 404
    assert client.post(f"/api/v2/products/{pid}/bogus").status_code == 404


def test_regular_price_is_shown_struck_through(client, engine):
    seed(engine, [product("1", "Deal", price=900, regular=1500)])
    assert "<del>15,00 €</del>" in client.get("/").text
