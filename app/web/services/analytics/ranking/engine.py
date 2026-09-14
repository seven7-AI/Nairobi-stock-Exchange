"""The composite ranking: overall score, classification, value-trap risk, compounder
score and a machine-readable explanation for every instrument as of a date.

Pure: it takes the factor scores and the raw metrics already stored for the
date. Every number here is reproducible from those rows and the weights version.

* ``overall`` - the weight-averaged market percentile of the factors that are
  available for the stock (weights renormalised); ``confidence`` is the available
  weight share times the mean factor coverage; below ``min_weight_available`` the
  stock gets no overall score;
* classification bands on the overall score, then two caps: a liquidity score
  below the gate or a confidence below the gate caps at *Watch*, a HIGH value-trap
  risk caps at *Watch*;
* value-trap risk - "cheap" (P/E far below the market, P/B below 1, or a high yield)
  combined with deterioration signals (falling revenue/EPS, deteriorating ROE,
  margins or leverage, negative FCF, weak momentum, thin liquidity, a dividend cut):
  HIGH with enough signals, MEDIUM with some, LOW otherwise, ``unavailable`` when
  nothing about cheapness is known;
* compounder score - the share of applicable compounding criteria met (steady
  revenue and EPS growth, strong ROE/ROA, positive FCF and FCF margin, controlled
  leverage, non-deteriorating margins, dividend growth, momentum), ``unavailable``
  when too few criteria can be judged.

These are model outputs, labelled as such in the explanation - never advice.

    codegraph explore "rank_universe composite_score value_trap compounder_score"
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from app.web.services.analytics.classification.taxonomy import FINANCIAL_SECTORS
from app.web.services.analytics.config import AnalyticsConfig
from app.web.services.analytics.measure import Measure, Provenance

CLASSES = ("Strong Candidate", "Buy Candidate", "Watch", "Neutral", "Weak", "Avoid")


class TrapRisk(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2


@dataclass(frozen=True, slots=True)
class FactorInput:
    """What the ranking needs per factor: the market percentile and the coverage."""

    factor: str
    percentile_market: float | None
    percentile_sector: float | None
    percentile_industry: float | None
    coverage: float
    status: str


@dataclass(frozen=True, slots=True)
class Detector:
    measure: Measure
    signals: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Ranking:
    ticker_symbol: str
    overall: Measure
    confidence: float
    classification: str | None
    factor_scores: dict[str, float | None]
    value_trap: Detector
    compounder: Detector
    explanation: dict[str, Any] = field(default_factory=dict)
    market_rank: int | None = None
    sector_rank: int | None = None
    industry_rank: int | None = None


# --- composite ------------------------------------------------------------------------


def composite_score(
    factors: Mapping[str, FactorInput], config: AnalyticsConfig
) -> tuple[Measure, float, dict[str, float | None]]:
    """Weighted market percentile over the available factors, plus confidence."""
    cfg = config.ranking
    total = sum(cfg.weights.values())
    available = 0.0
    weighted = 0.0
    coverage_sum = 0.0
    per_factor: dict[str, float | None] = {}
    for name, weight in cfg.weights.items():
        item = factors.get(name)
        if item is None or item.percentile_market is None:
            per_factor[name] = None
            continue
        per_factor[name] = item.percentile_market
        available += weight
        weighted += weight * item.percentile_market
        coverage_sum += weight * item.coverage
    share = available / total if total else 0.0
    if share < cfg.min_weight_available or available == 0.0:
        missing = [n for n, p in per_factor.items() if p is None]
        return (
            Measure.unavailable(
                f"overall: {share:.0%} of factor weight available (minimum "
                f"{cfg.min_weight_available:.0%}); missing {', '.join(missing)}"
            ),
            0.0,
            per_factor,
        )
    score = weighted / available
    confidence = share * (coverage_sum / available)
    provenance = Provenance(
        table="factor_scores",
        note=f"{cfg.model_name} v{cfg.model_version}: {share:.0%} of weight available",
    )
    return (
        Measure.known(score, provenance) if score != 0 else Measure.zero(provenance),
        confidence,
        per_factor,
    )


def classify(
    overall: Measure,
    confidence: float,
    liquidity_score: float | None,
    trap: TrapRisk | None,
    config: AnalyticsConfig,
) -> tuple[str | None, list[str]]:
    """Band by score, then apply the caps. Returns the class and the caps that actually
    pulled it down (a gate on a stock already at Watch or below changes nothing)."""
    if not overall.is_known or overall.value is None:
        return None, []
    cfg = config.ranking
    band = CLASSES[-1]
    for bound, label in zip(cfg.class_thresholds, CLASSES[:-1], strict=True):
        if overall.value >= bound:
            band = label
            break
    caps: list[str] = []
    order = {label: i for i, label in enumerate(CLASSES)}
    watch = order["Watch"]
    if liquidity_score is not None and liquidity_score < cfg.liquidity_gate:
        caps.append(
            f"liquidity score {liquidity_score:.0f} below the {cfg.liquidity_gate:.0f} gate"
        )
    if confidence < cfg.confidence_gate:
        caps.append(f"confidence {confidence:.0%} below the {cfg.confidence_gate:.0%} gate")
    if trap is TrapRisk.HIGH:
        caps.append("value-trap risk HIGH")
    if not caps or order[band] >= watch:
        return band, []  # nothing to cap: the band already sits at Watch or below
    return "Watch", caps


# --- detectors ------------------------------------------------------------------------


def _v(metrics: Mapping[str, Measure], name: str) -> float | None:
    m = metrics.get(name)
    return m.value if m is not None and m.is_known else None


def value_trap(metrics: Mapping[str, Measure], config: AnalyticsConfig) -> Detector:
    cfg = config.ranking
    cheap: list[str] = []
    pe_vs_market = _v(metrics, "pe_vs_market")
    pb = _v(metrics, "pb")
    dividend_yield = _v(metrics, "dividend_yield")
    if pe_vs_market is not None and pe_vs_market <= cfg.trap_cheap_pe_vs_market:
        cheap.append(f"P/E {pe_vs_market:+.0%} vs the market")
    if pb is not None and pb < cfg.trap_cheap_pb:
        cheap.append(f"P/B {pb:.2f}")
    if dividend_yield is not None and dividend_yield >= cfg.trap_cheap_yield:
        cheap.append(f"dividend yield {dividend_yield:.1%}")
    nothing_known = pe_vs_market is None and pb is None and dividend_yield is None
    if nothing_known:
        return Detector(Measure.unavailable("value trap: no valuation multiple known"), ())

    signals: list[str] = []
    momentum = _v(metrics, "momentum_12m_1m")
    liquidity = _v(metrics, "liquidity_score")
    checks: list[tuple[str, bool, str]] = [
        ("revenue_growth_1y", (_v(metrics, "revenue_growth_1y") or 0) < 0, "revenue fell"),
        ("eps_growth_1y", (_v(metrics, "eps_growth_1y") or 0) < 0, "EPS fell"),
        ("roe_trend", _v(metrics, "roe_trend") == -1, "ROE deteriorating"),
        ("net_margin_trend", _v(metrics, "net_margin_trend") == -1, "margins deteriorating"),
        ("debt_to_equity_trend", _v(metrics, "debt_to_equity_trend") == -1, "leverage rising"),
        ("fcf", (_v(metrics, "fcf") or 0) < 0, "negative free cash flow"),
        ("momentum_12m_1m", momentum is not None and momentum < cfg.trap_momentum, "weak momentum"),
        (
            "liquidity_score",
            liquidity is not None and liquidity < cfg.trap_liquidity,
            "thin liquidity",
        ),
        ("dividend_cut", _v(metrics, "dividend_cut") == 1, "dividend cut"),
    ]
    for name, fired, label in checks:
        if _v(metrics, name) is not None and fired:
            signals.append(label)
    if cheap and len(signals) >= cfg.trap_high_signals:
        risk = TrapRisk.HIGH
    elif (cheap and signals) or len(signals) >= cfg.trap_high_signals + 1:
        risk = TrapRisk.MEDIUM
    else:
        risk = TrapRisk.LOW
    parts: list[str] = []
    if cheap:
        parts.append("cheap on " + ", ".join(cheap))
    parts.append(
        ", ".join(signals) if signals else ("no deterioration signals" if cheap else "not cheap")
    )
    reason = f"{risk.name}: " + "; ".join(parts)
    provenance = Provenance(table="fundamental_metrics+market_metrics", note=reason)
    measure = (
        Measure.known(float(risk), provenance, reason=reason)
        if risk
        else Measure.zero(provenance, reason=reason)
    )
    return Detector(measure, tuple(cheap) + tuple(signals))


def compounder_score(
    metrics: Mapping[str, Measure], config: AnalyticsConfig, *, sector_code: str | None
) -> Detector:
    cfg = config.ranking
    financial = sector_code in FINANCIAL_SECTORS
    criteria: list[tuple[str, float | None, bool]] = []  # (label, value, met)

    def add(label: str, name: str, test: Any) -> None:
        value = _v(metrics, name)
        criteria.append((label, value, bool(test(value)) if value is not None else False))

    add("revenue 3y CAGR", "revenue_cagr_3y", lambda v: v >= cfg.compounder_growth)
    add("EPS 3y CAGR", "eps_cagr_3y", lambda v: v >= cfg.compounder_growth)
    add("revenue grew last year", "revenue_growth_1y", lambda v: v > 0)
    add("ROE", "roe", lambda v: v >= cfg.compounder_roe)
    add(
        "ROA",
        "roa",
        lambda v: v >= (cfg.compounder_roa_financial if financial else cfg.compounder_roa),
    )
    add("positive FCF", "fcf", lambda v: v > 0)
    add("FCF margin", "fcf_margin", lambda v: v >= cfg.compounder_fcf_margin)
    if not financial:
        add("leverage under control", "debt_to_equity", lambda v: v <= cfg.compounder_max_leverage)
    add("margins not deteriorating", "net_margin_trend", lambda v: v >= 0)
    add("dividend growing", "dividend_cagr_3y", lambda v: v > 0)
    add("positive momentum", "momentum_12m_1m", lambda v: v > 0)

    known = [c for c in criteria if c[1] is not None]
    if len(known) < cfg.compounder_min_known * len(criteria):
        return Detector(
            Measure.unavailable(
                f"compounder: {len(known)} of {len(criteria)} criteria can be judged"
            ),
            (),
        )
    met = [c for c in known if c[2]]
    score = 100.0 * len(met) / len(known)
    note = f"{len(met)}/{len(known)} criteria met: " + ", ".join(c[0] for c in met)
    provenance = Provenance(table="fundamental_metrics+market_metrics", note=note)
    measure = (
        Measure.known(score, provenance, reason=note)
        if score
        else Measure.zero(provenance, reason=note)
    )
    return Detector(measure, tuple(c[0] for c in met))


# --- explanation --------------------------------------------------------------------


def explain(
    ticker: str,
    overall: Measure,
    confidence: float,
    classification: str | None,
    caps: list[str],
    factors: Mapping[str, FactorInput],
    per_factor: Mapping[str, float | None],
    trap: Detector,
    compounder: Detector,
    metrics: Mapping[str, Measure],
    config: AnalyticsConfig,
) -> dict[str, Any]:
    cfg = config.ranking
    positives: list[str] = []
    negatives: list[str] = []
    for name, percentile in per_factor.items():
        if percentile is None:
            why = factors[name].status if name in factors else "no factor row"
            negatives.append(f"{name}: not scored ({why})")
        elif percentile >= 70:
            positives.append(f"Strong {name} (P{percentile:.0f} in the market)")
        elif percentile <= 30:
            negatives.append(f"Weak {name} (P{percentile:.0f} in the market)")
    if trap.measure.is_known and trap.measure.value in (
        float(TrapRisk.HIGH),
        float(TrapRisk.MEDIUM),
    ):
        negatives.append(f"Value-trap risk {trap.measure.reason}")
    if compounder.measure.is_known and (compounder.measure.value or 0) >= 70:
        positives.append(f"Compounder profile: {compounder.measure.reason}")
    for cap in caps:
        negatives.append(f"Capped at Watch: {cap}")
    flagged = [
        n
        for n in ("momentum_12m_1m", "volatility_annualised")
        if n in metrics
        and "flagged" in ((metrics[n].provenance[0].note or "") if metrics[n].provenance else "")
    ]
    if flagged:
        negatives.append("A window contains a suspected corporate action (unadjusted prices)")
    return {
        "ticker": ticker,
        "model": {"name": cfg.model_name, "version": cfg.model_version},
        "overall": overall.as_dict(),
        "confidence": round(confidence, 4),
        "classification": classification,
        "factors": {
            name: {
                "percentile_market": per_factor.get(name),
                "percentile_sector": factors[name].percentile_sector if name in factors else None,
                "percentile_industry": factors[name].percentile_industry
                if name in factors
                else None,
                "weight": cfg.weights[name],
                "coverage": factors[name].coverage if name in factors else 0.0,
            }
            for name in cfg.weights
        },
        "positive_factors": positives,
        "negative_factors": negatives,
        "value_trap": {"risk": trap.measure.as_dict(), "signals": list(trap.signals)},
        "compounder": {
            "score": compounder.measure.as_dict(),
            "criteria_met": list(compounder.signals),
        },
        "disclaimer": "Model output from stored metrics; not investment advice.",
    }


# --- the universe ---------------------------------------------------------------------


def rank_universe(
    factors: Mapping[str, Mapping[str, FactorInput]],
    metrics: Mapping[str, Mapping[str, Measure]],
    groups: Mapping[str, Mapping[str, str | None]],
    config: AnalyticsConfig,
) -> list[Ranking]:
    """Score, classify and rank every ticker that has factor rows."""
    provisional: list[Ranking] = []
    for ticker, own in factors.items():
        own_metrics = metrics.get(ticker, {})
        overall, confidence, per_factor = composite_score(own, config)
        trap = value_trap(own_metrics, config)
        sector_code = groups.get("sector", {}).get(ticker)
        compounder = compounder_score(own_metrics, config, sector_code=sector_code)
        trap_risk = (
            TrapRisk(int(trap.measure.value))
            if trap.measure.is_known and trap.measure.value is not None
            else None
        )
        classification, caps = classify(
            overall, confidence, _v(own_metrics, "liquidity_score"), trap_risk, config
        )
        explanation = explain(
            ticker,
            overall,
            confidence,
            classification,
            caps,
            own,
            per_factor,
            trap,
            compounder,
            own_metrics,
            config,
        )
        provisional.append(
            Ranking(
                ticker,
                overall,
                confidence,
                classification,
                per_factor,
                trap,
                compounder,
                explanation,
            )
        )

    scored = sorted(
        (r for r in provisional if r.overall.is_known and r.overall.value is not None),
        key=lambda r: -(r.overall.value or 0),
    )
    market_rank = {r.ticker_symbol: i + 1 for i, r in enumerate(scored)}
    sector_rank: dict[str, int] = {}
    industry_rank: dict[str, int] = {}
    for level, target in (("sector", sector_rank), ("industry", industry_rank)):
        membership = groups.get(level, {})
        counters: dict[str, int] = {}
        for r in scored:
            key = membership.get(r.ticker_symbol)
            if key is None:
                continue
            counters[key] = counters.get(key, 0) + 1
            target[r.ticker_symbol] = counters[key]
    out: list[Ranking] = []
    for r in provisional:
        explanation = dict(r.explanation)
        explanation["ranks"] = {
            "market": market_rank.get(r.ticker_symbol),
            "market_of": len(scored),
            "sector": sector_rank.get(r.ticker_symbol),
            "industry": industry_rank.get(r.ticker_symbol),
        }
        out.append(
            Ranking(
                r.ticker_symbol,
                r.overall,
                r.confidence,
                r.classification,
                r.factor_scores,
                r.value_trap,
                r.compounder,
                explanation,
                market_rank.get(r.ticker_symbol),
                sector_rank.get(r.ticker_symbol),
                industry_rank.get(r.ticker_symbol),
            )
        )
    return out


__all__ = [
    "CLASSES",
    "Detector",
    "FactorInput",
    "Ranking",
    "TrapRisk",
    "classify",
    "composite_score",
    "compounder_score",
    "explain",
    "rank_universe",
    "value_trap",
]
