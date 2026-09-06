"""JWT issuing/verification, RBAC dependencies, password hashing."""

from app.web.core.security.password import (
    hash_password,
    is_password_acceptable,
    verify_password,
)
from app.web.core.security.rbac import (
    ADMIN_ROLES,
    ANY_AUTHENTICATED,
    MARKET_DATA_ROLES,
    PLATFORM_ONLY,
    PORTFOLIO_ROLES,
    RESEARCH_ROLES,
    CurrentUser,
    CurrentUserDep,
    get_current_user,
    require_roles,
)
from app.web.core.security.tokens import (
    TokenPayload,
    TokenType,
    create_access_token,
    create_purpose_token,
    create_refresh_token,
    decode_token,
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
    "TokenPayload",
    "TokenType",
    "create_access_token",
    "create_purpose_token",
    "create_refresh_token",
    "decode_token",
    "get_current_user",
    "hash_password",
    "is_password_acceptable",
    "require_roles",
    "verify_password",
]
