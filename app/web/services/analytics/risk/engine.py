"""The risk engine: volatility, drawdown, beta, correlation, Sharpe and Sortino.

Everything is computed on a trailing window of one instrument's own observations,
resolved exactly like a return window (same segment, end not stale, start within the
gap threshold of its target), so nothing here ever averages across the 2025 hole.

* ``volatility_daily`` - sample standard deviation of simple daily returns over the
  volatility window; ``volatility_weekly`` / ``volatility_monthly`` - the same on
  last-close-of-week / of-month returns; ``volatility_annualised`` - daily x sqrt(252);
  ``volatility_rolling_3m`` - annualised daily volatility over the short window.
* ``drawdown_current`` - close / running peak - 1 at ``as_of``; ``max_drawdown_36m``
  - the deepest peak-to-trough fall in the drawdown window (peak and trough dates in
  ``window_start`` / ``window_end``); ``drawdown_recovery_days`` - days from that
  trough back to the peak level, ``unavailable`` while not recovered.
* ``beta_12m`` / ``beta_36m`` and ``correlation_market_12m`` - on daily returns
  inner-joined on date with the benchmark's, needing ``min_observations`` pairs;
  ``correlation_sector_12m`` - against the equal-weighted daily return of the
  sector peers.
* ``sharpe_12m`` / ``sortino_12m`` - annualised excess return over the configured
  risk-free rate divided by annualised total / downside deviation.

Returns are unadjusted; a window that contains a flagged observation is marked so
a split does not masquerade as a 90 % drawdown without anyone knowing.

    codegraph explore "risk_metrics volatility drawdown beta correlation_matrix"
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from app.web.services.analytics.config import AnalyticsConfig
from app.web.services.analytics.measure import Measure, Provenance
from app.web.services.analytics.momentum.engine import MetricResult
from app.web.services.analytics.returns.engine import WindowResult, window_return
from app.web.services.analytics.series import PriceSeries


@dataclass(frozen=True, slots=True)
class Window:
    """The part of a series a window resolved to, plus what the resolution said."""

    part: PriceSeries
    start: date
    end: date
    contains_flagged: bool


def resolve_window(series: PriceSeries, as_of: date, window: str, name: str) -> Window | Measure:
    """The in-segment slice for ``window`` ending at ``as_of``, or the blocking measure."""
    result: WindowResult = window_return(series, as_of, window)
    if not result.measure.is_known or result.start is None or result.end is None:
        return Measure(None, result.measure.status, f"{name}: {result.measure.reason}")
    return Window(
        series.between(result.start, result.end), result.start, result.end, result.contains_flagged
    )


def _returns(part: PriceSeries) -> pd.Series:
    return part.close.pct_change().dropna()


def _enough(returns: pd.Series, minimum: int, name: str) -> Measure | None:
    if len(returns) < minimum:
        return Measure.unavailable(f"{name}: {len(returns)} return observations, minimum {minimum}")
    return None


def _stat(value: float, window: Window, note: str) -> MetricResult:
    provenance = Provenance(
        table="stock_observations",
        ticker=window.part.ticker_symbol,
        start=window.start,
        end=window.end,
        note=note,
    )
    measure = Measure.known(value, provenance) if value != 0 else Measure.zero(provenance)
    return MetricResult(measure, window.start, window.end, window.contains_flagged)


def _blocked(measure: Measure) -> MetricResult:
    return MetricResult(measure)


# --- volatility ----------------------------------------------------------------------


def volatility(
    series: PriceSeries, as_of: date, config: AnalyticsConfig
) -> dict[str, MetricResult]:
    r = config.risk
    out: dict[str, MetricResult] = {}
    window = resolve_window(series, as_of, r.volatility_window, "volatility")
    if isinstance(window, Measure):
        for metric in (
            "volatility_daily",
            "volatility_weekly",
            "volatility_monthly",
            "volatility_annualised",
        ):
            out[metric] = _blocked(window)
    else:
        daily = _returns(window.part)
        short = _enough(daily, r.min_observations, "volatility")
        if short is not None:
            for metric in (
                "volatility_daily",
                "volatility_weekly",
                "volatility_monthly",
                "volatility_annualised",
            ):
                out[metric] = _blocked(short)
        else:
            daily_vol = float(daily.std(ddof=1))
            n = len(daily)
            out["volatility_daily"] = _stat(daily_vol, window, f"sample std of {n} daily returns")
            out["volatility_annualised"] = _stat(
                daily_vol * math.sqrt(config.market.trading_days_per_year),
                window,
                f"daily volatility x sqrt({config.market.trading_days_per_year}) over {n} returns",
            )
            closes = window.part.close
            stamps = window.part.dates
            iso = stamps.isocalendar()
            weekly = (
                closes.groupby([iso.year.to_numpy(), iso.week.to_numpy()])
                .last()
                .pct_change()
                .dropna()
            )
            monthly = (
                closes.groupby([stamps.year.to_numpy(), stamps.month.to_numpy()])
                .last()
                .pct_change()
                .dropna()
            )
            out["volatility_weekly"] = (
                _stat(
                    float(weekly.std(ddof=1)), window, f"sample std of {len(weekly)} weekly returns"
                )
                if len(weekly) >= 8
                else _blocked(
                    Measure.unavailable(
                        f"volatility weekly: {len(weekly)} weekly returns, minimum 8"
                    )
                )
            )
            out["volatility_monthly"] = (
                _stat(
                    float(monthly.std(ddof=1)),
                    window,
                    f"sample std of {len(monthly)} monthly returns",
                )
                if len(monthly) >= 6
                else _blocked(
                    Measure.unavailable(
                        f"volatility monthly: {len(monthly)} monthly returns, minimum 6"
                    )
                )
            )
    rolling = resolve_window(series, as_of, r.rolling_window, "rolling volatility")
    if isinstance(rolling, Measure):
        out["volatility_rolling_3m"] = _blocked(rolling)
    else:
        daily = _returns(rolling.part)
        short = _enough(daily, r.min_rolling_observations, "rolling volatility")
        out["volatility_rolling_3m"] = (
            _blocked(short)
            if short is not None
            else _stat(
                float(daily.std(ddof=1)) * math.sqrt(config.market.trading_days_per_year),
                rolling,
                f"annualised std of {len(daily)} daily returns",
            )
        )
    return out


# --- drawdown ---------------------------------------------------------------------------


def drawdown(series: PriceSeries, as_of: date, config: AnalyticsConfig) -> dict[str, MetricResult]:
    name = "drawdown"
    window = resolve_window(series, as_of, config.risk.drawdown_window, name)
    if isinstance(window, Measure):
        # Shorter history still has a drawdown: fall back to the whole current segment.
        end = series.position_on_or_before(as_of)
        if end is None or (as_of - series.dates[end].date()).days > series.gap_threshold_days:
            blocked = _blocked(window)
            return {
                "drawdown_current": blocked,
                "max_drawdown_36m": blocked,
                "drawdown_recovery_days": blocked,
            }
        segment = int(series.segment.iloc[end])
        mask = (series.segment == segment).to_numpy() & (np.arange(len(series)) <= end)
        part = series.between(series.dates[int(np.argmax(mask))].date(), series.dates[end].date())
        window = Window(
            part, part.first_date or as_of, part.last_date or as_of, bool(part.flagged.any())
        )
    closes = window.part.close
    if len(closes) < 2:
        blocked = _blocked(Measure.unavailable(f"{name}: fewer than two observations"))
        return {
            "drawdown_current": blocked,
            "max_drawdown_36m": blocked,
            "drawdown_recovery_days": blocked,
        }
    running_peak = closes.cummax()
    dd = closes / running_peak - 1.0
    current = float(dd.iloc[-1])
    trough_position = int(np.argmin(dd.to_numpy()))
    max_dd = float(dd.iloc[trough_position])
    peak_position = int(np.argmax(closes.to_numpy()[: trough_position + 1]))
    peak_day = window.part.dates[peak_position].date()
    trough_day = window.part.dates[trough_position].date()
    note = (
        f"peak {closes.iloc[peak_position]} on {peak_day}, "
        f"trough {closes.iloc[trough_position]} on {trough_day}"
    )
    out = {
        "drawdown_current": _stat(
            current, window, f"close vs running peak {running_peak.iloc[-1]}"
        ),
        "max_drawdown_36m": MetricResult(
            Measure.known(
                max_dd,
                Provenance(
                    table="stock_observations",
                    ticker=series.ticker_symbol,
                    start=peak_day,
                    end=trough_day,
                    note=note,
                ),
            )
            if max_dd != 0
            else Measure.zero(
                Provenance(
                    table="stock_observations",
                    ticker=series.ticker_symbol,
                    start=window.start,
                    end=window.end,
                    note="never below its running peak",
                )
            ),
            peak_day,
            trough_day,
            window.contains_flagged,
        ),
    }
    if max_dd == 0:
        out["drawdown_recovery_days"] = _blocked(
            Measure.not_applicable("recovery: no drawdown in the window")
        )
        return out
    peak_level = float(closes.iloc[peak_position])
    after = closes.iloc[trough_position + 1 :]
    recovered = after[after >= peak_level]
    if recovered.empty:
        out["drawdown_recovery_days"] = _blocked(
            Measure.unavailable(
                f"recovery: not yet back to the {peak_day} peak of {peak_level} by {window.end}"
            )
        )
    else:
        recovery_day = recovered.index[0].date()
        days = (recovery_day - trough_day).days
        out["drawdown_recovery_days"] = MetricResult(
            Measure.known(
                float(days),
                Provenance(
                    table="stock_observations",
                    ticker=series.ticker_symbol,
                    start=trough_day,
                    end=recovery_day,
                    note=f"back above {peak_level} on {recovery_day}",
                ),
            ),
            trough_day,
            recovery_day,
            window.contains_flagged,
        )
    return out


# --- beta and correlation ---------------------------------------------------------


def aligned_returns(
    a: PriceSeries, b: PriceSeries, start: date, end: date
) -> tuple[pd.Series, pd.Series]:
    """Daily returns of both series on their common dates inside [start, end]."""
    ra = _returns(a.between(start, end))
    rb = _returns(b.between(start, end))
    common = ra.index.intersection(rb.index)
    return ra.loc[common], rb.loc[common]


def beta_and_correlation(
    series: PriceSeries,
    reference: PriceSeries | None,
    as_of: date,
    window: str,
    config: AnalyticsConfig,
    *,
    reference_name: str,
) -> tuple[MetricResult, MetricResult]:
    name = f"beta {window}"
    resolved = resolve_window(series, as_of, window, name)
    if isinstance(resolved, Measure):
        return _blocked(resolved), _blocked(resolved)
    if reference is None or reference.is_empty:
        blocked = Measure.unavailable(f"{name}: {reference_name} has no observations")
        return _blocked(blocked), _blocked(blocked)
    ref_window = resolve_window(reference, as_of, window, f"{name} ({reference_name})")
    if isinstance(ref_window, Measure):
        return _blocked(ref_window), _blocked(ref_window)
    own, ref = aligned_returns(series, reference, resolved.start, resolved.end)
    short = _enough(own, config.risk.min_observations, name)
    if short is not None:
        return _blocked(short), _blocked(short)
    ref_var = float(ref.var(ddof=1))
    if ref_var == 0.0:
        blocked = Measure.not_meaningful(f"{name}: {reference_name} did not move over the window")
        return _blocked(blocked), _blocked(blocked)
    cov = float(np.cov(own.to_numpy(), ref.to_numpy(), ddof=1)[0, 1])
    beta = cov / ref_var
    own_std = float(own.std(ddof=1))
    corr = cov / (own_std * math.sqrt(ref_var)) if own_std > 0 else 0.0
    note = f"{len(own)} common daily returns with {reference_name}"
    return _stat(beta, resolved, f"beta: {note}"), _stat(corr, resolved, f"correlation: {note}")


def sector_return_series(
    peers: Mapping[str, PriceSeries], start: date, end: date, *, min_peers: int
) -> pd.Series | Measure:
    """Equal-weighted daily return of the peers on dates where at least ``min_peers`` traded."""
    frames = [_returns(p.between(start, end)).rename(t) for t, p in peers.items()]
    frames = [f for f in frames if not f.empty]
    if len(frames) < min_peers:
        return Measure.unavailable(
            f"only {len(frames)} peer(s) with returns in the window (minimum {min_peers})"
        )
    table = pd.concat(frames, axis=1)
    enough = table.count(axis=1) >= min_peers
    return table[enough].mean(axis=1)


def correlation_with_sector(
    series: PriceSeries, peers: Mapping[str, PriceSeries], as_of: date, config: AnalyticsConfig
) -> MetricResult:
    name = "correlation with sector 12M"
    resolved = resolve_window(series, as_of, config.risk.correlation_window, name)
    if isinstance(resolved, Measure):
        return _blocked(resolved)
    reference = sector_return_series(
        peers, resolved.start, resolved.end, min_peers=config.risk.min_peers
    )
    if isinstance(reference, Measure):
        return _blocked(Measure(None, reference.status, f"{name}: {reference.reason}"))
    own = _returns(series.between(resolved.start, resolved.end))
    common = own.index.intersection(reference.index)
    own, ref = own.loc[common], reference.loc[common]
    short = _enough(own, config.risk.min_observations, name)
    if short is not None:
        return _blocked(short)
    if float(own.std(ddof=1)) == 0.0 or float(ref.std(ddof=1)) == 0.0:
        return _blocked(Measure.not_meaningful(f"{name}: a constant return series"))
    corr = float(np.corrcoef(own.to_numpy(), ref.to_numpy())[0, 1])
    return _stat(corr, resolved, f"{len(own)} common daily returns with {len(peers)} sector peers")


def correlation_matrix(
    universe: Mapping[str, PriceSeries], as_of: date, window: str, config: AnalyticsConfig
) -> list[tuple[str, str, float, int]]:
    """Pairwise daily-return correlations over ``window`` for every instrument with a
    resolvable window; ``(a, b, value, n_obs)`` with ``a < b``."""
    returns: dict[str, pd.Series] = {}
    for ticker, series in universe.items():
        resolved = resolve_window(series, as_of, window, "correlation")
        if isinstance(resolved, Measure):
            continue
        r = _returns(resolved.part)
        if len(r) >= config.risk.min_observations and float(r.std(ddof=1)) > 0:
            returns[ticker] = r
    if len(returns) < 2:
        return []
    table = pd.concat([s.rename(t) for t, s in returns.items()], axis=1)
    counts = table.notna().astype(int)
    pair_counts = counts.T @ counts
    corr = table.corr(min_periods=config.risk.min_observations)
    names = [str(c) for c in table.columns]
    values = corr.to_numpy(dtype=float)
    counts_matrix = pair_counts.to_numpy(dtype=int)
    out: list[tuple[str, str, float, int]] = []
    for i, a in enumerate(names):
        for j in range(i + 1, len(names)):
            value = float(values[i, j])
            if not math.isnan(value):
                out.append((a, names[j], value, int(counts_matrix[i, j])))
    return out


# --- risk-adjusted returns ------------------------------------------------------------


def sharpe_and_sortino(
    series: PriceSeries, as_of: date, config: AnalyticsConfig
) -> dict[str, MetricResult]:
    name = "sharpe 12M"
    resolved = resolve_window(series, as_of, config.risk.volatility_window, name)
    if isinstance(resolved, Measure):
        return {"sharpe_12m": _blocked(resolved), "sortino_12m": _blocked(resolved)}
    daily = _returns(resolved.part)
    short = _enough(daily, config.risk.min_observations, name)
    if short is not None:
        return {"sharpe_12m": _blocked(short), "sortino_12m": _blocked(short)}
    periods = config.market.trading_days_per_year
    rf_daily = config.market.risk_free_rate / periods
    excess = daily - rf_daily
    mean_excess = float(excess.mean()) * periods
    total_dev = float(daily.std(ddof=1)) * math.sqrt(periods)
    downside = excess[excess < 0]
    downside_dev = (
        float(np.sqrt(np.mean(np.square(downside.to_numpy())))) * math.sqrt(periods)
        if len(downside)
        else 0.0
    )
    rf_note = f"risk-free {config.market.risk_free_rate:.2%} p.a. over {len(daily)} daily returns"
    out: dict[str, MetricResult] = {}
    out["sharpe_12m"] = (
        _stat(mean_excess / total_dev, resolved, f"sharpe: {rf_note}")
        if total_dev > 0
        else _blocked(Measure.not_meaningful(f"{name}: zero volatility"))
    )
    out["sortino_12m"] = (
        _stat(mean_excess / downside_dev, resolved, f"sortino: {rf_note}")
        if downside_dev > 0
        else _blocked(
            Measure.not_meaningful("sortino 12M: no negative excess returns in the window")
        )
    )
    return out


# --- everything -----------------------------------------------------------------------


def risk_metrics(
    series: PriceSeries,
    as_of: date,
    *,
    benchmark: PriceSeries | None,
    peers: Mapping[str, PriceSeries],
    config: AnalyticsConfig,
) -> dict[str, MetricResult]:
    out: dict[str, MetricResult] = {}
    out.update(volatility(series, as_of, config))
    out.update(drawdown(series, as_of, config))
    benchmark_name = config.market.benchmark_index
    for window in config.risk.beta_windows:
        beta, corr = beta_and_correlation(
            series, benchmark, as_of, window, config, reference_name=benchmark_name
        )
        out[f"beta_{window.lower()}"] = beta
        if window == config.risk.correlation_window:
            out["correlation_market_12m"] = corr
    out["correlation_sector_12m"] = correlation_with_sector(series, peers, as_of, config)
    out.update(sharpe_and_sortino(series, as_of, config))
    return out


__all__ = [
    "Window",
    "aligned_returns",
    "beta_and_correlation",
    "correlation_matrix",
    "correlation_with_sector",
    "drawdown",
    "resolve_window",
    "risk_metrics",
    "sector_return_series",
    "sharpe_and_sortino",
    "volatility",
]
