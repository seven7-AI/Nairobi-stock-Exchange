"""Application state and dependency injection.

``AppState`` is built once, in the lifespan context manager in
``app/web/main.py``, and every service reaches request handlers through
``Depends()``. Nothing constructs a client at import time, and nothing reads
``os.environ`` directly.

**There is no ``@app.on_event()`` in this codebase. Use lifespan.**

    codegraph explore "AppState build_app_state lifespan main.py"
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.web.config import Settings, get_settings
from app.web.db.base import build_async_engine, build_async_session_factory
from app.web.services.email import EmailService
from app.web.services.market_data.supabase_client import SupabaseConnection
from app.web.services.redis import RedisService
from app.web.services.storage import StorageService
from app.web.utils.logger import get_logger

logger = get_logger("app.web.core.dependencies")


@dataclass(slots=True)
class AppState:
    """Everything the service needs, resolved once at startup."""

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    redis: RedisService
    email: EmailService
    storage: StorageService
    supabase: SupabaseConnection | None = None


_app_state: AppState | None = None


def build_app_state(settings: Settings | None = None) -> AppState:
    """Construct application state. Called by the lifespan handler only."""
    resolved = settings or get_settings()
    engine = build_async_engine(resolved)

    supabase: SupabaseConnection | None
    try:
        supabase = SupabaseConnection(resolved)
    except Exception:
        # The upstream market-data table is optional at boot: the API still
        # serves everything backed by our own tables without it.
        logger.warning("supabase_client_unavailable_at_startup")
        supabase = None

    return AppState(
        settings=resolved,
        engine=engine,
        session_factory=build_async_session_factory(engine),
        redis=RedisService.from_settings(resolved),
        email=EmailService(resolved),
        storage=StorageService(resolved),
        supabase=supabase,
    )


def set_app_state(state: AppState | None) -> None:
    """Install (or clear) the process-wide state. Lifespan owns this."""
    global _app_state
    _app_state = state


def get_app_state() -> AppState:
    """Return the initialized state, or fail loudly if startup did not run."""
    if _app_state is None:
        raise RuntimeError(
            "AppState is not initialized. It is built by the lifespan context "
            "manager in app/web/main.py — construct the app through create_app()."
        )
    return _app_state


async def shutdown_app_state(state: AppState) -> None:
    """Release every resource acquired at startup."""
    await state.redis.close()
    await state.engine.dispose()
    set_app_state(None)


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------
def get_state(request: Request) -> AppState:
    """Prefer the state attached to the app; fall back to the module global."""
    state: AppState | None = getattr(request.app.state, "app_state", None)
    return state or get_app_state()


def get_settings_dep(request: Request) -> Settings:
    return get_state(request).settings


def get_redis(request: Request) -> RedisService:
    return get_state(request).redis


def get_email(request: Request) -> EmailService:
    return get_state(request).email


def get_storage(request: Request) -> StorageService:
    return get_state(request).storage


def get_supabase(request: Request) -> SupabaseConnection | None:
    return get_state(request).supabase


__all__ = [
    "AppState",
    "build_app_state",
    "get_app_state",
    "get_email",
    "get_redis",
    "get_settings_dep",
    "get_state",
    "get_storage",
    "get_supabase",
    "set_app_state",
    "shutdown_app_state",
]
