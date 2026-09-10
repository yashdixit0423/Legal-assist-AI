"""Application factory and process lifespan.

Nothing in this module contains business logic — it wires configuration,
logging, middleware, error handling, metrics and routers together.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app import __version__
from app.api.v1 import api_router
from app.core.config import Settings, get_settings
from app.core.error_handlers import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
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
    )
    try:
        yield
    finally:
        await dispose_engine()
        logger.info("api_stopped")


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

    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router)

    Instrumentator(
        should_group_status_codes=True,
        excluded_handlers=["/metrics"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    return app


app = create_app()
