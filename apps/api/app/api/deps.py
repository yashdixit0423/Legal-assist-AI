"""Shared route dependencies.

Authentication is opt-in per route, not global middleware. Spec §06 requires
that reading the corpus works without credentials, and a global guard with an
exemption list is one careless edit away from either locking the corpus or
opening ``/v1/ask``. Requiring the dependency where it applies makes the
protected set readable from the route definitions.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AuthenticationError
from app.db.models import User
from app.db.session import get_session
from app.services.auth import accounts, tokens

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise AuthenticationError("Authentication is required.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError("Authentication is required.")
    return token.strip()


async def current_user(
    session: SessionDep,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve the bearer access token to an active account."""
    user_id = tokens.decode(settings, bearer_token(authorization), expect="access")
    return await accounts.get_user(session, user_id)


CurrentUser = Annotated[User, Depends(current_user)]


def client_ip(request: Request) -> str:
    """The caller's address, trusting one proxy hop.

    Caddy sets ``X-Forwarded-For`` in the production overlay. Only the first
    entry is used and only the leftmost hop is trusted: the header is
    client-settable, so treating the whole chain as authentic would let anyone
    forge a fresh identity per request and walk around the limit entirely.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
