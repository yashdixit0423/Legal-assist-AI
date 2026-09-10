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
    last_ingest_at: datetime | None = None


class HealthResponse(BaseModel):
    """Liveness plus enough detail to tell an empty stack from a broken one."""

    status: Literal["ok", "degraded"]
    version: str
    app_env: str
    database: DatabaseHealth
    corpus: CorpusHealth
