"""Enumerations shared across models, schemas, and RBAC.

``UserRole`` is the single definition of the seven platform roles. RBAC
dependencies, JWT claims, and every ``require_roles(...)`` call resolve to this
enum — never to a bare string literal.

    codegraph explore "UserRole require_roles rbac.py"
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


class UserRole(StrEnum):
    """The seven platform roles."""

    PLATFORM_ADMIN = "platform_admin"
    ORG_ADMIN = "org_admin"
    ANALYST = "analyst"
    PORTFOLIO_MANAGER = "portfolio_manager"
    TRADER = "trader"
    RESEARCH_VIEWER = "research_viewer"
    CLIENT = "client"


#: Roles permitted to read data belonging to an organization other than their own.
CROSS_ORG_ROLES: frozenset[UserRole] = frozenset({UserRole.PLATFORM_ADMIN})

#: Roles with administrative authority inside a single organization.
ORG_ADMIN_ROLES: frozenset[UserRole] = frozenset(
    {UserRole.PLATFORM_ADMIN, UserRole.ORG_ADMIN}
)


class OnboardingStatus(StrEnum):
    """Lifecycle of an organization's onboarding wizard."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class OrganizationStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"


class UserStatus(StrEnum):
    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    DISABLED = "disabled"


class ReportKind(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ReportRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ConnectorType(StrEnum):
    SUPABASE = "supabase"
    SCRAPER = "scraper"
    CSV_ARCHIVE = "csv_archive"


class ConnectorStatus(StrEnum):
    UNCONFIGURED = "unconfigured"
    CONNECTED = "connected"
    ERROR = "error"


class InstrumentStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELISTED = "delisted"


def pg_enum(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """Postgres ENUM column type that persists the enum *value*, not its name.

    SQLAlchemy's default is to store ``member.name`` (``PLATFORM_ADMIN``). Every
    other surface in this system — JWT role claims, API request and response
    bodies, ``require_roles(...)`` — speaks the ``StrEnum`` *value*
    (``platform_admin``). Storing the name would mean translating at every
    boundary and getting it wrong once. Store the value.
    """
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda members: [member.value for member in members],
    )
