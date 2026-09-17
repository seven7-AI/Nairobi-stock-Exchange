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
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from app.web.api.deps import MarketDataSourceDep, SettingsDep
from app.web.api.routers.dashboard.schema import MarketOut, OverviewOut, StatusOut, VersionOut
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
from app.web.services.market_data.sources.base import MarketDataSource
from app.web.services.market_data.sources.nse_scraper import NseScraperSource

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

AsOf = Query(default=None, description="Result date (defaults to the latest stored)")
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


__all__ = ["router"]
