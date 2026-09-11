"""Response shapes for the corpus read API and search.

Every endpoint here is keyless by spec §06: reading the corpus is free, and
only ``POST /v1/ask`` ever needs a provider key.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field


class StatuteSummary(BaseModel):
    """One Act, as it appears in a list."""

    slug: str
    short_title: str
    long_title: str | None = None
    act_number: str | None = None
    year: int
    jurisdiction: str
    level: str
    ministry: str | None = None
    section_count: int = Field(description="Sections in force, not rows held.")
    as_of_date: dt.date
    is_repealed: bool
    source_portal: str
    source_url: str


class SectionIndexEntry(BaseModel):
    """A section as it appears in an Act's navigation index."""

    id: int
    section_no: str
    marginal_note: str | None = None
    is_omitted: bool


class PartNode(BaseModel):
    """A Part or Chapter in an Act's tree. See ``StatuteDetail.parts_available``."""

    id: int
    kind: str
    number: str | None = None
    heading: str | None = None
    children: list[PartNode] = Field(default_factory=list)
    section_ids: list[int] = Field(default_factory=list)


class StatuteDetail(StatuteSummary):
    """One Act with everything the browser's navigation needs."""

    parts: list[PartNode] = Field(default_factory=list)
    parts_available: bool = Field(
        description=(
            "False when the Part/Chapter tree is genuinely unknown rather than "
            "absent: India Code's API carries no per-section chapter field and "
            "the headings are not present in the section text either."
        )
    )
    sections: list[SectionIndexEntry] = Field(default_factory=list)
    sections_total: int = Field(description="All rows held, including omitted ones.")
    sections_in_force: int


class RelatedSection(BaseModel):
    """A section reachable from this one through ``statute_links``."""

    id: int
    statute_slug: str
    statute_short_title: str
    section_no: str
    marginal_note: str | None = None
    relation: str
    direction: str = Field(description="'outbound' (this cites it) or 'inbound'.")


class SectionDetail(BaseModel):
    """One section, verbatim, plus its provenance and neighbours."""

    id: int
    statute_slug: str
    statute_short_title: str
    section_no: str
    marginal_note: str | None = None
    text: str = Field(description="Verbatim source text. Footnote markers kept inline as [N].")
    footnotes: list[dict[str, Any]] = Field(default_factory=list)
    amendment_note: str | None = None
    commenced_on: dt.date | None = None
    as_of_date: dt.date
    is_omitted: bool
    explanation: str | None = Field(
        default=None, description="Plain-language explanation. Not generated yet (Stage 8)."
    )
    related: list[RelatedSection] = Field(default_factory=list)
    source_url: str


class SearchRequest(BaseModel):
    """A corpus search. No LLM, no key."""

    q: str = Field(min_length=2, max_length=500)
    statute_slug: str | None = Field(default=None, max_length=120)
    limit: int = Field(default=20, ge=1, le=100)
    include_omitted: bool = Field(
        default=False, description="Repealed provisions are excluded by default."
    )


class SearchHit(BaseModel):
    """One ranked section."""

    section_id: int
    statute_slug: str
    statute: str
    section_no: str
    marginal_note: str | None = None
    snippet: str
    score: float = Field(description="Reciprocal Rank Fusion score. Not a probability.")
    dense_rank: int | None = None
    sparse_rank: int | None = None


class SearchResponse(BaseModel):
    """Ranked sections, best first."""

    query: str
    total: int
    hits: list[SearchHit]
    reranked: bool = Field(
        default=False,
        description=(
            "Search returns fusion order and does not run the cross-encoder: "
            "reranking costs tens of seconds on CPU and search must stay fast. "
            "POST /v1/ask does rerank."
        ),
    )
