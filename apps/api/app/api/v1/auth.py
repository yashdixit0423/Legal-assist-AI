"""Accounts and the write-only provider-key vault — spec §06."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, SessionDep, SettingsDep
from app.core.errors import ProviderError
from app.core.logging import get_logger
from app.db.models import ApiCredential
from app.schemas.auth import (
    CredentialResponse,
    LoginRequest,
    PutCredentialRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
    VerifyCredentialRequest,
    VerifyCredentialResponse,
)
from app.services.auth import accounts, tokens

router = APIRouter(tags=["auth"])
logger = get_logger(__name__)


def _tokens(settings: SettingsDep, user_id: object) -> TokenResponse:
    pair = tokens.issue_pair(settings, user_id)  # type: ignore[arg-type]
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
    )


def _credential(credential: ApiCredential) -> CredentialResponse:
    return CredentialResponse(
        provider=credential.provider,
        key_hint=credential.key_hint,
        key_version=credential.key_version,
        last_verified_at=credential.last_verified_at,
        created_at=credential.created_at,
        updated_at=credential.updated_at,
    )


@router.post(
    "/auth/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
    responses={409: {"description": "That email is already registered."}},
)
async def register(
    payload: RegisterRequest, session: SessionDep, settings: SettingsDep
) -> TokenResponse:
    user = await accounts.register(session, email=payload.email, password=payload.password)
    return _tokens(settings, user.id)


@router.post(
    "/auth/login",
    response_model=TokenResponse,
    summary="Exchange email and password for tokens",
    responses={401: {"description": "Email or password is incorrect."}},
)
async def login(payload: LoginRequest, session: SessionDep, settings: SettingsDep) -> TokenResponse:
    """One error for every failure, so this is not an account-enumeration oracle."""
    user = await accounts.authenticate(session, email=payload.email, password=payload.password)
    return _tokens(settings, user.id)


@router.post(
    "/auth/refresh",
    response_model=TokenResponse,
    summary="Exchange a refresh token for a new pair",
    responses={401: {"description": "Invalid or expired refresh token."}},
)
async def refresh(
    payload: RefreshRequest, session: SessionDep, settings: SettingsDep
) -> TokenResponse:
    """A refresh token is only accepted here; the ``typ`` claim is checked.

    There is no revocation list — see the module note in ``services/auth/tokens``.
    """
    user_id = tokens.decode(settings, payload.refresh_token, expect="refresh")
    user = await accounts.get_user(session, user_id)
    return _tokens(settings, user.id)


@router.get("/auth/me", response_model=UserResponse, summary="The current account")
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse(
        id=user.id, email=user.email, is_active=user.is_active, created_at=user.created_at
    )


# --- the vault --------------------------------------------------------------


@router.put(
    "/credentials",
    response_model=CredentialResponse,
    summary="Store or replace a provider key",
    description="The key is encrypted on write and is never returned by any endpoint.",
)
async def put_credential(
    payload: PutCredentialRequest,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> CredentialResponse:
    credential = await accounts.put_credential(
        session, settings, user=user, provider=payload.provider, api_key=payload.api_key
    )
    return _credential(credential)


@router.get(
    "/credentials",
    response_model=list[CredentialResponse],
    summary="Which providers have a stored key — metadata only",
)
async def list_credentials(user: CurrentUser, session: SessionDep) -> list[CredentialResponse]:
    return [_credential(c) for c in await accounts.list_credentials(session, user)]


@router.delete(
    "/credentials/{provider}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Forget a stored provider key",
)
async def delete_credential(provider: str, user: CurrentUser, session: SessionDep) -> Response:
    """204 with no body. ``response_class`` is explicit because FastAPI would
    otherwise try to serialise ``null`` into a response that may not have one."""
    await accounts.delete_credential(session, user, provider)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/credentials/verify",
    response_model=VerifyCredentialResponse,
    summary="Live-check a provider key",
)
async def verify_credential(
    payload: VerifyCredentialRequest,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> VerifyCredentialResponse:
    """Ask the provider whether the key works, and report *why* it does not.

    Returns 200 with ``valid: false`` and a typed ``error_code`` rather than
    propagating the provider's status: the caller asked a question about a key
    and got an answer, which is not the same as their request having failed.
    """
    from app.services.llm import client as llm

    provider = accounts.validate_provider(payload.provider)
    api_key = payload.api_key or await accounts.resolve_api_key(session, settings, user, provider)
    checked_at = dt.datetime.now(tz=dt.UTC)
    try:
        await llm.probe(settings, provider=provider, api_key=api_key)
    except ProviderError as exc:
        logger.info("credential_verify_failed", provider=provider, code=exc.code)
        return VerifyCredentialResponse(
            provider=provider,
            valid=False,
            checked_at=checked_at,
            error_code=exc.code,
            message=exc.message,
        )
    if payload.api_key is None:
        await accounts.mark_verified(session, user, provider)
    return VerifyCredentialResponse(provider=provider, valid=True, checked_at=checked_at)
