"""Organization — a clinic, fund, desk, or firm subscribing to the platform."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.web.db.base import Base
from app.web.db.models.base import TimestampMixin, UUIDMixin
from app.web.db.models.enums import OrganizationStatus, pg_enum

if TYPE_CHECKING:
    from app.web.db.models.connector import Connector
    from app.web.db.models.onboarding_state import OnboardingState
    from app.web.db.models.user import User
    from app.web.db.models.watchlist import Watchlist


class Organization(UUIDMixin, TimestampMixin, Base):
    """Tenant boundary. Every org-scoped row carries this row's id."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="KE")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Africa/Nairobi")
    status: Mapped[OrganizationStatus] = mapped_column(
        pg_enum(OrganizationStatus, "organization_status"),
        nullable=False,
        default=OrganizationStatus.PENDING,
    )
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    users: Mapped[list[User]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    onboarding_state: Mapped[OnboardingState | None] = relationship(
        back_populates="organization", uselist=False, cascade="all, delete-orphan"
    )
    watchlists: Mapped[list[Watchlist]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    connectors: Mapped[list[Connector]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Organization {self.slug}>"


__all__ = ["Organization"]
