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

import asyncio
import re
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
from app.services.answer.citations import (
    BRACKETED,
    CITATION,
    DOCUMENT_REF,
    CitationCheck,
    validate_citations,
)
from app.services.answer.pack import (
    ContextBlock,
    expand_to_sections,
    pack,
    packed_section_ids,
    render_context,
)
from app.services.answer.prompt import (
    DOCUMENT_PROMPT_VERSION,
    PROMPT_VERSION,
    build_document_messages,
    build_document_retry_messages,
    build_messages,
    build_retry_messages,
)
from app.services.answer.rewrite import Rewrite, rewrite_question
from app.services.documents.retrieve import DocumentBlock, render_documents, select_blocks
from app.services.documents.store import StoredDocument
from app.services.llm import client as llm
from app.services.retrieval.hybrid import hybrid_search
from app.services.retrieval.rerank import Scored, rerank

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
    # Chat documents (docs/adr/0005). Empty for Ask and document-free Chat.
    document_blocks: list[DocumentBlock] = field(default_factory=list)
    cited_document_ids: list[str] = field(default_factory=list)
    documents_used: int = 0

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
    document_blocks: list[DocumentBlock] = field(default_factory=list)
    documents_used: int = 0

    @property
    def ready(self) -> bool:
        return (self.gate.passed and bool(self.allowed)) or bool(self.document_blocks)

    @property
    def allowed_documents(self) -> frozenset[str] | None:
        """``None`` when no documents are in play — the validator then ignores D ids."""
        if not self.documents_used:
            return None
        return frozenset(block.citation_id for block in self.document_blocks)

    @property
    def prompt_version(self) -> str:
        return DOCUMENT_PROMPT_VERSION if self.documents_used else PROMPT_VERSION

    def messages(self) -> list[dict[str, str]]:
        if not self.documents_used:
            return build_messages(self.rewrite.question, self.context)
        return build_document_messages(
            self.rewrite.question, self.context, render_documents(self.document_blocks)
        )


async def _prepare(
    session: AsyncSession,
    settings: Settings,
    question: str,
    *,
    turns: list[dict[str, str]] | None = None,
    statute_slug: str | None = None,
    api_key: str | None = None,
    documents: list[StoredDocument] | None = None,
) -> Prepared:
    """Rewrite, retrieve, rerank, gate, expand and pack. No model call to answer.

    With documents attached (docs/adr/0005), their passages are packed too and
    the request is ready even when no statute clears the floor: "summarise
    this" cannot be scored against the corpus. The citation validator is still
    the guarantee — the answer must cite something it was given. With
    documents, each candidate's gate score is also its best score against any
    one clause of the question (:func:`question_clauses`); the floor itself is
    unchanged, and without documents this step does not run.
    """
    rewrite = await rewrite_question(settings, question, turns or [], api_key=api_key)
    candidates = await hybrid_search(session, settings, rewrite.question, statute_slug=statute_slug)
    ranked = rerank(settings, rewrite.question, candidates)
    if documents:
        clauses = question_clauses(rewrite.question)
        ranked = _best_per_candidate(
            [ranked, *(rerank(settings, clause, candidates) for clause in clauses)]
        )
    gate = apply_floor(ranked, floor=settings.RERANK_SCORE_FLOOR, top_n=settings.RERANK_TOP_N)

    document_blocks: list[DocumentBlock] = []
    if documents:
        document_blocks = await asyncio.to_thread(
            select_blocks, settings, rewrite.question, documents
        )
    documents_used = len(documents or [])

    if not gate.passed:
        if not document_blocks:
            logger.info("abstained", reason=gate.reason, top_score=gate.top_score)
            return Prepared(gate=gate, rewrite=rewrite, abstain_reason=gate.reason)
        return Prepared(
            gate=gate,
            rewrite=rewrite,
            document_blocks=document_blocks,
            documents_used=documents_used,
        )

    blocks = pack(
        await expand_to_sections(session, gate.kept),
        budget_tokens=settings.CONTEXT_BUDGET_TOKENS,
    )
    allowed = packed_section_ids(blocks)
    if not allowed and not document_blocks:
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
        document_blocks=document_blocks,
        documents_used=documents_used,
    )


# A clause boundary: after . ? ! or ;, a spaced dash, or a joining word that
# starts a new question ("..., and what rent does it set?").
_CLAUSE_BREAK = re.compile(
    r"(?<=[.?!;])\s+"
    r"|\s+[—–-]\s+"
    r"|,?\s+(?:and|but|or)\s+(?=(?:what|which|who|when|where|why|how|is|are|does|do|did"
    r"|can|could|must|should|will|would|may|has|have)\b)",
    re.IGNORECASE,
)


def question_clauses(question: str) -> list[str]:
    """The clauses of a multi-part question; empty when it has only one.

    With a document attached, a question mixes facts about the document with a
    question about the law ("My lease is for 11 months — must it be
    registered?"). The cross-encoder scores such a sentence as a whole well
    below what its law clause scores alone, so the statute gate also scores
    each clause (fix F3). Splitting is deterministic: no model call.
    """
    parts = [part.strip(" ,") for part in _CLAUSE_BREAK.split(question)]
    clauses = [part for part in parts if len(part) >= 8]
    return clauses if len(clauses) > 1 else []


def _best_per_candidate(rankings: list[list[Scored]]) -> list[Scored]:
    """Each candidate at the best score any ranking gave it, best first.

    Candidates are the same in every ranking (one search, several readings of
    the question), so the floor is applied to the same set at its best reading.
    """
    best: dict[int, Scored] = {}
    for ranking in rankings:
        for item in ranking:
            current = best.get(item.candidate.chunk_id)
            if current is None or item.score > current.score:
                best[item.candidate.chunk_id] = item
    return sorted(best.values(), key=lambda item: -item.score)


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
        prompt_version=prepared.prompt_version,
        documents_used=prepared.documents_used,
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
    documents: list[StoredDocument] | None = None,
) -> AskResult:
    """Answer one question, or abstain honestly."""
    started = time.perf_counter()
    prepared = await _prepare(
        session,
        settings,
        question,
        turns=turns,
        statute_slug=statute_slug,
        api_key=api_key,
        documents=documents,
    )
    if not prepared.ready:
        return _abstention(prepared, started=started)

    messages = prepared.messages()
    completion = await llm.complete(settings, messages, api_key=api_key)
    check = validate_citations(completion.text, prepared.allowed, prepared.allowed_documents)

    violation = check.violation
    if not check.ok:
        logger.warning("citation_check_failed", reason=check.reason, attempt=1)
        completion = await llm.complete(
            settings, _retry_messages(prepared, completion.text, check), api_key=api_key
        )
        check = validate_citations(completion.text, prepared.allowed, prepared.allowed_documents)
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
        **_document_fields(prepared, check),
    )


def _document_fields(prepared: Prepared, check: CitationCheck) -> dict[str, Any]:
    return {
        "prompt_version": prepared.prompt_version,
        "document_blocks": prepared.document_blocks,
        "cited_document_ids": sorted(check.cited_documents),
        "documents_used": prepared.documents_used,
    }


def _retry_messages(
    prepared: Prepared, previous: str, check: CitationCheck
) -> list[dict[str, str]]:
    invalid = [f"S{sid}" for sid in sorted(check.invalid)] + sorted(check.invalid_documents)
    if not prepared.documents_used:
        return build_retry_messages(
            prepared.rewrite.question,
            prepared.context,
            previous,
            invalid=invalid or ["nothing at all"],
            allowed=[block.citation_id for block in prepared.blocks],
        )
    return build_document_retry_messages(
        prepared.rewrite.question,
        prepared.context,
        render_documents(prepared.document_blocks),
        previous,
        invalid=invalid or ["nothing at all"],
        allowed=[block.citation_id for block in prepared.blocks]
        + [block.citation_id for block in prepared.document_blocks],
    )


# --- streaming path ---------------------------------------------------------


def _sources_payload(
    result_blocks: list[ContextBlock], document_blocks: list[DocumentBlock] | None = None
) -> list[dict[str, Any]]:
    statutes = [
        {
            "kind": "statute",
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
    # Document passages go back only to their owner, with a short excerpt so a
    # citation can be checked. Never the whole text, never logged.
    documents = [
        {
            "kind": "document",
            "citation_id": block.citation_id,
            "document_id": block.document_id,
            "filename": block.filename,
            "locator_kind": block.locator_kind,
            "locator": block.locator,
            "excerpt": block.excerpt,
            "rerank_score": block.score,
        }
        for block in document_blocks or []
    ]
    return statutes + documents


async def stream_answer(
    session: AsyncSession,
    settings: Settings,
    question: str,
    *,
    turns: list[dict[str, str]] | None = None,
    statute_slug: str | None = None,
    api_key: str | None = None,
    documents: list[StoredDocument] | None = None,
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
    prepared = await _prepare(
        session,
        settings,
        question,
        turns=turns,
        statute_slug=statute_slug,
        api_key=api_key,
        documents=documents,
    )

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

    yield (
        Event("sources", {"sources": _sources_payload(prepared.blocks, prepared.document_blocks)}),
        None,
    )

    messages = prepared.messages()
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
        check = validate_citations(completion.text, prepared.allowed, prepared.allowed_documents)
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
        **_document_fields(prepared, check),
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
        if _has_invalid_citation(buffer, prepared.allowed, prepared.allowed_documents):
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
        check=validate_citations(text, prepared.allowed, prepared.allowed_documents),
        violated=False,
    )


def _has_invalid_citation(
    buffer: str, allowed: frozenset[int], allowed_documents: frozenset[str] | None = None
) -> bool:
    """True as soon as a complete ``[S<id>]`` (or ``[D<n>-…]``) is not permitted."""
    if any(int(match.group(1)) not in allowed for match in CITATION.finditer(buffer)):
        return True
    if allowed_documents is None:
        return False
    return any(
        f"D{int(ref.group(1))}-{ref.group(2)}{int(ref.group(3))}" not in allowed_documents
        for group in BRACKETED.finditer(buffer)
        for ref in DOCUMENT_REF.finditer(group.group(1))
    )


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
        "cited_document_ids": result.cited_document_ids,
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
            # A count only. Document text is never logged (docs/adr/0005).
            documents_used=result.documents_used,
        )
    )
    await session.commit()


__all__ = ["AskResult", "Event", "answer_question", "stream_answer", "write_ask_log"]
