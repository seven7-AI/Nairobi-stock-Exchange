"""The public dashboard API against a throwaway store built from the fixture prices.

No Postgres: these tests build their own app and never mint a token - the point of
the router is that it needs none.

    codegraph explore "dashboard views.py build_status build_overview build_market"
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.web.config import Settings
from app.web.services.analytics.classification.service import classify_instruments
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.dashboard import reset_dashboard_cache
from app.web.services.jobs import run_pipeline
from app.web.services.market_data.sources.nse_scraper import NseScraperSource

pytestmark = [pytest.mark.integration]

BASE = "/api/v1/dashboard"
AS_OF = date(2024, 12, 31)  # the last day with a full set of known market metrics


@pytest.fixture(scope="module")
def dashboard_store(fixture_db_path: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("dashboard")
    settings = Settings(
        NSE_SCRAPER_DB_PATH=str(fixture_db_path),
        NSE_SCRAPER_PATH=str(root / "scraper"),
        ANALYTICS_DB_PATH=str(root / "analytics.sqlite3"),
    )
    upgrade_analytics_db(settings.analytics_db_path)
    source = NseScraperSource(settings)
    classify_instruments(settings, source)
    run_pipeline(settings, source, "daily", as_of=AS_OF)
    run_pipeline(settings, source, "fundamentals", as_of=AS_OF)
    return settings.analytics_db_path


@pytest.fixture
async def dashboard_client(
    dashboard_store: Path, fixture_db_path: Path
) -> AsyncIterator[AsyncClient]:
    from app.web.config import get_settings
    from app.web.main import create_app

    keys = ("ANALYTICS_DB_PATH", "NSE_SCRAPER_DB_PATH", "NSE_SCRAPER_PATH", "DASHBOARD_PUBLIC")
    previous = {k: os.environ.get(k) for k in keys}
    os.environ["ANALYTICS_DB_PATH"] = str(dashboard_store)
    os.environ["NSE_SCRAPER_DB_PATH"] = str(fixture_db_path)
    os.environ["NSE_SCRAPER_PATH"] = str(fixture_db_path.parent)
    os.environ["DASHBOARD_PUBLIC"] = "true"
    get_settings.cache_clear()
    reset_dashboard_cache()
    app = create_app()
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client,
        app.router.lifespan_context(app),
    ):
        yield http_client
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    get_settings.cache_clear()
    reset_dashboard_cache()


ENDPOINTS = ("/status/version", "/status", "/overview", "/market")


@pytest.mark.parametrize("path", ENDPOINTS)
async def test_every_endpoint_is_public(dashboard_client: AsyncClient, path: str) -> None:
    response = await dashboard_client.get(BASE + path)
    assert response.status_code == 200, response.text[:300]
    assert response.headers["x-store-version"]
    body = response.text
    assert "/home/" not in body and "/tmp/" not in body  # no filesystem paths leave the process


async def test_version_is_cheap_and_conditional(dashboard_client: AsyncClient) -> None:
    first = await dashboard_client.get(f"{BASE}/status/version")
    body = first.json()
    assert body["version"] == first.headers["x-store-version"]
    assert body["latest_market_date"] == "2026-09-13"  # the fixture's newest scrape day
    assert body["latest_analytics_date"] == AS_OF.isoformat()
    etag = first.headers["etag"]
    again = await dashboard_client.get(f"{BASE}/status/version", headers={"If-None-Match": etag})
    assert again.status_code == 304


async def test_version_changes_when_the_store_changes(
    dashboard_client: AsyncClient, dashboard_store: Path
) -> None:
    from app.web.services.dashboard.cache import file_mtime_ns

    before = (await dashboard_client.get(f"{BASE}/status/version")).json()["version"]
    # newer than the file *and* its WAL journal, which is what the stamp follows
    bumped = file_mtime_ns(dashboard_store) + 1_000_000_000
    os.utime(dashboard_store, ns=(bumped, bumped))
    after = (await dashboard_client.get(f"{BASE}/status/version")).json()["version"]
    assert after != before


async def test_status_reports_store_pipelines_source_and_cron(
    dashboard_client: AsyncClient,
) -> None:
    body = (await dashboard_client.get(f"{BASE}/status")).json()
    assert body["store"]["migrated"] is True and body["store"]["revision"] == body["store"]["head"]
    assert body["store"]["tables"]["market_metrics"] > 0
    pipelines = {p["pipeline"]: p for p in body["pipelines"]}
    assert set(pipelines) == {"daily", "fundamentals", "weekly"}
    daily = pipelines["daily"]
    assert (
        daily["last_run"]["status"] == "succeeded"
        and daily["last_success"]["as_of"] == AS_OF.isoformat()
    )
    assert [s["name"] for s in daily["steps"]][:2] == ["data_quality", "returns"]
    assert pipelines["weekly"]["last_run"] is None  # never run on this store
    assert daily["schedule"] == "40 09 * * *" and daily["timezone"] == "Africa/Nairobi"
    assert body["source"]["status"] in ("ok", "stale") and "location" not in body["source"]
    assert body["watermarks"]["observations"].startswith("2026-09-13:")
    assert [c["pipeline"] for c in body["cron"]] == ["scrape", "daily", "fundamentals", "weekly"]
    assert any(j["job_name"] == "pipeline:daily" for j in body["jobs"])
    assert {m["name"] for m in body["models"]} >= {"factor-model"}


async def test_overview_counts_are_honest(dashboard_client: AsyncClient) -> None:
    body = (await dashboard_client.get(f"{BASE}/overview")).json()
    assert body["latest_market_date"] == "2026-09-13" and body["stocks_with_data_on_latest"] == 8
    assert (
        body["classified_universe"] == body["tracked_stocks"] == 10
    )  # 12 instruments minus 2 indices
    assert body["scraped_stocks"] == 8
    assert body["store_migrated"] is True
    rankings = body["analytics"]["stock_rankings"]
    assert rankings["as_of"] == AS_OF.isoformat()
    # point-in-time universe on 2024-12-31: the two instruments delisted years earlier
    # (ACCS 2012, KENO 2019) have no ranking row; the rest do, known or not
    assert rankings["counts"].get("known", 0) >= 1 and sum(rankings["counts"].values()) <= 8
    # the weekly pipeline never ran here: no forecasts at all, and the payload says so
    assert body["forecasts"] == {"as_of": None, "counts": {}, "latest_known_as_of": None}
    assert set(body["open_findings"]) == {"error", "warning", "info"}
    assert body["version"]["latest_analytics_date"] == AS_OF.isoformat()


async def test_market_lists_every_equity_with_statuses(dashboard_client: AsyncClient) -> None:
    body = (await dashboard_client.get(f"{BASE}/market")).json()
    assert body["as_of"] == AS_OF.isoformat() and body["universe"] == 10 == len(body["quotes"])
    quotes = {q["ticker_symbol"]: q for q in body["quotes"]}
    kcb = quotes["KCB"]
    assert kcb["source"] == "stockanalysis_stocks" and kcb["price"]["status"] == "known"
    assert kcb["price"]["value"] == 94.0 and kcb["volume"]["value"] == 375298
    assert kcb["facts"]["industry"] == "Commercial Banks" and kcb["facts"]["founded"] == 1896
    assert kcb["close"]["value"] > 0 and kcb["close_date"] == "2026-09-13"
    # delisted long ago and never scraped: present, honest, not zero
    keno = quotes["KENO"]
    assert keno["source"] == "none" and keno["price"]["status"] == "unavailable"
    assert "last observation 2019-10-11" in keno["price"]["reason"]
    assert keno["volume"]["value"] is None
    # sector medians on the analytics date, every sector listed
    one_day = {s["sector"]: s for s in body["performance"]["1d"]}
    assert one_day and all(s["members"] >= s["known_members"] for s in one_day.values())
    banking = one_day["Banking"]
    assert banking["median"]["status"] == "known" and banking["known_members"] >= 3
    assert set(body["performance"]) == {"1d", "1w", "1m"}
    assert body["coverage"]["return_1d"]["known"] >= 5
    # indices are known on 2024-12-31 (their last day) and carry their level
    assert body["index"]["^NASI"]["status"] == "known" and body["index"]["^NASI"]["last"] > 0
    assert body["index"]["^NASI"]["latest_known_as_of"] == AS_OF.isoformat()
    # movers are ordered and only from tickers with a scraped change
    changes = [q["change_pct"]["value"] for q in body["top_movers"]]
    assert changes == sorted(changes, reverse=True) and all(c is not None for c in changes)


async def test_market_after_the_gap_marks_indices_stale(dashboard_client: AsyncClient) -> None:
    body = (await dashboard_client.get(f"{BASE}/market", params={"as_of": "2026-09-13"})).json()
    # no metrics stored for that date on this store -> sectors all unavailable, still listed
    assert body["as_of"] == "2026-09-13"
    assert all(s["median"]["status"] == "unavailable" for s in body["performance"]["1m"])
    nasi = body["index"]["^NASI"]
    assert nasi["status"] == "unavailable" and "2024-12-31" in nasi["reason"]


async def test_market_404_without_metrics(fixture_db_path: Path, tmp_path: Path) -> None:
    from app.web.config import get_settings
    from app.web.main import create_app

    empty = tmp_path / "empty.sqlite3"
    upgrade_analytics_db(empty)
    previous = {
        k: os.environ.get(k)
        for k in ("ANALYTICS_DB_PATH", "NSE_SCRAPER_DB_PATH", "NSE_SCRAPER_PATH")
    }
    os.environ["ANALYTICS_DB_PATH"] = str(empty)
    os.environ["NSE_SCRAPER_DB_PATH"] = str(fixture_db_path)
    os.environ["NSE_SCRAPER_PATH"] = str(fixture_db_path.parent)
    get_settings.cache_clear()
    reset_dashboard_cache()
    try:
        app = create_app()
        async with (
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
            app.router.lifespan_context(app),
        ):
            assert (await c.get(f"{BASE}/market")).status_code == 404
            overview = (await c.get(f"{BASE}/overview")).json()
            assert overview["tracked_stocks"] == 0  # nothing classified yet
            assert all(
                t["as_of"] is None and t["counts"] == {} for t in overview["analytics"].values()
            )
            assert overview["forecasts"]["as_of"] is None
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        reset_dashboard_cache()


async def test_router_can_be_switched_off(dashboard_store: Path, fixture_db_path: Path) -> None:
    from app.web.config import get_settings
    from app.web.main import create_app

    previous = {k: os.environ.get(k) for k in ("DASHBOARD_PUBLIC", "ANALYTICS_DB_PATH")}
    os.environ["DASHBOARD_PUBLIC"] = "false"
    os.environ["ANALYTICS_DB_PATH"] = str(dashboard_store)
    get_settings.cache_clear()
    try:
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            assert (await c.get(f"{BASE}/overview")).status_code == 404
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


@pytest.mark.realdata
async def test_live_store_overview(live_source: NseScraperSource) -> None:
    """Against the real databases when they exist: the numbers the user sees."""
    from app.web.config import get_settings
    from app.web.main import create_app

    keys = ("ANALYTICS_DB_PATH", "NSE_SCRAPER_DB_PATH", "NSE_SCRAPER_PATH", "DASHBOARD_PUBLIC")
    previous = {k: os.environ.pop(k, None) for k in keys}  # the real files, not a fixture
    get_settings.cache_clear()
    reset_dashboard_cache()
    try:
        settings = get_settings()
        if not settings.analytics_db_path.exists():
            pytest.skip("no live analytics store")
        app = create_app()
        async with (
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
            app.router.lifespan_context(app),
        ):
            overview = (await c.get(f"{BASE}/overview")).json()
            assert overview["tracked_stocks"] >= 60 and overview["store_migrated"]
            assert overview["forecasts"]["latest_known_as_of"] is not None
    finally:
        for key, value in previous.items():
            if value is not None:
                os.environ[key] = value
        get_settings.cache_clear()
        reset_dashboard_cache()
