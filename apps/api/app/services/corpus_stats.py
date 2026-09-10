"""Corpus size and freshness.

Shared by ``GET /v1/health`` and (from Stage 4) ``legaledge-kb stats`` — one
implementation, two callers, per the architecture rules.

Until Stage 1 creates the tables, ``schema_ready`` is False and the counts are
zero. That is a real measurement of an empty deployment, not a placeholder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import column, func, select, table
from sqlalchemy.ext.asyncio import AsyncSession

# Tables the counts read. Declared as lightweight Core constructs so this module
# compiles before the Stage 1 ORM models exist; it moves to the models in Stage 1.
_STATUTES = table("statutes", column("id"))
_SECTIONS = table("statute_sections", column("id"))
_CHUNKS = table("kb_chunks", column("id"))
_INGEST_RUNS = table("ingest_runs", column("id"), column("finished_at"))

REQUIRED_TABLES = ("statutes", "statute_sections", "kb_chunks", "ingest_runs")


@dataclass(frozen=True)
class CorpusStats:
    """A snapshot of what is indexed right now."""

    schema_ready: bool
    statutes: int = 0
    sections: int = 0
    chunks: int = 0
    last_ingest_at: datetime | None = None
    warnings: list[str] = field(default_factory=list)


async def schema_is_ready(session: AsyncSession) -> bool:
    """True when every corpus table exists (i.e. migrations have been applied)."""
    stmt = select(*[func.to_regclass(f"public.{name}") for name in REQUIRED_TABLES])
    row = (await session.execute(stmt)).one()
    return all(value is not None for value in row)


async def get_corpus_stats(session: AsyncSession) -> CorpusStats:
    """Count what is in the corpus, tolerating a database with no schema yet."""
    if not await schema_is_ready(session):
        return CorpusStats(schema_ready=False)

    counts = await session.execute(
        select(
            select(func.count()).select_from(_STATUTES).scalar_subquery(),
            select(func.count()).select_from(_SECTIONS).scalar_subquery(),
            select(func.count()).select_from(_CHUNKS).scalar_subquery(),
            select(func.max(_INGEST_RUNS.c.finished_at)).scalar_subquery(),
        )
    )
    statutes, sections, chunks, last_ingest_at = counts.one()
    return CorpusStats(
        schema_ready=True,
        statutes=statutes,
        sections=sections,
        chunks=chunks,
        last_ingest_at=last_ingest_at,
    )
