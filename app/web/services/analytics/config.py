"""``AnalyticsConfig`` - every investment assumption the engine uses, in one place.

Nothing in the engines is a literal: the risk-free rate, publication lags, window
lengths, thresholds and weights all come from here. The configuration is hashed
and recorded as a ``calc_versions`` row before anything is computed, so a stored
number can always be tied to the exact assumptions behind it. Change a value and
you get a new version; the old results stay and keep pointing at the old one.

Sections grow as the engines arrive (returns, momentum, risk, liquidity,
fundamentals, factors, ...). Defaults are starting assumptions, not conclusions -
the backtester exists to test them.

    codegraph explore "AnalyticsConfig config_hash register_calc_version CalcVersion"
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.web.db.analytics.models import CalcVersion

#: Bump when a change to the *meaning* of a section should be visible in the version
#: label even if the numbers did not move (a new metric definition, say).
CONFIG_VERSION = "1.0"


class FundamentalsConfig(BaseModel):
    """How financial statements become point-in-time inputs."""

    model_config = ConfigDict(frozen=True)

    #: Days after a fiscal period end by which its statement is assumed published.
    #: Used only for statements first captured AFTER that date (the 2026-09 backfill of
    #: FY2021-2025); a statement captured live keeps its real first-seen date. NSE
    #: listed companies must publish annual results within 90 days and interim within
    #: 60 days of period end (CMA regulations), which is where the defaults come from.
    publication_lag_days_annual: int = Field(default=90, ge=0, le=365)
    publication_lag_days_interim: int = Field(default=60, ge=0, le=365)
    #: Fiscal years needed before a trend (improving/stable/deteriorating) is labelled.
    trend_min_periods: int = Field(default=3, ge=2)
    #: |slope| / mean level per period within which a trend is "stable".
    trend_stable_band: float = Field(default=0.05, ge=0.0, le=1.0)
    #: Sector-relative growth needs this many peers with a value.
    min_peers: int = Field(default=3, ge=1)

    def publication_lag(self, period_type: str) -> timedelta:
        if period_type == "annual":
            return timedelta(days=self.publication_lag_days_annual)
        return timedelta(days=self.publication_lag_days_interim)


class MarketConfig(BaseModel):
    """Series-level assumptions shared by returns, momentum and risk."""

    model_config = ConfigDict(frozen=True)

    #: A break longer than this between two observations is a data gap, not a holiday.
    #: 14 days is what the stock-growth diagrams already use (growth_series.py).
    gap_threshold_days: int = Field(default=14, ge=2)
    #: NSE trades Monday-Friday; used to convert calendar windows into observation counts.
    trading_days_per_year: int = Field(default=252, ge=200, le=260)
    #: Annual risk-free rate as a fraction. Kenya's 91-day Treasury bill has traded in a
    #: 8-16% band over 2015-2026; the default is a mid value and MUST be reviewed, which
    #: is exactly why it lives here and is versioned.
    risk_free_rate: float = Field(default=0.12, ge=0.0, le=1.0)
    #: Benchmark index used for relative performance and beta.
    benchmark_index: str = "^NASI"
    #: Fallback benchmark when the primary lacks the window (`^N20I` starts 2007).
    secondary_benchmark_index: str = "^N20I"


class DataQualityConfig(BaseModel):
    """Thresholds for the data-quality checks (``analytics/quality``)."""

    model_config = ConfigDict(frozen=True)

    #: |close / previous close - 1| above this is flagged. 0.5 catches decimal-point
    #: slips and unflagged corporate actions; a genuine 50 % daily move on the NSE is
    #: rare enough that flagging it is right.
    price_jump_threshold: float = Field(default=0.5, gt=0.0, le=5.0)
    #: A run of this many consecutive zero-volume days is a liquidity finding.
    zero_volume_streak_days: int = Field(default=20, ge=2)
    #: |assets - (liabilities + equity)| / assets above this flags a balance sheet.
    balance_sheet_tolerance: float = Field(default=0.02, ge=0.0, le=0.5)
    #: A day's low/high must bracket the close within this fraction (rounding slack).
    ohlc_tolerance: float = Field(default=0.005, ge=0.0, le=0.1)
    #: Instruments with fewer observations than this are reported, not analysed.
    min_observations: int = Field(default=20, ge=1)


class MomentumConfig(BaseModel):
    """Momentum engine parameters (``analytics/momentum``)."""

    model_config = ConfigDict(frozen=True)

    #: Moving-average lengths in observations (trading days).
    ma_short: int = Field(default=50, ge=5, le=250)
    ma_long: int = Field(default=200, ge=20, le=500)
    #: Window for the signed-R² trend strength.
    trend_window: str = Field(default="6M", pattern=r"^(1|3|6|12|24|36)M$")
    #: Sector-relative returns need at least this many peers with a known return.
    min_peers: int = Field(default=2, ge=1)


class RiskConfig(BaseModel):
    """Risk engine windows and minimums (``analytics/risk``)."""

    model_config = ConfigDict(frozen=True)

    volatility_window: str = Field(default="12M", pattern=r"^(1|3|6|12|24|36)M$")
    rolling_window: str = Field(default="3M", pattern=r"^(1|3|6|12|24|36)M$")
    drawdown_window: str = Field(default="36M", pattern=r"^(1|3|6|12|24|36)M$")
    correlation_window: str = Field(default="12M", pattern=r"^(1|3|6|12|24|36)M$")
    beta_windows: tuple[str, ...] = ("12M", "36M")
    #: Daily-return pairs needed for volatility, beta, correlation, Sharpe.
    min_observations: int = Field(default=100, ge=10)
    min_rolling_observations: int = Field(default=30, ge=5)
    min_peers: int = Field(default=2, ge=1)


class LiquidityConfig(BaseModel):
    """Liquidity engine window, minimums, score weights and bucket bounds."""

    model_config = ConfigDict(frozen=True)

    window: str = Field(default="6M", pattern=r"^(1|3|6|12|24|36)M$")
    #: Observations that must report a volume before volume statistics are computed.
    min_volume_observations: int = Field(default=20, ge=1)
    weight_turnover: float = Field(default=0.5, ge=0.0, le=1.0)
    weight_frequency: float = Field(default=0.2, ge=0.0, le=1.0)
    weight_nonzero_volume: float = Field(default=0.2, ge=0.0, le=1.0)
    weight_steadiness: float = Field(default=0.1, ge=0.0, le=1.0)
    #: Lower bounds (0-100) for Highly liquid, Liquid, Moderately liquid, Illiquid.
    bucket_thresholds: tuple[float, float, float, float] = (80.0, 60.0, 40.0, 20.0)


class ValuationConfig(BaseModel):
    """Valuation-multiple and dividend-engine thresholds."""

    model_config = ConfigDict(frozen=True)

    #: Dividend yield at or above which a stock is "high-yield" (and a trap candidate).
    high_yield_threshold: float = Field(default=0.08, ge=0.0, le=1.0)
    #: Payout above this share of earnings is a trap signal.
    payout_trap_threshold: float = Field(default=1.0, ge=0.0)
    #: Fiscal years of dividend history considered.
    dividend_history_years: int = Field(default=5, ge=2)
    #: Years paid without interruption before a payer is "reliable".
    reliable_min_years: int = Field(default=3, ge=1)
    #: Fiscal-year multiples needed before "vs history" is computed.
    min_history_years: int = Field(default=3, ge=1)
    #: Peers with a positive multiple needed for sector/market medians.
    min_peers: int = Field(default=3, ge=1)


class FactorInput(BaseModel):
    """One metric feeding a factor: where it lives, which way is better, how much it counts."""

    model_config = ConfigDict(frozen=True)

    metric: str
    source: Literal["market", "fundamental"]
    #: +1 when a higher value is better, -1 when lower is better.
    direction: Literal[1, -1] = 1
    weight: float = Field(default=1.0, gt=0.0)


class FactorDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    inputs: tuple[FactorInput, ...]


def _default_factors() -> tuple[FactorDefinition, ...]:
    m, f = "market", "fundamental"
    return (
        FactorDefinition(
            name="value",
            inputs=(
                FactorInput(metric="pe", source=f, direction=-1),
                FactorInput(metric="pb", source=f, direction=-1),
                FactorInput(metric="ps", source=f, direction=-1, weight=0.5),
                FactorInput(metric="ev_ebitda", source=f, direction=-1, weight=0.5),
                FactorInput(metric="fcf_yield", source=f, direction=1, weight=0.5),
                FactorInput(metric="dividend_yield", source=f, direction=1, weight=0.5),
            ),
        ),
        FactorDefinition(
            name="quality",
            inputs=(
                FactorInput(metric="roe", source=f),
                FactorInput(metric="roa", source=f, weight=0.5),
                FactorInput(metric="net_margin", source=f),
                FactorInput(metric="operating_margin", source=f, weight=0.5),
                FactorInput(metric="fcf_margin", source=f, weight=0.5),
                FactorInput(metric="debt_to_equity", source=f, direction=-1, weight=0.5),
                FactorInput(metric="roe_trend", source=f, weight=0.5),
            ),
        ),
        FactorDefinition(
            name="growth",
            inputs=(
                FactorInput(metric="revenue_growth_1y", source=f),
                FactorInput(metric="eps_growth_1y", source=f),
                FactorInput(metric="revenue_cagr_3y", source=f),
                FactorInput(metric="eps_cagr_3y", source=f),
                FactorInput(metric="fcf_growth_1y", source=f, weight=0.5),
            ),
        ),
        FactorDefinition(
            name="momentum",
            inputs=(
                FactorInput(metric="momentum_12m_1m", source=m),
                FactorInput(metric="momentum_6m", source=m, weight=0.5),
                FactorInput(metric="relative_12m_vs_market", source=m),
                FactorInput(metric="trend_strength_6m", source=m, weight=0.5),
                FactorInput(metric="price_to_ma_200", source=m, weight=0.5),
                FactorInput(metric="distance_from_52w_high", source=m, weight=0.5),
            ),
        ),
        FactorDefinition(
            name="dividend",
            inputs=(
                FactorInput(metric="dividend_yield", source=f),
                FactorInput(metric="dividend_consistency", source=f),
                FactorInput(metric="dividend_cagr_3y", source=f, weight=0.5),
                FactorInput(metric="fcf_dividend_coverage", source=f, weight=0.5),
                FactorInput(metric="dividend_class", source=f, weight=0.5),
            ),
        ),
        FactorDefinition(
            name="risk",
            inputs=(
                FactorInput(metric="volatility_annualised", source=m, direction=-1),
                FactorInput(metric="max_drawdown_36m", source=m, direction=1),
                FactorInput(metric="beta_12m", source=m, direction=-1, weight=0.5),
                FactorInput(metric="sharpe_12m", source=m, direction=1),
            ),
        ),
        FactorDefinition(
            name="liquidity",
            inputs=(
                FactorInput(metric="liquidity_score", source=m),
                FactorInput(metric="avg_daily_turnover", source=m, weight=0.5),
                FactorInput(metric="trading_frequency", source=m, weight=0.5),
                FactorInput(metric="zero_volume_share", source=m, direction=-1, weight=0.5),
            ),
        ),
    )


class FactorConfig(BaseModel):
    """Factor definitions and cross-sectional normalisation (``analytics/factors``)."""

    model_config = ConfigDict(frozen=True)

    factors: tuple[FactorDefinition, ...] = Field(default_factory=_default_factors)
    #: Winsorisation quantiles applied to every input across the universe.
    winsor_lower: float = Field(default=0.05, ge=0.0, le=0.5)
    winsor_upper: float = Field(default=0.95, ge=0.5, le=1.0)
    #: Share of a factor's input weight that must be known for the factor to be scored.
    min_coverage: float = Field(default=0.5, gt=0.0, le=1.0)
    #: Members needed before a within-group percentile is reported.
    min_group_size: int = Field(default=3, ge=2)


class RankingConfig(BaseModel):
    """The composite factor model: weights, classification bands, gates, detectors.

    Starting assumptions, not conclusions - the backtester exists to test them.
    """

    model_config = ConfigDict(frozen=True)

    model_name: str = "factor-model"
    model_version: str = "1"
    #: factor -> weight; renormalised over the factors that are available per stock.
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "quality": 0.25,
            "value": 0.20,
            "growth": 0.15,
            "momentum": 0.15,
            "risk": 0.10,
            "dividend": 0.10,
            "liquidity": 0.05,
        }
    )
    #: Share of total weight that must be available for an overall score.
    min_weight_available: float = Field(default=0.5, gt=0.0, le=1.0)
    #: Lower bounds of Strong Candidate, Buy Candidate, Watch, Neutral, Weak (else Avoid).
    class_thresholds: tuple[float, float, float, float, float] = (80.0, 65.0, 50.0, 35.0, 20.0)
    #: A liquidity score below this caps the classification at Watch.
    liquidity_gate: float = Field(default=20.0, ge=0.0, le=100.0)
    #: Confidence below this caps the classification at Watch.
    confidence_gate: float = Field(default=0.5, ge=0.0, le=1.0)
    # value-trap detector
    trap_cheap_pe_vs_market: float = Field(default=-0.25, le=0.0)
    trap_cheap_pb: float = Field(default=1.0, gt=0.0)
    trap_cheap_yield: float = Field(default=0.08, ge=0.0)
    trap_momentum: float = Field(default=-0.10, le=0.0)
    trap_liquidity: float = Field(default=40.0, ge=0.0, le=100.0)
    trap_high_signals: int = Field(default=3, ge=1)
    # compounder detector
    compounder_growth: float = Field(default=0.08, ge=0.0)
    compounder_roe: float = Field(default=0.15, ge=0.0)
    compounder_roa: float = Field(default=0.05, ge=0.0)
    compounder_roa_financial: float = Field(default=0.015, ge=0.0)
    compounder_fcf_margin: float = Field(default=0.05, ge=0.0)
    compounder_max_leverage: float = Field(default=1.0, gt=0.0)
    compounder_min_known: float = Field(default=0.6, gt=0.0, le=1.0)


class FairValueConfig(BaseModel):
    """Fair-value engine assumptions. Every number here is an *assumption* and is
    written into the valuation's ``assumptions`` so the reader sees it."""

    model_config = ConfigDict(frozen=True)

    #: Equity risk premium over the risk-free rate (``market.risk_free_rate``); Kenya's
    #: country premium puts it well above developed-market figures.
    equity_risk_premium: float = Field(default=0.07, ge=0.0, le=0.3)
    default_beta: float = Field(default=1.0, gt=0.0)
    beta_floor: float = Field(default=0.5, gt=0.0)
    beta_cap: float = Field(default=1.5, gt=0.0)
    #: A scenario moves the discount rate by this much (bear up, bull down).
    rate_shift: float = Field(default=0.01, ge=0.0)
    # DCF (free cash flow = OCF - capex, treated as cash flow to equity)
    projection_years: int = Field(default=5, ge=1, le=15)
    terminal_growth: float = Field(default=0.05, ge=0.0, le=0.1)
    terminal_growth_bear: float = Field(default=0.03, ge=0.0, le=0.1)
    terminal_growth_bull: float = Field(default=0.06, ge=0.0, le=0.1)
    growth_floor: float = Field(default=-0.05, le=0.0)
    growth_cap: float = Field(default=0.15, ge=0.0)
    growth_shift: float = Field(default=0.05, ge=0.0)
    fcf_average_years: int = Field(default=3, ge=1)
    # justified P/B and dividend discount (financials)
    roe_bear_multiplier: float = Field(default=0.85, gt=0.0, le=1.0)
    roe_bull_multiplier: float = Field(default=1.10, ge=1.0)
    sustainable_growth_cap: float = Field(default=0.10, ge=0.0)
    dividend_growth_cap: float = Field(default=0.10, ge=0.0)
    dividend_growth_shift: float = Field(default=0.02, ge=0.0)
    # relative multiples
    multiple_haircut: float = Field(default=0.20, ge=0.0, lt=1.0)
    min_peers: int = Field(default=3, ge=2)
    # uncertainty score (0-1): additive penalties, clamped
    uncertainty_base: float = Field(default=0.10, ge=0.0, le=1.0)
    uncertainty_single_method: float = Field(default=0.20, ge=0.0, le=1.0)
    uncertainty_thin_history: float = Field(default=0.15, ge=0.0, le=1.0)
    uncertainty_deteriorating: float = Field(default=0.15, ge=0.0, le=1.0)
    uncertainty_illiquid: float = Field(default=0.15, ge=0.0, le=1.0)
    uncertainty_leverage: float = Field(default=0.15, ge=0.0, le=1.0)
    uncertainty_dispersion: float = Field(default=0.15, ge=0.0, le=1.0)
    uncertainty_no_beta: float = Field(default=0.05, ge=0.0, le=1.0)
    min_fiscal_years: int = Field(default=3, ge=1)
    illiquid_score: float = Field(default=40.0, ge=0.0, le=100.0)
    leverage_limit: float = Field(default=1.5, ge=0.0)
    coverage_limit: float = Field(default=2.0, ge=0.0)
    dispersion_limit: float = Field(default=0.5, ge=0.0)
    #: At or above this uncertainty the margin of safety is flagged as not actionable.
    uncertainty_threshold: float = Field(default=0.6, ge=0.0, le=1.0)


class AnalyticsConfig(BaseModel):
    """The whole configuration. Frozen, hashable, versioned."""

    model_config = ConfigDict(frozen=True)

    version: str = CONFIG_VERSION
    fundamentals: FundamentalsConfig = Field(default_factory=FundamentalsConfig)
    market: MarketConfig = Field(default_factory=MarketConfig)
    quality: DataQualityConfig = Field(default_factory=DataQualityConfig)
    momentum: MomentumConfig = Field(default_factory=MomentumConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    liquidity: LiquidityConfig = Field(default_factory=LiquidityConfig)
    valuation: ValuationConfig = Field(default_factory=ValuationConfig)
    factors: FactorConfig = Field(default_factory=FactorConfig)
    ranking: RankingConfig = Field(default_factory=RankingConfig)
    fair_value: FairValueConfig = Field(default_factory=FairValueConfig)

    def canonical_json(self) -> str:
        """Deterministic JSON: sorted keys, no whitespace, so equal configs hash equal."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def config_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


DEFAULT_CONFIG = AnalyticsConfig()

CALC_VERSION_NAME = "analytics"


def register_calc_version(
    session: Session, config: AnalyticsConfig, *, name: str = CALC_VERSION_NAME
) -> CalcVersion:
    """Get-or-create the ``calc_versions`` row for this exact configuration.

    Idempotent on ``(name, config_hash)``: running every job with the same config
    forever creates one row; changing a single number creates a second, and results
    computed under each stay distinguishable.
    """
    digest = config.config_hash()
    existing = session.execute(
        select(CalcVersion).where(CalcVersion.name == name, CalcVersion.config_hash == digest)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = CalcVersion(
        name=name, version=config.version, config_hash=digest, config_json=config.as_dict()
    )
    session.add(row)
    session.flush()
    return row


__all__ = [
    "CALC_VERSION_NAME",
    "CONFIG_VERSION",
    "DEFAULT_CONFIG",
    "AnalyticsConfig",
    "DataQualityConfig",
    "FactorConfig",
    "FactorDefinition",
    "FactorInput",
    "FairValueConfig",
    "FundamentalsConfig",
    "LiquidityConfig",
    "MarketConfig",
    "MomentumConfig",
    "RankingConfig",
    "RiskConfig",
    "ValuationConfig",
    "register_calc_version",
]
