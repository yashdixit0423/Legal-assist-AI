"""Account and credential operations. No HTTP, no framework."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import (
    AuthenticationError,
    ConflictError,
    InvalidRequestError,
    MissingProviderKeyError,
    NotFoundError,
)
from app.core.logging import get_logger
from app.db.models import ApiCredential, Provider, User
from app.services.auth import passwords, vault

logger = get_logger(__name__)


def normalise_email(email: str) -> str:
    """Lowercased and trimmed — the ``ck_users_email_lowercase`` CHECK requires it."""
    return email.strip().lower()


async def register(session: AsyncSession, *, email: str, password: str) -> User:
    """Create an account, or 409 if the email is taken."""
    user = User(email=normalise_email(email), password_hash=passwords.hash_password(password))
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("An account with that email already exists.") from exc
    await session.commit()
    logger.info("user_registered", user_id=str(user.id))
    return user


async def authenticate(session: AsyncSession, *, email: str, password: str) -> User:
    """Verify credentials.

    One error for every failure — unknown email, wrong password, deactivated
    account. Distinguishing them would turn the login form into an account
    enumeration oracle.
    """
    user = (
        await session.execute(select(User).where(User.email == normalise_email(email)))
    ).scalar_one_or_none()
    ok = passwords.verify_password(password, user.password_hash if user else None)
    if user is None or not ok or not user.is_active:
        raise AuthenticationError("Email or password is incorrect.")
    if passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(password)
        await session.commit()
    return user


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise AuthenticationError("Invalid or expired token.")
    return user


# --- the vault --------------------------------------------------------------


def validate_provider(provider: str) -> str:
    """``api_credentials.provider`` has no CHECK constraint (ADR/Stage 1: the
    catalogue grows), so the vocabulary is enforced here instead."""
    try:
        return Provider(provider.strip().lower()).value
    except ValueError as exc:
        allowed = ", ".join(p.value for p in Provider)
        raise InvalidRequestError(
            f"Unknown provider {provider!r}. Expected one of: {allowed}.",
            details={"allowed": [p.value for p in Provider]},
        ) from exc


async def put_credential(
    session: AsyncSession,
    settings: Settings,
    *,
    user: User,
    provider: str,
    api_key: str,
) -> ApiCredential:
    """Store or replace one provider key. The plaintext is never persisted."""
    name = validate_provider(provider)
    sealed = vault.seal(settings, user_id=user.id, provider=name, api_key=api_key)
    existing = await _find(session, user.id, name)
    if existing is None:
        existing = ApiCredential(user_id=user.id, provider=name)
        session.add(existing)
    existing.ciphertext = sealed.ciphertext
    existing.nonce = sealed.nonce
    existing.key_version = sealed.key_version
    existing.key_hint = sealed.key_hint
    existing.last_verified_at = None
    await session.commit()
    await session.refresh(existing)
    # No key material, no hint, no ciphertext length in the log line.
    logger.info("credential_stored", user_id=str(user.id), provider=name)
    return existing


async def list_credentials(session: AsyncSession, user: User) -> list[ApiCredential]:
    return list(
        (
            await session.execute(
                select(ApiCredential)
                .where(ApiCredential.user_id == user.id)
                .order_by(ApiCredential.provider)
            )
        )
        .scalars()
        .all()
    )


async def delete_credential(session: AsyncSession, user: User, provider: str) -> None:
    name = validate_provider(provider)
    existing = await _find(session, user.id, name)
    if existing is None:
        raise NotFoundError(f"No stored key for provider {name!r}.")
    await session.delete(existing)
    await session.commit()
    logger.info("credential_deleted", user_id=str(user.id), provider=name)


async def resolve_api_key(
    session: AsyncSession, settings: Settings, user: User, provider: str
) -> str:
    """The plaintext key for an outbound call. The only caller is the LLM client.

    Raises the typed 402 when the user has stored nothing, so the frontend can
    route to Settings instead of showing a generic failure.
    """
    name = validate_provider(provider)
    credential = await _find(session, user.id, name)
    if credential is None:
        raise MissingProviderKeyError(details={"provider": name})
    return vault.unseal(
        settings,
        user_id=user.id,
        provider=name,
        ciphertext=credential.ciphertext,
        nonce=credential.nonce,
    )


async def mark_verified(session: AsyncSession, user: User, provider: str) -> None:
    credential = await _find(session, user.id, validate_provider(provider))
    if credential is not None:
        credential.last_verified_at = dt.datetime.now(tz=dt.UTC)
        await session.commit()


async def _find(session: AsyncSession, user_id: uuid.UUID, provider: str) -> ApiCredential | None:
    return (
        await session.execute(
            select(ApiCredential).where(
                ApiCredential.user_id == user_id, ApiCredential.provider == provider
            )
        )
    ).scalar_one_or_none()
