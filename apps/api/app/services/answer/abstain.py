"""The abstention gate — spec §05 step 4.

Run *before* any model call, so an out-of-corpus question costs nothing and
cannot be answered from the model's own memory of Indian law. That is the whole
product claim: the system answers from text it actually retrieved, or it says
it cannot.

Deliberately about twenty lines. It is short because it has to be obviously
correct, not because it is unimportant.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.retrieval.rerank import Scored


@dataclass(frozen=True)
class GateResult:
    """Whether to call the model, and what survived if so."""

    passed: bool
    kept: list[Scored]
    top_score: float | None
    floor: float
    reason: str | None = None


def apply_floor(ranked: list[Scored], *, floor: float, top_n: int) -> GateResult:
    """Keep the best ``top_n`` candidates that clear ``floor``; otherwise abstain.

    ``ranked`` is expected best-first from the cross-encoder. An empty
    candidate list and a list where nothing clears the floor are the same
    decision, reported with different reasons so the logs distinguish "the
    corpus has nothing" from "the corpus has something, but not close enough".
    """
    if not ranked:
        return GateResult(
            passed=False, kept=[], top_score=None, floor=floor, reason="no_candidates"
        )
    top_score = ranked[0].score
    kept = [item for item in ranked[:top_n] if item.score >= floor]
    if not kept:
        return GateResult(
            passed=False,
            kept=[],
            top_score=top_score,
            floor=floor,
            reason="below_score_floor",
        )
    return GateResult(passed=True, kept=kept, top_score=top_score, floor=floor)


ABSTENTION_MESSAGE = (
    "I could not find a provision in the indexed corpus that answers this "
    "question, so I am not going to answer it. The corpus currently covers the "
    "Indian Contract Act 1872, the Transfer of Property Act 1882, the Indian "
    "Stamp Act 1899, the Registration Act 1908, the Information Technology Act "
    "2000 and the Digital Personal Data Protection Act 2023 — and nothing else. "
    "It holds no case law, no state amendments and no tax rates."
)
