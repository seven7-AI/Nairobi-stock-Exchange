"""Backtest jobs: run the ranking model, compare against benchmarks, search weights.

codegraph explore "run_model_backtest weight_search build_context"
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import JobRun, JobStatus
from app.web.db.analytics.services.backtests import save_backtest
from app.web.db.analytics.services.classifications import load_classifications
from app.web.services.analytics.backtesting.engine import (
    BacktestResult,
    run_backtest,
)
from app.web.services.analytics.backtesting.signals import (
    SignalContext,
    ranking_signal,
    turnover_lookup,
)
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.analytics.config import (
    DEFAULT_CONFIG,
    AnalyticsConfig,
    RankingConfig,
    register_calc_version,
)
from app.web.services.analytics.fundamentals.service import load_statements
from app.web.services.analytics.measure import Measure
from app.web.services.analytics.returns.service import load_universe
from app.web.services.analytics.series import PriceSeries
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.utils.logger import get_logger

logger = get_logger(__name__)

JOB_NAME = "backtest"
EQUAL_WEIGHT = "equal_weight"


@dataclass(frozen=True)
class BacktestRunResult:
    run_id: int
    name: str
    start: date
    end: date
    result: BacktestResult
    equal_weight: BacktestResult | None

    def headline(self) -> dict[str, Any]:
        """Portfolio vs benchmarks, per segment: the numbers a reader looks at first."""
        out: dict[str, Any] = {"segments": []}
        for number, segment in enumerate(self.result.segments, start=1):
            block: dict[str, Any] = {
                "segment": number,
                "start": segment.start.isoformat(),
                "end": segment.end.isoformat(),
            }
            for series, metrics in segment.metrics.items():
                block[series] = {
                    k: (round(m.value, 4) if m.value is not None else m.status.value)
                    for k, m in metrics.items()
                    if k
                    in (
                        "total_return",
                        "cagr",
                        "volatility",
                        "sharpe",
                        "max_drawdown",
                        "alpha_vs_^NASI",
                        "alpha_t_stat_vs_^NASI",
                        "beta_vs_^NASI",
                        "avg_monthly_turnover",
                    )
                }
            if self.equal_weight is not None and number <= len(self.equal_weight.segments):
                ew = self.equal_weight.segments[number - 1].metrics.get("portfolio", {})
                block[EQUAL_WEIGHT] = {
                    k: (round(m.value, 4) if m.value is not None else m.status.value)
                    for k, m in ew.items()
                    if k in ("total_return", "cagr", "volatility", "sharpe", "max_drawdown")
                }
            out["segments"].append(block)
        out["linked"] = {k: m.as_dict() for k, m in self.result.linked.items()}
        return out


def build_context(
    source: NseScraperSource, session_index: ClassificationIndex, config: AnalyticsConfig
) -> SignalContext:
    """Load prices, statements and snapshots once for a whole backtest."""
    universe = load_universe(source, config)
    tickers = list(universe)
    statements = load_statements(source, tickers, config)
    snapshots = (
        {t: source.fetch_fundamental_snapshots(t, view="overview") for t in tickers}
        if source.has_financial_statements()
        else {}
    )
    return SignalContext(universe, statements, snapshots, session_index, config)


def stock_prices(
    prices: Mapping[str, PriceSeries], index: ClassificationIndex
) -> dict[str, PriceSeries]:
    """Everything that is not an index (benchmarks are never candidates)."""
    out: dict[str, PriceSeries] = {}
    for ticker, series in prices.items():
        if ticker.startswith("^"):
            continue
        out[ticker] = series
    return out


def equal_weight_signal(day: date, listed: Sequence[str]) -> list[tuple[str, float]]:
    return [(t, 1.0) for t in sorted(listed)]


def _save(
    session: Any,
    result: BacktestResult,
    *,
    name: str,
    purpose: str,
    config: AnalyticsConfig,
    calc_version_id: int,
    top_n: int,
    details: dict[str, Any] | None,
    cost_rate: float | None,
) -> int:
    cfg = config.backtest
    costs = cfg.costs.model_dump()
    costs["rate"] = cfg.costs.rate if cost_rate is None else cost_rate
    run = save_backtest(
        session,
        result,
        name=name,
        model_name=config.ranking.model_name,
        model_version=config.ranking.model_version,
        purpose=purpose,
        config_hash=config.config_hash(),
        top_n=top_n,
        weights=dict(config.ranking.weights),
        costs=costs,
        benchmarks=list(cfg.benchmarks),
        details=details,
        calc_version_id=calc_version_id,
    )
    return int(run.id)


def run_model_backtest(
    settings: Settings,
    source: NseScraperSource,
    *,
    start: date,
    end: date,
    name: str = "factor-model",
    config: AnalyticsConfig = DEFAULT_CONFIG,
    top_n: int | None = None,
    with_equal_weight: bool = True,
    context: SignalContext | None = None,
    purpose: str = "run",
) -> BacktestRunResult:
    """Simulate the ranking model over [start, end], store it, and (optionally) the
    equal-weight universe under the same calendar and costs for comparison."""
    started = datetime.now(UTC)
    # Register the run in a short transaction, simulate with no lock held (a full
    # backtest takes minutes to hours), then store in a second short transaction.
    with analytics_session(settings) as session:
        version = register_calc_version(session, config)
        job = JobRun(job_name=JOB_NAME, started_at=started, as_of_date=end)
        session.add(job)
        session.flush()
        version_id, job_id = version.id, job.id
        index = ClassificationIndex(load_classifications(session))
    try:
        ctx = context or build_context(source, index, config)
        prices = stock_prices(ctx.prices, index)
        benchmarks = {b: ctx.prices[b] for b in config.backtest.benchmarks if b in ctx.prices}
        n = top_n or config.backtest.top_n
        result = run_backtest(
            prices,
            ranking_signal(ctx, config),
            start=start,
            end=end,
            config=config,
            benchmarks=benchmarks,
            turnover=turnover_lookup(ctx),
            top_n=n,
        )
        equal_weight: BacktestResult | None = None
        if with_equal_weight:
            equal_weight = run_backtest(
                prices,
                equal_weight_signal,
                start=start,
                end=end,
                config=config,
                benchmarks=benchmarks,
                turnover=None,
                top_n=len(prices),
                cost_rate=0.0,
            )
    except Exception as exc:
        with analytics_session(settings) as session:
            failed = session.get(JobRun, job_id)
            if failed is not None:
                failed.status = JobStatus.FAILED
                failed.error = f"{type(exc).__name__}: {exc}"
                failed.finished_at = datetime.now(UTC)
        raise
    with analytics_session(settings) as session:
        run_id = _save(
            session,
            result,
            name=name,
            purpose=purpose,
            config=config,
            calc_version_id=version_id,
            top_n=n,
            cost_rate=None,
            details={"rebalances": sum(len(s.rebalances) for s in result.segments)},
        )
        if equal_weight is not None:
            _save(
                session,
                equal_weight,
                name=f"{name}:{EQUAL_WEIGHT}",
                purpose="benchmark",
                config=config,
                calc_version_id=version_id,
                top_n=len(prices),
                cost_rate=0.0,
                details={"note": "equal-weight listed universe, monthly, no costs"},
            )
        stored = session.get(JobRun, job_id)
        if stored is not None:
            stored.status = JobStatus.SUCCEEDED
            stored.finished_at = datetime.now(UTC)
            stored.rows_written = sum(len(s.trades) + len(s.equity) for s in result.segments)
            stored.watermark = end.isoformat()
            stored.details = {
                "run_id": run_id,
                "segments": len(result.segments),
                "notes": result.notes,
            }
    logger.info("backtest_run", name=name, run_id=run_id, segments=len(result.segments))
    return BacktestRunResult(run_id, name, start, end, result, equal_weight)


@dataclass(frozen=True)
class WeightSearchResult:
    candidates: dict[str, dict[str, float]]
    in_sample: dict[str, dict[str, Measure]]
    out_of_sample: dict[str, dict[str, Measure]]
    best_in_sample: str | None
    run_ids: dict[str, tuple[int, int]]


def weight_search(
    settings: Settings,
    source: NseScraperSource,
    *,
    candidates: Mapping[str, Mapping[str, float]],
    start: date,
    split: date,
    end: date,
    config: AnalyticsConfig = DEFAULT_CONFIG,
    top_n: int | None = None,
) -> WeightSearchResult:
    """Run every candidate weight set in-sample [start, split) and out-of-sample
    [split, end]; the pick is made in-sample by Sharpe and reported out-of-sample.
    The metric table per date is shared across candidates (one context)."""
    if not (start < split < end):
        raise ValueError("expected start < split < end")
    with analytics_session(settings) as session:
        index = ClassificationIndex(load_classifications(session))
    ctx = build_context(source, index, config)
    ctx.memoise_all = True  # the candidates share one metric table per date
    in_sample: dict[str, dict[str, Measure]] = {}
    out_of_sample: dict[str, dict[str, Measure]] = {}
    run_ids: dict[str, tuple[int, int]] = {}
    for name, weights in candidates.items():
        variant = config.model_copy(
            update={
                "ranking": config.ranking.model_copy(
                    update={"weights": dict(weights), "model_version": f"search:{name}"}
                )
            }
        )
        first = run_model_backtest(
            settings,
            source,
            start=start,
            end=split,
            name=f"search:{name}",
            config=variant,
            top_n=top_n,
            with_equal_weight=False,
            context=ctx,
            purpose="weight_search:in_sample",
        )
        second = run_model_backtest(
            settings,
            source,
            start=split,
            end=end,
            name=f"search:{name}",
            config=variant,
            top_n=top_n,
            with_equal_weight=False,
            context=ctx,
            purpose="weight_search:out_of_sample",
        )
        in_sample[name] = _portfolio_summary(first.result)
        out_of_sample[name] = _portfolio_summary(second.result)
        run_ids[name] = (first.run_id, second.run_id)
    scored = {
        n: m["sharpe"].value
        for n, m in in_sample.items()
        if m.get("sharpe") and m["sharpe"].value is not None
    }
    best = max(scored, key=lambda n: scored[n]) if scored else None
    return WeightSearchResult(
        {k: dict(v) for k, v in candidates.items()}, in_sample, out_of_sample, best, run_ids
    )


def _portfolio_summary(result: BacktestResult) -> dict[str, Measure]:
    """Portfolio metrics of the first segment (a search period should not span a gap)
    plus the linked total."""
    if not result.segments:
        return {"total_return": Measure.unavailable("no segments")}
    out = dict(result.segments[0].metrics.get("portfolio", {}))
    out.update({f"linked_{k}": v for k, v in result.linked.items()})
    if len(result.segments) > 1:
        out["segments"] = Measure.known(float(len(result.segments)))
    return out


def market_only_ranking(config: AnalyticsConfig = DEFAULT_CONFIG) -> AnalyticsConfig:
    """A documented variant: the ranking on market factors only (momentum, risk,
    liquidity), for periods before any statements exist. Not the model - a control."""
    weights = {"momentum": 0.5, "risk": 0.3, "liquidity": 0.2}
    return config.model_copy(
        update={
            "ranking": RankingConfig(
                model_name="factor-model-market-only",
                model_version="1",
                weights=weights,
                min_weight_available=0.5,
            )
        }
    )


__all__ = [
    "EQUAL_WEIGHT",
    "JOB_NAME",
    "BacktestRunResult",
    "WeightSearchResult",
    "build_context",
    "equal_weight_signal",
    "market_only_ranking",
    "run_model_backtest",
    "stock_prices",
    "weight_search",
]
