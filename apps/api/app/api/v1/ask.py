"""``POST /v1/ask`` — the grounded answer endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.schemas.ask import AskRequest, AskResponse, SourceBlock
from app.services.answer.pipeline import AskResult, answer_question

router = APIRouter(tags=["ask"])


def _sources(result: AskResult) -> list[SourceBlock]:
    cited = set(result.cited_section_ids)
    return [
        SourceBlock(
            citation_id=block.citation_id,
            section_id=block.section_id,
            statute=block.statute_short_title,
            statute_slug=block.statute_slug,
            section_no=block.section_no,
            marginal_note=block.marginal_note,
            origin=block.origin,
            rerank_score=block.rerank_score,
            cited=block.section_id in cited,
        )
        for block in result.blocks
    ]


@router.post(
    "/ask",
    response_model=AskResponse,
    summary="Ask a question and get an answer grounded in retrieved statute text",
    responses={
        402: {"description": "No provider API key is configured (missing_provider_key)."},
        502: {"description": "The model provider failed."},
    },
)
async def ask(
    payload: AskRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AskResponse:
    """Answer from retrieved text, or abstain.

    A 200 with ``abstained: true`` is a successful outcome, not a failure: it
    means the corpus does not cover the question and no model was called.
    """
    result = await answer_question(
        session, settings, payload.question, statute_slug=payload.statute_slug
    )
    return AskResponse(
        answered=result.answered,
        abstained=result.abstained,
        answer=result.answer,
        sources=_sources(result),
        cited_section_ids=result.cited_section_ids,
        top_score=result.top_score,
        score_floor=result.score_floor,
        abstain_reason=result.abstain_reason,
        citation_violation=result.citation_violation,
        model=result.model,
        prompt_version=result.prompt_version,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        latency_ms=result.latency_ms,
        turns_used=False,
    )
