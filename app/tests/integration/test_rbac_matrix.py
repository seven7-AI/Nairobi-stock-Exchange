"""RBAC matrix: for each protected route, allowed roles pass and others get 403.

A new protected route without an entry here is an incomplete change — see
``app/tests/CLAUDE.md``.

    codegraph explore "require_roles RESEARCH_ROLES ADMIN_ROLES PLATFORM_ONLY"
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.tests.conftest import TEST_PASSWORD

pytestmark = [pytest.mark.integration]

ALL_ROLES = (
    "org_admin",
    "analyst",
    "portfolio_manager",
    "trader",
    "research_viewer",
    "client",
)

#: route -> roles that must be admitted. Every other role must get 403.
#: `platform_admin` is excluded: an org_admin cannot mint one, by design.
MATRIX: dict[tuple[str, str], set[str]] = {
    ("GET", "/api/v1/organizations/me"): {"org_admin"},
    ("GET", "/api/v1/users"): {"org_admin"},
    ("GET", "/api/v1/connectors"): {"org_admin"},
    ("GET", "/api/v1/onboarding/state"): {"org_admin"},
    ("GET", "/api/v1/instruments"): {
        "org_admin",
        "analyst",
        "portfolio_manager",
        "trader",
        "research_viewer",
    },
    ("GET", "/api/v1/instruments/sectors"): {
        "org_admin",
        "analyst",
        "portfolio_manager",
        "trader",
        "research_viewer",
    },
    ("GET", "/api/v1/indicators/feasibility"): {
        "org_admin",
        "analyst",
        "portfolio_manager",
        "trader",
        "research_viewer",
    },
    ("GET", "/api/v1/reports/daily"): {
        "org_admin",
        "analyst",
        "portfolio_manager",
        "trader",
        "research_viewer",
    },
    ("GET", "/api/v1/reports/runs"): {
        "org_admin",
        "analyst",
        "portfolio_manager",
        "trader",
        "research_viewer",
    },
}

#: `client` is the narrowest role and must be shut out of all of the above.
CLIENT_ROLE = "client"


@pytest.mark.parametrize(("method", "path"), sorted(MATRIX))
@pytest.mark.parametrize("role", ALL_ROLES)
async def test_role_matrix(
    client: AsyncClient, token_for_role, method: str, path: str, role: str
) -> None:
    """Allowed roles must not get 403; disallowed roles must."""
    actor = await token_for_role(role)
    response = await client.request(method, path, headers=actor["headers"])

    if role in MATRIX[(method, path)]:
        assert response.status_code != 403, (
            f"{role} should be allowed on {method} {path}, got {response.status_code}"
        )
    else:
        assert response.status_code == 403, (
            f"{role} should be forbidden on {method} {path}, got {response.status_code}"
        )


async def test_client_role_is_shut_out_of_every_admin_route(
    client: AsyncClient, token_for_role
) -> None:
    actor = await token_for_role(CLIENT_ROLE)
    for method, path in sorted(MATRIX):
        response = await client.request(method, path, headers=actor["headers"])
        assert response.status_code == 403, f"client reached {method} {path}"


async def test_unauthenticated_requests_are_401_not_403(client: AsyncClient) -> None:
    """No token at all is an authentication failure, not an authorization one."""
    for method, path in sorted(MATRIX):
        response = await client.request(method, path)
        assert response.status_code == 401, f"{method} {path} -> {response.status_code}"


async def test_org_admin_cannot_create_a_platform_admin(
    client: AsyncClient, org_admin: dict, unique_email: str
) -> None:
    """Privilege escalation guard: org_admin must not mint platform_admin."""
    response = await client.post(
        "/api/v1/users",
        headers=org_admin["headers"],
        json={
            "email": unique_email,
            "password": TEST_PASSWORD,
            "role": "platform_admin",
        },
    )
    assert response.status_code == 403


async def test_org_admin_cannot_reach_the_platform_wide_list(
    client: AsyncClient, org_admin: dict
) -> None:
    """Cross-organization listing is platform_admin only."""
    response = await client.get("/api/v1/organizations", headers=org_admin["headers"])
    assert response.status_code == 403
