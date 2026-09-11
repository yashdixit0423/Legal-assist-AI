"""Hybrid retrieval: dense, sparse, fused with Reciprocal Rank Fusion.

Two retrievers, because neither is sufficient on its own and their failures do
not overlap:

* **Dense** (pgvector cosine over ``kb_chunks.embedding``) matches meaning. It
  finds the right provision when the question shares no vocabulary with an
  1872 statute.
* **Sparse** (``ts_rank`` over ``kb_chunks.tsv``) matches words. It finds the
  right provision when the question uses a term of art the embedding model has
  never had to place — Stage 3 measured this directly: "non-compete" puts
  Contract Act s.27 at dense rank 22 and sparse rank 1.

RRF fuses them on *rank*, not score, which is the point: a cosine of 0.66 and a
``ts_rank`` of 0.10 are not comparable numbers, and any attempt to normalise
them into one scale is a hyperparameter nobody can calibrate.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import Float, Select, bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.models import KbChunk, Statute, StatuteSection
from app.services.kb.embedding import embed_query

logger = get_logger(__name__)

TS_CONFIG = "english"


@dataclass(frozen=True)
class Candidate:
    """One chunk that at least one retriever thought was relevant."""

    chunk_id: int
    section_id: int
    statute_id: int
    statute_short_title: str
    statute_slug: str
    section_no: str
    marginal_note: str | None
    heading_prefix: str
    text: str
    dense_rank: int | None = None
    sparse_rank: int | None = None
    dense_score: float | None = None
    sparse_score: float | None = None
    rrf_score: float = 0.0

    @property
    def citation(self) -> str:
        """How this provision is named in an answer."""
        return f"{self.statute_short_title}, s. {self.section_no}"


def _base_select() -> Select[Any]:
    return (
        select(
            KbChunk.id,
            KbChunk.section_id,
            KbChunk.statute_id,
            Statute.short_title,
            Statute.slug,
            StatuteSection.section_no,
            StatuteSection.marginal_note,
            KbChunk.heading_prefix,
            KbChunk.text,
        )
        .join(StatuteSection, StatuteSection.id == KbChunk.section_id)
        .join(Statute, Statute.id == KbChunk.statute_id)
    )


def _row_to_candidate(row: tuple[Any, ...]) -> Candidate:
    return Candidate(
        chunk_id=int(row[0]),
        section_id=int(row[1]),
        statute_id=int(row[2]),
        statute_short_title=str(row[3]),
        statute_slug=str(row[4]),
        section_no=str(row[5]),
        marginal_note=None if row[6] is None else str(row[6]),
        heading_prefix=str(row[7]),
        text=str(row[8]),
    )


async def dense_search(
    session: AsyncSession,
    settings: Settings,
    question: str,
    *,
    limit: int,
    statute_slug: str | None = None,
) -> list[tuple[Candidate, float]]:
    """Cosine nearest neighbours. The ``query:`` prefix is applied by
    :func:`embed_query`, never here."""
    vector = embed_query(settings, question)
    distance = KbChunk.embedding.cosine_distance(vector)
    stmt = _base_select().add_columns(distance.label("distance"))
    if statute_slug:
        stmt = stmt.where(Statute.slug == statute_slug)
    stmt = stmt.order_by(distance).limit(limit)
    rows = (await session.execute(stmt)).all()
    return [(_row_to_candidate(tuple(row)), 1.0 - float(row[-1])) for row in rows]


def _or_tsquery(question: str) -> ColumnElement[Any]:
    """A tsquery that ORs the question's own lexemes.

    Both ``plainto_tsquery`` and ``websearch_to_tsquery`` join unquoted terms
    with AND, which is right for a search box and wrong for a question: nothing
    in a statute contains every word of "is a non-compete after employment
    enforceable" at once, so the sparse retriever returned **zero rows** and
    hybrid search was quietly running on one leg. Measured, not theorised —
    that query matched 0 chunks with AND and 117 with OR.

    The question is lexemised by ``to_tsvector`` (so stemming and the English
    stopword list are Postgres's, not ours) and the lexemes are then ORed.
    ``nullif`` covers a question that is entirely stopwords: ``to_tsquery`` is
    strict, so a NULL argument yields NULL, which matches nothing rather than
    raising a tsquery syntax error.
    """
    lexemes = func.array_to_string(
        func.tsvector_to_array(func.to_tsvector(TS_CONFIG, bindparam("q", question))), " | "
    )
    return func.to_tsquery(TS_CONFIG, func.nullif(lexemes, ""))


async def sparse_search(
    session: AsyncSession,
    question: str,
    *,
    limit: int,
    statute_slug: str | None = None,
) -> list[tuple[Candidate, float]]:
    """Lexical ranking over the English tsvector — the BM25 half of the hybrid.

    This is the retriever that finds a provision by its term of art when the
    embedding model cannot: Stage 3 measured Contract Act s.27 at dense rank 22
    and sparse rank 1 for "restraint of trade non compete".
    """
    query = _or_tsquery(question)
    rank = func.ts_rank(KbChunk.tsv, query).cast(Float)
    stmt = _base_select().add_columns(rank.label("rank")).where(KbChunk.tsv.op("@@")(query))
    if statute_slug:
        stmt = stmt.where(Statute.slug == statute_slug)
    stmt = stmt.order_by(text("rank DESC")).limit(limit)
    rows = (await session.execute(stmt)).all()
    return [(_row_to_candidate(tuple(row)), float(row[-1])) for row in rows]


def reciprocal_rank_fusion(
    dense: list[tuple[Candidate, float]],
    sparse: list[tuple[Candidate, float]],
    *,
    k: int,
) -> list[Candidate]:
    """Fuse two ranked lists into one, scoring each chunk ``sum(1/(k+rank))``.

    Ranks are 1-based. A chunk found by both retrievers scores higher than one
    found by either alone, which is the behaviour we want: agreement between
    two independent signals is evidence.
    """
    merged: dict[int, Candidate] = {}
    scores: dict[int, float] = {}

    for rank, (candidate, score) in enumerate(dense, start=1):
        merged[candidate.chunk_id] = candidate
        scores[candidate.chunk_id] = scores.get(candidate.chunk_id, 0.0) + 1.0 / (k + rank)
        merged[candidate.chunk_id] = _with(
            merged[candidate.chunk_id], dense_rank=rank, dense_score=score
        )
    for rank, (candidate, score) in enumerate(sparse, start=1):
        existing = merged.get(candidate.chunk_id, candidate)
        scores[candidate.chunk_id] = scores.get(candidate.chunk_id, 0.0) + 1.0 / (k + rank)
        merged[candidate.chunk_id] = _with(existing, sparse_rank=rank, sparse_score=score)

    fused = [_with(merged[cid], rrf_score=score) for cid, score in scores.items()]
    fused.sort(key=lambda c: (-c.rrf_score, c.chunk_id))
    return fused


def _with(candidate: Candidate, **changes: Any) -> Candidate:
    return replace(candidate, **changes)


async def hybrid_search(
    session: AsyncSession,
    settings: Settings,
    question: str,
    *,
    statute_slug: str | None = None,
) -> list[Candidate]:
    """Top-k from each retriever, fused. The candidate set for reranking."""
    limit = settings.RETRIEVAL_TOP_K
    dense = await dense_search(session, settings, question, limit=limit, statute_slug=statute_slug)
    sparse = await sparse_search(session, question, limit=limit, statute_slug=statute_slug)
    fused = reciprocal_rank_fusion(dense, sparse, k=settings.RRF_K)
    logger.info("hybrid_search", dense=len(dense), sparse=len(sparse), fused=len(fused))
    return fused
