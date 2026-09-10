"""Operational tables: ``ingest_runs`` and ``ask_logs``.

``ask_logs`` is deliberately anonymous. There is no ``user_id`` column and no
foreign key to ``users``, because the rows describe questions people asked about
their legal problems. ``tests/unit/test_models.py`` asserts the absence, so the
column cannot reappear by accident.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IngestStatus(StrEnum):
    """Lifecycle of one pipeline run."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class IngestRun(Base):
    """One execution of a corpus pipeline command.

    ``warnings`` and ``errors`` carry the per-run report the parser guardrails
    produce (spec §04); a run that ends ``failed`` must exit non-zero.
    """

    __tablename__ = "ingest_runs"
    __table_args__ = (
        CheckConstraint(
            "status in ('running', 'succeeded', 'partial', 'failed')",
            name="ck_ingest_runs_status",
        ),
        Index("ix_ingest_runs_slug_started", "statute_slug", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_portal: Mapped[str] = mapped_column(String(60), nullable=False)
    # Null when a run covers a whole tier rather than one Act.
    statute_slug: Mapped[str | None] = mapped_column(String(120))
    command: Mapped[str | None] = mapped_column(String(200))
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    docs_fetched: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    sections_written: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default="[]")
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    def __repr__(self) -> str:
        return f"<IngestRun {self.id} {self.statute_slug!r} {self.status}>"


class AskLog(Base):
    """One question, anonymised. The only evaluation data this phase produces.

    No user id, no session id, no IP address: nothing that ties a row to a
    person. ``citation_violation`` records when the validator caught the model
    citing a section that was not in the packed set — the metric that must stay
    at zero.
    """

    __tablename__ = "ask_logs"
    __table_args__ = (
        CheckConstraint("not (answered and abstained)", name="ck_ask_logs_answer_or_abstain"),
        Index("ix_ask_logs_created_at", "created_at"),
        Index("ix_ask_logs_violation", "citation_violation"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str] = mapped_column(String(8), nullable=False)
    rewritten_question: Mapped[str | None] = mapped_column(Text)
    retrieved_section_ids: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), nullable=False, server_default="{}"
    )
    top_score: Mapped[float | None] = mapped_column(Float)
    answered: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    abstained: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    citation_violation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    model: Mapped[str | None] = mapped_column(String(120))
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<AskLog {self.id} answered={self.answered} abstained={self.abstained}>"
