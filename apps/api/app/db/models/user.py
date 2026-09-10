"""Accounts and the encrypted provider-key vault.

Auth exists in Phase 1.1 for one reason: to hold the user's own LLM API key.
The vault stores AES-256-GCM ciphertext and never the key itself; Stage 6 builds
the write-only API over it, and no endpoint ever returns these columns.
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin


class Provider(StrEnum):
    """LLM providers the gateway can route to with a user-supplied key."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"
    GROQ = "groq"
    OPENROUTER = "openrouter"


class User(Base, TimestampMixin):
    """An account. Identified by a UUID because it is exposed in tokens."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
        CheckConstraint("position('@' in email) > 1", name="ck_users_email_shape"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    # Argon2id, produced by app/services (Stage 6). Never a raw or reversible value.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    credentials: Mapped[list[ApiCredential]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User {self.id}>"


class ApiCredential(Base, TimestampMixin):
    """One provider key, envelope-encrypted.

    ``ciphertext`` and ``nonce`` are the AES-256-GCM output;
    ``key_version`` names which ``CREDENTIAL_ENC_KEY`` encrypted it so the key
    can be rotated without a flag day. ``key_hint`` is the last few characters of
    the *original* key, kept only so the UI can show which key is stored — it is
    never enough to reconstruct one.
    """

    __tablename__ = "api_credentials"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_api_credentials_user_provider"),
        CheckConstraint("octet_length(ciphertext) > 0", name="ck_api_credentials_cipher"),
        CheckConstraint("octet_length(nonce) = 12", name="ck_api_credentials_nonce_len"),
        CheckConstraint("key_version >= 1", name="ck_api_credentials_key_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    key_hint: Mapped[str | None] = mapped_column(String(8))
    last_verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="credentials")

    def __repr__(self) -> str:
        # Never include ciphertext, nonce or hint in a repr: reprs reach logs.
        return f"<ApiCredential user={self.user_id} provider={self.provider!r}>"
