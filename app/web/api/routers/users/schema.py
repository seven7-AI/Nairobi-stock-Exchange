"""User management schemas."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.web.api.routers.auth.schema import PasswordMixin, UserRead
from app.web.db.models.enums import UserRole, UserStatus


class UserCreate(PasswordMixin):
    """Add a user to the caller's organization."""

    email: EmailStr
    full_name: str | None = Field(default=None, max_length=255)
    role: UserRole


class UserRoleUpdate(BaseModel):
    role: UserRole


class UserStatusUpdate(BaseModel):
    status: UserStatus


__all__ = ["UserCreate", "UserRead", "UserRoleUpdate", "UserStatusUpdate"]
