"""Catalog UI tests through the FastAPI test client. Temporary SQLite, no network."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from cdon_watcher.catalog.catalogue import CatalogueError, SyncPayload, sync_catalogue
from cdon_watcher.catalog.db import open_catalog
from cdon_watcher.catalog.importer import import_run
from cdon_watcher.catalog.matching import set_manual_match
from cdon_watcher.catalog.models import MovieMetadata, StoreProduct
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
        title = "Heat" if tmdb_id == 949 else f"Movie {tmdb_id}"
        return MovieDetails(tmdb_id=tmdb_id, title=title, release_year=1995, poster_path="/p.jpg")


class FakeCatalogue:
    def __init__(self, owned=(), wanted=(), fail=None):
        self.payload = {"owned": list(owned), "wanted": list(wanted)}
        self.fail = fail
        self.wants: list[dict] = []

    def fetch_sync(self):
        return SyncPayload.model_validate(self.payload)

    def create_want(self, body):
        if self.fail:
            raise CatalogueError(self.fail)
        self.wants.append(body)
        return len(self.wants) == 1


def wish(tmdb_id, formats=("Blu-ray", "UHD"), cap=None):
    return {
        "tmdb_id": tmdb_id,
        "title": f"Movie {tmdb_id}",
        "year": 1995,
        "formats": list(formats),
        "max_price_cents": cap,
    }


def matched(engine, mapping):
    """Manually match products (by store product id string) to TMDB ids."""
    product_ids = ids(engine)
    for pid, tmdb_id in mapping.items():
        set_manual_match(engine, FakeTmdb(), product_ids[pid], tmdb_id)
    return product_ids


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
            product("1", "Cheap BD", price=1500),
            product("2", "Too dear BD", price=1501),
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
    assert '<section class="wishlist">' not in html
    assert ">unmatched<" in html


@pytest.mark.parametrize(
    "query,expected",
    [
        ("", ["E used 5", "A bd 9", "C bd 15 ax", "D bd 15 cdon", "B 4k 19"]),
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


def test_wishlist_tab_ignores_caps_and_main_page_badges_wishes(client, engine):
    seed(
        engine,
        [
            product("1", "Wished dear", price=5000),
            product("2", "Normal", price=900),
            product("3", "Wished wrong format", price=900, fmt=Format.UHD),
        ],
    )
    matched(engine, {"1": 10, "2": 20, "3": 10})
    sync_catalogue(engine, FakeCatalogue(wanted=[wish(10, ["Blu-ray"])]))
    assert titles(client.get("/in-stock").text, "wishlist") == ["Movie 10"]
    assert titles(client.get("/?max_bd=1&max_4k=1").text) == []
    html = client.get("/").text
    assert '<section class="wishlist">' not in html
    assert "1 wishlist offer in stock" in html
    # Wished movies browse normally under the caps, badged, in any format.
    assert titles(html) == ["Movie 10", "Movie 20"]
    assert html.count(">on wishlist<") == 1


def test_owned_movies_are_hidden_unless_dvd_only_or_wished(client, engine):
    seed(
        engine,
        [
            product("1", "Own BD", price=900),
            product("2", "Own DVD", price=900),
            product("3", "Own UHD but wished", price=900),
            product("4", "Not owned", price=900),
            product("5", "Unmatched", price=900),
        ],
    )
    matched(engine, {"1": 1, "2": 2, "3": 3, "4": 4})
    owned = [
        {"tmdb_id": 1, "formats": ["Blu-ray"]},
        {"tmdb_id": 2, "formats": ["DVD"]},
        {"tmdb_id": 3, "formats": ["UHD"]},
    ]
    sync_catalogue(engine, FakeCatalogue(owned=owned, wanted=[wish(3, ["UHD"])]))
    html = client.get("/").text
    assert titles(html) == ["Movie 2", "Movie 3", "Movie 4", "Unmatched"]
    assert ">own: DVD<" in html and ">on wishlist<" in html
    assert "1 owned on Blu-ray/UHD hidden" in html


def test_deal_is_marked_within_the_wish_cap(client, engine):
    seed(engine, [product("1", "Cheap", price=1500), product("2", "Dear", price=2500)])
    matched(engine, {"1": 10, "2": 10})
    sync_catalogue(engine, FakeCatalogue(wanted=[wish(10, cap=2000)]))
    html = client.get("/in-stock").text
    assert titles(html, "wishlist") == ["Movie 10", "Movie 10"]
    assert html.count(">deal<") == 1


def test_wish_action_adds_to_catalogue(client, engine):
    seed(engine, [product("1", "Heat", price=900), product("2", "Mystery", price=900)])
    product_ids = matched(engine, {"1": 949})
    assert client.post(f"/api/v2/products/{product_ids['1']}/wish").status_code == 503

    catalogue = FakeCatalogue()
    client.app.state.catalogue_client = catalogue
    html = client.get("/").text
    assert html.count('data-action="wish"') == 1  # unmatched products cannot be wished for
    response = client.post(f"/api/v2/products/{product_ids['1']}/wish")
    assert response.json() == {"tmdb_id": 949, "created": True}
    assert catalogue.wants[0]["title"] == {
        "tmdb_id": 949,
        "media_type": "movie",
        "title": "Heat",
        "original_title": None,
        "year": 1995,
        "poster_path": "/p.jpg",
    }
    html = client.get("/in-stock").text
    assert titles(html, "wishlist") == ["Heat"]  # remembered before the next sync
    assert 'data-action="wish"' not in html
    assert client.post(f"/api/v2/products/{product_ids['2']}/wish").status_code == 409
    client.app.state.catalogue_client = FakeCatalogue(fail="down")
    assert client.post(f"/api/v2/products/{product_ids['1']}/wish").status_code == 502


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


def test_watch_is_gone(client, engine):
    seed(engine, [product("1", "Flip", price=900)])
    pid = ids(engine)["1"]
    assert client.post(f"/api/v2/products/{pid}/watch").status_code == 404
    response = client.get("/watchlist", follow_redirects=False)
    assert response.status_code == 308 and response.headers["location"] == "/wishlist"


def test_unmatched_tag_links_to_its_queue_entry(client, engine):
    seed(engine, [product("1", "Heat", price=900), product("2", "Box", price=900, collection=True)])
    product_ids = ids(engine)
    heat, box = product_ids["1"], product_ids["2"]
    assert f'href="/queue#product-{heat}"' in client.get("/").text
    assert f'href="/queue#product-{box}"' not in client.get("/").text  # never queued
    html = client.get("/queue").text
    assert f'id="product-{heat}"' in html
    assert 'id="queue-filter"' in html


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


def test_wishlist_page_lists_every_wish_with_offers_first(client, engine):
    seed(
        engine,
        [
            product("1", "Sold out", price=900, avail=Availability.OUT_OF_STOCK),
            product("2", "Available", price=900),
        ],
    )
    matched(engine, {"1": 10, "2": 20})
    sync_catalogue(engine, FakeCatalogue(wanted=[wish(10), wish(20, cap=1000), wish(30)]))
    html = client.get("/wishlist").text
    assert html.index("Movie 20") < html.index("Movie 10") < html.index("Movie 30")
    assert html.count("No in-stock offers") == 2
    assert html.count("Not searched yet") == 3
    assert ">deal<" in html


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


def test_offers_api_follows_the_catalogue_contract(client, engine):
    from cdon_watcher.catalog.models import Store, WishSearch

    seed(
        engine,
        [
            product("1", "Heat (4K)", price=2299, fmt=Format.UHD, regular=3599),
            product("2", "Heat BD", price=999),
            product("3", "Heat sold out", price=500, avail=Availability.OUT_OF_STOCK),
            product("5", "Heat box", price=100, collection=True),
        ],
    )
    seed(
        engine, [product("9", "Heat stale", price=50)], run_id=0, fetched=NOW - timedelta(hours=49)
    )
    product_ids = matched(engine, {"1": 949, "2": 949, "3": 949, "9": 949})
    with Session(engine) as session:
        session.get(StoreProduct, product_ids["5"]).tmdb_id = 949
        store = session.exec(select(Store)).one()
        at = datetime(2026, 11, 11, 6, 0, 0)
        session.add(
            WishSearch(store_id=store.id, tmdb_id=949, query="Heat", run_id=2, searched_at=at)
        )
        session.add(
            WishSearch(
                store_id=store.id, tmdb_id=1551, query="x", run_id=2, error="boom", failed_at=at
            )
        )
        session.commit()

    body = client.get("/api/v2/offers?tmdb_id=949&tmdb_id=1551").json()
    assert set(body["offers"]) == {"949", "1551"}
    assert body["offers"]["1551"] == {"searched_at": None, "items": []}
    heat = body["offers"]["949"]
    assert heat["searched_at"] == "2026-11-11T06:00:00Z"
    assert [i["title"] for i in heat["items"]] == ["Heat sold out", "Heat BD", "Heat (4K)"]
    first = heat["items"][2]
    assert first["id"] == product_ids["1"]
    assert set(first) == {
        "id",
        "store_key",
        "store",
        "title",
        "format",
        "condition",
        "price_cents",
        "regular_price_cents",
        "currency",
        "availability",
        "url",
        "image_url",
        "last_seen_at",
    }
    assert first["format"] == "4k" and first["regular_price_cents"] == 3599
    assert first["store_key"] == "ax" and first["store"] == "Levykauppa Äx"
    assert first["last_seen_at"].endswith("Z") and "T" in first["last_seen_at"]
    assert heat["items"][0]["availability"] == "out_of_stock"
    assert client.get("/api/v2/offers").json() == {"offers": {}}
    assert client.get("/api/v2/offers?tmdb_id=abc").status_code == 422


def test_rows_show_store_cover_else_tmdb_poster(client, engine):
    seed(engine, [product("1", "No cover", price=900), product("2", "Has cover", price=950)])
    with Session(engine) as session:
        session.exec(
            select(StoreProduct).where(StoreProduct.product_id == "2")
        ).one().image_url = "https://store.test/cover.jpg"
        session.commit()
    html = client.get("/").text
    assert html.count('<td class="thumb"><a') == 1
    assert 'src="https://store.test/cover.jpg"' in html
    matched(engine, {"1": 949})
    html = client.get("/").text
    assert 'src="https://image.tmdb.org/t/p/w154/p.jpg"' in html
    assert 'class="queue-cover" src="https://store.test/cover.jpg"' in client.get("/queue").text
