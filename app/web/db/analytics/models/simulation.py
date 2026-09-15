"""Simulation and Regime rows.

``simulations`` holds Monte Carlo horizon distributions (``scenario = ""``) and the
named scenario outcomes (``method = "scenario"``) for one instrument as of one
date; ``regimes`` holds the market-regime label per date with its evidence and the
weight overrides it proposes.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.web.db.analytics.base import AnalyticsBase
from app.web.db.analytics.models.mixins import IntIdMixin, UTCDateTime, utcnow


class Simulation(IntIdMixin, AnalyticsBase):
    __tablename__ = "simulations"
    __table_args__ = (
        UniqueConstraint(
            "ticker_symbol",
            "as_of_date",
            "horizon_days",
            "method",
            "scenario",
            "calc_version_id",
            name="uq_simulation_identity",
        ),
    )

    ticker_symbol: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    as_of_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    #: bootstrap, block_bootstrap, scenario
    method: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    #: "" for Monte Carlo rows; the scenario name otherwise.
    scenario: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    n_paths: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    q05: Mapped[float | None] = mapped_column(Float, nullable=True)
    q25: Mapped[float | None] = mapped_column(Float, nullable=True)
    q50: Mapped[float | None] = mapped_column(Float, nullable=True)
    q75: Mapped[float | None] = mapped_column(Float, nullable=True)
    q95: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_positive: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_return_above: Mapped[dict[str, float] | None] = mapped_column(JSON, nullable=True)
    p_drawdown_above: Mapped[dict[str, float] | None] = mapped_column(JSON, nullable=True)
    expected_max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    implied_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    assumptions: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    inputs: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    provenance: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    calc_version_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("calc_versions.id"), nullable=False, index=True
    )
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return (
            f"<Simulation {self.ticker_symbol} {self.as_of_date} {self.horizon_days}d "
            f"{self.method}{' ' + self.scenario if self.scenario else ''}>"
        )


class Regime(IntIdMixin, AnalyticsBase):
    __tablename__ = "regimes"
    __table_args__ = (
        UniqueConstraint(
            "as_of_date", "index_symbol", "calc_version_id", name="uq_regime_identity"
        ),
    )

    as_of_date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    index_symbol: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    trend: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    volatility: Mapped[str | None] = mapped_column(String(16), nullable=True)
    risk: Mapped[str | None] = mapped_column(String(16), nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    weight_overrides: Mapped[dict[str, float] | None] = mapped_column(JSON, nullable=True)
    calc_version_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("calc_versions.id"), nullable=False, index=True
    )
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return f"<Regime {self.index_symbol} {self.as_of_date} {self.trend}/{self.volatility}>"


__all__ = ["Regime", "Simulation"]
