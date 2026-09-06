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
def _configure_database(database_url: str) -> Iterator[None]:
    """Point Settings at the test database for the whole session."""
    os.environ["DATABASE_URL"] = database_url
    from app.web.config import get_settings

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
            "password": "correct horse battery staple",
            "organization_name": unique_org_name,
        },
    )
    assert registration.status_code == 201, registration.text
    tokens = await client.post(
        "/api/v1/auth/login",
        json={"email": unique_email, "password": "correct horse battery staple"},
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
        password = "correct horse battery staple"
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
