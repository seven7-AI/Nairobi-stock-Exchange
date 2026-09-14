"""Forecast and ForecastEvaluation - a return forecast and how it turned out.

A forecast is a distribution over the horizon return as of an origin date, per model
version; the evaluation row is written once the horizon has elapsed and the data
exists, never before.
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


class Forecast(IntIdMixin, AnalyticsBase):
    __tablename__ = "forecasts"
    __table_args__ = (
        UniqueConstraint(
            "ticker_symbol",
            "as_of_date",
            "horizon_months",
            "model",
            "model_version",
            "calc_version_id",
            name="uq_forecast_identity",
        ),
    )

    ticker_symbol: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    as_of_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    horizon_months: Mapped[int] = mapped_column(Integer, nullable=False)
    model: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_log: Mapped[float | None] = mapped_column(Float, nullable=True)
    sd_log: Mapped[float | None] = mapped_column(Float, nullable=True)
    q05: Mapped[float | None] = mapped_column(Float, nullable=True)
    q25: Mapped[float | None] = mapped_column(Float, nullable=True)
    q50: Mapped[float | None] = mapped_column(Float, nullable=True)
    q75: Mapped[float | None] = mapped_column(Float, nullable=True)
    q95: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_positive: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_outperform: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_vol: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    drawdown_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    benchmark: Mapped[str | None] = mapped_column(String(24), nullable=True)
    inputs: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    provenance: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    calc_version_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("calc_versions.id"), nullable=False, index=True
    )
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return (
            f"<Forecast {self.ticker_symbol} {self.as_of_date} {self.horizon_months}m {self.model}>"
        )


class ForecastEvaluation(IntIdMixin, AnalyticsBase):
    __tablename__ = "forecast_evaluations"
    __table_args__ = (UniqueConstraint("forecast_id", name="uq_forecast_evaluation_forecast"),)

    forecast_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("forecasts.id"), nullable=False, index=True
    )
    realised_return: Mapped[float] = mapped_column(Float, nullable=False)
    realised_benchmark_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    realised_end_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    error: Mapped[float] = mapped_column(Float, nullable=False)
    directional_hit: Mapped[bool] = mapped_column(Boolean, nullable=False)
    benchmark_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    within_interval: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return (
            f"<ForecastEvaluation forecast={self.forecast_id} realised={self.realised_return:.4f}>"
        )


__all__ = ["Forecast", "ForecastEvaluation"]
