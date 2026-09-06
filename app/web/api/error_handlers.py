"""Exception handlers.

The contract: a 4xx/5xx body carries a stable ``error`` code, a safe
``message``, and the request id. It never carries a stack trace, a SQL string,
or the exception's ``detail`` field — those go to the log only.

    codegraph explore "register_exception_handlers NSEAnalysisError main.py"
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.web.core.exceptions import NSEAnalysisError
from app.web.utils.logger import get_logger

logger = get_logger("app.web.api.errors")


def _request_id(request: Request) -> str | None:
    value: str | None = getattr(request.state, "request_id", None)
    return value


def _body(error: str, message: str, request: Request, **extra: Any) -> dict[str, Any]:
    return {
        "error": error,
        "message": message,
        "request_id": _request_id(request),
        **extra,
    }


def register_exception_handlers(app: FastAPI) -> None:
    """Install every handler. Called once from ``create_app``."""

    @app.exception_handler(NSEAnalysisError)
    async def _domain_error(request: Request, exc: NSEAnalysisError) -> JSONResponse:
        # `detail` is the internal explanation and stays in the log.
        logger.warning(
            "domain_error",
            request_id=_request_id(request),
            error=type(exc).__name__,
            status_code=exc.status_code,
            detail=exc.detail,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(type(exc).__name__, exc.message, request),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Pydantic's own errors name fields and constraints, not values, so they
        # are safe to return — but strip any echoed input just in case.
        errors = [
            {"loc": err.get("loc"), "msg": err.get("msg"), "type": err.get("type")}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            content=_body(
                "ValidationError", "The request body failed validation.", request, errors=errors
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_body("HTTPError", str(exc.detail), request),
        )

    @app.exception_handler(SQLAlchemyError)
    async def _db_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        # str(exc) contains the failing SQL and often bound parameters.
        logger.exception(
            "database_error",
            request_id=_request_id(request),
            error=type(exc).__name__,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            content=_body(
                "DatabaseError", "The data store is temporarily unavailable.", request
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_error",
            request_id=_request_id(request),
            error=type(exc).__name__,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            content=_body("InternalServerError", "An unexpected error occurred.", request),
        )


__all__ = ["register_exception_handlers"]
