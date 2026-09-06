"""Organization routes.

Cross-organization reads are ``platform_admin`` only. Every other route
resolves the organization from the caller's token, or checks it explicitly via
``assert_can_access_organization``.

    codegraph explore "organizations views.py assert_can_access_organization"
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.web.api.deps import CurrentUser, SessionDep
from app.web.api.pagination import Cursor, CursorPage, PageSize, decode_cursor
from app.web.api.routers.organizations.schema import OrganizationRead, OrganizationUpdate
from app.web.core.exceptions import ResourceNotFoundError
from app.web.core.security import ADMIN_ROLES, PLATFORM_ONLY, require_roles
from app.web.db.services import user_service
from app.web.utils.datetime_utils import cursor_datetime

router = APIRouter(prefix="/organizations", tags=["organizations"])

PlatformUser = Depends(require_roles(*PLATFORM_ONLY))
AdminUser = Depends(require_roles(*ADMIN_ROLES))


@router.get("", response_model=CursorPage[OrganizationRead])
async def list_organizations(
    session: SessionDep,
    page_size: PageSize = 50,
    cursor: Cursor = None,
    current_user: CurrentUser = PlatformUser,
) -> CursorPage[OrganizationRead]:
    """List every organization. Platform administrators only."""
    created_before = cursor_datetime(decode_cursor(cursor)) if cursor else None
    rows = await user_service.list_organizations(
        session, limit=page_size + 1, created_before=created_before
    )
    items = [OrganizationRead.model_validate(row) for row in rows]
    return CursorPage.build(
        items,
        page_size=page_size,
        cursor_for=lambda item: {"created_at": item.created_at.isoformat()},
    )


@router.get("/me", response_model=OrganizationRead)
async def read_my_organization(
    session: SessionDep, current_user: CurrentUser = AdminUser
) -> OrganizationRead:
    """The caller's own organization."""
    organization = await user_service.get_organization(session, current_user.organization_id)
    if organization is None:
        raise ResourceNotFoundError(detail=f"organization {current_user.organization_id}")
    return OrganizationRead.model_validate(organization)


@router.get("/{organization_id}", response_model=OrganizationRead)
async def read_organization(
    organization_id: uuid.UUID, session: SessionDep, current_user: CurrentUser = AdminUser
) -> OrganizationRead:
    """Fetch one organization. Non-platform roles may only fetch their own."""
    current_user.assert_can_access_organization(organization_id)
    organization = await user_service.get_organization(session, organization_id)
    if organization is None:
        raise ResourceNotFoundError(detail=f"organization {organization_id}")
    return OrganizationRead.model_validate(organization)


@router.patch("/{organization_id}", response_model=OrganizationRead)
async def update_organization(
    organization_id: uuid.UUID,
    payload: OrganizationUpdate,
    session: SessionDep,
    current_user: CurrentUser = AdminUser,
) -> OrganizationRead:
    """Update organization details."""
    current_user.assert_can_access_organization(organization_id)
    organization = await user_service.get_organization(session, organization_id)
    if organization is None:
        raise ResourceNotFoundError(detail=f"organization {organization_id}")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(organization, field, value)
    await session.flush()
    return OrganizationRead.model_validate(organization)


__all__ = ["router"]
