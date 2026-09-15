"""``nse-analysis analytics`` - the quantitative research engine's commands.

Thin wrappers, like the rest of the CLI: every command calls a service in
``app/web/services/analytics`` that the API and the job runner call too.

    codegraph explore "analytics_app upgrade_analytics_db analytics_db_status"
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import typer
from rich.console import Console
from rich.table import Table

from app.web.config import Settings, get_settings
from app.web.services.analytics.returns.service import ComputeResult
from app.web.services.analytics.store import analytics_db_status, upgrade_analytics_db
from app.web.services.market_data.sources import NseScraperSource, build_market_data_source
from app.web.utils.logger import configure_logging

analytics_app = typer.Typer(help="Quantitative research engine: analytics store, jobs, metrics.")
console = Console()


def _settings() -> Settings:
    settings = get_settings()
    configure_logging(settings.logs_dir / "nse_be.log", settings.log_level)
    return settings


def _scraper_source() -> tuple[Settings, NseScraperSource]:
    settings = _settings()
    source = build_market_data_source(settings)
    if not isinstance(source, NseScraperSource):
        raise typer.BadParameter("this command needs the nse_scraper source (canonical timeline).")
    return settings, source


@analytics_app.command("upgrade")
def upgrade() -> None:
    """Create or migrate the analytics store to the latest schema (idempotent)."""
    settings = _settings()
    before = analytics_db_status(settings.analytics_db_path)
    revision = upgrade_analytics_db(settings.analytics_db_path)
    if before.exists and before.current_revision == revision:
        console.print(f"analytics store already at {revision}: {settings.analytics_db_path}")
        return
    console.print(
        f"analytics store {'created' if not before.exists else 'migrated'} "
        f"{before.current_revision or 'nothing'} -> {revision}: {settings.analytics_db_path}"
    )


@analytics_app.command("status")
def status() -> None:
    """Show the store's location, schema revision and row counts."""
    settings = _settings()
    report = analytics_db_status(settings.analytics_db_path)

    table = Table(title="Analytics store")
    table.add_column("Property")
    table.add_column("Value")
    table.add_row("path", str(report.path))
    table.add_row("exists", "yes" if report.exists else "no")
    table.add_row("revision", report.current_revision or "-")
    table.add_row("head", report.head_revision or "-")
    table.add_row("up to date", "yes" if report.is_current else "no - run `analytics upgrade`")
    for name, count in report.tables.items():
        table.add_row(f"rows: {name}", f"{count:,}")
    console.print(table)
    if not report.is_current:
        raise typer.Exit(code=1)


@analytics_app.command("classify")
def classify() -> None:
    """Rebuild the point-in-time sector/industry classification of every instrument."""
    from app.web.services.analytics.classification.service import classify_instruments

    settings, source = _scraper_source()
    result = classify_instruments(settings, source)
    console.print(
        f"classifications rebuilt: {result.rows_written} rows for {result.tickers} instruments"
    )
    for line in result.skipped_rows:
        console.print(f"  skipped sector-file row: {line}")
    if result.unclassified:
        console.print(f"  [red]unclassified: {', '.join(result.unclassified)}[/red]")
        raise typer.Exit(code=1)


@analytics_app.command("dq")
def data_quality(
    fail_on: str = typer.Option(
        "error",
        "--fail-on",
        help="Exit 1 when findings of this severity or worse exist: error|warning|never",
    ),
) -> None:
    """Run the data-quality checks, record findings, write reports/data_quality/."""
    from app.web.services.analytics.quality import run_data_quality

    settings, source = _scraper_source()
    report = run_data_quality(settings, source)

    table = Table(title=f"Data quality — {report.instruments} instruments")
    table.add_column("Check")
    table.add_column("Findings", justify="right")
    for check, count in sorted(report.counts_by_check.items()):
        table.add_row(check, str(count))
    info = report.counts_by_severity.get("info", 0)
    table.add_row(
        "[bold]errors / warnings / info[/bold]", f"{report.errors} / {report.warnings} / {info}"
    )
    console.print(table)
    console.print(
        f"new {report.reconciled.created} · still open {report.reconciled.still_open} · "
        f"resolved {report.reconciled.resolved} · report {report.report_path}"
    )
    threshold = fail_on.strip().lower()
    if threshold == "error" and report.errors:
        raise typer.Exit(code=1)
    if threshold == "warning" and (report.errors or report.warnings):
        raise typer.Exit(code=1)


compute_app = typer.Typer(help="Compute market and fundamental metrics into the analytics store.")
analytics_app.add_typer(compute_app, name="compute")


def _parse_day(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(f"--as-of must be YYYY-MM-DD, got {value!r}") from exc


@compute_app.command("returns")
def compute_returns_command(
    as_of: str | None = typer.Option(
        None, "--as-of", help="Evaluation date (YYYY-MM-DD); default today"
    ),
    ticker: list[str] | None = typer.Option(None, "--ticker", help="Restrict to these tickers"),
) -> None:
    """Trailing 1D..36M, YTD and YoY returns for every instrument as of a date."""
    from app.web.services.analytics.returns import compute_returns

    settings, source = _scraper_source()
    _print_compute(
        compute_returns(settings, source, as_of=_parse_day(as_of), tickers=ticker or None)
    )


def _print_compute(result: ComputeResult) -> None:
    table = Table(
        title=f"{result.job_name} as of {result.as_of} (calc version {result.calc_version_id})"
    )
    table.add_column("Metric")
    table.add_column("Known / processed", justify="right")
    for metric, count in sorted(result.known_counts.items()):
        table.add_row(metric, f"{count} / {len(result.tickers_processed)}")
    console.print(table)
    console.print(
        f"rows written {result.rows_written} · instruments {len(result.tickers_processed)} · "
        f"skipped {len(result.tickers_skipped)}"
    )


@compute_app.command("momentum")
def compute_momentum_command(
    as_of: str | None = typer.Option(None, "--as-of", help="Evaluation date (YYYY-MM-DD)"),
    ticker: list[str] | None = typer.Option(None, "--ticker", help="Restrict to these tickers"),
) -> None:
    """Momentum: 1M..24M, 12-1, relative vs market and sector, MAs, trend, 52-week range."""
    from app.web.services.analytics.momentum import compute_momentum

    settings, source = _scraper_source()
    _print_compute(
        compute_momentum(settings, source, as_of=_parse_day(as_of), tickers=ticker or None)
    )


@compute_app.command("risk")
def compute_risk_command(
    as_of: str | None = typer.Option(None, "--as-of", help="Evaluation date (YYYY-MM-DD)"),
    ticker: list[str] | None = typer.Option(None, "--ticker", help="Restrict to these tickers"),
    no_matrix: bool = typer.Option(
        False, "--no-matrix", help="Skip the stock-to-stock correlation matrix"
    ),
) -> None:
    """Risk: volatility, drawdown, beta, correlations, Sharpe/Sortino (+ correlation matrix)."""
    from app.web.services.analytics.risk import compute_risk

    settings, source = _scraper_source()
    _print_compute(
        compute_risk(
            settings,
            source,
            as_of=_parse_day(as_of),
            tickers=ticker or None,
            with_correlation_matrix=not no_matrix,
        )
    )


@compute_app.command("liquidity")
def compute_liquidity_command(
    as_of: str | None = typer.Option(None, "--as-of", help="Evaluation date (YYYY-MM-DD)"),
    ticker: list[str] | None = typer.Option(None, "--ticker", help="Restrict to these tickers"),
) -> None:
    """Liquidity: volume, turnover, trading frequency, zero-volume days, score and bucket."""
    from app.web.services.analytics.liquidity import compute_liquidity

    settings, source = _scraper_source()
    _print_compute(
        compute_liquidity(settings, source, as_of=_parse_day(as_of), tickers=ticker or None)
    )


@compute_app.command("fundamentals")
def compute_fundamentals_command(
    as_of: str | None = typer.Option(None, "--as-of", help="Evaluation date (YYYY-MM-DD)"),
    ticker: list[str] | None = typer.Option(None, "--ticker", help="Restrict to these tickers"),
) -> None:
    """Fundamentals: ROE/ROA/margins/cash flow/leverage, trends, growth and CAGRs."""
    from app.web.services.analytics.fundamentals import compute_fundamentals

    settings, source = _scraper_source()
    _print_compute(
        compute_fundamentals(settings, source, as_of=_parse_day(as_of), tickers=ticker or None)
    )


@compute_app.command("valuation-metrics")
def compute_valuation_metrics_command(
    as_of: str | None = typer.Option(None, "--as-of", help="Evaluation date (YYYY-MM-DD)"),
    ticker: list[str] | None = typer.Option(None, "--ticker", help="Restrict to these tickers"),
) -> None:
    """Valuation multiples (P/E, P/B, P/S, EV/EBITDA, yields), history/sector/market
    relatives and the dividend classification."""
    from app.web.services.analytics.valuation_metrics import compute_valuation_metrics

    settings, source = _scraper_source()
    _print_compute(
        compute_valuation_metrics(settings, source, as_of=_parse_day(as_of), tickers=ticker or None)
    )


@compute_app.command("factors")
def compute_factors_command(
    as_of: str | None = typer.Option(None, "--as-of", help="Evaluation date (YYYY-MM-DD)"),
) -> None:
    """Factor z-scores and market/sector/industry percentiles from the stored metrics."""
    from app.web.services.analytics.factors import compute_factors

    settings = _settings()
    result = compute_factors(settings, as_of=_parse_day(as_of))
    table = Table(title=f"factors as of {result.as_of} (calc version {result.calc_version_id})")
    table.add_column("Factor")
    table.add_column("Known / universe", justify="right")
    for factor, count in sorted(result.known_counts.items()):
        table.add_row(factor, f"{count} / {len(result.universe)}")
    console.print(table)
    console.print(f"rows written {result.rows_written} · universe {len(result.universe)}")


@compute_app.command("fair-value")
def compute_fair_value_command(
    as_of: str | None = typer.Option(None, "--as-of", help="Evaluation date (YYYY-MM-DD)"),
    ticker: list[str] | None = typer.Option(None, "--ticker", help="Restrict to these tickers"),
) -> None:
    """Per-method fair values (justified P/B, DDM, DCF, EV/EBITDA, P/E) and the blend."""
    from app.web.services.analytics.fair_value import compute_fair_value

    settings, source = _scraper_source()
    result = compute_fair_value(settings, source, as_of=_parse_day(as_of), tickers=ticker or None)
    _print_compute(result)


@compute_app.command("montecarlo")
def compute_montecarlo_command(
    as_of: str | None = typer.Option(None, "--as-of", help="Origin date (YYYY-MM-DD)"),
    ticker: list[str] | None = typer.Option(None, "--ticker", help="Restrict to these tickers"),
) -> None:
    """Seeded bootstrap price paths: return quantiles, P(return > x), P(drawdown > x)."""
    from app.web.services.analytics.montecarlo import compute_montecarlo

    settings, source = _scraper_source()
    result = compute_montecarlo(settings, source, as_of=_parse_day(as_of), tickers=ticker or None)
    _print_compute(result)


@compute_app.command("scenarios")
def compute_scenarios_command(
    as_of: str | None = typer.Option(None, "--as-of", help="Origin date (YYYY-MM-DD)"),
    ticker: list[str] | None = typer.Option(None, "--ticker", help="Restrict to these tickers"),
) -> None:
    """Bear / base / bull what-ifs per stock with their assumptions stored verbatim."""
    from app.web.services.analytics.scenarios import compute_scenarios

    settings, source = _scraper_source()
    result = compute_scenarios(settings, source, as_of=_parse_day(as_of), tickers=ticker or None)
    _print_compute(result)


@compute_app.command("regime")
def compute_regime_command(
    as_of: str | None = typer.Option(None, "--as-of", help="One date (YYYY-MM-DD)"),
    start: str | None = typer.Option(None, "--from", help="First of a monthly series of dates"),
    end: str | None = typer.Option(None, "--to", help="Last date of the series"),
) -> None:
    """Market regime on the benchmark index: trend, volatility, risk-on/off, evidence."""
    from app.web.services.analytics.regime import compute_regime

    settings, source = _scraper_source()
    result = compute_regime(
        settings, source, as_of=_parse_day(as_of), start=_parse_day(start), end=_parse_day(end)
    )
    table = Table(title=f"regime on {result.index} (calc version {result.calc_version_id})")
    table.add_column("Label")
    table.add_column("Dates", justify="right")
    for label, count in sorted(result.labels.items(), key=lambda item: -item[1]):
        table.add_row(label, str(count))
    console.print(table)
    if len(result.regimes) == 1:
        console.print_json(data=result.regimes[0].evidence)
    console.print(f"rows written {result.rows_written}")


@compute_app.command("rankings")
def compute_rankings_command(
    as_of: str | None = typer.Option(None, "--as-of", help="Evaluation date (YYYY-MM-DD)"),
) -> None:
    """Composite score, classification, value-trap and compounder flags from factor scores."""
    from app.web.services.analytics.ranking import compute_rankings

    settings = _settings()
    result = compute_rankings(settings, as_of=_parse_day(as_of))
    table = Table(title=f"rankings as of {result.as_of} (calc version {result.calc_version_id})")
    table.add_column("Class")
    table.add_column("Count", justify="right")
    for label, count in sorted(result.classes.items(), key=lambda item: -item[1]):
        table.add_row(label, str(count))
    console.print(table)
    console.print(
        f"rows written {result.rows_written} · scored {result.scored} / {len(result.universe)}"
    )


@analytics_app.command("rank")
def rank_command(
    as_of: str | None = typer.Option(None, "--as-of", help="Ranking date (default: latest)"),
    top: int = typer.Option(20, "--top", min=1, help="How many to show"),
    ticker: str | None = typer.Option(None, "--ticker", help="Show one instrument's explanation"),
) -> None:
    """Show the stored ranking table for a date, or one instrument's explanation."""
    import json

    from sqlalchemy import func, select

    from app.web.db.analytics import analytics_session
    from app.web.db.analytics.models import StockRanking
    from app.web.db.analytics.services.stock_rankings import load_rankings

    settings = _settings()
    with analytics_session(settings) as session:
        day = (
            _parse_day(as_of)
            or session.execute(select(func.max(StockRanking.as_of_date))).scalar_one_or_none()
        )
        if day is None:
            console.print("no rankings stored yet - run `analytics compute rankings` first")
            raise typer.Exit(code=1)
        if ticker is not None:
            rows = load_rankings(session, as_of_date=day, ticker_symbol=ticker)
            if not rows:
                console.print(f"no ranking for {ticker.upper()} as of {day}")
                raise typer.Exit(code=1)
            console.print_json(json.dumps(rows[-1].explanation))
            return
        rows = load_rankings(session, as_of_date=day, limit=top)
        table = Table(title=f"ranking as of {day} ({rows[0].model_name if rows else ''})")
        for column in ("#", "Ticker", "Overall", "Conf", "Class", "Trap", "Compounder"):
            table.add_column(
                column, justify="right" if column not in ("Ticker", "Class") else "left"
            )
        trap_names = {0: "low", 1: "medium", 2: "high"}
        for row in rows:
            table.add_row(
                str(row.market_rank or "-"),
                row.ticker_symbol,
                f"{row.overall_score:.1f}" if row.overall_score is not None else row.status,
                f"{row.confidence:.2f}",
                row.classification or "-",
                trap_names.get(row.value_trap_risk, "-")
                if row.value_trap_risk is not None
                else "n/a",
                f"{row.compounder_score:.0f}" if row.compounder_score is not None else "n/a",
            )
        console.print(table)


@compute_app.command("forecasts")
def compute_forecasts_command(
    as_of: str | None = typer.Option(None, "--as-of", help="Origin date (YYYY-MM-DD)"),
    ticker: list[str] | None = typer.Option(None, "--ticker", help="Restrict to these tickers"),
) -> None:
    """Return-forecast baselines (naive, mean, EWMA, AR(1)) per horizon for every stock."""
    from app.web.services.analytics.forecasting import compute_forecasts

    settings, source = _scraper_source()
    result = compute_forecasts(settings, source, as_of=_parse_day(as_of), tickers=ticker or None)
    table = Table(title=f"forecasts as of {result.as_of} (calc version {result.calc_version_id})")
    table.add_column("Model")
    table.add_column("Known forecasts", justify="right")
    for model, count in sorted(result.known_counts.items()):
        table.add_row(model, str(count))
    console.print(table)
    console.print(
        f"rows written {result.rows_written} · universe {len(result.tickers)} "
        f"· skipped {len(result.skipped)}"
    )


def _print_model_summary(summary: dict[str, dict[str, object]], admitted: tuple[str, ...]) -> None:
    table = Table(title="out-of-sample summary per model and horizon")
    for column in ("Model", "Horizon", "n", "MAE", "RMSE", "Dir. acc.", "Bench. hit", "90% cov."):
        table.add_column(column, justify="right" if column not in ("Model", "Horizon") else "left")

    def fmt(stats: dict[str, object], key: str) -> str:
        value = stats.get(key)
        return "-" if value is None else f"{float(str(value)):.3f}"

    for model, horizons in summary.items():
        for horizon, stats in horizons.items():
            s = stats if isinstance(stats, dict) else {}
            table.add_row(
                model,
                horizon,
                str(s.get("n", 0)),
                fmt(s, "mae"),
                fmt(s, "rmse"),
                fmt(s, "directional_accuracy"),
                fmt(s, "benchmark_hit_rate"),
                fmt(s, "interval_coverage"),
            )
    console.print(table)
    console.print("admitted candidates: " + (", ".join(admitted) if admitted else "none"))


forecast_app = typer.Typer(help="Evaluate stored forecasts and run walk-forward tests.")
analytics_app.add_typer(forecast_app, name="forecast")


@forecast_app.command("evaluate")
def evaluate_forecasts_command(
    as_of: str | None = typer.Option(
        None, "--as-of", help="Evaluate what has elapsed by this date"
    ),
    ticker: list[str] | None = typer.Option(None, "--ticker", help="Restrict to these tickers"),
) -> None:
    """Score every forecast whose horizon has elapsed; summarise and gate the models."""
    from app.web.services.analytics.forecasting import evaluate_forecasts

    settings, source = _scraper_source()
    result = evaluate_forecasts(settings, source, as_of=_parse_day(as_of), tickers=ticker or None)
    _print_model_summary(result.summary, result.admitted)
    console.print(
        f"evaluated {result.evaluated} · pending {result.pending} · skipped {result.skipped}"
    )


@forecast_app.command("walk-forward")
def walk_forward_command(
    ticker: list[str] = typer.Option(..., "--ticker", help="Tickers to test"),
    start: str = typer.Option(..., "--from", help="First origin (YYYY-MM-DD)"),
    end: str = typer.Option(..., "--to", help="Last origin / evaluation date (YYYY-MM-DD)"),
) -> None:
    """Forecast at monthly origins, each seeing only its past, then evaluate and summarise."""
    from app.web.services.analytics.forecasting import walk_forward

    settings, source = _scraper_source()
    first, last = _parse_day(start), _parse_day(end)
    assert first is not None and last is not None
    result = walk_forward(settings, source, tickers=ticker, start=first, end=last)
    _print_model_summary(result.summary, result.admitted)
    console.print(
        f"evaluated {result.evaluated} · pending {result.pending} · skipped {result.skipped}"
    )


portfolio_app = typer.Typer(help="Risk analysis of hypothetical portfolios.")
analytics_app.add_typer(portfolio_app, name="portfolio")


@portfolio_app.command("analyse")
def portfolio_analyse_command(
    weights: str = typer.Option(..., "--weights", help="TICKER=WEIGHT,... summing to 1"),
    as_of: str | None = typer.Option(None, "--as-of", help="Analysis date (YYYY-MM-DD)"),
    name: str = typer.Option("adhoc", "--name", help="Label stored with the analysis"),
) -> None:
    """Expected return, risk, exposure, concentration, liquidity and warnings for weights."""
    from app.web.services.analytics.portfolio import (
        WeightError,
        analyse_hypothetical_portfolio,
        parse_weights,
    )

    settings, source = _scraper_source()
    try:
        parsed = parse_weights(weights)
        result = analyse_hypothetical_portfolio(
            settings, source, parsed, name=name, as_of=_parse_day(as_of)
        )
    except WeightError as exc:
        raise typer.BadParameter(str(exc)) from exc
    a = result.analysis
    table = Table(title=f"portfolio '{result.name}' as of {result.as_of} (row {result.row_id})")
    table.add_column("Metric")
    table.add_column("Value", justify="right")

    def show(label: str, measure: object) -> None:
        value = getattr(measure, "value", None)
        status = getattr(measure, "status", None)
        text = f"{value:.4f}" if value is not None else str(getattr(status, "value", status))
        table.add_row(label, text)

    show("expected return (hist., ann.)", a.expected_return)
    show("volatility (ann.)", a.volatility)
    show("Sharpe", a.sharpe)
    show("max drawdown", a.max_drawdown)
    show("beta", a.beta)
    show("avg pairwise correlation", a.average_correlation)
    table.add_row("HHI / effective positions", f"{a.hhi:.3f} / {a.effective_positions:.2f}")
    table.add_row("top-N weight", f"{a.top_n_weight:.2f}")
    table.add_row("coverage", f"{a.coverage:.0%}")
    console.print(table)
    console.print(
        "sector exposure: " + ", ".join(f"{k} {v:.0%}" for k, v in a.sector_exposure.items())
    )
    console.print(
        "days to liquidate: "
        + ", ".join(
            f"{k} {v:.1f}" if v is not None else f"{k} n/a" for k, v in a.days_to_liquidate.items()
        )
    )
    for warning in a.warnings:
        console.print(f"[yellow]warning[/yellow] {warning}")
    if not a.expected_return.is_known:
        console.print(f"[red]{a.expected_return.reason}[/red]")


backtest_app = typer.Typer(help="Historical simulation of the ranking model.")
analytics_app.add_typer(backtest_app, name="backtest")


def _print_backtest(result: object) -> None:
    import json

    headline = result.headline()  # type: ignore[attr-defined]
    for block in headline["segments"]:
        table = Table(title=f"segment {block['segment']}: {block['start']} -> {block['end']}")
        table.add_column("Series")
        for column in ("total_return", "cagr", "volatility", "sharpe", "max_drawdown"):
            table.add_column(column, justify="right")
        for series, metrics in block.items():
            if not isinstance(metrics, dict):
                continue
            table.add_row(
                series,
                *(
                    str(metrics.get(c, "-"))
                    for c in ("total_return", "cagr", "volatility", "sharpe", "max_drawdown")
                ),
            )
        console.print(table)
        portfolio = block.get("portfolio", {})
        console.print(
            "alpha vs ^NASI: "
            f"{portfolio.get('alpha_vs_^NASI', '-')} "
            f"(t {portfolio.get('alpha_t_stat_vs_^NASI', '-')}), "
            f"beta {portfolio.get('beta_vs_^NASI', '-')}, "
            f"avg monthly turnover {portfolio.get('avg_monthly_turnover', '-')}"
        )
    console.print(
        "linked: " + json.dumps({k: v.get("value") for k, v in headline["linked"].items()})
    )


@backtest_app.command("run")
def backtest_run_command(
    start: str = typer.Option(..., "--from", help="First date (YYYY-MM-DD)"),
    end: str = typer.Option(..., "--to", help="Last date (YYYY-MM-DD)"),
    top_n: int | None = typer.Option(None, "--top-n", help="Positions per rebalance"),
    name: str = typer.Option("factor-model", "--name", help="Run label"),
    market_only: bool = typer.Option(
        False, "--market-only", help="Control variant: momentum / risk / liquidity weights only"
    ),
) -> None:
    """Monthly top-N rebalance of the ranking model, costed, vs ^NASI, ^N20I, equal weight."""
    from app.web.services.analytics.backtesting import market_only_ranking, run_model_backtest
    from app.web.services.analytics.config import DEFAULT_CONFIG

    settings, source = _scraper_source()
    first, last = _parse_day(start), _parse_day(end)
    assert first is not None and last is not None
    config = market_only_ranking(DEFAULT_CONFIG) if market_only else DEFAULT_CONFIG
    result = run_model_backtest(
        settings, source, start=first, end=last, name=name, config=config, top_n=top_n
    )
    console.print(f"run {result.run_id} '{result.name}' {result.start} -> {result.end}")
    for note in result.result.notes:
        console.print(f"[yellow]note[/yellow] {note}")
    _print_backtest(result)


@backtest_app.command("compare")
def backtest_compare_command(
    name: str | None = typer.Option(None, "--name", help="Only runs with this label"),
) -> None:
    """List stored runs with their linked total return and first-segment Sharpe."""
    from app.web.db.analytics import analytics_session
    from app.web.db.analytics.services.backtests import load_backtest_results, load_backtest_runs

    settings = _settings()
    table = Table(title="backtest runs")
    for column in (
        "id",
        "name",
        "purpose",
        "period",
        "top N",
        "cost rate",
        "linked return",
        "CAGR",
        "Sharpe (seg 1)",
        "MDD (seg 1)",
    ):
        table.add_column(
            column, justify="right" if column not in ("name", "purpose", "period") else "left"
        )

    def cell(results: dict[tuple[str, str, str], object], segment: str, metric: str) -> str:
        row = results.get((segment, "portfolio", metric))
        value = getattr(row, "value", None)
        return "-" if value is None else f"{float(value):.4f}"

    lines: list[str] = []
    with analytics_session(settings) as session:
        for run in load_backtest_runs(session, name=name):
            results: dict[tuple[str, str, str], object] = {
                (r.segment, r.series, r.metric): r for r in load_backtest_results(session, run.id)
            }
            table.add_row(
                str(run.id),
                run.name,
                run.purpose,
                f"{run.start_date}..{run.end_date}",
                str(run.top_n),
                f"{run.costs.get('rate', 0.0):.4f}",
                cell(results, "linked", "total_return"),
                cell(results, "linked", "cagr"),
                cell(results, "1", "sharpe"),
                cell(results, "1", "max_drawdown"),
            )
            lines.append(
                f"{run.id} {run.name} ({run.purpose}) {run.start_date}..{run.end_date} "
                f"linked return {cell(results, 'linked', 'total_return')}"
            )
    console.print(table)
    for line in lines:
        console.print(line, soft_wrap=True)


@backtest_app.command("weight-search")
def backtest_weight_search_command(
    start: str = typer.Option(..., "--from", help="In-sample start (YYYY-MM-DD)"),
    split: str = typer.Option(..., "--split", help="Out-of-sample start (YYYY-MM-DD)"),
    end: str = typer.Option(..., "--to", help="Out-of-sample end (YYYY-MM-DD)"),
    candidate: list[str] = typer.Option(
        ..., "--candidate", help="name=factor:weight,factor:weight,... (repeatable)"
    ),
    top_n: int | None = typer.Option(None, "--top-n", help="Positions per rebalance"),
) -> None:
    """Try weight sets in-sample, pick by Sharpe, report them out-of-sample."""
    from app.web.services.analytics.backtesting import weight_search

    settings, source = _scraper_source()
    candidates: dict[str, dict[str, float]] = {}
    for item in candidate:
        if "=" not in item:
            raise typer.BadParameter(f"expected name=factor:weight,..., got {item!r}")
        label, spec = item.split("=", 1)
        weights: dict[str, float] = {}
        for pair in spec.split(","):
            factor, _, weight = pair.partition(":")
            try:
                weights[factor.strip()] = float(weight)
            except ValueError as exc:
                raise typer.BadParameter(f"{label}: weight {weight!r} is not a number") from exc
        candidates[label.strip()] = weights
    first, mid, last = _parse_day(start), _parse_day(split), _parse_day(end)
    assert first is not None and mid is not None and last is not None
    result = weight_search(
        settings, source, candidates=candidates, start=first, split=mid, end=last, top_n=top_n
    )
    table = Table(title="weight search: in-sample pick, out-of-sample report")
    for column in (
        "candidate",
        "IS return",
        "IS Sharpe",
        "IS MDD",
        "OOS return",
        "OOS Sharpe",
        "OOS MDD",
        "runs",
    ):
        table.add_column(column, justify="right" if column != "candidate" else "left")

    def fmt(block: Mapping[str, object], key: str) -> str:
        measure = block.get(key)
        value = getattr(measure, "value", None)
        return "-" if value is None else f"{float(value):.4f}"

    for label in candidates:
        i, o = result.in_sample[label], result.out_of_sample[label]
        table.add_row(
            label + (" *" if label == result.best_in_sample else ""),
            fmt(i, "total_return"),
            fmt(i, "sharpe"),
            fmt(i, "max_drawdown"),
            fmt(o, "total_return"),
            fmt(o, "sharpe"),
            fmt(o, "max_drawdown"),
            "/".join(str(r) for r in result.run_ids[label]),
        )
    console.print(table)
    console.print("* = best in-sample Sharpe; judge it by the out-of-sample columns")


__all__ = ["analytics_app"]
