"""TMDB identity matching for single-movie store products.

Runs after import as its own retryable stage. A TMDB outage marks products
as `error` and leaves them for the next run; it never raises past match_pending.
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher

from sqlalchemy import Engine
from sqlmodel import Session, select

from ..box_set_detector import is_box_set as title_is_box_set
from .catalogue import Catalogue, load_catalogue
from .jev import NO as JEV_NO
from .jev import (
    JevCandidate,
    JevClient,
    JevError,
    ProductFacts,
    box_set_probability,
    is_box_set,
    maybe_box_set,
    pick_candidate,
    tokens_used,
)
from .models import MatchState, MovieMetadata, SearchHit, Store, StoreProduct
from .preferences import demote_movie_preferences, transfer_product_preferences
from .tmdb import Candidate, MovieDetails, TmdbClient, TmdbError

logger = logging.getLogger(__name__)

ACCEPT_SCORE = 0.80
"""Minimum score of the best candidate for an automatic match."""
ACCEPT_MARGIN = 0.08
"""Minimum lead over the runner-up for an automatic match."""
SOLE_CANDIDATE_SCORE = 0.85
"""A lone candidate needs this much to be accepted without a runner-up."""
TARGET_REVIEW_SCORE = 0.6
"""A search hit scoring at least this against the wished movie goes to the review queue."""
RETRY_STATUSES = ("pending", "error")
DECIDED_STATUSES = ("auto", "manual")
USER_STATUSES = ("manual", "rejected")
"""A person decided these; the box-set gate leaves them alone."""
JEV_CANDIDATES = 5
"""How many of the best-scored candidates Jev chooses among."""

_TITLE_YEAR = re.compile(r"\((19\d{2}|20\d{2})\)")
_NOISE = re.compile(
    r"\b(blu-?ray|4k|uhd|ultra\s*hd|dvd|steelbook|limited|collector'?s|special|edition|"
    r"extended|director'?s\s+cut|remastered?|import|rajoitettu|erikoisjulkaisu)\b",
    re.IGNORECASE,
)
_DISC = re.compile(r"\(?\b\d+\s*(disc|levy[äa]?)\b\)?", re.IGNORECASE)
_PUNCT = re.compile(r"[:\-–—/|]+")
_MARKETPLACE_NOISE = re.compile(
    r"\b(brand\s+new|new|uusi|k[äa]ytetty|used|region\s*[a-c0-9]|region\s+free|"
    r"importti?|saksalainen|eu|bd|blu\s*ray)\b",
    re.IGNORECASE,
)
_TITLE_SEPARATOR = re.compile(r"\s+/\s+")
_SPACE = re.compile(r"\s+")


def search_query(cleaned_title: str) -> tuple[str, int | None]:
    """Strip edition noise and lift a '(1982)' year out of a title."""
    year = None
    year_match = _TITLE_YEAR.search(cleaned_title)
    if year_match:
        year = int(year_match.group(1))
    text = _TITLE_YEAR.sub("", cleaned_title)
    text = _DISC.sub("", text)
    text = _NOISE.sub("", text)
    text = re.sub(r"\(\s*\)|\[\s*\]", "", text)
    text = _PUNCT.sub(" ", text)
    return _SPACE.sub(" ", text).strip(), year


def _normalize(text: str) -> str:
    return _SPACE.sub(" ", re.sub(r"[^\w\s]", " ", text.casefold())).strip()


def score_candidate(query: str, year: int | None, candidate: Candidate) -> float:
    """Title similarity carries the score; year adjusts it; popularity only breaks ties."""
    normalized = _normalize(query)
    titles = [candidate.title, candidate.original_title or ""]
    similarity = max(
        SequenceMatcher(None, normalized, _normalize(title)).ratio() for title in titles if title
    )
    score = similarity * 0.8
    if year and candidate.release_year:
        diff = abs(year - candidate.release_year)
        if diff == 0:
            score += 0.15
        elif diff == 1:
            score += 0.10
        elif diff == 2:
            score += 0.05
        elif diff > 5:
            score -= 0.15
    score += min(candidate.popularity / 100.0, 1.0) * 0.02
    return round(max(0.0, min(score, 1.0)), 4)


def score_target(cleaned_title: str, year: int | None, target: Candidate) -> float:
    """Score a search hit against the movie the search was for.

    CDON lists 'Finnish title / Original title' and marketplace sellers append
    noise, so each side of a slash is scored on its own after removing that
    noise. A title containing every word of the wished title is at least
    worth a review.
    """
    best = 0.0
    parts = [cleaned_title, *_TITLE_SEPARATOR.split(cleaned_title)]
    for part in parts:
        query, title_year = search_query(_MARKETPLACE_NOISE.sub(" ", part))
        if query:
            best = max(best, score_candidate(query, year or title_year, target))
    words = set(_normalize(cleaned_title).split())
    wanted = [set(_normalize(t).split()) for t in (target.title, target.original_title) if t]
    if any(w and w <= words for w in wanted):
        best = max(best, TARGET_REVIEW_SCORE)
    return best


@dataclass
class MatchResult:
    considered: int = 0
    auto: int = 0
    reused: int = 0
    ambiguous: int = 0
    unmatched: int = 0
    not_applicable: int = 0
    errors: int = 0
    searched: int = 0
    """Accepted as the wished-for movie a search was looking for."""
    jev: int = 0
    """Accepted because Jev picked a candidate the title scores could not separate."""
    held: int = 0
    """Would have been accepted, but Jev was unsure whether it is a box set."""


PROGRESS_EVERY = 50


def _log_progress(result: MatchResult, total: int, level: int, jev: JevClient | None) -> None:
    logger.log(
        level,
        "matched %d/%d: %d auto, %d reused, %d wished, %d by Jev, %d held, %d ambiguous, "
        "%d unmatched, %d not applicable, %d errors%s",
        result.considered,
        total,
        result.auto,
        result.reused,
        result.searched,
        result.jev,
        result.held,
        result.ambiguous,
        result.unmatched,
        result.not_applicable,
        result.errors,
        tokens_used(jev),
    )


def _candidates_json(scored: list[tuple[float, Candidate]]) -> str:
    return json.dumps(
        [
            {
                "tmdb_id": c.tmdb_id,
                "title": c.title,
                "original_title": c.original_title,
                "release_year": c.release_year,
                "score": s,
                "poster_path": c.poster_path,
            }
            for s, c in scored[:5]
        ]
    )


def _ensure_metadata(session: Session, client: TmdbClient, tmdb_id: int, now: datetime) -> None:
    if session.get(MovieMetadata, tmdb_id) is not None:
        return
    details: MovieDetails = client.movie_details(tmdb_id)
    session.add(
        MovieMetadata(
            tmdb_id=tmdb_id,
            imdb_id=details.imdb_id,
            title=details.title,
            original_title=details.original_title,
            release_year=details.release_year,
            poster_path=details.poster_path,
            overview=details.overview,
            director=details.director,
            cast=", ".join(details.cast) or None,
            fetched_at=now,
        )
    )


def _state_for(session: Session, product: StoreProduct) -> MatchState:
    assert product.id is not None
    state = session.exec(
        select(MatchState).where(MatchState.store_product_id == product.id)
    ).first()
    if state is None:
        state = MatchState(store_product_id=product.id, status="pending")
        session.add(state)
        session.flush()
    return state


def _find_reusable(
    session: Session, product: StoreProduct, query: str, year: int | None
) -> MatchState | None:
    """A decided match for the same cleaned title (and compatible year) elsewhere."""
    rows = session.exec(
        select(MatchState, StoreProduct)
        .join(StoreProduct, StoreProduct.id == MatchState.store_product_id)  # type: ignore[arg-type]
        .where(
            MatchState.status.in_(DECIDED_STATUSES),  # type: ignore[attr-defined]
            MatchState.tmdb_id.is_not(None),  # type: ignore[union-attr]
            StoreProduct.id != product.id,
        )
    ).all()
    wanted = _normalize(query)
    for state, other in rows:
        other_query, other_year = search_query(other.cleaned_title)
        if _normalize(other_query) != wanted:
            continue
        other_year = other_year or other.release_year
        if year and other_year and abs(year - other_year) > 2:
            continue
        return state
    return None


def _search_targets(
    session: Session, product: StoreProduct, catalogue: Catalogue
) -> list[Candidate]:
    """The wished-for movies whose searches found this product."""
    targets = []
    for tmdb_id in session.exec(
        select(SearchHit.tmdb_id).where(SearchHit.store_product_id == product.id)
    ).all():
        wish = catalogue.wanted.get(tmdb_id)
        if wish is not None:
            targets.append(Candidate(tmdb_id, wish.title, wish.original_title, wish.year))
            continue
        meta = session.get(MovieMetadata, tmdb_id)
        if meta is not None:
            targets.append(Candidate(tmdb_id, meta.title, meta.original_title, meta.release_year))
    return targets


@dataclass
class _Run:
    """What one matching pass shares across products."""

    session: Session
    client: TmdbClient
    jev: JevClient | None
    now: datetime
    result: MatchResult
    catalogue: Catalogue


def _hold(state: MatchState, product: StoreProduct, run: _Run, accepted: str) -> None:
    """A possible box set is never matched automatically; a person confirms it."""
    state.status, state.tmdb_id = "ambiguous", None
    state.note = (
        f"Possible box set (Jev {product.box_set_probability:.2f}); would have accepted {accepted}"
    )
    run.result.held += 1


def _accept(
    run: _Run,
    product: StoreProduct,
    state: MatchState,
    candidate: Candidate,
    *,
    decided_by: str,
    note: str | None = None,
) -> bool:
    """Record the match. False: held for review as a possible box set."""
    accepted = f"{candidate.title!r} ({candidate.release_year})"
    if maybe_box_set(product.box_set_probability):
        _hold(state, product, run, accepted)
        return False
    _ensure_metadata(run.session, run.client, candidate.tmdb_id, run.now)
    state.status, state.tmdb_id = "auto", candidate.tmdb_id
    state.note = note or f"Accepted {accepted}"
    state.decided_at, state.decided_by = run.now, decided_by
    product.tmdb_id = candidate.tmdb_id
    transfer_product_preferences(run.session, product)
    return True


def _decide_against_targets(
    run: _Run,
    product: StoreProduct,
    state: MatchState,
    targets: list[Candidate],
    year: int | None,
) -> list[tuple[float, Candidate]] | None:
    """Check a search hit against the wished movie.

    None: accepted as the wish. Otherwise the wishes that scored in the review band,
    which open matching adds to its TMDB candidates: a store search returns many
    loosely related titles, and only a clear score settles a hit without a search.
    """
    scored = sorted(
        ((score_target(product.cleaned_title, year, t), t) for t in targets), key=lambda x: -x[0]
    )
    best_score, best = scored[0]
    if best_score >= ACCEPT_SCORE:
        state.confidence = best_score
        state.candidates_json = _candidates_json(scored)
        if _accept(run, product, state, best, decided_by="search"):
            run.result.searched += 1
        return None
    return [(score, t) for score, t in scored if score >= TARGET_REVIEW_SCORE]


def _with_wishes(
    query: str,
    year: int | None,
    found: list[Candidate],
    wishes: list[tuple[float, Candidate]],
) -> list[tuple[float, Candidate]]:
    """TMDB results plus the wishes a search hit might be, best first.

    A wish keeps the higher of its wish score and its open score, so it can still
    win, but a TMDB result that fits the title better is never outranked by it.
    """
    wish_scores = {c.tmdb_id: score for score, c in wishes}
    candidates = {c.tmdb_id: c for c in found}
    for _, wish in wishes:
        candidates.setdefault(wish.tmdb_id, wish)
    scored = [
        (max(score_candidate(query, year, c), wish_scores.get(c.tmdb_id, 0.0)), c)
        for c in candidates.values()
    ]
    return sorted(scored, key=lambda x: -x[0])


def _reuse(run: _Run, product: StoreProduct, state: MatchState, reusable: MatchState) -> None:
    if maybe_box_set(product.box_set_probability):
        _hold(state, product, run, f"the match of product {reusable.store_product_id}")
        return
    state.status, state.tmdb_id = "auto", reusable.tmdb_id
    state.confidence = reusable.confidence
    state.note = f"Reused {reusable.status} match of product {reusable.store_product_id}"
    state.decided_at, state.decided_by = run.now, "reuse"
    product.tmdb_id = reusable.tmdb_id
    transfer_product_preferences(run.session, product)
    run.result.reused += 1


def _facts(session: Session, product: StoreProduct) -> ProductFacts:
    store = session.get(Store, product.store_id)
    return ProductFacts(
        store=store.name if store else "",
        raw_title=product.raw_title,
        format=product.format,
        release_year=product.release_year,
        publisher=product.publisher,
        edition_note=product.edition_note,
    )


def _ask_jev(
    run: _Run,
    jev: JevClient,
    product: StoreProduct,
    state: MatchState,
    scored: list[tuple[float, Candidate]],
) -> None:
    """The scores could not decide: Jev picks among the top candidates, or none."""
    candidates = []
    for _, c in scored[:JEV_CANDIDATES]:
        titles = run.client.movie_titles(c.tmdb_id)
        candidates.append(
            JevCandidate(
                tmdb_id=c.tmdb_id,
                title=c.title,
                original_title=c.original_title,
                release_year=c.release_year,
                popularity=titles.popularity,
                vote_count=titles.vote_count,
                finnish_title=titles.finnish_title,
                finland_titles=titles.finland_titles,
            )
        )
    pick = pick_candidate(jev, _facts(run.session, product), candidates)
    if pick.verdict == "accept":
        chosen = next(c for _, c in scored if c.tmdb_id == pick.candidate.tmdb_id)
        state.confidence = pick.probability
        if _accept(run, product, state, chosen, decided_by="jev", note=pick.describe()):
            run.result.jev += 1
        return
    state.note = pick.describe()
    if pick.verdict == "none":
        state.status = "unmatched"
        run.result.unmatched += 1
    else:
        state.status = "ambiguous"
        run.result.ambiguous += 1


def _decide(run: _Run, product: StoreProduct, state: MatchState) -> None:
    query, title_year = search_query(product.cleaned_title)
    year = title_year or product.release_year
    state.query, state.query_year = query, year
    targets = _search_targets(run.session, product, run.catalogue)
    wishes: list[tuple[float, Candidate]] = []
    if targets:
        review = _decide_against_targets(run, product, state, targets, year)
        if review is None:
            return
        wishes = review
    if not query and not wishes:
        state.status, state.note = "unmatched", "Empty search query after cleanup"
        run.result.unmatched += 1
        return

    reusable = _find_reusable(run.session, product, query, year) if query else None
    if reusable is not None and reusable.tmdb_id is not None:
        _reuse(run, product, state, reusable)
        return

    candidates = run.client.search_movies(query, year) if query else []
    if not candidates and year and query:
        candidates = run.client.search_movies(query)
    scored = _with_wishes(query, year, candidates, wishes)
    state.candidates_json = _candidates_json(scored)
    if not scored:
        state.status, state.note = "unmatched", "No TMDB results"
        run.result.unmatched += 1
        return
    best_score, best = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else None
    accepted = best_score >= ACCEPT_SCORE and (
        (runner_up is None and best_score >= SOLE_CANDIDATE_SCORE)
        or (runner_up is not None and best_score - runner_up >= ACCEPT_MARGIN)
    )
    state.confidence = best_score
    if accepted:
        if _accept(run, product, state, best, decided_by="auto"):
            run.result.auto += 1
        return
    if run.jev is not None:
        _ask_jev(run, run.jev, product, state, scored)
        return
    state.status = "ambiguous"
    state.note = f"Best {best.title!r} scored {best_score}, runner-up {runner_up}"
    run.result.ambiguous += 1


@dataclass
class BoxSetResult:
    checked: int = 0
    box_sets: int = 0
    maybe: int = 0
    errors: int = 0


def _gate_candidates(session: Session, store: str | None, limit: int | None):  # type: ignore[no-untyped-def]
    """Active products without a box-set answer, minus title-pattern collections and
    products a person already decided."""
    query = (
        select(StoreProduct, Store)
        .join(Store, Store.id == StoreProduct.store_id)  # type: ignore[arg-type]
        .outerjoin(MatchState, MatchState.store_product_id == StoreProduct.id)  # type: ignore[arg-type]
        .where(
            StoreProduct.active == True,  # noqa: E712
            StoreProduct.is_collection == False,  # noqa: E712
            StoreProduct.box_set_probability.is_(None),  # type: ignore[union-attr]
            (MatchState.id.is_(None)) | (MatchState.status.not_in(USER_STATUSES)),  # type: ignore[attr-defined,union-attr]
        )
        .order_by(StoreProduct.id)  # type: ignore[arg-type]
    )
    if store is not None:
        query = query.where(Store.key == store)
    if limit is not None:
        query = query.limit(limit)
    return query


def _mark_box_set(session: Session, product: StoreProduct, probability: float) -> None:
    product.is_collection = True
    state = _state_for(session, product)
    state.status, state.tmdb_id = "not_applicable", None
    state.note = f"Box set (Jev {probability:.2f})"
    old_tmdb_id = product.tmdb_id
    product.tmdb_id = None
    if old_tmdb_id is not None:
        demote_movie_preferences(session, product, old_tmdb_id)


def _reopen_former_box_set(session: Session, product: StoreProduct, probability: float) -> None:
    """A new answer that no longer calls the product a box set gets it matched again.

    Happens after a retitle or a re-check with new question wording.
    """
    state = _state_for(session, product)
    note = state.note or ""
    was_box_set = state.status == "not_applicable" and note.startswith("Box set")
    was_held = state.status == "ambiguous" and note.startswith("Possible box set")
    if was_box_set or (was_held and not maybe_box_set(probability)):
        state.status, state.note = "pending", None


def _hold_decided(session: Session, product: StoreProduct, probability: float) -> None:
    """An automatic match made before the gate goes back to the queue."""
    state = _state_for(session, product)
    if state.status != "auto":
        return
    state.status, state.tmdb_id = "ambiguous", None
    state.note = f"Possible box set (Jev {probability:.2f}); was matched automatically"
    old_tmdb_id = product.tmdb_id
    product.tmdb_id = None
    if old_tmdb_id is not None:
        demote_movie_preferences(session, product, old_tmdb_id)


def gate_box_sets(
    engine: Engine,
    jev: JevClient,
    *,
    store: str | None = None,
    limit: int | None = None,
) -> BoxSetResult:
    """Ask Jev once per product title whether it is a box set of several films.

    A box set becomes a collection and is never matched. An unsettled answer is
    matched as usual but held for review. A failed call leaves the product
    unchecked, and matching skips it until a later run gets an answer.
    """
    result = BoxSetResult()
    with Session(engine) as session:
        rows = session.exec(_gate_candidates(session, store, limit)).all()
        logger.info("checking %d products for box sets", len(rows))
        for done, (product, store_row) in enumerate(rows):
            if done and done % PROGRESS_EVERY == 0:
                _log_gate_progress(result, done, len(rows), jev)
            facts = ProductFacts(
                store=store_row.name,
                raw_title=product.raw_title,
                format=product.format,
                release_year=product.release_year,
                publisher=product.publisher,
                edition_note=product.edition_note,
            )
            try:
                probability = box_set_probability(jev, facts)
            except JevError as error:
                result.errors += 1
                logger.warning("Jev box-set check failed for product %s: %s", product.id, error)
                continue
            result.checked += 1
            product.box_set_probability = probability
            if is_box_set(probability):
                _mark_box_set(session, product, probability)
                result.box_sets += 1
            else:
                _reopen_former_box_set(session, product, probability)
                if maybe_box_set(probability):
                    _hold_decided(session, product, probability)
                    result.maybe += 1
            session.commit()
        if rows:
            _log_gate_progress(result, len(rows), len(rows), jev)
    return result


def _log_gate_progress(result: BoxSetResult, done: int, total: int, jev: JevClient) -> None:
    logger.info(
        "box-set check %d/%d: %d box sets, %d unsure, %d errors%s",
        done,
        total,
        result.box_sets,
        result.maybe,
        result.errors,
        tokens_used(jev),
    )


def clear_box_set_answers(engine: Engine, *, store: str | None = None) -> int:
    """Forget Jev's box-set answers of NO and above, so the gate asks again.

    For new question wording. Title-pattern collections stay collections; the gate
    reopens matches whose new answer differs.
    """
    with Session(engine) as session:
        query = select(StoreProduct).where(
            StoreProduct.box_set_probability >= JEV_NO  # type: ignore[operator]
        )
        if store is not None:
            query = query.join(Store, Store.id == StoreProduct.store_id).where(Store.key == store)  # type: ignore[arg-type]
        products = session.exec(query).all()
        for product in products:
            product.box_set_probability = None
            product.is_collection = product.marked_box_set or title_is_box_set(product.raw_title)
        session.commit()
    return len(products)


def reset_ambiguous(engine: Engine, *, store: str | None = None) -> int:
    """Send undecided ambiguous matches back to pending, to be decided again."""
    with Session(engine) as session:
        query = select(MatchState).where(MatchState.status == "ambiguous")
        if store is not None:
            query = (
                query.join(StoreProduct, StoreProduct.id == MatchState.store_product_id)  # type: ignore[arg-type]
                .join(Store, Store.id == StoreProduct.store_id)  # type: ignore[arg-type]
                .where(Store.key == store)
            )
        states = session.exec(query).all()
        for state in states:
            state.status = "pending"
        session.commit()
    return len(states)


def _pending_products(
    session: Session, store: str | None, limit: int | None, gated: bool
) -> list[StoreProduct]:
    query = select(StoreProduct).outerjoin(
        MatchState,
        MatchState.store_product_id == StoreProduct.id,  # type: ignore[arg-type]
    )
    query = query.where(
        (MatchState.id.is_(None)) | (MatchState.status.in_(RETRY_STATUSES))  # type: ignore[attr-defined,union-attr]
    )
    if gated:
        # Not yet checked for a box set (the check failed): wait for an answer.
        query = query.where(
            (StoreProduct.is_collection == True)  # noqa: E712
            | (StoreProduct.box_set_probability.is_not(None))  # type: ignore[union-attr]
        )
    if store is not None:
        query = query.join(Store, Store.id == StoreProduct.store_id).where(Store.key == store)  # type: ignore[arg-type]
    query = query.order_by(StoreProduct.id)  # type: ignore[arg-type]
    if limit is not None:
        query = query.limit(limit)
    return list(session.exec(query).all())


def _match_one(run: _Run, product: StoreProduct) -> None:
    session, result = run.session, run.result
    state = _state_for(session, product)
    state.attempts += 1
    state.last_attempt_at = run.now
    state.last_error = None
    if product.is_collection:
        state.status = "not_applicable"
        if not (state.note or "").startswith("Box set"):
            state.note = "Collection"
        result.not_applicable += 1
        return
    try:
        _decide(run, product, state)
    except (TmdbError, JevError) as error:
        session.rollback()
        state = _state_for(session, product)
        state.attempts += 1
        state.last_attempt_at = run.now
        state.status, state.last_error = "error", str(error)
        result.errors += 1
        logger.warning("Matching error for product %s: %s", product.id, error)


def match_pending(
    engine: Engine,
    client: TmdbClient,
    *,
    jev: JevClient | None = None,
    store: str | None = None,
    limit: int | None = None,
    now: datetime | None = None,
    progress_level: int = logging.DEBUG,
) -> MatchResult:
    """Match products that have no decision yet, or whose last attempt errored.

    With a Jev client, products must have passed the box-set gate first, and Jev
    decides the cases the title scores cannot. Progress is logged every 50 products
    at progress_level: DEBUG keeps refresh logs short, the match command uses INFO.
    """
    now = now or datetime.now(UTC).replace(tzinfo=None)
    result = MatchResult()
    with Session(engine) as session:
        products = _pending_products(session, store, limit, gated=jev is not None)
        run = _Run(session, client, jev, now, result, load_catalogue(session))
        logger.log(progress_level, "matching %d products against TMDB", len(products))
        for product in products:
            if result.considered and result.considered % PROGRESS_EVERY == 0:
                _log_progress(result, len(products), progress_level, jev)
            result.considered += 1
            _match_one(run, product)
            session.commit()
        if products:
            _log_progress(result, len(products), progress_level, jev)
    return result


def mark_box_set(
    engine: Engine, store_product_id: int, *, now: datetime | None = None
) -> MatchState:
    """A person tags the product as a box set: never matched, listed on /box-sets."""
    now = now or datetime.now(UTC).replace(tzinfo=None)
    with Session(engine) as session:
        product = session.get(StoreProduct, store_product_id)
        if product is None:
            raise LookupError(f"No store product {store_product_id}")
        product.marked_box_set = True
        product.is_collection = True
        state = _state_for(session, product)
        state.status, state.tmdb_id = "not_applicable", None
        state.note = "Box set (marked by hand)"
        state.decided_at, state.decided_by = now, "user"
        state.last_error = None
        old_tmdb_id = product.tmdb_id
        product.tmdb_id = None
        if old_tmdb_id is not None:
            demote_movie_preferences(session, product, old_tmdb_id)
        session.commit()
        session.refresh(state)
        session.expunge(state)
        return state


def set_manual_match(
    engine: Engine,
    client: TmdbClient | None,
    store_product_id: int,
    tmdb_id: int | None,
    *,
    now: datetime | None = None,
) -> MatchState:
    """Record a user decision. tmdb_id None rejects every candidate for good."""
    now = now or datetime.now(UTC).replace(tzinfo=None)
    with Session(engine) as session:
        product = session.get(StoreProduct, store_product_id)
        if product is None:
            raise LookupError(f"No store product {store_product_id}")
        state = _state_for(session, product)
        if tmdb_id is not None:
            if session.get(MovieMetadata, tmdb_id) is None:
                if client is None:
                    raise LookupError(f"No cached metadata for TMDB {tmdb_id} and no client")
                _ensure_metadata(session, client, tmdb_id, now)
            state.status = "manual"
        else:
            state.status = "rejected"
        old_tmdb_id = product.tmdb_id
        state.tmdb_id = tmdb_id
        product.tmdb_id = tmdb_id
        if old_tmdb_id is not None and old_tmdb_id != tmdb_id:
            demote_movie_preferences(session, product, old_tmdb_id)
        if tmdb_id is not None:
            transfer_product_preferences(session, product)
        state.decided_at, state.decided_by = now, "user"
        state.last_error = None
        session.commit()
        session.refresh(state)
        session.expunge(state)
        return state
