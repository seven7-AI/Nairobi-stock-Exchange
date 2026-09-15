"""Detect and store the market regime for one date or a monthly series of dates.

codegraph explore "compute_regime detect_regime upsert_regimes"
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import JobRun, JobStatus
from app.web.db.analytics.services.simulations import upsert_regimes
from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig, register_calc_version
from app.web.services.analytics.forecasting.engine import shift_forward
from app.web.services.analytics.regime.engine import Regime, detect_regime
from app.web.services.analytics.returns.service import load_universe
from app.web.services.analytics.series import PriceSeries
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.utils.logger import get_logger

logger = get_logger(__name__)

JOB_NAME = "regime"


@dataclass(frozen=True)
class RegimeRunResult:
    index: str
    calc_version_id: int
    rows_written: int
    regimes: tuple[Regime, ...]

    @property
    def labels(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.regimes:
            key = r.measure.reason if r.measure.is_known else "unavailable"
            out[key or "unavailable"] = out.get(key or "unavailable", 0) + 1
        return out


def _with_fallback(primary: Regime, fallback: PriceSeries, config: AnalyticsConfig) -> Regime:
    """The primary's regime, or the fallback index's when the primary has none and the
    fallback does (the row names the index it came from)."""
    if primary.measure.is_known:
        return primary
    second = detect_regime(fallback, primary.as_of, config, index=config.regime.fallback_index)
    return second if second.measure.is_known else primary


def compute_regime(
    settings: Settings,
    source: NseScraperSource,
    *,
    as_of: date | None = None,
    start: date | None = None,
    end: date | None = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> RegimeRunResult:
    """One date (``as_of``) or every month-end-anchored date from ``start`` to ``end``."""
    last = end or as_of or datetime.now(UTC).date()
    dates: list[date] = []
    if start is not None:
        step = 0
        while (day := shift_forward(start, step)) <= last:
            dates.append(day)
            step += 1
    else:
        dates.append(last)
    started = datetime.now(UTC)
    with analytics_session(settings) as session:
        version = register_calc_version(session, config)
        run = JobRun(job_name=JOB_NAME, started_at=started, as_of_date=last)
        session.add(run)
        session.flush()
        try:
            cfg = config.regime
            universe = load_universe(source, config, tickers=[cfg.index, cfg.fallback_index])
            series = universe.get(cfg.index)
            if series is None:
                raise ValueError(f"regime index {cfg.index} is not in the source")
            fallback = universe.get(cfg.fallback_index)
            regimes = [detect_regime(series, day, config) for day in dates]
            if fallback is not None:
                # dates the primary cannot cover for lack of history fall back to the
                # older index; the row says which index it came from
                regimes = [_with_fallback(r, fallback, config) for r in regimes]
            written = upsert_regimes(session, regimes, calc_version_id=version.id)
        except Exception as exc:
            run.status = JobStatus.FAILED
            run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now(UTC)
            raise
        run.status = JobStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        run.rows_written = written
        run.watermark = last.isoformat()
        result = RegimeRunResult(config.regime.index, version.id, written, tuple(regimes))
        run.details = {"calc_version_id": version.id, "dates": len(dates), "labels": result.labels}
    logger.info("regime_computed", index=config.regime.index, dates=len(dates), rows=written)
    return result


__all__ = ["JOB_NAME", "RegimeRunResult", "compute_regime"]
