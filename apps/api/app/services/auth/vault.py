"""The provider-key vault: AES-256-GCM, write-only.

A user's LLM API key is a bearer credential for *their* money. It is stored as
ciphertext and is never returned by any endpoint — the write-only property is
enforced here (there is no "get the plaintext" function reachable from a route)
and again in the schemas, which have no field to put it in.

Design notes:

* **AES-256-GCM with a fresh 12-byte nonce per write.** GCM nonce reuse under
  the same key is catastrophic — it leaks the XOR of plaintexts and the
  authentication subkey — so the nonce is generated at encryption time and
  never derived from anything.
* **The user id and provider are authenticated as associated data.** A row
  moved between users or relabelled to another provider fails to decrypt
  rather than silently handing one user's key to another.
* **``key_hint`` is the last four characters.** Enough for a person to
  recognise which key is stored, useless for reconstructing it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.core.logging import get_logger

logger = get_logger(__name__)

NONCE_BYTES = 12
CURRENT_KEY_VERSION = 1
HINT_CHARS = 4


@dataclass(frozen=True)
class Sealed:
    """Ciphertext ready to be written to ``api_credentials``."""

    ciphertext: bytes
    nonce: bytes
    key_version: int
    key_hint: str


def _cipher(settings: Settings) -> AESGCM:
    import base64

    raw = base64.b64decode(settings.CREDENTIAL_ENC_KEY, validate=True)
    if len(raw) != 32:  # already validated at startup; belt and braces
        raise ConfigurationError("CREDENTIAL_ENC_KEY must decode to 32 bytes.")
    return AESGCM(raw)


def _aad(user_id: uuid.UUID, provider: str) -> bytes:
    """Bind the ciphertext to the row it belongs in."""
    return f"{user_id}:{provider}".encode()


def seal(settings: Settings, *, user_id: uuid.UUID, provider: str, api_key: str) -> Sealed:
    """Encrypt one provider key for storage."""
    import os

    nonce = os.urandom(NONCE_BYTES)
    ciphertext = _cipher(settings).encrypt(nonce, api_key.encode(), _aad(user_id, provider))
    return Sealed(
        ciphertext=ciphertext,
        nonce=nonce,
        key_version=CURRENT_KEY_VERSION,
        key_hint=api_key[-HINT_CHARS:] if len(api_key) > HINT_CHARS else "",
    )


def unseal(
    settings: Settings, *, user_id: uuid.UUID, provider: str, ciphertext: bytes, nonce: bytes
) -> str:
    """Decrypt a stored key.

    Called from exactly one place — resolving the credential for an outbound
    provider call. No route reaches this, and none should: the day one does,
    the vault stops being write-only.
    """
    try:
        plaintext = _cipher(settings).decrypt(nonce, ciphertext, _aad(user_id, provider))
    except InvalidTag as exc:
        # Wrong CREDENTIAL_ENC_KEY, a rotated key version we cannot read, or a
        # row that has been tampered with or moved between users.
        logger.error("credential_decrypt_failed", provider=provider)
        raise ConfigurationError(
            "A stored provider key could not be decrypted. It may have been "
            "encrypted with a different CREDENTIAL_ENC_KEY."
        ) from exc
    return plaintext.decode()
