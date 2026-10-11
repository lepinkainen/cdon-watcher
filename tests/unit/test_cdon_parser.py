"""CDON adapter, parser and crawl tests against rendered fixtures. No network."""

import gzip
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from bs4 import BeautifulSoup

from cdon_watcher.ingestion.archive import RawArchive
from cdon_watcher.ingestion.cdon_parser import CdonParser
from cdon_watcher.ingestion.contract import Availability, Condition, Format
from cdon_watcher.ingestion.crawler import Crawler, Response
from cdon_watcher.ingestion.normalize import clean_title
from cdon_watcher.ingestion.parse import parse_run
from cdon_watcher.ingestion.stores import CdonAdapter

FIXTURES = Path(__file__).parents[1] / "fixtures" / "cdon"
URL = CdonAdapter.start_url


def fixture(page=1):
    return gzip.decompress((FIXTURES / f"elokuvat-page-{page}.html.gz").read_bytes())


def by_id(products, product_id):
    return next(p for p in products if p.product_id == product_id)


def page_with_articles(articles, page=1):
    """Fixture page whose article list and page marker are replaced."""
    soup = BeautifulSoup(fixture(), "html.parser")
    node = soup.select_one("script#__NEXT_DATA__")
    data = json.loads(node.get_text())
    data["props"]["pageProps"]["serverData"]["articles"] = articles
    node.string = json.dumps(data)
    html = str(soup).replace("Sivu 1/", f"Sivu {page}/")
    return html.encode()


def article(**changes):
    base = {
        "articleId": "f22e2fd9-169a-5422-bd30-a79c8dc97f5a",
        "title": "Saw X Blu Ray",
        "slug": "saw-x-blu-ray-f22e2fd9169a5422",
        "articleUrl": "/tuote/saw-x-blu-ray-f22e2fd9169a5422",
        "price": {"formatted": "9,90 €", "amount": 9.9, "currency": "EUR"},
        "stock": 2,
        "publishState": "published",
        "images": [{"url": "https://images.example/saw.jpg"}],
        "classifications": [{"name": "condition", "value": "new"}],
        "properties": [{"name": "preset_media_format", "value": "blu-ray"}],
    }
    base.update(changes)
    return base


def test_parse_page_two_articles():
    products, errors = CdonParser().parse(fixture(2))
    assert errors == []
    assert len(products) == 48
    saw = by_id(products, "f22e2fd9169a5422")
    assert saw.raw_title == "Saw X Blu Ray"
    assert saw.cleaned_title == "Saw X"
    assert saw.edition_url == "https://cdon.fi/tuote/saw-x-blu-ray-f22e2fd9169a5422/"
    assert saw.format is Format.BLURAY
    assert {"blu-ray", "4k ultra hd", "dvd"} <= {p.format_raw for p in products}
    assert (saw.condition, saw.condition_raw) == (Condition.UNKNOWN, None)  # no classification
    assert sum(p.condition is Condition.NEW for p in products) > 40
    assert (saw.price_cents, saw.currency, saw.regular_price_cents) == (990, "EUR", None)
    assert (saw.availability, saw.stock_quantity) == (Availability.IN_STOCK, 2)
    assert saw.image_url is not None and saw.image_url.startswith("https://")
    assert saw.release_year is None
    uhd = by_id(products, "c2ef4622832b5dd2")
    assert uhd.format is Format.UHD
    assert by_id(products, "a267871f40475613").format is Format.DVD
    assert sum(p.eligible for p in products) == 28


def test_parse_page_one_resolves_every_format():
    products, errors = CdonParser().parse(fixture())
    assert errors == []
    assert len(products) == 48
    assert all(p.format is not Format.UNKNOWN for p in products)
    assert sum(p.eligible for p in products) == 44


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"stock": 0}, Availability.OUT_OF_STOCK),
        ({"stock": 7}, Availability.IN_STOCK),
        ({"publishState": "unpublished"}, Availability.UNKNOWN),
        ({"stock": None}, Availability.UNKNOWN),
    ],
)
def test_availability_from_stock_and_publish_state(changes, expected):
    products, _ = CdonParser().parse(page_with_articles([article(**changes)]))
    assert products[0].availability is expected


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"properties": [{"name": "preset_media_format", "value": "4k ultra hd"}]}, Format.UHD),
        ({"properties": [], "slug": "alien-4k-uhd-blu-ray-0123456789abcdef"}, Format.UHD),
        ({"properties": [], "slug": "alien-dvd-0123456789abcdef"}, Format.DVD),
        ({"properties": [], "slug": "alien-0123456789abcdef", "title": "Alien"}, Format.UNKNOWN),
    ],
)
def test_format_property_then_slug(changes, expected):
    products, _ = CdonParser().parse(page_with_articles([article(**changes)]))
    assert products[0].format is expected


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"price": {"amount": 0, "currency": "EUR"}}, "invalid price"),
        ({"price": {"formatted": "9,90 €"}}, "invalid price"),
        ({"slug": "no-id-here"}, "16-hex id"),
        ({"title": ""}, "empty title"),
    ],
)
def test_bad_articles_become_errors(changes, reason):
    products, errors = CdonParser().parse(page_with_articles([article(**changes), article()]))
    assert len(products) == 1
    assert len(errors) == 1
    assert reason in errors[0].reason


def test_challenge_page_is_one_error():
    body = b"<html><head><title>Just a moment...</title></head><body></body></html>"
    products, errors = CdonParser().parse(body)
    assert products == []
    assert "__NEXT_DATA__" in errors[0].reason


def test_collection_flag_from_title():
    products, _ = CdonParser().parse(fixture(2))
    assert by_id(products, "42d88a2af0c2504b").is_collection  # Rambo Trilogy 4K
    assert by_id(products, "266b68feaa86577f").is_collection  # 5-Film Collection
    assert not by_id(products, "f22e2fd9169a5422").is_collection
    # Disc count alone never makes a collection: a 5+5 disc limited box stays a product.
    assert not by_id(products, "9a377654f4935245").is_collection


@pytest.mark.parametrize(
    "raw,cleaned",
    [
        ("Saw X Blu Ray", "Saw X"),
        ("Lee Cronin's The Mummy 4K UHD", "Lee Cronin's The Mummy"),
        ("Scrooged - Haamujen kosto Blu-ray", "Scrooged - Haamujen kosto"),
        ("Heat (Blu-ray)", "Heat"),
        ("Dune: Part Two", "Dune: Part Two"),
    ],
)
def test_clean_title_strips_trailing_formats(raw, cleaned):
    assert clean_title(raw) == cleaned


def test_adapter_discovers_eligible_products_and_page_window():
    adapter = CdonAdapter(max_pages=3)
    listing = adapter.discover(fixture(2), URL + "?page=2", URL + "?page=2")
    assert listing.pages == [URL, URL + "?page=2", URL + "?page=3"]
    products, _ = CdonParser().parse(fixture(2))
    assert len(listing.products) == sum(p.eligible for p in products) == 28
    assert len(listing.signature) == 48
    assert all(p.edition_url.startswith("https://cdon.fi/tuote/") for p in listing.products)


@pytest.mark.parametrize(
    "requested,final,body",
    [
        (URL + "?page=2", URL + "?page=2", b"<html>Just a moment...</html>"),
        (URL + "?page=2", URL, None),  # redirected back to page 1
        (URL + "?page=3", URL + "?page=3", "loop"),  # page says Sivu 2
        (URL + "?page=2&sort=x", URL + "?page=2&sort=x", None),
    ],
)
def test_adapter_rejects_bad_pages(requested, final, body):
    if body is None:
        body = fixture(2)
    elif body == "loop":
        body = fixture(2)  # page marker says Sivu 2 while page 3 was requested
    with pytest.raises(ValueError):
        CdonAdapter().discover(body, requested, final)


def test_crawl_fetches_only_the_page_window_and_marks_rendered(tmp_path):
    bodies = {URL: fixture(1), URL + "?page=2": fixture(2)}
    fetch = Mock(side_effect=lambda url: Response(url, 200, bodies[url], rendered=True))
    run = Crawler(RawArchive(tmp_path), fetch, sleep=Mock()).crawl(CdonAdapter(max_pages=2))
    assert run.manifest.complete
    assert [c.args[0] for c in fetch.call_args_list] == [URL, URL + "?page=2"]
    assert run.manifest.listing_count == 2
    assert all(s.rendered for s in run.manifest.snapshots)
    parsed = parse_run(tmp_path, CdonParser())
    assert parsed.store == "cdon"
    assert parsed.expire_unseen is False
    assert len(parsed.products) > 40
    assert all(p.eligible for p in parsed.products)


def test_crawl_page_limit_is_complete_not_incomplete(tmp_path):
    fetch = Mock(side_effect=lambda url: Response(url, 200, fixture(1), rendered=True))
    run = Crawler(RawArchive(tmp_path), fetch, sleep=Mock()).crawl(CdonAdapter(max_pages=1))
    assert run.manifest.complete
    assert fetch.call_count == 1
