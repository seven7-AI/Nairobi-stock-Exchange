"""Auth request and response schemas.

No response model here carries ``hashed_password``. ``UserRead`` is the only
shape a user is ever serialized in.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.web.core.security.password import MAX_PASSWORD_BYTES, MIN_PASSWORD_LENGTH
from app.web.db.models.enums import UserRole, UserStatus

SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


def _password_field() -> object:
    return Field(min_length=MIN_PASSWORD_LENGTH, description="Plaintext password")


class PasswordMixin(BaseModel):
    password: str = Field(min_length=MIN_PASSWORD_LENGTH)

    @field_validator("password")
    @classmethod
    def _bcrypt_length_limit(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes.")
        return value


class RegisterRequest(PasswordMixin):
    """Creates an organization and its first user, who becomes org_admin."""

    email: EmailStr
    full_name: str | None = Field(default=None, max_length=255)
    organization_name: str = Field(min_length=2, max_length=255)

    @property
    def organization_slug(self) -> str:
        return SLUG_PATTERN.sub("-", self.organization_name.lower()).strip("-")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class VerifyEmailRequest(BaseModel):
    token: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(PasswordMixin):
    token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")


class AccessToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserRead(BaseModel):
    """Public user shape. Never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: UserRole
    status: UserStatus
    is_email_verified: bool
    organization_id: uuid.UUID
    last_login_at: datetime | None
    created_at: datetime


class RegisterResponse(BaseModel):
    user: UserRead
    organization_id: uuid.UUID
    verification_email_sent: bool
    next_step: str = "Verify your email address, then begin onboarding at step 1."


class MessageResponse(BaseModel):
    message: str


__all__ = [
    "AccessToken",
    "LoginRequest",
    "MessageResponse",
    "PasswordResetConfirm",
    "PasswordResetRequest",
    "RefreshRequest",
    "RegisterRequest",
    "RegisterResponse",
    "TokenPair",
    "UserRead",
    "VerifyEmailRequest",
]
