"""One smoke test per corpus read endpoint, against a real migrated database.

Scope decision of 2026-09-11: the four pillars get suites, everything else gets
one test that would fail if the thing were broken. These run against seeded
rows rather than the developer's corpus, so they assert behaviour rather than
whatever India Code happened to publish.

Search itself is not exercised here: it needs embeddings, and embedding a
fixture would load a 1.1 GB model into a unit-test run. Search is verified
against the live corpus instead, and the evidence is in the build log.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Statute, StatuteLink, StatuteSection
from app.services import corpus_read
from app.services.kb.section_numbers import section_no_sort


async def _seed(session: AsyncSession) -> tuple[Statute, dict[str, StatuteSection]]:
    statute = Statute(
        slug="demo-act-1899",
        short_title="Demo Act, 1899",
        long_title="An Act to demonstrate the read API.",
        year=1899,
        jurisdiction="India",
        level="central",
        source_portal="indiacode",
        source_url="https://indiacode.gov.in/demo",
        source_sha256="b" * 64,
        as_of_date=dt.date(2026, 9, 1),
        section_count=2,
    )
    session.add(statute)
    await session.flush()

    sections: dict[str, StatuteSection] = {}
    for idx, (number, omitted) in enumerate([("2", False), ("21-A", False), ("9", True)]):
        section = StatuteSection(
            statute_id=statute.id,
            section_no=number,
            section_no_sort=section_no_sort(number),
            marginal_note=f"Note for {number}",
            text_verbatim=f"The text of section {number}. " * 40,
            as_of_date=statute.as_of_date,
            is_omitted=omitted,
            order_idx=idx,
        )
        session.add(section)
        sections[number] = section
    await session.flush()

    session.add(
        StatuteLink(
            from_section_id=sections["2"].id,
            to_section_id=sections["21-A"].id,
            relation="refers_to",
            raw_text="section 21-A",
        )
    )
    await session.flush()
    return statute, sections


async def test_statutes_list_and_detail_report_real_counts(db_session):
    statute, _ = await _seed(db_session)

    listed = await corpus_read.list_statutes(db_session)
    assert [s.slug for s in listed] == ["demo-act-1899"]

    total, in_force = await corpus_read.section_counts(db_session, statute.id)
    assert (total, in_force) == (3, 2), "omitted sections are held but not in force"

    index = await corpus_read.section_index(db_session, statute.id)
    assert [s.section_no for s in index] == ["2", "9", "21-A"], "citation order, not text order"
    assert any(s.is_omitted for s in index), "a reader must see the gap, not a hole"


async def test_a_section_resolves_however_the_citation_spells_it(db_session):
    """21A, 21-A and 21 A are one provision; a reader typing the form they saw
    in a judgment should not get a 404."""
    await _seed(db_session)
    for spelling in ("21-A", "21A", "21 a"):
        section, statute = await corpus_read.get_section_by_number(
            db_session, "demo-act-1899", spelling
        )
        assert section.section_no == "21-A"
        assert statute.slug == "demo-act-1899"


async def test_unknown_act_and_unknown_section_are_typed_not_found(db_session):
    from app.core.errors import NotFoundError

    await _seed(db_session)
    for call in (
        corpus_read.get_statute(db_session, "no-such-act"),
        corpus_read.get_section_by_number(db_session, "demo-act-1899", "999"),
        corpus_read.get_section_by_id(db_session, 10_000_000),
    ):
        try:
            await call
        except NotFoundError as exc:
            assert exc.http_status == 404
        else:  # pragma: no cover - the call must raise
            raise AssertionError("expected NotFoundError")


async def test_related_sections_are_reported_in_both_directions(db_session):
    """The edges are stored one way; a reader of a definition needs to know
    what points at it."""
    _, sections = await _seed(db_session)

    outbound = await corpus_read.related_sections(db_session, sections["2"].id)
    assert [(r.direction, r.section.section_no) for r in outbound] == [("outbound", "21-A")]

    inbound = await corpus_read.related_sections(db_session, sections["21-A"].id)
    assert [(r.direction, r.section.section_no) for r in inbound] == [("inbound", "2")]


def test_snippets_are_cut_at_a_word_boundary():
    from app.services.corpus_read import _snippet

    text = "Every  agreement\nby which any one is restrained " * 20
    snippet = _snippet(text, limit=60)
    assert len(snippet) <= 61
    assert snippet.endswith("…")
    assert "  " not in snippet, "whitespace is normalised"
    assert _snippet("short text") == "short text", "no ellipsis when nothing was cut"


def test_a_query_that_is_a_citation_is_recognised():
    from app.services.corpus_read import CITATION_QUERY

    for query, expected in [
        ("section 27", "27"),
        ("s. 17", "17"),
        ("what does section 43A say", "43A"),
        ("ss 3", "3"),
    ]:
        match = CITATION_QUERY.search(query)
        assert match is not None and match.group(1) == expected
    assert CITATION_QUERY.search("what is a contract") is None
