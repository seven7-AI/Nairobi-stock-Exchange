"""Mixins shared by every analytics table.

Integer keys rather than UUIDs: the store is a single SQLite file written by
one job at a time, and the rows are addressed by natural keys
``(ticker, as_of_date, metric, calc_version)`` far more often than by id.
Timestamps are UTC. SQLite has no timezone type and hands back naive values, so
``UTCDateTime`` re-attaches UTC on the way out and normalises aware values to UTC
on the way in; every writer stamps ``datetime.now(UTC)``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Integer
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """``DateTime(timezone=True)`` that always yields aware UTC datetimes."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"expected datetime, got {type(value).__name__}")
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def utcnow() -> datetime:
    """Timezone-aware UTC now, the only clock the analytics store uses."""
    return datetime.now(UTC)


class IntIdMixin:
    """Autoincrement integer primary key."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)


class CreatedAtMixin:
    """UTC creation timestamp, set in Python so tests can freeze it."""

    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)


__all__ = ["CreatedAtMixin", "IntIdMixin", "UTCDateTime", "utcnow"]
