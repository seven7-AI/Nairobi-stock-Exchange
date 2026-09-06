"""Computed indicators for a ticker, and the indicator feasibility catalogue.

The feasibility endpoint answers "which of the catalogued indicators can this
platform actually compute today" — the same question the CLI's
``check-feasibility`` command answers, through the same service.

    codegraph explore "indicators views.py analyze_feasibility get_latest_snapshot"
"""

from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends, Query

from app.web.api.deps import CurrentUser, SessionDep, SettingsDep
from app.web.api.routers.indicators.schema import (
    FeasibilityReport,
    FeasibilityRow,
    IndicatorSnapshotRead,
    TickerIndicators,
)
from app.web.core.exceptions import ResourceNotFoundError
from app.web.core.security import RESEARCH_ROLES, require_roles
from app.web.db.services import instrument_service
from app.web.services.indicators.feasibility import analyze_feasibility, summarize_feasibility
from app.web.services.indicators.registry import build_indicator_map, parse_indicators

router = APIRouter(prefix="/indicators", tags=["indicators"])

ResearchUser = Depends(require_roles(*RESEARCH_ROLES))


@router.get("/feasibility", response_model=FeasibilityReport)
async def read_feasibility(
    settings: SettingsDep, current_user: CurrentUser = ResearchUser
) -> FeasibilityReport:
    """Which catalogued indicators are computable with the data available."""
    definitions = parse_indicators(settings.indicators_file)
    records = analyze_feasibility(definitions)
    summary = summarize_feasibility(records)
    return FeasibilityReport(
        calculable=summary.get("calculable", 0),
        partially_calculable=summary.get("partially_calculable", 0),
        not_calculable=summary.get("not_calculable", 0),
        total=len(records),
        categories=len(build_indicator_map(definitions)),
        rows=[
            FeasibilityRow(
                indicator=record.indicator,
                category=record.category,
                status=record.status,
                source=record.source,
                missing_data=list(record.missing_data),
                notes=record.notes,
            )
            for record in records
        ],
    )


@router.get("/{ticker_symbol}", response_model=TickerIndicators)
async def read_indicators(
    ticker_symbol: str,
    session: SessionDep,
    as_of: date_type | None = Query(default=None, description="Defaults to the latest snapshot"),
    current_user: CurrentUser = ResearchUser,
) -> TickerIndicators:
    """Indicator snapshot for one instrument."""
    instrument = await instrument_service.get_instrument_by_ticker(session, ticker_symbol)
    if instrument is None:
        raise ResourceNotFoundError(f"No instrument found for ticker {ticker_symbol.upper()}.")

    snapshot = (
        await instrument_service.get_snapshot(session, instrument.id, as_of)
        if as_of is not None
        else await instrument_service.get_latest_snapshot(session, instrument.id)
    )
    if snapshot is None:
        raise ResourceNotFoundError(
            f"No indicator snapshot for {instrument.ticker_symbol}"
            + (f" on {as_of.isoformat()}." if as_of else ".")
        )
    return TickerIndicators(
        ticker_symbol=instrument.ticker_symbol,
        company_name=instrument.company_name,
        snapshot=IndicatorSnapshotRead.model_validate(snapshot),
    )


__all__ = ["router"]
