"""Market data — latest quotes and daily price history.

History is served newest-first so a cursor walks backwards through time, which
is the direction clients actually read it.

    codegraph explore "market_data views.py list_price_bars get_latest_price_bar"
"""

from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends, Query

from app.web.api.deps import CurrentUser, SessionDep
from app.web.api.pagination import Cursor, CursorPage, PageSize, decode_cursor
from app.web.api.routers.market_data.schema import (
    HistoryCoverage,
    PriceBarRead,
    QuoteRead,
)
from app.web.core.exceptions import ResourceNotFoundError
from app.web.core.security import MARKET_DATA_ROLES, require_roles
from app.web.db.services import instrument_service
from app.web.utils.datetime_utils import cursor_date

router = APIRouter(prefix="/market-data", tags=["market-data"])

MarketUser = Depends(require_roles(*MARKET_DATA_ROLES))

#: Observation counts the indicator layer needs for each window.
WEEKLY_WINDOW = 5
MONTHLY_WINDOW = 22
MA_200_WINDOW = 200


@router.get("/{ticker_symbol}/quote", response_model=QuoteRead)
async def read_quote(
    ticker_symbol: str, session: SessionDep, current_user: CurrentUser = MarketUser
) -> QuoteRead:
    """Latest known close for one instrument."""
    instrument = await instrument_service.get_instrument_by_ticker(session, ticker_symbol)
    if instrument is None:
        raise ResourceNotFoundError(f"No instrument found for ticker {ticker_symbol.upper()}.")

    bar = await instrument_service.get_latest_price_bar(session, instrument.id)
    if bar is None:
        raise ResourceNotFoundError(f"No price history for {instrument.ticker_symbol}.")

    change = (
        bar.close_price - bar.previous_close if bar.previous_close is not None else None
    )
    change_pct = (
        float(change / bar.previous_close * 100)
        if change is not None and bar.previous_close
        else None
    )
    return QuoteRead(
        instrument_id=instrument.id,
        ticker_symbol=instrument.ticker_symbol,
        company_name=instrument.company_name,
        sector=instrument.sector,
        bar_date=bar.bar_date,
        close_price=bar.close_price,
        previous_close=bar.previous_close,
        change=change,
        change_pct=change_pct,
    )


@router.get("/{ticker_symbol}/history", response_model=CursorPage[PriceBarRead])
async def read_history(
    ticker_symbol: str,
    session: SessionDep,
    page_size: PageSize = 50,
    cursor: Cursor = None,
    start_date: date_type | None = Query(default=None, description="Earliest bar to include"),
    current_user: CurrentUser = MarketUser,
) -> CursorPage[PriceBarRead]:
    """Daily price history, most recent first."""
    instrument = await instrument_service.get_instrument_by_ticker(session, ticker_symbol)
    if instrument is None:
        raise ResourceNotFoundError(f"No instrument found for ticker {ticker_symbol.upper()}.")

    before_date = cursor_date(decode_cursor(cursor)) if cursor else None
    rows = await instrument_service.list_price_bars(
        session,
        instrument.id,
        limit=page_size + 1,
        before_date=before_date,
        start_date=start_date,
    )
    items = [PriceBarRead.model_validate(row) for row in rows]
    return CursorPage.build(
        items,
        page_size=page_size,
        cursor_for=lambda item: {"bar_date": item.bar_date.isoformat()},
    )


@router.get("/{ticker_symbol}/coverage", response_model=HistoryCoverage)
async def read_coverage(
    ticker_symbol: str, session: SessionDep, current_user: CurrentUser = MarketUser
) -> HistoryCoverage:
    """How much history exists, and therefore which indicators are computable."""
    instrument = await instrument_service.get_instrument_by_ticker(session, ticker_symbol)
    if instrument is None:
        raise ResourceNotFoundError(f"No instrument found for ticker {ticker_symbol.upper()}.")

    count = await instrument_service.count_price_bars(session, instrument.id)
    return HistoryCoverage(
        ticker_symbol=instrument.ticker_symbol,
        bar_count=count,
        supports_weekly=count >= WEEKLY_WINDOW,
        supports_monthly=count >= MONTHLY_WINDOW,
        supports_ma_200=count >= MA_200_WINDOW,
    )


__all__ = ["router"]
