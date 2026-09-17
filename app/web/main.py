"""FastAPI application factory.

Startup and shutdown run through the **lifespan context manager**. There is no
``@app.on_event()`` anywhere in this codebase and there must not be — it is
deprecated, and it cannot express "build this, hand it to the app, tear it
down" without module-level globals.

    codegraph explore "create_app lifespan AppState register_exception_handlers"
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.concurrency import run_in_threadpool

from app.web.api.error_handlers import register_exception_handlers
from app.web.api.middleware import RequestContextMiddleware
from app.web.api.routers.analytics.views import router as analytics_router
from app.web.api.routers.auth.views import router as auth_router
from app.web.api.routers.connectors.views import router as connectors_router
from app.web.api.routers.dashboard.views import router as dashboard_router
from app.web.api.routers.indicators.views import router as indicators_router
from app.web.api.routers.instruments.views import router as instruments_router
from app.web.api.routers.market_data.views import router as market_data_router
from app.web.api.routers.onboarding.views import router as onboarding_router
from app.web.api.routers.organizations.views import router as organizations_router
from app.web.api.routers.reports.views import router as reports_router
from app.web.api.routers.research.views import router as research_router
from app.web.api.routers.users.views import router as users_router
from app.web.api.spa import SECURITY_HEADERS, mount_spa
from app.web.config import Settings, get_settings
from app.web.core.dependencies import build_app_state, set_app_state, shutdown_app_state
from app.web.utils.logger import configure_logging, get_logger

logger = get_logger("app.web.main")

#: Every domain router, mounted under the versioned prefix.
DOMAIN_ROUTERS = (
    auth_router,
    onboarding_router,
    organizations_router,
    users_router,
    instruments_router,
    market_data_router,
    indicators_router,
    analytics_router,
    reports_router,
    research_router,
    connectors_router,
)

DESCRIPTION = """
Market data, indicators, analytics and scheduled reporting for the
Nairobi Securities Exchange.

Authenticate at `POST /api/v1/auth/login` and send the access token as
`Authorization: Bearer <token>`. Every protected route declares the roles it
admits; see the `role` claim on your token.
"""


STANDALONE_DESCRIPTION = """
The **public dashboard** of the NSE Analytics Backend: read-only, no login.

Every endpoint under `/api/v1/dashboard` serves derived analytics and market prices
from the engine's SQLite store and the scraper's database; every number carries a
`status` and a `reason`, so missing is never shown as zero. Model outputs, not
investment advice.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build application state on startup, release it on shutdown."""
    settings = get_settings()
    configure_logging(settings.logs_dir / "nse_be.log", settings.log_level)

    state = build_app_state(settings)
    set_app_state(state)
    app.state.app_state = state
    logger.info(
        "service_started",
        app_name=settings.app_name,
        environment=settings.environment,
        beat_enabled=settings.celery_beat_enabled,
    )
    try:
        yield
    finally:
        await shutdown_app_state(state)
        logger.info("service_stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct the application. The only supported way to build it."""
    resolved = settings or get_settings()

    app = FastAPI(
        title="NSE Analytics Backend"
        + (" - public dashboard" if resolved.dashboard_standalone else ""),
        description=STANDALONE_DESCRIPTION if resolved.dashboard_standalone else DESCRIPTION,
        version="0.2.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(RequestContextMiddleware)
    if resolved.dashboard_standalone:
        # Same-origin SPA, no credentials: no CORS; plain security headers instead.
        @app.middleware("http")
        async def _security_headers(request: Request, call_next: Any) -> Any:
            response = await call_next(request)
            for name, value in SECURITY_HEADERS.items():
                response.headers.setdefault(name, value)
            return response
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    register_exception_handlers(app)

    api = APIRouter(prefix=resolved.api_v1_prefix)
    if not resolved.dashboard_standalone:
        for router in DOMAIN_ROUTERS:
            api.include_router(router)
    if resolved.dashboard_public or resolved.dashboard_standalone:
        # Unauthenticated, read-only, SQLite-only - see routers/dashboard/views.py.
        api.include_router(dashboard_router)
    app.include_router(api)
    app.include_router(_ops_router(resolved))

    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    # Last, so every route above wins; a no-op without a built dashboard.
    mount_spa(app, resolved)
    return app


def _ops_router(settings: Settings) -> APIRouter:
    """Unauthenticated operational endpoints."""
    router = APIRouter(tags=["ops"])

    @router.get("/health")
    async def health() -> dict[str, Any]:
        """Docker healthcheck target. Deliberately cheap and dependency-free."""
        return {
            "status": "ok",
            "service": settings.app_name,
            "environment": settings.environment,
            "version": "0.2.0",
        }

    @router.get("/health/ready")
    async def readiness() -> dict[str, Any]:
        """Readiness: reports whether backing services answer.

        Never fails the request — an orchestrator reads the body, and a 500
        here would hide which dependency is actually down.
        """
        from app.web.core.dependencies import get_app_state

        state = get_app_state()
        if settings.dashboard_standalone:
            return await _standalone_readiness(settings, state)
        redis_ok = await state.redis.ping()
        database_ok = True
        try:
            async with state.session_factory() as session:
                from sqlalchemy import text

                await session.execute(text("SELECT 1"))
        except Exception:
            logger.warning("readiness_database_unreachable")
            database_ok = False

        # The market-data source is reported in full rather than as a bool: an
        # operator needs to tell "cannot read it" from "read it, but nothing has
        # refreshed it since Tuesday". Both are unhealthy, for different reasons.
        try:
            source_health = state.market_data_source.health_check().to_dict()
        except Exception:
            logger.warning("readiness_market_data_source_unreachable")
            source_health = {"name": state.market_data_source.name, "status": "unreachable"}

        source_ok = source_health.get("status") == "ok"
        return {
            "status": "ok" if (redis_ok and database_ok and source_ok) else "degraded",
            "redis": redis_ok,
            "database": database_ok,
            "market_data_source": source_health,
        }

    return router


async def _standalone_readiness(settings: Settings, state: Any) -> dict[str, Any]:
    """The public port has no Postgres and no Redis: report the two SQLite files."""
    from app.web.services.analytics.store import analytics_db_status

    store_ok = False
    revision: str | None = None
    try:
        status = await run_in_threadpool(analytics_db_status, settings.analytics_db_path)
        store_ok = status.exists and status.current_revision == status.head_revision
        revision = status.current_revision
    except Exception:
        logger.warning("readiness_analytics_store_unreachable")
    try:
        source_health = await run_in_threadpool(state.market_data_source.health_check)
        source = source_health.to_dict()
        source.pop("location", None)
    except Exception:
        logger.warning("readiness_market_data_source_unreachable")
        source = {"name": state.market_data_source.name, "status": "unreachable"}
    source_ok = source.get("status") == "ok"
    return {
        "status": "ok" if (store_ok and source_ok) else "degraded",
        "analytics_store": {"ok": store_ok, "revision": revision},
        "market_data_source": source,
        "dashboard": (settings.dashboard_dist_dir / "index.html").is_file(),
    }


app = create_app()

__all__ = ["app", "create_app", "lifespan"]
