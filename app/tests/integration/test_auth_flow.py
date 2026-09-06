"""End-to-end authentication.

codegraph explore "auth views.py create_access_token decode_token"
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration]

PASSWORD = "correct horse battery staple"


async def register(client: AsyncClient, email: str, org: str) -> dict:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "organization_name": org},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def login(client: AsyncClient, email: str, password: str = PASSWORD):
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def test_register_creates_org_admin(
    client: AsyncClient, unique_email: str, unique_org_name: str
) -> None:
    body = await register(client, unique_email, unique_org_name)
    assert body["user"]["role"] == "org_admin"
    assert body["user"]["email"] == unique_email
    assert body["user"]["is_email_verified"] is False
    # The password hash must never be serialized.
    assert "hashed_password" not in body["user"]
    assert "password" not in body["user"]


async def test_duplicate_registration_conflicts(
    client: AsyncClient, unique_email: str, unique_org_name: str
) -> None:
    await register(client, unique_email, unique_org_name)
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": unique_email,
            "password": PASSWORD,
            "organization_name": f"{unique_org_name} Two",
        },
    )
    assert response.status_code == 409


async def test_login_returns_usable_token_pair(
    client: AsyncClient, unique_email: str, unique_org_name: str
) -> None:
    await register(client, unique_email, unique_org_name)
    response = await login(client, unique_email)
    assert response.status_code == 200, response.text
    tokens = response.json()
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] > 0

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == unique_email


async def test_wrong_password_and_unknown_user_are_indistinguishable(
    client: AsyncClient, unique_email: str, unique_org_name: str
) -> None:
    """Different responses here would make the endpoint a user-enumeration oracle."""
    await register(client, unique_email, unique_org_name)
    wrong = await login(client, unique_email, "not the right password")
    unknown = await login(client, "nobody-here@nse-analytics-test.co.ke", PASSWORD)

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["message"] == unknown.json()["message"]


async def test_refresh_token_is_rejected_as_a_bearer_credential(
    client: AsyncClient, unique_email: str, unique_org_name: str
) -> None:
    await register(client, unique_email, unique_org_name)
    tokens = (await login(client, unique_email)).json()

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
    )
    assert response.status_code == 401


async def test_refresh_endpoint_issues_a_new_access_token(
    client: AsyncClient, unique_email: str, unique_org_name: str
) -> None:
    await register(client, unique_email, unique_org_name)
    tokens = (await login(client, unique_email)).json()

    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["access_token"]


async def test_password_reset_request_does_not_reveal_existence(
    client: AsyncClient, unique_email: str, unique_org_name: str
) -> None:
    await register(client, unique_email, unique_org_name)
    known = await client.post("/api/v1/auth/password-reset/request", json={"email": unique_email})
    unknown = await client.post(
        "/api/v1/auth/password-reset/request", json={"email": "nobody@nse-analytics-test.co.ke"}
    )
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


async def test_missing_credentials_are_rejected(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_short_password_fails_validation(
    client: AsyncClient, unique_email: str, unique_org_name: str
) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": unique_email, "password": "short", "organization_name": unique_org_name},
    )
    assert response.status_code == 422
