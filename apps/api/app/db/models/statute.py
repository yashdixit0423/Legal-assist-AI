"""Statutes and their hierarchy: ``statutes``, ``statute_parts``, ``statute_sections``.

Identifier strategy: corpus rows use ``BIGINT`` identities rather than UUIDs
because section ids are packed into the generation prompt as citation
identifiers, where a 36-character UUID costs tokens on every retrieved block for
no benefit. See docs/adr/0003.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.kb_chunk import KbChunk, StatuteLink


class StatuteLevel(StrEnum):
    """Which legislature enacted the Act."""

    CENTRAL = "central"
    STATE = "state"


class PartKind(StrEnum):
    """A statute's structural divisions above section level."""

    PART = "part"
    CHAPTER = "chapter"


class Statute(Base, TimestampMixin):
    """One Act, as published by a government portal.

    ``source_url`` and ``source_sha256`` are not optional: GODL attribution and
    a reproducible pipeline both depend on knowing exactly which document a
    section came from.
    """

    __tablename__ = "statutes"
    __table_args__ = (
        CheckConstraint("level in ('central', 'state')", name="ck_statutes_level"),
        CheckConstraint("year between 1800 and 2200", name="ck_statutes_year"),
        CheckConstraint("char_length(source_sha256) = 64", name="ck_statutes_sha256_len"),
        Index("ix_statutes_jurisdiction_year", "jurisdiction", "year"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    short_title: Mapped[str] = mapped_column(String(300), nullable=False)
    long_title: Mapped[str | None] = mapped_column(Text)
    act_number: Mapped[str | None] = mapped_column(String(40))
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    enacted_on: Mapped[dt.date | None] = mapped_column(Date)
    jurisdiction: Mapped[str] = mapped_column(String(60), nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    ministry: Mapped[str | None] = mapped_column(String(200))

    # Provenance, per spec §03: portal, URL and checksum for every document.
    source_portal: Mapped[str] = mapped_column(String(60), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    # The corpus is never presented as current law; this date is shown on every
    # section and every citation.
    as_of_date: Mapped[dt.date] = mapped_column(Date, nullable=False)

    is_repealed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    repealed_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("statutes.id", ondelete="SET NULL")
    )
    section_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    parts: Mapped[list[StatutePart]] = relationship(
        back_populates="statute", cascade="all, delete-orphan"
    )
    sections: Mapped[list[StatuteSection]] = relationship(
        back_populates="statute", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Statute {self.slug!r}>"


class StatutePart(Base):
    """A PART or CHAPTER. Nests via ``parent_id`` (a chapter inside a part)."""

    __tablename__ = "statute_parts"
    __table_args__ = (
        CheckConstraint("kind in ('part', 'chapter')", name="ck_statute_parts_kind"),
        UniqueConstraint("statute_id", "order_idx", name="uq_statute_parts_order"),
        Index("ix_statute_parts_statute_parent", "statute_id", "parent_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    statute_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("statutes.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("statute_parts.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    number: Mapped[str | None] = mapped_column(String(40))
    heading: Mapped[str | None] = mapped_column(Text)
    order_idx: Mapped[int] = mapped_column(Integer, nullable=False)

    statute: Mapped[Statute] = relationship(back_populates="parts")
    children: Mapped[list[StatutePart]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
    parent: Mapped[StatutePart | None] = relationship(back_populates="children", remote_side=[id])
    sections: Mapped[list[StatuteSection]] = relationship(back_populates="part")

    def __repr__(self) -> str:
        return f"<StatutePart {self.kind} {self.number!r}>"


class StatuteSection(Base, TimestampMixin):
    """One section, stored verbatim.

    ``section_no_sort`` carries the byte-sortable citation key produced by
    :func:`app.services.kb.section_numbers.section_no_sort`. Its column is
    ``COLLATE "C"`` so the ordering is a property of the schema rather than of
    whatever ``datcollate`` the server was initialised with. (On a glibc
    ``en_US.utf8`` database the locale ordering agrees with the byte ordering for
    this key format; on an ICU collation, where padding and punctuation can be
    ignorable at the primary level, that agreement is not guaranteed. The
    citation order is too important to depend on it.)

    ``text_raw`` keeps the originally extracted block alongside the parsed text
    so a parser fix can be replayed without re-fetching (spec §04).
    """

    __tablename__ = "statute_sections"
    __table_args__ = (
        UniqueConstraint("statute_id", "section_no", name="uq_statute_sections_no"),
        UniqueConstraint("statute_id", "order_idx", name="uq_statute_sections_order"),
        # The browser's ordering index, and the reason section_no_sort exists.
        Index("ix_statute_sections_citation_order", "statute_id", "section_no_sort"),
        Index("ix_statute_sections_part", "part_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    statute_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("statutes.id", ondelete="CASCADE"), nullable=False
    )
    part_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("statute_parts.id", ondelete="SET NULL")
    )

    section_no: Mapped[str] = mapped_column(String(40), nullable=False)
    section_no_sort: Mapped[str] = mapped_column(String(64, collation="C"), nullable=False)
    marginal_note: Mapped[str | None] = mapped_column(Text)
    text_verbatim: Mapped[str] = mapped_column(Text, nullable=False)
    text_raw: Mapped[str | None] = mapped_column(Text)
    footnotes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    amendment_note: Mapped[str | None] = mapped_column(Text)
    commenced_on: Mapped[dt.date | None] = mapped_column(Date)
    as_of_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    is_omitted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    order_idx: Mapped[int] = mapped_column(Integer, nullable=False)

    statute: Mapped[Statute] = relationship(back_populates="sections")
    part: Mapped[StatutePart | None] = relationship(back_populates="sections")
    chunks: Mapped[list[KbChunk]] = relationship(
        back_populates="section", cascade="all, delete-orphan"
    )
    explanations: Mapped[list[SectionExplanation]] = relationship(
        back_populates="section", cascade="all, delete-orphan"
    )
    links_out: Mapped[list[StatuteLink]] = relationship(
        back_populates="from_section",
        foreign_keys="StatuteLink.from_section_id",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<StatuteSection {self.statute_id}:{self.section_no!r}>"


class SectionExplanation(Base):
    """A plain-language explanation, generated once at build time and cached.

    Unique per (section, language, prompt version) so a prompt revision can be
    regenerated selectively without discarding the previous text.
    """

    __tablename__ = "section_explanations"
    __table_args__ = (
        UniqueConstraint(
            "section_id", "lang", "prompt_version", name="uq_section_explanations_version"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    section_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("statute_sections.id", ondelete="CASCADE"), nullable=False
    )
    explanation_plain: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str] = mapped_column(String(8), nullable=False, server_default="en")
    model_used: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    generated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    human_reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    section: Mapped[StatuteSection] = relationship(back_populates="explanations")

    def __repr__(self) -> str:
        return f"<SectionExplanation section={self.section_id} v={self.prompt_version!r}>"
