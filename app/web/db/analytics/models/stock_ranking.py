"""StockRanking - the composite model output for one instrument as of one date.

Overall score, per-factor percentiles, ranks, classification, value-trap risk,
compounder score and the explanation JSON, stamped with the model name/version
and the calc version so any historical score can be reproduced.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.web.db.analytics.base import AnalyticsBase
from app.web.db.analytics.models.mixins import IntIdMixin, UTCDateTime, utcnow


class StockRanking(IntIdMixin, AnalyticsBase):
    __tablename__ = "stock_rankings"
    __table_args__ = (
        UniqueConstraint(
            "ticker_symbol",
            "as_of_date",
            "model_name",
            "model_version",
            "calc_version_id",
            name="uq_stock_ranking_identity",
        ),
    )

    ticker_symbol: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    as_of_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    classification: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    value_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    growth_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    momentum_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    dividend_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    liquidity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sector_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    industry_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: 0 low, 1 medium, 2 high; NULL when unavailable (reason in explanation).
    value_trap_risk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    compounder_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    calc_version_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("calc_versions.id"), nullable=False, index=True
    )
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return f"<StockRanking {self.ticker_symbol} {self.as_of_date} {self.classification}>"


__all__ = ["StockRanking"]
