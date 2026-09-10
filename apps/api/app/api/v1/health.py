"""Liveness and corpus freshness.

Deliberately requires no API key and no authentication: it is the first thing
an operator and a deploy probe both reach for.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Response, status
from sqlalchemy import select

from app import __version__
from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_sessionmaker
from app.schemas.health import CorpusHealth, DatabaseHealth, HealthResponse
from app.services.corpus_stats import CorpusStats, get_corpus_stats

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


async def _probe_database() -> tuple[DatabaseHealth, CorpusStats]:
    """Check connectivity and, if the schema exists, count the corpus.

    The catch is deliberately broad. Not every driver failure arrives as a
    ``SQLAlchemyError`` — asyncpg raises its own
    ``InvalidAuthorizationSpecificationError`` straight through on connect, and
    a wrong port surfaces as ``OSError``. A health probe that turns an
    unreachable database into a 500 tells an operator nothing, so anything that
    goes wrong here is reported as ``degraded`` with the exception *class* in
    the ``error`` field: a bug in our own corpus SQL therefore shows up by name
    rather than silently.
    """
    started = time.perf_counter()
    try:
        async with get_sessionmaker()() as session:
            await session.execute(select(1))
            stats = await get_corpus_stats(session)
    except Exception as exc:  # noqa: BLE001 — see the docstring
        # The exception text can contain the DSN, so only the class is reported.
        logger.error("health_database_unreachable", exc_type=type(exc).__name__)
        return (
            DatabaseHealth(connected=False, schema_ready=False, error=type(exc).__name__),
            CorpusStats(schema_ready=False),
        )
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    return (
        DatabaseHealth(connected=True, schema_ready=stats.schema_ready, latency_ms=latency_ms),
        stats,
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness, database connectivity and corpus counts",
    responses={503: {"description": "A required dependency is unavailable."}},
)
async def health(response: Response) -> HealthResponse:
    """Return app version, database state and how much corpus is indexed."""
    settings = get_settings()
    database, stats = await _probe_database()
    if not database.connected:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if database.connected else "degraded",
        version=__version__,
        app_env=settings.APP_ENV,
        database=database,
        corpus=CorpusHealth(
            statutes=stats.statutes,
            sections=stats.sections,
            chunks=stats.chunks,
            last_ingest_at=stats.last_ingest_at,
        ),
    )
