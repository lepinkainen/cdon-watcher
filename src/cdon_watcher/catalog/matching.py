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

from .models import MatchState, MovieMetadata, StoreProduct
from .preferences import transfer_product_preferences
from .tmdb import Candidate, MovieDetails, TmdbClient, TmdbError

logger = logging.getLogger(__name__)

ACCEPT_SCORE = 0.80
"""Minimum score of the best candidate for an automatic match."""
ACCEPT_MARGIN = 0.08
"""Minimum lead over the runner-up for an automatic match."""
SOLE_CANDIDATE_SCORE = 0.85
"""A lone candidate needs this much to be accepted without a runner-up."""
RETRY_STATUSES = ("pending", "error")
DECIDED_STATUSES = ("auto", "manual")

_TITLE_YEAR = re.compile(r"\((19\d{2}|20\d{2})\)")
_NOISE = re.compile(
    r"\b(blu-?ray|4k|uhd|ultra\s*hd|dvd|steelbook|limited|collector'?s|special|edition|"
    r"extended|director'?s\s+cut|remastered?|import|rajoitettu|erikoisjulkaisu)\b",
    re.IGNORECASE,
)
_DISC = re.compile(r"\(?\b\d+\s*(disc|levy[äa]?)\b\)?", re.IGNORECASE)
_PUNCT = re.compile(r"[:\-–—/|]+")
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


@dataclass
class MatchResult:
    considered: int = 0
    auto: int = 0
    reused: int = 0
    ambiguous: int = 0
    unmatched: int = 0
    not_applicable: int = 0
    errors: int = 0


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


def _decide(
    session: Session,
    client: TmdbClient,
    product: StoreProduct,
    state: MatchState,
    now: datetime,
    result: MatchResult,
) -> None:
    query, title_year = search_query(product.cleaned_title)
    year = title_year or product.release_year
    state.query, state.query_year = query, year
    if not query:
        state.status, state.note = "unmatched", "Empty search query after cleanup"
        result.unmatched += 1
        return

    reusable = _find_reusable(session, product, query, year)
    if reusable is not None and reusable.tmdb_id is not None:
        state.status, state.tmdb_id = "auto", reusable.tmdb_id
        state.confidence = reusable.confidence
        state.note = f"Reused {reusable.status} match of product {reusable.store_product_id}"
        state.decided_at, state.decided_by = now, "reuse"
        product.tmdb_id = reusable.tmdb_id
        transfer_product_preferences(session, product)
        result.reused += 1
        return

    candidates = client.search_movies(query, year)
    if not candidates and year:
        candidates = client.search_movies(query)
    scored = sorted(((score_candidate(query, year, c), c) for c in candidates), key=lambda x: -x[0])
    state.candidates_json = _candidates_json(scored)
    if not scored:
        state.status, state.note = "unmatched", "No TMDB results"
        result.unmatched += 1
        return
    best_score, best = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else None
    accepted = best_score >= ACCEPT_SCORE and (
        (runner_up is None and best_score >= SOLE_CANDIDATE_SCORE)
        or (runner_up is not None and best_score - runner_up >= ACCEPT_MARGIN)
    )
    state.confidence = best_score
    if not accepted:
        state.status = "ambiguous"
        state.note = f"Best {best.title!r} scored {best_score}, runner-up {runner_up}"
        result.ambiguous += 1
        return
    _ensure_metadata(session, client, best.tmdb_id, now)
    state.status, state.tmdb_id = "auto", best.tmdb_id
    state.note = f"Accepted {best.title!r} ({best.release_year})"
    state.decided_at, state.decided_by = now, "auto"
    product.tmdb_id = best.tmdb_id
    transfer_product_preferences(session, product)
    result.auto += 1


def match_pending(
    engine: Engine,
    client: TmdbClient,
    *,
    store: str | None = None,
    limit: int | None = None,
    now: datetime | None = None,
) -> MatchResult:
    """Match products that have no decision yet, or whose last attempt errored."""
    now = now or datetime.now(UTC).replace(tzinfo=None)
    result = MatchResult()
    with Session(engine) as session:
        query = select(StoreProduct).outerjoin(
            MatchState,
            MatchState.store_product_id == StoreProduct.id,  # type: ignore[arg-type]
        )
        query = query.where(
            (MatchState.id.is_(None)) | (MatchState.status.in_(RETRY_STATUSES))  # type: ignore[attr-defined,union-attr]
        )
        if store is not None:
            from .models import Store

            query = query.join(Store, Store.id == StoreProduct.store_id).where(Store.key == store)  # type: ignore[arg-type]
        query = query.order_by(StoreProduct.id)  # type: ignore[arg-type]
        if limit is not None:
            query = query.limit(limit)
        products = session.exec(query).all()

        for product in products:
            result.considered += 1
            state = _state_for(session, product)
            state.attempts += 1
            state.last_attempt_at = now
            state.last_error = None
            if product.is_collection:
                state.status, state.note = "not_applicable", "Collection"
                result.not_applicable += 1
                session.commit()
                continue
            try:
                _decide(session, client, product, state, now, result)
            except TmdbError as error:
                session.rollback()
                state = _state_for(session, product)
                state.attempts += 1
                state.last_attempt_at = now
                state.status, state.last_error = "error", str(error)
                result.errors += 1
                logger.warning("TMDB error for product %s: %s", product.id, error)
            session.commit()
    return result


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
        state.tmdb_id = tmdb_id
        product.tmdb_id = tmdb_id
        if tmdb_id is not None:
            transfer_product_preferences(session, product)
        state.decided_at, state.decided_by = now, "user"
        state.last_error = None
        session.commit()
        session.refresh(state)
        session.expunge(state)
        return state
