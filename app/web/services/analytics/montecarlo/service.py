"""Run the Monte Carlo simulations for a date and store them.

codegraph explore "compute_montecarlo simulate_stock upsert_simulations"
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import JobRun, JobStatus
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.simulations import upsert_simulations
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig, register_calc_version
from app.web.services.analytics.forecasting.service import forecast_universe
from app.web.services.analytics.montecarlo.engine import Simulation, simulate_stock
from app.web.services.analytics.returns.service import ComputeResult, load_universe
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.utils.logger import get_logger

logger = get_logger(__name__)

JOB_NAME = "montecarlo"


def compute_montecarlo(
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
            results: list[Simulation] = []
            skipped: dict[str, str] = {}
            for ticker in wanted:
                series = universe[ticker]
                if series.is_empty:
                    skipped[ticker] = "no observations"
                    continue
                results.extend(simulate_stock(series, day, config, ticker=ticker))
            written = upsert_simulations(
                session, results, as_of_date=day, calc_version_id=version.id
            )
        except Exception as exc:
            run.status = JobStatus.FAILED
            run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now(UTC)
            raise
        known: dict[str, int] = {}
        for s in results:
            if s.measure.is_known:
                known[s.method] = known.get(s.method, 0) + 1
        run.status = JobStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        run.rows_written = written
        run.watermark = day.isoformat()
        run.details = {
            "calc_version_id": version.id,
            "universe": len(wanted),
            "known_counts": known,
            "n_paths": config.montecarlo.n_paths,
            "seed": config.montecarlo.seed,
        }
        version_id = version.id
    processed = [t for t in wanted if t not in skipped]
    logger.info("montecarlo_computed", as_of=day.isoformat(), universe=len(wanted), rows=written)
    return ComputeResult(JOB_NAME, day, version_id, written, tuple(processed), skipped, known)


__all__ = ["JOB_NAME", "compute_montecarlo"]
