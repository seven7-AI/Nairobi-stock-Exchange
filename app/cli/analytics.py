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


__all__ = ["analytics_app"]
