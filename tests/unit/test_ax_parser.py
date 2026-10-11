"""Offline Äx parser tests against saved fixtures. No network."""

import gzip
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from cdon_watcher.ingestion.archive import RawArchive
from cdon_watcher.ingestion.ax_parser import (
    AxParser,
    clean_title,
    parse_availability,
    parse_format,
    parse_price_cents,
)
from cdon_watcher.ingestion.contract import Availability, Condition, Format, ParsedRun
from cdon_watcher.ingestion.parse import load_parsed, parse_run

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ax"


def fixture(page=1):
    return gzip.decompress((FIXTURES / f"offers-page-{page}.html.gz").read_bytes())


def by_id(products, product_id):
    return next(p for p in products if p.product_id == product_id)


def row_page(**changes):
    """One captured row with selected parts rewritten, wrapped in a listing."""
    soup = BeautifulSoup(fixture(), "html.parser")
    row = soup.select_one("li.hproduct")
    if "media" in changes:
        row.select_one("span.type").string = changes["media"]
    if "price_html" in changes:
        row.select_one("span.price").clear()
        row.select_one("span.price").append(BeautifulSoup(changes["price_html"], "html.parser"))
    if "shipping" in changes:
        node = row.select_one("p.shipping")
        node.string = changes["shipping"]
        node["class"] = ["shipping"]
    if "title" in changes:
        row.select_one("a.fn strong").string = changes["title"]
    if changes.get("drop_price"):
        row.select_one("span.price").decompose()
    if changes.get("drop_id"):
        del row["id"]
    return f'<ul class="list-products">{row}</ul>'.encode()


def test_first_page_new_products():
    products, errors = AxParser().parse(fixture())
    assert errors == []
    assert len(products) == 96
    mi = by_id(products, "1120921")
    assert mi.raw_title == "Mission Impossible - The Final Reckoning"
    assert mi.edition_url.endswith("/movie/mission_impossible_the_final_reckoning/#1120921")
    assert (mi.format, mi.disc_count, mi.condition) == (Format.BLURAY, 2, Condition.NEW)
    assert (mi.price_cents, mi.regular_price_cents, mi.currency) == (1199, 1399, "EUR")
    assert mi.availability is Availability.SUPPLIER_ORDER
    assert mi.availability_raw == "Toimitusaika n. 1-2 viikkoa."
    assert (mi.release_year, mi.publisher) == (2025, "Paramount")
    assert mi.image_url == "https://www.levykauppax.fi/cover/width_100/1/11/1120921.jpg"
    assert mi.stock_quantity is None
    assert mi.eligible
    combined = by_id(products, "1149002")
    assert combined.format is Format.UHD
    assert combined.eligible
    dvd = by_id(products, "1185326")
    assert dvd.format is Format.DVD
    assert not dvd.eligible


def test_last_page_used_products_in_stock():
    products, errors = AxParser().parse(fixture(14))
    assert errors == []
    assert len(products) == 39
    used = by_id(products, "1097394")
    assert (used.format, used.condition, used.condition_raw) == (
        Format.DVD,
        Condition.USED,
        "Käytetty",
    )
    assert (used.price_cents, used.regular_price_cents) == (180, 600)
    assert used.availability is Availability.IN_STOCK
    assert used.stock_quantity == 2
    assert all(p.condition is Condition.USED for p in products)
    assert all(p.availability is Availability.IN_STOCK for p in products)
    assert sum(p.eligible for p in products) == 7


@pytest.mark.parametrize(
    "text,expected",
    [
        ("13,99 €", 1399),
        ("1\xa0234,56 €", 123456),
        ("1 234,56 €", 123456),
        ("6,00 €", 600),
        ("12.50", 1250),
        ("0,00 €", None),
        ("", None),
        ("ilmainen", None),
        ("1,999 €", None),
    ],
)
def test_parse_price_cents(text, expected):
    assert parse_price_cents(text) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Blu-Ray", (Format.BLURAY, Condition.NEW, None)),
        ("2 Blu-ray", (Format.BLURAY, Condition.NEW, 2)),
        ("4K Ultra HD", (Format.UHD, Condition.NEW, None)),
        ("4K ULTRA HD + BLU", (Format.UHD, Condition.NEW, None)),
        ("3ULTRAHD + BLU", (Format.UHD, Condition.NEW, 3)),
        ("3x4K Ultra HD", (Format.UHD, Condition.NEW, 3)),
        ("Käytetty 3D Blu-ray", (Format.BLURAY, Condition.USED, None)),
        ("Käytetty 8DVD", (Format.DVD, Condition.USED, 8)),
        ("4DVD", (Format.DVD, Condition.NEW, 4)),
        ("VHS", (Format.UNKNOWN, Condition.NEW, None)),
    ],
)
def test_parse_format(raw, expected):
    assert parse_format(raw) == expected


@pytest.mark.parametrize(
    "html,expected",
    [
        (
            '<p class="shipping in-stock">Tuotetta hyllyssä, toimitus heti</p>',
            Availability.IN_STOCK,
        ),
        ('<p class="shipping">Toimitusaika n. 1-2 kuukautta.</p>', Availability.SUPPLIER_ORDER),
        ('<p class="shipping">Toimitusaika ei ole tiedossa</p>', Availability.UNKNOWN),
        ('<p class="shipping">Ennakkotilaus, julkaistaan 1.12.2026</p>', Availability.PREORDER),
        ('<p class="shipping">Loppuunmyyty</p>', Availability.OUT_OF_STOCK),
        ('<p class="shipping"></p>', Availability.UNKNOWN),
        ("", Availability.UNKNOWN),
    ],
)
def test_parse_availability(html, expected):
    node = BeautifulSoup(html, "html.parser").select_one("p")
    assert parse_availability(node)[0] is expected


@pytest.mark.parametrize(
    "raw,cleaned",
    [
        ("Mission Impossible - The Final Reckoning", "Mission Impossible - The Final Reckoning"),
        ("Alien (4K Ultra HD + Blu-ray)", "Alien"),
        ("Heat (Limited Steelbook Edition)", "Heat"),
        ("Se7en [Remastered]", "Se7en"),
        ("Dune: Part Two (2024)", "Dune: Part Two (2024)"),
    ],
)
def test_clean_title(raw, cleaned):
    assert clean_title(raw) == cleaned


def test_collections_flagged_by_title_not_disc_count():
    products, _ = AxParser().parse(fixture())
    assert not by_id(products, "1120921").is_collection  # 2 Blu-ray single movie
    titled, _ = AxParser().parse(row_page(title="Alien 6-Film Collection"))
    assert titled[0].is_collection
    assert titled[0].eligible


def test_missing_regular_price_is_allowed():
    products, errors = AxParser().parse(row_page(price_html="9,99 €"))
    assert errors == []
    assert (products[0].price_cents, products[0].regular_price_cents) == (999, None)


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"drop_price": True}, "no price"),
        ({"price_html": "<del>13,99 €</del> ilmainen"}, "invalid current price"),
        ({"price_html": "<del>5,00 €</del> 9,99 €"}, "Regular price is below"),
        ({"drop_id": True}, "no numeric product id"),
    ],
)
def test_bad_rows_become_errors_not_crashes(changes, reason):
    products, errors = AxParser().parse(row_page(**changes))
    assert products == []
    assert len(errors) == 1
    assert reason in errors[0].reason


def test_bad_row_does_not_discard_good_rows():
    soup = BeautifulSoup(fixture(), "html.parser")
    soup.select_one("#p-1120921 span.price").string = "ilmainen"
    products, errors = AxParser().parse(str(soup).encode())
    assert len(products) == 95
    assert [e.product_id for e in errors] == ["1120921"]


def test_unrecognized_page_is_one_error():
    products, errors = AxParser().parse(b"<html>Temporary error</html>")
    assert products == []
    assert errors[0].product_id is None


def archived_run(tmp_path, bodies, *, complete=True, broken_snapshot=False):
    archive = RawArchive(tmp_path)
    with archive.start("ax", "movie-offers") as run:
        for url, body in bodies.items():
            run.record(url, final_url=url, status=200, body=body, attempt=1)
        if broken_snapshot:
            snapshot = run.record(
                "https://www.levykauppax.fi/leffat/offer/?p2=9",
                final_url=None,
                status=503,
                body=b"unavailable",
                attempt=1,
                error="HTTP 503",
            )
            assert snapshot.body_ref is not None
        run.manifest.complete = complete
    return run


def test_parse_run_writes_parsed_json_and_skips_failed_snapshots(tmp_path):
    bodies = {
        "https://www.levykauppax.fi/leffat/offer/": fixture(),
        "https://www.levykauppax.fi/leffat/offer/?p2=14": fixture(14),
    }
    archived_run(tmp_path, bodies, complete=False, broken_snapshot=True)
    parsed = parse_run(tmp_path, AxParser())
    assert parsed.run_id == 1
    assert parsed.parser_version == "ax-1"
    assert not parsed.complete
    assert [s.snapshot_id for s in parsed.snapshots] == [1, 2]
    assert len(parsed.products) == 66 + 7  # eligible rows only
    assert all(p.eligible for p in parsed.products)
    saved = load_parsed(tmp_path, "ax", 1)
    assert saved == parsed
    everything = parse_run(tmp_path, AxParser(), 1, eligible_only=False)
    assert len(everything.products) == 96 + 39
    assert (
        ParsedRun.model_validate_json((tmp_path / "ax" / "1" / "parsed.json").read_text())
        == everything
    )


def test_parse_run_dedupes_products_across_snapshots_and_uses_latest_run(tmp_path):
    archived_run(tmp_path, {"https://www.levykauppax.fi/leffat/offer/": row_page()})
    archived_run(
        tmp_path,
        {
            "https://www.levykauppax.fi/leffat/offer/": row_page(),
            "https://www.levykauppax.fi/leffat/offer/?p2=2": row_page(),
        },
    )
    parsed = parse_run(tmp_path, AxParser())
    assert parsed.run_id == 2
    assert [len(s.products) for s in parsed.snapshots] == [1, 0]


def test_parse_run_without_runs_raises(tmp_path):
    (tmp_path / "ax").mkdir()
    with pytest.raises(FileNotFoundError):
        parse_run(tmp_path, AxParser())


def test_parse_raw_cli(tmp_path, monkeypatch, capsys):
    from cdon_watcher.cli import main

    archived_run(tmp_path, {"https://www.levykauppax.fi/leffat/offer/": fixture()})
    monkeypatch.setattr(
        "sys.argv", ["cdon-watcher", "parse-raw", "--store", "ax", "--raw-dir", str(tmp_path)]
    )
    main()
    out = capsys.readouterr().out
    assert "run 1: 66 products, 0 row errors, complete crawl" in out
    assert (tmp_path / "ax" / "1" / "parsed.json").exists()
