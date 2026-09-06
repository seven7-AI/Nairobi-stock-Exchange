"""Role-based access control.

``require_roles(*roles)`` is the only way a route declares who may call it, and
it is applied **at the router**, never inside a business service. A service
receives an already-authorized ``CurrentUser`` and never inspects a role.

    codegraph explore "require_roles get_current_user CurrentUser UserRole"
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

from app.web.core.exceptions import AuthenticationError, AuthorizationError
from app.web.core.security.tokens import TokenType, decode_token
from app.web.db.models.enums import CROSS_ORG_ROLES, UserRole

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")


class CurrentUser(BaseModel):
    """The authenticated caller, resolved from a validated access token."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    email: str
    role: UserRole
    organization_id: uuid.UUID

    @property
    def can_read_across_organizations(self) -> bool:
        return self.role in CROSS_ORG_ROLES

    def assert_can_access_organization(self, organization_id: uuid.UUID) -> None:
        """Guard org-scoped reads and writes.

        Call this whenever an organization id arrives from the path or a body
        rather than from the caller's own token.
        """
        if self.can_read_across_organizations:
            return
        if organization_id != self.organization_id:
            raise AuthorizationError(
                detail=f"user org {self.organization_id} != requested {organization_id}"
            )


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> CurrentUser:
    """Resolve the caller from the ``Authorization: Bearer <token>`` header."""
    if credentials is None or not credentials.credentials:
        raise AuthenticationError(detail="missing bearer credentials")

    from app.web.core.dependencies import get_state

    settings = get_state(request).settings
    payload = decode_token(settings, credentials.credentials, expected_type=TokenType.ACCESS)
    return CurrentUser(
        id=payload.sub,
        email=payload.email,
        role=payload.role,
        organization_id=payload.organization_id,
    )


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def require_roles(
    *roles: UserRole,
) -> Callable[..., Coroutine[Any, Any, CurrentUser]]:
    """Build a dependency admitting only the given roles.

    Usage::

        @router.get("/", dependencies=[Depends(require_roles(UserRole.ANALYST))])

    or, when the handler needs the caller::

        async def handler(user: CurrentUser = Depends(require_roles(UserRole.ANALYST))):

    Passing no roles is rejected at import time: an empty allow-list would
    silently admit everyone, which is the opposite of what the caller meant.
    """
    if not roles:
        raise ValueError(
            "require_roles() needs at least one role. An empty allow-list would "
            "admit every authenticated caller."
        )
    allowed = frozenset(roles)

    async def _dependency(user: CurrentUserDep) -> CurrentUser:
        if user.role not in allowed:
            raise AuthorizationError(
                detail=f"role {user.role.value} not in {sorted(r.value for r in allowed)}"
            )
        return user

    _dependency.__name__ = f"require_roles_{'_'.join(sorted(r.value for r in allowed))}"
    return _dependency


#: Convenience role bundles. Prefer these over re-listing roles in every route,
#: so a permission change lands in one place.
ANY_AUTHENTICATED: tuple[UserRole, ...] = tuple(UserRole)
PLATFORM_ONLY: tuple[UserRole, ...] = (UserRole.PLATFORM_ADMIN,)
ADMIN_ROLES: tuple[UserRole, ...] = (UserRole.PLATFORM_ADMIN, UserRole.ORG_ADMIN)
RESEARCH_ROLES: tuple[UserRole, ...] = (
    UserRole.PLATFORM_ADMIN,
    UserRole.ORG_ADMIN,
    UserRole.ANALYST,
    UserRole.PORTFOLIO_MANAGER,
    UserRole.TRADER,
    UserRole.RESEARCH_VIEWER,
)
MARKET_DATA_ROLES: tuple[UserRole, ...] = RESEARCH_ROLES
PORTFOLIO_ROLES: tuple[UserRole, ...] = (
    UserRole.PLATFORM_ADMIN,
    UserRole.ORG_ADMIN,
    UserRole.PORTFOLIO_MANAGER,
    UserRole.ANALYST,
)

__all__ = [
    "ADMIN_ROLES",
    "ANY_AUTHENTICATED",
    "MARKET_DATA_ROLES",
    "PLATFORM_ONLY",
    "PORTFOLIO_ROLES",
    "RESEARCH_ROLES",
    "CurrentUser",
    "CurrentUserDep",
    "get_current_user",
    "require_roles",
]
