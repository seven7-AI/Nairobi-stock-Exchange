"""Shared FastAPI dependency aliases.

Routers import these rather than re-deriving ``Depends()`` chains, so the
session, settings and service wiring is declared in exactly one place.

    codegraph explore "SessionDep CurrentUserDep get_async_session require_roles"
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.web.config import Settings
from app.web.core.dependencies import (
    get_email,
    get_redis,
    get_settings_dep,
    get_storage,
    get_supabase,
)
from app.web.core.security.rbac import CurrentUser, CurrentUserDep, get_current_user
from app.web.db.base import get_async_session
from app.web.services.email import EmailService
from app.web.services.market_data.supabase_client import SupabaseConnection
from app.web.services.redis import RedisService
from app.web.services.storage import StorageService

SessionDep = Annotated[AsyncSession, Depends(get_async_session)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
RedisDep = Annotated[RedisService, Depends(get_redis)]
EmailDep = Annotated[EmailService, Depends(get_email)]
StorageDep = Annotated[StorageService, Depends(get_storage)]
SupabaseDep = Annotated[SupabaseConnection | None, Depends(get_supabase)]

__all__ = [
    "CurrentUser",
    "CurrentUserDep",
    "EmailDep",
    "RedisDep",
    "SessionDep",
    "SettingsDep",
    "StorageDep",
    "SupabaseDep",
    "get_current_user",
]
