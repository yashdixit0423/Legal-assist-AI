"""Shapes for ``/v1/chat/documents`` — docs/adr/0005.

Metadata only. No field here can carry document text.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field


class DocumentResponse(BaseModel):
    """A document now held in memory for the caller's questions."""

    document_id: str = Field(description="Pass in /v1/ask `document_ids`.")
    filename: str = Field(description="Sanitised, for display only.")
    kind: Literal["pdf", "txt", "docx"]
    pages: int | None = Field(default=None, description="PDF only.")
    chunk_count: int
    expires_at: dt.datetime = Field(
        description="When it is forgotten if not used again (idle TTL; each use extends it)."
    )
