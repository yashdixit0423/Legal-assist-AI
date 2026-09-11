"""Expand and pack — spec §05 steps 5 and 6.

The reranker hands back *chunks*. A chunk can be one sub-section of a long
provision, so answering from it alone risks reading a rule without the proviso
that guts it. So each surviving chunk is expanded to its full parent section,
and then to the sections that section cross-references — the edges Stage 3
extracted into ``statute_links``.

Blocks are ordered by statute and then by ``section_no_sort``, which is the
order a lawyer reads an Act in, and each carries the citation id the model must
use. The packed section ids are returned alongside, because those ids are what
the citation validator checks against.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Statute, StatuteLink, StatuteSection
from app.services.retrieval.rerank import Scored

logger = get_logger(__name__)

# Cross-references are pulled in one hop only. Two hops on a statute that
# cross-references as heavily as the Registration Act pulls in most of the Act
# and drowns the provision that actually matched.
CROSS_REFERENCE_HOPS = 1


@dataclass(frozen=True)
class ContextBlock:
    """One section, verbatim, as it appears in the prompt."""

    section_id: int
    statute_short_title: str
    statute_slug: str
    section_no: str
    section_no_sort: str
    marginal_note: str | None
    text: str
    origin: str  # "retrieved" | "cross_reference"
    rerank_score: float | None = None

    @property
    def citation_id(self) -> str:
        return f"S{self.section_id}"

    def render(self) -> str:
        """The block exactly as the model sees it."""
        note = f" — {self.marginal_note.rstrip('.')}" if self.marginal_note else ""
        return (
            f'<block id="{self.citation_id}">\n'
            f"{self.statute_short_title}, section {self.section_no}{note}\n\n"
            f"{self.text}\n"
            f"</block>"
        )


def estimate_tokens(text: str) -> int:
    """A deliberately conservative character-based estimate.

    Not the generation model's real tokenizer: that would mean shipping a
    provider-specific tokenizer for every model LiteLLM can route to, and being
    wrong in a *new* way for each one. Four characters per token over-counts
    English prose slightly, which is the safe direction for a context budget —
    it packs marginally fewer blocks than it could, never more than fits.
    """
    return max(1, len(text) // 4)


async def expand_to_sections(session: AsyncSession, kept: list[Scored]) -> list[ContextBlock]:
    """Turn surviving chunks into whole sections, plus what they reference."""
    best_score: dict[int, float] = {}
    for item in kept:
        section_id = item.candidate.section_id
        best_score[section_id] = max(best_score.get(section_id, 0.0), item.score)

    retrieved_ids = set(best_score)
    referenced_ids = (
        set(
            (
                await session.execute(
                    select(StatuteLink.to_section_id).where(
                        StatuteLink.from_section_id.in_(retrieved_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        - retrieved_ids
    )

    blocks = await _load_blocks(session, retrieved_ids, origin="retrieved", scores=best_score)
    blocks += await _load_blocks(session, referenced_ids, origin="cross_reference", scores={})
    blocks.sort(key=lambda block: (block.statute_short_title, block.section_no_sort))
    return blocks


async def _load_blocks(
    session: AsyncSession,
    section_ids: set[int],
    *,
    origin: str,
    scores: dict[int, float],
) -> list[ContextBlock]:
    if not section_ids:
        return []
    rows = (
        await session.execute(
            select(
                StatuteSection.id,
                Statute.short_title,
                Statute.slug,
                StatuteSection.section_no,
                StatuteSection.section_no_sort,
                StatuteSection.marginal_note,
                StatuteSection.text_verbatim,
            )
            .join(Statute, Statute.id == StatuteSection.statute_id)
            .where(StatuteSection.id.in_(section_ids))
        )
    ).all()
    return [
        ContextBlock(
            section_id=int(row[0]),
            statute_short_title=str(row[1]),
            statute_slug=str(row[2]),
            section_no=str(row[3]),
            section_no_sort=str(row[4]),
            marginal_note=None if row[5] is None else str(row[5]),
            text=str(row[6]),
            origin=origin,
            rerank_score=scores.get(int(row[0])),
        )
        for row in rows
    ]


def pack(blocks: list[ContextBlock], *, budget_tokens: int) -> list[ContextBlock]:
    """Fit blocks into the context budget, retrieved sections first.

    Priority order matters when the budget bites: a section the reranker chose
    must never be evicted in favour of something it merely cross-references.
    Order within the prompt stays statute-then-section regardless.
    """
    ordered = sorted(
        blocks,
        key=lambda block: (
            0 if block.origin == "retrieved" else 1,
            -(block.rerank_score or 0.0),
            block.statute_short_title,
            block.section_no_sort,
        ),
    )
    kept: list[ContextBlock] = []
    used = 0
    for block in ordered:
        cost = estimate_tokens(block.render())
        # The highest-priority block always goes in, even if it alone exceeds
        # the budget. Some provisions are genuinely enormous — Indian Stamp Act
        # s.47 is 29k characters of duty schedule, roughly 7k tokens — and
        # dropping the very section the reranker chose would abstain on a
        # question we had, in fact, retrieved the answer to. Overflowing a
        # 12k budget into a 200k context window is the lesser problem.
        if kept and used + cost > budget_tokens:
            continue
        kept.append(block)
        used += cost
    kept.sort(key=lambda block: (block.statute_short_title, block.section_no_sort))
    logger.info(
        "context_packed",
        blocks=len(kept),
        dropped=len(blocks) - len(kept),
        tokens=used,
        budget=budget_tokens,
        over_budget=used > budget_tokens,
    )
    return kept


def render_context(blocks: list[ContextBlock]) -> str:
    """The corpus half of the prompt."""
    return "\n\n".join(block.render() for block in blocks)


def packed_section_ids(blocks: list[ContextBlock]) -> frozenset[int]:
    """Exactly what the citation validator is allowed to accept."""
    return frozenset(block.section_id for block in blocks)
