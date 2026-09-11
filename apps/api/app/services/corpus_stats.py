"""Corpus size and freshness.

Shared by ``GET /v1/health`` and ``legaledge-kb stats`` — one implementation,
two callers, per the architecture rules. (The CLI reaches the same counts
through the synchronous :func:`app.services.kb.index.index_stats`; this module
is the async half for the request path.)

``schema_ready`` is False on a database that has not been migrated. That is a
real measurement of an empty deployment, not a placeholder: the counts are then
structurally zero because the tables do not exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestRun, KbChunk, Statute, StatuteLink, StatuteSection
from app.services.kb.index import VECTOR_INDEX

# Every table the counts read. Checked with to_regclass rather than caught as an
# error, because a failed query inside a transaction poisons the transaction.
COUNTED_TABLES = (
    Statute.__tablename__,
    StatuteSection.__tablename__,
    KbChunk.__tablename__,
    StatuteLink.__tablename__,
    IngestRun.__tablename__,
)


@dataclass(frozen=True)
class CorpusStats:
    """A snapshot of what is indexed right now."""

    schema_ready: bool
    statutes: int = 0
    sections: int = 0
    chunks: int = 0
    chunks_embedded: int = 0
    links: int = 0
    vector_index_ready: bool = False
    last_ingest_at: datetime | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def retrieval_ready(self) -> bool:
        """True when every chunk has a vector and the HNSW index is present.

        False on a corpus that is parsed but not yet indexed, and false in the
        middle of a bulk embed — which is exactly when an operator needs to be
        told that dense retrieval will be slow or wrong.
        """
        return self.chunks > 0 and self.chunks_embedded == self.chunks and self.vector_index_ready


async def schema_is_ready(session: AsyncSession) -> bool:
    """True when every corpus table exists (i.e. migrations have been applied)."""
    stmt = select(*[func.to_regclass(f"public.{name}") for name in COUNTED_TABLES])
    row = (await session.execute(stmt)).one()
    return all(value is not None for value in row)


async def get_corpus_stats(session: AsyncSession) -> CorpusStats:
    """Count what is in the corpus, tolerating a database with no schema yet."""
    if not await schema_is_ready(session):
        return CorpusStats(schema_ready=False)

    counts = await session.execute(
        select(
            select(func.count()).select_from(Statute).scalar_subquery(),
            select(func.count()).select_from(StatuteSection).scalar_subquery(),
            select(func.count()).select_from(KbChunk).scalar_subquery(),
            select(func.count())
            .select_from(KbChunk)
            .where(KbChunk.embedding.is_not(None))
            .scalar_subquery(),
            select(func.count()).select_from(StatuteLink).scalar_subquery(),
            func.to_regclass(f"public.{VECTOR_INDEX}").is_not(None),
            select(func.max(IngestRun.finished_at)).scalar_subquery(),
        )
    )
    statutes, sections, chunks, embedded, links, index_ready, last_ingest_at = counts.one()
    return CorpusStats(
        schema_ready=True,
        statutes=statutes,
        sections=sections,
        chunks=chunks,
        chunks_embedded=embedded,
        links=links,
        vector_index_ready=bool(index_ready),
        last_ingest_at=last_ingest_at,
    )
