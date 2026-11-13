"""TMDB matching stage tests with a fake client. No network."""

import logging
from datetime import UTC, datetime

import pytest
from sqlmodel import Session, select

from shelfwatch.catalog.db import open_catalog
from shelfwatch.catalog.importer import import_run
from shelfwatch.catalog.jev import JevError
from shelfwatch.catalog.matching import (
    clear_box_set_answers,
    gate_box_sets,
    match_pending,
    reset_ambiguous,
    score_candidate,
    search_query,
    set_manual_match,
)
from shelfwatch.catalog.models import MatchState, MovieMetadata, StoreProduct, UserPreference
from shelfwatch.catalog.preferences import apply
from shelfwatch.catalog.tmdb import Candidate, MovieDetails, MovieTitles, TmdbError
from shelfwatch.ingestion.contract import (
    Availability,
    Condition,
    Format,
    ParsedProduct,
    ParsedRun,
    ParsedSnapshot,
)

T0 = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)


class FakeTmdb:
    def __init__(self, results=None, *, fail=False, titles=None):
        self.results = results or {}
        self.fail = fail
        self.titles = titles or {}
        self.searches: list[tuple[str, int | None]] = []
        self.details: list[int] = []
        self.title_lookups: list[int] = []

    def movie_titles(self, tmdb_id):
        self.title_lookups.append(tmdb_id)
        return self.titles.get(tmdb_id, MovieTitles(tmdb_id))

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
    from shelfwatch.cli import main
    from shelfwatch.config import CONFIG

    monkeypatch.setitem(CONFIG, "tmdb_api_key", "")
    monkeypatch.setattr("sys.argv", ["shelfwatch", "match", "--db", str(tmp_path / "c.db")])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


def prefs(engine):
    with Session(engine) as session:
        rows = session.exec(select(UserPreference)).all()
        return {(p.kind, p.tmdb_id, p.store_product_id, p.origin_store_product_id) for p in rows}


def test_corrected_or_rejected_match_moves_its_promoted_preferences(engine):
    imported(engine, [product("1", "Heat"), product("2", "Heat"), product("3", "Heat")])
    with Session(engine) as session:
        ids = {p.product_id: p.id for p in session.exec(select(StoreProduct)).all()}
    client = FakeTmdb()
    for pid in ids.values():
        set_manual_match(engine, client, pid, 949)
    apply(engine, ids["1"], "ignore")
    apply(engine, ids["3"], "ignore")  # already ignored: keeps origin 1
    assert prefs(engine) == {("ignore", 949, None, ids["1"])}
    # Correction moves only this product's promoted preference to the new movie.
    set_manual_match(engine, client, ids["1"], 1091)
    assert prefs(engine) == {("ignore", 1091, None, ids["1"])}
    apply(engine, ids["2"], "ignore")
    # Rejection restores the product-level preference; 949's ignore from product 2 stays.
    set_manual_match(engine, None, ids["1"], None)
    assert prefs(engine) == {("ignore", None, ids["1"], ids["1"]), ("ignore", 949, None, ids["2"])}


def test_progress_is_logged_every_50_products(engine, caplog):
    imported(engine, [product(str(n), f"Movie {n}") for n in range(120)])
    with caplog.at_level("DEBUG", logger="shelfwatch.catalog.matching"):
        match_pending(engine, FakeTmdb())
    assert caplog.messages[0] == "matching 120 products against TMDB"
    assert [m.split(":")[0] for m in caplog.messages[1:]] == [
        "matched 50/120",
        "matched 100/120",
        "matched 120/120",
    ]
    assert "120 unmatched" in caplog.messages[-1]


def test_nothing_to_match_logs_only_the_count(engine, caplog):
    with caplog.at_level("DEBUG", logger="shelfwatch.catalog.matching"):
        match_pending(engine, FakeTmdb())
    assert caplog.messages == ["matching 0 products against TMDB"]


class FakeJev:
    """Box-set answers by raw title; candidate picks from a callable over the options."""

    def __init__(self, box=None, pick=None, *, fail=False):
        self.box = box or {}
        self.pick = pick
        self.fail = fail
        self.calls: list[set[str]] = []

    def ask(self, state, questions):
        self.calls.append(set(questions))
        if self.fail:
            raise JevError("jev down")
        if "box_set" in questions:
            return {"box_set": {"noul": self.box.get(state["product"]["store_title"], 0.05)}}
        return self.pick(list(questions["movie"]["criteria"]))


def answer(options, choice, *, p=0.95, fits=0.9, title=0.9):
    index = options.index(choice)
    rest = (1 - p) / max(len(options) - 1, 1)
    answers = {
        "movie": {
            "choice": choice,
            "probabilities": {o: p if o == choice else rest for o in options},
        },
        "any_fits": {"noul": fits},
    }
    for i in range(len(options)):
        answers[f"release_title_{i}"] = {"noul": title if i == index else 0.1}
    return answers


THING = {
    ("The Thing", None): [
        Candidate(1091, "The Thing", release_year=1982, popularity=30),
        Candidate(60935, "The Thing", release_year=2011, popularity=25),
    ]
}


def test_box_set_gate_tags_and_skips_all_lookups(engine):
    imported(engine, [product("1", "Young Guns / Young Guns II"), product("2", "Heat", year=1995)])
    jev = FakeJev(box={"Young Guns / Young Guns II": 0.93})
    gate = gate_box_sets(engine, jev)
    assert (gate.checked, gate.box_sets, gate.errors) == (2, 1, 0)
    client = FakeTmdb({("Heat", 1995): [Candidate(949, "Heat", release_year=1995, popularity=40)]})
    result = match_pending(engine, client, jev=jev)
    assert (result.considered, result.auto) == (1, 1)  # the gate already decided the box
    assert client.searches == [("Heat", 1995)]  # never for the box set
    assert states(engine)["1"] == ("not_applicable", None, None)
    with Session(engine) as session:
        box = session.exec(select(StoreProduct).where(StoreProduct.product_id == "1")).one()
        assert box.is_collection and box.box_set_probability == 0.93
    # Each title is checked once.
    assert gate_box_sets(engine, jev).checked == 0


def test_title_pattern_collections_skip_the_gate(engine):
    imported(engine, [product("1", "Alien Quadrilogy", collection=True)])
    jev = FakeJev()
    assert gate_box_sets(engine, jev).checked == 0
    assert jev.calls == []


def test_reimport_keeps_the_box_set_until_the_title_changes(engine):
    imported(engine, [product("1", "Young Guns / Young Guns II")])
    gate_box_sets(engine, FakeJev(box={"Young Guns / Young Guns II": 0.93}))
    imported(engine, [product("1", "Young Guns / Young Guns II")], run_id=2)
    with Session(engine) as session:
        assert session.exec(select(StoreProduct)).one().is_collection
    imported(engine, [product("1", "Young Guns II")], run_id=3)
    with Session(engine) as session:
        retitled = session.exec(select(StoreProduct)).one()
        assert not retitled.is_collection and retitled.box_set_probability is None
    gate_box_sets(engine, FakeJev())
    assert states(engine)["1"][0] == "pending"  # matched again under the new title


def test_failed_gate_leaves_the_product_unmatched_until_an_answer(engine):
    imported(engine, [product("1", "Heat", year=1995)])
    gate = gate_box_sets(engine, FakeJev(fail=True))
    assert (gate.checked, gate.errors) == (0, 1)
    client = FakeTmdb({("Heat", 1995): [Candidate(949, "Heat", release_year=1995, popularity=40)]})
    assert match_pending(engine, client, jev=FakeJev()).considered == 0
    assert client.searches == []
    gate_box_sets(engine, FakeJev())
    assert match_pending(engine, client, jev=FakeJev()).auto == 1


def test_unsure_box_set_is_held_for_review_instead_of_accepted(engine):
    imported(engine, [product("1", "Heat", year=1995)])
    gate = gate_box_sets(engine, FakeJev(box={"Heat": 0.5}))
    assert gate.maybe == 1
    client = FakeTmdb({("Heat", 1995): [Candidate(949, "Heat", release_year=1995, popularity=40)]})
    result = match_pending(engine, client, jev=FakeJev())
    assert (result.auto, result.held) == (0, 1)
    assert states(engine)["1"] == ("ambiguous", None, None)
    assert client.details == []


def test_gate_sends_an_earlier_auto_match_of_an_unsure_product_to_review(engine):
    imported(engine, [product("1", "Heat", year=1995), product("2", "Heat Steelbook", year=1995)])
    client = FakeTmdb({("Heat", 1995): [Candidate(949, "Heat", release_year=1995, popularity=40)]})
    match_pending(engine, client)
    assert states(engine)["2"] == ("auto", 949, 949)
    gate_box_sets(engine, FakeJev(box={"Heat Steelbook": 0.5}))
    assert states(engine)["2"] == ("ambiguous", None, None)
    assert states(engine)["1"] == ("auto", 949, 949)


def test_gate_leaves_user_decisions_alone(engine):
    imported(engine, [product("1", "The Thing")])
    with Session(engine) as session:
        pid = session.exec(select(StoreProduct)).one().id
    set_manual_match(engine, FakeTmdb(), pid, 1091)
    jev = FakeJev(box={"The Thing": 0.99})
    assert gate_box_sets(engine, jev).checked == 0
    assert states(engine)["1"] == ("manual", 1091, 1091)


def test_jev_decides_what_the_scores_cannot(engine):
    imported(engine, [product("1", "The Thing")])
    gate_box_sets(engine, FakeJev())
    client = FakeTmdb(
        THING, titles={1091: MovieTitles(1091, popularity=30, vote_count=7000, finnish_title="Se")}
    )
    jev = FakeJev(pick=lambda options: answer(options, options[0]))
    result = match_pending(engine, client, jev=jev)
    assert (result.jev, result.ambiguous) == (1, 0)
    assert states(engine)["1"] == ("auto", 1091, 1091)
    assert client.title_lookups == [1091, 60935]
    assert client.details == [1091]
    with Session(engine) as session:
        state = session.exec(select(MatchState)).one()
        assert state.decided_by == "jev" and state.note.startswith("Jev accept")


@pytest.mark.parametrize(
    "fits,title,status",
    [(0.5, 0.5, "ambiguous"), (0.1, 0.1, "unmatched")],
)
def test_jev_review_and_none_are_not_matched(engine, fits, title, status):
    imported(engine, [product("1", "The Thing")])
    gate_box_sets(engine, FakeJev())
    jev = FakeJev(pick=lambda options: answer(options, options[0], fits=fits, title=title))
    match_pending(engine, FakeTmdb(THING), jev=jev)
    assert states(engine)["1"] == (status, None, None)


def test_jev_failure_while_picking_is_an_error_and_retried(engine):
    imported(engine, [product("1", "The Thing")])
    gate_box_sets(engine, FakeJev())
    result = match_pending(engine, FakeTmdb(THING), jev=FakeJev(fail=True))
    assert result.errors == 1
    assert states(engine)["1"][0] == "error"
    jev = FakeJev(pick=lambda options: answer(options, options[1]))
    assert match_pending(engine, FakeTmdb(THING), jev=jev).jev == 1
    assert states(engine)["1"] == ("auto", 60935, 60935)


def test_reset_ambiguous_sends_them_back_for_a_decision(engine):
    imported(engine, [product("1", "The Thing")])
    match_pending(engine, FakeTmdb(THING))
    assert states(engine)["1"][0] == "ambiguous"
    assert reset_ambiguous(engine) == 1
    gate_box_sets(engine, FakeJev())
    jev = FakeJev(pick=lambda options: answer(options, options[0]))
    assert match_pending(engine, FakeTmdb(THING), jev=jev).jev == 1


def test_box_set_gate_reports_progress_at_info(engine, caplog):
    imported(engine, [product(str(n), f"Movie {n}") for n in range(120)])
    jev = FakeJev(box={"Movie 7": 0.95})
    jev.input_tokens = 0
    with caplog.at_level("INFO", logger="shelfwatch.catalog.matching"):
        gate_box_sets(engine, jev)
    assert caplog.messages[0] == "checking 120 products for box sets"
    assert [m.split(":")[0] for m in caplog.messages[1:]] == [
        "box-set check 50/120",
        "box-set check 100/120",
        "box-set check 120/120",
    ]
    assert caplog.messages[-1].endswith("1 box sets, 0 unsure, 0 errors, 0 Jev tokens")


def test_match_progress_level_is_chosen_by_the_caller(engine, caplog):
    imported(engine, [product("1", "Movie 1")])
    with caplog.at_level("INFO", logger="shelfwatch.catalog.matching"):
        match_pending(engine, FakeTmdb())
        assert caplog.messages == []
        match_pending(engine, FakeTmdb(), progress_level=logging.INFO, limit=0)
    assert caplog.messages == ["matching 0 products against TMDB"]


def test_ctrl_c_exits_quietly_with_130(tmp_path, monkeypatch, capsys):
    from shelfwatch import cli

    def interrupted(args, parser):
        raise KeyboardInterrupt

    monkeypatch.setitem(cli.COMMANDS, "match", interrupted)
    monkeypatch.setattr("sys.argv", ["shelfwatch", "match", "--db", str(tmp_path / "c.db")])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 130
    assert "interrupted" in capsys.readouterr().err


def test_recheck_reopens_products_the_new_answer_no_longer_calls_box_sets(engine):
    imported(
        engine,
        [
            product("1", "Key Largo / Myrskyvaroitus", year=1948),
            product("2", "Heat", year=1995),
            product("3", "Young Guns / Young Guns II"),
            product("4", "Alien Quadrilogy", collection=True),
        ],
    )
    gate_box_sets(
        engine,
        FakeJev(
            box={
                "Key Largo / Myrskyvaroitus": 0.75,
                "Heat": 0.5,
                "Young Guns / Young Guns II": 0.95,
            }
        ),
    )
    client = FakeTmdb({("Heat", 1995): [Candidate(949, "Heat", release_year=1995, popularity=40)]})
    match_pending(engine, client, jev=FakeJev())
    assert states(engine)["1"][0] == "not_applicable"
    assert states(engine)["2"] == ("ambiguous", None, None)  # held

    assert clear_box_set_answers(engine) == 3
    with Session(engine) as session:
        flags = {p.product_id: p.is_collection for p in session.exec(select(StoreProduct))}
    assert flags == {"1": False, "2": False, "3": False, "4": True}

    gate_box_sets(engine, FakeJev(box={"Young Guns / Young Guns II": 0.95}))
    assert states(engine)["1"][0] == "pending"
    assert states(engine)["2"][0] == "pending"
    assert states(engine)["3"][0] == "not_applicable"
    match_pending(engine, client, jev=FakeJev())
    assert states(engine)["2"] == ("auto", 949, 949)


def test_recheck_keeps_a_still_unsure_product_held(engine):
    imported(engine, [product("1", "Heat", year=1995)])
    gate_box_sets(engine, FakeJev(box={"Heat": 0.5}))
    client = FakeTmdb({("Heat", 1995): [Candidate(949, "Heat", release_year=1995, popularity=40)]})
    match_pending(engine, client, jev=FakeJev())
    clear_box_set_answers(engine)
    gate_box_sets(engine, FakeJev(box={"Heat": 0.45}))
    assert states(engine)["1"] == ("ambiguous", None, None)
