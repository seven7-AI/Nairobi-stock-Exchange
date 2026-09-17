"""The overview page: how much the engine knows right now, in counts and dates.

codegraph explore "build_overview Overview status_counts_on_latest"
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import (
    FactorScore,
    Forecast,
    FundamentalMetric,
    MarketMetric,
    Simulation,
    StockRanking,
    Valuation,
)
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.data_quality import open_findings
from app.web.db.analytics.services.summaries import latest_known_as_of, status_counts_on_latest
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.dashboard.common import equity_universe, severity_counts
from app.web.services.dashboard.market import latest_quotes
from app.web.services.dashboard.status import DashboardStatus, build_status
from app.web.services.market_data.sources.nse_scraper import NseScraperSource

#: Result tables summarised on the overview, with the label the page shows.
RESULT_TABLES: tuple[tuple[str, Any], ...] = (
    ("market_metrics", MarketMetric),
    ("fundamental_metrics", FundamentalMetric),
    ("factor_scores", FactorScore),
    ("stock_rankings", StockRanking),
    ("valuations", Valuation),
    ("forecasts", Forecast),
    ("simulations", Simulation),
)


@dataclass(frozen=True)
class TableCoverage:
    as_of: date | None
    counts: dict[str, int]
    latest_known_as_of: date | None


@dataclass(frozen=True)
class Overview:
    version: dict[str, Any]
    tracked_stocks: int
    scraped_stocks: int
    classified_universe: int
    latest_market_date: date | None
    stocks_with_data_on_latest: int
    source: dict[str, Any]
    pipelines: list[dict[str, Any]]
    analytics: dict[str, TableCoverage]
    forecasts: TableCoverage
    open_findings: dict[str, int]
    store_revision: str | None
    store_migrated: bool
    last_update: dict[str, str | None]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_overview(
    settings: Settings, source: NseScraperSource, status: DashboardStatus | None = None
) -> Overview:
    status = status or build_status(settings, source)
    quotes = latest_quotes(settings, source)
    latest_day, with_data = source.latest_trade_date_coverage()
    analytics: dict[str, TableCoverage] = {}
    findings: dict[str, int] = {"error": 0, "warning": 0, "info": 0}
    universe = 0
    if settings.analytics_db_path.exists():
        with analytics_session(settings) as session:
            index = ClassificationIndex(load_classifications(session))
            universe = len(equity_universe(index, latest_day or date.today()))
            for name, model in RESULT_TABLES:
                day, counts = status_counts_on_latest(session, model)
                analytics[name] = TableCoverage(day, counts, latest_known_as_of(session, model))
            findings = severity_counts(open_findings(session))
    forecasts = analytics.pop("forecasts", TableCoverage(None, {}, None))
    return Overview(
        status.version.as_dict(),
        len(quotes),
        sum(1 for q in quotes.values() if q.source == "stockanalysis_stocks"),
        universe,
        latest_day,
        with_data,
        status.source,
        [asdict(p) for p in status.pipelines],
        analytics,
        forecasts,
        findings,
        status.store.get("revision"),
        bool(status.store.get("migrated")),
        dict(status.store.get("last_update") or {}),
    )


__all__ = ["RESULT_TABLES", "Overview", "TableCoverage", "build_overview"]
