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

from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.dashboard import reset_dashboard_cache
from app.web.services.market_data.sources.nse_scraper import NseScraperSource

pytestmark = [pytest.mark.integration]

BASE = "/api/v1/dashboard"
AS_OF = date(2024, 12, 31)  # the last day with a full set of known market metrics


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


# --- #49: stocks list and stock detail ---------------------------------------------------


async def test_stocks_list_searches_sorts_and_pages(dashboard_client: AsyncClient) -> None:
    body = (await dashboard_client.get(f"{BASE}/stocks")).json()
    assert body["total"] == 10 and body["as_of"] == AS_OF.isoformat()
    assert [r["ticker_symbol"] for r in body["items"]][:3] == ["ABSA", "ACCS", "EQTY"]
    kcb = next(r for r in body["items"] if r["ticker_symbol"] == "KCB")
    assert kcb["price"]["value"] == 94.0 and kcb["classification"] is not None
    assert set(kcb["factor_percentiles"]) == {
        "value",
        "quality",
        "growth",
        "momentum",
        "dividend",
        "risk",
        "liquidity",
    }
    assert kcb["pe"]["status"] in ("known", "not_meaningful", "unavailable")
    # search narrows on ticker, company or sector
    only = (await dashboard_client.get(f"{BASE}/stocks", params={"q": "kc"})).json()
    assert [r["ticker_symbol"] for r in only["items"]] == ["KCB"]
    banks = (await dashboard_client.get(f"{BASE}/stocks", params={"q": "bank"})).json()
    assert {"KCB", "EQTY", "ABSA", "NCBA"} <= {r["ticker_symbol"] for r in banks["items"]}
    # sort by score: known scores first (desc), unscored last with their reason
    scored = (
        await dashboard_client.get(f"{BASE}/stocks", params={"sort": "score", "order": "desc"})
    ).json()
    values = [r["overall_score"]["value"] for r in scored["items"]]
    known = [v for v in values if v is not None]
    assert known == sorted(known, reverse=True) and values[: len(known)] == known
    assert all(
        r["overall_score"]["reason"] for r in scored["items"] if r["overall_score"]["value"] is None
    )
    # pages walk without duplicates and a foreign cursor is rejected
    first = (await dashboard_client.get(f"{BASE}/stocks", params={"limit": 4})).json()
    second = (
        await dashboard_client.get(
            f"{BASE}/stocks", params={"limit": 4, "cursor": first["next_cursor"]}
        )
    ).json()
    third = (
        await dashboard_client.get(
            f"{BASE}/stocks", params={"limit": 4, "cursor": second["next_cursor"]}
        )
    ).json()
    seen = [r["ticker_symbol"] for page in (first, second, third) for r in page["items"]]
    assert len(seen) == 10 == len(set(seen)) and third["next_cursor"] is None
    foreign = await dashboard_client.get(
        f"{BASE}/stocks", params={"limit": 4, "sort": "price", "cursor": first["next_cursor"]}
    )
    assert foreign.status_code == 422
    assert (
        await dashboard_client.get(f"{BASE}/stocks", params={"sort": "nope"})
    ).status_code == 422


async def test_stock_detail_carries_everything_with_reasons(dashboard_client: AsyncClient) -> None:
    body = (await dashboard_client.get(f"{BASE}/stocks/kcb")).json()
    assert body["ticker_symbol"] == "KCB"
    assert body["quote"]["price"]["value"] == 94.0
    profile = body["profile"]
    assert profile["identity"]["sector"] == "Banking"
    assert profile["metrics"]["quality"]["roe"]["status"] in ("known", "unavailable", "missing")
    assert profile["metrics"]["quality"]["interest_coverage"]["status"] == "not_applicable"
    assert body["facts"]["industry"] == "Commercial Banks" and body["facts"]["founded"] == 1896
    assert body["facts"]["listed_since"] == "2007-01-02"
    assert (
        body["geographic"]["status"] == "unavailable" and "scraper" in body["geographic"]["reason"]
    )
    assert body["geographic"]["segments"] == []
    # the weekly pipeline never ran on this store: forecasts absent, and it says so
    fa = body["forecast_availability"]
    assert fa["status"] == "unavailable" and fa["latest_known_as_of"] is None and fa["reason"]
    # a year of prices ending on the newest scrape day, crossing the 572-day gap
    prices = body["prices"]
    assert prices["range"] == "1y" and prices["end"] == "2026-09-13"
    # the year starts inside the 572-day gap: no break between the points, but a
    # hole at the start of the window, and the payload says so
    assert prices["start"] == "2026-07-26" and prices["gaps"] == []
    assert prices["availability"]["status"] == "partial"
    assert prices["missing_start"] == {"from": "2025-09-12", "to": "2026-07-26", "days": 317}
    # sector comparison rows carry the stock and the peers' median, or the reason
    rows = {r["metric"]: r for r in body["sector_comparison"]}
    assert set(rows) >= {"return_1m", "pe", "roe", "market_cap"}
    assert rows["return_1m"]["sector_members"] >= 3
    assert rows["return_1m"]["sector_median"]["status"] in ("known", "unavailable")
    assert body["links"]["prices"].endswith("/stocks/KCB/prices")


async def test_stock_statements_are_fiscal_years_with_hand_checked_values(
    dashboard_client: AsyncClient,
) -> None:
    body = (await dashboard_client.get(f"{BASE}/stocks/KCB/statements")).json()
    assert body["period_type"] == "annual" and body["availability"]["status"] == "known"
    years = {y["period_end"]: y for y in body["years"]}
    # KCB FY2024 as captured from stockanalysis (hand-checked in the scraper's tests):
    # revenue 173,395 m KES is FY2025; FY2021 net income 34,092 m
    fy2021 = years["2021-12-31"]
    assert fy2021["currency"] == "KES"
    assert round(fy2021["values"]["net_income"]["value"] / 1e6) == 34092
    assert fy2021["values"]["revenue"]["status"] == "known"
    assert body["concepts"] == [
        "revenue",
        "net_income",
        "eps",
        "dps",
        "equity",
        "total_assets",
        "ocf",
        "fcf",
    ]
    # a stock without statements is honest about it
    none = (await dashboard_client.get(f"{BASE}/stocks/KENO/statements")).json()
    assert none["years"] == [] and none["availability"]["status"] == "unavailable"
    assert (await dashboard_client.get(f"{BASE}/stocks/NOPE/statements")).status_code == 404


async def test_price_history_lists_gaps_and_sources(dashboard_client: AsyncClient) -> None:
    body = (
        await dashboard_client.get(f"{BASE}/stocks/ABSA/prices", params={"range": "max"})
    ).json()
    assert body["start"] == "2007-01-02" and body["end"] == "2026-09-13"
    assert body["n_observations"] == len(body["points"]) > 4000
    assert "BBK" in body["source_tickers"] and "ABSA" in body["source_tickers"]
    days = [g["days"] for g in body["gaps"]]
    assert 572 in days and body["gap_threshold_days"] == 14
    assert body["availability"]["status"] == "partial"
    weekly = (
        await dashboard_client.get(
            f"{BASE}/stocks/ABSA/prices", params={"range": "5y", "interval": "weekly"}
        )
    ).json()
    assert 0 < len(weekly["points"]) < len(body["points"]) and weekly["n_observations"] > len(
        weekly["points"]
    )
    index = (
        await dashboard_client.get(f"{BASE}/stocks/^NASI/prices", params={"range": "1y"})
    ).json()
    assert (
        index["end"] == "2024-12-31"
        and index["gaps"] == []
        and index["availability"]["status"] == "known"
    )
    assert (await dashboard_client.get(f"{BASE}/stocks/NOPE/prices")).status_code == 404
    assert (
        await dashboard_client.get(f"{BASE}/stocks/ABSA/prices", params={"range": "2y"})
    ).status_code == 422
    response = await dashboard_client.get(f"{BASE}/stocks/NOPE")
    assert response.status_code == 404 and "not an instrument" in response.json()["message"]


# --- #50: analytics, forecasts, signals, backtests ----------------------------------------


async def test_analytics_table_lists_the_ranked_universe(dashboard_client: AsyncClient) -> None:
    body = (await dashboard_client.get(f"{BASE}/analytics")).json()
    assert body["as_of"] == AS_OF.isoformat() and body["model"].startswith("factor-model")
    assert body["available_dates"] == [AS_OF.isoformat()]
    assert body["latest_known_as_of"] == AS_OF.isoformat()
    assert set(body["factor_names"]) == {
        "value",
        "quality",
        "growth",
        "momentum",
        "dividend",
        "risk",
        "liquidity",
    }
    rows = body["rows"]
    ranks = [r["market_rank"] for r in rows]
    known = [r for r in ranks if r is not None]
    assert known == sorted(known) and ranks[: len(known)] == known  # ranked first, unranked last
    kcb = next(r for r in rows if r["ticker_symbol"] == "KCB")
    assert kcb["sector"] == "Banking" and set(kcb["factors"]) == set(body["factor_names"])
    assert kcb["factors"]["quality"]["score"]["status"] in ("known", "unavailable")
    assert set(kcb["relative"]) == {
        f"relative_{w}_vs_{s}" for w in ("1m", "3m", "6m", "12m") for s in ("market", "sector")
    }
    assert kcb["relative"]["relative_12m_vs_market"]["status"] in ("known", "unavailable")
    assert all(r["overall"]["reason"] for r in rows if r["overall"]["value"] is None)
    assert sum(body["coverage"]["quality"].values()) == len(rows)
    banks = (await dashboard_client.get(f"{BASE}/analytics", params={"sector": "banking"})).json()
    assert {r["sector"] for r in banks["rows"]} == {"Banking"} and len(banks["rows"]) >= 3
    assert (
        await dashboard_client.get(f"{BASE}/analytics", params={"as_of": "2001-01-01"})
    ).status_code == 404


async def test_forecasts_are_ranges_with_availability(dashboard_client: AsyncClient) -> None:
    # the weekly pipeline never ran on this store
    assert (await dashboard_client.get(f"{BASE}/forecasts")).status_code == 404


async def test_signals_tie_back_to_rankings(dashboard_client: AsyncClient) -> None:
    body = (await dashboard_client.get(f"{BASE}/signals")).json()
    table = (await dashboard_client.get(f"{BASE}/analytics")).json()
    scores = {r["ticker_symbol"]: r for r in table["rows"]}
    assert body["as_of"] == table["as_of"] and body["universe"] == len(table["rows"])
    assert body["scored"] + body["unscored"] == body["universe"]
    buckets = ("buy_candidates", "watch", "neutral", "weak", "avoid")
    total = 0
    for bucket in buckets:
        for item in body[bucket]:
            total += 1
            row = scores[item["ticker_symbol"]]
            assert item["overall_score"]["value"] == row["overall"]["value"]
            assert (
                item["classification"] == row["classification"]
                and item["link"] == f"/stocks/{item['ticker_symbol']}"
            )
    assert total == body["scored"]
    for trap in body["value_traps"]:
        assert trap["extra"]["risk"] >= 1 and trap["extra"]["risk_label"] in ("medium", "high")
        assert scores[trap["ticker_symbol"]]["value_trap_risk"] == trap["extra"]["risk"]
    for comp in body["compounders"]:
        assert comp["extra"]["compounder_score"] >= body["compounder_threshold"]
    for v in body["valuation_upside"]:
        assert v["upside"] > 0 and v["intrinsic"]["status"] == "known"
    assert all(f["severity"] in ("error", "warning", "info") for f in body["risk_flags"])
    assert any(f["kind"] == "data_quality" for f in body["risk_flags"])
    assert "Not investment advice" in body["disclaimer"]


async def test_backtests_are_empty_but_well_shaped(dashboard_client: AsyncClient) -> None:
    body = (await dashboard_client.get(f"{BASE}/backtests")).json()
    assert body == {"items": [], "next_cursor": None, "total": 0}
    assert (await dashboard_client.get(f"{BASE}/backtests/1")).status_code == 404


@pytest.mark.realdata
async def test_live_forecasts_and_backtests() -> None:
    """The real store holds forecasts (known up to 2024-12-31) and four backtest runs."""
    from app.web.config import get_settings
    from app.web.main import create_app

    keys = ("ANALYTICS_DB_PATH", "NSE_SCRAPER_DB_PATH", "NSE_SCRAPER_PATH", "DASHBOARD_PUBLIC")
    previous = {k: os.environ.pop(k, None) for k in keys}
    get_settings.cache_clear()
    reset_dashboard_cache()
    try:
        settings = get_settings()
        if not settings.analytics_db_path.exists() or not settings.scraper_database_path.exists():
            pytest.skip("no live databases")
        app = create_app()
        async with (
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
            app.router.lifespan_context(app),
        ):
            fc = (await c.get(f"{BASE}/forecasts", params={"ticker": "KCB"})).json()
            assert fc["latest_known_as_of"] is not None and fc["items"][0]["ticker_symbol"] == "KCB"
            assert set(fc["items"][0]["models"]) >= {"naive", "ar1"}
            assert fc["accuracy"]["ar1"]["12m"]["n"] > 0
            known = (
                await c.get(
                    f"{BASE}/forecasts", params={"ticker": "KCB", "as_of": fc["latest_known_as_of"]}
                )
            ).json()
            cell = known["items"][0]["models"]["ar1"]["12m"]
            assert (
                cell["expected_return"]["status"] == "known"
                and cell["q05"] < cell["q50"] < cell["q95"]
            )
            runs = (await c.get(f"{BASE}/backtests")).json()
            assert runs["total"] >= 1
            detail = (await c.get(f"{BASE}/backtests/{runs['items'][0]['run_id']}")).json()
            assert len(detail["equity"]) > 1000 and detail["max_drawdown"]["status"] == "known"
    finally:
        for key, value in previous.items():
            if value is not None:
                os.environ[key] = value
        get_settings.cache_clear()
        reset_dashboard_cache()
