"""Platform user — carries the role that every RBAC check resolves against."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.web.db.base import Base
from app.web.db.models.base import TimestampMixin, UUIDMixin
from app.web.db.models.enums import UserRole, UserStatus, pg_enum

if TYPE_CHECKING:
    from app.web.db.models.organization import Organization


class User(UUIDMixin, TimestampMixin, Base):
    """A platform user, always scoped to exactly one organization."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, "user_role"),
        nullable=False,
        default=UserRole.RESEARCH_VIEWER,
        index=True,
    )
    status: Mapped[UserStatus] = mapped_column(
        pg_enum(UserStatus, "user_status"),
        nullable=False,
        default=UserStatus.PENDING_VERIFICATION,
    )
    is_email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization: Mapped[Organization] = relationship(back_populates="users")

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE and self.is_email_verified

    def __repr__(self) -> str:
        return f"<User {self.email} role={self.role}>"


__all__ = ["User"]
