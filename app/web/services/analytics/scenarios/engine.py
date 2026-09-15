"""Scenario engine: named what-ifs applied to one stock, assumptions carried verbatim.

Each scenario states a market move, a multiple change and an earnings change. The
stock's implied one-year price is computed two ways and both are reported:

* **beta path** - price x (1 + beta x market return), beta from ``beta_12m`` (default
  when unknown, and said so);
* **fundamental path** - EPS x (1 + earnings growth) x P/E x (1 + multiple change),
  only when the stock has a positive P/E on the date.

The scenario value is the mean of the paths that exist. Nothing here is a forecast:
it is arithmetic on stated assumptions, stored next to the assumptions.

    codegraph explore "scenario_outcomes ScenarioOutcome"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.web.services.analytics.config import AnalyticsConfig, ScenarioAssumptions
from app.web.services.analytics.measure import Measure, Provenance


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    ticker_symbol: str
    scenario: str
    measure: Measure  # implied return under the scenario, or the blocking status
    implied_price: float | None = None
    beta_path_price: float | None = None
    fundamental_path_price: float | None = None
    assumptions: dict[str, Any] = field(default_factory=dict)


def scenario_outcome(
    ticker: str,
    scenario: ScenarioAssumptions,
    *,
    price: float | None,
    beta: float | None,
    eps: float | None,
    pe: float | None,
    config: AnalyticsConfig,
) -> ScenarioOutcome:
    assumptions: dict[str, Any] = {
        **scenario.model_dump(mode="json"),
        "horizon_days": config.scenarios.horizon_days,
        "beta": beta if beta is not None else config.scenarios.default_beta,
        "beta_source": "beta_12m" if beta is not None else "default",
        "eps": eps,
        "pe": pe,
    }
    if price is None or price <= 0:
        return ScenarioOutcome(
            ticker,
            scenario.name,
            Measure.unavailable("scenario: no current price"),
            assumptions=assumptions,
        )
    used_beta = beta if beta is not None else config.scenarios.default_beta
    beta_price = price * (1.0 + used_beta * scenario.market_return)
    fundamental_price: float | None = None
    if eps is not None and pe is not None and eps > 0 and pe > 0:
        fundamental_price = (
            eps * (1.0 + scenario.earnings_growth) * pe * (1.0 + scenario.multiple_change)
        )
    paths = [p for p in (beta_price, fundamental_price) if p is not None]
    implied = sum(paths) / len(paths)
    assumptions["paths_used"] = ["beta"] + (
        ["fundamental"] if fundamental_price is not None else []
    )
    provenance = Provenance(
        table="market_metrics+fundamental_metrics",
        ticker=ticker,
        note=f"{scenario.name}: {scenario.description}",
    )
    implied_return = implied / price - 1.0
    return ScenarioOutcome(
        ticker,
        scenario.name,
        Measure.known(implied_return, provenance)
        if implied_return != 0
        else Measure.zero(provenance),
        implied_price=implied,
        beta_path_price=beta_price,
        fundamental_path_price=fundamental_price,
        assumptions=assumptions,
    )


def scenario_outcomes(
    ticker: str,
    *,
    price: float | None,
    beta: float | None,
    eps: float | None,
    pe: float | None,
    config: AnalyticsConfig,
) -> list[ScenarioOutcome]:
    return [
        scenario_outcome(ticker, s, price=price, beta=beta, eps=eps, pe=pe, config=config)
        for s in config.scenarios.scenarios
    ]


__all__ = ["ScenarioOutcome", "scenario_outcome", "scenario_outcomes"]
