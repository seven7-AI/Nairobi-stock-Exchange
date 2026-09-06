"""Market analytics — gainers, losers, trend, and sector performance.

Built from persisted ``indicator_snapshots``, so a query is a single indexed
read rather than a recomputation, and the numbers match whatever the report
for that date said.

    codegraph explore "analytics views.py classify_market_insights list_snapshots_for_date"
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.web.api.deps import CurrentUser, SessionDep
from app.web.api.routers.analytics.schema import (
    MarketSummary,
    MoverRow,
    SectorPerformance,
    SectorPerformanceReport,
)
from app.web.core.exceptions import ResourceNotFoundError
from app.web.core.security import RESEARCH_ROLES, require_roles
from app.web.db.services import instrument_service
from app.web.services.indicators.calculator import (
    classify_market_insights,
    classify_monthly_market_insights,
    classify_weekly_market_insights,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])

ResearchUser = Depends(require_roles(*RESEARCH_ROLES))

#: horizon -> (classifier, snapshot column, mean key)
HORIZONS: dict[str, tuple[Any, str, str]] = {
    "1d": (classify_market_insights, "price_change_1d_pct", "mean_daily_change_pct"),
    "1w": (classify_weekly_market_insights, "price_change_1w_pct", "mean_weekly_change_pct"),
    "1m": (classify_monthly_market_insights, "price_change_1m_pct", "mean_monthly_change_pct"),
}

Horizon = Query(default="1d", pattern="^(1d|1w|1m)$", description="1d, 1w or 1m")


async def _rows_for(
    session: SessionDep, as_of: date_type | None
) -> tuple[date_type, list[dict[str, Any]]]:
    """Load snapshots for a date as the plain dicts the classifiers expect."""
    resolved = as_of or await instrument_service.latest_snapshot_date(session)
    if resolved is None:
        raise ResourceNotFoundError(
            "No indicator snapshots exist yet. Run the daily pipeline first."
        )

    pairs = await instrument_service.list_snapshots_for_date(session, resolved)
    if not pairs:
        raise ResourceNotFoundError(f"No indicator snapshots for {resolved.isoformat()}.")

    def _float(value: Any) -> float | None:
        return float(value) if value is not None else None

    return resolved, [
        {
            "ticker_symbol": instrument.ticker_symbol,
            "company_name": instrument.company_name,
            "sector": instrument.sector,
            "stock_price": _float(snapshot.close_price),
            "price_change_1d_pct": _float(snapshot.price_change_1d_pct),
            "price_change_1w_pct": _float(snapshot.price_change_1w_pct),
            "price_change_1m_pct": _float(snapshot.price_change_1m_pct),
        }
        for snapshot, instrument in pairs
    ]


def _movers(records: list[dict[str, Any]], change_column: str) -> list[MoverRow]:
    return [
        MoverRow(
            ticker_symbol=str(record.get("ticker_symbol", "")),
            company_name=record.get("company_name"),
            sector=record.get("sector"),
            stock_price=record.get("stock_price"),
            change_pct=record.get(change_column),
        )
        for record in records
    ]


@router.get("/market-summary", response_model=MarketSummary)
async def read_market_summary(
    session: SessionDep,
    horizon: str = Horizon,
    as_of: date_type | None = Query(default=None),
    current_user: CurrentUser = ResearchUser,
) -> MarketSummary:
    """Trend, mean change, and the top movers for a horizon."""
    classifier, change_column, mean_key = HORIZONS[horizon]
    resolved, records = await _rows_for(session, as_of)
    summary = classifier(records)
    return MarketSummary(
        as_of_date=resolved,
        horizon=horizon,
        market_trend=summary["market_trend"],
        mean_change_pct=summary.get(mean_key),
        ranked_instruments=summary.get("ranked_instruments", 0),
        excluded_missing_change=summary.get("excluded_missing_change", 0),
        top_gainers=_movers(summary.get("top_gainers", []), change_column),
        top_losers=_movers(summary.get("top_losers", []), change_column),
    )


@router.get("/sectors", response_model=SectorPerformanceReport)
async def read_sector_performance(
    session: SessionDep,
    horizon: str = Horizon,
    as_of: date_type | None = Query(default=None),
    current_user: CurrentUser = ResearchUser,
) -> SectorPerformanceReport:
    """Mean change per sector, with the best and worst instrument in each."""
    _, change_column, _ = HORIZONS[horizon]
    resolved, records = await _rows_for(session, as_of)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record.get("sector") or "Unknown", []).append(record)

    sectors: list[SectorPerformance] = []
    for sector, members in sorted(grouped.items()):
        # Same rule as the market rankings: absent changes are excluded, not zeroed.
        rated = [m for m in members if m.get(change_column) is not None]
        mean = sum(float(m[change_column]) for m in rated) / len(rated) if rated else None
        ordered = sorted(rated, key=lambda m: float(m[change_column]), reverse=True)
        sectors.append(
            SectorPerformance(
                sector=sector,
                instrument_count=len(members),
                mean_change_pct=mean,
                best_ticker=ordered[0]["ticker_symbol"] if ordered else None,
                worst_ticker=ordered[-1]["ticker_symbol"] if ordered else None,
            )
        )

    return SectorPerformanceReport(as_of_date=resolved, horizon=horizon, sectors=sectors)


__all__ = ["router"]
