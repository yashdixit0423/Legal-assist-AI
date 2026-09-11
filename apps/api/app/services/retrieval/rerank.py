"""Cross-encoder reranking, and the score that the abstention gate reads.

The bi-encoder that produced the candidates scored the question and the passage
independently. A cross-encoder reads them together, which is far more accurate
and far too slow to run over a corpus — so it runs over the ~40 candidates RRF
handed back, and its score is the number the abstention gate trusts.

``BAAI/bge-reranker-v2-m3`` rather than ``nyaya-reranker-mini-v1``: the mini
model's own card concedes it trails bge by 6.8 points at recall@1 and sells on
size, and we are not size-constrained. ``RERANK_MODEL`` keeps it swappable if
memory ever becomes the constraint.

The model emits a raw logit. Sigmoid is applied here so the score is a 0-1
number comparable against ``RERANK_SCORE_FLOOR`` — a floor calibrated against
logits would silently change meaning the day the model is swapped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger
from app.services.retrieval.hybrid import Candidate

logger = get_logger(__name__)

_RERANKERS: dict[tuple[str, str], Any] = {}


@dataclass(frozen=True)
class Scored:
    """A candidate with the cross-encoder's verdict on it."""

    candidate: Candidate
    score: float


def get_reranker(settings: Settings) -> Any:
    """The cross-encoder, on CPU, at the pinned revision."""
    revision = settings.require_rerank_revision()
    device = settings.resolve_device()
    key = (settings.RERANK_MODEL, f"{revision}@{device}")
    if key not in _RERANKERS:
        from sentence_transformers import CrossEncoder

        logger.info(
            "reranker_load",
            model=settings.RERANK_MODEL,
            revision=revision[:12],
            device=device,
        )
        _RERANKERS[key] = CrossEncoder(
            settings.RERANK_MODEL,
            revision=revision,
            device=device,
            max_length=512,
        )
    return _RERANKERS[key]


def rerank(settings: Settings, question: str, candidates: list[Candidate]) -> list[Scored]:
    """Score every candidate against the question, best first.

    The passage shown to the cross-encoder is the heading plus the body, with
    the ``passage:`` marker stripped — that prefix is an instruction to an e5
    bi-encoder and means nothing to this model, which would simply spend
    tokens on it.
    """
    if not candidates:
        return []
    from torch.nn import Sigmoid

    model = get_reranker(settings)
    pairs = [(question, passage_for_rerank(candidate)) for candidate in candidates]
    scores = model.predict(
        pairs,
        batch_size=settings.EMBED_BATCH_SIZE,
        activation_fct=Sigmoid(),
        show_progress_bar=False,
    )
    ranked = [
        Scored(candidate=candidate, score=float(score))
        for candidate, score in zip(candidates, scores, strict=True)
    ]
    ranked.sort(key=lambda item: -item.score)
    logger.info(
        "reranked",
        candidates=len(ranked),
        top=round(ranked[0].score, 4) if ranked else None,
    )
    return ranked


def passage_for_rerank(candidate: Candidate) -> str:
    """The text the cross-encoder reads for one candidate."""
    heading = candidate.heading_prefix.removeprefix("passage: ")
    return f"{heading}{candidate.text}"
