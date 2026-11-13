"""TypeSafe Jev judgments for matching: the box-set gate and picking a TMDB candidate.

Jev answers typed questions with calibrated probabilities; the thresholds and the
decisions built on them live here, next to the question wording, so both can be
audited together. A failed call raises JevError and is never read as an answer.
Thresholds were checked by hand against 75 ambiguous products on jev-1.14.0.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import requests

logger = logging.getLogger(__name__)

API_URL = "https://api.typesafe.ai/v1/systemone"

YES = 0.7
"""A Noul above this reads as yes."""
NO = 0.3
"""A Noul below this reads as no; between NO and YES is unsettled."""
PICK = 0.7
"""The chosen candidate needs at least this probability to be accepted."""

FORMATS = {"bd": "Blu-ray", "4k": "4K UHD Blu-ray", "dvd": "DVD"}
CONTEXT = (
    "The product is a disc sold by a Finnish store. Store titles often give the original "
    "title and the Finnish release title separated by a slash or colon, and add format "
    "markers such as (Blu-ray). Films sold on disc are usually widely released; TMDB "
    "popularity and vote counts show how widely known each film is."
)


class JevError(RuntimeError):
    """Jev was unreachable or answered with something unusable. Retry later."""


class JevClient(Protocol):
    def ask(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        """Answers keyed by question id."""
        ...


class HttpJevClient:
    def __init__(self, api_key: str, *, model: str) -> None:
        if not api_key:
            raise ValueError("JEV_API_KEY is required for Jev judgments")
        self.model = model
        self.input_tokens = 0
        """Running total for this client, for progress logs. Output tokens are free."""
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {api_key}"

    def ask(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        payload = {"model": self.model, "state": state, "questions": questions}
        try:
            response = self.session.post(API_URL, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as error:
            raise JevError(f"Jev request failed: {error}") from error
        answers = data.get("answers") if isinstance(data, dict) else None
        if not isinstance(answers, dict) or set(questions) - set(answers):
            raise JevError("Jev response is missing answers")
        used = data.get("usage", {}).get("input_tokens")
        if isinstance(used, int):
            self.input_tokens += used
        logger.debug("jev %s: %s input tokens", data.get("model"), used)
        return answers


@dataclass
class ProductFacts:
    store: str
    raw_title: str
    format: str
    release_year: int | None = None
    publisher: str | None = None
    edition_note: str | None = None

    def state(self) -> dict[str, Any]:
        product: dict[str, Any] = {
            "store": self.store,
            "store_title": self.raw_title,
            "format": FORMATS.get(self.format, self.format),
        }
        if self.release_year:
            product["release_year_listed_by_store"] = self.release_year
        if self.publisher:
            product["publisher"] = self.publisher
        if self.edition_note:
            product["edition_note"] = self.edition_note
        return product


@dataclass
class JevCandidate:
    tmdb_id: int
    title: str
    original_title: str | None = None
    release_year: int | None = None
    popularity: float = 0.0
    vote_count: int = 0
    finnish_title: str | None = None
    finland_titles: list[str] = field(default_factory=list)

    def film(self) -> str:
        """How a question names this film."""
        text = f"{self.title!r} ({self.release_year or 'year unknown'})"
        if self.finnish_title and self.finnish_title != self.title:
            text += f", Finnish title {self.finnish_title!r},"
        return text

    def describe(self) -> str:
        text = f"TMDB film titled {self.title!r}"
        if self.original_title and self.original_title != self.title:
            text += f", original title {self.original_title!r}"
        if self.finnish_title:
            text += f", Finnish title {self.finnish_title!r}"
        if self.finland_titles:
            text += ", other titles in Finland: " + ", ".join(repr(t) for t in self.finland_titles)
        text += f", released {self.release_year or 'year unknown'}"
        return f"{text}, TMDB popularity {self.popularity:.1f} with {self.vote_count:,} votes"


TITLE_CONTEXT = (
    "The product is a disc sold by a Finnish store. Store titles often name the same film "
    "twice, giving its original title and its Finnish or alternative title separated by a "
    "slash or colon, as in 'The Shining / Hohto'."
)
"""Without this, 'Original / Finnish title' reads as two films (14 of 37 single films
tagged as box sets in a hand-labelled check; 2-3 with it, and no box sets missed)."""

BOX_SET_QUESTION = {
    "type": "noul",
    "instructions": "Does the product in `product` contain several different films?",
    "criteria": {
        "true": "The product is a set of different films, such as a film together with "
        "its sequels, a trilogy, a double feature or a film collection.",
        "false": "The product is one film, even when it comes in several versions or on "
        "several discs, such as a 4K disc with a Blu-ray copy, a 3D and a 2D version, "
        "a director's cut alongside the theatrical cut, or a bonus disc.",
    },
}


def tokens_used(client: JevClient | None) -> str:
    """', N Jev tokens' for a progress line, or nothing when the client does not count."""
    used = getattr(client, "input_tokens", None)
    return f", {used:,} Jev tokens" if isinstance(used, int) else ""


def box_set_probability(client: JevClient, product: ProductFacts) -> float:
    """Probability that the product is a set of several different films."""
    state = {"product": product.state(), "context": TITLE_CONTEXT}
    answers = client.ask(state, {"box_set": BOX_SET_QUESTION})
    return _noul(answers, "box_set")


def is_box_set(probability: float | None) -> bool:
    return probability is not None and probability > YES


def maybe_box_set(probability: float | None) -> bool:
    """Unsettled: match as usual, but a person confirms the result."""
    return probability is not None and NO <= probability <= YES


Verdict = Literal["accept", "review", "none"]


@dataclass
class Pick:
    verdict: Verdict
    candidate: JevCandidate
    probability: float
    """Probability of the chosen candidate among the options."""
    fits: float
    """Probability that any candidate is the film on the disc."""
    title_match: float
    """Probability that the store title is a release title of the chosen candidate."""

    def describe(self) -> str:
        c = self.candidate
        return (
            f"Jev {self.verdict}: {c.title!r} ({c.release_year}) p={self.probability:.2f}, "
            f"fits={self.fits:.2f}, title={self.title_match:.2f}"
        )


def decide(probability: float, fits: float, title_match: float) -> Verdict:
    """Accept only a clear pick that either a fit or a title match backs up."""
    if probability >= PICK and max(fits, title_match) > YES:
        return "accept"
    if fits < NO and title_match < NO:
        return "none"
    return "review"


def _option_names(candidates: list[JevCandidate]) -> list[str]:
    names: list[str] = []
    for c in candidates:
        name = f"{c.title} ({c.release_year or 'year unknown'})"
        if name in names:
            name = f"{name} [tmdb {c.tmdb_id}]"
        names.append(name)
    return names


def pick_candidate(
    client: JevClient, product: ProductFacts, candidates: list[JevCandidate]
) -> Pick:
    """Which candidate is the film on the disc, and whether any of them is."""
    if not candidates:
        raise ValueError("pick_candidate needs at least one candidate")
    names = _option_names(candidates)
    questions: dict[str, Any] = {
        "movie": {
            "type": "choice",
            "instructions": "Which film is on the disc described in `product`?",
            "criteria": {name: c.describe() for name, c in zip(names, candidates, strict=True)},
        },
        "any_fits": {
            "type": "noul",
            "instructions": "Is the film on the disc in `product` one of the films in "
            "`candidates`?",
            "criteria": {
                "true": "The disc contains one of the listed films, under its original or a "
                "translated title.",
                "false": "The disc contains a different film, for example a sequel, a remake, "
                "or another film that shares words with the title.",
            },
        },
    }
    for i, c in enumerate(candidates):
        film = c.film()
        questions[f"release_title_{i}"] = {
            "type": "noul",
            "instructions": f"Is `product.store_title` a title that the film {film} was "
            "released under, either its original title or a translated title such as its "
            "Finnish title?",
            "criteria": {
                "true": f"The store title names {film} by its original or a translated "
                "release title.",
                "false": f"The store title names a different film than {film}, even if some "
                "words match.",
            },
        }
    state = {
        "product": product.state(),
        "candidates": [c.describe() for c in candidates],
        "context": CONTEXT,
    }
    answers = client.ask(state, questions)
    movie = answers["movie"]
    probabilities = movie.get("probabilities") if isinstance(movie, dict) else None
    choice = movie.get("choice") if isinstance(movie, dict) else None
    if not isinstance(probabilities, dict) or choice not in names:
        raise JevError("Jev choice answer is malformed")
    index = names.index(choice)
    probability = float(probabilities[choice])
    fits = _noul(answers, "any_fits")
    title_match = _noul(answers, f"release_title_{index}")
    return Pick(
        verdict=decide(probability, fits, title_match),
        candidate=candidates[index],
        probability=probability,
        fits=fits,
        title_match=title_match,
    )


def _noul(answers: dict[str, Any], key: str) -> float:
    answer = answers.get(key)
    value = answer.get("noul") if isinstance(answer, dict) else None
    if not isinstance(value, int | float):
        raise JevError(f"Jev answer {key!r} is malformed")
    return float(value)
