"""Jev question building, answer parsing and decision rules. No network."""

from unittest.mock import Mock

import pytest
import requests

from shelfwatch.catalog.jev import (
    HttpJevClient,
    JevCandidate,
    JevError,
    ProductFacts,
    box_set_probability,
    decide,
    is_box_set,
    maybe_box_set,
    pick_candidate,
    tokens_used,
)

PRODUCT = ProductFacts(store="Äx", raw_title="Raivopäät (Blu-ray)", format="bd", release_year=1978)


class FakeJev:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def ask(self, state, questions):
        self.calls.append((state, questions))
        return self.answers(questions) if callable(self.answers) else self.answers


def noul(value):
    return {"type": "noul", "noul": value}


@pytest.mark.parametrize(
    "probability,fits,title,verdict",
    [
        (0.95, 0.9, 0.9, "accept"),
        (0.95, 0.5, 0.9, "accept"),  # the title match backs the pick up
        (0.95, 0.9, 0.2, "accept"),  # a fit alone backs it up
        (0.6, 0.9, 0.9, "review"),  # unclear pick
        (0.95, 0.6, 0.6, "review"),  # nothing backs it up
        (1.0, 0.2, 0.1, "none"),  # a sole wrong candidate
    ],
)
def test_decide(probability, fits, title, verdict):
    assert decide(probability, fits, title) == verdict


def test_box_set_bands():
    assert is_box_set(0.93) and not maybe_box_set(0.93)
    assert maybe_box_set(0.5) and not is_box_set(0.5)
    assert not is_box_set(0.1) and not maybe_box_set(0.1)
    assert not is_box_set(None) and not maybe_box_set(None)


def test_box_set_probability_sends_the_product_and_title_format():
    jev = FakeJev({"box_set": noul(0.93)})
    assert box_set_probability(jev, PRODUCT) == 0.93
    state, questions = jev.calls[0]
    assert set(questions) == {"box_set"}
    assert state["product"] == {
        "store": "Äx",
        "store_title": "Raivopäät (Blu-ray)",
        "format": "Blu-ray",
        "release_year_listed_by_store": 1978,
    }
    # 'Original / Finnish title' must not read as two films.
    assert "same film twice" in state["context"]


def test_pick_uses_the_chosen_candidates_title_question():
    candidates = [
        JevCandidate(2153, "Convoy", release_year=1978, vote_count=458, finnish_title="Raivopäät"),
        JevCandidate(9, "Convoy", release_year=1978, vote_count=1),
    ]

    def answers(questions):
        options = list(questions["movie"]["criteria"])
        assert options == ["Convoy (1978)", "Convoy (1978) [tmdb 9]"]
        assert "Raivopäät" in questions["release_title_0"]["instructions"]
        return {
            "movie": {"choice": options[0], "probabilities": {options[0]: 0.97, options[1]: 0.03}},
            "any_fits": noul(0.6),
            "release_title_0": noul(0.98),
            "release_title_1": noul(0.1),
        }

    jev = FakeJev(answers)
    pick = pick_candidate(jev, PRODUCT, candidates)
    assert (pick.verdict, pick.candidate.tmdb_id, pick.title_match) == ("accept", 2153, 0.98)
    state, _ = jev.calls[0]
    assert (
        "458 votes" in state["candidates"][0]
        and "Finnish title 'Raivopäät'" in state["candidates"][0]
    )


def test_malformed_choice_is_an_error_not_an_answer():
    jev = FakeJev(
        {
            "movie": {"choice": "Something else", "probabilities": {}},
            "any_fits": noul(0.9),
            "release_title_0": noul(0.9),
        }
    )
    with pytest.raises(JevError):
        pick_candidate(jev, PRODUCT, [JevCandidate(1, "Convoy", release_year=1978)])


def test_http_client_reports_failures_and_missing_answers():
    client = HttpJevClient("key", model="jev-1.14.0")
    client.session.post = Mock(side_effect=requests.ConnectionError("down"))
    with pytest.raises(JevError):
        client.ask({}, {"box_set": {}})
    response = Mock()
    response.json.return_value = {"answers": {}}
    client.session.post = Mock(return_value=response)
    with pytest.raises(JevError):
        client.ask({}, {"box_set": {}})
    response.json.return_value = {
        "answers": {"box_set": noul(0.2)},
        "model": "jev-1.14.0",
        "usage": {"input_tokens": 210, "output_tokens": 9},
    }
    assert client.ask({}, {"box_set": {}}) == {"box_set": noul(0.2)}
    client.ask({}, {"box_set": {}})
    assert client.input_tokens == 420
    assert tokens_used(client) == ", 420 Jev tokens"
    assert tokens_used(None) == ""
    assert client.session.post.call_args.kwargs["json"]["model"] == "jev-1.14.0"


def test_http_client_needs_a_key():
    with pytest.raises(ValueError):
        HttpJevClient("", model="jev-1.14.0")
