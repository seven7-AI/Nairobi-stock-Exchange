"""The NSE scraper source over HTTP.

Points the service at a temporary scraper layout, so these tests never depend on
``~/nse-stock-scraper`` existing or on a scrape having run.

    codegraph explore "read_source read_scraped_rows MarketDataSourceDep"
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.tests.unit.test_nse_scraper_source import SCHEMA, _insert

pytestmark = [pytest.mark.integration]

SOURCE_URL = "/api/v1/market-data/source"
SCRAPED_URL = "/api/v1/market-data/scraped"


@pytest.fixture
def fake_scraper(tmp_path: Path) -> Iterator[Path]:
    """A temp scraper layout, installed as the configured source."""
    (tmp_path / "data").mkdir()
    (tmp_path / "reports" / "stats").mkdir(parents=True)
    (tmp_path / "reports" / "local_fallback").mkdir(parents=True)

    connection = sqlite3.connect(tmp_path / "data" / "nse_scraper.sqlite3")
    connection.executescript(SCHEMA)
    for ticker in ("SCOM", "EQTY", "KCB", "ABSA"):
        _insert(connection, ticker)
    connection.commit()
    connection.close()

    (tmp_path / "reports" / "stats" / "stockanalysis_scraper-latest.json").write_text(
        json.dumps({"quality_ok": True, "item_scraped_count": 123, "db_upsert_ok": 63})
    )

    from app.web.config import get_settings

    previous = os.environ.get("NSE_SCRAPER_PATH")
    os.environ["NSE_SCRAPER_PATH"] = str(tmp_path)
    get_settings.cache_clear()
    yield tmp_path
    if previous is None:
        os.environ.pop("NSE_SCRAPER_PATH", None)
    else:
        os.environ["NSE_SCRAPER_PATH"] = previous
    get_settings.cache_clear()


async def test_source_endpoint_reports_a_healthy_source(
    fake_scraper: Path, client: AsyncClient, token_for_role
) -> None:
    actor = await token_for_role("analyst")
    response = await client.get(SOURCE_URL, headers=actor["headers"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "nse_scraper"
    assert body["status"] == "ok"
    assert body["reachable"] is True
    assert body["quality_ok"] is True
    assert body["is_stale"] is False
    tables = {t["name"]: t["row_count"] for t in body["tables"]}
    assert tables["stockanalysis_stocks"] == 4


@pytest.fixture
def stale_scraper(tmp_path: Path) -> Iterator[Path]:
    """A scraper layout whose newest scrape is nine days old.

    Must be requested *before* the ``client`` fixture: AppState builds the source
    at app-creation time, so the environment has to be in place first.
    """
    (tmp_path / "data").mkdir()
    connection = sqlite3.connect(tmp_path / "data" / "nse_scraper.sqlite3")
    connection.executescript(SCHEMA)
    _insert(connection, "SCOM", scraped_at=(datetime.now(tz=UTC) - timedelta(days=9)).isoformat())
    connection.commit()
    connection.close()

    from app.web.config import get_settings

    os.environ["NSE_SCRAPER_PATH"] = str(tmp_path)
    get_settings.cache_clear()
    yield tmp_path
    os.environ.pop("NSE_SCRAPER_PATH", None)
    get_settings.cache_clear()


async def test_source_endpoint_reports_stale_data_without_failing(
    stale_scraper: Path, client: AsyncClient, token_for_role
) -> None:
    """A source that reads fine but has not refreshed is still an answerable
    question, not a 500."""
    actor = await token_for_role("analyst")
    response = await client.get(SOURCE_URL, headers=actor["headers"])

    assert response.status_code == 200
    body = response.json()
    assert body["reachable"] is True
    assert body["is_stale"] is True
    assert body["status"] == "stale"


async def test_scraped_endpoint_preserves_the_raw_fields(
    fake_scraper: Path, client: AsyncClient, token_for_role
) -> None:
    """The brief is explicit: keep the scraper's fields, do not transform them."""
    actor = await token_for_role("analyst")
    response = await client.get(SCRAPED_URL, headers=actor["headers"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 4

    row = body["items"][0]
    assert row["ticker_symbol"]
    assert row["company_name"]
    assert isinstance(row["overview_metrics"], dict)
    assert isinstance(row["price_history"], list)
    assert row["overview_metrics"]["marketCap"] == 1000
    assert len(row["price_history"]) == 30


async def test_scraped_endpoint_paginates(
    fake_scraper: Path, client: AsyncClient, token_for_role
) -> None:
    actor = await token_for_role("analyst")
    first = await client.get(f"{SCRAPED_URL}?page_size=2", headers=actor["headers"])
    assert first.status_code == 200
    page_one = first.json()
    assert len(page_one["items"]) == 2
    assert page_one["has_more"] is True

    second = await client.get(
        f"{SCRAPED_URL}?page_size=2&cursor={page_one['next_cursor']}", headers=actor["headers"]
    )
    assert second.status_code == 200
    page_two = second.json()

    seen_first = {row["ticker_symbol"] for row in page_one["items"]}
    seen_second = {row["ticker_symbol"] for row in page_two["items"]}
    assert not (seen_first & seen_second), "pages must not repeat rows"


@pytest.mark.parametrize("url", [SOURCE_URL, SCRAPED_URL])
async def test_research_roles_are_admitted(
    fake_scraper: Path, client: AsyncClient, token_for_role, url: str
) -> None:
    for role in ("org_admin", "analyst", "portfolio_manager", "trader", "research_viewer"):
        actor = await token_for_role(role)
        response = await client.get(url, headers=actor["headers"])
        assert response.status_code == 200, f"{role} was refused {url}"


@pytest.mark.parametrize("url", [SOURCE_URL, SCRAPED_URL])
async def test_client_role_is_forbidden(
    fake_scraper: Path, client: AsyncClient, token_for_role, url: str
) -> None:
    actor = await token_for_role("client")
    assert (await client.get(url, headers=actor["headers"])).status_code == 403


@pytest.mark.parametrize("url", [SOURCE_URL, SCRAPED_URL])
async def test_unauthenticated_is_rejected(
    fake_scraper: Path, client: AsyncClient, url: str
) -> None:
    assert (await client.get(url)).status_code == 401


async def test_readiness_reports_the_market_data_source(
    fake_scraper: Path, client: AsyncClient
) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert "market_data_source" in body
    assert body["market_data_source"]["name"] == "nse_scraper"
