"""Research API schemas.

Numbers arrive as the store's Measure JSON: ``{"value", "status", "reason"}``. A
``null`` value always comes with a status and a reason; the API never turns an
absent number into 0.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from pydantic import BaseModel, Field


class Measure(BaseModel):
    value: float | None = None
    status: str
    reason: str | None = None


class StockSummary(BaseModel):
    ticker_symbol: str
    sector: str | None = None
    industry: str | None = None
    as_of: date_type | None = None
    overall_score: float | None = None
    status: str | None = None
    classification: str | None = None
    confidence: float | None = None
    market_rank: int | None = None


class StockPage(BaseModel):
    items: list[StockSummary]
    next_cursor: str | None = Field(default=None, description="Pass back as ?cursor= for the next page")
    total: int


class ResearchProfileOut(BaseModel):
    ticker_symbol: str
    as_of: dict[str, str | None]
    identity: dict[str, Any]
    score: dict[str, Any]
    factors: dict[str, Any]
    metrics: dict[str, dict[str, Any]]
    valuation: dict[str, Any]
    forecast: dict[str, Any]
    scenarios: dict[str, Any]
    simulation: dict[str, Any]
    regime: dict[str, Any]
    models: list[dict[str, Any]]
    disclaimer: str
    notes: list[str]


class BlockOut(BaseModel):
    ticker_symbol: str
    as_of: str | None
    block: str
    data: dict[str, Any]


class HistoryPoint(BaseModel):
    as_of: date_type
    overall_score: float | None = None
    status: str
    classification: str | None = None
    market_rank: int | None = None


class HistoryOut(BaseModel):
    ticker_symbol: str
    points: list[HistoryPoint]


class RankingRow(BaseModel):
    ticker_symbol: str
    market_rank: int | None
    overall_score: float | None
    status: str
    confidence: float
    classification: str | None
    value_trap_risk: int | None
    compounder_score: float | None
    sector: str | None = None


class RankingPage(BaseModel):
    as_of: date_type
    model: str
    items: list[RankingRow]
    next_cursor: str | None = None
    total: int


class SectorRow(BaseModel):
    sector: str
    members: int
    median_value: float | None


class SectorsOut(BaseModel):
    as_of: date_type
    metric: str
    sectors: list[SectorRow]


class BacktestRow(BaseModel):
    run_id: int
    name: str
    purpose: str
    model: str
    start_date: date_type
    end_date: date_type
    top_n: int
    cost_rate: float
    segments: int
    status: str
    linked_total_return: Measure
    first_segment: dict[str, Any]


class BacktestPage(BaseModel):
    items: list[BacktestRow]
    next_cursor: str | None = None
    total: int


class NarrativeOut(BaseModel):
    ticker_symbol: str
    as_of: date_type | None
    status: str
    reason: str | None
    narrative: str | None
    model: str | None
    prompt_version: str | None
    context_hash: str | None
    created_at: str | None


__all__ = [
    "BacktestPage",
    "BacktestRow",
    "BlockOut",
    "HistoryOut",
    "HistoryPoint",
    "Measure",
    "NarrativeOut",
    "RankingPage",
    "RankingRow",
    "ResearchProfileOut",
    "SectorRow",
    "SectorsOut",
    "StockPage",
    "StockSummary",
]
