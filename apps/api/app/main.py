"""Application factory and process lifespan.

Nothing in this module contains business logic — it wires configuration,
logging, middleware, error handling, metrics and routers together.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app import __version__
from app.api.v1 import api_router
from app.core.config import Settings, get_settings
from app.core.error_handlers import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.core.ratelimit import warn_if_not_shared
from app.db.session import dispose_engine

logger = get_logger(__name__)

DESCRIPTION = (
    "Grounded question answering over Indian central statutes. Corpus reads "
    "require no credentials; POST /v1/ask uses the caller's own provider key."
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Log a startup line, then guarantee the database pool is closed."""
    settings: Settings = app.state.settings
    logger.info(
        "api_starting",
        version=__version__,
        app_env=settings.APP_ENV,
        embed_model=settings.EMBED_MODEL,
        rerank_model=settings.RERANK_MODEL,
        device=settings.MODEL_DEVICE,
    )
    warn_if_not_shared(settings)
    if settings.WARM_MODELS_ON_START:
        await _warm_models(settings)
    try:
        yield
    finally:
        await dispose_engine()
        logger.info("api_stopped")


async def _warm_models(settings: Settings) -> None:
    """Load the models before the first request, off the request path.

    Measured in Stage 5: the first search after a cold start took 4.9 s and
    every later one 76-87 ms, because the embedding model loads lazily. That
    cost belongs to start-up, where a deploy probe can absorb it, not to
    whichever user arrives first. Loading is blocking and CPU-bound, so it runs
    in a worker thread rather than stalling the event loop.
    """
    import anyio

    from app.services.kb.embedding import get_encoder
    from app.services.retrieval.rerank import get_reranker

    for name, load in (("embed", get_encoder), ("rerank", get_reranker)):
        try:
            await anyio.to_thread.run_sync(load, settings)
            logger.info("model_warmed", model=name)
        except Exception as exc:  # noqa: BLE001 — a cold model is not fatal
            # Weights missing or no network: the API still serves health and
            # the corpus reads, and the first ask pays the load cost.
            logger.warning("model_warm_failed", model=name, exc_type=type(exc).__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the ASGI application.

    Settings are resolved here so a missing environment variable fails at
    process start with a readable message rather than on the first request.
    """
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="LegalEdge Knowledge Base API",
        description=DESCRIPTION,
        version=__version__,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # CORS before anything else, so a preflight never reaches the app.
    #
    # expose_headers matters more than it looks: a browser hides every response
    # header from JavaScript except a short safelist, so without naming the
    # rate-limit headers here the client can read the body of a response but
    # not how many questions the user has left. That failure is silent — the
    # request succeeds and the counter simply never appears.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,  # bearer tokens, not cookies
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "If-None-Match"],
        expose_headers=[
            "ETag",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
        ],
    )
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router)

    Instrumentator(
        should_group_status_codes=True,
        excluded_handlers=["/metrics"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    return app


app = create_app()
