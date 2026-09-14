"""The fair-value engine: independent per-share valuations by method, blended.

Pure. It takes the point-in-time inputs already resolved for a stock (latest
fiscal-year figures, price, stored quality / risk / liquidity metrics, peer
multiples) and returns bear / base / bull values per applicable method, the
blended intrinsic value and range, upside, margin of safety and an uncertainty
score. Every assumption used is written into the result.

Method applicability follows the sector: banks, insurers and investment firms are
valued on **justified P/B from ROE** and a **dividend discount**; other operating
companies on a **free-cash-flow DCF** (FCF = OCF - capex, treated as cash flow to
equity and discounted at the cost of equity), **EV/EBITDA** and **P/E** relative to
peers (sector median, else market median). Indices, ETFs and REITs are
``not_applicable``. A method whose inputs make no sense (negative earnings, EBITDA
or free-cash-flow base, ROE at or below growth, discount rate at or below growth)
is ``not_meaningful``; missing inputs make it ``unavailable`` with the reason.

The margin of safety is a number, not a signal: with uncertainty at or above the
configured threshold it is flagged ``actionable = False``.

    codegraph explore "value_stock dcf_value justified_pb_value ddm_value multiple_value"
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.web.services.analytics.classification.taxonomy import (
    FINANCIAL_SECTORS,
    OPERATING_SECTORS,
)
from app.web.services.analytics.config import AnalyticsConfig
from app.web.services.analytics.measure import Measure, Provenance

METHODS_FINANCIAL = ("pb_roe", "ddm")
METHODS_OPERATING = ("dcf", "ev_ebitda", "pe_relative")
BLENDED = "blended"


@dataclass(frozen=True, slots=True)
class ValuationInputs:
    """Everything the engine needs, as resolved on the valuation date.

    Per-share figures are for the latest fiscal year known on the date; ``None``
    means not known. ``fcf_history`` is per-share free cash flow by fiscal year,
    oldest first (used for the DCF base).
    """

    ticker_symbol: str
    sector_code: str | None
    price: float | None
    price_reason: str | None = None
    fiscal_years: int = 0
    eps: float | None = None
    bvps: float | None = None
    dps: float | None = None
    ebitda_per_share: float | None = None
    net_debt_per_share: float | None = None
    fcf_history: tuple[float, ...] = ()
    roe: float | None = None
    payout_ratio: float | None = None
    revenue_cagr_3y: float | None = None
    dividend_cagr_3y: float | None = None
    beta: float | None = None
    liquidity_score: float | None = None
    debt_to_equity: float | None = None
    interest_coverage: float | None = None
    roe_trend: float | None = None
    net_margin_trend: float | None = None
    peer_pe: float | None = None
    peer_pe_source: str | None = None
    peer_ev_ebitda: float | None = None
    peer_ev_ebitda_source: str | None = None
    provenance: tuple[Provenance, ...] = ()


@dataclass(frozen=True, slots=True)
class MethodValuation:
    method: str
    #: The base-case value per share, or the status that stopped the method.
    measure: Measure
    bear: float | None = None
    bull: float | None = None
    assumptions: dict[str, Any] = field(default_factory=dict)

    @property
    def base(self) -> float | None:
        return self.measure.value if self.measure.is_known else None


@dataclass(frozen=True, slots=True)
class Valuation:
    ticker_symbol: str
    price: float | None
    methods: tuple[MethodValuation, ...]
    intrinsic: Measure
    fair_low: float | None
    fair_high: float | None
    upside: Measure
    margin_of_safety: Measure
    uncertainty: float | None
    uncertainty_flags: tuple[str, ...]
    actionable: bool | None
    assumptions: dict[str, Any] = field(default_factory=dict)


# --- building blocks -------------------------------------------------------------------


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def cost_of_equity(beta: float | None, config: AnalyticsConfig) -> tuple[float, dict[str, Any]]:
    """CAPM cost of equity: risk-free + clamped beta x equity risk premium."""
    cfg = config.fair_value
    used = cfg.default_beta if beta is None else clamp(beta, cfg.beta_floor, cfg.beta_cap)
    rate = config.market.risk_free_rate + used * cfg.equity_risk_premium
    return rate, {
        "risk_free_rate": config.market.risk_free_rate,
        "equity_risk_premium": cfg.equity_risk_premium,
        "beta": used,
        "beta_source": "default" if beta is None else "beta_12m (clamped)",
        "cost_of_equity": round(rate, 4),
    }


def _scenarios(bear: float, base: float, bull: float) -> tuple[float, float, float]:
    """Order the three values so bear <= base <= bull whatever the inputs did."""
    return min(bear, base, bull), base, max(bear, base, bull)


def justified_pb_value(inputs: ValuationInputs, config: AnalyticsConfig) -> MethodValuation:
    """Fair P/B = (ROE - g) / (r - g), g = retention x ROE capped; value = P/B x BVPS."""
    cfg = config.fair_value
    missing = [
        n for n, v in (("book value per share", inputs.bvps), ("ROE", inputs.roe)) if v is None
    ]
    if missing:
        return MethodValuation(
            "pb_roe", Measure.unavailable("justified P/B: missing " + ", ".join(missing))
        )
    assert inputs.bvps is not None and inputs.roe is not None
    bvps = float(inputs.bvps)
    if inputs.bvps <= 0:
        return MethodValuation("pb_roe", Measure.not_meaningful("justified P/B: negative equity"))
    if inputs.roe <= 0:
        return MethodValuation(
            "pb_roe", Measure.not_meaningful("justified P/B: ROE is not positive")
        )
    r, rate_assumptions = cost_of_equity(inputs.beta, config)
    retention = (
        1.0 - clamp(inputs.payout_ratio, 0.0, 1.0) if inputs.payout_ratio is not None else 0.5
    )

    def value(roe: float, rate: float) -> float | None:
        g = clamp(retention * roe, 0.0, cfg.sustainable_growth_cap)
        if rate <= g or roe <= g:
            return None
        return (roe - g) / (rate - g) * bvps

    base = value(inputs.roe, r)
    if base is None:
        return MethodValuation(
            "pb_roe",
            Measure.not_meaningful(
                f"justified P/B: cost of equity {r:.1%} does not exceed growth "
                f"{clamp(retention * inputs.roe, 0.0, cfg.sustainable_growth_cap):.1%}"
            ),
            assumptions=rate_assumptions,
        )
    bear = value(inputs.roe * cfg.roe_bear_multiplier, r + cfg.rate_shift)
    bull = value(inputs.roe * cfg.roe_bull_multiplier, r - cfg.rate_shift)
    lo, mid, hi = _scenarios(
        bear if bear is not None else base, base, bull if bull is not None else base
    )
    assumptions = {
        **rate_assumptions,
        "roe": inputs.roe,
        "retention": round(retention, 4),
        "retention_source": "1 - payout ratio"
        if inputs.payout_ratio is not None
        else "default 50%",
        "sustainable_growth": round(
            clamp(retention * inputs.roe, 0.0, cfg.sustainable_growth_cap), 4
        ),
        "book_value_per_share": inputs.bvps,
        "scenarios": {
            "bear": f"ROE x{cfg.roe_bear_multiplier}, rate +{cfg.rate_shift:.0%}",
            "bull": f"ROE x{cfg.roe_bull_multiplier}, rate -{cfg.rate_shift:.0%}",
        },
    }
    return MethodValuation("pb_roe", Measure.known(mid, *inputs.provenance), lo, hi, assumptions)


def ddm_value(inputs: ValuationInputs, config: AnalyticsConfig) -> MethodValuation:
    """Gordon growth: DPS x (1 + g) / (r - g)."""
    cfg = config.fair_value
    if inputs.dps is None:
        return MethodValuation(
            "ddm", Measure.unavailable("dividend discount: missing dividend per share")
        )
    if inputs.dps <= 0:
        return MethodValuation("ddm", Measure.not_meaningful("dividend discount: no dividend paid"))
    dps = float(inputs.dps)
    r, rate_assumptions = cost_of_equity(inputs.beta, config)
    if inputs.dividend_cagr_3y is not None:
        g = clamp(inputs.dividend_cagr_3y, 0.0, cfg.dividend_growth_cap)
        g_source = "dividend 3y CAGR (clamped)"
    elif inputs.roe is not None and inputs.payout_ratio is not None:
        g = clamp(
            (1.0 - clamp(inputs.payout_ratio, 0.0, 1.0)) * inputs.roe, 0.0, cfg.dividend_growth_cap
        )
        g_source = "retention x ROE (clamped)"
    else:
        g = 0.0
        g_source = "no growth history: 0%"

    def value(growth: float, rate: float) -> float | None:
        if rate <= growth:
            return None
        return dps * (1.0 + growth) / (rate - growth)

    base = value(g, r)
    if base is None:
        return MethodValuation(
            "ddm",
            Measure.not_meaningful(
                f"dividend discount: cost of equity {r:.1%} does not exceed growth {g:.1%}"
            ),
            assumptions=rate_assumptions,
        )
    bear = value(max(0.0, g - cfg.dividend_growth_shift), r + cfg.rate_shift)
    bull = value(min(cfg.dividend_growth_cap, g + cfg.dividend_growth_shift), r - cfg.rate_shift)
    lo, mid, hi = _scenarios(
        bear if bear is not None else base, base, bull if bull is not None else base
    )
    assumptions = {
        **rate_assumptions,
        "dividend_per_share": inputs.dps,
        "growth": round(g, 4),
        "growth_source": g_source,
        "scenarios": {
            "bear": f"growth -{cfg.dividend_growth_shift:.0%}, rate +{cfg.rate_shift:.0%}",
            "bull": f"growth +{cfg.dividend_growth_shift:.0%}, rate -{cfg.rate_shift:.0%}",
        },
    }
    return MethodValuation("ddm", Measure.known(mid, *inputs.provenance), lo, hi, assumptions)


def dcf_value(inputs: ValuationInputs, config: AnalyticsConfig) -> MethodValuation:
    """Per-share FCF (average of the last years) grown for ``projection_years`` then a
    Gordon terminal value, all discounted at the cost of equity."""
    cfg = config.fair_value
    history = list(inputs.fcf_history)[-cfg.fcf_average_years :]
    if not history:
        return MethodValuation("dcf", Measure.unavailable("DCF: missing free cash flow per share"))
    base_fcf = sum(history) / len(history)
    if base_fcf <= 0:
        return MethodValuation(
            "dcf",
            Measure.not_meaningful(
                f"DCF: average free cash flow over {len(history)} fiscal year(s) is not positive"
            ),
        )
    r, rate_assumptions = cost_of_equity(inputs.beta, config)
    if inputs.revenue_cagr_3y is not None:
        g = clamp(inputs.revenue_cagr_3y, cfg.growth_floor, cfg.growth_cap)
        g_source = "revenue 3y CAGR (clamped)"
    else:
        g = 0.0
        g_source = "no revenue history: 0%"

    def value(growth: float, terminal: float, rate: float) -> float | None:
        if rate <= terminal:
            return None
        total = 0.0
        cash = base_fcf
        for year in range(1, cfg.projection_years + 1):
            cash *= 1.0 + growth
            total += cash / (1.0 + rate) ** year
        terminal_value = cash * (1.0 + terminal) / (rate - terminal)
        total += terminal_value / (1.0 + rate) ** cfg.projection_years
        return total

    base = value(g, cfg.terminal_growth, r)
    if base is None:
        return MethodValuation(
            "dcf",
            Measure.not_meaningful(
                f"DCF: cost of equity {r:.1%} does not exceed terminal growth "
                f"{cfg.terminal_growth:.1%}"
            ),
            assumptions=rate_assumptions,
        )
    bear = value(
        max(cfg.growth_floor, g - cfg.growth_shift), cfg.terminal_growth_bear, r + cfg.rate_shift
    )
    bull = value(
        min(cfg.growth_cap, g + cfg.growth_shift), cfg.terminal_growth_bull, r - cfg.rate_shift
    )
    lo, mid, hi = _scenarios(
        bear if bear is not None else base, base, bull if bull is not None else base
    )
    assumptions = {
        **rate_assumptions,
        "fcf_per_share_base": round(base_fcf, 4),
        "fcf_years_averaged": len(history),
        "fcf_definition": "operating cash flow - capex, treated as cash flow to equity",
        "growth": round(g, 4),
        "growth_source": g_source,
        "projection_years": cfg.projection_years,
        "terminal_growth": cfg.terminal_growth,
        "scenarios": {
            "bear": (
                f"growth -{cfg.growth_shift:.0%}, terminal {cfg.terminal_growth_bear:.0%}, "
                f"rate +{cfg.rate_shift:.0%}"
            ),
            "bull": (
                f"growth +{cfg.growth_shift:.0%}, terminal {cfg.terminal_growth_bull:.0%}, "
                f"rate -{cfg.rate_shift:.0%}"
            ),
        },
    }
    return MethodValuation("dcf", Measure.known(mid, *inputs.provenance), lo, hi, assumptions)


def multiple_value(
    method: str,
    metric_name: str,
    metric: float | None,
    multiple: float | None,
    multiple_source: str | None,
    inputs: ValuationInputs,
    config: AnalyticsConfig,
    *,
    subtract_net_debt: bool,
) -> MethodValuation:
    """Peer multiple x own metric per share (EV-based methods net out debt)."""
    cfg = config.fair_value
    label = {"ev_ebitda": "EV/EBITDA", "pe_relative": "P/E"}[method]
    if metric is None:
        return MethodValuation(
            method, Measure.unavailable(f"{label} relative: missing {metric_name}")
        )
    if multiple is None:
        return MethodValuation(
            method,
            Measure.unavailable(
                f"{label} relative: no peer median with at least {cfg.min_peers} members"
            ),
        )
    if metric <= 0:
        return MethodValuation(
            method, Measure.not_meaningful(f"{label} relative: {metric_name} is not positive")
        )
    net_debt = inputs.net_debt_per_share if subtract_net_debt else None
    if subtract_net_debt and net_debt is None:
        return MethodValuation(
            method, Measure.unavailable(f"{label} relative: missing net debt per share")
        )

    def value(mult: float) -> float:
        return mult * metric - (net_debt or 0.0)

    base = value(multiple)
    bear = value(multiple * (1.0 - cfg.multiple_haircut))
    bull = value(multiple * (1.0 + cfg.multiple_haircut))
    lo, mid, hi = _scenarios(bear, base, bull)
    assumptions = {
        metric_name: metric,
        "multiple": round(multiple, 4),
        "multiple_source": multiple_source,
        "haircut": cfg.multiple_haircut,
        **({"net_debt_per_share": net_debt} if subtract_net_debt else {}),
    }
    if mid <= 0:
        return MethodValuation(
            method,
            Measure.not_meaningful(
                f"{label} relative: net debt exceeds the implied enterprise value"
            ),
            assumptions=assumptions,
        )
    return MethodValuation(method, Measure.known(mid, *inputs.provenance), lo, hi, assumptions)


# --- uncertainty and blending ------------------------------------------------------------


def uncertainty_score(
    inputs: ValuationInputs,
    known_methods: Sequence[MethodValuation],
    intrinsic: float | None,
    config: AnalyticsConfig,
) -> tuple[float, list[str]]:
    cfg = config.fair_value
    score = cfg.uncertainty_base
    flags: list[str] = []
    if len(known_methods) <= 1:
        score += cfg.uncertainty_single_method
        flags.append("single method" if known_methods else "no method")
    if inputs.fiscal_years < cfg.min_fiscal_years:
        score += cfg.uncertainty_thin_history
        flags.append(f"{inputs.fiscal_years} fiscal year(s) of statements")
    if inputs.roe_trend == -1 or inputs.net_margin_trend == -1:
        score += cfg.uncertainty_deteriorating
        flags.append("deteriorating ROE or margins")
    if inputs.liquidity_score is None or inputs.liquidity_score < cfg.illiquid_score:
        score += cfg.uncertainty_illiquid
        flags.append("thin or unknown liquidity")
    financial = inputs.sector_code in FINANCIAL_SECTORS
    if (
        not financial
        and inputs.debt_to_equity is not None
        and inputs.debt_to_equity > cfg.leverage_limit
    ) or (
        inputs.interest_coverage is not None and 0 <= inputs.interest_coverage < cfg.coverage_limit
    ):
        score += cfg.uncertainty_leverage
        flags.append("balance-sheet risk")
    if inputs.beta is None:
        score += cfg.uncertainty_no_beta
        flags.append("no beta: default used")
    if intrinsic and len(known_methods) > 1:
        bases = [m.base for m in known_methods if m.base is not None]
        if (max(bases) - min(bases)) / intrinsic > cfg.dispersion_limit:
            score += cfg.uncertainty_dispersion
            flags.append("methods disagree")
    return round(min(1.0, score), 4), flags


def value_stock(inputs: ValuationInputs, config: AnalyticsConfig) -> Valuation:
    """Every applicable method, then the blend."""
    cfg = config.fair_value
    sector = inputs.sector_code
    common = {"model": "fair-value v1", "sector": sector}
    if sector is None or sector not in OPERATING_SECTORS:
        why = "unclassified" if sector is None else f"{sector}: not valued by these methods"
        na = Measure.not_applicable(f"fair value: {why}")
        return Valuation(
            inputs.ticker_symbol, inputs.price, (), na, None, None, na, na, None, (), None, common
        )
    methods: tuple[MethodValuation, ...]
    if sector in FINANCIAL_SECTORS:
        methods = (justified_pb_value(inputs, config), ddm_value(inputs, config))
    else:
        methods = (
            dcf_value(inputs, config),
            multiple_value(
                "ev_ebitda",
                "ebitda_per_share",
                inputs.ebitda_per_share,
                inputs.peer_ev_ebitda,
                inputs.peer_ev_ebitda_source,
                inputs,
                config,
                subtract_net_debt=True,
            ),
            multiple_value(
                "pe_relative",
                "eps",
                inputs.eps,
                inputs.peer_pe,
                inputs.peer_pe_source,
                inputs,
                config,
                subtract_net_debt=False,
            ),
        )
    known = [m for m in methods if m.base is not None]
    if not known:
        reasons = "; ".join(f"{m.method}: {m.measure.reason}" for m in methods)
        blocker = methods[0].measure.status
        unavailable = Measure(
            None, blocker, f"fair value: no applicable method produced a value ({reasons})"
        )
        return Valuation(
            inputs.ticker_symbol,
            inputs.price,
            methods,
            unavailable,
            None,
            None,
            unavailable,
            unavailable,
            None,
            (),
            None,
            common,
        )
    intrinsic_value = sum(m.base or 0.0 for m in known) / len(known)
    fair_low = sum(m.bear if m.bear is not None else (m.base or 0.0) for m in known) / len(known)
    fair_high = sum(m.bull if m.bull is not None else (m.base or 0.0) for m in known) / len(known)
    provenance = Provenance(
        table="fundamental_metrics+market_metrics",
        ticker=inputs.ticker_symbol,
        note=f"equal-weight blend of {', '.join(m.method for m in known)}",
    )
    intrinsic = Measure.known(intrinsic_value, provenance)
    uncertainty, flags = uncertainty_score(inputs, known, intrinsic_value, config)
    if inputs.price is None:
        price_block = Measure.unavailable(inputs.price_reason or "price: unavailable")
        upside = price_block
        margin = price_block
    else:
        upside = Measure.known(intrinsic_value / inputs.price - 1.0, provenance)
        margin = (
            Measure.known((intrinsic_value - inputs.price) / intrinsic_value, provenance)
            if intrinsic_value > 0
            else Measure.not_meaningful("margin of safety: intrinsic value is not positive")
        )
    actionable = uncertainty < cfg.uncertainty_threshold
    assumptions = {
        **common,
        "methods_used": [m.method for m in known],
        "blend": "equal-weight mean of method base cases; range = mean of bears .. mean of bulls",
        "uncertainty_threshold": cfg.uncertainty_threshold,
        "uncertainty_flags": flags,
        "disclaimer": "Model output under stated assumptions; not investment advice.",
    }
    return Valuation(
        inputs.ticker_symbol,
        inputs.price,
        methods,
        intrinsic,
        fair_low,
        fair_high,
        upside,
        margin,
        uncertainty,
        tuple(flags),
        actionable,
        assumptions,
    )


__all__ = [
    "BLENDED",
    "METHODS_FINANCIAL",
    "METHODS_OPERATING",
    "MethodValuation",
    "Valuation",
    "ValuationInputs",
    "cost_of_equity",
    "dcf_value",
    "ddm_value",
    "justified_pb_value",
    "multiple_value",
    "uncertainty_score",
    "value_stock",
]
