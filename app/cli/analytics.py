"""``nse-analysis analytics`` - the quantitative research engine's commands.

Thin wrappers, like the rest of the CLI: every command calls a service in
``app/web/services/analytics`` that the API and the job runner call too.

    codegraph explore "analytics_app upgrade_analytics_db analytics_db_status"
"""

from __future__ import annotations

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


__all__ = ["analytics_app"]
