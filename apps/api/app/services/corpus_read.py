"""Reading the corpus: Acts, sections, and search.

No model, no key, no generation. Everything here is a query against what the
pipeline already wrote, which is why spec §06 makes all of it keyless.

Search reuses :mod:`app.services.retrieval.hybrid` rather than reimplementing
retrieval — the same dense + sparse + RRF that feeds ``/v1/ask``, minus the
cross-encoder. That omission is deliberate and surfaced in the response as
``reranked: false``: reranking costs 30-50 seconds on CPU, and a search box
that takes a minute is not a search box.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import NotFoundError
from app.db.models import Statute, StatuteLink, StatuteSection
from app.services.kb.crossref import normalise_section_no
from app.services.retrieval.hybrid import Candidate, hybrid_search

SNIPPET_CHARS = 320

# "section 27", "s. 17", "ss 3" -- a query that is a citation rather than a question.
CITATION_QUERY = re.compile(
    r"\b(?:sections?|ss?\.?)\s*(\d{1,3}(?:-?[A-Za-z]{1,2})?)\b", re.IGNORECASE
)


# --- Acts -------------------------------------------------------------------


async def list_statutes(session: AsyncSession) -> list[Statute]:
    """Every indexed Act, oldest first — the order an index is read in."""
    return list(
        (await session.execute(select(Statute).order_by(Statute.year, Statute.short_title)))
        .scalars()
        .all()
    )


async def get_statute(session: AsyncSession, slug: str) -> Statute:
    statute = (
        await session.execute(select(Statute).where(Statute.slug == slug))
    ).scalar_one_or_none()
    if statute is None:
        raise NotFoundError(f"No indexed Act with slug {slug!r}.", details={"slug": slug})
    return statute


async def section_index(session: AsyncSession, statute_id: int) -> list[StatuteSection]:
    """Every section of an Act in citation order, for navigation.

    Omitted provisions are included here, unlike in search: a reader browsing
    an Act needs to see that s.66A exists and is omitted, or the numbering
    looks broken.
    """
    return list(
        (
            await session.execute(
                select(StatuteSection)
                .where(StatuteSection.statute_id == statute_id)
                .order_by(StatuteSection.section_no_sort)
            )
        )
        .scalars()
        .all()
    )


async def section_counts(session: AsyncSession, statute_id: int) -> tuple[int, int]:
    """(rows held, sections in force)."""
    total, in_force = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(StatuteSection.is_omitted.is_(False)),
            ).where(StatuteSection.statute_id == statute_id)
        )
    ).one()
    return int(total), int(in_force)


# --- sections ---------------------------------------------------------------


def _section_query() -> Select[tuple[StatuteSection, Statute]]:
    return select(StatuteSection, Statute).join(Statute, Statute.id == StatuteSection.statute_id)


async def get_section_by_id(
    session: AsyncSession, section_id: int
) -> tuple[StatuteSection, Statute]:
    """What a citation chip resolves against."""
    row = (
        await session.execute(_section_query().where(StatuteSection.id == section_id))
    ).one_or_none()
    if row is None:
        raise NotFoundError(f"No section with id {section_id}.", details={"section_id": section_id})
    return row[0], row[1]


async def get_section_by_number(
    session: AsyncSession, slug: str, section_no: str
) -> tuple[StatuteSection, Statute]:
    """Look a section up the way a citation writes it.

    Matched on the normalised number, so ``21A``, ``21-A`` and ``21 A`` all
    reach the same provision — legal citations are not consistent about this
    and a reader typing the form they saw in a judgment should not get a 404.
    """
    statute = await get_statute(session, slug)
    wanted = normalise_section_no(section_no)
    for section in await section_index(session, statute.id):
        if normalise_section_no(section.section_no) == wanted:
            return section, statute
    raise NotFoundError(
        f"{statute.short_title} has no section {section_no!r}.",
        details={"slug": slug, "section_no": section_no},
    )


@dataclass(frozen=True)
class Related:
    """One neighbour of a section, in either direction."""

    section: StatuteSection
    statute: Statute
    relation: str
    direction: str


async def related_sections(session: AsyncSession, section_id: int) -> list[Related]:
    """Sections this one cites, and sections that cite it.

    Both directions, because "what else points here?" is the question a reader
    asks about a definition, and the edges are already stored one-way only.
    """
    outbound = (
        await session.execute(
            _section_query()
            .add_columns(StatuteLink.relation)
            .join(StatuteLink, StatuteLink.to_section_id == StatuteSection.id)
            .where(StatuteLink.from_section_id == section_id)
        )
    ).all()
    inbound = (
        await session.execute(
            _section_query()
            .add_columns(StatuteLink.relation)
            .join(StatuteLink, StatuteLink.from_section_id == StatuteSection.id)
            .where(StatuteLink.to_section_id == section_id)
        )
    ).all()
    seen: set[tuple[int, str]] = set()
    out: list[Related] = []
    for rows, direction in ((outbound, "outbound"), (inbound, "inbound")):
        for section, statute, relation in rows:
            key = (section.id, direction)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                Related(section=section, statute=statute, relation=relation, direction=direction)
            )
    out.sort(key=lambda r: (r.direction, r.statute.short_title, r.section.section_no_sort))
    return out


# --- search -----------------------------------------------------------------


@dataclass(frozen=True)
class Hit:
    """One ranked section, collapsed from however many chunks matched."""

    candidate: Candidate
    score: float
    snippet: str


def _snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    """The head of the matched chunk, cut at a word boundary.

    Deliberately not ``ts_headline``: half of these hits come from the dense
    retriever and contain none of the query's words, so highlighting would
    produce a fragment for lexical matches and an arbitrary one for semantic
    matches — the same field meaning two different things.
    """
    body = " ".join(text.split())
    if len(body) <= limit:
        return body
    cut = body[:limit].rsplit(" ", 1)[0]
    return f"{cut}…"


async def search_corpus(
    session: AsyncSession,
    settings: Settings,
    query: str,
    *,
    statute_slug: str | None = None,
    limit: int = 20,
    include_omitted: bool = False,
) -> list[Hit]:
    """Hybrid search, collapsed to one row per section.

    A long section is several chunks, and three chunks of Registration Act s.17
    are one answer to the reader, not three results. The best-scoring chunk
    wins and supplies the snippet.
    """
    candidates = await hybrid_search(session, settings, query, statute_slug=statute_slug)
    if not candidates:
        return []

    best: dict[int, Candidate] = {}
    for candidate in candidates:
        current = best.get(candidate.section_id)
        if current is None or candidate.rrf_score > current.rrf_score:
            best[candidate.section_id] = candidate

    if not include_omitted:
        live = set(
            (
                await session.execute(
                    select(StatuteSection.id).where(
                        StatuteSection.id.in_(best), StatuteSection.is_omitted.is_(False)
                    )
                )
            )
            .scalars()
            .all()
        )
        best = {sid: c for sid, c in best.items() if sid in live}

    ranked = sorted(best.values(), key=lambda c: (-c.rrf_score, c.section_id))[:limit]
    return [
        Hit(candidate=candidate, score=candidate.rrf_score, snippet=_snippet(candidate.text))
        for candidate in ranked
    ]


async def search_by_citation(
    session: AsyncSession, query: str, *, limit: int = 5
) -> list[tuple[StatuteSection, Statute]]:
    """Resolve a query that is itself a citation, e.g. "section 27" or "s. 17".

    Cheap, exact, and run alongside the ranked search: a user who types a
    section number wants that section, not the twenty provisions that mention
    it, and no amount of retrieval tuning reliably delivers that.
    """
    match = CITATION_QUERY.search(query)
    if not match:
        return []
    normalised = func.lower(
        func.regexp_replace(StatuteSection.section_no, r"[^0-9A-Za-z]", "", "g")
    )
    rows = (
        await session.execute(
            _section_query()
            .where(normalised == normalise_section_no(match.group(1)))
            .order_by(Statute.year)
            .limit(limit)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]
