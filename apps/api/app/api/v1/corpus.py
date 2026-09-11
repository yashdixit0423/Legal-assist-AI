"""The corpus read API and search — spec §06.

Every route here is keyless on purpose: reading the law is free, and only
``POST /v1/ask`` spends anyone's money.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import Statute, StatuteSection
from app.db.session import get_session
from app.schemas.corpus import (
    RelatedSection,
    SearchHit,
    SearchRequest,
    SearchResponse,
    SectionDetail,
    SectionIndexEntry,
    StatuteDetail,
    StatuteSummary,
)
from app.services import corpus_read

router = APIRouter(tags=["corpus"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _summary(statute: Statute) -> StatuteSummary:
    return StatuteSummary(
        slug=statute.slug,
        short_title=statute.short_title,
        long_title=statute.long_title,
        act_number=statute.act_number,
        year=statute.year,
        jurisdiction=statute.jurisdiction,
        level=statute.level,
        ministry=statute.ministry,
        section_count=statute.section_count,
        as_of_date=statute.as_of_date,
        is_repealed=statute.is_repealed,
        source_portal=statute.source_portal,
        source_url=statute.source_url,
    )


async def _detail(
    session: AsyncSession, section: StatuteSection, statute: Statute
) -> SectionDetail:
    related = await corpus_read.related_sections(session, section.id)
    return SectionDetail(
        id=section.id,
        statute_slug=statute.slug,
        statute_short_title=statute.short_title,
        section_no=section.section_no,
        marginal_note=section.marginal_note,
        text=section.text_verbatim,
        footnotes=list(section.footnotes or []),
        amendment_note=section.amendment_note,
        commenced_on=section.commenced_on,
        as_of_date=section.as_of_date,
        is_omitted=section.is_omitted,
        explanation=None,
        related=[
            RelatedSection(
                id=item.section.id,
                statute_slug=item.statute.slug,
                statute_short_title=item.statute.short_title,
                section_no=item.section.section_no,
                marginal_note=item.section.marginal_note,
                relation=item.relation,
                direction=item.direction,
            )
            for item in related
        ],
        source_url=statute.source_url,
    )


@router.get("/statutes", response_model=list[StatuteSummary], summary="List indexed Acts")
async def list_statutes(session: SessionDep) -> list[StatuteSummary]:
    """Every Act in the corpus. No key required."""
    return [_summary(statute) for statute in await corpus_read.list_statutes(session)]


@router.get(
    "/statutes/{slug}",
    response_model=StatuteDetail,
    summary="One Act, with its section index",
    responses={404: {"description": "No indexed Act with that slug."}},
)
async def get_statute(slug: str, session: SessionDep) -> StatuteDetail:
    """One Act and everything needed to navigate it.

    ``parts`` is empty and ``parts_available`` is false: India Code's API
    exposes no per-section chapter field, and the headings are not in the
    section text either, so the tree is genuinely unknown rather than merely
    not loaded. Saying so in the payload is better than an empty list a client
    would read as "this Act has no chapters".
    """
    statute = await corpus_read.get_statute(session, slug)
    sections = await corpus_read.section_index(session, statute.id)
    total, in_force = await corpus_read.section_counts(session, statute.id)
    return StatuteDetail(
        **_summary(statute).model_dump(),
        parts=[],
        parts_available=False,
        sections=[
            SectionIndexEntry(
                id=section.id,
                section_no=section.section_no,
                marginal_note=section.marginal_note,
                is_omitted=section.is_omitted,
            )
            for section in sections
        ],
        sections_total=total,
        sections_in_force=in_force,
    )


@router.get(
    "/statutes/{slug}/sections/{section_no}",
    response_model=SectionDetail,
    summary="One section, verbatim",
    responses={404: {"description": "No such Act or section."}},
)
async def get_section_by_number(slug: str, section_no: str, session: SessionDep) -> SectionDetail:
    """``21A``, ``21-A`` and ``21 A`` all resolve to the same provision."""
    section, statute = await corpus_read.get_section_by_number(session, slug, section_no)
    return await _detail(session, section, statute)


@router.get(
    "/sections/{section_id}",
    response_model=SectionDetail,
    summary="One section by id — what a citation chip resolves against",
    responses={404: {"description": "No section with that id."}},
)
async def get_section(section_id: int, session: SessionDep) -> SectionDetail:
    """The id form used by ``[S<section_id>]`` citations in an answer."""
    section, statute = await corpus_read.get_section_by_id(session, section_id)
    return await _detail(session, section, statute)


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Keyword and semantic search across the corpus",
)
async def search(
    payload: SearchRequest, session: SessionDep, settings: SettingsDep
) -> SearchResponse:
    """Hybrid search, one row per section. No LLM, no key, no reranker."""
    hits = await corpus_read.search_corpus(
        session,
        settings,
        payload.q,
        statute_slug=payload.statute_slug,
        limit=payload.limit,
        include_omitted=payload.include_omitted,
    )
    return SearchResponse(
        query=payload.q,
        total=len(hits),
        hits=[
            SearchHit(
                section_id=hit.candidate.section_id,
                statute_slug=hit.candidate.statute_slug,
                statute=hit.candidate.statute_short_title,
                section_no=hit.candidate.section_no,
                marginal_note=hit.candidate.marginal_note,
                snippet=hit.snippet,
                score=hit.score,
                dense_rank=hit.candidate.dense_rank,
                sparse_rank=hit.candidate.sparse_rank,
            )
            for hit in hits
        ],
    )


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Search by query string — the GET form, for links and caching",
)
async def search_get(
    session: SessionDep,
    settings: SettingsDep,
    q: Annotated[str, Query(min_length=2, max_length=500)],
    statute_slug: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SearchResponse:
    """Same search, addressable by URL so a result page can be linked."""
    return await search(
        SearchRequest(q=q, statute_slug=statute_slug, limit=limit), session, settings
    )
