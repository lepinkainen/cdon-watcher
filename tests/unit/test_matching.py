"""TMDB matching stage tests with a fake client. No network."""

from datetime import UTC, datetime

import pytest
from sqlmodel import Session, select

from cdon_watcher.catalog.db import open_catalog
from cdon_watcher.catalog.importer import import_run
from cdon_watcher.catalog.matching import (
    match_pending,
    score_candidate,
    search_query,
    set_manual_match,
)
from cdon_watcher.catalog.models import MatchState, MovieMetadata, StoreProduct
from cdon_watcher.catalog.tmdb import Candidate, MovieDetails, TmdbError
from cdon_watcher.ingestion.contract import (
    Availability,
    Condition,
    Format,
    ParsedProduct,
    ParsedRun,
    ParsedSnapshot,
)

T0 = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)


class FakeTmdb:
    def __init__(self, results=None, *, fail=False):
        self.results = results or {}
        self.fail = fail
        self.searches: list[tuple[str, int | None]] = []
        self.details: list[int] = []

    def search_movies(self, query, year=None):
        if self.fail:
            raise TmdbError("boom")
        self.searches.append((query, year))
        return list(self.results.get((query, year), self.results.get((query, None), [])))

    def movie_details(self, tmdb_id):
        self.details.append(tmdb_id)
        return MovieDetails(
            tmdb_id=tmdb_id,
            title=f"Movie {tmdb_id}",
            release_year=1999,
            imdb_id=f"tt{tmdb_id:07d}",
            director="Someone",
            cast=["A", "B"],
        )


def product(product_id, title, *, store="ax", year=None, collection=False):
    return ParsedProduct(
        store=store,
        product_id=product_id,
        raw_title=title,
        cleaned_title=title,
        edition_url=f"https://example.test/{store}/{product_id}",
        format=Format.BLURAY,
        format_raw="Blu-Ray",
        condition=Condition.NEW,
        availability=Availability.IN_STOCK,
        price_cents=999,
        release_year=year,
        is_collection=collection,
    )


def imported(engine, products, *, store="ax", run_id=1):
    run = ParsedRun(
        store=store,
        run_id=run_id,
        parser_version="t",
        complete=True,
        parsed_at=T0,
        snapshots=[
            ParsedSnapshot(snapshot_id=1, requested_url="u", fetched_at=T0, products=list(products))
        ],
    )
    import_run(engine, run)


def states(engine):
    with Session(engine) as session:
        rows = session.exec(
            select(MatchState, StoreProduct)
            .join(StoreProduct, StoreProduct.id == MatchState.store_product_id)
            .order_by(StoreProduct.product_id)
        ).all()
        return {p.product_id: (s.status, s.tmdb_id, p.tmdb_id) for s, p in rows}


@pytest.fixture
def engine(tmp_path):
    return open_catalog(tmp_path / "catalog.db")


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Heat", ("Heat", None)),
        ("Blade Runner (1982)", ("Blade Runner", 1982)),
        ("Alien Limited Steelbook Edition", ("Alien", None)),
        (
            "Mission Impossible - The Final Reckoning",
            ("Mission Impossible The Final Reckoning", None),
        ),
        ("Se7en (2 disc) Remastered", ("Se7en", None)),
    ],
)
def test_search_query(title, expected):
    assert search_query(title) == expected


def test_score_prefers_title_then_year_and_barely_popularity():
    exact = Candidate(1, "Heat", release_year=1995, popularity=10)
    popular_other = Candidate(2, "Heat Wave", release_year=1995, popularity=500)
    far_year = Candidate(3, "Heat", release_year=1972, popularity=10)
    assert score_candidate("Heat", 1995, exact) > score_candidate("Heat", 1995, popular_other)
    assert score_candidate("Heat", 1995, exact) > score_candidate("Heat", 1995, far_year)
    assert score_candidate("Heat", None, exact) < score_candidate("Heat", 1995, exact)


def test_clear_match_is_accepted_and_metadata_cached(engine):
    imported(engine, [product("1", "Heat", year=1995)])
    client = FakeTmdb(
        {
            ("Heat", 1995): [
                Candidate(949, "Heat", release_year=1995, popularity=40),
                Candidate(2, "Heat Wave", release_year=1995, popularity=5),
            ]
        }
    )
    result = match_pending(engine, client)
    assert (result.considered, result.auto) == (1, 1)
    assert states(engine)["1"] == ("auto", 949, 949)
    assert client.details == [949]
    with Session(engine) as session:
        meta = session.get(MovieMetadata, 949)
        assert meta is not None and meta.imdb_id == "tt0000949"
    # Decided products are not queried again.
    again = match_pending(engine, client)
    assert again.considered == 0
    assert len(client.searches) == 1


def test_close_candidates_are_ambiguous_not_guessed(engine):
    imported(engine, [product("1", "The Thing")])
    client = FakeTmdb(
        {
            ("The Thing", None): [
                Candidate(1091, "The Thing", release_year=1982, popularity=30),
                Candidate(60935, "The Thing", release_year=2011, popularity=25),
            ]
        }
    )
    result = match_pending(engine, client)
    assert result.ambiguous == 1
    assert states(engine)["1"] == ("ambiguous", None, None)
    with Session(engine) as session:
        state = session.exec(select(MatchState)).one()
        assert "1091" in (state.candidates_json or "")


def test_year_breaks_remake_ties(engine):
    imported(engine, [product("1", "The Thing (1982)")])
    client = FakeTmdb(
        {
            ("The Thing", 1982): [
                Candidate(1091, "The Thing", release_year=1982, popularity=30),
                Candidate(60935, "The Thing", release_year=2011, popularity=25),
            ]
        }
    )
    match_pending(engine, client)
    assert states(engine)["1"] == ("auto", 1091, 1091)


def test_no_results_is_unmatched_and_retries_without_year(engine):
    imported(engine, [product("1", "Obscure Finnish Title", year=2001)])
    client = FakeTmdb()
    result = match_pending(engine, client)
    assert result.unmatched == 1
    assert client.searches == [("Obscure Finnish Title", 2001), ("Obscure Finnish Title", None)]
    assert states(engine)["1"] == ("unmatched", None, None)


def test_collections_are_not_applicable_and_never_searched(engine):
    imported(engine, [product("1", "Alien 6-Film Collection", collection=True)])
    client = FakeTmdb()
    result = match_pending(engine, client)
    assert result.not_applicable == 1
    assert client.searches == []
    assert states(engine)["1"][0] == "not_applicable"


def test_tmdb_outage_marks_error_and_is_retried(engine):
    imported(engine, [product("1", "Heat", year=1995)])
    down = FakeTmdb(fail=True)
    result = match_pending(engine, down)
    assert result.errors == 1
    assert states(engine)["1"][0] == "error"
    up = FakeTmdb({("Heat", 1995): [Candidate(949, "Heat", release_year=1995, popularity=40)]})
    result = match_pending(engine, up)
    assert result.auto == 1
    with Session(engine) as session:
        state = session.exec(select(MatchState)).one()
        assert state.attempts == 2 and state.last_error is None


def test_decided_match_is_reused_across_stores_without_a_search(engine):
    imported(engine, [product("1", "Heat (1995)", store="ax")], store="ax")
    imported(engine, [product("x1", "Heat Blu-ray (1995)", store="cdon")], store="cdon")
    client = FakeTmdb({("Heat", 1995): [Candidate(949, "Heat", release_year=1995, popularity=40)]})
    result = match_pending(engine, client)
    assert (result.auto, result.reused) == (1, 1)
    assert len(client.searches) == 1
    assert states(engine)["x1"] == ("auto", 949, 949)


def test_manual_override_and_rejection(engine):
    imported(engine, [product("1", "The Thing"), product("2", "Nothing")])
    client = FakeTmdb()
    match_pending(engine, client)
    with Session(engine) as session:
        ids = {p.product_id: p.id for p in session.exec(select(StoreProduct)).all()}
    state = set_manual_match(engine, client, ids["1"], 1091)
    assert (state.status, state.decided_by) == ("manual", "user")
    assert states(engine)["1"] == ("manual", 1091, 1091)
    assert client.details == [1091]
    rejected = set_manual_match(engine, None, ids["2"], None)
    assert rejected.status == "rejected"
    assert states(engine)["2"] == ("rejected", None, None)
    # Neither is touched by later automatic runs.
    assert match_pending(engine, client).considered == 0


def test_store_filter_and_limit(engine):
    imported(engine, [product("1", "A"), product("2", "B")], store="ax")
    imported(engine, [product("c1", "C", store="cdon")], store="cdon")
    client = FakeTmdb()
    assert match_pending(engine, client, store="cdon").considered == 1
    assert match_pending(engine, client, limit=1).considered == 1
    assert match_pending(engine, client).considered == 1


def test_match_cli_requires_api_key(tmp_path, monkeypatch):
    from cdon_watcher.cli import main
    from cdon_watcher.config import CONFIG

    monkeypatch.setitem(CONFIG, "tmdb_api_key", "")
    monkeypatch.setattr("sys.argv", ["cdon-watcher", "match", "--db", str(tmp_path / "c.db")])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
