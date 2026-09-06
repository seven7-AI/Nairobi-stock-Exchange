"""The 7-step onboarding wizard, tested as a state machine.

Invariants: steps run in order, step 5 alone may be skipped, and completing
step 7 activates the organization.

    codegraph explore "onboarding views.py complete_step skip_step can_start_step"
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration]

STEP_PAYLOADS: dict[int, dict] = {
    1: {"legal_name": "Test Capital Ltd", "country": "KE", "timezone": "Africa/Nairobi"},
    2: {"invitations": []},
    3: {"exchanges": ["NSE"], "sectors": ["Banking"]},
    4: {"name": "Core", "tickers": ["SCOM", "KCB"]},
    5: {"connector_type": "supabase", "name": "Primary", "config": {"table": "prices"}},
    6: {"daily_enabled": True, "weekly_enabled": True, "monthly_enabled": False},
    7: {"confirmed": True},
}


async def post_step(client: AsyncClient, headers: dict, step: int):
    return await client.post(
        f"/api/v1/onboarding/step/{step}", headers=headers, json=STEP_PAYLOADS[step]
    )


async def test_initial_state_is_step_one(client: AsyncClient, org_admin: dict) -> None:
    response = await client.get("/api/v1/onboarding/state", headers=org_admin["headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["current_step"] == 1
    assert body["total_steps"] == 7
    assert body["completed_steps"] == []
    assert body["status"] in {"not_started", "in_progress"}
    # Step 5 is the only optional one.
    optional = [step["number"] for step in body["steps"] if step["is_optional"]]
    assert optional == [5]


async def test_steps_in_order_complete_the_wizard(
    client: AsyncClient, org_admin: dict
) -> None:
    for step in range(1, 8):
        response = await post_step(client, org_admin["headers"], step)
        assert response.status_code == 200, f"step {step}: {response.text}"
        assert step in response.json()["completed_steps"]

    final = response.json()
    assert final["status"] == "completed"
    assert final["progress_percent"] == 100.0

    # Completing the wizard activates the organization.
    organization = await client.get("/api/v1/organizations/me", headers=org_admin["headers"])
    assert organization.json()["status"] == "active"


async def test_out_of_order_step_is_rejected(client: AsyncClient, org_admin: dict) -> None:
    """Jumping to step 4 before 1-3 must fail and name the outstanding step."""
    response = await post_step(client, org_admin["headers"], 4)
    assert response.status_code == 400, response.text
    assert "step 1" in response.json()["message"].lower()


async def test_progress_advances_one_step_at_a_time(
    client: AsyncClient, org_admin: dict
) -> None:
    await post_step(client, org_admin["headers"], 1)
    blocked = await post_step(client, org_admin["headers"], 3)
    assert blocked.status_code == 400

    ok = await post_step(client, org_admin["headers"], 2)
    assert ok.status_code == 200
    assert ok.json()["current_step"] == 3


async def test_optional_step_five_can_be_skipped(
    client: AsyncClient, org_admin: dict
) -> None:
    for step in (1, 2, 3, 4):
        assert (await post_step(client, org_admin["headers"], step)).status_code == 200

    skipped = await client.post("/api/v1/onboarding/step/5/skip", headers=org_admin["headers"])
    assert skipped.status_code == 200, skipped.text
    body = skipped.json()
    assert 5 in body["skipped_steps"]
    assert 5 not in body["completed_steps"]
    assert body["current_step"] == 6

    # A skipped optional step must not block the rest of the wizard.
    for step in (6, 7):
        assert (await post_step(client, org_admin["headers"], step)).status_code == 200


async def test_required_step_cannot_be_skipped(client: AsyncClient, org_admin: dict) -> None:
    """Only step 5 is optional; the skip route does not exist for the others."""
    response = await client.post("/api/v1/onboarding/step/1/skip", headers=org_admin["headers"])
    assert response.status_code == 404


async def test_activation_requires_explicit_confirmation(
    client: AsyncClient, org_admin: dict
) -> None:
    for step in range(1, 7):
        assert (await post_step(client, org_admin["headers"], step)).status_code == 200

    response = await client.post(
        "/api/v1/onboarding/step/7", headers=org_admin["headers"], json={"confirmed": False}
    )
    assert response.status_code == 400


async def test_completed_wizard_rejects_further_steps(
    client: AsyncClient, org_admin: dict
) -> None:
    for step in range(1, 8):
        assert (await post_step(client, org_admin["headers"], step)).status_code == 200

    replay = await post_step(client, org_admin["headers"], 3)
    assert replay.status_code == 400
    assert "already complete" in replay.json()["message"].lower()


async def test_connector_config_rejects_inline_secrets(
    client: AsyncClient, org_admin: dict
) -> None:
    """config is readable org-wide, so a credential must not be accepted into it."""
    response = await client.post(
        "/api/v1/connectors",
        headers=org_admin["headers"],
        json={
            "connector_type": "supabase",
            "name": "Leaky",
            "config": {"api_key": "sbp_should_not_be_here"},
        },
    )
    assert response.status_code == 422
