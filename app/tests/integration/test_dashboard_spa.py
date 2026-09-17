"""SPA serving and standalone mode: the built dashboard at ``/`` with a client-side
fallback, the API untouched, and a public port that never reaches Postgres or Redis."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.web.services.dashboard import reset_dashboard_cache

pytestmark = [pytest.mark.integration]

BASE = "/api/v1/dashboard"


@contextmanager
def _env(**values: str | None) -> Iterator[None]:
    from app.web.config import get_settings

    previous = {k: os.environ.get(k) for k in values}
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    get_settings.cache_clear()
    reset_dashboard_cache()
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        reset_dashboard_cache()


def _dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><title>NSE dashboard</title><div id=root></div>"
    )
    (dist / "assets" / "app-abc123.js").write_text("console.log('hi')")
    (dist / "favicon.svg").write_text("<svg/>")
    return dist


@pytest.fixture
async def spa_client(
    dashboard_store: Path, fixture_db_path: Path, tmp_path: Path
) -> AsyncIterator[tuple[AsyncClient, Path]]:
    from app.web.main import create_app

    dist = _dist(tmp_path)
    with _env(
        ANALYTICS_DB_PATH=str(dashboard_store),
        NSE_SCRAPER_DB_PATH=str(fixture_db_path),
        NSE_SCRAPER_PATH=str(fixture_db_path.parent),
        DASHBOARD_DIST_DIR=str(dist),
        DASHBOARD_STANDALONE="true",
    ):
        app = create_app()
        async with (
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
            app.router.lifespan_context(app),
        ):
            yield client, dist


async def test_spa_serves_index_and_deep_links(spa_client: tuple[AsyncClient, Path]) -> None:
    client, _ = spa_client
    root = await client.get("/")
    assert root.status_code == 200 and "NSE dashboard" in root.text
    assert root.headers["cache-control"] == "no-cache"
    assert "default-src 'self'" in root.headers["content-security-policy"]
    assert root.headers["x-content-type-options"] == "nosniff"
    deep = await client.get("/stocks/KCB")
    assert deep.status_code == 200 and "NSE dashboard" in deep.text  # client-side route
    asset = await client.get("/assets/app-abc123.js")
    assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
    assert (await client.get("/assets/missing-999.js")).status_code == 404  # a real file
    assert (await client.get("/favicon.svg")).status_code == 200


async def test_api_and_ops_routes_win_over_the_spa(spa_client: tuple[AsyncClient, Path]) -> None:
    client, _ = spa_client
    version = await client.get(f"{BASE}/status/version")
    assert version.status_code == 200 and version.headers["content-type"].startswith(
        "application/json"
    )
    assert version.headers["x-content-type-options"] == "nosniff"
    nope = await client.get(f"{BASE}/nope")
    assert nope.status_code == 404 and nope.headers["content-type"].startswith("application/json")
    health = await client.get("/health")
    assert health.status_code == 200 and health.json()["status"] == "ok"
    assert (await client.get("/docs")).status_code == 200
    assert (await client.get("/openapi.json")).status_code == 200


async def test_standalone_mounts_no_platform_routers(spa_client: tuple[AsyncClient, Path]) -> None:
    client, _ = spa_client
    assert (await client.post("/api/v1/auth/login", json={})).status_code == 404
    assert (await client.get("/api/v1/users")).status_code == 404
    assert (await client.get("/api/v1/research/stocks")).status_code == 404
    paths = (await client.get("/openapi.json")).json()["paths"]
    assert all(p.startswith(BASE) or p.startswith("/health") for p in paths), sorted(paths)


async def test_standalone_readiness_reads_sqlite_only(spa_client: tuple[AsyncClient, Path]) -> None:
    client, _ = spa_client
    body = (await client.get("/health/ready")).json()
    assert set(body) == {"status", "analytics_store", "market_data_source", "dashboard"}
    assert body["analytics_store"]["ok"] is True and body["analytics_store"]["revision"]
    assert "location" not in body["market_data_source"] and body["dashboard"] is True
    assert body["status"] in ("ok", "degraded")


async def test_without_a_build_the_root_is_404_and_platform_mode_is_untouched(
    dashboard_store: Path, fixture_db_path: Path, tmp_path: Path
) -> None:
    from app.web.main import create_app

    with _env(
        ANALYTICS_DB_PATH=str(dashboard_store),
        NSE_SCRAPER_DB_PATH=str(fixture_db_path),
        NSE_SCRAPER_PATH=str(fixture_db_path.parent),
        DASHBOARD_DIST_DIR=str(tmp_path / "nothing"),
        DASHBOARD_STANDALONE=None,
    ):
        app = create_app()
        async with (
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
            app.router.lifespan_context(app),
        ):
            assert (await client.get("/")).status_code == 404
            assert (await client.get("/stocks/KCB")).status_code == 404
            assert (await client.post("/api/v1/auth/login", json={})).status_code in (401, 422)
            paths = (await client.get("/openapi.json")).json()["paths"]
            assert "/api/v1/research/stocks" in paths and f"{BASE}/overview" in paths
