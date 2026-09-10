"""Model-level invariants that a later stage must not quietly break."""

from __future__ import annotations

from typing import cast

import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import String, Table

from app.core.config import EMBEDDING_DIM
from app.db.base import Base
from app.db.models import (
    ApiCredential,
    AskLog,
    IngestRun,
    IngestStatus,
    KbChunk,
    LinkRelation,
    PartKind,
    SectionExplanation,
    Statute,
    StatuteLevel,
    StatuteLink,
    StatutePart,
    StatuteSection,
    User,
)

EXPECTED_TABLES = {
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


def test_every_spec_table_is_declared():
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_ask_logs_is_anonymous():
    """Spec §06: anonymous, no user_id. The rows describe people's legal problems."""
    columns = set(AskLog.__table__.columns.keys())
    assert "user_id" not in columns
    assert not any("user" in name for name in columns)
    assert AskLog.__table__.foreign_keys == set()


def test_ask_logs_records_the_citation_violation_flag():
    """The zero-tolerance metric needs somewhere to be counted from."""
    assert "citation_violation" in AskLog.__table__.columns


def test_embedding_column_matches_the_model_dimensionality():
    embedding = KbChunk.__table__.columns["embedding"]
    assert cast("Vector", embedding.type).dim == EMBEDDING_DIM
    assert EMBEDDING_DIM == 768


def test_section_sort_column_uses_byte_collation():
    """Byte ordering makes the citation order independent of the server locale."""
    column = StatuteSection.__table__.columns["section_no_sort"]
    assert cast("String", column.type).collation == "C"
    assert column.nullable is False


def test_citation_order_index_exists_on_statute_and_sort_key():
    index = next(
        idx
        for idx in cast("Table", StatuteSection.__table__).indexes
        if idx.name == "ix_statute_sections_citation_order"
    )
    assert [c.name for c in index.columns] == ["statute_id", "section_no_sort"]


def test_provenance_columns_are_mandatory():
    """GODL attribution and a reproducible pipeline both need these."""
    for name in ("source_portal", "source_url", "source_sha256", "as_of_date"):
        assert Statute.__table__.columns[name].nullable is False


def test_section_keeps_raw_text_alongside_parsed_text():
    """Spec §04: a parser fix must be replayable without re-fetching."""
    assert "text_raw" in StatuteSection.__table__.columns
    assert StatuteSection.__table__.columns["text_verbatim"].nullable is False


@pytest.mark.parametrize(
    ("table", "constraint", "enum"),
    [
        (Statute, "ck_statutes_level", StatuteLevel),
        (StatutePart, "ck_statute_parts_kind", PartKind),
        (StatuteLink, "ck_statute_links_relation", LinkRelation),
        (IngestRun, "ck_ingest_runs_status", IngestStatus),
    ],
)
def test_check_constraints_list_exactly_their_enum_members(table, constraint, enum):
    """Drift guard: a new enum member with no CHECK update fails inserts at runtime."""
    text = next(str(c.sqltext) for c in table.__table__.constraints if c.name == constraint)
    in_constraint = {
        token.strip().strip("'") for token in text.split("(")[1].rstrip(")").split(",")
    }
    assert in_constraint == {member.value for member in enum}


def test_chunk_embed_input_is_prefix_plus_text():
    """The embedded string is exactly what token_count counted."""
    chunk = KbChunk(
        heading_prefix="passage: DPDP Act, 2023 — Consent. ",
        text="The consent given by the Data Principal shall be free.",
        token_count=17,
        chunk_idx=0,
    )
    assert chunk.embed_input == (
        "passage: DPDP Act, 2023 — Consent. "
        "The consent given by the Data Principal shall be free."
    )


def test_credential_repr_never_leaks_the_ciphertext():
    """Reprs reach logs and tracebacks."""
    credential = ApiCredential(
        provider="anthropic",
        ciphertext=b"\xde\xad\xbe\xef-secret-ciphertext",
        nonce=b"0" * 12,
        key_hint="ab12",
    )
    rendered = repr(credential)
    assert "ciphertext" not in rendered
    assert "deadbeef" not in rendered.lower()
    assert "ab12" not in rendered
    assert "anthropic" in rendered


def test_no_model_exposes_a_plaintext_key_column():
    for table in (ApiCredential.__table__, User.__table__):
        for name in table.columns:
            assert name not in {"api_key", "secret", "password", "plaintext"}


def test_explanations_are_unique_per_section_language_and_prompt_version():
    names = {c.name for c in cast("Table", SectionExplanation.__table__).constraints}
    assert "uq_section_explanations_version" in names
