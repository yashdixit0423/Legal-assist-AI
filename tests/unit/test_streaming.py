"""Streaming, rewriting and the anonymous log — Stage 6.

The one thing here that is not a smoke test is the mid-stream citation check.
It is an extension of the citation validator, which spec §05 calls the most
important twenty lines in this phase, onto a transport where getting it wrong
means a fabricated section number is rendered on a lawyer's screen and then
retracted. The buffered path's guarantee has to survive the streaming path.
"""

from __future__ import annotations

import pytest

from app.services.answer.citations import validate_citations
from app.services.answer.pipeline import Event, _has_invalid_citation

ALLOWED = frozenset({1046, 537})


# --- the mid-stream guard ---------------------------------------------------


def test_a_permitted_citation_does_not_trip_the_guard():
    assert not _has_invalid_citation("A lease determines by efflux of time [S1046].", ALLOWED)


def test_a_fabricated_citation_trips_the_guard_as_soon_as_it_closes():
    assert _has_invalid_citation("The Act provides [S9999]", ALLOWED)


def test_a_half_written_citation_does_not_trip_the_guard_early():
    """Deltas arrive mid-token. "[S10" is the start of a permitted [S1046] as
    often as it is the start of a fabricated one; tripping on the prefix would
    abandon valid answers."""
    for partial in ("[S", "[S1", "[S10", "[S104"):
        assert not _has_invalid_citation(f"Some text {partial}", ALLOWED)
    assert not _has_invalid_citation("Some text [S1046]", ALLOWED)


def test_the_guard_agrees_with_the_buffered_validator():
    """One rule, two transports. If these ever disagree, the streaming path
    has a different safety property from the JSON one."""
    for text in (
        "Valid [S1046].",
        "Invalid [S9999].",
        "Mixed [S537] and [S4242].",
        "Footnote markers [1] and [2][State Government] with [S537].",
    ):
        buffered = validate_citations(text, ALLOWED)
        streamed = _has_invalid_citation(text, ALLOWED)
        assert streamed == buffered.violation


# --- query rewriting --------------------------------------------------------


async def test_rewriting_is_skipped_when_there_are_no_turns(settings_env):
    """Most questions are first questions; they must not pay for a model call."""
    from app.core.config import get_settings
    from app.services.answer import rewrite as rewriter

    async def explode(*args, **kwargs):
        raise AssertionError("no model call on a first question")

    rewrite = await rewriter.rewrite_question(get_settings(), "what is a contract", [])
    assert not rewrite.rewritten
    assert rewrite.reason == "no_turns"
    assert rewrite.question == "what is a contract"
    assert not rewrite.changed
    _ = explode


async def test_a_failing_rewrite_leaves_the_original_question(monkeypatch, settings_env):
    """Rewriting is an optimisation. A missing key here must not 402 a request
    that the abstention path could have answered without a key at all."""
    from app.core.config import get_settings
    from app.core.errors import MissingProviderKeyError
    from app.services.answer import rewrite as rewriter

    async def missing_key(*args, **kwargs):
        raise MissingProviderKeyError()

    monkeypatch.setattr(rewriter.llm, "complete", missing_key)
    rewrite = await rewriter.rewrite_question(
        get_settings(),
        "and the notice period?",
        [{"role": "user", "content": "how do I terminate a lease"}],
    )
    assert not rewrite.rewritten
    assert rewrite.reason == "failed_missing_provider_key"
    assert rewrite.question == "and the notice period?"


async def test_an_overlong_rewrite_is_discarded(monkeypatch, settings_env):
    """A model that explains itself instead of rewriting must not have its
    essay handed to the retriever as a query."""
    from app.core.config import get_settings
    from app.services.answer import rewrite as rewriter
    from app.services.llm.client import Completion

    async def waffle(*args, **kwargs):
        return Completion(text="x" * 500, model="m", tokens_in=1, tokens_out=1)

    monkeypatch.setattr(rewriter.llm, "complete", waffle)
    rewrite = await rewriter.rewrite_question(
        get_settings(), "and then?", [{"role": "user", "content": "lease"}]
    )
    assert not rewrite.rewritten
    assert rewrite.reason == "unusable_output"


# --- the event stream -------------------------------------------------------


async def test_an_abstention_streams_abstain_then_done_and_calls_no_model(
    monkeypatch, settings_env
):
    from app.core.config import get_settings
    from app.services.answer import pipeline
    from app.services.llm import client as llm_client

    async def explode(*args, **kwargs):
        raise AssertionError("the model must not be called on an abstention")

    monkeypatch.setattr(llm_client, "complete", explode)

    async def no_candidates(*args, **kwargs):
        return []

    def no_ranking(*_args, **_kwargs):
        return []

    monkeypatch.setattr(pipeline, "hybrid_search", no_candidates)
    monkeypatch.setattr(pipeline, "rerank", no_ranking)

    events: list[Event] = []
    final = None
    async for event, result in pipeline.stream_answer(None, get_settings(), "the GST rate"):
        events.append(event)
        final = result or final

    names = [event.name for event in events]
    assert names == ["abstain", "done"]
    assert events[0].data["reason"] == "no_candidates"
    assert final is not None and final.abstained
    assert not final.answered


# --- the anonymous log ------------------------------------------------------


def test_the_log_row_carries_no_identity():
    """ask_logs has no user_id and no foreign keys, by construction."""
    from app.db.models import AskLog

    columns = set(AskLog.__table__.columns.keys())
    assert "user_id" not in columns
    assert AskLog.__table__.foreign_keys == set()
    for expected in ("question", "rewritten_question", "retrieved_section_ids", "top_score"):
        assert expected in columns


@pytest.mark.parametrize(("answered", "abstained"), [(True, False), (False, True)])
def test_the_result_exposes_exactly_what_the_log_row_needs(answered, abstained):
    from app.services.answer.pipeline import AskResult

    result = AskResult(answered=answered, abstained=abstained, answer="x")
    assert result.retrieved_section_ids == []
    assert result.prompt_version
