"""Citation ordering, asserted by PostgreSQL rather than by Python.

The sort that matters in production is the one the database performs through
``ix_statute_sections_citation_order``. These tests insert real rows and read
them back with ``ORDER BY``.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KbChunk, Statute, StatuteSection
from app.services.kb.section_numbers import section_no_sort

# Deliberately inserted in a scrambled order so the ORDER BY does the work.
INSERT_ORDER = [
    "10",
    "2A",
    "9",
    "371",
    "21A",
    "1",
    "45ZF",
    "2",
    "100",
    "14B",
    "21",
    "14",
    "3",
    "14A",
    "2AA",
    "99",
]
LEGAL_ORDER = [
    "1",
    "2",
    "2A",
    "2AA",
    "3",
    "9",
    "10",
    "14",
    "14A",
    "14B",
    "21",
    "21A",
    "45ZF",
    "99",
    "100",
    "371",
]


async def _make_statute(session: AsyncSession, slug: str = "test-act-1872") -> Statute:
    statute = Statute(
        slug=slug,
        short_title="Test Act, 1872",
        year=1872,
        jurisdiction="India",
        level="central",
        source_portal="indiacode",
        source_url="https://www.indiacode.nic.in/example",
        source_sha256="a" * 64,
        as_of_date=dt.date(2026, 8, 1),
    )
    session.add(statute)
    await session.flush()
    return statute


async def _add_sections(session: AsyncSession, statute: Statute, numbers: list[str]) -> None:
    for idx, number in enumerate(numbers):
        session.add(
            StatuteSection(
                statute_id=statute.id,
                section_no=number,
                section_no_sort=section_no_sort(number),
                marginal_note=f"Marginal note for {number}",
                text_verbatim=f"Text of section {number}.",
                as_of_date=statute.as_of_date,
                order_idx=idx,
            )
        )
    await session.flush()


async def test_database_orders_sections_the_way_a_lawyer_reads_them(db_session):
    statute = await _make_statute(db_session)
    await _add_sections(db_session, statute, INSERT_ORDER)

    rows = await db_session.execute(
        select(StatuteSection.section_no)
        .where(StatuteSection.statute_id == statute.id)
        .order_by(StatuteSection.section_no_sort)
    )
    assert list(rows.scalars()) == LEGAL_ORDER


async def test_ordering_by_the_rendered_number_is_wrong(db_session):
    """Proof that the sort column earns its place: without it, 10 precedes 9."""
    statute = await _make_statute(db_session)
    await _add_sections(db_session, statute, INSERT_ORDER)

    rows = await db_session.execute(
        select(StatuteSection.section_no)
        .where(StatuteSection.statute_id == statute.id)
        .order_by(StatuteSection.section_no)
    )
    naive = list(rows.scalars())
    assert naive != LEGAL_ORDER
    assert naive.index("10") < naive.index("9")


async def test_ordering_is_independent_of_insertion_order(db_session):
    statute = await _make_statute(db_session)
    await _add_sections(db_session, statute, list(reversed(INSERT_ORDER)))

    rows = await db_session.execute(
        select(StatuteSection.section_no)
        .where(StatuteSection.statute_id == statute.id)
        .order_by(StatuteSection.section_no_sort)
    )
    assert list(rows.scalars()) == LEGAL_ORDER


async def test_two_renderings_of_one_provision_share_a_position(db_session):
    """'21-A' from one portal and '21A' from another are the same provision."""
    statute = await _make_statute(db_session)
    await _add_sections(db_session, statute, ["21", "21-A", "22"])

    rows = await db_session.execute(
        select(StatuteSection.section_no, StatuteSection.section_no_sort)
        .where(StatuteSection.statute_id == statute.id)
        .order_by(StatuteSection.section_no_sort)
    )
    ordered = list(rows.all())
    assert [row[0] for row in ordered] == ["21", "21-A", "22"]
    assert ordered[1][1] == section_no_sort("21A")


async def test_the_citation_index_is_the_one_postgres_chooses(db_session):
    """A sequential scan on a 4,000-section corpus would still pass the tests."""
    statute = await _make_statute(db_session)
    await _add_sections(db_session, statute, INSERT_ORDER)
    await db_session.execute(text("set local enable_seqscan = off"))

    plan = await db_session.execute(
        text(
            "explain (format text) select section_no from statute_sections "
            "where statute_id = :sid order by section_no_sort"
        ),
        {"sid": statute.id},
    )
    rendered = "\n".join(row[0] for row in plan)
    assert "ix_statute_sections_citation_order" in rendered


async def test_section_numbers_are_unique_within_a_statute(db_session):
    """A duplicate section number means the parser merged or repeated a provision."""
    statute = await _make_statute(db_session)
    await _add_sections(db_session, statute, ["7"])
    # A distinct order_idx, so this can only trip the section_no constraint.
    db_session.add(
        StatuteSection(
            statute_id=statute.id,
            section_no="7",
            section_no_sort=section_no_sort("7"),
            text_verbatim="A second, conflicting section 7.",
            as_of_date=statute.as_of_date,
            order_idx=99,
        )
    )
    with pytest.raises(IntegrityError, match="uq_statute_sections_no"):
        await db_session.flush()


async def test_the_same_section_number_may_exist_in_two_statutes(db_session):
    first = await _make_statute(db_session, slug="first-act-1872")
    second = await _make_statute(db_session, slug="second-act-1882")
    await _add_sections(db_session, first, ["7"])
    await _add_sections(db_session, second, ["7"])
    count = await db_session.scalar(
        select(StatuteSection.id).where(StatuteSection.section_no == "7").limit(2)
    )
    assert count is not None


async def test_deleting_a_statute_removes_its_sections_and_chunks(db_session):
    statute = await _make_statute(db_session)
    await _add_sections(db_session, statute, ["1", "2"])
    section = await db_session.scalar(
        select(StatuteSection).where(StatuteSection.statute_id == statute.id).limit(1)
    )
    assert section is not None
    db_session.add(
        KbChunk(
            section_id=section.id,
            statute_id=statute.id,
            chunk_idx=0,
            heading_prefix="passage: Test Act, 1872 — Marginal note for 1. ",
            text="Text of section 1.",
            token_count=12,
        )
    )
    await db_session.flush()

    await db_session.execute(delete(Statute).where(Statute.id == statute.id))
    await db_session.flush()

    assert (
        await db_session.scalar(
            select(StatuteSection.id).where(StatuteSection.statute_id == statute.id)
        )
        is None
    )
    assert (
        await db_session.scalar(select(KbChunk.id).where(KbChunk.statute_id == statute.id)) is None
    )


async def test_a_chunk_must_carry_a_positive_token_count(db_session):
    statute = await _make_statute(db_session)
    await _add_sections(db_session, statute, ["1"])
    section = await db_session.scalar(
        select(StatuteSection).where(StatuteSection.statute_id == statute.id).limit(1)
    )
    assert section is not None
    db_session.add(
        KbChunk(
            section_id=section.id,
            statute_id=statute.id,
            chunk_idx=0,
            heading_prefix="passage: x ",
            text="y",
            token_count=0,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
