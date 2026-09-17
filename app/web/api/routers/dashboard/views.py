"""The public dashboard API - **unauthenticated, read-only, by design.**

This router is the single exception to the "every protected endpoint declares its
roles" rule (CLAUDE.md §2). It serves derived analytics and market prices from the
two SQLite files only: it never touches Postgres or Redis, never imports a platform
model, and never emits a setting, a filesystem path or a provenance record. It is
mounted only when ``Settings.dashboard_public`` is true.

Every handler reads through ``app.web.services.dashboard`` in the threadpool; the
payloads are cached per store version (``X-Store-Version``), and ``/status/version``
is the cheap poll the SPA uses to learn that something changed.

    codegraph explore "dashboard views.py build_status build_overview build_market"
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any, Literal

from fastapi import APIRouter, Path, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from app.web.api.deps import MarketDataSourceDep, SettingsDep
from app.web.api.routers.dashboard.schema import (
    MarketOut,
    OverviewOut,
    PriceHistoryOut,
    StatementsOut,
    StatusOut,
    StockDetailOut,
    StockListPage,
    VersionOut,
)
from app.web.config import Settings
from app.web.core.exceptions import ExternalServiceError, ResourceNotFoundError
from app.web.services.dashboard import (
    build_market,
    build_overview,
    build_status,
    build_version,
    get_dashboard_cache,
    store_stamp,
)
from app.web.services.dashboard.stocks import (
    Interval,
    PriceRange,
    SortKey,
    build_stock_detail,
    list_stocks,
    price_history,
    statement_summary,
)
from app.web.services.market_data.sources.base import MarketDataSource
from app.web.services.market_data.sources.nse_scraper import NseScraperSource

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

AsOf = Query(default=None, description="Result date (defaults to the latest stored)")
Limit = Query(default=50, ge=1, le=200)
Cursor = Query(default=None, description="Opaque cursor from the previous page")
Search = Query(default=None, max_length=32, description="Ticker, company or sector contains")
Ticker = Path(pattern=r"^\^?[A-Za-z0-9.&-]{1,24}$")
VERSION_HEADER = "X-Store-Version"


def _scraper(source: MarketDataSource) -> NseScraperSource:
    if not isinstance(source, NseScraperSource):
        raise ExternalServiceError("The dashboard needs the NSE scraper source.")
    return source


def _cached(settings: Settings, key: tuple[Any, ...], compute: Any) -> tuple[Any, str]:
    stamp = store_stamp(settings)
    value = get_dashboard_cache(settings).get_or_compute(key, stamp, compute)
    return value, stamp.version


def _no_store(response: Response, version: str) -> None:
    response.headers[VERSION_HEADER] = version
    response.headers["Cache-Control"] = "no-store"


@router.get("/status/version", response_model=VersionOut)
async def status_version(
    request: Request, response: Response, settings: SettingsDep, source: MarketDataSourceDep
) -> Any:
    """The cheap poll: file stamps and the two dates that matter. Honours If-None-Match."""
    scraper = _scraper(source)
    stamp = store_stamp(settings)
    etag = f'W/"{stamp.version}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, VERSION_HEADER: stamp.version})
    version, _ = await run_in_threadpool(
        _cached, settings, ("version",), lambda: build_version(settings, scraper, stamp)
    )
    response.headers["ETag"] = etag
    response.headers[VERSION_HEADER] = stamp.version
    response.headers["Cache-Control"] = "no-cache"
    return VersionOut(**version.as_dict())


@router.get("/status", response_model=StatusOut)
async def status(
    response: Response, settings: SettingsDep, source: MarketDataSourceDep
) -> StatusOut:
    """Store revision and tables, each pipeline's last run and last success, the
    scraper's health, watermarks, the cron chain, the model registry."""
    scraper = _scraper(source)
    data, version = await run_in_threadpool(
        _cached, settings, ("status",), lambda: build_status(settings, scraper)
    )
    _no_store(response, version)
    return StatusOut(**data.as_dict())


@router.get("/overview", response_model=OverviewOut)
async def overview(
    response: Response, settings: SettingsDep, source: MarketDataSourceDep
) -> OverviewOut:
    """Counts and dates: what the engine knows, has calculated and can forecast today."""
    scraper = _scraper(source)

    def compute() -> Any:
        status, _ = _cached(settings, ("status",), lambda: build_status(settings, scraper))
        return build_overview(settings, scraper, status)

    data, version = await run_in_threadpool(_cached, settings, ("overview",), compute)
    _no_store(response, version)
    return OverviewOut(**data.as_dict())


@router.get("/market", response_model=MarketOut)
async def market(
    response: Response,
    settings: SettingsDep,
    source: MarketDataSourceDep,
    as_of: date_type | None = AsOf,
) -> MarketOut:
    """Latest quotes for every classified equity, sector medians for 1d/1w/1m, movers,
    and the benchmark indices' availability."""
    scraper = _scraper(source)
    data, version = await run_in_threadpool(
        _cached, settings, ("market", as_of), lambda: build_market(settings, scraper, as_of=as_of)
    )
    if data is None:
        raise ResourceNotFoundError("No market metrics stored yet. Run the daily pipeline first.")
    _no_store(response, version)
    return MarketOut(**data.as_dict())


@router.get("/stocks", response_model=StockListPage)
async def stocks(
    response: Response,
    settings: SettingsDep,
    source: MarketDataSourceDep,
    q: str | None = Search,
    sector: str | None = Query(default=None, max_length=64),
    sort: SortKey = "ticker",
    order: Literal["asc", "desc"] = "asc",
    limit: int = Limit,
    cursor: str | None = Cursor,
) -> StockListPage:
    """Every classified equity with quote, multiples, factor percentiles and ranking -
    searchable, sortable (non-known values always last), cursor-paginated."""
    scraper = _scraper(source)
    page = await run_in_threadpool(
        list_stocks,
        settings,
        scraper,
        q=q,
        sector=sector,
        sort=sort,
        order=order,
        limit=limit,
        cursor=cursor,
    )
    _no_store(response, store_stamp(settings).version)
    return StockListPage(**page.as_dict())


@router.get("/stocks/{ticker}", response_model=StockDetailOut)
async def stock_detail(
    response: Response,
    settings: SettingsDep,
    source: MarketDataSourceDep,
    ticker: str = Ticker,
    as_of: date_type | None = AsOf,
) -> StockDetailOut:
    """The research profile plus quote, a year of prices with gaps, statements, sector
    comparison, company facts and the (unavailable) geographic block."""
    scraper = _scraper(source)
    symbol = ticker.upper()
    data, version = await run_in_threadpool(
        _cached,
        settings,
        ("stock", symbol, as_of),
        lambda: build_stock_detail(settings, scraper, symbol, as_of=as_of),
    )
    if data is None:
        raise ResourceNotFoundError(f"{symbol} is not an instrument in the analytics store.")
    _no_store(response, version)
    return StockDetailOut(**data.as_dict())


@router.get("/stocks/{ticker}/prices", response_model=PriceHistoryOut)
async def stock_prices(
    response: Response,
    settings: SettingsDep,
    source: MarketDataSourceDep,
    ticker: str = Ticker,
    range: PriceRange = "1y",
    interval: Interval = "daily",
) -> PriceHistoryOut:
    """Closes with every gap longer than the engine's threshold listed explicitly."""
    scraper = _scraper(source)
    symbol = ticker.upper()
    data, version = await run_in_threadpool(
        _cached,
        settings,
        ("prices", symbol, range, interval),
        lambda: price_history(settings, scraper, symbol, range_=range, interval=interval),
    )
    if data is None:
        raise ResourceNotFoundError(f"{symbol} is not an instrument in the analytics store.")
    _no_store(response, version)
    return PriceHistoryOut(**data.as_dict())


@router.get("/stocks/{ticker}/statements", response_model=StatementsOut)
async def stock_statements(
    response: Response,
    settings: SettingsDep,
    source: MarketDataSourceDep,
    ticker: str = Ticker,
    periods: int = Query(default=10, ge=1, le=20),
    as_of: date_type | None = AsOf,
) -> StatementsOut:
    """One row per fiscal year as known on the date: revenue, net income, EPS, DPS,
    equity, total assets, operating and free cash flow."""
    scraper = _scraper(source)
    symbol = ticker.upper()
    known = await run_in_threadpool(lambda: symbol in _tickers(settings))
    if not known:
        raise ResourceNotFoundError(f"{symbol} is not an instrument in the analytics store.")
    data, version = await run_in_threadpool(
        _cached,
        settings,
        ("statements", symbol, periods, as_of),
        lambda: statement_summary(scraper, symbol, periods=periods, as_of=as_of),
    )
    _no_store(response, version)
    return StatementsOut(**data.as_dict())


def _tickers(settings: Settings) -> set[str]:
    from app.web.db.analytics import analytics_session
    from app.web.db.analytics.services.classifications import load_classifications
    from app.web.services.analytics.classification.lookup import ClassificationIndex

    with analytics_session(settings) as session:
        return set(ClassificationIndex(load_classifications(session)).tickers)


__all__ = ["router"]
