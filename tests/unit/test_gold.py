"""The gold set and its metrics.

The metrics are the number that makes the retrieval claim checkable, so the
arithmetic gets tested rather than eyeballed — a recall figure that is quietly
wrong is worse than no recall figure, because it will be quoted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.eval.gold import CaseOutcome, GoldCase, Report

GOLD_FILE = Path("eval/gold/gold-v1.json")


def case(cid: str, expected: set[int], *, adversarial: bool = False) -> GoldCase:
    return GoldCase(
        id=cid,
        question=f"question {cid}",
        topic="t",
        expected_section_ids=frozenset(expected),
        must_abstain=adversarial,
    )


def outcome(
    cid: str,
    expected: set[int],
    ranked: list[int],
    *,
    abstained: bool = False,
    adversarial: bool = False,
) -> CaseOutcome:
    return CaseOutcome(
        case=case(cid, expected, adversarial=adversarial),
        ranked_section_ids=ranked,
        top_score=0.9,
        abstained=abstained,
        latency_ms=100,
    )


# --- recall and MRR ---------------------------------------------------------


def test_a_hit_at_rank_one_counts_at_every_k():
    o = outcome("a", {7}, [7, 8, 9])
    assert all(o.hit_at(k) for k in (1, 3, 6, 10))


def test_a_hit_at_rank_four_counts_only_from_six():
    o = outcome("a", {7}, [1, 2, 3, 7, 8, 9])
    assert not o.hit_at(1)
    assert not o.hit_at(3)
    assert o.hit_at(6)


def test_any_one_of_several_labelled_sections_is_a_hit():
    """Some questions are answered by more than one provision; finding either
    is finding the answer."""
    o = outcome("a", {7, 8}, [99, 8])
    assert o.hit_at(3)


def test_a_case_with_no_labels_is_never_a_hit():
    assert not outcome("a", set(), [1, 2, 3]).hit_at(10)


def test_reciprocal_rank_is_one_over_the_first_correct_rank():
    assert outcome("a", {7}, [7]).reciprocal_rank == 1.0
    assert outcome("a", {7}, [1, 7]).reciprocal_rank == pytest.approx(0.5)
    assert outcome("a", {7}, [1, 2, 3, 7]).reciprocal_rank == pytest.approx(0.25)
    assert outcome("a", {7}, [1, 2, 3]).reciprocal_rank == 0.0


def test_recall_is_computed_over_labelled_cases_only():
    """Adversarial cases have no correct section; including them in the
    denominator would drag recall down for behaving correctly."""
    report = Report(
        outcomes=[
            outcome("a", {1}, [1]),
            outcome("b", {2}, [9, 9, 9]),
            outcome("x", set(), [], abstained=True, adversarial=True),
        ]
    )
    assert len(report.in_corpus) == 2
    assert report.recall_at(6) == pytest.approx(0.5)


def test_mrr_averages_over_labelled_cases():
    report = Report(outcomes=[outcome("a", {1}, [1]), outcome("b", {2}, [9, 2])])
    assert report.mrr == pytest.approx((1.0 + 0.5) / 2)


# --- abstention -------------------------------------------------------------


def test_abstention_accuracy_counts_refusals_of_adversarial_questions():
    report = Report(
        outcomes=[
            outcome("x", set(), [], abstained=True, adversarial=True),
            outcome("y", set(), [], abstained=True, adversarial=True),
            outcome("z", set(), [5], abstained=False, adversarial=True),
        ]
    )
    assert report.abstention_accuracy == pytest.approx(2 / 3)


def test_false_abstention_rate_is_the_cost_of_the_floor():
    """Refusing a question the corpus can answer is the failure mode a high
    floor produces, and it has to be visible next to abstention accuracy or
    the floor looks free."""
    report = Report(outcomes=[outcome("a", {1}, [1]), outcome("b", {2}, [2], abstained=True)])
    assert report.false_abstention_rate == pytest.approx(0.5)


def test_an_abstained_labelled_case_is_not_correct_even_if_retrieval_found_it():
    """Retrieval putting the right section first does not help a user who was
    told the corpus has nothing."""
    o = outcome("a", {1}, [1], abstained=True)
    assert o.hit_at(1)
    assert not o.correct


def test_an_adversarial_case_is_correct_exactly_when_it_abstains():
    assert outcome("x", set(), [], abstained=True, adversarial=True).correct
    assert not outcome("x", set(), [3], abstained=False, adversarial=True).correct


# --- latency ----------------------------------------------------------------


def test_percentiles_come_from_every_case():
    report = Report(outcomes=[outcome(str(i), {1}, [1]) for i in range(10)])
    for index, o in enumerate(report.outcomes):
        o.latency_ms = index * 100
    assert report.latency_p50 == 400
    assert report.latency_p95 == 900


# --- the gold file itself ---------------------------------------------------


@pytest.fixture(scope="module")
def gold() -> dict:
    if not GOLD_FILE.exists():
        pytest.skip("gold set not present")
    return json.loads(GOLD_FILE.read_text(encoding="utf-8"))


def test_the_gold_set_has_both_halves(gold):
    assert len(gold["in_corpus"]) >= 100
    assert len(gold["adversarial"]) >= 30


def test_every_gold_id_is_unique(gold):
    ids = [c["id"] for c in gold["in_corpus"] + gold["adversarial"]]
    assert len(ids) == len(set(ids))


def test_every_labelled_case_names_at_least_one_section(gold):
    for entry in gold["in_corpus"]:
        assert entry["expected"], entry["id"]
        for group in entry["expected"]:
            assert group["statute_slug"]
            assert group["sections"]


def test_no_adversarial_case_names_a_section(gold):
    """An out-of-corpus question with an expected section is a contradiction,
    and would be scored as both a miss and a correct refusal."""
    for entry in gold["adversarial"]:
        assert entry["expected"] == []
        assert entry["must_abstain"] is True


def test_questions_are_written_as_a_user_would_ask_them(gold):
    for entry in gold["in_corpus"] + gold["adversarial"]:
        question = entry["question"]
        assert question.endswith("?"), entry["id"]
        # Three words is a real question ("What is bailment?"); one is not.
        assert len(question.split()) >= 3, entry["id"]


def test_the_adversarial_half_covers_the_categories_that_matter(gold):
    """Spec §10 names case law, foreign law, tax rates and opinions."""
    topics = {entry["topic"] for entry in gold["adversarial"]}
    for required in ("case law", "foreign law", "tax", "opinion"):
        assert required in topics


# --- checkpointing ----------------------------------------------------------


def test_the_fingerprint_changes_when_the_device_changes(settings_env, tmp_path, monkeypatch):
    """Mixing CPU and MPS results into one recall figure means two instruments
    behind one number. The fingerprint is what stops that happening silently."""
    from app.core.config import get_settings, reset_settings_cache
    from app.services.eval.gold import fingerprint

    gold = tmp_path / "g.json"
    gold.write_text('{"in_corpus": [], "adversarial": []}', encoding="utf-8")

    before = fingerprint(get_settings(), gold)
    monkeypatch.setenv("MODEL_DEVICE", "mps")
    reset_settings_cache()
    assert fingerprint(get_settings(), gold) != before


def test_the_fingerprint_changes_when_the_score_floor_changes(settings_env, tmp_path, monkeypatch):
    from app.core.config import get_settings, reset_settings_cache
    from app.services.eval.gold import fingerprint

    gold = tmp_path / "g.json"
    gold.write_text('{"in_corpus": [], "adversarial": []}', encoding="utf-8")
    before = fingerprint(get_settings(), gold)
    monkeypatch.setenv("RERANK_SCORE_FLOOR", "0.45")
    reset_settings_cache()
    assert fingerprint(get_settings(), gold) != before


def test_the_fingerprint_changes_when_the_gold_set_changes(settings_env, tmp_path):
    from app.core.config import get_settings
    from app.services.eval.gold import fingerprint

    gold = tmp_path / "g.json"
    gold.write_text('{"in_corpus": [], "adversarial": []}', encoding="utf-8")
    before = fingerprint(get_settings(), gold)
    gold.write_text('{"in_corpus": [1], "adversarial": []}', encoding="utf-8")
    assert fingerprint(get_settings(), gold) != before


def test_a_truncated_checkpoint_line_is_discarded_not_fatal(tmp_path):
    """A run killed mid-write leaves a partial final line. Resuming must drop
    it and redo that one case, not crash."""
    from app.services.eval.gold import _read_checkpoint

    ledger = tmp_path / "c.jsonl"
    ledger.write_text(
        '{"id": "a", "ranked_section_ids": [1], "top_score": 0.9, '
        '"abstained": false, "latency_ms": 10}\n'
        '{"id": "b", "ranked_sec',
        encoding="utf-8",
    )
    assert set(_read_checkpoint(ledger)) == {"a"}


def test_a_checkpointed_case_round_trips(tmp_path):
    from app.services.eval.gold import (
        _append_checkpoint,
        _outcome_from_row,
        _read_checkpoint,
    )

    ledger = tmp_path / "c.jsonl"
    original = outcome("a", {7}, [7, 8], abstained=False)
    _append_checkpoint(ledger, original)
    restored = _outcome_from_row(original.case, _read_checkpoint(ledger)["a"])
    assert restored.ranked_section_ids == original.ranked_section_ids
    assert restored.abstained == original.abstained
    assert restored.hit_at(1) == original.hit_at(1)
