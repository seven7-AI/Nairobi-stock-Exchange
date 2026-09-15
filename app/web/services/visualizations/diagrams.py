"""Regenerate the research diagram folders from the analytics store and the prices.

codegraph explore "plot_kinds DIAGRAM_KINDS write_volatility write_backtest"
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig
from app.web.services.analytics.returns.service import load_universe
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.services.visualizations.common import DIAGRAM_KINDS
from app.web.services.visualizations.momentum import write_momentum
from app.web.services.visualizations.research_charts import (
    write_all_backtests,
    write_all_portfolios,
    write_backtest,
    write_forecast,
    write_portfolio,
    write_ranking,
    write_sector,
    write_valuation,
)
from app.web.services.visualizations.volatility import write_volatility

PER_STOCK = ("volatility", "momentum", "forecasts")


def plot_kinds(
    settings: Settings,
    source: NseScraperSource,
    kind: str,
    *,
    diagrams_dir: Path,
    tickers: list[str] | None = None,
    all_tickers: bool = False,
    as_of: date | None = None,
    run_id: int | None = None,
    name: str | None = None,
    config: AnalyticsConfig = DEFAULT_CONFIG,
) -> list[Path]:
    kinds = list(DIAGRAM_KINDS) if kind == "all" else [kind]
    unknown = [k for k in kinds if k not in DIAGRAM_KINDS]
    if unknown:
        raise ValueError(
            f"unknown diagram kind {unknown[0]!r}; expected one of "
            f"{', '.join(DIAGRAM_KINDS)} or all"
        )
    written: list[Path] = []
    needs_prices = any(k in PER_STOCK for k in kinds)
    universe = load_universe(source, config) if needs_prices else {}
    if needs_prices:
        wanted = [t for t in universe if not t.startswith("^")]
        if tickers and not all_tickers:
            requested = {t.strip().upper() for t in tickers}
            wanted = [t for t in wanted if t in requested]
        elif not all_tickers and kind != "all":
            raise ValueError("per-stock charts need --ticker or --all")
        # `plot all` without --ticker regenerates every instrument
    benchmark = universe.get(config.market.benchmark_index)
    with analytics_session(settings) as session:
        for k in kinds:
            if k == "volatility":
                written += [
                    write_volatility(universe[t], diagrams_dir)
                    for t in wanted
                    if not universe[t].is_empty
                ]
            elif k == "momentum":
                if benchmark is not None:
                    written += [
                        write_momentum(universe[t], benchmark, diagrams_dir)
                        for t in wanted
                        if not universe[t].is_empty
                    ]
            elif k == "forecasts":
                written += [
                    write_forecast(session, universe[t], diagrams_dir, as_of=as_of)
                    for t in wanted
                    if not universe[t].is_empty
                ]
            elif k == "sector-analysis":
                written.append(write_sector(session, diagrams_dir, as_of=as_of))
            elif k == "factor-ranking":
                written.append(write_ranking(session, diagrams_dir, as_of=as_of))
            elif k == "valuation":
                written.append(write_valuation(session, diagrams_dir, as_of=as_of))
            elif k == "backtests":
                if run_id is None and name is None:
                    written += write_all_backtests(session, diagrams_dir)
                else:
                    written.append(write_backtest(session, diagrams_dir, run_id=run_id, name=name))
            elif k == "portfolio-risk":
                if name is None:
                    written += write_all_portfolios(session, diagrams_dir)
                else:
                    written.append(write_portfolio(session, diagrams_dir, name=name))
    return written


__all__ = ["PER_STOCK", "plot_kinds"]
