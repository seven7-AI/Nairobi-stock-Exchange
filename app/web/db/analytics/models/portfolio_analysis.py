"""PortfolioAnalysis - the risk picture of one hypothetical weight set as of one date."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.web.db.analytics.base import AnalyticsBase
from app.web.db.analytics.models.mixins import IntIdMixin, UTCDateTime, utcnow


class PortfolioAnalysis(IntIdMixin, AnalyticsBase):
    __tablename__ = "portfolio_analyses"

    as_of_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    weights: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    notional: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    coverage: Mapped[float] = mapped_column(Float, nullable=False)
    #: expected_return, volatility, sharpe, max_drawdown, beta, average_correlation,
    #: hhi, effective_positions, top_n_weight - each Measure as its JSON shape.
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    sector_exposure: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    industry_exposure: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    correlation: Mapped[dict[str, dict[str, float]] | None] = mapped_column(JSON, nullable=True)
    days_to_liquidate: Mapped[dict[str, float | None]] = mapped_column(JSON, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    inputs: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    calc_version_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("calc_versions.id"), nullable=False, index=True
    )
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return f"<PortfolioAnalysis {self.name} {self.as_of_date} {self.status}>"


__all__ = ["PortfolioAnalysis"]
