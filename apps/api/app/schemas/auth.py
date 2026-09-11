"""Request and response shapes for accounts and the credential vault.

There is no field anywhere in this module that could carry a provider key back
out. That is the write-only property expressed in the type system, not only in
the service layer.
"""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field, field_validator


class _WithEmail(BaseModel):
    """Shared email validation.

    Not ``EmailStr``: that needs the ``email-validator`` package, which is not
    in the pinned set and is not worth adding for this. The rule here is the
    same one the database enforces (``ck_users_email_shape``: an ``@`` that is
    not the first character), so the API and the CHECK constraint cannot
    disagree about what an email is.
    """

    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def _shape(cls, value: str) -> str:
        candidate = value.strip().lower()
        local, _, domain = candidate.partition("@")
        if not local or not domain or "." not in domain or " " in candidate:
            msg = "email must look like name@example.com"
            raise ValueError(msg)
        return candidate


class RegisterRequest(_WithEmail):
    password: str = Field(
        min_length=12,
        max_length=200,
        description="At least 12 characters. Length is the only rule that reliably helps.",
    )


class LoginRequest(_WithEmail):
    password: str = Field(min_length=1, max_length=200)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=4000)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds.")


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    is_active: bool
    created_at: dt.datetime


class PutCredentialRequest(BaseModel):
    provider: str = Field(description="anthropic | openai | google | groq | openrouter")
    api_key: str = Field(
        min_length=8,
        max_length=500,
        description="Stored AES-256-GCM encrypted. Never returned by any endpoint.",
    )


class CredentialResponse(BaseModel):
    """Metadata only. There is deliberately no field for the key itself."""

    provider: str
    key_hint: str | None = Field(
        default=None, description="Last four characters, so a person can tell which key is stored."
    )
    key_version: int
    last_verified_at: dt.datetime | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class VerifyCredentialRequest(BaseModel):
    provider: str
    api_key: str | None = Field(
        default=None,
        description="Check this key without storing it. Omit to verify the stored one.",
    )


class VerifyCredentialResponse(BaseModel):
    provider: str
    valid: bool
    checked_at: dt.datetime
    error_code: str | None = Field(
        default=None,
        description=(
            "provider_key_invalid | provider_quota_exceeded | provider_timeout | " "provider_error"
        ),
    )
    message: str | None = None
