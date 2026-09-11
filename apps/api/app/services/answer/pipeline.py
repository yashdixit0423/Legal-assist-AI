"""``POST /v1/ask``, end to end — spec §05 steps 1 to 9.

    rewrite → retrieve → rerank → **gate** → expand → pack → generate →
    **validate** → log

The gate runs before the model, so a question the corpus cannot answer costs
nothing and cannot be answered from the model's own memory. The validator runs
on what was actually produced, so a fabricated section number is caught in code
rather than hoped away in a prompt instruction.

Two entry points share one prologue:

* :func:`answer_question` — buffered, returns an :class:`AskResult`;
* :func:`stream_answer` — the same work, yielding :class:`Event` objects for SSE.

They share :func:`_prepare` so that the gate, the packing and the allowed
citation set cannot drift between the streaming and non-streaming paths. A
product whose safety property holds on one transport and not the other has no
safety property.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import LegalEdgeError
from app.core.logging import get_logger
from app.db.models import AskLog
from app.services.answer.abstain import ABSTENTION_MESSAGE, GateResult, apply_floor
from app.services.answer.citations import CITATION, CitationCheck, validate_citations
from app.services.answer.pack import (
    ContextBlock,
    expand_to_sections,
    pack,
    packed_section_ids,
    render_context,
)
from app.services.answer.prompt import PROMPT_VERSION, build_messages, build_retry_messages
from app.services.answer.rewrite import Rewrite, rewrite_question
from app.services.llm import client as llm
from app.services.retrieval.hybrid import hybrid_search
from app.services.retrieval.rerank import rerank

logger = get_logger(__name__)

EventName = Literal["sources", "token", "citation", "invalidated", "abstain", "error", "done"]


@dataclass(frozen=True)
class Event:
    """One server-sent event."""

    name: EventName
    data: dict[str, Any]


@dataclass
class AskResult:
    """Everything a caller needs to build a response or a log row."""

    answered: bool
    abstained: bool
    answer: str
    blocks: list[ContextBlock] = field(default_factory=list)
    cited_section_ids: list[int] = field(default_factory=list)
    top_score: float | None = None
    score_floor: float = 0.0
    abstain_reason: str | None = None
    citation_violation: bool = False
    model: str | None = None
    prompt_version: str = PROMPT_VERSION
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int = 0
    question: str = ""
    rewritten_question: str | None = None

    @property
    def retrieved_section_ids(self) -> list[int]:
        return [block.section_id for block in self.blocks]


@dataclass
class Prepared:
    """The outcome of everything that happens before the model is called."""

    gate: GateResult
    rewrite: Rewrite
    blocks: list[ContextBlock] = field(default_factory=list)
    context: str = ""
    allowed: frozenset[int] = frozenset()
    abstain_reason: str | None = None

    @property
    def ready(self) -> bool:
        return self.gate.passed and bool(self.allowed)


async def _prepare(
    session: AsyncSession,
    settings: Settings,
    question: str,
    *,
    turns: list[dict[str, str]] | None = None,
    statute_slug: str | None = None,
    api_key: str | None = None,
) -> Prepared:
    """Rewrite, retrieve, rerank, gate, expand and pack. No model call to answer."""
    rewrite = await rewrite_question(settings, question, turns or [], api_key=api_key)
    candidates = await hybrid_search(session, settings, rewrite.question, statute_slug=statute_slug)
    ranked = rerank(settings, rewrite.question, candidates)
    gate = apply_floor(ranked, floor=settings.RERANK_SCORE_FLOOR, top_n=settings.RERANK_TOP_N)
    if not gate.passed:
        logger.info("abstained", reason=gate.reason, top_score=gate.top_score)
        return Prepared(gate=gate, rewrite=rewrite, abstain_reason=gate.reason)

    blocks = pack(
        await expand_to_sections(session, gate.kept),
        budget_tokens=settings.CONTEXT_BUDGET_TOKENS,
    )
    allowed = packed_section_ids(blocks)
    if not allowed:
        # Cannot happen with a sane budget, but a prompt with no blocks would
        # be asking the model to answer from memory.
        logger.error("packing_produced_no_blocks", kept=len(gate.kept))
        return Prepared(gate=gate, rewrite=rewrite, abstain_reason="no_context_packed")

    return Prepared(
        gate=gate,
        rewrite=rewrite,
        blocks=blocks,
        context=render_context(blocks),
        allowed=allowed,
    )


def _abstention(prepared: Prepared, *, started: float, reason: str | None = None) -> AskResult:
    return AskResult(
        answered=False,
        abstained=True,
        answer=ABSTENTION_MESSAGE,
        top_score=prepared.gate.top_score,
        score_floor=prepared.gate.floor,
        abstain_reason=reason or prepared.abstain_reason,
        question=prepared.rewrite.original,
        rewritten_question=prepared.rewrite.question if prepared.rewrite.changed else None,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


# --- buffered path ----------------------------------------------------------


async def answer_question(
    session: AsyncSession,
    settings: Settings,
    question: str,
    *,
    turns: list[dict[str, str]] | None = None,
    statute_slug: str | None = None,
    api_key: str | None = None,
) -> AskResult:
    """Answer one question, or abstain honestly."""
    started = time.perf_counter()
    prepared = await _prepare(
        session, settings, question, turns=turns, statute_slug=statute_slug, api_key=api_key
    )
    if not prepared.ready:
        return _abstention(prepared, started=started)

    messages = build_messages(prepared.rewrite.question, prepared.context)
    completion = await llm.complete(settings, messages, api_key=api_key)
    check = validate_citations(completion.text, prepared.allowed)

    violation = check.violation
    if not check.ok:
        logger.warning("citation_check_failed", reason=check.reason, attempt=1)
        completion = await llm.complete(settings, _retry_messages(prepared, completion.text, check))
        check = validate_citations(completion.text, prepared.allowed)
        if not check.ok:
            logger.error("citation_check_failed_twice", reason=check.reason)
            result = _abstention(prepared, started=started, reason=f"citation_{check.reason}")
            result.citation_violation = True
            result.model = completion.model
            result.tokens_in = completion.tokens_in
            result.tokens_out = completion.tokens_out
            return result

    return AskResult(
        answered=True,
        abstained=False,
        answer=completion.text,
        blocks=prepared.blocks,
        cited_section_ids=sorted(check.cited),
        top_score=prepared.gate.top_score,
        score_floor=prepared.gate.floor,
        citation_violation=violation,
        model=completion.model,
        tokens_in=completion.tokens_in,
        tokens_out=completion.tokens_out,
        question=prepared.rewrite.original,
        rewritten_question=prepared.rewrite.question if prepared.rewrite.changed else None,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def _retry_messages(
    prepared: Prepared, previous: str, check: CitationCheck
) -> list[dict[str, str]]:
    return build_retry_messages(
        prepared.rewrite.question,
        prepared.context,
        previous,
        invalid=[f"S{sid}" for sid in sorted(check.invalid)] or ["nothing at all"],
        allowed=[block.citation_id for block in prepared.blocks],
    )


# --- streaming path ---------------------------------------------------------


def _sources_payload(result_blocks: list[ContextBlock]) -> list[dict[str, Any]]:
    return [
        {
            "citation_id": block.citation_id,
            "section_id": block.section_id,
            "statute": block.statute_short_title,
            "statute_slug": block.statute_slug,
            "section_no": block.section_no,
            "marginal_note": block.marginal_note,
            "origin": block.origin,
            "rerank_score": block.rerank_score,
        }
        for block in result_blocks
    ]


async def stream_answer(
    session: AsyncSession,
    settings: Settings,
    question: str,
    *,
    turns: list[dict[str, str]] | None = None,
    statute_slug: str | None = None,
    api_key: str | None = None,
) -> AsyncIterator[tuple[Event, AskResult | None]]:
    """Yield SSE events, and on the final ``done`` the result for logging.

    **Citations are validated as they are emitted, not only at the end.** The
    alternative — stream freely and check afterwards — puts a fabricated
    section number on a lawyer's screen and retracts it a second later, which
    is worse than being slow. The moment a ``[S…]`` id appears that was not in
    the prompt, the stream is abandoned mid-sentence and an ``invalidated``
    event tells the client to discard everything it has rendered. The single
    permitted retry is then run buffered, so the corrected answer is only sent
    once it is known to be clean.
    """
    started = time.perf_counter()
    prepared = await _prepare(session, settings, question, turns=turns, statute_slug=statute_slug)

    if prepared.rewrite.changed:
        yield Event("token", {"text": ""}), None  # keeps the connection warm
    if not prepared.ready:
        result = _abstention(prepared, started=started)
        yield (
            Event(
                "abstain",
                {
                    "reason": result.abstain_reason,
                    "message": result.answer,
                    "top_score": result.top_score,
                    "score_floor": result.score_floor,
                },
            ),
            None,
        )
        yield Event("done", _done_payload(result)), result
        return

    yield Event("sources", {"sources": _sources_payload(prepared.blocks)}), None

    messages = build_messages(prepared.rewrite.question, prepared.context)
    try:
        streamed = await _stream_attempt(settings, messages, prepared, api_key=api_key)
    except LegalEdgeError as exc:
        yield Event("error", {"code": exc.code, "message": exc.message}), None
        return

    for event in streamed.events:
        yield event, None

    check = streamed.check
    completion = streamed.completion

    if check is None or not check.ok:
        yield (
            Event(
                "invalidated",
                {
                    "reason": (check.reason if check else "citation_out_of_context"),
                    "message": "Discard the text streamed so far; it is being corrected.",
                },
            ),
            None,
        )
        try:
            completion = await llm.complete(
                settings,
                _retry_messages(prepared, streamed.text, streamed.check_or_empty),
                api_key=api_key,
            )
        except LegalEdgeError as exc:
            yield Event("error", {"code": exc.code, "message": exc.message}), None
            return
        check = validate_citations(completion.text, prepared.allowed)
        if not check.ok:
            logger.error("citation_check_failed_twice", reason=check.reason)
            result = _abstention(prepared, started=started, reason=f"citation_{check.reason}")
            result.citation_violation = True
            result.model = completion.model
            yield (
                Event("abstain", {"reason": result.abstain_reason, "message": result.answer}),
                None,
            )
            yield Event("done", _done_payload(result)), result
            return
        yield Event("token", {"text": completion.text, "replaces_all": True}), None

    result = AskResult(
        answered=True,
        abstained=False,
        answer=completion.text if completion else streamed.text,
        blocks=prepared.blocks,
        cited_section_ids=sorted(check.cited),
        top_score=prepared.gate.top_score,
        score_floor=prepared.gate.floor,
        citation_violation=streamed.violated,
        model=completion.model if completion else None,
        tokens_in=completion.tokens_in if completion else None,
        tokens_out=completion.tokens_out if completion else None,
        question=prepared.rewrite.original,
        rewritten_question=prepared.rewrite.question if prepared.rewrite.changed else None,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    for section_id in result.cited_section_ids:
        yield Event("citation", {"citation_id": f"S{section_id}", "section_id": section_id}), None
    yield Event("done", _done_payload(result)), result


@dataclass
class _StreamAttempt:
    events: list[Event]
    text: str
    completion: Any
    check: CitationCheck | None
    violated: bool

    @property
    def check_or_empty(self) -> CitationCheck:
        return self.check or validate_citations("", frozenset())


async def _stream_attempt(
    settings: Settings,
    messages: list[dict[str, str]],
    prepared: Prepared,
    *,
    api_key: str | None = None,
) -> _StreamAttempt:
    """Consume one streamed completion, stopping the moment a citation is bad."""
    events: list[Event] = []
    buffer = ""
    completion = None
    violated = False

    async for part in llm.stream(settings, messages, api_key=api_key):
        if not isinstance(part, str):
            completion = part
            break
        buffer += part
        if _has_invalid_citation(buffer, prepared.allowed):
            violated = True
            logger.warning("citation_violation_mid_stream", chars=len(buffer))
            break
        events.append(Event("token", {"text": part}))

    if violated:
        return _StreamAttempt(
            events=events, text=buffer, completion=completion, check=None, violated=True
        )
    text = completion.text if completion else buffer.strip()
    return _StreamAttempt(
        events=events,
        text=text,
        completion=completion,
        check=validate_citations(text, prepared.allowed),
        violated=False,
    )


def _has_invalid_citation(buffer: str, allowed: frozenset[int]) -> bool:
    """True as soon as a complete ``[S<id>]`` in the buffer is not permitted."""
    return any(int(match.group(1)) not in allowed for match in CITATION.finditer(buffer))


def _done_payload(result: AskResult) -> dict[str, Any]:
    return {
        "answered": result.answered,
        "abstained": result.abstained,
        "cited_section_ids": result.cited_section_ids,
        "citation_violation": result.citation_violation,
        "model": result.model,
        "prompt_version": result.prompt_version,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "latency_ms": result.latency_ms,
    }


# --- step 9: the anonymous log ---------------------------------------------


async def write_ask_log(session: AsyncSession, result: AskResult) -> None:
    """One anonymous row per question — spec §05 step 9.

    No ``user_id``, no foreign keys; the table has none and a test asserts it
    cannot grow one. This is the only place user text is persisted anywhere in
    the system, and it is deliberate: it is the sole evaluation data this phase
    produces, and Stage 8's metrics have nothing to read without it.
    """
    session.add(
        AskLog(
            question=result.question,
            lang="en",
            rewritten_question=result.rewritten_question,
            retrieved_section_ids=result.retrieved_section_ids,
            top_score=result.top_score,
            answered=result.answered,
            abstained=result.abstained,
            citation_violation=result.citation_violation,
            model=result.model,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            latency_ms=result.latency_ms,
        )
    )
    await session.commit()


__all__ = ["AskResult", "Event", "answer_question", "stream_answer", "write_ask_log"]
