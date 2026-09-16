"""Research API: every allowed role reads, `client` is shut out, unknown tickers are 404,
and unavailable numbers arrive with their reasons.

    codegraph explore "research views.py build_profile token_for_role"
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.web.config import Settings
from app.web.services.analytics.classification.service import classify_instruments
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.jobs import run_pipeline
from app.web.services.market_data.sources import NseScraperSource

pytestmark = [pytest.mark.integration]

BASE = "/api/v1/research"
ALLOWED = ("org_admin", "analyst", "portfolio_manager", "trader", "research_viewer")


@pytest.fixture(scope="module")
def research_store(fixture_db_path: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """An analytics store populated once from the fixture prices as of 2019-12-31."""
    root = tmp_path_factory.mktemp("research")
    settings = Settings(
        NSE_SCRAPER_DB_PATH=str(fixture_db_path),
        NSE_SCRAPER_PATH=str(root / "scraper"),
        ANALYTICS_DB_PATH=str(root / "analytics.sqlite3"),
    )
    upgrade_analytics_db(settings.analytics_db_path)
    source = NseScraperSource(settings)
    classify_instruments(settings, source)
    run_pipeline(settings, source, "daily", as_of=date(2019, 12, 31))
    run_pipeline(settings, source, "weekly", as_of=date(2019, 12, 31))
    return settings.analytics_db_path


@pytest.fixture
async def research_client(
    research_store: Path, fixture_db_path: Path, client: AsyncClient
) -> AsyncIterator[AsyncClient]:
    """An app instance whose settings point at the fixture store (the shared ``client``
    was created before these environment variables existed and would read the live
    store); tokens minted through ``client`` are valid here - same database, same secret."""
    from httpx import ASGITransport

    from app.web.config import get_settings
    from app.web.main import create_app

    keys = ("ANALYTICS_DB_PATH", "NSE_SCRAPER_DB_PATH", "NSE_SCRAPER_PATH")
    previous = {k: os.environ.get(k) for k in keys}
    os.environ["ANALYTICS_DB_PATH"] = str(research_store)
    os.environ["NSE_SCRAPER_DB_PATH"] = str(fixture_db_path)
    os.environ["NSE_SCRAPER_PATH"] = str(fixture_db_path.parent)
    get_settings.cache_clear()
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


@pytest.mark.parametrize("role", ALLOWED)
async def test_allowed_roles_read_every_endpoint(
    research_client: AsyncClient, token_for_role, role: str
) -> None:
    actor = await token_for_role(role)
    for path in (
        "/stocks",
        "/stocks/KCB",
        "/stocks/KCB/metrics",
        "/stocks/KCB/valuation",
        "/stocks/KCB/forecast",
        "/stocks/KCB/risk",
        "/stocks/KCB/factors",
        "/stocks/KCB/history",
        "/stocks/KCB/narrative",
        "/rankings",
        "/sectors",
        "/backtests",
    ):
        response = await research_client.get(BASE + path, headers=actor["headers"])
        assert response.status_code == 200, (
            f"{role} {path}: {response.status_code} {response.text[:200]}"
        )


async def test_client_role_is_forbidden_everywhere(
    research_client: AsyncClient, token_for_role
) -> None:
    actor = await token_for_role("client")
    for path in (
        "/stocks",
        "/stocks/KCB",
        "/stocks/KCB/metrics",
        "/stocks/KCB/narrative",
        "/rankings",
        "/sectors",
        "/backtests",
    ):
        assert (await research_client.get(BASE + path, headers=actor["headers"])).status_code == 403


async def test_unknown_ticker_is_404(research_client: AsyncClient, token_for_role) -> None:
    actor = await token_for_role("analyst")
    for path in (
        "/stocks/NOPE",
        "/stocks/NOPE/metrics",
        "/stocks/NOPE/history",
        "/stocks/NOPE/narrative",
    ):
        response = await research_client.get(BASE + path, headers=actor["headers"])
        assert response.status_code == 404, path
        assert "not an instrument" in response.json()["message"]


async def test_profile_carries_statuses_and_reasons(
    research_client: AsyncClient, token_for_role
) -> None:
    actor = await token_for_role("research_viewer")
    body = (await research_client.get(f"{BASE}/stocks/KCB", headers=actor["headers"])).json()
    assert body["ticker_symbol"] == "KCB" and body["identity"]["sector"] == "Banking"
    assert (
        body["as_of"]["market_metrics"] == "2019-12-31" and body["as_of"]["ranking"] == "2019-12-31"
    )
    momentum = body["metrics"]["momentum"]["momentum_12m_1m"]
    assert momentum["status"] == "known" and momentum["value"] is not None
    # no statements before 2021: the fundamental blocks are present, each with a reason
    roe = body["metrics"]["quality"]["roe"]
    assert (
        roe["value"] is None and roe["status"] == "unavailable" and "not computed" in roe["reason"]
    )
    assert body["notes"] == []  # KCB has statements captured (none visible in 2019)
    absa = (await research_client.get(f"{BASE}/stocks/ABSA", headers=actor["headers"])).json()
    assert absa["notes"] and "no statements" in absa["notes"][0]
    assert (
        body["score"]["overall"]["status"] == "unavailable"
    )  # market factors alone are 30 % of the weight
    assert "30%" in body["score"]["overall"]["reason"]
    assert "naive" in body["forecast"]["models"] and "12m" in body["forecast"]["models"]["naive"]
    assert body["regime"]["label"] and body["regime"]["index"] == "^NASI"
    assert "not investment advice" in body["disclaimer"]
    assert {m["name"] for m in body["models"]} >= {"factor-model", "naive", "ar1"}
    risk = (await research_client.get(f"{BASE}/stocks/KCB/risk", headers=actor["headers"])).json()
    assert risk["block"] == "risk" and "volatility_annualised" in risk["data"]["risk"]
    factors = (
        await research_client.get(f"{BASE}/stocks/KCB/factors", headers=actor["headers"])
    ).json()
    assert factors["data"]["factors"]["momentum"]["percentile_market"] is not None
    history = (
        await research_client.get(f"{BASE}/stocks/KCB/history", headers=actor["headers"])
    ).json()
    assert history["points"] and history["points"][-1]["as_of"] == "2019-12-31"


async def test_lists_paginate(research_client: AsyncClient, token_for_role) -> None:
    actor = await token_for_role("trader")
    first = (await research_client.get(f"{BASE}/stocks?limit=3", headers=actor["headers"])).json()
    assert len(first["items"]) == 3 and first["next_cursor"] == first["items"][-1]["ticker_symbol"]
    second = (
        await research_client.get(
            f"{BASE}/stocks?limit=3&cursor={first['next_cursor']}", headers=actor["headers"]
        )
    ).json()
    assert second["items"][0]["ticker_symbol"] > first["next_cursor"]
    assert first["total"] == second["total"] >= 8
    rankings = (
        await research_client.get(f"{BASE}/rankings?limit=2", headers=actor["headers"])
    ).json()
    assert rankings["as_of"] == "2019-12-31" and rankings["model"].startswith("factor-model")
    assert len(rankings["items"]) == 2 and rankings["next_cursor"]
    assert (
        all(item["status"] == "unavailable" for item in rankings["items"])
        or rankings["items"][0]["market_rank"] == 1
    )
    sectors = (await research_client.get(f"{BASE}/sectors", headers=actor["headers"])).json()
    assert sectors["metric"] == "return_12m" and any(
        s["sector"] == "Banking" for s in sectors["sectors"]
    )
    backtests = (await research_client.get(f"{BASE}/backtests", headers=actor["headers"])).json()
    assert backtests == {"items": [], "next_cursor": None, "total": 0}
    bad = await research_client.get(f"{BASE}/sectors?metric=drop%20table", headers=actor["headers"])
    assert bad.status_code == 422


async def test_narrative_is_unavailable_until_generated(
    research_client: AsyncClient, token_for_role
) -> None:
    actor = await token_for_role("research_viewer")
    body = (
        await research_client.get(f"{BASE}/stocks/KCB/narrative", headers=actor["headers"])
    ).json()
    assert body["ticker_symbol"] == "KCB" and body["status"] == "unavailable"
    assert body["narrative"] is None and "AI_NARRATIVES_ENABLED" in body["reason"]


async def test_unauthenticated_is_401(research_client: AsyncClient) -> None:
    assert (await research_client.get(f"{BASE}/stocks")).status_code == 401
