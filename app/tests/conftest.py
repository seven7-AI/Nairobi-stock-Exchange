"""Shared pytest fixtures.

Before adding a fixture, query CodeGraph for what you are about to test:
``codegraph explore "<symbol>"`` — the blast radius names the callers you
should also be exercising.

Integration tests need PostgreSQL. Point ``TEST_DATABASE_URL`` at a disposable
database; without it the integration suite skips rather than failing, so the
unit suite still runs anywhere.
"""

from __future__ import annotations

import os
import secrets
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient

REPO_ROOT = Path(__file__).resolve().parents[2]

# Settings are read at import time by several modules, so these must be set
# before anything under app.* is imported.
os.environ.setdefault("SUPABASE_URL", "https://placeholder.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "placeholder-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-for-production-at-least-32-bytes-long")
os.environ.setdefault("ENVIRONMENT", "local")
# Production uses 12; a few hundred test hashes at that cost dominate the run.
os.environ.setdefault("BCRYPT_ROUNDS", "4")

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Absolute repo root, so tests never depend on the working directory."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def indicators_file(repo_root: Path) -> Path:
    """Path to the indicator reference file parsed by the registry."""
    return repo_root / "indicators.txt"


# ---------------------------------------------------------------------------
# Real-data fixtures for the analytics engines
# ---------------------------------------------------------------------------
# ``fixture_source`` is a slice of the real scraper database (12 instruments, full
# history, statements) shipped gzipped under app/tests/fixtures/ and rebuilt with
# scripts/build_test_fixture.py. It runs everywhere. ``live_source`` is the actual
# ~/nse-stock-scraper database and is only for @pytest.mark.realdata tests, which
# skip when it is not on this machine.
FIXTURE_DB_GZ = REPO_ROOT / "app" / "tests" / "fixtures" / "nse_fixture.sqlite3.gz"


@pytest.fixture(scope="session")
def fixture_db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The fixture database, decompressed once per session."""
    import gzip
    import shutil

    target = tmp_path_factory.mktemp("nse_fixture") / "nse_scraper.sqlite3"
    with gzip.open(FIXTURE_DB_GZ, "rb") as src, target.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    return target


@pytest.fixture(scope="session")
def fixture_settings(fixture_db_path: Path, tmp_path_factory: pytest.TempPathFactory):
    """Settings pointed at the fixture database and a throwaway analytics store."""
    from app.web.config import Settings

    analytics = tmp_path_factory.mktemp("analytics") / "nse_analytics.sqlite3"
    return Settings(
        NSE_SCRAPER_DB_PATH=str(fixture_db_path),
        NSE_SCRAPER_PATH=str(fixture_db_path.parent),
        ANALYTICS_DB_PATH=str(analytics),
    )


@pytest.fixture(scope="session")
def fixture_source(fixture_settings):
    """``NseScraperSource`` over the fixture database (read-only, like production)."""
    from app.web.services.market_data.sources import NseScraperSource

    return NseScraperSource(fixture_settings)


@pytest.fixture(scope="session")
def live_source():
    """``NseScraperSource`` over the real scraper database, or skip."""
    from app.web.config import Settings
    from app.web.services.market_data.sources import NseScraperSource

    settings = Settings()
    if not settings.scraper_database_path.exists():
        pytest.skip(f"live scraper database not found at {settings.scraper_database_path}")
    return NseScraperSource(settings)


# ---------------------------------------------------------------------------
# Integration fixtures
# ---------------------------------------------------------------------------
requires_db = pytest.mark.skipif(
    TEST_DATABASE_URL is None,
    reason="TEST_DATABASE_URL is not set; integration tests need PostgreSQL.",
)


@pytest.fixture(scope="session")
def database_url() -> str:
    if TEST_DATABASE_URL is None:
        pytest.skip("TEST_DATABASE_URL is not set.")
    return TEST_DATABASE_URL


@pytest.fixture(scope="session", autouse=True)
def _configure_database() -> Iterator[None]:
    """Point Settings at the test database when one is configured.

    Deliberately does NOT depend on the skipping ``database_url`` fixture. As an
    autouse session fixture, doing so skipped the entire suite - unit tests
    included - whenever TEST_DATABASE_URL was unset, which is exactly the
    environment unit tests are supposed to run in.
    """
    from app.web.config import get_settings

    if TEST_DATABASE_URL:
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def client(_configure_database: None) -> AsyncIterator[AsyncClient]:
    """httpx client bound to the real app, lifespan included."""
    from httpx import ASGITransport, AsyncClient

    from app.web.main import create_app

    app = create_app()
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client,
        app.router.lifespan_context(app),
    ):
        yield http_client


#: Generated once per session, so no password literal lives in the test suite.
TEST_PASSWORD = secrets.token_urlsafe(24)


@pytest.fixture(scope="session")
def test_password() -> str:
    """The password every fixture-created account is registered with."""
    return TEST_PASSWORD


@pytest.fixture
def unique_email() -> str:
    """An address no other test has used."""
    return f"user-{uuid.uuid4().hex[:12]}@nse-analytics-test.co.ke"


@pytest.fixture
def unique_org_name() -> str:
    return f"Test Capital {uuid.uuid4().hex[:8]}"


@pytest.fixture
async def org_admin(client, unique_email: str, unique_org_name: str) -> dict:
    """A registered organization admin plus their access token."""
    registration = await client.post(
        "/api/v1/auth/register",
        json={
            "email": unique_email,
            "password": TEST_PASSWORD,
            "organization_name": unique_org_name,
        },
    )
    assert registration.status_code == 201, registration.text
    tokens = await client.post(
        "/api/v1/auth/login",
        json={"email": unique_email, "password": TEST_PASSWORD},
    )
    assert tokens.status_code == 200, tokens.text
    return {
        "email": unique_email,
        "organization_id": registration.json()["organization_id"],
        "access_token": tokens.json()["access_token"],
        "headers": {"Authorization": f"Bearer {tokens.json()['access_token']}"},
    }


@pytest.fixture
async def token_for_role(client, org_admin: dict):
    """Factory: mint a user with a given role inside the admin's organization."""

    async def _make(role: str) -> dict:
        email = f"{role}-{uuid.uuid4().hex[:10]}@nse-analytics-test.co.ke"
        password = TEST_PASSWORD
        created = await client.post(
            "/api/v1/users",
            headers=org_admin["headers"],
            json={"email": email, "password": password, "role": role},
        )
        assert created.status_code == 201, created.text
        tokens = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
        assert tokens.status_code == 200, tokens.text
        return {
            "email": email,
            "role": role,
            "headers": {"Authorization": f"Bearer {tokens.json()['access_token']}"},
        }

    return _make


@pytest.fixture(scope="session")
def dashboard_store(fixture_db_path: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """An analytics store built once from the fixture prices as of 2024-12-31 - the last
    day with a full set of known market metrics - with the daily and fundamentals
    pipelines run. Shared by the public-dashboard tests."""
    from datetime import date

    from app.web.config import Settings
    from app.web.services.analytics.classification.service import classify_instruments
    from app.web.services.analytics.store import upgrade_analytics_db
    from app.web.services.jobs import run_pipeline
    from app.web.services.market_data.sources import NseScraperSource

    root = tmp_path_factory.mktemp("dashboard")
    settings = Settings(
        NSE_SCRAPER_DB_PATH=str(fixture_db_path),
        NSE_SCRAPER_PATH=str(root / "scraper"),
        ANALYTICS_DB_PATH=str(root / "analytics.sqlite3"),
    )
    upgrade_analytics_db(settings.analytics_db_path)
    source = NseScraperSource(settings)
    classify_instruments(settings, source)
    run_pipeline(settings, source, "daily", as_of=date(2024, 12, 31))
    run_pipeline(settings, source, "fundamentals", as_of=date(2024, 12, 31))
    return settings.analytics_db_path
