"""Response shapes for ``GET /v1/health``."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DatabaseHealth(BaseModel):
    """Connectivity and migration state of PostgreSQL."""

    connected: bool
    schema_ready: bool = Field(
        description="True once the corpus tables exist (migrations applied)."
    )
    latency_ms: float | None = None
    error: str | None = Field(default=None, description="Failure class, never a connection string.")


class CorpusHealth(BaseModel):
    """Corpus size and freshness, per spec §06 (surfaced on /health)."""

    statutes: int = 0
    sections: int = 0
    chunks: int = 0
    chunks_embedded: int = 0
    links: int = Field(default=0, description="Extracted cross-references between sections.")
    vector_index_ready: bool = Field(
        default=False, description="False while a bulk embed has the HNSW index dropped."
    )
    retrieval_ready: bool = Field(
        default=False, description="True only when every chunk is embedded and indexed."
    )
    last_ingest_at: datetime | None = None


class HealthResponse(BaseModel):
    """Liveness plus enough detail to tell an empty stack from a broken one."""

    status: Literal["ok", "degraded"]
    version: str
    app_env: str
    database: DatabaseHealth
    corpus: CorpusHealth
