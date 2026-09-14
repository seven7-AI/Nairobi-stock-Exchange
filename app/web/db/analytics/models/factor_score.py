"""FactorScore - one factor for one instrument as of one date, with its peer ranks.

``score`` is the cross-sectional z-score (NULL when unavailable), the three
percentiles are within market / sector / industry (NULL when the group is too
small), ``coverage`` is the share of input weight that was known, and ``inputs``
records every input's value, z-score and weight so the score is reproducible.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.web.db.analytics.base import AnalyticsBase
from app.web.db.analytics.models.mixins import IntIdMixin, UTCDateTime, utcnow


class FactorScore(IntIdMixin, AnalyticsBase):
    __tablename__ = "factor_scores"
    __table_args__ = (
        UniqueConstraint(
            "ticker_symbol",
            "as_of_date",
            "factor",
            "calc_version_id",
            name="uq_factor_score_identity",
        ),
    )

    ticker_symbol: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    as_of_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    factor: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    coverage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    percentile_market: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentile_sector: Mapped[float | None] = mapped_column(Float, nullable=True)
    percentile_industry: Mapped[float | None] = mapped_column(Float, nullable=True)
    group_sizes: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    inputs: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    calc_version_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("calc_versions.id"), nullable=False, index=True
    )
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return f"<FactorScore {self.ticker_symbol} {self.factor} {self.as_of_date} {self.status}>"


__all__ = ["FactorScore"]
