"""Wishlist searches: adapters, parsers, archive, import, matching, refresh. No network."""

import gzip
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from sqlmodel import Session, select

from shelfwatch import refresh
from shelfwatch.catalog.catalogue import SyncPayload, sync_catalogue
from shelfwatch.catalog.db import open_catalog
from shelfwatch.catalog.importer import import_run
from shelfwatch.catalog.matching import match_pending, score_target
from shelfwatch.catalog.models import MatchState, SearchHit, StoreProduct, WishSearch
from shelfwatch.catalog.tmdb import Candidate, MovieDetails
from shelfwatch.ingestion.archive import RawArchive
from shelfwatch.ingestion.ax_parser import AxParser
from shelfwatch.ingestion.browser import BrowserFetcher
from shelfwatch.ingestion.cdon_parser import CdonParser
from shelfwatch.ingestion.contract import (
    SEARCH_SCOPE,
    Availability,
    Condition,
    Format,
    ParsedProduct,
    ParsedRun,
    ParsedSnapshot,
)
from shelfwatch.ingestion.crawler import FetchError, Response
from shelfwatch.ingestion.normalize import clean_title
from shelfwatch.ingestion.parse import latest_run_id, parse_run
from shelfwatch.ingestion.search import (
    AxSearchAdapter,
    CdonSearchAdapter,
    Searcher,
    SearchTask,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"
NOW = datetime.now(UTC).replace(tzinfo=None)


def fixture(name):
    return gzip.decompress((FIXTURES / name).read_bytes())


AX_EMPTY = b"<html><h1>Haku</h1><p>Ei tuloksia</p></html>"


# --- adapters and parsers -------------------------------------------------------


def test_search_urls_encode_the_query():
    assert AxSearchAdapter().search_url("Mad Max: Fury Road") == (
        "https://www.levykauppax.fi/v2/search/?q=Mad+Max%3A+Fury+Road"
    )
    assert CdonSearchAdapter().search_url("Mad Max: Fury Road") == (
        "https://cdon.fi/s?q=Mad%20Max%3A%20Fury%20Road"
    )


def test_ax_result_count_and_wrong_pages():
    adapter = AxSearchAdapter()
    url = adapter.search_url("Innerspace")
    assert adapter.result_count(fixture("ax/search-innerspace.html.gz"), url) == 5
    assert adapter.result_count(AX_EMPTY, url) == 0
    with pytest.raises(ValueError, match="heading"):
        adapter.result_count(fixture("ax/offers-page-1.html.gz"), url)
    with pytest.raises(ValueError, match="left the results page"):
        adapter.result_count(AX_EMPTY, "https://www.levykauppax.fi/")


def test_cdon_result_count():
    adapter = CdonSearchAdapter()
    assert adapter.result_count(fixture("cdon/search-oldboy.json.gz"), "u") == 21
    with pytest.raises(ValueError, match="Malformed"):
        adapter.result_count(b"<html>challenge</html>", "u")
    with pytest.raises(ValueError, match="no articles"):
        adapter.result_count(b'{"error": "x"}', "u")


def test_ax_parse_search_keeps_movies_in_eligible_formats():
    products, errors = AxParser().parse_search(fixture("ax/search-oldboy.html.gz"))
    assert errors == []
    eligible = [p for p in products if p.eligible]
    assert len(products) == 10 and len(eligible) == 6
    assert {p.condition for p in eligible} == {Condition.NEW, Condition.USED}
    assert all(p.edition_url.startswith("https://www.levykauppax.fi/movie/") for p in eligible)
    assert AxParser().parse_search(AX_EMPTY) == ([], [])
    _, errors = AxParser().parse_search(b"<h1>Virhe</h1>")
    assert errors[0].product_id is None


def test_cdon_parse_search_reads_marketplace_formats_from_titles():
    products, errors = CdonParser().parse_search(fixture("cdon/search-innerspace.json.gz"))
    assert errors == []
    eligible = {p.raw_title: p.format for p in products if p.eligible}
    assert eligible["Innerspace Bluray 52 Brand New"] is Format.BLURAY
    assert eligible["24-tunnin takaa-ajo / Innerspace (4K UHD / Limited)"] is Format.UHD
    assert len(eligible) == 5  # DVDs, cassettes, CDs and LPs drop out
    assert all(p.edition_url.startswith("https://cdon.fi/tuote/") for p in products)
    no_match, _ = CdonParser().parse_search(fixture("cdon/search-no-match.json.gz"))
    assert not [p for p in no_match if p.eligible]
    _, errors = CdonParser().parse_search(b"not json")
    assert errors[0].product_id is None


# --- searcher and archive -------------------------------------------------------


def searcher(tmp_path, fetch, adapter=None, **kwargs):
    return Searcher(
        RawArchive(tmp_path), fetch, adapter or AxSearchAdapter(), sleep=Mock(), **kwargs
    )


def ax_fetch(pages):
    def fetch(url):
        body = pages[url]
        if isinstance(body, Exception):
            raise body
        return Response(url, 200, body)

    return Mock(side_effect=fetch)


def test_searcher_falls_back_to_original_title_only_when_nothing_is_found(tmp_path):
    adapter = AxSearchAdapter()
    fetch = ax_fetch(
        {
            adapter.search_url("Kaikki rahat"): AX_EMPTY,
            adapter.search_url("All the Money"): fixture("ax/search-oldboy.html.gz"),
            adapter.search_url("Innerspace"): fixture("ax/search-innerspace.html.gz"),
        }
    )
    worker = searcher(tmp_path, fetch)
    run = worker.search(
        [
            SearchTask(1, "Kaikki rahat", "All the Money"),
            SearchTask(2, "Innerspace", "Innerspace"),
        ]
    )
    assert run.manifest.scope == SEARCH_SCOPE and run.manifest.complete
    assert [(s.search_tmdb_id, s.search_query) for s in run.manifest.snapshots] == [
        (1, "Kaikki rahat"),
        (1, "All the Money"),
        (2, "Innerspace"),
    ]
    assert run.manifest.listing_count == 3 and run.manifest.product_count == 15
    assert worker.sleep.call_count == 3  # the delay comes before every request


def test_searcher_retries_and_records_failures_without_fallback(tmp_path):
    adapter = AxSearchAdapter()
    fetch = ax_fetch({adapter.search_url("Heat"): requests.Timeout("timed out")})
    run = searcher(tmp_path, fetch, attempts=2).search([SearchTask(949, "Heat", "Heat 1995")])
    assert not run.manifest.complete
    assert [(s.attempt, s.error) for s in run.manifest.snapshots] == [
        (1, "timed out"),
        (2, "timed out"),
    ]
    assert "'Heat'" in run.manifest.failures[0]


def test_parse_search_run_keeps_failures_and_duplicate_results(tmp_path):
    adapter = AxSearchAdapter()
    page = fixture("ax/search-innerspace.html.gz")
    fetch = ax_fetch(
        {
            adapter.search_url("Innerspace"): page,
            adapter.search_url("Inner Space"): page,
            adapter.search_url("Broken"): FetchError("Timeout"),
        }
    )
    searcher(tmp_path, fetch, attempts=1).search(
        [SearchTask(1, "Innerspace"), SearchTask(2, "Inner Space"), SearchTask(3, "Broken")]
    )
    parsed = parse_run(tmp_path, AxParser(), search=True)
    assert parsed.scope == SEARCH_SCOPE
    assert [(s.search_tmdb_id, len(s.products), s.search_failed) for s in parsed.snapshots] == [
        (1, 3, None),
        (2, 3, None),
        (3, 0, "Timeout"),
    ]
    with pytest.raises(FileNotFoundError, match="category"):
        latest_run_id(tmp_path, "ax", search=False)


def test_browser_search_returns_the_result_json_the_page_fetched(monkeypatch):
    fetcher = BrowserFetcher.__new__(BrowserFetcher)
    fetcher.challenge_timeout, fetcher.content_timeout_ms, fetcher.settle_seconds = 5, 1, 0
    result = Mock(status=200)
    result.body.return_value = b'{"articles": []}'
    waiter = Mock()
    waiter.__enter__ = Mock(return_value=Mock(value=result))
    waiter.__exit__ = Mock(return_value=False)
    fetcher._page = Mock()
    fetcher._page.expect_response.return_value = waiter
    monkeypatch.setattr(
        fetcher, "_fetch", Mock(return_value=Response("https://cdon.fi/s/?q=x", 200, b"<html>"))
    )
    response = fetcher.search("https://cdon.fi/s?q=x")
    assert response == Response("https://cdon.fi/s/?q=x", 200, b'{"articles": []}', True)
    predicate = fetcher._page.expect_response.call_args.args[0]
    post = Mock(url="https://search-bff.cdon.se/search/v2/result")
    post.request.method = "POST"
    assert predicate(post)
    post.request.method = "GET"
    assert not predicate(post)


# --- import ---------------------------------------------------------------------


def item(pid, title="Innerspace", *, store="ax", fmt=Format.BLURAY, price=1500):
    return ParsedProduct(
        store=store,
        product_id=pid,
        raw_title=title,
        cleaned_title=clean_title(title),
        edition_url=f"https://{store}.test/{pid}",
        format=fmt,
        format_raw=fmt.value,
        condition=Condition.NEW,
        availability=Availability.IN_STOCK,
        price_cents=price,
    )


def search_run(run_id, searches, *, at=None, store="ax"):
    """searches: {tmdb_id: [products] or an error string}."""
    at = at or NOW
    snapshots = []
    for n, (tmdb_id, found) in enumerate(searches.items(), 1):
        failed = found if isinstance(found, str) else None
        snapshots.append(
            ParsedSnapshot(
                snapshot_id=n,
                requested_url=f"search {tmdb_id}",
                fetched_at=at,
                products=[] if failed else found,
                search_tmdb_id=tmdb_id,
                search_query=f"query {tmdb_id}",
                search_failed=failed,
            )
        )
    return ParsedRun(
        store=store,
        run_id=run_id,
        parser_version="t",
        complete=True,
        parsed_at=at,
        scope=SEARCH_SCOPE,
        snapshots=snapshots,
    )


def category_run(run_id, products, *, at=None):
    at = at or NOW
    return ParsedRun(
        store="ax",
        run_id=run_id,
        parser_version="t",
        complete=True,
        parsed_at=at,
        snapshots=[
            ParsedSnapshot(snapshot_id=1, requested_url="c", fetched_at=at, products=products)
        ],
    )


def state(engine):
    with Session(engine) as session:
        products = {
            p.product_id: (p.active, p.category_member)
            for p in session.exec(select(StoreProduct)).all()
        }
        hits = {
            (session.get(StoreProduct, h.store_product_id).product_id, h.tmdb_id)
            for h in session.exec(select(SearchHit)).all()
        }
        searches = {
            s.tmdb_id: (s.hit_count, s.searched_at is not None, s.error)
            for s in session.exec(select(WishSearch)).all()
        }
    return products, hits, searches


@pytest.fixture
def engine(tmp_path):
    return open_catalog(tmp_path / "c.db")


def test_search_import_links_hits_and_records_searches(engine):
    result = import_run(
        engine, search_run(5, {2614: [item("1"), item("2", fmt=Format.UHD)], 670: [item("1")]})
    )
    assert (result.searches, result.search_hits, result.products_created) == (2, 3, 2)
    products, hits, searches = state(engine)
    assert products == {"1": (True, False), "2": (True, False)}
    assert hits == {("1", 2614), ("2", 2614), ("1", 670)}
    assert searches == {2614: (2, True, None), 670: (1, True, None)}


def test_later_search_drops_hits_and_deactivates_search_only_products(engine):
    import_run(engine, category_run(1, [item("1")]))  # "1" is also in the category crawl
    import_run(engine, search_run(2, {2614: [item("1"), item("2")]}))
    result = import_run(engine, search_run(3, {2614: []}))
    assert result.hits_dropped == 2 and result.expired == 1
    products, hits, searches = state(engine)
    assert products == {"1": (True, True), "2": (False, False)}
    assert hits == set()
    assert searches[2614] == (0, True, None)


def test_failed_search_keeps_previous_hits_and_searched_at(engine):
    import_run(engine, search_run(2, {2614: [item("2")]}, at=NOW - timedelta(hours=24)))
    result = import_run(engine, search_run(3, {2614: "Timeout"}))
    assert result.searches_failed == 1
    products, hits, searches = state(engine)
    assert products["2"] == (True, False) and hits == {("2", 2614)}
    assert searches[2614] == (1, True, "Timeout")


def test_category_expiry_spares_products_a_search_still_finds(engine):
    import_run(engine, category_run(1, [item("1"), item("2")]))
    import_run(engine, search_run(2, {2614: [item("1")]}))
    result = import_run(engine, category_run(3, []))
    assert result.expired == 1
    products, _, _ = state(engine)
    assert products == {"1": (True, False), "2": (False, False)}


def test_older_search_run_does_not_override_newer(engine):
    import_run(engine, search_run(3, {2614: [item("1")]}))
    import_run(engine, search_run(2, {2614: "Timeout"}))
    _, hits, searches = state(engine)
    assert hits == {("1", 2614)} and searches[2614] == (1, True, None)


# --- matching -------------------------------------------------------------------


class FakeTmdb:
    def __init__(self):
        self.searches = []

    def search_movies(self, query, year=None):
        self.searches.append(query)
        return [Candidate(99, "Something Else", release_year=2001, popularity=10)]

    def movie_details(self, tmdb_id):
        titles = {2614: "Innerspace", 670: "Oldboy", 99: "Something Else"}
        return MovieDetails(tmdb_id=tmdb_id, title=titles[tmdb_id], release_year=1987)


def wishes(engine, *wanted):
    payload = {"owned": [], "wanted": list(wanted)}
    client = Mock()
    client.fetch_sync.return_value = SyncPayload.model_validate(payload)
    sync_catalogue(engine, client)


INNERSPACE = {"tmdb_id": 2614, "title": "Innerspace", "year": 1987, "formats": ["Blu-ray"]}
OLDBOY = {
    "tmdb_id": 670,
    "title": "Oldboy",
    "original_title": "올드보이",
    "year": 2003,
    "formats": ["Blu-ray", "UHD"],
}
INNERSPACE_ID, OLDBOY_ID = INNERSPACE["tmdb_id"], OLDBOY["tmdb_id"]


def statuses(engine):
    with Session(engine) as session:
        rows = session.exec(select(MatchState, StoreProduct).join(StoreProduct)).all()
        return {p.raw_title: (s.status, s.tmdb_id, s.decided_by) for s, p in rows}


def test_search_hits_are_checked_against_the_wished_movie(engine):
    wishes(engine, INNERSPACE, OLDBOY)
    import_run(
        engine,
        search_run(
            2,
            {
                2614: [
                    item("1", "24 tunnin takaa-ajo / Innerspace (Blu-ray)"),
                    item("2", "Innerspace Bluray 52 Brand New"),
                    item("3", "Destination Inner Space (1966) DVD-elokuva"),
                ],
                670: [
                    item("4", "Oldboy (2013) Rare BluRay Josh Brolin"),
                    item("5", "Oldboy (Blu-ray)"),
                ],
            },
        ),
    )
    tmdb = FakeTmdb()
    result = match_pending(engine, tmdb)
    assert statuses(engine) == {
        "24 tunnin takaa-ajo / Innerspace (Blu-ray)": ("auto", 2614, "search"),
        "Innerspace Bluray 52 Brand New": ("ambiguous", None, None),
        "Destination Inner Space (1966) DVD-elokuva": ("ambiguous", None, None),
        "Oldboy (2013) Rare BluRay Josh Brolin": ("ambiguous", None, None),
        "Oldboy (Blu-ray)": ("auto", 670, "search"),
    }
    assert result.searched == 2
    # Only a clear wish score skips the open TMDB search; review-band hits are searched
    # too, and with no TMDB results they stay ambiguous with the wish as the candidate.
    assert tmdb.searches == [
        "Innerspace 52 Brand New",
        "Destination Inner Space elokuva",
        "Oldboy Rare Josh Brolin",
    ]


def test_review_candidates_hold_the_wish(engine):
    wishes(engine, INNERSPACE)
    import_run(engine, search_run(2, {2614: [item("2", "Innerspace Bluray 52 Brand New")]}))
    match_pending(engine, FakeTmdb())
    with Session(engine) as session:
        candidates = session.exec(select(MatchState)).one().candidates_json
    assert '"tmdb_id": 2614' in candidates


def test_new_search_hit_reopens_an_undecided_product(engine):
    import_run(engine, category_run(1, [item("1", "Innerspace Bluray 52 Brand New")]))
    match_pending(engine, FakeTmdb())
    assert statuses(engine)["Innerspace Bluray 52 Brand New"][0] == "ambiguous"
    wishes(engine, INNERSPACE)
    import_run(engine, search_run(2, {2614: [item("1", "Innerspace Bluray 52 Brand New")]}))
    with Session(engine) as session:
        assert session.exec(select(MatchState)).one().status == "pending"


@pytest.mark.parametrize(
    ("title", "accepted"),
    [
        ("24 tunnin takaa-ajo / Innerspace (Blu-ray)", True),
        ("OldBoy (2003) Region B Blu Ray Brand New", True),
        ("Oldboy (2013) Rare BluRay Josh Brolin", False),
        ("INNERSPACE BLU RAY STEELBOOK Brand New", True),
    ],
)
def test_score_target(title, accepted):
    targets = {
        "inner": Candidate(2614, "Innerspace", None, 1987),
        "old": Candidate(670, "Oldboy", None, 2003),
    }
    target = targets["inner" if "nner" in title.lower() else "old"]
    assert (score_target(clean_title(title), None, target) >= 0.8) is accepted


# --- refresh --------------------------------------------------------------------


class FakeFetcher:
    def __init__(self, bodies):
        self.bodies, self.urls, self.closed = bodies, [], False

    def __call__(self, url):
        self.urls.append(url)
        return Response(url, 200, self.bodies(url))

    def search(self, url):
        return self(url)

    def close(self):
        self.closed = True


@pytest.fixture
def no_sleep(monkeypatch):
    real = Searcher.__init__

    def init(self, *args, **kwargs):
        kwargs["sleep"] = Mock()
        real(self, *args, **kwargs)

    monkeypatch.setattr(Searcher, "__init__", init)


def test_search_command_path_searches_imports_and_respects_the_cap(tmp_path, monkeypatch, no_sleep):
    db = tmp_path / "c.db"
    engine = open_catalog(db)
    wishes(engine, INNERSPACE, OLDBOY)
    fetcher = FakeFetcher(
        lambda url: fixture(
            "ax/search-innerspace.html.gz" if "Innerspace" in url else "ax/search-oldboy.html.gz"
        )
    )
    monkeypatch.setattr(refresh, "make_fetcher", lambda store: fetcher)
    report = refresh.refresh_store(
        "ax", raw_dir=tmp_path / "raw", db_path=db, categories=False, tmdb_api_key="", search_cap=1
    )
    assert report.search_imported is not None and report.search_imported.searches == 1
    assert fetcher.closed and len(fetcher.urls) == 1
    assert "searched 1 wishes" in refresh.describe(report)
    # The cap counts requests in the last 24 h; the next run has no budget left.
    assert refresh.search_tasks(engine, "ax", 1) == []
    searched = report.searched.snapshots[0].search_tmdb_id
    # The wish just searched is fresh for 24 h; only the other one is due.
    assert [t.tmdb_id for t in refresh.search_tasks(engine, "ax", 5)] == [
        w for w in (INNERSPACE_ID, OLDBOY_ID) if w != searched
    ]
    second = refresh.search_tasks(engine, "ax", 5, min_interval_hours=0)
    assert len(second) == 2
    assert second[-1].tmdb_id == searched  # least recently searched goes first


def test_search_interval_skips_fresh_wishes_but_retries_failures(engine):
    wishes(engine, INNERSPACE, OLDBOY)
    import_run(engine, search_run(1, {INNERSPACE_ID: [item("1")], OLDBOY_ID: "timeout"}))
    with Session(engine) as session:
        search = session.exec(select(WishSearch).where(WishSearch.tmdb_id == INNERSPACE_ID)).one()
        searched_at = search.searched_at
    soon, later = searched_at + timedelta(hours=23), searched_at + timedelta(hours=25)
    assert [t.tmdb_id for t in refresh.search_tasks(engine, "ax", 100, now=soon)] == [OLDBOY_ID]
    assert {t.tmdb_id for t in refresh.search_tasks(engine, "ax", 100, now=later)} == {
        INNERSPACE_ID,
        OLDBOY_ID,
    }


def test_cdon_covers_use_the_resized_cdn_image_when_cdon_hosts_it():
    products, _ = CdonParser().parse_search(fixture("cdon/search-oldboy.json.gz"))
    urls = [p.image_url for p in products if p.image_url]
    cdn = [u for u in urls if u.startswith("https://images.cdon.com/images/f_auto/t_600x600/")]
    assert len(cdn) == 14
    assert not any(re.search(r"-[0-9a-f]{16}$", u) for u in cdn)  # slug id dropped
    # A seller image that CDON does not host stays as the seller's URL.
    assert any(u.startswith("https://mediatronixs.com/") for u in urls)
