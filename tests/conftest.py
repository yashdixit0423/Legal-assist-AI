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
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import NullPool

REPO_ROOT = Path(__file__).resolve().parents[1]


def _default_database_url() -> str:
    """Where the throwaway test databases should be created.

    Hardcoding a port here was a real bug: this machine's Postgres runs on 5433
    (5432 is occupied by an unrelated server), so the default pointed at a
    server with no ``legaledge`` role and **15 database-backed tests skipped
    silently** — including the ``section_no_sort`` ordering suite, which is one
    of the four things that are supposed to have a full suite. A green run that
    quietly tested less than it claimed is the exact failure mode worth
    preventing.

    So the host and port come from the developer's own ``DATABASE_URL`` in
    ``.env`` when there is one, with the database name replaced. An explicit
    ``DATABASE_URL`` in the environment still wins over both, because
    ``os.environ.setdefault`` below never overwrites it.
    """
    fallback = "postgresql://legaledge:legaledge@localhost:5432/legaledge_test"
    dotenv = REPO_ROOT / ".env"
    if not dotenv.exists():
        return fallback
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        if not line.startswith("DATABASE_URL="):
            continue
        url = line.split("=", 1)[1].strip()
        server, _, _database = url.rpartition("/")
        if server:
            return f"{server}/legaledge_test"
    return fallback


# Deterministic, obviously-fake values. Real deployments read these from .env.
TEST_ENV = {
    "APP_ENV": "ci",
    "LOG_JSON": "true",
    "DATABASE_URL": _default_database_url(),
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


# ---------------------------------------------------------------------------
# Database fixtures.
#
# Every database-backed test runs against a throwaway database created by the
# real Alembic migration — not by ``create_all`` — so what the tests exercise is
# the schema production will actually have. The database name carries a random
# suffix and is dropped afterwards, so a run never inherits its own leftovers.
# ---------------------------------------------------------------------------


def _split_dsn(url: str) -> tuple[str, str]:
    """Return (server URL without database, database name)."""
    server, _, database = url.rpartition("/")
    return server, database


def _admin_url() -> str:
    """A sync URL pointed at the ``postgres`` maintenance database."""
    from app.core.config import get_settings

    server, _ = _split_dsn(get_settings().database_url_sync)
    return f"{server}/postgres"


def _postgres_is_reachable() -> bool:
    import psycopg

    try:
        with psycopg.connect(_admin_url().replace("postgresql+psycopg://", "postgresql://")):
            return True
    except Exception:  # noqa: BLE001 — any failure means "cannot test against a DB"
        return False


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[str]:
    """Create a uniquely named database, migrate it to head, drop it afterwards.

    Yields the plain ``postgresql://`` URL of that database. Skips the test when
    no PostgreSQL is reachable; CI always provides one, so nothing is silently
    unverified there.
    """
    import uuid as _uuid

    import psycopg

    from alembic import command
    from alembic.config import Config

    if not _postgres_is_reachable():
        pytest.skip("no reachable PostgreSQL for DATABASE_URL")

    from app.core.config import get_settings

    server, _ = _split_dsn(str(get_settings().DATABASE_URL))
    name = f"legaledge_test_{_uuid.uuid4().hex[:10]}"
    admin = _admin_url().replace("postgresql+psycopg://", "postgresql://")

    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')

    url = f"{server}/{name}"
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "apps" / "api" / "alembic"))
    config.set_main_option("sqlalchemy.url", url.replace("postgresql://", "postgresql+psycopg://"))
    try:
        command.upgrade(config, "head")
        yield url
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(
                "select pg_terminate_backend(pid) from pg_stat_activity "
                "where datname = %s and pid <> pg_backend_pid()",
                (name,),
            )
            conn.execute(f'DROP DATABASE IF EXISTS "{name}"')


@pytest.fixture
def empty_database() -> Iterator[str]:
    """An unmigrated database: no corpus tables at all."""
    import uuid as _uuid

    import psycopg

    if not _postgres_is_reachable():
        pytest.skip("no reachable PostgreSQL for DATABASE_URL")

    from app.core.config import get_settings

    server, _ = _split_dsn(str(get_settings().DATABASE_URL))
    name = f"legaledge_bare_{_uuid.uuid4().hex[:10]}"
    admin = _admin_url().replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    try:
        yield f"{server}/{name}"
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}"')


@pytest.fixture
async def db_session(migrated_database: str) -> AsyncIterator[AsyncSession]:
    """An async session on the migrated database, rolled back after the test.

    The session joins an outer transaction as a savepoint, so a test may call
    ``commit()`` and still leave the database exactly as it found it.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    engine = create_async_engine(
        migrated_database.replace("postgresql://", "postgresql+asyncpg://"),
        poolclass=NullPool,
    )
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()
    await engine.dispose()
