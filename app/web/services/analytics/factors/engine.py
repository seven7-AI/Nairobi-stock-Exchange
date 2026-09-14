"""The factor engine: cross-sectional z-scores and peer-relative percentile ranks.

Pure: it takes the metric values already stored for a date (market and fundamental
metrics, keyed by ticker) plus the point-in-time group membership, and returns one
``FactorScore`` per (ticker, factor).

For every factor input across the scoring universe: winsorise at the configured
quantiles, z-score, flip the sign for "lower is better" inputs. A factor's raw
score is the weight-averaged z-score of the inputs that are *known*; ``coverage``
is the share of input weight that was known, and a factor with coverage below
``min_coverage`` is ``unavailable`` rather than a score built on one number.
Percentile ranks (0-100) are then computed within industry, sector and the whole
universe; a group smaller than ``min_group_size`` yields no rank for that level.

    codegraph explore "score_factors FactorScore winsorised_zscores"
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.web.services.analytics.config import AnalyticsConfig, FactorDefinition
from app.web.services.analytics.measure import Measure, Provenance

#: (source, metric) -> {ticker: value}; only KNOWN/ZERO values are present.
MetricTable = Mapping[tuple[str, str], Mapping[str, float]]


@dataclass(frozen=True, slots=True)
class InputScore:
    metric: str
    source: str
    value: float | None
    z: float | None
    weight: float
    status: str


@dataclass(frozen=True, slots=True)
class FactorScore:
    ticker_symbol: str
    factor: str
    measure: Measure
    coverage: float
    percentile_market: float | None
    percentile_sector: float | None
    percentile_industry: float | None
    group_sizes: dict[str, int] = field(default_factory=dict)
    inputs: tuple[InputScore, ...] = ()

    def inputs_json(self) -> list[dict[str, Any]]:
        return [
            {
                "metric": i.metric,
                "source": i.source,
                "value": i.value,
                "z": i.z,
                "weight": i.weight,
                "status": i.status,
            }
            for i in self.inputs
        ]


def winsorised_zscores(
    values: Mapping[str, float], *, lower: float, upper: float
) -> dict[str, float]:
    """z-scores across tickers after clipping to the [lower, upper] quantiles.

    With fewer than three values or no dispersion there is no cross-section to
    stand in: every z is 0 (average), which is honest - nothing distinguishes them.
    """
    if not values:
        return {}
    series = pd.Series(values, dtype=float)
    if len(series) < 3:
        return {str(t): 0.0 for t in series.index}
    clipped = series.clip(series.quantile(lower), series.quantile(upper))
    std = float(clipped.std(ddof=1))
    if std == 0.0 or np.isnan(std):
        return {str(t): 0.0 for t in series.index}
    z = (clipped - clipped.mean()) / std
    return {str(t): float(v) for t, v in z.items()}


def _percentiles(scores: Mapping[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    ranked = pd.Series(scores, dtype=float).rank(pct=True, method="average") * 100.0
    return {str(t): float(v) for t, v in ranked.items()}


def score_factor(
    definition: FactorDefinition,
    metrics: MetricTable,
    universe: Sequence[str],
    config: AnalyticsConfig,
) -> dict[str, tuple[Measure, float, tuple[InputScore, ...]]]:
    """Raw factor score per ticker: weighted mean of signed input z-scores + coverage."""
    cfg = config.factors
    per_input: dict[str, dict[str, float]] = {}
    for spec in definition.inputs:
        raw = {
            t: v for t, v in metrics.get((spec.source, spec.metric), {}).items() if t in universe
        }
        z = winsorised_zscores(raw, lower=cfg.winsor_lower, upper=cfg.winsor_upper)
        per_input[spec.metric] = {t: spec.direction * value for t, value in z.items()}
    total_weight = sum(spec.weight for spec in definition.inputs)
    out: dict[str, tuple[Measure, float, tuple[InputScore, ...]]] = {}
    for ticker in universe:
        inputs: list[InputScore] = []
        weighted = 0.0
        covered = 0.0
        for spec in definition.inputs:
            signed = per_input[spec.metric].get(ticker)
            value = metrics.get((spec.source, spec.metric), {}).get(ticker)
            if signed is None:
                inputs.append(
                    InputScore(spec.metric, spec.source, None, None, spec.weight, "unavailable")
                )
                continue
            inputs.append(InputScore(spec.metric, spec.source, value, signed, spec.weight, "known"))
            weighted += spec.weight * signed
            covered += spec.weight
        coverage = covered / total_weight if total_weight else 0.0
        known_inputs = sum(1 for i in inputs if i.z is not None)
        provenance = Provenance(
            table="market_metrics+fundamental_metrics",
            ticker=ticker,
            note=f"{definition.name}: {known_inputs}/{len(inputs)} inputs, coverage {coverage:.0%}",
        )
        if coverage < cfg.min_coverage or covered == 0.0:
            measure = Measure.unavailable(
                f"{definition.name}: coverage {coverage:.0%} below the "
                f"{cfg.min_coverage:.0%} minimum",
                provenance,
            )
        else:
            score = weighted / covered
            measure = Measure.known(score, provenance) if score != 0 else Measure.zero(provenance)
        out[ticker] = (measure, coverage, tuple(inputs))
    return out


def rank_within_groups(
    scores: Mapping[str, float],
    groups: Mapping[str, Mapping[str, str | None]],
    *,
    min_group_size: int,
) -> dict[str, dict[str, float | None]]:
    """Percentile of each ticker's score within each grouping (``market``, ``sector``,
    ``industry``); None when its group is too small or its membership unknown."""
    out: dict[str, dict[str, float | None]] = {t: {} for t in scores}
    for level, membership in groups.items():
        buckets: dict[str, dict[str, float]] = {}
        for ticker, score in scores.items():
            key = membership.get(ticker)
            if key is None:
                continue
            buckets.setdefault(key, {})[ticker] = score
        for ticker in scores:
            key = membership.get(ticker)
            members = buckets.get(key or "", {})
            if key is None or len(members) < min_group_size:
                out[ticker][level] = None
            else:
                out[ticker][level] = _percentiles(members)[ticker]
    return out


def score_factors(
    metrics: MetricTable,
    universe: Sequence[str],
    groups: Mapping[str, Mapping[str, str | None]],
    config: AnalyticsConfig,
) -> list[FactorScore]:
    """Every factor for every ticker in the universe."""
    results: list[FactorScore] = []
    market_membership = dict.fromkeys(universe, "market")
    all_groups = {"market": market_membership, **groups}
    for definition in config.factors.factors:
        raw = score_factor(definition, metrics, universe, config)
        known = {t: m.value for t, (m, _, _) in raw.items() if m.is_known and m.value is not None}
        ranks = rank_within_groups(known, all_groups, min_group_size=config.factors.min_group_size)
        for ticker in universe:
            measure, coverage, inputs = raw[ticker]
            r = ranks.get(ticker, {})
            sizes = {
                level: sum(1 for t in known if membership.get(t) == membership.get(ticker))
                for level, membership in all_groups.items()
                if membership.get(ticker) is not None
            }
            results.append(
                FactorScore(
                    ticker_symbol=ticker,
                    factor=definition.name,
                    measure=measure,
                    coverage=coverage,
                    percentile_market=r.get("market"),
                    percentile_sector=r.get("sector"),
                    percentile_industry=r.get("industry"),
                    group_sizes=sizes,
                    inputs=inputs,
                )
            )
    return results


__all__ = [
    "FactorScore",
    "InputScore",
    "MetricTable",
    "rank_within_groups",
    "score_factor",
    "score_factors",
    "winsorised_zscores",
]
