"""The liquidity engine: how tradeable an instrument actually is.

Over the liquidity window (config, default 6M), on the instrument's own
observations inside one segment:

* ``avg_daily_volume`` - mean of the reported volumes (shares); ``unavailable``
  when fewer than ``min_volume_observations`` observations report one - the
  scraper era carries volume for only a rotating handful, and a missing volume is
  **not** zero;
* ``avg_daily_turnover`` - mean of close x volume (KES);
* ``trading_frequency`` - observed trading days over the business days in the
  window (a stock that only prints a price twice a month is illiquid whatever its
  volume says);
* ``zero_volume_days`` / ``zero_volume_share`` - explicit zero-volume observations;
* ``volume_cv`` / ``turnover_cv`` - coefficient of variation (std / mean); lower is
  steadier;
* ``market_cap`` - the latest ``fundamental_snapshots`` overview value on or before
  ``as_of`` (only from 2026-09-13; ``unavailable`` with the reason before that);
* ``free_float`` - ``unavailable``: no source carries it yet.

``liquidity_score`` (0-100) is cross-sectional: percentile ranks of turnover,
frequency, non-zero-volume share and steadiness across the universe as of the
date, weighted by config, then mapped to five buckets. It is computed by the
service, which sees the whole universe; this module provides the per-instrument
inputs and the scoring function.

    codegraph explore "liquidity_inputs liquidity_scores LiquidityInputs"
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from app.web.services.analytics.config import AnalyticsConfig
from app.web.services.analytics.measure import Measure, Provenance
from app.web.services.analytics.momentum.engine import MetricResult
from app.web.services.analytics.risk.engine import Window, resolve_window
from app.web.services.analytics.series import PriceSeries

BUCKETS: tuple[tuple[float, str], ...] = (
    (80.0, "Highly liquid"),
    (60.0, "Liquid"),
    (40.0, "Moderately liquid"),
    (20.0, "Illiquid"),
    (0.0, "Very illiquid"),
)


@dataclass(frozen=True, slots=True)
class LiquidityInputs:
    """Per-instrument measures plus the raw numbers the cross-sectional score needs."""

    metrics: dict[str, MetricResult]
    turnover: float | None
    frequency: float | None
    nonzero_share: float | None
    steadiness: float | None


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


def market_cap(snapshots: Sequence[Mapping[str, Any]], as_of: date) -> MetricResult:
    """Latest overview snapshot on or before ``as_of`` with a market cap."""
    latest: Mapping[str, Any] | None = None
    for snapshot in snapshots:
        if snapshot.get("view") != "overview":
            continue
        day = date.fromisoformat(str(snapshot["snapshot_date"])[:10])
        if day <= as_of and (snapshot.get("metrics") or {}).get("marketCap"):
            latest = snapshot
    if latest is None:
        return MetricResult(
            Measure.unavailable(f"market cap: no fundamentals snapshot on or before {as_of}")
        )
    day = date.fromisoformat(str(latest["snapshot_date"])[:10])
    value = float(latest["metrics"]["marketCap"])
    return MetricResult(
        Measure.known(
            value,
            Provenance(
                table="fundamental_snapshots",
                ids=(int(latest.get("id") or 0),),
                ticker=str(latest.get("ticker_symbol")),
                end=day,
                note=f"stockanalysis overview marketCap on {day}",
            ),
        ),
        day,
        day,
        False,
    )


def liquidity_inputs(
    series: PriceSeries,
    as_of: date,
    snapshots: Sequence[Mapping[str, Any]],
    config: AnalyticsConfig,
) -> LiquidityInputs:
    cfg = config.liquidity
    out: dict[str, MetricResult] = {}
    window = resolve_window(series, as_of, cfg.window, "liquidity")
    if isinstance(window, Measure):
        for metric in (
            "avg_daily_volume",
            "avg_daily_turnover",
            "trading_frequency",
            "zero_volume_days",
            "zero_volume_share",
            "volume_cv",
            "turnover_cv",
        ):
            out[metric] = MetricResult(window)
        out["market_cap"] = market_cap(snapshots, as_of)
        out["free_float"] = MetricResult(Measure.unavailable("free float: no source carries it"))
        return LiquidityInputs(out, None, None, None, None)

    part = window.part
    business_days = int(np.busday_count(window.start, window.end + pd.Timedelta(days=1)))
    frequency = len(part) / business_days if business_days else 0.0
    out["trading_frequency"] = _stat(
        frequency, window, f"{len(part)} observations over {business_days} business days"
    )

    volume = part.volume.dropna()
    reported = len(volume)
    turnover_value: float | None = None
    nonzero_share: float | None = None
    steadiness: float | None = None
    if reported < cfg.min_volume_observations:
        reason = (
            f"volume reported on {reported} of {len(part)} observations "
            f"(minimum {cfg.min_volume_observations})"
        )
        for metric in (
            "avg_daily_volume",
            "avg_daily_turnover",
            "zero_volume_days",
            "zero_volume_share",
            "volume_cv",
            "turnover_cv",
        ):
            out[metric] = MetricResult(Measure.unavailable(f"{metric}: {reason}"))
    else:
        turnover = (part.close.loc[volume.index] * volume).astype(float)
        zero_days = int((volume == 0).sum())
        out["avg_daily_volume"] = _stat(float(volume.mean()), window, f"mean of {reported} volumes")
        out["avg_daily_turnover"] = _stat(
            float(turnover.mean()), window, f"mean close x volume over {reported} observations"
        )
        out["zero_volume_days"] = _stat(float(zero_days), window, f"of {reported} reported")
        out["zero_volume_share"] = _stat(zero_days / reported, window, f"{zero_days}/{reported}")
        mean_volume = float(volume.mean())
        mean_turnover = float(turnover.mean())
        if mean_volume > 0:
            out["volume_cv"] = _stat(float(volume.std(ddof=1)) / mean_volume, window, "std / mean")
        else:
            out["volume_cv"] = MetricResult(
                Measure.not_meaningful("volume cv: mean volume is zero")
            )
        if mean_turnover > 0:
            cv = float(turnover.std(ddof=1)) / mean_turnover
            out["turnover_cv"] = _stat(cv, window, "std / mean")
            steadiness = 1.0 / (1.0 + cv)
        else:
            out["turnover_cv"] = MetricResult(
                Measure.not_meaningful("turnover cv: mean turnover is zero")
            )
        turnover_value = mean_turnover
        nonzero_share = 1.0 - zero_days / reported
    out["market_cap"] = market_cap(snapshots, as_of)
    out["free_float"] = MetricResult(Measure.unavailable("free float: no source carries it"))
    return LiquidityInputs(out, turnover_value, frequency, nonzero_share, steadiness)


def _percentile_ranks(values: Mapping[str, float | None]) -> dict[str, float]:
    """0-100 percentile rank among the tickers that have a value.

    Ties take the highest rank (``method="max"``): every stock that traded on every
    business day is at the top for frequency, not averaged down into the middle
    because forty others did the same.
    """
    known = {t: v for t, v in values.items() if v is not None and np.isfinite(v)}
    if not known:
        return {}
    ranked = pd.Series(known).rank(pct=True, method="max") * 100.0
    return {str(t): float(v) for t, v in ranked.items()}


def bucket_label(score: float, thresholds: Sequence[float]) -> str:
    """Map a score to one of the five labels using the configured lower bounds."""
    labels = [label for _, label in BUCKETS]
    for bound, label in zip(thresholds, labels[:-1], strict=True):
        if score >= bound:
            return label
    return labels[-1]


def liquidity_scores(
    inputs: Mapping[str, LiquidityInputs], as_of: date, config: AnalyticsConfig
) -> dict[str, tuple[MetricResult, MetricResult]]:
    """``liquidity_score`` and ``liquidity_bucket`` per ticker from the cross-section.

    A ticker missing turnover (no volume reported in the window) gets ``unavailable``
    for both - never a low score - because absence of data is not illiquidity.
    """
    cfg = config.liquidity
    turnover_pct = _percentile_ranks({t: i.turnover for t, i in inputs.items()})
    frequency_pct = _percentile_ranks({t: i.frequency for t, i in inputs.items()})
    nonzero_pct = _percentile_ranks({t: i.nonzero_share for t, i in inputs.items()})
    steady_pct = _percentile_ranks({t: i.steadiness for t, i in inputs.items()})
    out: dict[str, tuple[MetricResult, MetricResult]] = {}
    for ticker, item in inputs.items():
        if ticker not in turnover_pct or ticker not in frequency_pct:
            reason = item.metrics["avg_daily_turnover"].measure.reason or "turnover unavailable"
            blocked = MetricResult(Measure.unavailable(f"liquidity score: {reason}"))
            out[ticker] = (blocked, blocked)
            continue
        components = {
            "turnover": (turnover_pct[ticker], cfg.weight_turnover),
            "frequency": (frequency_pct[ticker], cfg.weight_frequency),
            "nonzero": (nonzero_pct.get(ticker, 0.0), cfg.weight_nonzero_volume),
            "steadiness": (steady_pct.get(ticker, 0.0), cfg.weight_steadiness),
        }
        total_weight = sum(w for _, w in components.values())
        score = sum(p * w for p, w in components.values()) / total_weight
        label = bucket_label(score, cfg.bucket_thresholds)
        note = ", ".join(f"{name} pct {p:.0f}" for name, (p, _) in components.items())
        provenance = Provenance(
            table="market_metrics",
            ticker=ticker,
            end=as_of,
            note=f"cross-section of {len(turnover_pct)} instruments: {note}",
        )
        score_result = MetricResult(Measure.known(score, provenance), None, as_of, False)
        bucket_index = float(len(BUCKETS) - [b for _, b in BUCKETS].index(label))
        bucket_result = MetricResult(
            Measure.known(bucket_index, provenance, reason=label), None, as_of, False
        )
        out[ticker] = (score_result, bucket_result)
    return out


__all__ = [
    "BUCKETS",
    "LiquidityInputs",
    "bucket_label",
    "liquidity_inputs",
    "liquidity_scores",
    "market_cap",
]
