"""One smoke test per component that is not a load-bearing pillar.

Scope decision of 2026-09-11: full suites are reserved for the four things that
can silently produce a wrong legal answer — section ordering, the chunker's e5
prefixes, the abstention gate, and the citation validator. Everything else gets
one test that would fail if the component were broken, and no more.
"""

from __future__ import annotations

import pytest

from app import __version__


def test_settings_load_and_fail_loudly(settings_env):
    """Config is valid here, and a missing required variable is a clear error."""
    from app.core.config import EMBEDDING_DIM, ConfigError, get_settings, reset_settings_cache

    settings = get_settings()
    assert settings.EMBED_MODEL == "NyayaLabs98/nyaya-embed-v1"
    assert settings.MAX_CHUNK_TOKENS == 450
    assert EMBEDDING_DIM == 768

    settings_env.setattr("app.core.config._ENV_FILE", None)
    settings_env.delenv("DATABASE_URL")
    reset_settings_cache()
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        get_settings()


def test_logging_redacts_secrets_and_drops_user_text(capsys, settings_env):
    from app.core.config import get_settings
    from app.core.logging import configure_logging, get_logger

    configure_logging(get_settings())
    get_logger("smoke").info("event", api_key="sk-must-not-appear", question="private")
    captured = capsys.readouterr().err
    assert "sk-must-not-appear" not in captured
    assert "private" not in captured


def test_error_envelope_and_the_missing_key_code():
    from app.core.errors import MissingProviderKeyError

    exc = MissingProviderKeyError()
    assert exc.http_status == 402
    assert exc.to_payload()["code"] == "missing_provider_key"


async def test_health_endpoint_answers(client):
    response = await client.get("/v1/health")
    assert response.status_code in (200, 503)
    body = response.json()
    assert body["version"] == __version__
    assert "schema_ready" in body["database"]
    assert "statutes" in body["corpus"]


def test_cli_check_config(settings_env):
    from typer.testing import CliRunner

    from legaledge_kb.main import app as cli_app

    result = CliRunner().invoke(cli_app, ["check-config"])
    assert result.exit_code == 0
    assert "configuration valid" in result.stdout
    assert "AAAAAAAA" not in result.stdout  # secrets are never printed


def test_schema_declares_every_table_and_ask_logs_stays_anonymous():
    from app.db.base import Base
    from app.db.models import AskLog, KbChunk

    assert set(Base.metadata.tables) == {
        "statutes",
        "statute_parts",
        "statute_sections",
        "statute_links",
        "kb_chunks",
        "section_explanations",
        "ingest_runs",
        "ask_logs",
        "users",
        "api_credentials",
    }
    # No user id, no foreign keys: these rows describe people's legal problems.
    assert "user_id" not in AskLog.__table__.columns
    assert AskLog.__table__.foreign_keys == set()
    assert KbChunk.__table__.columns["embedding"].type.dim == 768


def test_migration_applies_and_rolls_back(empty_database):
    import psycopg

    from alembic import command
    from alembic.config import Config
    from tests.conftest import REPO_ROOT

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "apps" / "api" / "alembic"))
    config.set_main_option(
        "sqlalchemy.url", empty_database.replace("postgresql://", "postgresql+psycopg://")
    )

    def tables() -> set[str]:
        with psycopg.connect(empty_database) as conn, conn.cursor() as cur:
            cur.execute("select tablename from pg_tables where schemaname = 'public'")
            return {row[0] for row in cur.fetchall()}

    command.upgrade(config, "head")
    applied = tables()
    assert "kb_chunks" in applied
    assert "statute_sections" in applied

    command.downgrade(config, "base")
    assert tables() == {"alembic_version"}


async def test_corpus_stats_counts_real_rows(db_session):
    import datetime as dt

    from app.db.models import Statute
    from app.services.corpus_stats import get_corpus_stats

    before = await get_corpus_stats(db_session)
    assert before.schema_ready is True

    db_session.add(
        Statute(
            slug="smoke-act-2026",
            short_title="Smoke Act, 2026",
            year=2026,
            jurisdiction="India",
            level="central",
            source_portal="indiacode",
            source_url="https://indiacode.gov.in/handle/123456789/496413",
            source_sha256="d" * 64,
            as_of_date=dt.date(2026, 9, 11),
        )
    )
    await db_session.flush()
    after = await get_corpus_stats(db_session)
    assert after.statutes == before.statutes + 1
