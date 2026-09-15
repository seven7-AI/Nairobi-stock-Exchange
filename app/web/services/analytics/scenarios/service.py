"""Apply the configured scenarios to every stock for a date and store the outcomes.

Inputs are the last close on or before the date, the stored ``beta_12m`` and the
stored ``pe`` (EPS = price / P/E when the multiple is known).

    codegraph explore "compute_scenarios scenario_outcomes upsert_scenarios"
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import JobRun, JobStatus
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.factor_scores import metric_table_for
from app.web.db.analytics.services.simulations import upsert_scenarios
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig, register_calc_version
from app.web.services.analytics.forecasting.service import forecast_universe
from app.web.services.analytics.measure import Measure
from app.web.services.analytics.returns.service import ComputeResult, load_universe
from app.web.services.analytics.scenarios.engine import ScenarioOutcome, scenario_outcomes
from app.web.services.analytics.valuation_metrics.engine import price_on
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.utils.logger import get_logger

logger = get_logger(__name__)

JOB_NAME = "scenarios"


def compute_scenarios(
    settings: Settings,
    source: NseScraperSource,
    *,
    as_of: date | None = None,
    tickers: list[str] | None = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> ComputeResult:
    day = as_of or datetime.now(UTC).date()
    started = datetime.now(UTC)
    with analytics_session(settings) as session:
        version = register_calc_version(session, config)
        run = JobRun(job_name=JOB_NAME, started_at=started, as_of_date=day)
        session.add(run)
        session.flush()
        try:
            index = ClassificationIndex(load_classifications(session))
            universe = load_universe(source, config)
            wanted = forecast_universe(index, list(universe), day)
            if tickers:
                requested = {t.strip().upper() for t in tickers}
                wanted = [t for t in wanted if t in requested]
            table = metric_table_for(session, day)
            betas = table.get(("market", "beta_12m"), {})
            pes = table.get(("fundamental", "pe"), {})
            results: list[ScenarioOutcome] = []
            skipped: dict[str, str] = {}
            for ticker in wanted:
                located = price_on(universe[ticker].as_of(day), day)
                if isinstance(located, Measure):
                    skipped[ticker] = located.reason or "no price"
                    continue
                pe = pes.get(ticker)
                eps = located.close / pe if pe is not None and pe > 0 else None
                outcomes = scenario_outcomes(
                    ticker,
                    price=located.close,
                    beta=betas.get(ticker),
                    eps=eps,
                    pe=pe,
                    config=config,
                )
                for o in outcomes:
                    o.assumptions["price"] = located.close
                    o.assumptions["price_date"] = located.day.isoformat()
                results.extend(outcomes)
            written = upsert_scenarios(
                session,
                results,
                as_of_date=day,
                horizon_days=config.scenarios.horizon_days,
                calc_version_id=version.id,
            )
        except Exception as exc:
            run.status = JobStatus.FAILED
            run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now(UTC)
            raise
        known: dict[str, int] = {}
        for o in results:
            if o.measure.is_known:
                known[o.scenario] = known.get(o.scenario, 0) + 1
        run.status = JobStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        run.rows_written = written
        run.watermark = day.isoformat()
        run.details = {
            "calc_version_id": version.id,
            "universe": len(wanted),
            "known_counts": known,
        }
        version_id = version.id
    processed = [t for t in wanted if t not in skipped]
    logger.info("scenarios_computed", as_of=day.isoformat(), universe=len(wanted), rows=written)
    return ComputeResult(JOB_NAME, day, version_id, written, tuple(processed), skipped, known)


__all__ = ["JOB_NAME", "compute_scenarios"]
