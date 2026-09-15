"""The pipelines: which services run, in what order, reading what.

``daily`` (after the scrape): data quality → returns → momentum → risk → liquidity →
valuation multiples → factors → rankings → fair value → scenarios.
``fundamentals`` (when statements change): fundamentals → valuation multiples →
factors → rankings → fair value.
``weekly``: regime → forecasts → forecast evaluation → Monte Carlo → factors →
rankings. Forecast evaluation always runs: it acts on time passing.

    codegraph explore "PIPELINES daily_steps Step run_pipeline"
"""

from __future__ import annotations

from app.web.services.jobs.runner import JobContext, Step, StepBody, StepOutcome


def _dq(ctx: JobContext) -> StepOutcome:
    from app.web.services.analytics.quality.runner import run_data_quality

    result = run_data_quality(ctx.settings, ctx.source, ctx.config)
    return StepOutcome(
        result.reconciled.created,
        {
            "findings": len(result.findings),
            "by_severity": result.counts_by_severity,
            "resolved": result.reconciled.resolved,
        },
    )


def _compute(name: str) -> StepBody:
    """A step body over one of the ``compute`` services, by name."""

    def body(ctx: JobContext) -> StepOutcome:
        from app.web.services.analytics import (
            factors,
            fair_value,
            fundamentals,
            liquidity,
            momentum,
            montecarlo,
            ranking,
            returns,
            risk,
            scenarios,
            valuation_metrics,
        )

        if name == "returns":
            r = returns.compute_returns(
                ctx.settings, ctx.source, as_of=ctx.as_of, config=ctx.config
            )
        elif name == "momentum":
            r = momentum.compute_momentum(
                ctx.settings, ctx.source, as_of=ctx.as_of, config=ctx.config
            )
        elif name == "risk":
            r = risk.compute_risk(
                ctx.settings,
                ctx.source,
                as_of=ctx.as_of,
                config=ctx.config,
                with_correlation_matrix=True,
            )
        elif name == "liquidity":
            r = liquidity.compute_liquidity(
                ctx.settings, ctx.source, as_of=ctx.as_of, config=ctx.config
            )
        elif name == "fundamentals":
            r = fundamentals.compute_fundamentals(
                ctx.settings, ctx.source, as_of=ctx.as_of, config=ctx.config
            )
        elif name == "valuation_metrics":
            r = valuation_metrics.compute_valuation_metrics(
                ctx.settings, ctx.source, as_of=ctx.as_of, config=ctx.config
            )
        elif name == "fair_value":
            r = fair_value.compute_fair_value(
                ctx.settings, ctx.source, as_of=ctx.as_of, config=ctx.config
            )
        elif name == "scenarios":
            r = scenarios.compute_scenarios(
                ctx.settings, ctx.source, as_of=ctx.as_of, config=ctx.config
            )
        elif name == "montecarlo":
            r = montecarlo.compute_montecarlo(
                ctx.settings, ctx.source, as_of=ctx.as_of, config=ctx.config
            )
        elif name == "factors":
            f = factors.compute_factors(ctx.settings, as_of=ctx.as_of, config=ctx.config)
            return StepOutcome(
                f.rows_written, {"universe": len(f.universe), "known": f.known_counts}
            )
        elif name == "rankings":
            k = ranking.compute_rankings(ctx.settings, as_of=ctx.as_of, config=ctx.config)
            return StepOutcome(k.rows_written, {"scored": k.scored, "classes": k.classes})
        else:  # pragma: no cover - a typo in the pipeline definition
            raise ValueError(f"unknown compute step {name!r}")
        return StepOutcome(
            r.rows_written,
            {
                "processed": len(r.tickers_processed),
                "skipped": len(r.tickers_skipped),
                "known": dict(list(r.known_counts.items())[:12]),
            },
        )

    return body


def _regime(ctx: JobContext) -> StepOutcome:
    from app.web.services.analytics.regime import compute_regime

    r = compute_regime(ctx.settings, ctx.source, as_of=ctx.as_of, config=ctx.config)
    return StepOutcome(r.rows_written, {"labels": r.labels})


def _forecasts(ctx: JobContext) -> StepOutcome:
    from app.web.services.analytics.forecasting import compute_forecasts

    r = compute_forecasts(ctx.settings, ctx.source, as_of=ctx.as_of, config=ctx.config)
    return StepOutcome(r.rows_written, {"universe": len(r.tickers), "known": r.known_counts})


def _evaluate_forecasts(ctx: JobContext) -> StepOutcome:
    from app.web.services.analytics.forecasting import evaluate_forecasts

    r = evaluate_forecasts(ctx.settings, ctx.source, as_of=ctx.as_of, config=ctx.config)
    return StepOutcome(
        r.evaluated, {"pending": r.pending, "skipped": r.skipped, "admitted": list(r.admitted)}
    )


MARKET = ("observations",)
FUNDAMENTAL = ("observations", "statements", "snapshots")

DAILY: tuple[Step, ...] = (
    Step("data_quality", _dq, MARKET),
    Step("returns", _compute("returns"), MARKET),
    Step("momentum", _compute("momentum"), MARKET, ("returns",)),
    Step("risk", _compute("risk"), MARKET, ("returns",)),
    Step("liquidity", _compute("liquidity"), ("observations", "snapshots"), ("returns",)),
    Step("valuation_metrics", _compute("valuation_metrics"), FUNDAMENTAL),
    Step(
        "factors",
        _compute("factors"),
        FUNDAMENTAL,
        ("momentum", "risk", "liquidity", "valuation_metrics"),
    ),
    Step("rankings", _compute("rankings"), FUNDAMENTAL, ("factors",)),
    Step(
        "fair_value",
        _compute("fair_value"),
        FUNDAMENTAL,
        ("risk", "liquidity", "valuation_metrics"),
    ),
    Step("scenarios", _compute("scenarios"), FUNDAMENTAL, ("risk", "valuation_metrics")),
)

FUNDAMENTALS: tuple[Step, ...] = (
    Step("fundamentals", _compute("fundamentals"), ("statements",)),
    Step("valuation_metrics", _compute("valuation_metrics"), FUNDAMENTAL, ("fundamentals",)),
    Step("factors", _compute("factors"), FUNDAMENTAL, ("fundamentals", "valuation_metrics")),
    Step("rankings", _compute("rankings"), FUNDAMENTAL, ("factors",)),
    Step("fair_value", _compute("fair_value"), FUNDAMENTAL, ("fundamentals", "valuation_metrics")),
)

WEEKLY: tuple[Step, ...] = (
    Step("regime", _regime, MARKET),
    Step("forecasts", _forecasts, MARKET),
    Step("forecast_evaluation", _evaluate_forecasts, MARKET, ("forecasts",), always_run=True),
    Step("montecarlo", _compute("montecarlo"), MARKET),
    Step("factors", _compute("factors"), FUNDAMENTAL),
    Step("rankings", _compute("rankings"), FUNDAMENTAL, ("factors",)),
)

PIPELINES: dict[str, tuple[Step, ...]] = {
    "daily": DAILY,
    "fundamentals": FUNDAMENTALS,
    "weekly": WEEKLY,
}

__all__ = ["DAILY", "FUNDAMENTALS", "PIPELINES", "WEEKLY"]
