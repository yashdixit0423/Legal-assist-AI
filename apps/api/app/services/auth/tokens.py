"""JWT access and refresh tokens.

Stateless, HS256, signed with ``JWT_SECRET``. Both token types carry a ``typ``
claim and it is checked on use: a refresh token presented as a bearer token is
rejected, because a refresh token lives longer and is stored in more places.

**Known limitation, deliberate:** there is no revocation list. Logging out is
a client-side discard, and a stolen refresh token is valid until it expires.
Revocation needs a store — a ``refresh_tokens`` table or Redis — and that is a
schema decision, not something to slip in here. Recorded in the build log.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any, Literal

import jwt

from app.core.config import Settings
from app.core.errors import AuthenticationError

ALGORITHM = "HS256"
TokenType = Literal["access", "refresh"]


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 0


def _encode(settings: Settings, subject: uuid.UUID, token_type: TokenType, ttl_seconds: int) -> str:
    now = dt.datetime.now(tz=dt.UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "typ": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(seconds=ttl_seconds)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def issue_pair(settings: Settings, subject: uuid.UUID) -> TokenPair:
    return TokenPair(
        access_token=_encode(settings, subject, "access", settings.JWT_ACCESS_TTL),
        refresh_token=_encode(settings, subject, "refresh", settings.JWT_REFRESH_TTL),
        expires_in=settings.JWT_ACCESS_TTL,
    )


def decode(settings: Settings, token: str, *, expect: TokenType) -> uuid.UUID:
    """Return the subject, or raise :class:`AuthenticationError`.

    Every failure mode collapses to the same message. Telling a caller whether
    a token was expired, malformed or the wrong type is information they do not
    need and an attacker does.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid or expired token.") from exc
    if payload.get("typ") != expect:
        raise AuthenticationError("Invalid or expired token.")
    try:
        return uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid or expired token.") from exc
