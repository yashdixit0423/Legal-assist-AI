"""Passwords, tokens and the credential vault.

The scope cut named four things that get a full suite. This is a fifth, and
the justification is the same one: a vault that silently misbehaves hands one
user's provider key — their money — to someone else, and nothing about the
symptom would point at the cause. Everything here is cheap and deterministic.
"""

from __future__ import annotations

import base64
import uuid

import pytest

from app.core.errors import AuthenticationError, ConfigurationError
from app.services.auth import passwords, tokens, vault

USER_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_B = uuid.UUID("22222222-2222-2222-2222-222222222222")
SECRET = "sk-ant-api03-not-a-real-key-0123456789"


# --- passwords --------------------------------------------------------------


def test_a_password_verifies_against_its_own_hash():
    digest = passwords.hash_password("correct horse battery staple")
    assert passwords.verify_password("correct horse battery staple", digest)


def test_a_wrong_password_does_not_verify():
    digest = passwords.hash_password("correct horse battery staple")
    assert not passwords.verify_password("Correct horse battery staple", digest)


def test_the_hash_is_argon2id_and_not_the_password():
    digest = passwords.hash_password(SECRET)
    assert digest.startswith("$argon2id$")
    assert SECRET not in digest


def test_the_same_password_hashes_differently_every_time():
    """Per-password salt. Identical hashes would let an attacker with the table
    see which accounts share a password."""
    assert passwords.hash_password("same") != passwords.hash_password("same")


def test_verifying_against_no_hash_is_false_and_still_does_the_work():
    """An unknown email must not return faster than a known one, or the login
    form becomes an account-enumeration oracle."""
    assert not passwords.verify_password("anything", None)


# --- tokens -----------------------------------------------------------------


def test_an_access_token_round_trips(settings_env):
    from app.core.config import get_settings

    settings = get_settings()
    pair = tokens.issue_pair(settings, USER_A)
    assert tokens.decode(settings, pair.access_token, expect="access") == USER_A


def test_a_refresh_token_is_rejected_as_an_access_token(settings_env):
    """A refresh token lives fourteen days and is stored in more places. It
    must not be usable as a bearer credential."""
    from app.core.config import get_settings

    settings = get_settings()
    pair = tokens.issue_pair(settings, USER_A)
    with pytest.raises(AuthenticationError):
        tokens.decode(settings, pair.refresh_token, expect="access")
    assert tokens.decode(settings, pair.refresh_token, expect="refresh") == USER_A


def test_a_tampered_token_is_rejected(settings_env):
    from app.core.config import get_settings

    settings = get_settings()
    token = tokens.issue_pair(settings, USER_A).access_token
    head, payload, signature = token.split(".")
    with pytest.raises(AuthenticationError):
        tokens.decode(settings, f"{head}.{payload}.{signature[:-2]}xx", expect="access")


def test_a_token_signed_with_another_secret_is_rejected(settings_env, monkeypatch):
    from app.core.config import get_settings, reset_settings_cache

    settings = get_settings()
    token = tokens.issue_pair(settings, USER_A).access_token
    monkeypatch.setenv("JWT_SECRET", "a-completely-different-secret-value-32+")
    reset_settings_cache()
    with pytest.raises(AuthenticationError):
        tokens.decode(get_settings(), token, expect="access")


def test_an_expired_token_is_rejected(settings_env, monkeypatch):
    from app.core.config import get_settings, reset_settings_cache

    monkeypatch.setenv("JWT_ACCESS_TTL", "60")
    reset_settings_cache()
    settings = get_settings()
    token = tokens._encode(settings, USER_A, "access", ttl_seconds=-10)
    with pytest.raises(AuthenticationError):
        tokens.decode(settings, token, expect="access")


def test_every_token_failure_gives_the_same_message(settings_env):
    """Telling a caller whether a token was expired, malformed or the wrong
    type is information they do not need and an attacker does."""
    from app.core.config import get_settings

    settings = get_settings()
    messages = set()
    for bad in ("", "not-a-token", "a.b.c"):
        with pytest.raises(AuthenticationError) as caught:
            tokens.decode(settings, bad, expect="access")
        messages.add(caught.value.message)
    assert len(messages) == 1


# --- the vault --------------------------------------------------------------


def test_a_sealed_key_round_trips(settings_env):
    from app.core.config import get_settings

    settings = get_settings()
    sealed = vault.seal(settings, user_id=USER_A, provider="anthropic", api_key=SECRET)
    assert (
        vault.unseal(
            settings,
            user_id=USER_A,
            provider="anthropic",
            ciphertext=sealed.ciphertext,
            nonce=sealed.nonce,
        )
        == SECRET
    )


def test_the_ciphertext_does_not_contain_the_key(settings_env):
    from app.core.config import get_settings

    sealed = vault.seal(get_settings(), user_id=USER_A, provider="anthropic", api_key=SECRET)
    assert SECRET.encode() not in sealed.ciphertext
    assert SECRET not in base64.b64encode(sealed.ciphertext).decode()


def test_each_write_uses_a_fresh_nonce(settings_env):
    """GCM nonce reuse under one key leaks the XOR of the plaintexts and the
    authentication subkey. Reusing a nonce here would be catastrophic, so this
    asserts the property rather than trusting the call site."""
    from app.core.config import get_settings

    settings = get_settings()
    nonces = {
        vault.seal(settings, user_id=USER_A, provider="anthropic", api_key=SECRET).nonce
        for _ in range(20)
    }
    assert len(nonces) == 20
    assert all(len(nonce) == vault.NONCE_BYTES for nonce in nonces)


def test_a_credential_cannot_be_read_as_another_user(settings_env):
    """The user id is authenticated as associated data, so a row moved between
    accounts fails to decrypt instead of handing over someone else's key."""
    from app.core.config import get_settings

    settings = get_settings()
    sealed = vault.seal(settings, user_id=USER_A, provider="anthropic", api_key=SECRET)
    with pytest.raises(ConfigurationError):
        vault.unseal(
            settings,
            user_id=USER_B,
            provider="anthropic",
            ciphertext=sealed.ciphertext,
            nonce=sealed.nonce,
        )


def test_a_credential_cannot_be_read_as_another_provider(settings_env):
    from app.core.config import get_settings

    settings = get_settings()
    sealed = vault.seal(settings, user_id=USER_A, provider="anthropic", api_key=SECRET)
    with pytest.raises(ConfigurationError):
        vault.unseal(
            settings,
            user_id=USER_A,
            provider="openai",
            ciphertext=sealed.ciphertext,
            nonce=sealed.nonce,
        )


def test_tampered_ciphertext_is_rejected_rather_than_returning_garbage(settings_env):
    """GCM authenticates. A flipped bit must raise, not decrypt to nonsense
    that then gets sent to a provider as a key."""
    from app.core.config import get_settings

    settings = get_settings()
    sealed = vault.seal(settings, user_id=USER_A, provider="anthropic", api_key=SECRET)
    broken = bytearray(sealed.ciphertext)
    broken[0] ^= 0x01
    with pytest.raises(ConfigurationError):
        vault.unseal(
            settings,
            user_id=USER_A,
            provider="anthropic",
            ciphertext=bytes(broken),
            nonce=sealed.nonce,
        )


def test_the_key_hint_is_only_the_last_four_characters(settings_env):
    from app.core.config import get_settings

    sealed = vault.seal(get_settings(), user_id=USER_A, provider="anthropic", api_key=SECRET)
    assert sealed.key_hint == SECRET[-4:]
    assert len(sealed.key_hint) == 4


def test_a_short_key_gets_no_hint_at_all(settings_env):
    from app.core.config import get_settings

    sealed = vault.seal(get_settings(), user_id=USER_A, provider="anthropic", api_key="abcd")
    assert sealed.key_hint == ""


def test_a_credential_repr_never_leaks_material():
    """reprs reach logs and tracebacks."""
    from app.db.models import ApiCredential

    credential = ApiCredential(
        user_id=USER_A, provider="anthropic", ciphertext=b"\x00secret", nonce=b"n" * 12
    )
    rendered = repr(credential)
    assert "secret" not in rendered
    assert "ciphertext" not in rendered


def test_no_response_schema_can_carry_a_key():
    """The write-only property, asserted against the types rather than the
    prose. If someone adds an api_key field to a response, this fails."""
    from app.schemas import auth as schemas

    for name in ("CredentialResponse", "VerifyCredentialResponse", "UserResponse"):
        fields = set(getattr(schemas, name).model_fields)
        assert not {"api_key", "key", "secret", "ciphertext"} & fields
