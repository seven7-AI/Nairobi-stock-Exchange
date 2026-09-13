"""Analytics-store models.

Importing this package attaches every table to ``AnalyticsBase.metadata``; the
analytics Alembic env imports it for exactly that reason. Add new tables here
as they arrive (metrics, factor scores, valuations, forecasts, backtests).

    codegraph explore "AnalyticsBase JobRun CalcVersion ModelRegistryEntry"
"""

from __future__ import annotations

from app.web.db.analytics.base import AnalyticsBase
from app.web.db.analytics.models.calc_version import CalcVersion
from app.web.db.analytics.models.job_run import JobRun, JobStatus
from app.web.db.analytics.models.model_registry import ModelKind, ModelRegistryEntry, ModelStatus

__all__ = [
    "AnalyticsBase",
    "CalcVersion",
    "JobRun",
    "JobStatus",
    "ModelKind",
    "ModelRegistryEntry",
    "ModelStatus",
]
