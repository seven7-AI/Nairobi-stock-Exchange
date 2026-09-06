"""User management within an organization.

Org scoping comes from the caller's token, never from a request body — a
client cannot create a user inside somebody else's organization by supplying
its id.

    codegraph explore "users views.py create_user set_role assert_can_access_organization"
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.web.api.deps import CurrentUser, SessionDep
from app.web.api.pagination import Cursor, CursorPage, PageSize, decode_cursor
from app.web.api.routers.users.schema import (
    UserCreate,
    UserRead,
    UserRoleUpdate,
    UserStatusUpdate,
)
from app.web.core.exceptions import (
    AuthorizationError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from app.web.core.security import ADMIN_ROLES, hash_password, require_roles
from app.web.db.models.enums import UserRole, UserStatus
from app.web.db.models.user import User
from app.web.db.services import user_service
from app.web.utils.datetime_utils import cursor_datetime
from app.web.utils.logger import get_logger

router = APIRouter(prefix="/users", tags=["users"])
logger = get_logger("app.web.api.users")

AdminUser = Depends(require_roles(*ADMIN_ROLES))


async def _load_in_scope(session: SessionDep, user_id: uuid.UUID, caller: CurrentUser) -> User:
    user = await user_service.get_user_by_id(session, user_id)
    if user is None:
        raise ResourceNotFoundError(detail=f"user {user_id}")
    caller.assert_can_access_organization(user.organization_id)
    return user


@router.get("", response_model=CursorPage[UserRead])
async def list_users(
    session: SessionDep,
    page_size: PageSize = 50,
    cursor: Cursor = None,
    current_user: CurrentUser = AdminUser,
) -> CursorPage[UserRead]:
    """Users in the caller's organization."""
    created_before = cursor_datetime(decode_cursor(cursor)) if cursor else None
    rows = await user_service.list_users_for_organization(
        session,
        current_user.organization_id,
        limit=page_size + 1,
        created_before=created_before,
    )
    items = [UserRead.model_validate(row) for row in rows]
    return CursorPage.build(
        items,
        page_size=page_size,
        cursor_for=lambda item: {"created_at": item.created_at.isoformat()},
    )


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate, session: SessionDep, current_user: CurrentUser = AdminUser
) -> UserRead:
    """Add a user to the caller's organization.

    Only a ``platform_admin`` may mint another ``platform_admin``; an
    ``org_admin`` cannot escalate anyone above their own scope.
    """
    if payload.role == UserRole.PLATFORM_ADMIN and not current_user.can_read_across_organizations:
        raise AuthorizationError(detail=f"{current_user.role.value} tried to create platform_admin")
    if await user_service.get_user_by_email(session, payload.email) is not None:
        raise ResourceConflictError("An account with that email already exists.")

    user = await user_service.create_user(
        session,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        organization_id=current_user.organization_id,
        role=payload.role,
        full_name=payload.full_name,
    )
    logger.info("user_created", user_id=str(user.id), role=user.role.value)
    return UserRead.model_validate(user)


@router.get("/{user_id}", response_model=UserRead)
async def read_user(
    user_id: uuid.UUID, session: SessionDep, current_user: CurrentUser = AdminUser
) -> UserRead:
    """Fetch one user from the caller's organization."""
    return UserRead.model_validate(await _load_in_scope(session, user_id, current_user))


@router.patch("/{user_id}/role", response_model=UserRead)
async def update_user_role(
    user_id: uuid.UUID,
    payload: UserRoleUpdate,
    session: SessionDep,
    current_user: CurrentUser = AdminUser,
) -> UserRead:
    """Change a user's role."""
    if payload.role == UserRole.PLATFORM_ADMIN and not current_user.can_read_across_organizations:
        raise AuthorizationError(detail=f"{current_user.role.value} tried to grant platform_admin")
    if user_id == current_user.id:
        raise AuthorizationError(
            "You cannot change your own role.", detail="self role change blocked"
        )
    user = await _load_in_scope(session, user_id, current_user)
    await user_service.set_role(session, user, payload.role)
    logger.info("user_role_changed", user_id=str(user_id), role=payload.role.value)
    return UserRead.model_validate(user)


@router.patch("/{user_id}/status", response_model=UserRead)
async def update_user_status(
    user_id: uuid.UUID,
    payload: UserStatusUpdate,
    session: SessionDep,
    current_user: CurrentUser = AdminUser,
) -> UserRead:
    """Enable or disable a user."""
    if user_id == current_user.id and payload.status == UserStatus.DISABLED:
        raise AuthorizationError(
            "You cannot disable your own account.", detail="self disable blocked"
        )
    user = await _load_in_scope(session, user_id, current_user)
    await user_service.set_status(session, user, payload.status)
    logger.info("user_status_changed", user_id=str(user_id), status=payload.status.value)
    return UserRead.model_validate(user)


__all__ = ["router"]
