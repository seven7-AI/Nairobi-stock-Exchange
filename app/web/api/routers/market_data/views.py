"""Market data — latest quotes and daily price history.

History is served newest-first so a cursor walks backwards through time, which
is the direction clients actually read it.

    codegraph explore "market_data views.py list_price_bars get_latest_price_bar"
"""

from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.web.api.deps import CurrentUser, MarketDataSourceDep, SessionDep
from app.web.api.pagination import Cursor, CursorPage, PageSize, decode_cursor
from app.web.api.routers.market_data.schema import (
    HistoryCoverage,
    MarketDataSourceRead,
    PriceBarRead,
    QuoteRead,
    ScrapedRow,
    SourceTableRead,
)
from app.web.core.exceptions import ResourceNotFoundError
from app.web.core.security import MARKET_DATA_ROLES, require_roles
from app.web.db.services import instrument_service
from app.web.services.market_data.sources import NseScraperSource
from app.web.utils.datetime_utils import cursor_date, cursor_str

router = APIRouter(prefix="/market-data", tags=["market-data"])

MarketUser = Depends(require_roles(*MARKET_DATA_ROLES))

#: Observation counts the indicator layer needs for each window.
WEEKLY_WINDOW = 5
MONTHLY_WINDOW = 22
MA_200_WINDOW = 200

#: One row per ticker upstream, so this comfortably covers the whole exchange.
SCRAPED_FETCH_LIMIT = 1000


@router.get("/source", response_model=MarketDataSourceRead)
async def read_source(
    source: MarketDataSourceDep, current_user: CurrentUser = MarketUser
) -> MarketDataSourceRead:
    """Where the raw NSE data comes from, and whether it is currently trustworthy.

    The source is the ``~/nse-stock-scraper`` project's daily SQLite output. This
    endpoint is the answer to "is today's market data actually there and fresh",
    which matters before anyone builds analysis on top of it.
    """
    health = source.health_check()
    return MarketDataSourceRead(
        name=health.name,
        status=health.status,
        reachable=health.reachable,
        location=health.location,
        detail=health.detail,
        newest_scraped_at=health.newest_scraped_at,
        age_hours=health.age_hours,
        is_stale=health.is_stale,
        quality_ok=health.quality_ok,
        tables=[
            SourceTableRead(
                name=table.name,
                row_count=table.row_count,
                newest_scraped_at=table.newest_scraped_at,
            )
            for table in health.tables
        ],
    )


@router.get("/scraped", response_model=CursorPage[ScrapedRow])
async def read_scraped_rows(
    source: MarketDataSourceDep,
    page_size: PageSize = 50,
    cursor: Cursor = None,
    current_user: CurrentUser = MarketUser,
) -> CursorPage[ScrapedRow]:
    """The latest scraped rows, exactly as the scraper produced them.

    No transformation beyond decoding the JSON columns the scraper stores as
    text. This is the raw surface future indicators, agents and research will
    build on.
    """
    rows = source.fetch_latest_rows(limit=SCRAPED_FETCH_LIMIT)
    after_ticker = cursor_str(decode_cursor(cursor), "ticker_symbol") if cursor else None

    # The source returns one row per ticker, so a stable ticker ordering gives a
    # cursor that cannot skip or repeat rows between pages.
    ordered = sorted(rows, key=lambda row: str(row.get("ticker_symbol", "")))
    if after_ticker is not None:
        ordered = [r for r in ordered if str(r.get("ticker_symbol", "")) > after_ticker]

    items = [ScrapedRow.model_validate(row) for row in ordered[: page_size + 1]]
    return CursorPage.build(
        items,
        page_size=page_size,
        cursor_for=lambda item: {"ticker_symbol": item.ticker_symbol},
    )


@router.get("/{ticker_symbol}/growth", response_class=Response)
async def read_growth_chart(
    ticker_symbol: str, source: MarketDataSourceDep, current_user: CurrentUser = MarketUser
) -> Response:
    """The stock-growth chart (2007 → latest scrape) as a PNG.

    Same figure `nse-analysis plot-stock` writes to diagrams/stock-growth/, built
    from the same canonical timeline. Gaps are gaps; prices are unadjusted and
    suspected corporate actions are marked.
    """
    from app.web.services.visualizations import figure_for, load_growth_series, render_png

    if not isinstance(source, NseScraperSource):
        raise ResourceNotFoundError("Growth charts need the canonical timeline source.")
    series = load_growth_series(source, ticker_symbol)  # raises ResourceNotFoundError -> 404
    return Response(content=render_png(figure_for(series)), media_type="image/png")


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

    change = bar.close_price - bar.previous_close if bar.previous_close is not None else None
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
