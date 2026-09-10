"""Corpus counts, against a real schema and real rows."""

from __future__ import annotations

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.models import IngestRun, KbChunk, Statute, StatuteSection
from app.services.corpus_stats import get_corpus_stats, schema_is_ready
from app.services.kb.section_numbers import section_no_sort


async def test_unmigrated_database_reports_schema_not_ready(empty_database):
    """A deployment before its first migration: honest zeros, not an error."""
    engine = create_async_engine(
        empty_database.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    try:
        async with AsyncSession(engine) as session:
            assert await schema_is_ready(session) is False
            stats = await get_corpus_stats(session)
    finally:
        await engine.dispose()

    assert stats.schema_ready is False
    assert (stats.statutes, stats.sections, stats.chunks) == (0, 0, 0)
    assert stats.last_ingest_at is None


async def test_migrated_but_empty_corpus(db_session):
    assert await schema_is_ready(db_session) is True
    stats = await get_corpus_stats(db_session)
    assert stats.schema_ready is True
    assert (stats.statutes, stats.sections, stats.chunks) == (0, 0, 0)
    assert stats.last_ingest_at is None


async def test_counts_reflect_the_rows_present(db_session):
    statute = Statute(
        slug="dpdp-2023",
        short_title="Digital Personal Data Protection Act, 2023",
        year=2023,
        jurisdiction="India",
        level="central",
        source_portal="meity",
        source_url="https://www.meity.gov.in/example",
        source_sha256="b" * 64,
        as_of_date=dt.date(2026, 8, 1),
    )
    db_session.add(statute)
    await db_session.flush()

    for idx, number in enumerate(["4", "5", "6"]):
        section = StatuteSection(
            statute_id=statute.id,
            section_no=number,
            section_no_sort=section_no_sort(number),
            text_verbatim=f"Section {number} text.",
            as_of_date=statute.as_of_date,
            order_idx=idx,
        )
        db_session.add(section)
        await db_session.flush()
        db_session.add(
            KbChunk(
                section_id=section.id,
                statute_id=statute.id,
                chunk_idx=0,
                heading_prefix="passage: DPDP Act, 2023 — Consent. ",
                text=f"Section {number} text.",
                token_count=11,
            )
        )

    finished = dt.datetime(2026, 9, 10, 12, 0, tzinfo=dt.UTC)
    db_session.add(
        IngestRun(
            source_portal="meity",
            statute_slug="dpdp-2023",
            status="succeeded",
            docs_fetched=1,
            sections_written=3,
            finished_at=finished,
        )
    )
    await db_session.flush()

    stats = await get_corpus_stats(db_session)
    assert stats.schema_ready is True
    assert stats.statutes == 1
    assert stats.sections == 3
    assert stats.chunks == 3
    assert stats.last_ingest_at == finished


async def test_last_ingest_at_is_the_most_recent_finished_run(db_session):
    older = dt.datetime(2026, 7, 1, tzinfo=dt.UTC)
    newer = dt.datetime(2026, 9, 1, tzinfo=dt.UTC)
    for finished in (older, newer):
        db_session.add(
            IngestRun(source_portal="indiacode", status="succeeded", finished_at=finished)
        )
    # A run still in flight must not count as freshness.
    db_session.add(IngestRun(source_portal="indiacode", status="running"))
    await db_session.flush()

    stats = await get_corpus_stats(db_session)
    assert stats.last_ingest_at == newer
