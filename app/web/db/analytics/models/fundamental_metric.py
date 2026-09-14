"""FundamentalMetric - one statement-derived number for one instrument as of one date.

Same contract as ``market_metrics`` (value NULL unless known/zero, reason says why,
provenance points at statement rows) plus the fiscal period the value describes.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.web.db.analytics.base import AnalyticsBase
from app.web.db.analytics.models.mixins import IntIdMixin, UTCDateTime, utcnow


class FundamentalMetric(IntIdMixin, AnalyticsBase):
    __tablename__ = "fundamental_metrics"
    __table_args__ = (
        UniqueConstraint(
            "ticker_symbol",
            "as_of_date",
            "metric",
            "calc_version_id",
            name="uq_fundamental_metric_identity",
        ),
    )

    ticker_symbol: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    as_of_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    #: e.g. ``roe``, ``net_margin``, ``revenue_cagr_3y``, ``roe_trend``.
    metric: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    #: The fiscal period the value describes (NULL when unavailable).
    period_end: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    period_type: Mapped[str | None] = mapped_column(String(12), nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    calc_version_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("calc_versions.id"), nullable=False, index=True
    )
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    def __repr__(self) -> str:
        where = f"{self.ticker_symbol} {self.metric} {self.as_of_date}"
        return f"<FundamentalMetric {where} {self.status}>"


__all__ = ["FundamentalMetric"]
