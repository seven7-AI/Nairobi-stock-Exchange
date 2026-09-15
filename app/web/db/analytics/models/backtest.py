"""BacktestRun, BacktestResult, BacktestPosition, BacktestEquity.

A run is one simulation of one model / weight set over one period with one cost
schedule; its results are per segment and per series (the portfolio and each
benchmark), its positions are every trade, and its equity curve is stored so the
diagrams and the API can show it without re-running.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.web.db.analytics.base import AnalyticsBase
from app.web.db.analytics.models.mixins import IntIdMixin, UTCDateTime, utcnow


class BacktestRun(IntIdMixin, AnalyticsBase):
    __tablename__ = "backtest_runs"

    name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    #: run, weight_search:in_sample, weight_search:out_of_sample, benchmark
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, default="run", index=True)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    start_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    end_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    top_n: Mapped[int] = mapped_column(Integer, nullable=False)
    weights: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    costs: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    benchmarks: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    segments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    calc_version_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("calc_versions.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return f"<BacktestRun {self.id} {self.name} {self.start_date}..{self.end_date}>"


class BacktestResult(IntIdMixin, AnalyticsBase):
    __tablename__ = "backtest_results"
    __table_args__ = (
        UniqueConstraint("run_id", "segment", "series", "metric", name="uq_backtest_result"),
    )

    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("backtest_runs.id"), nullable=False, index=True
    )
    #: "1", "2", ... per data segment; "linked" for the compounded whole.
    segment: Mapped[str] = mapped_column(String(16), nullable=False)
    #: portfolio, ^NASI, ^N20I, equal_weight
    series: Mapped[str] = mapped_column(String(32), nullable=False)
    metric: Mapped[str] = mapped_column(String(48), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class BacktestPosition(IntIdMixin, AnalyticsBase):
    __tablename__ = "backtest_positions"
    __table_args__ = (Index("ix_backtest_positions_run_day", "run_id", "day"),)

    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("backtest_runs.id"), nullable=False, index=True
    )
    segment: Mapped[str] = mapped_column(String(16), nullable=False)
    day: Mapped[date_type] = mapped_column(Date, nullable=False)
    ticker_symbol: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    price_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    cost: Mapped[float] = mapped_column(Float, nullable=False)
    #: target weight the rebalance assigned (None on exits)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)


class BacktestEquity(IntIdMixin, AnalyticsBase):
    __tablename__ = "backtest_equity"
    __table_args__ = (UniqueConstraint("run_id", "day", name="uq_backtest_equity_day"),)

    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("backtest_runs.id"), nullable=False, index=True
    )
    segment: Mapped[str] = mapped_column(String(16), nullable=False)
    day: Mapped[date_type] = mapped_column(Date, nullable=False)
    equity: Mapped[float] = mapped_column(Float, nullable=False)
    #: benchmark name -> level rebased at the segment start
    benchmarks: Mapped[dict[str, float] | None] = mapped_column(JSON, nullable=True)


__all__ = ["BacktestEquity", "BacktestPosition", "BacktestResult", "BacktestRun"]
