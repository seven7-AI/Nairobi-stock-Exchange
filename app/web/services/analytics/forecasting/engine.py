"""Return-forecast baselines on monthly log returns, with a full distribution.

Pure. Given a stock's monthly log-return history as known on the origin date (and
the benchmark's, for the relative forecast) each model produces the mean and
standard deviation of the *cumulative log return* over the horizon; from those the
engine derives the expected simple return, the quantiles, P(positive), P(outperform
the benchmark), the expected horizon volatility and P(drawdown beyond a threshold)
- the probability that the path loses more than the threshold from the origin at
some point in the horizon (Brownian first-passage under the forecast's drift and
volatility). Distributions are normal in log space: a stated, testable assumption,
not a hidden one.

Models (all baselines; none claims skill until the evaluation says so):

* ``naive`` - zero drift, historical volatility (random walk);
* ``mean`` - the lookback mean monthly return and volatility, scaled by the horizon;
* ``ewma`` - exponentially weighted mean and volatility (half-life in months);
* ``ar1`` - AR(1) on monthly log returns by least squares (ARIMA(1,0,0)); the
  h-step-ahead sum has a closed-form mean and variance, used exactly.

    codegraph explore "forecast_returns ar1_fit horizon_distribution Forecast"
"""

from __future__ import annotations

import calendar
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import norm

from app.web.services.analytics.config import AnalyticsConfig
from app.web.services.analytics.measure import Measure, Provenance
from app.web.services.analytics.series import PriceSeries


@dataclass(frozen=True, slots=True)
class MonthlySeries:
    """Month-end closes of the segment that contains the origin, oldest first."""

    ticker_symbol: str
    origin: date
    closes: pd.Series  # index: month-end observation dates
    log_returns: pd.Series  # len = len(closes) - 1

    @property
    def months(self) -> int:
        return len(self.log_returns)


@dataclass(frozen=True, slots=True)
class Forecast:
    ticker_symbol: str
    horizon_months: int
    model: str
    measure: Measure  # expected simple return, or the blocking status
    mean_log: float | None = None
    sd_log: float | None = None
    quantiles: dict[str, float] = field(default_factory=dict)
    p_positive: float | None = None
    p_outperform: float | None = None
    expected_vol: float | None = None
    p_drawdown: float | None = None
    inputs: dict[str, Any] = field(default_factory=dict)


# --- data preparation ------------------------------------------------------------------


def monthly_series(
    series: PriceSeries, as_of: date, config: AnalyticsConfig
) -> MonthlySeries | Measure:
    """Month-end closes from the last observation on or before ``as_of`` back through
    its segment (never across a data gap); the final point is the as-of close."""
    part = series.as_of(as_of)
    if part.is_empty:
        return Measure.unavailable(f"forecast: no observations on or before {as_of}")
    last_position = len(part) - 1
    last_day = part.dates[last_position].date()
    if (as_of - last_day).days > config.market.gap_threshold_days:
        return Measure.unavailable(
            f"forecast: last observation {last_day} is {(as_of - last_day).days} days "
            f"before {as_of}"
        )
    segment_id = int(part.segment.iloc[last_position])
    in_segment = part.close[part.segment == segment_id]
    by_month: dict[tuple[int, int], tuple[pd.Timestamp, float]] = {}
    for ts, close in zip(in_segment.index, in_segment.to_numpy(), strict=True):
        stamp = pd.Timestamp(str(ts))
        by_month[(stamp.year, stamp.month)] = (stamp, float(close))
    ordered = [by_month[key] for key in sorted(by_month)]
    index = pd.DatetimeIndex([ts for ts, _ in ordered])
    values = np.array([close for _, close in ordered], dtype=float)
    # the origin month is represented by the as-of close, whatever its day
    values[-1] = float(part.close.iloc[last_position])
    closes = pd.Series(values, index=index)
    log_returns = pd.Series(np.diff(np.log(values)), index=index[1:])
    return MonthlySeries(series.ticker_symbol, as_of, closes, log_returns)


def _by_month(series: pd.Series) -> dict[tuple[int, int], float]:
    out: dict[tuple[int, int], float] = {}
    for ts, value in zip(series.index, series.to_numpy(), strict=True):
        stamp = pd.Timestamp(str(ts))
        out[(stamp.year, stamp.month)] = float(value)
    return out


# --- model estimates: (mean, sd) of the horizon log return -------------------------


def naive_estimate(
    r: pd.Series, horizon: int, config: AnalyticsConfig
) -> tuple[float, float, dict[str, Any]]:
    window = r.iloc[-config.forecast.lookback_months :]
    sd = float(window.std(ddof=1))
    return 0.0, sd * np.sqrt(horizon), {"drift": 0.0, "monthly_sd": sd, "months_used": len(window)}


def mean_estimate(
    r: pd.Series, horizon: int, config: AnalyticsConfig
) -> tuple[float, float, dict[str, Any]]:
    window = r.iloc[-config.forecast.lookback_months :]
    mu = float(window.mean())
    sd = float(window.std(ddof=1))
    return (
        mu * horizon,
        sd * np.sqrt(horizon),
        {"monthly_mean": mu, "monthly_sd": sd, "months_used": len(window)},
    )


def ewma_estimate(
    r: pd.Series, horizon: int, config: AnalyticsConfig
) -> tuple[float, float, dict[str, Any]]:
    halflife = config.forecast.ewma_halflife_months
    mu = float(r.ewm(halflife=halflife).mean().iloc[-1])
    var = float(r.ewm(halflife=halflife).var(bias=False).iloc[-1])
    sd = float(np.sqrt(max(var, 0.0)))
    return (
        mu * horizon,
        sd * np.sqrt(horizon),
        {"monthly_mean": mu, "monthly_sd": sd, "halflife_months": halflife},
    )


def ar1_fit(r: Sequence[float]) -> tuple[float, float, float]:
    """Least-squares AR(1): r_t = c + phi r_{t-1} + e. Returns (c, phi, innovation sd)."""
    y = np.asarray(r[1:], dtype=float)
    x = np.asarray(r[:-1], dtype=float)
    x_mean, y_mean = x.mean(), y.mean()
    var_x = float(((x - x_mean) ** 2).sum())
    phi = float(((x - x_mean) * (y - y_mean)).sum() / var_x) if var_x > 0 else 0.0
    c = float(y_mean - phi * x_mean)
    residuals = y - (c + phi * x)
    dof = max(len(y) - 2, 1)
    sigma = float(np.sqrt((residuals**2).sum() / dof))
    return c, phi, sigma


def ar1_horizon(
    c: float, phi: float, sigma: float, last: float, horizon: int
) -> tuple[float, float]:
    """Exact mean and sd of the sum of the next ``horizon`` AR(1) values given the last one."""
    mean = 0.0
    expected = last
    for _ in range(horizon):
        expected = c + phi * expected
        mean += expected
    # the innovation at step k affects steps k..h with weights 1, phi, phi^2, ...
    variance = 0.0
    for k in range(1, horizon + 1):
        weight = sum(phi**j for j in range(horizon - k + 1))
        variance += (weight * sigma) ** 2
    return mean, float(np.sqrt(variance))


def ar1_estimate(
    r: pd.Series, horizon: int, config: AnalyticsConfig
) -> tuple[float, float, dict[str, Any]]:
    window = r.iloc[-config.forecast.lookback_months :]
    c, phi, sigma = ar1_fit([float(v) for v in window.to_numpy()])
    cap = config.forecast.ar1_max_phi
    shrunk = float(np.clip(phi, -cap, cap))
    mean, sd = ar1_horizon(c, shrunk, sigma, float(window.iloc[-1]), horizon)
    return (
        mean,
        sd,
        {
            "c": c,
            "phi": phi,
            "phi_used": shrunk,
            "innovation_sd": sigma,
            "months_used": len(window),
        },
    )


ESTIMATORS = {
    "naive": naive_estimate,
    "mean": mean_estimate,
    "ewma": ewma_estimate,
    "ar1": ar1_estimate,
}


# --- from (mean, sd) to the forecast -----------------------------------------------


def p_first_passage(mean_log: float, sd_log: float, threshold: float) -> float:
    """P(the log price path falls to log(1 - threshold) at some point within the
    horizon) for Brownian motion with drift ``mean_log`` and sd ``sd_log`` over the
    horizon (reflection principle)."""
    if sd_log <= 0:
        return 1.0 if mean_log <= np.log1p(-threshold) else 0.0
    a = float(np.log1p(-threshold))  # negative barrier
    term1 = float(norm.cdf((a - mean_log) / sd_log))
    # the reflected term in log space: it can be exp(huge) x cdf(tiny)
    log_term2 = 2.0 * mean_log * a / sd_log**2 + float(norm.logcdf((a + mean_log) / sd_log))
    term2 = float(np.exp(min(log_term2, 0.0)))
    return float(min(1.0, max(0.0, term1 + term2)))


def horizon_distribution(
    ticker: str,
    model: str,
    horizon: int,
    mean_log: float,
    sd_log: float,
    *,
    benchmark: tuple[float, float, float] | None,
    inputs: Mapping[str, Any],
    config: AnalyticsConfig,
    provenance: Provenance,
) -> Forecast:
    """Quantiles, probabilities and the expected simple return from a normal log return."""
    cfg = config.forecast
    if not np.isfinite(sd_log) or sd_log <= 0:
        return Forecast(
            ticker,
            horizon,
            model,
            Measure.unavailable(f"{model}: no return dispersion to forecast with"),
            inputs=dict(inputs),
        )
    levels = {"q05": 0.05, "q25": 0.25, "q50": 0.50, "q75": 0.75, "q95": 0.95}
    quantiles = {k: float(np.expm1(mean_log + sd_log * norm.ppf(p))) for k, p in levels.items()}
    expected = float(np.expm1(mean_log + 0.5 * sd_log**2))
    p_positive = float(1.0 - norm.cdf(-mean_log / sd_log))
    p_outperform: float | None = None
    if benchmark is not None:
        b_mean, b_sd, correlation = benchmark
        rel_var = sd_log**2 + b_sd**2 - 2.0 * correlation * sd_log * b_sd
        if rel_var > 0:
            p_outperform = float(1.0 - norm.cdf(-(mean_log - b_mean) / np.sqrt(rel_var)))
        else:
            p_outperform = 1.0 if mean_log > b_mean else 0.0
    p_dd = p_first_passage(mean_log, sd_log, cfg.drawdown_threshold)
    measure = Measure.known(expected, provenance) if expected != 0 else Measure.zero(provenance)
    return Forecast(
        ticker,
        horizon,
        model,
        measure,
        mean_log,
        sd_log,
        quantiles,
        p_positive,
        p_outperform,
        sd_log,
        p_dd,
        dict(inputs),
    )


def forecast_returns(
    stock: MonthlySeries | Measure,
    benchmark: MonthlySeries | Measure | None,
    config: AnalyticsConfig,
    *,
    ticker: str,
) -> list[Forecast]:
    """Every configured model at every horizon for one stock as of its origin."""
    cfg = config.forecast
    out: list[Forecast] = []
    models = tuple(cfg.models) + tuple(cfg.candidate_models)
    if isinstance(stock, Measure):
        for model in models:
            for horizon in cfg.horizons:
                out.append(
                    Forecast(ticker, horizon, model, Measure(None, stock.status, stock.reason))
                )
        return out
    if stock.months < cfg.min_months:
        for model in models:
            for horizon in cfg.horizons:
                out.append(
                    Forecast(
                        ticker,
                        horizon,
                        model,
                        Measure.unavailable(
                            f"forecast: {stock.months} contiguous monthly returns, "
                            f"minimum {cfg.min_months}"
                        ),
                    )
                )
        return out
    provenance = Provenance(
        table="stock_observations",
        ticker=ticker,
        start=stock.closes.index[0].date(),
        end=stock.origin,
        note=f"{stock.months} monthly log returns",
    )
    aligned_benchmark: pd.Series | None = None
    correlation = 0.0
    if isinstance(benchmark, MonthlySeries):
        stock_by_month = _by_month(stock.log_returns)
        bench_by_month = _by_month(benchmark.log_returns)
        common = sorted(set(stock_by_month) & set(bench_by_month))
        if len(common) >= cfg.min_months:
            aligned_benchmark = benchmark.log_returns
            pair = np.array([[stock_by_month[k], bench_by_month[k]] for k in common])
            corr = float(np.corrcoef(pair[:, 0], pair[:, 1])[0, 1]) if len(common) > 2 else 0.0
            correlation = corr if np.isfinite(corr) else 0.0
    for model in models:
        estimator = ESTIMATORS.get(model)
        if estimator is None:
            for horizon in cfg.horizons:
                out.append(
                    Forecast(
                        ticker,
                        horizon,
                        model,
                        Measure.unavailable(f"{model}: no estimator registered"),
                    )
                )
            continue
        for horizon in cfg.horizons:
            mean_log, sd_log, inputs = estimator(stock.log_returns, horizon, config)
            bench: tuple[float, float, float] | None = None
            if aligned_benchmark is not None:
                b_mean, b_sd, _ = estimator(aligned_benchmark, horizon, config)
                bench = (b_mean, b_sd, correlation)
            out.append(
                horizon_distribution(
                    ticker,
                    model,
                    horizon,
                    mean_log,
                    sd_log,
                    benchmark=bench,
                    inputs={
                        **inputs,
                        "months": stock.months,
                        "benchmark_correlation": correlation if bench else None,
                    },
                    config=config,
                    provenance=provenance,
                )
            )
    return out


# --- evaluation ------------------------------------------------------------------------


def shift_forward(day: date, months: int) -> date:
    """``day`` plus calendar months; clamps to the target month's last day."""
    year, month = day.year, day.month + months
    while month > 12:
        month -= 12
        year += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def realised_return(
    series: PriceSeries, origin: date, horizon_months: int, config: AnalyticsConfig
) -> tuple[float, date] | Measure:
    """Simple return from the origin close to the close on or before origin + horizon,
    within the gap threshold of the target and without crossing a data gap."""
    start = series.position_on_or_before(origin)
    if start is None:
        return Measure.unavailable(f"realised: no observation on or before {origin}")
    target = shift_forward(origin, horizon_months)
    end = series.position_on_or_before(target)
    if end is None:
        return Measure.unavailable(f"realised: no observation on or before {target}")
    end_day = series.dates[end].date()
    if (target - end_day).days > config.market.gap_threshold_days:
        last = series.last_date
        if last is not None and last < target:
            return Measure.unavailable(
                f"realised: the horizon has not elapsed in the data (last observation {last}, "
                f"target {target})"
            )
        return Measure.unavailable(
            f"realised: last observation {end_day} is {(target - end_day).days} days "
            f"before {target}"
        )
    if end <= start:
        return Measure.unavailable(f"realised: no observation after {origin} by {target}")
    if not series.same_segment(start, end):
        return Measure.unavailable(f"realised: {origin} -> {end_day} crosses a data gap")
    return float(series.close.iloc[end] / series.close.iloc[start] - 1.0), end_day


@dataclass(frozen=True, slots=True)
class Evaluation:
    realised_return: float
    realised_benchmark_return: float | None
    error: float
    directional_hit: bool
    benchmark_hit: bool | None
    within_interval: bool
    end_date: date


def evaluate_forecast(
    f: Forecast, realised: float, benchmark: float | None, end_date: date
) -> Evaluation:
    expected = float(f.measure.value or 0.0)
    q05, q95 = f.quantiles.get("q05"), f.quantiles.get("q95")
    within = bool(q05 is not None and q95 is not None and q05 <= realised <= q95)
    directional = (realised > 0) == ((f.p_positive or 0.5) > 0.5)
    benchmark_hit: bool | None = None
    if benchmark is not None and f.p_outperform is not None:
        benchmark_hit = (realised > benchmark) == (f.p_outperform > 0.5)
    return Evaluation(
        realised, benchmark, realised - expected, bool(directional), benchmark_hit, within, end_date
    )


def summarise(evaluations: Sequence[Evaluation]) -> dict[str, float | int | None]:
    """MAE, RMSE, directional accuracy, benchmark hit rate, interval coverage, n."""
    if not evaluations:
        return {
            "n": 0,
            "mae": None,
            "rmse": None,
            "directional_accuracy": None,
            "benchmark_hit_rate": None,
            "interval_coverage": None,
        }
    errors = np.array([e.error for e in evaluations])
    with_benchmark = [e for e in evaluations if e.benchmark_hit is not None]
    return {
        "n": len(evaluations),
        "mae": float(np.abs(errors).mean()),
        "rmse": float(np.sqrt((errors**2).mean())),
        "directional_accuracy": float(np.mean([e.directional_hit for e in evaluations])),
        "benchmark_hit_rate": float(np.mean([e.benchmark_hit for e in with_benchmark]))
        if with_benchmark
        else None,
        "interval_coverage": float(np.mean([e.within_interval for e in evaluations])),
    }


def beats_baselines(
    candidate: Mapping[str, Any], baselines: Sequence[Mapping[str, Any]], *, margin: float
) -> bool:
    """A candidate is admitted only with a lower MAE than every baseline (by the margin)
    and a directional accuracy no worse than the best baseline."""
    if (
        candidate.get("mae") is None
        or not baselines
        or any(b.get("mae") is None for b in baselines)
    ):
        return False
    best_mae = min(float(b["mae"]) for b in baselines)
    best_hit = max(float(b.get("directional_accuracy") or 0.0) for b in baselines)
    return (
        float(candidate["mae"]) < best_mae * (1.0 - margin)
        and float(candidate.get("directional_accuracy") or 0.0) >= best_hit
    )


__all__ = [
    "ESTIMATORS",
    "Evaluation",
    "Forecast",
    "MonthlySeries",
    "ar1_estimate",
    "ar1_fit",
    "ar1_horizon",
    "beats_baselines",
    "evaluate_forecast",
    "ewma_estimate",
    "forecast_returns",
    "horizon_distribution",
    "mean_estimate",
    "monthly_series",
    "naive_estimate",
    "p_first_passage",
    "realised_return",
    "shift_forward",
    "summarise",
]
