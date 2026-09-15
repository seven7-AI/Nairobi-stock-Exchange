"""Portfolio risk for a hypothetical set of weights, from the stocks' own histories.

Pure. Takes the weights, each stock's in-segment daily returns over the window
(aligned on common dates), the benchmark's, the sector / industry membership and
the stored average daily turnover, and returns:

* historical expected return and volatility (annualised), Sharpe, max drawdown of
  the constant-weight equity curve, beta to the benchmark;
* the pairwise correlation matrix and the average pairwise correlation;
* concentration - HHI, effective number of positions (1 / HHI), top-N weight;
* sector and industry exposure;
* liquidity - days to liquidate each position at the ADV participation cap;
* warnings that say why (a single position, a sector, HHI, correlation, liquidity).

Any stock without enough aligned history makes the return / risk block
``unavailable`` naming it; exposures, concentration and liquidity are still reported
for what is known. Nothing here is a recommendation.

    codegraph explore "analyse_portfolio PortfolioAnalysis validate_weights"
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.web.services.analytics.config import AnalyticsConfig
from app.web.services.analytics.measure import Measure, Provenance


class WeightError(ValueError):
    """The weights are not a portfolio."""


@dataclass(frozen=True, slots=True)
class PortfolioInputs:
    weights: dict[str, float]
    #: ticker -> daily simple returns indexed by date (already in-segment, ending at as_of)
    returns: Mapping[str, pd.Series]
    benchmark: pd.Series | None
    sectors: Mapping[str, str | None]
    industries: Mapping[str, str | None]
    #: ticker -> average daily turnover in KES (stored liquidity metric), when known
    turnover: Mapping[str, float]
    #: why the benchmark series is absent, when it is
    benchmark_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PortfolioAnalysis:
    weights: dict[str, float]
    coverage: float
    expected_return: Measure
    volatility: Measure
    sharpe: Measure
    max_drawdown: Measure
    beta: Measure
    average_correlation: Measure
    correlation: dict[str, dict[str, float]] = field(default_factory=dict)
    hhi: float = 0.0
    effective_positions: float = 0.0
    top_n_weight: float = 0.0
    sector_exposure: dict[str, float] = field(default_factory=dict)
    industry_exposure: dict[str, float] = field(default_factory=dict)
    days_to_liquidate: dict[str, float | None] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)


def validate_weights(raw: Mapping[str, float], config: AnalyticsConfig) -> dict[str, float]:
    """Upper-cased tickers with positive weights summing to one (within tolerance)."""
    if not raw:
        raise WeightError("no weights given")
    weights: dict[str, float] = {}
    for ticker, weight in raw.items():
        symbol = ticker.strip().upper()
        if not symbol:
            raise WeightError("empty ticker symbol")
        if symbol in weights:
            raise WeightError(f"{symbol} appears twice")
        if not np.isfinite(weight) or weight <= 0:
            raise WeightError(f"{symbol}: weight must be a positive number, got {weight!r}")
        weights[symbol] = float(weight)
    total = sum(weights.values())
    if abs(total - 1.0) > config.portfolio.weight_tolerance:
        raise WeightError(
            f"weights sum to {total:.4f}, expected 1 "
            f"(tolerance {config.portfolio.weight_tolerance})"
        )
    return weights


def parse_weights(text: str) -> dict[str, float]:
    """``"KCB=0.2,EQTY=0.3"`` -> {"KCB": 0.2, "EQTY": 0.3}."""
    out: dict[str, float] = {}
    for item in text.split(","):
        if not item.strip():
            continue
        if "=" not in item:
            raise WeightError(f"expected TICKER=WEIGHT, got {item.strip()!r}")
        ticker, value = item.split("=", 1)
        try:
            out[ticker.strip().upper()] = float(value)
        except ValueError as exc:
            raise WeightError(
                f"{ticker.strip()}: weight {value.strip()!r} is not a number"
            ) from exc
    return out


def exposures(
    weights: Mapping[str, float], membership: Mapping[str, str | None]
) -> dict[str, float]:
    out: dict[str, float] = {}
    for ticker, weight in weights.items():
        key = membership.get(ticker) or "unclassified"
        out[key] = out.get(key, 0.0) + weight
    return dict(sorted(out.items(), key=lambda item: -item[1]))


def concentration(weights: Mapping[str, float], top_n: int) -> tuple[float, float, float]:
    values = sorted(weights.values(), reverse=True)
    hhi = float(sum(w * w for w in values))
    return hhi, (1.0 / hhi if hhi > 0 else 0.0), float(sum(values[:top_n]))


def _max_drawdown(daily: np.ndarray) -> float:
    equity = np.cumprod(1.0 + daily)
    peak = np.maximum.accumulate(equity)
    return float((equity / peak - 1.0).min())


def analyse_portfolio(inputs: PortfolioInputs, config: AnalyticsConfig) -> PortfolioAnalysis:
    cfg = config.portfolio
    weights = inputs.weights
    tickers = list(weights)
    covered = [
        t for t in tickers if t in inputs.returns and len(inputs.returns[t]) >= cfg.min_observations
    ]
    missing = [t for t in tickers if t not in covered]
    coverage = float(sum(weights[t] for t in covered))
    hhi, effective, top_n = concentration(weights, cfg.top_n)
    sector_exposure = exposures(weights, inputs.sectors)
    industry_exposure = exposures(weights, inputs.industries)
    warnings: list[str] = []
    for ticker, weight in sorted(weights.items(), key=lambda item: -item[1]):
        if weight > cfg.single_position_warning:
            warnings.append(
                f"{ticker} is {weight:.0%} of the portfolio "
                f"(limit {cfg.single_position_warning:.0%})"
            )
    for sector, weight in sector_exposure.items():
        if weight > cfg.sector_warning:
            members = [t for t in tickers if (inputs.sectors.get(t) or "unclassified") == sector]
            warnings.append(
                f"{sector} is {weight:.0%} of the portfolio across {len(members)} position(s) "
                f"(limit {cfg.sector_warning:.0%}) - they are one bet on the sector, not "
                f"{len(members)} independent ones"
            )
    if hhi > cfg.hhi_warning:
        warnings.append(
            f"HHI {hhi:.2f} (effective positions {effective:.1f}) above {cfg.hhi_warning:.2f}"
        )

    # liquidity: days to sell each position at the participation cap
    days: dict[str, float | None] = {}
    for ticker, weight in weights.items():
        turnover = inputs.turnover.get(ticker)
        if turnover is None or turnover <= 0:
            days[ticker] = None
            continue
        needed = float(cfg.notional * weight / (cfg.adv_participation * turnover))
        days[ticker] = needed
        if needed > cfg.days_to_liquidate_warning:
            warnings.append(
                f"{ticker}: {needed:.0f} days to liquidate KES {cfg.notional * weight:,.0f} "
                f"at {cfg.adv_participation:.0%} of average daily turnover"
            )
    for ticker in tickers:
        if inputs.turnover.get(ticker) is None:
            warnings.append(f"{ticker}: no turnover data - liquidity unknown")

    inputs_note: dict[str, Any] = {
        "window": cfg.window,
        "notional": cfg.notional,
        "adv_participation": cfg.adv_participation,
        "risk_free_rate": config.market.risk_free_rate,
        "covered": covered,
        "missing": missing,
    }
    if missing:
        why = ", ".join(
            f"{t} ({len(inputs.returns[t])} obs)" if t in inputs.returns else f"{t} (no series)"
            for t in missing
        )
        blocked = Measure.unavailable(
            f"portfolio: {coverage:.0%} of the weight has enough history; missing {why}"
        )
        return PortfolioAnalysis(
            weights,
            coverage,
            blocked,
            blocked,
            blocked,
            blocked,
            blocked,
            blocked,
            {},
            hhi,
            effective,
            top_n,
            sector_exposure,
            industry_exposure,
            days,
            warnings,
            inputs_note,
        )

    frame = pd.concat([inputs.returns[t].rename(t) for t in covered], axis=1, join="inner").dropna()
    if len(frame) < cfg.min_observations:
        blocked = Measure.unavailable(
            f"portfolio: {len(frame)} common return dates across the positions, "
            f"minimum {cfg.min_observations}"
        )
        return PortfolioAnalysis(
            weights,
            coverage,
            blocked,
            blocked,
            blocked,
            blocked,
            blocked,
            blocked,
            {},
            hhi,
            effective,
            top_n,
            sector_exposure,
            industry_exposure,
            days,
            warnings,
            inputs_note,
        )
    matrix = frame.to_numpy(dtype=float)
    w = np.array([weights[t] for t in covered])
    daily = matrix @ w
    periods = config.market.trading_days_per_year
    mean_annual = float(daily.mean() * periods)
    vol_annual = float(daily.std(ddof=1) * np.sqrt(periods))
    corr = np.corrcoef(matrix, rowvar=False) if len(covered) > 1 else np.ones((1, 1))
    corr_map = {
        a: {b: float(corr[i, j]) for j, b in enumerate(covered)} for i, a in enumerate(covered)
    }
    if len(covered) > 1:
        upper = corr[np.triu_indices(len(covered), k=1)]
        avg_corr = float(np.nanmean(upper))
    else:
        avg_corr = float("nan")
    start, end = frame.index[0].date(), frame.index[-1].date()
    provenance = Provenance(
        table="stock_observations",
        start=start,
        end=end,
        note=f"{len(frame)} common daily returns across {len(covered)} positions",
    )

    def known(value: float) -> Measure:
        return Measure.known(value, provenance) if value != 0 else Measure.zero(provenance)

    sharpe = (
        known((mean_annual - config.market.risk_free_rate) / vol_annual)
        if vol_annual > 0
        else Measure.not_meaningful("Sharpe: zero volatility")
    )
    beta: Measure
    if inputs.benchmark is None:
        beta = Measure.unavailable(f"beta: {inputs.benchmark_reason or 'no benchmark series'}")
    else:
        joined = pd.concat(
            [pd.Series(daily, index=frame.index, name="p"), inputs.benchmark.rename("b")],
            axis=1,
            join="inner",
        ).dropna()
        if len(joined) < cfg.min_observations:
            beta = Measure.unavailable(
                f"beta: {len(joined)} paired observations with the benchmark, "
                f"minimum {cfg.min_observations}"
            )
        else:
            b = joined["b"].to_numpy(dtype=float)
            var_b = float(b.var(ddof=1))
            beta = (
                known(float(np.cov(joined["p"].to_numpy(dtype=float), b, ddof=1)[0, 1] / var_b))
                if var_b > 0
                else Measure.not_meaningful("beta: benchmark has no variance")
            )
    if np.isfinite(avg_corr) and avg_corr > cfg.correlation_warning:
        warnings.append(
            f"average pairwise correlation {avg_corr:.2f}: the {len(covered)} positions move "
            f"together (effective diversification is much lower than the count suggests)"
        )
    inputs_note["observations"] = len(frame)
    inputs_note["start"] = start.isoformat()
    inputs_note["end"] = end.isoformat()
    return PortfolioAnalysis(
        weights,
        coverage,
        known(mean_annual),
        known(vol_annual),
        sharpe,
        known(_max_drawdown(daily)),
        beta,
        known(avg_corr)
        if np.isfinite(avg_corr)
        else Measure.not_applicable("correlation: one position"),
        corr_map,
        hhi,
        effective,
        top_n,
        sector_exposure,
        industry_exposure,
        days,
        warnings,
        inputs_note,
    )


__all__ = [
    "PortfolioAnalysis",
    "PortfolioInputs",
    "WeightError",
    "analyse_portfolio",
    "concentration",
    "exposures",
    "parse_weights",
    "validate_weights",
]
