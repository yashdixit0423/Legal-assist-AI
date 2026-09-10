"""The migration itself: applies to an empty database, and rolls back cleanly.

Each test runs against a throwaway database created for the run, so the suite
never inherits its own leftovers and can be run twice in a row.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from tests.conftest import REPO_ROOT

EXPECTED_TABLES = {
    "alembic_version",
    "api_credentials",
    "ask_logs",
    "ingest_runs",
    "kb_chunks",
    "section_explanations",
    "statute_links",
    "statute_parts",
    "statute_sections",
    "statutes",
    "users",
}


def _alembic_config(url: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "apps" / "api" / "alembic"))
    config.set_main_option("sqlalchemy.url", url.replace("postgresql://", "postgresql+psycopg://"))
    return config


def _rows(url: str, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """Run a read-only query with psycopg and return every row."""
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def test_migration_history_has_exactly_one_head():
    """Two heads mean somebody branched and the deploy order is ambiguous."""
    script = ScriptDirectory.from_config(_alembic_config("postgresql://x/y"))
    assert len(script.get_heads()) == 1


def test_upgrade_creates_every_table(migrated_database):
    tables = {
        row[0]
        for row in _rows(
            migrated_database,
            "select tablename from pg_tables where schemaname = 'public'",
        )
    }
    assert tables == EXPECTED_TABLES


def test_upgrade_creates_the_vector_extension(migrated_database):
    assert _rows(migrated_database, "select extname from pg_extension where extname='vector'")


def test_embedding_column_is_vector_768(migrated_database):
    (rendered,) = _rows(
        migrated_database,
        """
        select format_type(a.atttypid, a.atttypmod)
        from pg_attribute a join pg_class c on c.oid = a.attrelid
        where c.relname = 'kb_chunks' and a.attname = 'embedding'
        """,
    )[0]
    assert rendered == "vector(768)"


def test_section_sort_column_is_c_collated_in_the_database(migrated_database):
    (collation,) = _rows(
        migrated_database,
        """
        select coll.collname
        from pg_attribute a
        join pg_class c on c.oid = a.attrelid
        join pg_collation coll on coll.oid = a.attcollation
        where c.relname = 'statute_sections' and a.attname = 'section_no_sort'
        """,
    )[0]
    assert collation == "C"


def test_hnsw_index_has_the_specified_parameters(migrated_database):
    (definition,) = _rows(
        migrated_database,
        "select indexdef from pg_indexes where indexname = 'ix_kb_chunks_embedding_hnsw'",
    )[0]
    assert "USING hnsw" in definition
    assert "vector_cosine_ops" in definition
    assert "m='16'" in definition
    assert "ef_construction='64'" in definition


def test_gin_index_on_tsv(migrated_database):
    (definition,) = _rows(
        migrated_database,
        "select indexdef from pg_indexes where indexname = 'ix_kb_chunks_tsv_gin'",
    )[0]
    assert "USING gin" in definition
    assert "(tsv)" in definition


def test_btree_index_for_citation_ordered_browsing(migrated_database):
    (definition,) = _rows(
        migrated_database,
        "select indexdef from pg_indexes " "where indexname = 'ix_statute_sections_citation_order'",
    )[0]
    assert "USING btree (statute_id, section_no_sort)" in definition


def test_models_and_migration_do_not_drift(migrated_database):
    """Autogenerate against the migrated schema must produce an empty diff.

    This is the test that keeps the ORM and the migration honest for the rest of
    the build: any model change without a migration fails here.
    """
    from sqlalchemy import create_engine

    import app.db.models  # noqa: F401  # registers every table
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from app.db.base import Base

    engine = create_engine(migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"compare_type": True, "compare_server_default": True}
            )
            diff = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    assert diff == [], f"models drifted from the migration: {diff}"


def test_downgrade_leaves_no_trace(empty_database):
    """upgrade → downgrade must return the database to (near) empty."""
    config = _alembic_config(empty_database)
    command.upgrade(config, "head")
    assert (
        len(_rows(empty_database, "select tablename from pg_tables where schemaname='public'")) > 1
    )

    command.downgrade(config, "base")
    remaining = {
        row[0]
        for row in _rows(
            empty_database, "select tablename from pg_tables where schemaname='public'"
        )
    }
    # Alembic's own bookkeeping table survives a downgrade by design.
    assert remaining == {"alembic_version"}
    assert not _rows(empty_database, "select extname from pg_extension where extname='vector'")


def test_upgrade_is_repeatable_after_a_downgrade(empty_database):
    config = _alembic_config(empty_database)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    tables = {
        row[0]
        for row in _rows(
            empty_database, "select tablename from pg_tables where schemaname='public'"
        )
    }
    assert tables == EXPECTED_TABLES


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("statutes", "source_sha256"),
        ("statutes", "as_of_date"),
        ("statute_sections", "text_verbatim"),
        ("statute_sections", "section_no_sort"),
        ("kb_chunks", "heading_prefix"),
    ],
)
def test_mandatory_columns_are_not_null_in_the_database(migrated_database, table, column):
    (is_nullable,) = _rows(
        migrated_database,
        "select is_nullable from information_schema.columns "
        "where table_name = %s and column_name = %s",
        (table, column),
    )[0]
    assert is_nullable == "NO"
