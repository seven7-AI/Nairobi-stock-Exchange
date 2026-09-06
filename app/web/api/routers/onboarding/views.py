"""The 7-step organization onboarding wizard.

Steps are strictly ordered: a step is only reachable once every prior step is
complete or skipped. Step 5 (data connectors) is the sole optional step.
Ordering is enforced in ``onboarding_service`` rather than here, so the rule
holds for every caller.

    codegraph explore "onboarding views.py complete_step skip_step OnboardingState"
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.web.api.deps import CurrentUser, SessionDep
from app.web.api.routers.onboarding.schema import (
    DataConnectorsStep,
    MarketCoverageStep,
    OnboardingStateRead,
    OrganizationProfileStep,
    ReportPreferencesStep,
    ReviewActivateStep,
    StepDescriptor,
    TeamInvitationsStep,
    WatchlistSetupStep,
)
from app.web.core.exceptions import OnboardingStepError
from app.web.core.security import ADMIN_ROLES, require_roles
from app.web.db.models.onboarding_state import (
    ONBOARDING_STEPS,
    OPTIONAL_ONBOARDING_STEPS,
    TOTAL_ONBOARDING_STEPS,
    OnboardingState,
)
from app.web.db.services import onboarding_service
from app.web.utils.logger import get_logger

router = APIRouter(prefix="/onboarding", tags=["onboarding"])
logger = get_logger("app.web.api.onboarding")

#: The wizard configures the organization itself, so it is admin-only.
AdminUser = Depends(require_roles(*ADMIN_ROLES))


def _to_read(state: OnboardingState) -> OnboardingStateRead:
    return OnboardingStateRead(
        organization_id=state.organization_id,
        current_step=state.current_step,
        current_step_name=onboarding_service.step_name(state.current_step),
        completed_steps=list(state.completed_steps),
        skipped_steps=list(state.skipped_steps),
        status=state.status,
        progress_percent=onboarding_service.progress_percent(state),
        total_steps=TOTAL_ONBOARDING_STEPS,
        steps=[
            StepDescriptor(
                number=number,
                name=name,
                is_complete=number in state.completed_steps,
                is_skipped=number in state.skipped_steps,
                is_optional=number in OPTIONAL_ONBOARDING_STEPS,
            )
            for number, name in enumerate(ONBOARDING_STEPS, start=1)
        ],
    )


@router.get("/state", response_model=OnboardingStateRead)
async def read_state(
    session: SessionDep, current_user: CurrentUser = AdminUser
) -> OnboardingStateRead:
    """Current wizard progress for the caller's organization."""
    state = await onboarding_service.get_or_create_state(session, current_user.organization_id)
    return _to_read(state)


async def _complete(
    session: SessionDep, current_user: CurrentUser, step: int, payload: dict[str, object]
) -> OnboardingStateRead:
    state = await onboarding_service.complete_step(
        session, current_user.organization_id, step, payload
    )
    logger.info(
        "onboarding_step_completed",
        organization_id=str(current_user.organization_id),
        step=step,
        status=state.status.value,
    )
    return _to_read(state)


@router.post("/step/1", response_model=OnboardingStateRead)
async def step_1_organization_profile(
    payload: OrganizationProfileStep, session: SessionDep, current_user: CurrentUser = AdminUser
) -> OnboardingStateRead:
    """Step 1 — organization profile."""
    return await _complete(session, current_user, 1, payload.model_dump(mode="json"))


@router.post("/step/2", response_model=OnboardingStateRead)
async def step_2_team_invitations(
    payload: TeamInvitationsStep, session: SessionDep, current_user: CurrentUser = AdminUser
) -> OnboardingStateRead:
    """Step 2 — invite team members and assign roles."""
    return await _complete(session, current_user, 2, payload.model_dump(mode="json"))


@router.post("/step/3", response_model=OnboardingStateRead)
async def step_3_market_coverage(
    payload: MarketCoverageStep, session: SessionDep, current_user: CurrentUser = AdminUser
) -> OnboardingStateRead:
    """Step 3 — exchanges and sectors to cover."""
    return await _complete(session, current_user, 3, payload.model_dump(mode="json"))


@router.post("/step/4", response_model=OnboardingStateRead)
async def step_4_watchlist_setup(
    payload: WatchlistSetupStep, session: SessionDep, current_user: CurrentUser = AdminUser
) -> OnboardingStateRead:
    """Step 4 — initial watchlist."""
    return await _complete(session, current_user, 4, payload.model_dump(mode="json"))


@router.post("/step/5", response_model=OnboardingStateRead)
async def step_5_data_connectors(
    payload: DataConnectorsStep, session: SessionDep, current_user: CurrentUser = AdminUser
) -> OnboardingStateRead:
    """Step 5 — data connectors. Optional: see ``POST /onboarding/step/5/skip``."""
    return await _complete(session, current_user, 5, payload.model_dump(mode="json"))


@router.post("/step/5/skip", response_model=OnboardingStateRead)
async def skip_step_5(
    session: SessionDep, current_user: CurrentUser = AdminUser
) -> OnboardingStateRead:
    """Skip the optional connectors step and advance to step 6."""
    state = await onboarding_service.skip_step(session, current_user.organization_id, 5)
    logger.info(
        "onboarding_step_skipped",
        organization_id=str(current_user.organization_id),
        step=5,
    )
    return _to_read(state)


@router.post("/step/6", response_model=OnboardingStateRead)
async def step_6_report_preferences(
    payload: ReportPreferencesStep, session: SessionDep, current_user: CurrentUser = AdminUser
) -> OnboardingStateRead:
    """Step 6 — report cadence and delivery."""
    return await _complete(session, current_user, 6, payload.model_dump(mode="json"))


@router.post("/step/7", response_model=OnboardingStateRead)
async def step_7_review_and_activate(
    payload: ReviewActivateStep, session: SessionDep, current_user: CurrentUser = AdminUser
) -> OnboardingStateRead:
    """Step 7 — review and activate. Completing this activates the organization."""
    if not payload.confirmed:
        raise OnboardingStepError("Activation must be explicitly confirmed.")
    return await _complete(session, current_user, 7, payload.model_dump(mode="json"))


__all__ = ["router"]
