"""Market-regime detection on the benchmark index.

Trend: the index against its 200-day moving average and its 6-month return
(Bull when above the average with a return beyond +5 %, Bear when below with a
return beyond -5 %, Sideways otherwise). Volatility: the 63-day annualised
volatility against the median of the same measure over three years (High-vol above
1.25x, Low-vol below 0.75x, Normal between). Risk: risk-on in a Bull that is not
High-vol, risk-off in a Bear or High-vol, neutral otherwise. The evidence - every
number the labels came from - is stored with the label, and the factor-weight
overrides the regime *proposes* are recorded for the backtester to evaluate, not
applied anywhere by default.

A date whose windows cross a data gap (the 2025 gap) gets no regime.

    codegraph explore "detect_regime Regime regime_weights"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from app.web.services.analytics.config import AnalyticsConfig
from app.web.services.analytics.measure import Measure, Provenance
from app.web.services.analytics.returns.engine import window_return
from app.web.services.analytics.risk.engine import Window, resolve_window
from app.web.services.analytics.series import PriceSeries

TREND_LABELS = ("Bull", "Bear", "Sideways")
VOL_LABELS = ("High-vol", "Low-vol", "Normal")


@dataclass(frozen=True, slots=True)
class Regime:
    index: str
    as_of: date
    measure: Measure  # the composite label is in the reason; value = risk score (+1/0/-1)
    trend: str | None = None
    volatility: str | None = None
    risk: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    weight_overrides: dict[str, float] = field(default_factory=dict)


def regime_weights(base: dict[str, float], overrides: dict[str, float]) -> dict[str, float]:
    """Base factor weights plus the additive overrides, floored at zero and renormalised."""
    adjusted = {k: max(0.0, v + overrides.get(k, 0.0)) for k, v in base.items()}
    total = sum(adjusted.values())
    return {k: v / total for k, v in adjusted.items()} if total > 0 else dict(base)


def reference_window(series: PriceSeries, as_of: date, config: AnalyticsConfig) -> Window | Measure:
    """The volatility reference window ending at ``as_of``: the configured span, or -
    when the index is younger than that, or the span would cross a data gap -
    everything in the segment that contains ``as_of`` (the minimum length is enforced
    by the caller, so a short segment after a gap still yields no regime). A stale
    end always blocks."""
    cfg = config.regime
    window = resolve_window(series, as_of, cfg.vol_reference_window, "regime")
    reason = window.reason or "" if isinstance(window, Measure) else ""
    if not isinstance(window, Measure) or not (
        "history starts" in reason or "crosses data gap" in reason
    ):
        return window
    part = series.as_of(as_of)
    last = len(part) - 1
    segment_id = int(part.segment.iloc[last])
    in_segment = part.close[part.segment == segment_id]
    start = in_segment.index[0].date()
    end = part.dates[last].date()
    return Window(
        series.between(start, end), start, end, bool(part.flagged.iloc[-len(in_segment) :].any())
    )


def detect_regime(
    series: PriceSeries, as_of: date, config: AnalyticsConfig, *, index: str | None = None
) -> Regime:
    cfg = config.regime
    name = index or cfg.index
    reference = reference_window(series, as_of, config)
    if isinstance(reference, Measure):
        return Regime(name, as_of, Measure(None, reference.status, reference.reason))
    closes = reference.part.close.to_numpy(dtype=float)
    if len(closes) < cfg.trend_ma_days + cfg.vol_window_days:
        return Regime(
            name,
            as_of,
            Measure.unavailable(
                f"regime: {len(closes)} observations in the window, minimum "
                f"{cfg.trend_ma_days + cfg.vol_window_days}"
            ),
        )
    price = float(closes[-1])
    ma = float(closes[-cfg.trend_ma_days :].mean())
    trend_return = window_return(series, as_of, cfg.trend_return_window)
    if not trend_return.measure.is_known or trend_return.measure.value is None:
        return Regime(
            name,
            as_of,
            Measure(None, trend_return.measure.status, f"regime: {trend_return.measure.reason}"),
        )
    six_month = float(trend_return.measure.value)
    log_returns = np.diff(np.log(closes))
    annualiser = np.sqrt(config.market.trading_days_per_year)
    recent_vol = float(log_returns[-cfg.vol_window_days :].std(ddof=1) * annualiser)
    rolling = np.array(
        [
            log_returns[i - cfg.vol_window_days : i].std(ddof=1) * annualiser
            for i in range(cfg.vol_window_days, len(log_returns) + 1)
        ]
    )
    reference_vol = float(np.median(rolling))
    vol_ratio = recent_vol / reference_vol if reference_vol > 0 else float("nan")

    if price > ma and six_month > cfg.trend_threshold:
        trend = "Bull"
    elif price < ma and six_month < -cfg.trend_threshold:
        trend = "Bear"
    else:
        trend = "Sideways"
    if not np.isfinite(vol_ratio):
        volatility = "Normal"
    elif vol_ratio > cfg.high_vol_ratio:
        volatility = "High-vol"
    elif vol_ratio < cfg.low_vol_ratio:
        volatility = "Low-vol"
    else:
        volatility = "Normal"
    if trend == "Bear" or volatility == "High-vol":
        risk, score = "Risk-off", -1.0
    elif trend == "Bull":
        risk, score = "Risk-on", 1.0
    else:
        risk, score = "Neutral", 0.0
    overrides: dict[str, float] = {}
    for label in (trend, volatility):
        for factor, delta in cfg.weight_overrides.get(label, {}).items():
            overrides[factor] = overrides.get(factor, 0.0) + delta
    evidence = {
        "price": price,
        f"ma_{cfg.trend_ma_days}": ma,
        "price_vs_ma": price / ma - 1.0,
        f"return_{cfg.trend_return_window.lower()}": six_month,
        f"vol_{cfg.vol_window_days}d_annualised": recent_vol,
        "vol_reference_median": reference_vol,
        "vol_ratio": vol_ratio if np.isfinite(vol_ratio) else None,
        "window_start": reference.start.isoformat(),
        "window_end": reference.end.isoformat(),
        "contains_flagged": reference.contains_flagged,
    }
    provenance = Provenance(
        table="stock_observations",
        ticker=name,
        start=reference.start,
        end=reference.end,
        note=f"{trend} / {volatility} / {risk}",
    )
    label = f"{trend} / {volatility} / {risk}"
    measure = (
        Measure.known(score, provenance, reason=label)
        if score
        else Measure.zero(provenance, reason=label)
    )
    return Regime(name, as_of, measure, trend, volatility, risk, evidence, overrides)


__all__ = [
    "TREND_LABELS",
    "VOL_LABELS",
    "Regime",
    "detect_regime",
    "reference_window",
    "regime_weights",
]
