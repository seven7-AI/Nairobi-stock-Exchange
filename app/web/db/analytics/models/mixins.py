"""Mixins shared by every analytics table.

Integer keys rather than UUIDs: the store is a single SQLite file written by
one job at a time, and the rows are addressed by natural keys
``(ticker, as_of_date, metric, calc_version)`` far more often than by id.
Timestamps are naive UTC - SQLite has no timezone type, and every writer in
this repository stamps ``datetime.now(UTC)``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    """Timezone-aware UTC now, the only clock the analytics store uses."""
    return datetime.now(UTC)


class IntIdMixin:
    """Autoincrement integer primary key."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)


class CreatedAtMixin:
    """UTC creation timestamp, set in Python so tests can freeze it."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


__all__ = ["CreatedAtMixin", "IntIdMixin", "utcnow"]
