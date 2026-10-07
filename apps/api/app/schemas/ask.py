"""Request and response shapes for ``POST /v1/ask``.

Transport is chosen by the ``Accept`` header: ``text/event-stream`` streams,
anything else returns this JSON body. ``turns`` are client-held history — they
arrive in the request body, are used to rewrite the question, and are never
stored.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class Turn(BaseModel):
    """One prior exchange, held by the client. Never stored server-side."""

    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class AskRequest(BaseModel):
    """A question, optionally scoped to one Act."""

    question: str = Field(min_length=3, max_length=2000)
    lang: Literal["en"] = Field(
        default="en", description="Hindi is deferred; 'en' is the only value accepted."
    )
    turns: list[Turn] = Field(
        default_factory=list,
        max_length=6,
        description="Client-held history. Accepted but not yet used (Stage 6).",
    )
    statute_slug: str | None = Field(
        default=None, max_length=120, description="Restrict retrieval to one Act."
    )
    document_ids: list[Annotated[str, Field(min_length=8, max_length=64)]] = Field(
        default_factory=list,
        max_length=3,
        description="Chat only: the caller's own documents from POST /v1/chat/documents "
        "(docs/adr/0005). An unknown, expired or foreign id is a 404.",
    )


class SourceBlock(BaseModel):
    """One section that was placed in the prompt."""

    kind: Literal["statute"] = "statute"
    citation_id: str = Field(description="The id the answer cites, e.g. 'S1046'.")
    section_id: int
    statute: str
    statute_slug: str
    section_no: str
    marginal_note: str | None = None
    origin: Literal["retrieved", "cross_reference"]
    rerank_score: float | None = None
    cited: bool = Field(description="True when the answer actually cited this block.")


class DocumentSourceBlock(BaseModel):
    """One passage of the caller's own document that was placed in the prompt."""

    kind: Literal["document"] = "document"
    citation_id: str = Field(description="The id the answer cites, e.g. 'D1-p4'.")
    document_id: str
    filename: str
    locator_kind: Literal["page", "para"]
    locator: int
    excerpt: str = Field(description="A short excerpt, returned only to the document's owner.")
    rerank_score: float | None = None
    cited: bool


class AskResponse(BaseModel):
    """A grounded answer, or an honest abstention."""

    answered: bool
    abstained: bool
    answer: str
    sources: list[SourceBlock] = Field(
        default_factory=list, description="Empty on an abstention: nothing was sent to a model."
    )
    cited_section_ids: list[int] = Field(default_factory=list)
    top_score: float | None = Field(
        default=None, description="Best cross-encoder score, before the floor."
    )
    score_floor: float
    abstain_reason: str | None = Field(
        default=None,
        description="no_candidates | below_score_floor | citation_* when the model "
        "twice cited something it was not given.",
    )
    citation_violation: bool = Field(
        default=False, description="True when a generated answer had to be corrected."
    )
    model: str | None = None
    prompt_version: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    latency_ms: int
    turns_used: bool = Field(
        default=False, description="True when prior turns changed the question actually searched."
    )
    rewritten_question: str | None = Field(
        default=None, description="The standalone question retrieval ran against, if rewritten."
    )
    document_sources: list[DocumentSourceBlock] = Field(
        default_factory=list, description="Chat only: document passages placed in the prompt."
    )
    cited_document_ids: list[str] = Field(default_factory=list)
