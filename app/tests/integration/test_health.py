"""Operational endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration]


async def test_health_is_unauthenticated_and_cheap(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_readiness_reports_each_dependency(client: AsyncClient) -> None:
    """Readiness never 500s; it reports which dependency is down."""
    response = await client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["database"] is True
    assert set(body) >= {"status", "redis", "database", "market_data_source"}


async def test_readiness_describes_the_market_data_source(client: AsyncClient) -> None:
    """The source is reported as a shape, not a bool.

    "cannot read it" and "read it fine, but nothing has refreshed it since
    Tuesday" are both unhealthy for different reasons, and a boolean hides the
    second one entirely.
    """
    body = (await client.get("/health/ready")).json()
    source = body["market_data_source"]
    assert source["name"] == "nse_scraper"
    assert set(source) >= {"name", "status"}


async def test_request_id_is_echoed(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "abc123"})
    assert response.headers["X-Request-ID"] == "abc123"
