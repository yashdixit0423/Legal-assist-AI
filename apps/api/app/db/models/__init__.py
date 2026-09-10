"""ORM models for the eleven Phase 1.1 tables (spec §06).

Importing this package registers every table on ``Base.metadata``, which is what
Alembic's ``env.py`` and ``create_all`` both need.
"""

from app.db.models.ask_log import AskLog, IngestRun, IngestStatus
from app.db.models.kb_chunk import KbChunk, LinkRelation, StatuteLink
from app.db.models.statute import (
    PartKind,
    SectionExplanation,
    Statute,
    StatuteLevel,
    StatutePart,
    StatuteSection,
)
from app.db.models.user import ApiCredential, Provider, User

__all__ = [
    "ApiCredential",
    "AskLog",
    "IngestRun",
    "IngestStatus",
    "KbChunk",
    "LinkRelation",
    "PartKind",
    "Provider",
    "SectionExplanation",
    "Statute",
    "StatuteLevel",
    "StatuteLink",
    "StatutePart",
    "StatuteSection",
    "User",
]
