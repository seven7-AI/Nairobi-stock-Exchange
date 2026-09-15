"""Analytics-store models.

Importing this package attaches every table to ``AnalyticsBase.metadata``; the
analytics Alembic env imports it for exactly that reason. Add new tables here
as they arrive (metrics, factor scores, valuations, forecasts, backtests).

    codegraph explore "AnalyticsBase JobRun CalcVersion ModelRegistryEntry"
"""

from __future__ import annotations

from app.web.db.analytics.base import AnalyticsBase
from app.web.db.analytics.models.calc_version import CalcVersion
from app.web.db.analytics.models.classification import Classification
from app.web.db.analytics.models.correlation import Correlation
from app.web.db.analytics.models.data_quality_finding import DataQualityFinding, Severity
from app.web.db.analytics.models.factor_score import FactorScore
from app.web.db.analytics.models.forecast import Forecast, ForecastEvaluation
from app.web.db.analytics.models.fundamental_metric import FundamentalMetric
from app.web.db.analytics.models.job_run import JobRun, JobStatus
from app.web.db.analytics.models.market_metric import MarketMetric
from app.web.db.analytics.models.model_registry import ModelKind, ModelRegistryEntry, ModelStatus
from app.web.db.analytics.models.simulation import Regime, Simulation
from app.web.db.analytics.models.stock_ranking import StockRanking
from app.web.db.analytics.models.valuation import Valuation

__all__ = [
    "AnalyticsBase",
    "CalcVersion",
    "Classification",
    "Correlation",
    "DataQualityFinding",
    "FactorScore",
    "Forecast",
    "ForecastEvaluation",
    "FundamentalMetric",
    "JobRun",
    "JobStatus",
    "MarketMetric",
    "ModelKind",
    "ModelRegistryEntry",
    "ModelStatus",
    "Regime",
    "Severity",
    "Simulation",
    "StockRanking",
    "Valuation",
]
