"""MarketMetric - one price-derived number for one instrument as of one date.

Returns, momentum, risk and liquidity all land here, one row per
``(ticker, as_of_date, metric, calc_version)``. ``value`` is NULL whenever
``status`` is not known/zero, and ``reason`` says why - a missing row and an
unavailable metric are different facts.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.web.db.analytics.base import AnalyticsBase
from app.web.db.analytics.models.mixins import IntIdMixin, UTCDateTime, utcnow


class MarketMetric(IntIdMixin, AnalyticsBase):
    __tablename__ = "market_metrics"
    __table_args__ = (
        UniqueConstraint(
            "ticker_symbol",
            "as_of_date",
            "metric",
            "calc_version_id",
            name="uq_market_metric_identity",
        ),
    )

    ticker_symbol: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    as_of_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    #: e.g. ``return_12m``, ``momentum_6m``, ``volatility_annualised``.
    metric: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    #: The observation window actually used (both NULL when unavailable).
    window_start: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    window_end: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The window contains an observation flagged as a corporate action (unadjusted prices).
    contains_flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provenance: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    calc_version_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("calc_versions.id"), nullable=False, index=True
    )
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return f"<MarketMetric {self.ticker_symbol} {self.metric} {self.as_of_date} {self.status}>"


__all__ = ["MarketMetric"]
