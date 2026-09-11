"""The abstention gate — the third of the four things that get a real suite.

The gate is what makes the product claim true: no model call is made when
retrieval fails the floor, so an out-of-corpus question cannot be answered from
the model's own memory of Indian law, and costs nothing.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.answer.abstain import ABSTENTION_MESSAGE, apply_floor
from app.services.retrieval.hybrid import Candidate
from app.services.retrieval.rerank import Scored

FLOOR = 0.30
TOP_N = 6


def candidate(chunk_id: int) -> Candidate:
    return Candidate(
        chunk_id=chunk_id,
        section_id=1000 + chunk_id,
        statute_id=1,
        statute_short_title="Indian Contract Act, 1872",
        statute_slug="indian-contract-act-1872",
        section_no=str(chunk_id),
        marginal_note="A marginal note",
        heading_prefix="passage: Indian Contract Act, 1872 — A marginal note. ",
        text="Some provision text.",
    )


def scored(*scores: float) -> list[Scored]:
    """Best-first, as the cross-encoder returns them."""
    return [Scored(candidate=candidate(i), score=s) for i, s in enumerate(scores, start=1)]


def test_nothing_retrieved_abstains():
    result = apply_floor([], floor=FLOOR, top_n=TOP_N)
    assert not result.passed
    assert result.kept == []
    assert result.top_score is None
    assert result.reason == "no_candidates"


def test_everything_below_the_floor_abstains():
    result = apply_floor(scored(0.29, 0.11, 0.04), floor=FLOOR, top_n=TOP_N)
    assert not result.passed
    assert result.kept == []
    assert result.reason == "below_score_floor"
    assert result.top_score == pytest.approx(0.29)


def test_a_score_exactly_on_the_floor_passes():
    """The floor is inclusive. Stated explicitly so a later refactor cannot
    flip it by accident and change the abstention rate without a test failing."""
    result = apply_floor(scored(0.30), floor=FLOOR, top_n=TOP_N)
    assert result.passed
    assert len(result.kept) == 1


def test_only_the_candidates_above_the_floor_are_kept():
    result = apply_floor(scored(0.91, 0.62, 0.31, 0.29, 0.02), floor=FLOOR, top_n=TOP_N)
    assert result.passed
    assert [round(item.score, 2) for item in result.kept] == [0.91, 0.62, 0.31]


def test_at_most_top_n_survive():
    result = apply_floor(scored(*[0.9] * 20), floor=FLOOR, top_n=TOP_N)
    assert len(result.kept) == TOP_N


def test_the_cut_is_applied_to_the_best_n_not_the_best_n_above_the_floor():
    """top_n bounds the prompt size. Ten strong candidates must not become ten
    blocks because the floor happened to admit them all."""
    result = apply_floor(scored(*[0.8] * 10), floor=FLOOR, top_n=3)
    assert len(result.kept) == 3


def test_top_score_is_reported_even_when_the_gate_closes():
    """The number is what calibrates the floor later; losing it on the
    abstention path would leave nothing to tune against."""
    result = apply_floor(scored(0.2999), floor=FLOOR, top_n=TOP_N)
    assert not result.passed
    assert result.top_score == pytest.approx(0.2999)
    assert result.floor == FLOOR


def test_a_floor_of_zero_admits_anything_scored():
    result = apply_floor(scored(0.0), floor=0.0, top_n=TOP_N)
    assert result.passed


def test_the_abstention_message_names_the_corpus_and_its_limits():
    """An abstention that does not say what the corpus covers is unhelpful, and
    one that does not say what it excludes invites the user to assume it is
    complete."""
    for act in ("Indian Contract Act 1872", "Digital Personal Data Protection Act 2023"):
        assert act in ABSTENTION_MESSAGE
    assert "no case law" in ABSTENTION_MESSAGE


def test_the_gate_does_not_reorder_or_mutate_its_input():
    ranked = scored(0.9, 0.5)
    snapshot = [replace(item) for item in ranked]
    apply_floor(ranked, floor=FLOOR, top_n=TOP_N)
    assert [item.score for item in ranked] == [item.score for item in snapshot]
