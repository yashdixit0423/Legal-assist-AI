"""Retrieval-side tables: ``kb_chunks`` and ``statute_links``."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import EMBEDDING_DIM
from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.statute import StatuteSection


class LinkRelation(StrEnum):
    """How one section relates to another (deterministic extraction, no LLM)."""

    REFERS_TO = "refers_to"
    AMENDED_BY = "amended_by"
    SEE_ALSO = "see_also"


class KbChunk(Base):
    """One retrievable unit: a whole section, or one sub-section split of it.

    ``heading_prefix`` holds the e5 ``passage:`` prefix together with the act
    title and marginal note, built by the chunker at index time. The embedded
    string is ``heading_prefix + text``; ``token_count`` counts that whole
    string, which is what has to stay under the model's 512-token ceiling.

    ``embedding`` and ``tsv`` are nullable because rows are bulk-loaded first and
    the HNSW index is built once afterwards, not maintained per row.
    """

    __tablename__ = "kb_chunks"
    __table_args__ = (
        UniqueConstraint("section_id", "chunk_idx", name="uq_kb_chunks_section_idx"),
        CheckConstraint("token_count > 0", name="ck_kb_chunks_token_count"),
        Index("ix_kb_chunks_statute", "statute_id"),
        # Dense retrieval. Declared here as well as in the migration so the ORM
        # metadata fully describes the schema and the drift test has something
        # to compare against.
        Index(
            "ix_kb_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # Sparse retrieval (BM25 via ts_rank).
        Index("ix_kb_chunks_tsv_gin", "tsv", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    section_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("statute_sections.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalised from the section so a statute filter never needs a join.
    statute_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("statutes.id", ondelete="CASCADE"), nullable=False
    )
    chunk_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    heading_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    tsv: Mapped[str | None] = mapped_column(TSVECTOR)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    section: Mapped[StatuteSection] = relationship(back_populates="chunks")

    @property
    def embed_input(self) -> str:
        """Exactly the string that was, or will be, embedded."""
        return f"{self.heading_prefix}{self.text}"

    def __repr__(self) -> str:
        return f"<KbChunk section={self.section_id} idx={self.chunk_idx}>"


class StatuteLink(Base):
    """A cross-reference between two sections, extracted by regex.

    Unique per (from, to, relation) so re-running the extractor is idempotent;
    ``raw_text`` keeps the phrase that produced the link for auditing.
    """

    __tablename__ = "statute_links"
    __table_args__ = (
        UniqueConstraint(
            "from_section_id", "to_section_id", "relation", name="uq_statute_links_edge"
        ),
        CheckConstraint(
            "relation in ('refers_to', 'amended_by', 'see_also')",
            name="ck_statute_links_relation",
        ),
        CheckConstraint(
            "from_section_id <> to_section_id", name="ck_statute_links_no_self_reference"
        ),
        Index("ix_statute_links_to", "to_section_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    from_section_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("statute_sections.id", ondelete="CASCADE"), nullable=False
    )
    to_section_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("statute_sections.id", ondelete="CASCADE"), nullable=False
    )
    relation: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)

    from_section: Mapped[StatuteSection] = relationship(
        back_populates="links_out", foreign_keys=[from_section_id]
    )

    def __repr__(self) -> str:
        return f"<StatuteLink {self.from_section_id}->{self.to_section_id} {self.relation}>"
