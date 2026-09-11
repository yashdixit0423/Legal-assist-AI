"""``POST /v1/ask``, end to end — spec §05 steps 2 to 8.

Step 1 (query rewriting from prior turns) and step 9 (``ask_logs``) belong to
Stage 6 and are deliberately absent; ``turns`` is accepted and ignored, which
is recorded in the response so nobody mistakes silence for support.

The order of the steps is the product:

    retrieve → rerank → **gate** → expand → pack → generate → **validate**

The gate runs before the model, so a question the corpus cannot answer costs
nothing and cannot be answered from the model's own memory. The validator runs
after, so a fabricated section number is caught in code rather than hoped away
in a prompt instruction.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.services.answer.abstain import ABSTENTION_MESSAGE, GateResult, apply_floor
from app.services.answer.citations import CitationCheck, validate_citations
from app.services.answer.pack import (
    ContextBlock,
    expand_to_sections,
    pack,
    packed_section_ids,
    render_context,
)
from app.services.answer.prompt import (
    PROMPT_VERSION,
    build_messages,
    build_retry_messages,
)
from app.services.llm import client as llm
from app.services.retrieval.hybrid import hybrid_search
from app.services.retrieval.rerank import rerank

logger = get_logger(__name__)


@dataclass
class AskResult:
    """Everything the route needs to build a response."""

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


def _abstain(gate: GateResult, *, started: float, reason: str | None = None) -> AskResult:
    return AskResult(
        answered=False,
        abstained=True,
        answer=ABSTENTION_MESSAGE,
        top_score=gate.top_score,
        score_floor=gate.floor,
        abstain_reason=reason or gate.reason,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


async def answer_question(
    session: AsyncSession,
    settings: Settings,
    question: str,
    *,
    statute_slug: str | None = None,
) -> AskResult:
    """Answer one question, or abstain honestly."""
    started = time.perf_counter()

    candidates = await hybrid_search(session, settings, question, statute_slug=statute_slug)
    ranked = rerank(settings, question, candidates)
    gate = apply_floor(ranked, floor=settings.RERANK_SCORE_FLOOR, top_n=settings.RERANK_TOP_N)
    if not gate.passed:
        logger.info("abstained", reason=gate.reason, top_score=gate.top_score)
        return _abstain(gate, started=started)

    blocks = pack(
        await expand_to_sections(session, gate.kept),
        budget_tokens=settings.CONTEXT_BUDGET_TOKENS,
    )
    allowed = packed_section_ids(blocks)
    if not allowed:
        # Nothing survived packing. Cannot happen with a sane budget, but a
        # prompt with no blocks would ask the model to answer from memory.
        logger.error("packing_produced_no_blocks", kept=len(gate.kept))
        return _abstain(gate, started=started, reason="no_context_packed")

    context = render_context(blocks)
    messages = build_messages(question, context)

    # Raises MissingProviderKeyError (402) only once we know we would answer,
    # so an out-of-corpus question never needs a key.
    completion = await llm.complete(settings, messages)
    check = validate_citations(completion.text, allowed)

    violation = False
    if not check.ok:
        violation = check.violation
        logger.warning(
            "citation_check_failed",
            reason=check.reason,
            invalid=sorted(check.invalid),
            attempt=1,
        )
        completion = await llm.complete(
            settings,
            build_retry_messages(
                question,
                context,
                completion.text,
                invalid=[f"S{sid}" for sid in sorted(check.invalid)] or ["nothing at all"],
                allowed=[block.citation_id for block in blocks],
            ),
        )
        check = validate_citations(completion.text, allowed)
        if not check.ok:
            logger.error(
                "citation_check_failed_twice",
                reason=check.reason,
                invalid=sorted(check.invalid),
            )
            result = _abstain(gate, started=started, reason=f"citation_{check.reason}")
            result.citation_violation = True
            result.model = completion.model
            result.tokens_in = completion.tokens_in
            result.tokens_out = completion.tokens_out
            return result

    return AskResult(
        answered=True,
        abstained=False,
        answer=completion.text,
        blocks=blocks,
        cited_section_ids=sorted(check.cited),
        top_score=gate.top_score,
        score_floor=gate.floor,
        citation_violation=violation,
        model=completion.model,
        tokens_in=completion.tokens_in,
        tokens_out=completion.tokens_out,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


__all__ = ["AskResult", "CitationCheck", "answer_question"]
