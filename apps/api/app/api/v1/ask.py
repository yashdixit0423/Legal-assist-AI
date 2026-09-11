"""``POST /v1/ask`` — the grounded answer endpoint, streaming or buffered.

Transport is chosen by the ``Accept`` header: ``text/event-stream`` gets SSE,
anything else gets the JSON body Stage 4 shipped. Both run the identical
pipeline — same gate, same packed blocks, same citation validation — because a
grounding guarantee that holds on one transport and not the other is not a
guarantee.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from sse_starlette.sse import EventSourceResponse

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import get_sessionmaker
from app.schemas.ask import AskRequest, AskResponse, SourceBlock
from app.services.answer import pipeline
from app.services.answer.pipeline import AskResult

router = APIRouter(tags=["ask"])
logger = get_logger(__name__)


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


def _turns(payload: AskRequest) -> list[dict[str, str]]:
    """Prior turns arrive in the request body and are never stored."""
    return [{"role": turn.role, "content": turn.content} for turn in payload.turns]


@router.post(
    "/ask",
    response_model=AskResponse,
    summary="Ask a question and get an answer grounded in retrieved statute text",
    responses={
        200: {
            "content": {
                "application/json": {},
                "text/event-stream": {
                    "schema": {
                        "type": "string",
                        "description": (
                            "SSE. Events: sources, token, citation, invalidated, "
                            "abstain, error, done."
                        ),
                    }
                },
            }
        },
        402: {"description": "No provider API key is configured (missing_provider_key)."},
        502: {"description": "The model provider failed."},
    },
)
async def ask(
    payload: AskRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    accept: Annotated[str, Header()] = "application/json",
) -> AskResponse | EventSourceResponse:
    """Answer from retrieved text, or abstain.

    A 200 with ``abstained: true`` is a successful outcome, not a failure: the
    corpus does not cover the question and no model was called.
    """
    if "text/event-stream" in accept.lower():
        return EventSourceResponse(
            _event_stream(payload, request, settings),
            ping=15,
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    # The request-scoped session is used for retrieval; the log row gets its
    # own so a logging failure can never roll back nothing-in-particular.
    async with get_sessionmaker()() as session:
        result = await pipeline.answer_question(
            session,
            settings,
            payload.question,
            turns=_turns(payload),
            statute_slug=payload.statute_slug,
        )
    await _log(result)
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
        turns_used=bool(result.rewritten_question),
        rewritten_question=result.rewritten_question,
    )


async def _event_stream(
    payload: AskRequest, request: Request, settings: Settings
) -> AsyncIterator[dict[str, str]]:
    """Adapt pipeline events onto the SSE wire format.

    Disconnection is checked between events: a client that closes the tab must
    not leave the provider streaming into nothing on their key.
    """
    async with get_sessionmaker()() as session:
        final: AskResult | None = None
        try:
            async for event, result in pipeline.stream_answer(
                session,
                settings,
                payload.question,
                turns=_turns(payload),
                statute_slug=payload.statute_slug,
            ):
                if await request.is_disconnected():
                    logger.info("ask_stream_client_gone")
                    break
                final = result or final
                yield {"event": event.name, "data": json.dumps(event.data)}
        except Exception as exc:  # noqa: BLE001 — the stream owns its errors
            code = getattr(exc, "code", "internal_error")
            logger.error("ask_stream_failed", exc_type=type(exc).__name__, code=code)
            yield {
                "event": "error",
                "data": json.dumps({"code": code, "message": str(getattr(exc, "message", ""))}),
            }
    if final is not None:
        await _log(final)


async def _log(result: AskResult) -> None:
    """Write the anonymous ask_logs row. Never fails the request."""
    try:
        async with get_sessionmaker()() as session:
            await pipeline.write_ask_log(session, result)
    except Exception as exc:  # noqa: BLE001 — evaluation data is not the product
        logger.error("ask_log_write_failed", exc_type=type(exc).__name__)
