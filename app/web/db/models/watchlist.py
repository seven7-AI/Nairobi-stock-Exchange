"""Watchlist and its items — org-scoped, optionally owned by a single user."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.web.db.base import Base
from app.web.db.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.web.db.models.instrument import Instrument
    from app.web.db.models.organization import Organization


class Watchlist(UUIDMixin, TimestampMixin, Base):
    """A named set of instruments belonging to an organization."""

    __tablename__ = "watchlists"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_watchlist_org_name"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    organization: Mapped[Organization] = relationship(back_populates="watchlists")
    items: Mapped[list[WatchlistItem]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Watchlist {self.name} org={self.organization_id}>"


class WatchlistItem(UUIDMixin, TimestampMixin, Base):
    """An instrument's membership in a watchlist."""

    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "instrument_id", name="uq_watchlist_item"),
    )

    watchlist_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("watchlists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("instruments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    watchlist: Mapped[Watchlist] = relationship(back_populates="items")
    instrument: Mapped[Instrument] = relationship(back_populates="watchlist_items")

    def __repr__(self) -> str:
        return f"<WatchlistItem {self.instrument_id}>"


__all__ = ["Watchlist", "WatchlistItem"]
