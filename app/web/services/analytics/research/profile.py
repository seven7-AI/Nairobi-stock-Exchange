"""The research profile: every stored number about one instrument, as of a date.

Assembled from the analytics store only (classification, market and fundamental
metrics, factor scores, the ranking with its explanation, valuations, forecasts,
scenarios, simulations, the market regime, the model registry). Every metric is
serialised as its Measure JSON - ``value``, ``status``, ``reason`` - so an absent
number is present as an explanation, never as 0 or a missing key. Nothing here
computes; that is what the jobs are for.

    codegraph explore "build_profile ResearchProfile metric_block latest_dates"
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import (
    Forecast,
    FundamentalMetric,
    MarketMetric,
    ModelRegistryEntry,
    Simulation,
    StockRanking,
    Valuation,
)
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.factor_scores import load_factor_scores
from app.web.db.analytics.services.forecasts import load_forecasts
from app.web.db.analytics.services.fundamental_metrics import load_fundamental_metrics
from app.web.db.analytics.services.market_metrics import load_metrics
from app.web.db.analytics.services.simulations import load_regimes, load_simulations
from app.web.db.analytics.services.stock_rankings import load_rankings
from app.web.db.analytics.services.valuations import load_valuations
from app.web.services.analytics.classification.lookup import ClassificationIndex

DISCLAIMER = "Model outputs from stored, versioned calculations; not investment advice."

#: Which stored metrics make up each block of the profile.
BLOCKS: dict[str, tuple[str, tuple[str, ...]]] = {
    "returns": (
        "market",
        (
            "return_1d",
            "return_1w",
            "return_1m",
            "return_3m",
            "return_6m",
            "return_12m",
            "return_ytd",
            "return_24m",
            "return_36m",
        ),
    ),
    "momentum": (
        "market",
        (
            "momentum_1m",
            "momentum_3m",
            "momentum_6m",
            "momentum_12m",
            "momentum_12m_1m",
            "relative_12m_vs_market",
            "relative_12m_vs_sector",
            "price_to_ma_50",
            "price_to_ma_200",
            "trend_strength_6m",
            "distance_from_52w_high",
        ),
    ),
    "risk": (
        "market",
        (
            "volatility_daily",
            "volatility_annualised",
            "max_drawdown_36m",
            "beta_12m",
            "beta_36m",
            "correlation_market_12m",
            "sharpe_12m",
            "sortino_12m",
        ),
    ),
    "liquidity": (
        "market",
        (
            "avg_daily_volume",
            "avg_daily_turnover",
            "trading_frequency",
            "zero_volume_share",
            "market_cap",
            "liquidity_score",
            "liquidity_bucket",
        ),
    ),
    "quality": (
        "fundamental",
        (
            "roe",
            "roa",
            "net_margin",
            "gross_margin",
            "operating_margin",
            "fcf",
            "fcf_margin",
            "debt_to_equity",
            "interest_coverage",
            "asset_turnover",
            "roe_trend",
            "net_margin_trend",
            "debt_to_equity_trend",
        ),
    ),
    "growth": (
        "fundamental",
        (
            "revenue_growth_1y",
            "eps_growth_1y",
            "net_income_growth_1y",
            "fcf_growth_1y",
            "revenue_cagr_3y",
            "eps_cagr_3y",
            "revenue_cagr_5y",
            "revenue_growth_1y_vs_sector",
        ),
    ),
    "value": (
        "fundamental",
        (
            "price",
            "market_cap",
            "pe",
            "pe_ttm",
            "pb",
            "ps",
            "ev_ebitda",
            "fcf_yield",
            "pe_vs_history",
            "pe_vs_sector",
            "pe_vs_market",
            "pb_vs_sector",
            "pb_vs_market",
        ),
    ),
    "dividend": (
        "fundamental",
        (
            "dividend_yield",
            "dividend_yield_ttm",
            "payout_ratio",
            "dividend_years_paid",
            "dividend_consistency",
            "dividend_cut",
            "fcf_dividend_coverage",
            "dividend_class",
            "dividend_cagr_3y",
        ),
    ),
}


@dataclass(frozen=True)
class ResearchProfile:
    ticker_symbol: str
    as_of: dict[str, str | None]
    identity: dict[str, Any]
    score: dict[str, Any]
    factors: dict[str, Any]
    metrics: dict[str, dict[str, Any]]
    valuation: dict[str, Any]
    forecast: dict[str, Any]
    scenarios: dict[str, Any]
    simulation: dict[str, Any]
    regime: dict[str, Any]
    models: list[dict[str, Any]]
    disclaimer: str = DISCLAIMER
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _measure(row: Any) -> dict[str, Any]:
    return {"value": row.value, "status": row.status, "reason": row.reason}


def _absent(name: str, as_of: date | None) -> dict[str, Any]:
    return {"value": None, "status": "unavailable", "reason": f"{name}: not computed as of {as_of}"}


def metric_block(rows: Iterable[Any], names: tuple[str, ...], as_of: date | None) -> dict[str, Any]:
    by_name = {r.metric: r for r in rows}
    return {n: (_measure(by_name[n]) if n in by_name else _absent(n, as_of)) for n in names}


def latest_for(session: Session, model: Any, ticker: str, upto: date | None) -> date | None:
    stmt = select(func.max(model.as_of_date)).where(model.ticker_symbol == ticker)
    if upto is not None:
        stmt = stmt.where(model.as_of_date <= upto)
    return session.execute(stmt).scalar_one_or_none()


def build_profile(
    settings: Settings, ticker: str, *, as_of: date | None = None
) -> ResearchProfile | None:
    """The profile, or None when the instrument is unknown to the store."""
    symbol = ticker.strip().upper()
    with analytics_session(settings) as session:
        index = ClassificationIndex(load_classifications(session))
        if symbol not in index.tickers:
            return None
        dates = {
            "market_metrics": latest_for(session, MarketMetric, symbol, as_of),
            "fundamental_metrics": latest_for(session, FundamentalMetric, symbol, as_of),
            "ranking": latest_for(session, StockRanking, symbol, as_of),
            "valuation": latest_for(session, Valuation, symbol, as_of),
            "forecast": latest_for(session, Forecast, symbol, as_of),
            "simulation": latest_for(session, Simulation, symbol, as_of),
        }
        reference = as_of or max((d for d in dates.values() if d is not None), default=None)
        assignment = index.sector_for(symbol, reference) if reference else None
        stints = index.history(symbol)
        identity = {
            "ticker_symbol": symbol,
            "sector": assignment.sector_label if assignment else None,
            "sector_code": assignment.sector_code if assignment else None,
            "industry": assignment.industry if assignment else None,
            "classified_from": assignment.valid_from.isoformat() if assignment else None,
            "classification_source": assignment.source if assignment else None,
            "stints": len(stints),
        }
        notes: list[str] = []
        metrics: dict[str, dict[str, Any]] = {}
        market_rows = (
            load_metrics(session, ticker_symbol=symbol, as_of_date=dates["market_metrics"])
            if dates["market_metrics"]
            else []
        )
        fundamental_rows = (
            load_fundamental_metrics(
                session, ticker_symbol=symbol, as_of_date=dates["fundamental_metrics"]
            )
            if dates["fundamental_metrics"]
            else []
        )
        for block, (source, names) in BLOCKS.items():
            rows = market_rows if source == "market" else fundamental_rows
            day = dates["market_metrics"] if source == "market" else dates["fundamental_metrics"]
            metrics[block] = metric_block(rows, names, day)
        if not fundamental_rows:
            notes.append(
                "no fundamental metrics stored: no statements captured for this instrument"
            )

        score: dict[str, Any] = {"status": "unavailable", "reason": "ranking: not computed"}
        factors: dict[str, Any] = {}
        if dates["ranking"]:
            rank = load_rankings(session, as_of_date=dates["ranking"], ticker_symbol=symbol)
            if rank:
                r = rank[-1]
                score = {
                    "as_of": r.as_of_date.isoformat(),
                    "model": f"{r.model_name} v{r.model_version}",
                    "overall": {"value": r.overall_score, "status": r.status, "reason": r.reason},
                    "confidence": r.confidence,
                    "classification": r.classification,
                    "signal": r.classification,
                    "ranks": {
                        "market": r.market_rank,
                        "sector": r.sector_rank,
                        "industry": r.industry_rank,
                    },
                    "value_trap_risk": r.value_trap_risk,
                    "compounder_score": r.compounder_score,
                    "explanation": r.explanation,
                }
            for f in load_factor_scores(session, as_of_date=dates["ranking"], ticker_symbol=symbol):
                factors[f.factor] = {
                    "score": {"value": f.score, "status": f.status, "reason": f.reason},
                    "coverage": f.coverage,
                    "percentile_market": f.percentile_market,
                    "percentile_sector": f.percentile_sector,
                    "percentile_industry": f.percentile_industry,
                    "inputs": f.inputs,
                }

        valuation: dict[str, Any] = {"status": "unavailable", "reason": "fair value: not computed"}
        if dates["valuation"]:
            rows_v = load_valuations(session, as_of_date=dates["valuation"], ticker_symbol=symbol)
            blended = next((v for v in rows_v if v.method == "blended"), None)
            valuation = {
                "as_of": dates["valuation"].isoformat(),
                "intrinsic": {
                    "value": blended.base if blended else None,
                    "status": blended.status if blended else "unavailable",
                    "reason": blended.reason if blended else None,
                },
                "fair_low": blended.fair_low if blended else None,
                "fair_high": blended.fair_high if blended else None,
                "price": blended.price if blended else None,
                "upside": blended.upside if blended else None,
                "margin_of_safety": blended.margin_of_safety if blended else None,
                "uncertainty": blended.uncertainty if blended else None,
                "actionable": blended.actionable if blended else None,
                "methods": {
                    v.method: {
                        "status": v.status,
                        "reason": v.reason,
                        "bear": v.bear,
                        "base": v.base,
                        "bull": v.bull,
                        "assumptions": v.assumptions,
                    }
                    for v in rows_v
                    if v.method != "blended"
                },
            }

        forecast: dict[str, Any] = {"status": "unavailable", "reason": "forecast: not computed"}
        if dates["forecast"]:
            rows_f = load_forecasts(session, as_of_date=dates["forecast"], ticker_symbol=symbol)
            forecast = {"as_of": dates["forecast"].isoformat(), "models": {}}
            for fc in rows_f:
                forecast["models"].setdefault(fc.model, {})[f"{fc.horizon_months}m"] = {
                    "expected_return": {
                        "value": fc.expected_return,
                        "status": fc.status,
                        "reason": fc.reason,
                    },
                    "q05": fc.q05,
                    "q25": fc.q25,
                    "q50": fc.q50,
                    "q75": fc.q75,
                    "q95": fc.q95,
                    "p_positive": fc.p_positive,
                    "p_outperform": fc.p_outperform,
                    "expected_vol": fc.expected_vol,
                    "p_drawdown": fc.p_drawdown,
                }

        scenarios: dict[str, Any] = {"status": "unavailable", "reason": "scenarios: not computed"}
        simulation: dict[str, Any] = {
            "status": "unavailable",
            "reason": "monte carlo: not computed",
        }
        if dates["simulation"]:
            rows_s = load_simulations(session, as_of_date=dates["simulation"], ticker_symbol=symbol)
            scen = [s for s in rows_s if s.method == "scenario"]
            if scen:
                scenarios = {
                    "as_of": dates["simulation"].isoformat(),
                    "outcomes": {
                        s.scenario: {
                            "implied_return": {
                                "value": s.mean_return,
                                "status": s.status,
                                "reason": s.reason,
                            },
                            "implied_price": s.implied_price,
                            "assumptions": s.assumptions,
                        }
                        for s in scen
                    },
                }
            mc = [s for s in rows_s if s.method != "scenario"]
            if mc:
                simulation = {"as_of": dates["simulation"].isoformat(), "paths": {}}
                for s in mc:
                    simulation["paths"].setdefault(s.method, {})[f"{s.horizon_days}d"] = {
                        "mean_return": {
                            "value": s.mean_return,
                            "status": s.status,
                            "reason": s.reason,
                        },
                        "q05": s.q05,
                        "q50": s.q50,
                        "q95": s.q95,
                        "p_positive": s.p_positive,
                        "p_return_above": s.p_return_above,
                        "p_drawdown_above": s.p_drawdown_above,
                        "n_paths": s.n_paths,
                        "seed": s.seed,
                    }

        regime_rows = load_regimes(session, end=reference)
        regime: dict[str, Any] = {"status": "unavailable", "reason": "regime: not computed"}
        if regime_rows:
            g = regime_rows[-1]
            regime = {
                "as_of": g.as_of_date.isoformat(),
                "index": g.index_symbol,
                "label": g.reason,
                "status": g.status,
                "trend": g.trend,
                "volatility": g.volatility,
                "risk": g.risk,
                "weight_overrides": g.weight_overrides,
            }

        models = [
            {"name": m.name, "version": m.version, "kind": str(m.kind), "status": str(m.status)}
            for m in session.execute(
                select(ModelRegistryEntry).order_by(ModelRegistryEntry.name)
            ).scalars()
        ]
    return ResearchProfile(
        symbol,
        {k: (v.isoformat() if v else None) for k, v in dates.items()},
        identity,
        score,
        factors,
        metrics,
        valuation,
        forecast,
        scenarios,
        simulation,
        regime,
        models,
        DISCLAIMER,
        notes,
    )


def render_profile(profile: ResearchProfile) -> str:
    """The §46-style text profile for the CLI: one line per number, with its status."""

    def fmt(value: Any, pattern: str = "{:.4f}") -> str:
        return "-" if value is None else pattern.format(float(value))

    def trap_label(value: Any) -> str:
        return {0: "low", 1: "medium", 2: "high"}.get(int(value), "-") if value is not None else "-"

    def m(block: Mapping[str, Any], key: str, fmt: str = "{:.4f}") -> str:
        item = block.get(key) or {}
        value = item.get("value")
        if value is None:
            return f"{item.get('status', 'unavailable')} ({item.get('reason') or '-'})"
        return fmt.format(value)

    lines = [f"# {profile.ticker_symbol} — research profile", ""]
    lines.append("as of: " + ", ".join(f"{k} {v or '-'}" for k, v in profile.as_of.items()))
    ident = profile.identity
    lines.append(f"sector: {ident.get('sector') or '-'} · industry: {ident.get('industry') or '-'}")
    lines.append("")
    s = profile.score
    if "overall" in s:
        lines += [
            f"score: {m(s, 'overall')} ({s['model']}, confidence {s['confidence']:.2f}) "
            f"→ {s['classification'] or 'unclassified'}",
            f"ranks: market {s['ranks']['market']} · sector {s['ranks']['sector']} · "
            f"industry {s['ranks']['industry']}",
            f"value-trap risk: {trap_label(s['value_trap_risk'])} · compounder: "
            f"{fmt(s['compounder_score'], '{:.1f}')}",
        ]
        ex = s.get("explanation") or {}
        for label in ("positive_factors", "negative_factors"):
            for item in ex.get(label, [])[:6]:
                lines.append(f"  {'+' if label.startswith('pos') else '-'} {item}")
    else:
        lines.append(f"score: {s.get('status')} ({s.get('reason')})")
    lines.append("")
    for block, values in profile.metrics.items():
        lines.append(f"[{block}]")
        for key in values:
            lines.append(f"  {key:28s} {m(values, key)}")
    v = profile.valuation
    lines.append("")
    if "intrinsic" in v:
        lines.append(
            f"[valuation] intrinsic {m(v, 'intrinsic')} range {fmt(v['fair_low'])}.."
            f"{fmt(v['fair_high'])} price {fmt(v['price'], '{:.2f}')} upside "
            f"{fmt(v['upside'], '{:+.1%}')} uncertainty {fmt(v['uncertainty'], '{:.2f}')} "
            f"actionable {v['actionable']}"
        )
        for name, method in v.get("methods", {}).items():
            lines.append(
                f"  {name:12s} {method['status']} base {fmt(method['base'])} "
                f"({method.get('reason') or '-'})"
            )
    else:
        lines.append(f"[valuation] {v.get('status')} ({v.get('reason')})")
    f = profile.forecast
    if "models" in f:
        for model, horizons in f["models"].items():
            parts = [f"{h} {m(hv, 'expected_return', '{:+.2%}')}" for h, hv in horizons.items()]
            lines.append(f"[forecast {model}] " + " · ".join(parts))
    else:
        lines.append(f"[forecast] {f.get('status')} ({f.get('reason')})")
    sc = profile.scenarios
    if "outcomes" in sc:
        lines.append(
            "[scenarios] "
            + " · ".join(
                f"{k} {m(o, 'implied_return', '{:+.1%}')}" for k, o in sc["outcomes"].items()
            )
        )
    else:
        lines.append(f"[scenarios] {sc.get('status')} ({sc.get('reason')})")
    r = profile.regime
    lines.append(
        f"[regime] {r.get('label') or r.get('status')} "
        f"({r.get('index') or r.get('reason')}, {r.get('as_of', '-')})"
    )
    lines.append(
        "[models] "
        + ", ".join(f"{x['name']} v{x['version']} ({x['status']})" for x in profile.models)
    )
    for note in profile.notes:
        lines.append(f"note: {note}")
    lines.append("")
    lines.append(profile.disclaimer)
    return "\n".join(lines)


__all__ = [
    "BLOCKS",
    "DISCLAIMER",
    "ResearchProfile",
    "build_profile",
    "metric_block",
    "render_profile",
]
