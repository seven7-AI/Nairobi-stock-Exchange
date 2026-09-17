"""Forecasts for the dashboard: every model x horizon cell with its quantiles and
probabilities, the scenario and Monte Carlo rows when one ticker is asked for, the
regime, and the models' walk-forward accuracy from the registry.

Never a single "target price": the cells carry ranges and probabilities, and the
payload says plainly when the latest date is all ``unavailable`` and which earlier date
still has known forecasts.

    codegraph explore "build_forecasts Forecasts load_forecasts load_simulations load_regimes"
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from sqlalchemy import select

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import Forecast, ModelRegistryEntry, Simulation
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.forecasts import load_forecasts
from app.web.db.analytics.services.simulations import load_regimes, load_simulations
from app.web.db.analytics.services.summaries import latest_as_of, latest_known_as_of
from app.web.services.analytics.classification.lookup import ClassificationIndex
from app.web.services.dashboard.common import measure, unavailable
from app.web.services.market_data.sources.nse_scraper import NseScraperSource

DISCLAIMER = (
    "Ranges and probabilities are stored outputs of statistical models fitted to past "
    "returns; they are not price targets and not investment advice."
)


@dataclass(frozen=True)
class TickerForecasts:
    ticker_symbol: str
    sector: str | None
    as_of: date
    price: float | None
    models: dict[str, dict[str, dict[str, Any]]]
    scenarios: dict[str, Any] | None
    simulation: dict[str, Any] | None


@dataclass(frozen=True)
class Forecasts:
    as_of: date
    availability: dict[str, Any]
    latest_known_as_of: date | None
    available_dates: list[date]
    tickers: list[str]
    items: list[TickerForecasts]
    accuracy: dict[str, dict[str, dict[str, Any]]]
    regime: dict[str, Any]
    models: list[dict[str, Any]]
    disclaimer: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _cell(f: Forecast) -> dict[str, Any]:
    return {
        "expected_return": measure(f.expected_return, str(f.status), f.reason),
        "q05": f.q05,
        "q25": f.q25,
        "q50": f.q50,
        "q75": f.q75,
        "q95": f.q95,
        "p_positive": f.p_positive,
        "p_outperform": f.p_outperform,
        "expected_vol": f.expected_vol,
        "p_drawdown": f.p_drawdown,
        "drawdown_threshold": f.drawdown_threshold,
        "benchmark": f.benchmark,
    }


def _scenario_block(rows: list[Simulation]) -> dict[str, Any] | None:
    scen = [s for s in rows if s.method == "scenario"]
    if not scen:
        return None
    return {
        "as_of": scen[0].as_of_date,
        "price": scen[0].price,
        "outcomes": {
            s.scenario: {
                "implied_return": measure(s.mean_return, str(s.status), s.reason),
                "implied_price": s.implied_price,
                "assumptions": s.assumptions or {},
            }
            for s in scen
        },
    }


def _simulation_block(rows: list[Simulation]) -> dict[str, Any] | None:
    mc = [s for s in rows if s.method != "scenario"]
    if not mc:
        return None
    paths: dict[str, dict[str, dict[str, Any]]] = {}
    for s in mc:
        paths.setdefault(s.method, {})[f"{s.horizon_days}d"] = {
            "mean_return": measure(s.mean_return, str(s.status), s.reason),
            "q05": s.q05,
            "q25": s.q25,
            "q50": s.q50,
            "q75": s.q75,
            "q95": s.q95,
            "p_positive": s.p_positive,
            "p_return_above": s.p_return_above,
            "p_drawdown_above": s.p_drawdown_above,
            "expected_max_drawdown": s.expected_max_drawdown,
            "n_paths": s.n_paths,
        }
    return {"as_of": mc[0].as_of_date, "price": mc[0].price, "paths": paths}


def regime_block(session: Any, *, end: date | None) -> dict[str, Any]:
    """The latest stored regime up to ``end`` (same shape the research profile uses)."""
    rows = load_regimes(session, end=end)
    if not rows:
        return {"status": "unavailable", "reason": "regime: not computed"}
    g = rows[-1]
    return {
        "as_of": g.as_of_date,
        "index": g.index_symbol,
        "label": g.reason if g.status == "known" else None,
        "status": g.status,
        "reason": g.reason,
        "trend": g.trend,
        "volatility": g.volatility,
        "risk": g.risk,
        "risk_score": g.risk_score,
        "evidence": g.evidence or {},
        "weight_overrides": g.weight_overrides or {},
    }


def forecast_dates(session: Any) -> list[date]:
    rows = session.execute(
        select(Forecast.as_of_date).distinct().order_by(Forecast.as_of_date.desc()).limit(200)
    ).scalars()
    return list(rows)


def _last_close(source: NseScraperSource, symbol: str, day: date) -> float | None:
    """The close on or before ``day`` - what a quantile return is applied to."""
    from datetime import timedelta

    rows = source.fetch_observations(symbol, start=day - timedelta(days=45), end=day, limit=100)
    for o in reversed(rows):
        close = o.get("close_price")
        if close is not None and float(close) > 0:
            return float(close)
    return None


def build_forecasts(
    settings: Settings,
    source: NseScraperSource,
    *,
    as_of: date | None = None,
    ticker: str | None = None,
    model: str | None = None,
    horizon: int | None = None,
) -> Forecasts | None:
    symbol = ticker.strip().upper() if ticker else None
    with analytics_session(settings) as session:
        day = as_of or latest_as_of(session, Forecast)
        if day is None:
            return None
        index = ClassificationIndex(load_classifications(session))
        rows = load_forecasts(
            session, as_of_date=day, ticker_symbol=symbol, model=model, horizon_months=horizon
        )
        grouped: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        for f in rows:
            grouped.setdefault(f.ticker_symbol, {}).setdefault(f.model, {})[
                f"{f.horizon_months}m"
            ] = _cell(f)
        # the price the quantiles apply to - looked up only for one ticker (one query)
        prices: dict[str, float | None] = {}
        if symbol and symbol in grouped:
            prices[symbol] = _last_close(source, symbol, day)
        known = sum(1 for f in rows if f.status in ("known", "zero"))
        if known:
            availability = measure(None, "known", None)
            if known < len(rows):
                availability["reason"] = f"{known} of {len(rows)} cells known on {day}"
        else:
            reasons = Counter(f.reason for f in rows if f.reason)
            top = reasons.most_common(1)[0][0] if reasons else f"no forecast rows on {day}"
            availability = unavailable(str(top))
        sim_rows: dict[str, list[Simulation]] = {}
        if symbol:
            sim_day = latest_as_of(session, Simulation)
            if sim_day:
                sim_rows[symbol] = load_simulations(
                    session, ticker_symbol=symbol, as_of_date=sim_day
                )
        items = [
            TickerForecasts(
                t,
                (a.sector_label if (a := index.sector_for(t, day)) else None),
                day,
                prices.get(t),
                grouped[t],
                _scenario_block(sim_rows.get(t, [])),
                _simulation_block(sim_rows.get(t, [])),
            )
            for t in sorted(grouped)
        ]
        registry = list(
            session.execute(
                select(ModelRegistryEntry).order_by(
                    ModelRegistryEntry.name, ModelRegistryEntry.version
                )
            ).scalars()
        )
        accuracy: dict[str, dict[str, dict[str, Any]]] = {}
        for m in registry:
            if str(m.kind) != "forecast" or not m.performance:
                continue
            accuracy[m.name] = {
                str(h): {
                    "n": int(p.get("n") or 0),
                    "mae": measure(
                        p.get("mae"),
                        "known" if p.get("mae") is not None else "unavailable",
                        None if p.get("mae") is not None else "no matured forecasts",
                    ),
                    "rmse": measure(
                        p.get("rmse"), "known" if p.get("rmse") is not None else "unavailable", None
                    ),
                    "directional_accuracy": measure(
                        p.get("directional_accuracy"),
                        "known" if p.get("directional_accuracy") is not None else "unavailable",
                        None,
                    ),
                    "benchmark_hit_rate": measure(
                        p.get("benchmark_hit_rate"),
                        "known" if p.get("benchmark_hit_rate") is not None else "unavailable",
                        None,
                    ),
                    "interval_coverage": measure(
                        p.get("interval_coverage"),
                        "known" if p.get("interval_coverage") is not None else "unavailable",
                        None,
                    ),
                }
                for h, p in (m.performance or {}).items()
                if isinstance(p, dict)
            }
        latest_known = latest_known_as_of(session, Forecast, ticker_symbol=symbol)
        availability["latest_known_as_of"] = latest_known
        return Forecasts(
            day,
            availability,
            latest_known,
            forecast_dates(session),
            sorted(grouped),
            items,
            accuracy,
            regime_block(session, end=day),
            [
                {"name": m.name, "version": m.version, "kind": str(m.kind), "status": str(m.status)}
                for m in registry
            ],
            DISCLAIMER,
        )


__all__ = ["DISCLAIMER", "Forecasts", "TickerForecasts", "build_forecasts", "regime_block"]
