"""The analytics table: every ranked instrument on a date with its composite score,
factor scores and percentiles, and the sector- and market-relative return metrics.

    codegraph explore "build_analytics_table AnalyticsTable load_rankings load_factor_scores"
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import StockRanking
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.factor_scores import load_factor_scores
from app.web.db.analytics.services.market_metrics import load_metrics
from app.web.db.analytics.services.stock_rankings import load_rankings
from app.web.db.analytics.services.summaries import latest_as_of, latest_known_as_of
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.dashboard.common import from_row, measure, unavailable

RELATIVE_METRICS: tuple[str, ...] = tuple(
    f"relative_{w}_vs_{scope}" for w in ("1m", "3m", "6m", "12m") for scope in ("market", "sector")
)


@dataclass(frozen=True)
class AnalyticsRow:
    ticker_symbol: str
    sector: str | None
    industry: str | None
    overall: dict[str, Any]
    classification: str | None
    confidence: float
    market_rank: int | None
    sector_rank: int | None
    industry_rank: int | None
    value_trap_risk: int | None
    compounder_score: float | None
    positive_factors: list[str]
    negative_factors: list[str]
    factors: dict[str, dict[str, Any]]
    relative: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class AnalyticsTable:
    as_of: date
    model: str
    available_dates: list[date]
    factor_names: list[str]
    rows: list[AnalyticsRow]
    coverage: dict[str, dict[str, int]]
    latest_known_as_of: date | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def ranking_dates(session: Any) -> list[date]:
    """Every date with a stored ranking, newest first (the as-of selector)."""
    from sqlalchemy import select

    rows = session.execute(
        select(StockRanking.as_of_date).distinct().order_by(StockRanking.as_of_date.desc())
    ).scalars()
    return list(rows)


def build_analytics_table(
    settings: Settings, *, as_of: date | None = None, sector: str | None = None
) -> AnalyticsTable | None:
    with analytics_session(settings) as session:
        day = as_of or latest_as_of(session, StockRanking)
        if day is None:
            return None
        index = ClassificationIndex(load_classifications(session))
        rankings = load_rankings(session, as_of_date=day)
        if not rankings:
            return None
        scores: dict[str, dict[str, dict[str, Any]]] = {}
        coverage: dict[str, dict[str, int]] = {}
        factor_names: list[str] = []
        for f in load_factor_scores(session, as_of_date=day):
            if f.factor not in factor_names:
                factor_names.append(f.factor)
            coverage.setdefault(f.factor, {})
            coverage[f.factor][str(f.status)] = coverage[f.factor].get(str(f.status), 0) + 1
            scores.setdefault(f.ticker_symbol, {})[f.factor] = {
                "score": measure(f.score, str(f.status), f.reason),
                "coverage": f.coverage,
                "percentile_market": f.percentile_market,
                "percentile_sector": f.percentile_sector,
                "percentile_industry": f.percentile_industry,
            }
        relative: dict[str, dict[str, dict[str, Any]]] = {}
        for r in load_metrics(session, as_of_date=day):
            if r.metric in RELATIVE_METRICS:
                relative.setdefault(r.ticker_symbol, {})[r.metric] = from_row(r)
        rows: list[AnalyticsRow] = []
        for rk in rankings:
            assignment = index.sector_for(rk.ticker_symbol, day)
            if sector and (assignment is None or assignment.sector_label.lower() != sector.lower()):
                continue
            explanation = rk.explanation or {}
            rows.append(
                AnalyticsRow(
                    rk.ticker_symbol,
                    assignment.sector_label if assignment else None,
                    assignment.industry if assignment else None,
                    measure(rk.overall_score, str(rk.status), rk.reason),
                    rk.classification,
                    rk.confidence,
                    rk.market_rank,
                    rk.sector_rank,
                    rk.industry_rank,
                    rk.value_trap_risk,
                    rk.compounder_score,
                    list(explanation.get("positive_factors") or []),
                    list(explanation.get("negative_factors") or []),
                    {
                        name: scores.get(rk.ticker_symbol, {}).get(
                            name,
                            {
                                "score": unavailable(f"{name}: not scored on {day}"),
                                "coverage": 0.0,
                                "percentile_market": None,
                                "percentile_sector": None,
                                "percentile_industry": None,
                            },
                        )
                        for name in factor_names
                    },
                    {
                        name: relative.get(rk.ticker_symbol, {}).get(
                            name, unavailable(f"{name}: not computed on {day}")
                        )
                        for name in RELATIVE_METRICS
                    },
                )
            )
        rows.sort(key=lambda r: (r.market_rank is None, r.market_rank or 0, r.ticker_symbol))
        model = f"{rankings[0].model_name} v{rankings[0].model_version}"
        return AnalyticsTable(
            day,
            model,
            ranking_dates(session),
            factor_names,
            rows,
            coverage,
            latest_known_as_of(session, StockRanking),
        )


__all__ = [
    "RELATIVE_METRICS",
    "AnalyticsRow",
    "AnalyticsTable",
    "build_analytics_table",
    "ranking_dates",
]
