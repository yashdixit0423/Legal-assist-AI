"""Declarative base for every ORM model.

Stage 1 adds the nine tables from spec §06 on top of this.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared metadata for all LegalEdge tables."""
