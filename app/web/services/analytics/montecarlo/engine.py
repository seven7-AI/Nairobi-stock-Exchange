"""Monte Carlo price paths from historical daily log returns.

Pure and seeded: the same inputs, config and seed give the same numbers. Paths
are built by resampling the stock's own in-segment daily log returns over the
lookback window - iid (``bootstrap``) or in blocks that keep volatility clustering
(``block_bootstrap``) - so nothing is assumed about the return distribution beyond
"the future resembles the sampled past". Every horizon reports the terminal-return
quantiles, the mean, P(return > x) for the configured thresholds and P(max drawdown
within the horizon > x) measured on the simulated paths themselves.

    codegraph explore "simulate_paths simulation_summary Simulation"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from app.web.services.analytics.config import AnalyticsConfig
from app.web.services.analytics.measure import Measure, Provenance
from app.web.services.analytics.risk.engine import Window, resolve_window
from app.web.services.analytics.series import PriceSeries


@dataclass(frozen=True, slots=True)
class Simulation:
    ticker_symbol: str
    horizon_days: int
    method: str
    measure: Measure  # mean terminal simple return, or the blocking status
    n_paths: int = 0
    seed: int | None = None
    price: float | None = None
    quantiles: dict[str, float] = field(default_factory=dict)
    p_positive: float | None = None
    p_return_above: dict[str, float] = field(default_factory=dict)
    p_drawdown_above: dict[str, float] = field(default_factory=dict)
    expected_max_drawdown: float | None = None
    inputs: dict[str, Any] = field(default_factory=dict)


def sample_returns(
    series: PriceSeries, as_of: date, config: AnalyticsConfig
) -> tuple[np.ndarray, Window] | Measure:
    """In-segment daily log returns over the lookback window ending at the origin."""
    cfg = config.montecarlo
    window = resolve_window(series, as_of, cfg.lookback_window, "monte carlo")
    if isinstance(window, Measure):
        return window
    closes = window.part.close.to_numpy(dtype=float)
    log_returns = np.diff(np.log(closes))
    if len(log_returns) < cfg.min_observations:
        return Measure.unavailable(
            f"monte carlo: {len(log_returns)} daily returns in the window, "
            f"minimum {cfg.min_observations}"
        )
    return log_returns, window


def simulate_paths(
    log_returns: np.ndarray,
    *,
    horizon_days: int,
    n_paths: int,
    seed: int,
    method: str,
    block_days: int,
) -> np.ndarray:
    """Cumulative log-return paths, shape (n_paths, horizon_days)."""
    rng = np.random.default_rng(seed)
    n = len(log_returns)
    if method == "bootstrap":
        draws = rng.integers(0, n, size=(n_paths, horizon_days))
        steps = log_returns[draws]
    elif method == "block_bootstrap":
        blocks_needed = int(np.ceil(horizon_days / block_days))
        starts = rng.integers(0, n, size=(n_paths, blocks_needed))
        offsets = np.arange(block_days)
        # circular blocks so every start is valid
        idx = (starts[:, :, None] + offsets[None, None, :]) % n
        steps = log_returns[idx].reshape(n_paths, blocks_needed * block_days)[:, :horizon_days]
    else:
        raise ValueError(f"unknown simulation method {method!r}")
    return np.cumsum(steps, axis=1)


def path_statistics(paths: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Terminal simple returns and max drawdown (as a positive fraction) per path."""
    terminal = np.expm1(paths[:, -1])
    with_start = np.concatenate([np.zeros((paths.shape[0], 1)), paths], axis=1)
    running_peak = np.maximum.accumulate(with_start, axis=1)
    drawdowns = 1.0 - np.exp(with_start - running_peak)
    return terminal, drawdowns.max(axis=1)


def simulation_summary(
    ticker: str,
    method: str,
    horizon_days: int,
    log_returns: np.ndarray,
    window: Window,
    price: float,
    config: AnalyticsConfig,
    *,
    seed: int | None = None,
    n_paths: int | None = None,
) -> Simulation:
    cfg = config.montecarlo
    used_seed = cfg.seed if seed is None else seed
    used_paths = cfg.n_paths if n_paths is None else n_paths
    paths = simulate_paths(
        log_returns,
        horizon_days=horizon_days,
        n_paths=used_paths,
        seed=used_seed + horizon_days,  # a different stream per horizon, still deterministic
        method=method,
        block_days=cfg.block_days,
    )
    terminal, max_dd = path_statistics(paths)
    quantiles = {
        f"q{int(p * 100):02d}": float(np.quantile(terminal, p))
        for p in (0.05, 0.25, 0.50, 0.75, 0.95)
    }
    mean = float(terminal.mean())
    provenance = Provenance(
        table="stock_observations",
        ticker=ticker,
        start=window.start,
        end=window.end,
        note=(
            f"{method}: {len(log_returns)} daily log returns resampled, {used_paths} paths, "
            f"seed {used_seed}"
        ),
    )
    return Simulation(
        ticker_symbol=ticker,
        horizon_days=horizon_days,
        method=method,
        measure=Measure.known(mean, provenance) if mean != 0 else Measure.zero(provenance),
        n_paths=used_paths,
        seed=used_seed,
        price=price,
        quantiles=quantiles,
        p_positive=float((terminal > 0).mean()),
        p_return_above={f"{t:+.2f}": float((terminal > t).mean()) for t in cfg.return_thresholds},
        p_drawdown_above={f"{t:.2f}": float((max_dd > t).mean()) for t in cfg.drawdown_thresholds},
        expected_max_drawdown=float(max_dd.mean()),
        inputs={
            "observations": len(log_returns),
            "window": cfg.lookback_window,
            "daily_mean_log": float(log_returns.mean()),
            "daily_sd_log": float(log_returns.std(ddof=1)),
            "block_days": cfg.block_days if method == "block_bootstrap" else None,
            "contains_flagged": window.contains_flagged,
        },
    )


def simulate_stock(
    series: PriceSeries, as_of: date, config: AnalyticsConfig, *, ticker: str
) -> list[Simulation]:
    """Every method at every horizon for one stock as of the origin."""
    cfg = config.montecarlo
    sampled = sample_returns(series, as_of, config)
    out: list[Simulation] = []
    if isinstance(sampled, Measure):
        for method in cfg.methods:
            for horizon in cfg.horizons_days:
                out.append(
                    Simulation(
                        ticker, horizon, method, Measure(None, sampled.status, sampled.reason)
                    )
                )
        return out
    log_returns, window = sampled
    price = float(window.part.close.iloc[-1])
    for method in cfg.methods:
        for horizon in cfg.horizons_days:
            out.append(
                simulation_summary(ticker, method, horizon, log_returns, window, price, config)
            )
    return out


__all__ = [
    "Simulation",
    "path_statistics",
    "sample_returns",
    "simulate_paths",
    "simulate_stock",
    "simulation_summary",
]
