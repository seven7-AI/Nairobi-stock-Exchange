"""Onboarding wizard persistence and step-ordering rules.

The ordering invariant lives here rather than in the router so that both the
API and any future CLI path enforce it identically.

    codegraph explore "advance_step OnboardingState ONBOARDING_STEPS onboarding views.py"
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.web.core.exceptions import OnboardingStepError, ResourceNotFoundError
from app.web.db.models.enums import OnboardingStatus, OrganizationStatus
from app.web.db.models.onboarding_state import (
    ONBOARDING_STEPS,
    OPTIONAL_ONBOARDING_STEPS,
    TOTAL_ONBOARDING_STEPS,
    OnboardingState,
)
from app.web.db.models.organization import Organization


def step_name(step: int) -> str:
    """Human-readable name for a step number."""
    if not 1 <= step <= TOTAL_ONBOARDING_STEPS:
        raise OnboardingStepError(
            f"Step must be between 1 and {TOTAL_ONBOARDING_STEPS}.",
            detail=f"requested step {step}",
        )
    return ONBOARDING_STEPS[step - 1]


async def get_state(
    session: AsyncSession, organization_id: uuid.UUID
) -> OnboardingState | None:
    result = await session.execute(
        select(OnboardingState).where(OnboardingState.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


async def get_or_create_state(
    session: AsyncSession, organization_id: uuid.UUID
) -> OnboardingState:
    state = await get_state(session, organization_id)
    if state is not None:
        return state
    state = OnboardingState(
        organization_id=organization_id,
        current_step=1,
        completed_steps=[],
        skipped_steps=[],
        status=OnboardingStatus.NOT_STARTED,
        step_data={},
    )
    session.add(state)
    await session.flush()
    return state


def _assert_step_reachable(state: OnboardingState, step: int) -> None:
    """Reject an out-of-order step, naming the first one still outstanding."""
    if state.status == OnboardingStatus.COMPLETED:
        raise OnboardingStepError(
            "Onboarding is already complete.", detail=f"org {state.organization_id}"
        )
    if state.can_start_step(step):
        return
    outstanding = next(
        prior for prior in range(1, step) if not state.is_step_complete(prior)
    )
    raise OnboardingStepError(
        f"Step {step} ({step_name(step)}) cannot be started until step "
        f"{outstanding} ({step_name(outstanding)}) is complete.",
        detail=f"org {state.organization_id} at step {state.current_step}",
    )


def _record(state: OnboardingState, step: int, *, skipped: bool) -> None:
    """Mark a step done or skipped and move the cursor forward."""
    if skipped:
        state.skipped_steps = sorted({*state.skipped_steps, step})
    else:
        state.completed_steps = sorted({*state.completed_steps, step})
    state.last_completed_step_name = step_name(step)
    state.current_step = min(max(state.current_step, step + 1), TOTAL_ONBOARDING_STEPS)
    state.status = (
        OnboardingStatus.COMPLETED
        if all(state.is_step_complete(n) for n in range(1, TOTAL_ONBOARDING_STEPS + 1))
        else OnboardingStatus.IN_PROGRESS
    )


async def complete_step(
    session: AsyncSession,
    organization_id: uuid.UUID,
    step: int,
    payload: dict[str, Any],
) -> OnboardingState:
    """Record a completed step after validating that prior steps are done."""
    name = step_name(step)
    state = await get_or_create_state(session, organization_id)
    _assert_step_reachable(state, step)

    state.step_data = {**state.step_data, name: payload}
    _record(state, step, skipped=False)
    await _activate_when_finished(session, state)
    await session.flush()
    return state


async def skip_step(
    session: AsyncSession, organization_id: uuid.UUID, step: int
) -> OnboardingState:
    """Skip an optional step. Only step 5 (data connectors) may be skipped."""
    step_name(step)  # validates the range
    if step not in OPTIONAL_ONBOARDING_STEPS:
        raise OnboardingStepError(
            f"Step {step} ({step_name(step)}) is required and cannot be skipped.",
            detail=f"optional steps are {sorted(OPTIONAL_ONBOARDING_STEPS)}",
        )
    state = await get_or_create_state(session, organization_id)
    _assert_step_reachable(state, step)
    _record(state, step, skipped=True)
    await _activate_when_finished(session, state)
    await session.flush()
    return state


async def _activate_when_finished(session: AsyncSession, state: OnboardingState) -> None:
    """Activate the organization once the wizard is complete."""
    if state.status != OnboardingStatus.COMPLETED:
        return
    organization = await session.get(Organization, state.organization_id)
    if organization is None:
        raise ResourceNotFoundError(detail=f"organization {state.organization_id}")
    organization.status = OrganizationStatus.ACTIVE


def progress_percent(state: OnboardingState) -> float:
    done = sum(
        1 for step in range(1, TOTAL_ONBOARDING_STEPS + 1) if state.is_step_complete(step)
    )
    return round(done / TOTAL_ONBOARDING_STEPS * 100, 1)


__all__ = [
    "complete_step",
    "get_or_create_state",
    "get_state",
    "progress_percent",
    "skip_step",
    "step_name",
]
