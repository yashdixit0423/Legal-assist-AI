"""Async engine and session lifecycle.

The engine is created once per process on first use and disposed by the app
lifespan. Nothing here reads the environment directly — settings arrive as an
argument so the CLI and tests can drive the same code with their own values.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import Engine
from sqlalchemy import create_engine as _create_sync_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def create_engine(settings: Settings) -> AsyncEngine:
    """Build a fresh async engine from settings (no global state touched)."""
    return create_async_engine(
        settings.database_url_async,
        echo=settings.DB_ECHO,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_POOL_MAX_OVERFLOW,
        pool_pre_ping=True,
        future=True,
    )


def get_engine() -> AsyncEngine:
    """Return the process-wide engine, creating it on first call."""
    global _engine, _sessionmaker  # noqa: PLW0603 — one engine per process
    if _engine is None:
        _engine = create_engine(get_settings())
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory."""
    get_engine()
    assert _sessionmaker is not None  # noqa: S101 — set by get_engine()
    return _sessionmaker


async def dispose_engine() -> None:
    """Close the pool. Called from the app lifespan on shutdown."""
    global _engine, _sessionmaker  # noqa: PLW0603
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session that always closes."""
    async with get_sessionmaker()() as session:
        yield session


# --- synchronous access, for the corpus pipeline ---------------------------
# The API path is async throughout; the CLI is a batch job and psycopg is
# simpler there (it is also the driver Alembic uses).


def create_sync_engine(settings: Settings) -> Engine:
    """Build a psycopg engine for the pipeline."""
    return _create_sync_engine(
        settings.database_url_sync, echo=settings.DB_ECHO, future=True
    )


def sync_session(settings: Settings) -> Session:
    """A new synchronous session. The caller owns commit and close."""
    return Session(bind=create_sync_engine(settings), expire_on_commit=False)
