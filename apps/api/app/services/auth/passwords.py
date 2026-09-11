"""Password hashing.

Argon2id, with the library's defaults. They are chosen by people who follow
the parameter guidance; hand-tuning time and memory cost here would be a way
to be confidently wrong for years.
"""

from __future__ import annotations

from contextlib import suppress

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

# Argon2id is deliberately slow, which is the point, but it also means a login
# against a non-existent account returns faster than one against a real one
# unless we hash anyway. This is a hash of a fixed dummy password, used to burn
# the same time on the miss path.
_DUMMY_HASH = _hasher.hash("a-password-that-belongs-to-nobody")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-ish time verification that does not leak account existence.

    A ``None`` hash means no such user. We still run a verification against a
    dummy hash so the response time does not tell an attacker which emails are
    registered.
    """
    if password_hash is None:
        with suppress(VerifyMismatchError, VerificationError, InvalidHashError):
            _hasher.verify(_DUMMY_HASH, password)
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash used weaker parameters than we now use."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True
