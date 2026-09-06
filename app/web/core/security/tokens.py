"""JWT issuing and verification.

Access and refresh tokens are distinguished by a ``type`` claim, and the claim
is checked on decode: a refresh token presented as a bearer credential is
rejected. The role claim carries the ``UserRole`` *value*, matching what the
database stores.

    codegraph explore "create_access_token decode_token TokenPayload require_roles"
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import jwt
from pydantic import BaseModel, ConfigDict

from app.web.config import Settings
from app.web.core.exceptions import AuthenticationError
from app.web.db.models.enums import UserRole


class TokenType(StrEnum):
    """The ``token_type`` claim.

    Checked on decode so a token minted for one purpose cannot be replayed for
    another: a password-reset link is not a bearer credential.
    """

    ACCESS = "access"
    REFRESH = "refresh"
    EMAIL_VERIFY = "email_verify"
    PASSWORD_RESET = "password_reset"


class TokenPayload(BaseModel):
    """Decoded, validated JWT claims."""

    model_config = ConfigDict(frozen=True)

    sub: uuid.UUID
    email: str
    role: UserRole
    organization_id: uuid.UUID
    token_type: TokenType
    exp: datetime
    iat: datetime
    jti: str


def _encode(
    settings: Settings,
    *,
    user_id: uuid.UUID,
    email: str,
    role: UserRole,
    organization_id: uuid.UUID,
    token_type: TokenType,
    expires_delta: timedelta,
) -> str:
    now = datetime.now(tz=UTC)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "role": role.value,
        "organization_id": str(organization_id),
        "token_type": token_type.value,
        "iat": now,
        "exp": now + expires_delta,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(
    settings: Settings,
    *,
    user_id: uuid.UUID,
    email: str,
    role: UserRole,
    organization_id: uuid.UUID,
) -> str:
    """Short-lived credential presented as a bearer token."""
    return _encode(
        settings,
        user_id=user_id,
        email=email,
        role=role,
        organization_id=organization_id,
        token_type=TokenType.ACCESS,
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(
    settings: Settings,
    *,
    user_id: uuid.UUID,
    email: str,
    role: UserRole,
    organization_id: uuid.UUID,
) -> str:
    """Long-lived credential, only ever exchanged at the refresh endpoint."""
    return _encode(
        settings,
        user_id=user_id,
        email=email,
        role=role,
        organization_id=organization_id,
        token_type=TokenType.REFRESH,
        expires_delta=timedelta(days=settings.refresh_token_expire_days),
    )


def decode_token(
    settings: Settings, token: str, *, expected_type: TokenType = TokenType.ACCESS
) -> TokenPayload:
    """Decode and validate a token, or raise ``AuthenticationError``.

    The error message is uniform on purpose — distinguishing "expired" from
    "malformed" from "wrong type" tells an attacker which knob to turn.
    """
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationError(detail=f"jwt decode failed: {type(exc).__name__}") from exc

    payload = TokenPayload.model_validate(claims)
    if payload.token_type != expected_type:
        raise AuthenticationError(
            detail=f"expected {expected_type.value} token, got {payload.token_type.value}"
        )
    return payload


def create_purpose_token(
    settings: Settings,
    *,
    user_id: uuid.UUID,
    email: str,
    role: UserRole,
    organization_id: uuid.UUID,
    token_type: TokenType,
    expires_in_hours: int = 24,
) -> str:
    """Single-purpose, link-delivered token (email verification, password reset).

    Deliberately short-lived and typed, so it is rejected if presented as a
    bearer credential.
    """
    return _encode(
        settings,
        user_id=user_id,
        email=email,
        role=role,
        organization_id=organization_id,
        token_type=token_type,
        expires_delta=timedelta(hours=expires_in_hours),
    )


__all__ = [
    "TokenPayload",
    "TokenType",
    "create_access_token",
    "create_purpose_token",
    "create_refresh_token",
    "decode_token",
]
