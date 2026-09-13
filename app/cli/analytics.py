"""``nse-analysis analytics`` - the quantitative research engine's commands.

Thin wrappers, like the rest of the CLI: every command calls a service in
``app/web/services/analytics`` that the API and the job runner call too.

    codegraph explore "analytics_app upgrade_analytics_db analytics_db_status"
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from app.web.config import Settings, get_settings
from app.web.services.analytics.store import analytics_db_status, upgrade_analytics_db
from app.web.utils.logger import configure_logging

analytics_app = typer.Typer(help="Quantitative research engine: analytics store, jobs, metrics.")
console = Console()


def _settings() -> Settings:
    settings = get_settings()
    configure_logging(settings.logs_dir / "nse_be.log", settings.log_level)
    return settings


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
    from app.web.services.market_data.sources import NseScraperSource, build_market_data_source

    settings = _settings()
    source = build_market_data_source(settings)
    if not isinstance(source, NseScraperSource):
        raise typer.BadParameter("classify needs the nse_scraper source (instrument master).")
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
    from app.web.services.market_data.sources import NseScraperSource, build_market_data_source

    settings = _settings()
    source = build_market_data_source(settings)
    if not isinstance(source, NseScraperSource):
        raise typer.BadParameter("dq needs the nse_scraper source (canonical timeline).")
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


__all__ = ["analytics_app"]
