"""DataQualityFinding - one suspicious thing the checks found, tracked across runs.

A finding is identified by ``(check, ticker, trade_date, detail_hash)``. The first
run that sees it creates the row; every later run that still sees it moves
``last_seen_at``; the first run that no longer sees it sets ``resolved_at``. So the
table is both today's list and the history of what went wrong and when it was
fixed - nothing is deleted.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Date, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.web.db.analytics.base import AnalyticsBase
from app.web.db.analytics.models.mixins import IntIdMixin, UTCDateTime, utcnow


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DataQualityFinding(IntIdMixin, AnalyticsBase):
    __tablename__ = "data_quality_findings"
    __table_args__ = (
        UniqueConstraint(
            "check_name",
            "ticker_symbol",
            "trade_date",
            "detail_hash",
            name="uq_dq_finding_identity",
        ),
    )

    check_name: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    #: NULL for universe-wide findings (a market-wide gap, a failed scrape).
    ticker_symbol: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    trade_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    #: sha256 of the detail text - the stable identity of a finding whose detail is long.
    detail_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Machine-readable specifics (values, thresholds, row ids) for the API and the AI layer.
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    first_seen_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_seen_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None

    def __repr__(self) -> str:
        where = f"{self.ticker_symbol or '*'} {self.trade_date or ''}".strip()
        return f"<DQ {self.check_name} {self.severity} {where}>"


__all__ = ["DataQualityFinding", "Severity"]
