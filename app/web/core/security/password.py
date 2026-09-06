"""Password hashing.

Uses the ``bcrypt`` library directly rather than passlib. passlib 1.7.4 (its
last release, 2020) probes the backend with a secret longer than 72 bytes,
which bcrypt >= 4.1 refuses outright — so ``CryptContext.hash()`` raises
``ValueError`` before it ever hashes anything. bcrypt's own API is small,
typed, and maintained.

The hash is the only form a password takes after the request body is parsed.
It is never logged (``hashed`` and ``password`` are both redacted key names,
and the ``$2b$`` prefix is redacted by value shape) and never appears in a
response schema.

    codegraph explore "hash_password verify_password auth views.py"
"""

from __future__ import annotations

import bcrypt

from app.web.config import get_settings

#: bcrypt hashes at most 72 bytes and modern versions refuse longer input
#: rather than truncating silently. Reject at the edge instead.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 12
#: Fallback when settings are unavailable (e.g. a bare unit test).
DEFAULT_BCRYPT_ROUNDS = 12


def _rounds() -> int:
    """Cost factor from settings, falling back to the production default."""
    try:
        return get_settings().bcrypt_rounds
    except Exception:
        return DEFAULT_BCRYPT_ROUNDS


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    encoded = plain_password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password exceeds {MAX_PASSWORD_BYTES} bytes.")
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=_rounds())).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a plaintext password against a stored hash.

    Returns ``False`` on a malformed or over-long input rather than raising, so
    a corrupted row cannot be told apart from a wrong password by status code.
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


def is_password_acceptable(plain_password: str) -> bool:
    """Length policy, checked before hashing."""
    return (
        len(plain_password) >= MIN_PASSWORD_LENGTH
        and len(plain_password.encode("utf-8")) <= MAX_PASSWORD_BYTES
    )


__all__ = [
    "DEFAULT_BCRYPT_ROUNDS",
    "MAX_PASSWORD_BYTES",
    "MIN_PASSWORD_LENGTH",
    "hash_password",
    "is_password_acceptable",
    "verify_password",
]
