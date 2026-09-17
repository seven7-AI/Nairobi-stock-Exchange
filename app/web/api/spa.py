"""Serve the built dashboard (``dashboard/dist``) with single-page-app semantics.

Mounted last in ``create_app`` so every API route, ``/health``, ``/docs`` and
``/metrics`` match first. An unknown extension-less GET under the mount is a
client-side route and gets ``index.html``; anything under the API prefix stays a
JSON 404; ``index.html`` is never cached, hashed assets are cached for a year.

    codegraph explore "SpaStaticFiles mount_spa create_app"
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from app.web.config import Settings
from app.web.utils.logger import get_logger

logger = get_logger(__name__)

ASSETS_CACHE = "public, max-age=31536000, immutable"
INDEX_CACHE = "no-cache"
#: Sent with every SPA response; the API sets its own headers.
SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
INDEX_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; font-src 'self'; frame-ancestors 'none'"
)


class SpaStaticFiles(StaticFiles):
    """``StaticFiles`` with the fallback a browser router needs."""

    def __init__(self, *, directory: Path, api_prefix: str) -> None:
        super().__init__(directory=str(directory), html=True, check_dir=True)
        self._api_prefix = api_prefix.rstrip("/") + "/"

    async def get_response(self, path: str, scope: Scope) -> Response:
        request_path = str(scope.get("path") or "")
        if request_path.startswith(self._api_prefix):
            # An API path nothing routed: a JSON 404 from the app, never the SPA and
            # never a 405 for a POST that found no handler.
            raise HTTPException(status_code=404)
        if path in ("", "."):  # Starlette normalises "/" to "."
            path = "index.html"
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or scope["method"] not in ("GET", "HEAD"):
                raise
            if "." in path.rsplit("/", 1)[-1]:
                raise  # a real file that does not exist stays a 404
            response = await super().get_response("index.html", scope)
        _decorate(response)
        return response


def _decorate(response: Response) -> None:
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    served = str(getattr(response, "path", "") or "")
    if served.endswith(".html"):
        response.headers["Cache-Control"] = INDEX_CACHE
        response.headers.setdefault("Content-Security-Policy", INDEX_CSP)
    elif f"{os.sep}assets{os.sep}" in served:
        response.headers["Cache-Control"] = ASSETS_CACHE


def mount_spa(app: FastAPI, settings: Settings) -> bool:
    """Mount the built dashboard at ``/`` when ``dist/index.html`` exists."""
    dist = settings.dashboard_dist_dir
    if not (dist / "index.html").is_file():
        logger.info("dashboard_spa_not_mounted", reason="no dist/index.html")
        return False
    app.mount(
        "/",
        SpaStaticFiles(directory=dist, api_prefix=settings.api_v1_prefix),
        name="dashboard-spa",
    )
    logger.info("dashboard_spa_mounted")
    return True


__all__ = ["SECURITY_HEADERS", "SpaStaticFiles", "mount_spa"]
