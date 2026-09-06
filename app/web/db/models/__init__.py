"""SQLAlchemy models — one file per table.

Every model must be imported here: Alembic autogenerate only sees what is
attached to ``Base.metadata`` at import time. A model missing from this list
silently never gets a migration.

    codegraph explore "Base metadata target_metadata env.py autogenerate"
"""

from app.web.db.base import Base
from app.web.db.models.base import TimestampMixin, UUIDMixin
from app.web.db.models.connector import Connector
from app.web.db.models.enums import (
    ConnectorStatus,
    ConnectorType,
    InstrumentStatus,
    OnboardingStatus,
    OrganizationStatus,
    ReportKind,
    ReportRunStatus,
    UserRole,
    UserStatus,
    pg_enum,
)
from app.web.db.models.external import StockAnalysisStock
from app.web.db.models.indicator_snapshot import IndicatorSnapshot
from app.web.db.models.instrument import Instrument
from app.web.db.models.onboarding_state import (
    ONBOARDING_STEPS,
    OPTIONAL_ONBOARDING_STEPS,
    TOTAL_ONBOARDING_STEPS,
    OnboardingState,
)
from app.web.db.models.organization import Organization
from app.web.db.models.price_bar import PriceBar
from app.web.db.models.report_run import ReportRun
from app.web.db.models.user import User
from app.web.db.models.watchlist import Watchlist, WatchlistItem

__all__ = [
    "ONBOARDING_STEPS",
    "OPTIONAL_ONBOARDING_STEPS",
    "TOTAL_ONBOARDING_STEPS",
    "Base",
    "Connector",
    "ConnectorStatus",
    "ConnectorType",
    "IndicatorSnapshot",
    "Instrument",
    "InstrumentStatus",
    "OnboardingState",
    "OnboardingStatus",
    "Organization",
    "OrganizationStatus",
    "PriceBar",
    "ReportKind",
    "ReportRun",
    "ReportRunStatus",
    "StockAnalysisStock",
    "TimestampMixin",
    "UUIDMixin",
    "User",
    "UserRole",
    "UserStatus",
    "Watchlist",
    "WatchlistItem",
    "pg_enum",
]
