"""Domain-specific exceptions.

Business services raise these. Routers never raise them and never catch them
one by one — the handlers registered in ``app/web/main.py`` translate the
hierarchy into responses.

**A 4xx/5xx body must never carry a stack trace or an internal detail.** Each
exception therefore has two messages: ``message`` is safe to return to a
client, ``detail`` is for logs only.

    codegraph explore "NSEAnalysisError register_exception_handlers main.py"
"""

from __future__ import annotations

from http import HTTPStatus


class NSEAnalysisError(Exception):
    """Base exception for the nse-be service."""

    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    #: Returned to the client when the raiser supplies no message.
    default_message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None, *, detail: str | None = None) -> None:
        self.message = message or self.default_message
        #: Never serialized into a response. For structured logs only.
        self.detail = detail
        super().__init__(self.message)


# --- infrastructure ---------------------------------------------------------
class DatabaseConnectionError(NSEAnalysisError):
    """Raised when the database cannot be reached."""

    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    default_message = "The data store is temporarily unavailable."


class ExternalServiceError(NSEAnalysisError):
    """Raised when an upstream dependency fails."""

    status_code = HTTPStatus.BAD_GATEWAY
    default_message = "An upstream data source is unavailable."


# --- data / domain ----------------------------------------------------------
class DataValidationError(NSEAnalysisError):
    """Raised when inbound data fails validation checks."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    default_message = "The submitted data failed validation."


class IndicatorCalculationError(NSEAnalysisError):
    """Raised when indicators cannot be computed safely."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    default_message = "Indicators could not be calculated for this instrument."


class ReportGenerationError(NSEAnalysisError):
    """Raised when report rendering fails."""

    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    default_message = "The report could not be generated."


# --- resources --------------------------------------------------------------
class ResourceNotFoundError(NSEAnalysisError):
    """Raised when a requested resource does not exist or is out of scope."""

    status_code = HTTPStatus.NOT_FOUND
    default_message = "The requested resource was not found."


class ResourceConflictError(NSEAnalysisError):
    """Raised when a write would violate a uniqueness or state constraint."""

    status_code = HTTPStatus.CONFLICT
    default_message = "The request conflicts with the current state."


# --- auth -------------------------------------------------------------------
class AuthenticationError(NSEAnalysisError):
    """Raised when credentials are missing, malformed, or invalid."""

    status_code = HTTPStatus.UNAUTHORIZED
    default_message = "Could not validate credentials."


class AuthorizationError(NSEAnalysisError):
    """Raised when an authenticated caller lacks the required role or scope.

    The message is deliberately uniform: telling a caller *which* role would
    have worked leaks the permission model.
    """

    status_code = HTTPStatus.FORBIDDEN
    default_message = "You do not have permission to perform this action."


# --- onboarding -------------------------------------------------------------
class OnboardingStepError(NSEAnalysisError):
    """Raised when a wizard step is attempted out of order or is already done."""

    status_code = HTTPStatus.BAD_REQUEST
    default_message = "This onboarding step cannot be completed yet."


__all__ = [
    "AuthenticationError",
    "AuthorizationError",
    "DataValidationError",
    "DatabaseConnectionError",
    "ExternalServiceError",
    "IndicatorCalculationError",
    "NSEAnalysisError",
    "OnboardingStepError",
    "ReportGenerationError",
    "ResourceConflictError",
    "ResourceNotFoundError",
]
