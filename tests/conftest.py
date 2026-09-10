"""Test-wide fixtures.

The environment is populated at import time, before any ``app`` module is
loaded, because :func:`app.core.config.get_settings` deliberately refuses to
build settings out of an incomplete environment.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

REPO_ROOT = Path(__file__).resolve().parents[1]

# Deterministic, obviously-fake values. Real deployments read these from .env.
TEST_ENV = {
    "APP_ENV": "ci",
    "LOG_JSON": "true",
    "DATABASE_URL": "postgresql://legaledge:legaledge@localhost:5432/legaledge_test",
    "JWT_SECRET": "test-only-secret-value-of-at-least-32-characters",
    "CREDENTIAL_ENC_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "CORPUS_ARCHIVE_DIR": str(REPO_ROOT / "var" / "corpus_archive"),
}
for key, value in TEST_ENV.items():
    os.environ.setdefault(key, value)


@pytest.fixture
def settings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """Give a test an isolated environment plus a cleared settings cache."""
    from app.core.config import reset_settings_cache

    for key in list(os.environ):
        if key in TEST_ENV or key.startswith(("EMBED_", "RERANK_", "FETCH_", "LANGFUSE_")):
            monkeypatch.delenv(key, raising=False)
    for key, value in TEST_ENV.items():
        monkeypatch.setenv(key, value)
    reset_settings_cache()
    yield monkeypatch
    reset_settings_cache()


@pytest.fixture
def app_instance() -> FastAPI:
    """A freshly built application, independent of the module-level singleton."""
    from app.main import create_app

    return create_app()


@pytest.fixture
async def client(app_instance: FastAPI) -> AsyncIterator[AsyncClient]:
    """An httpx client speaking ASGI directly to the app (no network)."""
    from httpx import ASGITransport

    async with AsyncClient(
        transport=ASGITransport(app=app_instance, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as async_client:
        yield async_client


@pytest.fixture
async def database_reachable() -> bool:
    """True when DATABASE_URL actually answers; used to skip integration tests."""
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.db.session import create_engine

    engine = create_engine(get_settings())
    try:
        async with engine.connect() as connection:
            await connection.execute(select(1))
        return True
    except Exception:  # noqa: BLE001 — any failure means "not reachable"
        # Includes driver-level errors (bad role, wrong port) that SQLAlchemy
        # does not always wrap, plus plain connection refusals.
        return False
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
async def _dispose_engine_after_each_test() -> AsyncIterator[None]:
    """The process-wide engine is closed by the app lifespan, which ASGITransport
    does not run. Dispose it here so connections do not leak between tests."""
    yield
    from app.db.session import dispose_engine

    await dispose_engine()
