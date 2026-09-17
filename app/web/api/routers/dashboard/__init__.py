"""Public, read-only dashboard API (``/api/v1/dashboard``)."""

from app.web.api.routers.dashboard.views import router

__all__ = ["router"]
