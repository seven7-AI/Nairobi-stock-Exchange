"""CLI entry point for NSE analytics workflows.

**A thin wrapper, not a second implementation.** Every command here calls the
same business services the HTTP routers and Celery tasks call. Logic reachable
from ``nse-analysis`` but not from the API is in the wrong place — move it into
``app/web/services/`` and have both call it.

The console script name is unchanged (``nse-analysis``), so the scheduled
report workflows and the scheduler scripts keep working.

    codegraph explore "app/cli/main.py run_pipeline load_market_data"
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from app.web.config import Settings, get_settings
from app.web.db.models.enums import ReportKind
from app.web.db.services.metadata_service import inspect_all
from app.web.services.indicators.feasibility import analyze_feasibility, summarize_feasibility
from app.web.services.indicators.registry import build_indicator_map, parse_indicators
from app.web.services.market_data.fetcher import DataFetcher
from app.web.services.market_data.supabase_client import SupabaseConnection
from app.web.services.reports.pipeline import load_market_data, run_pipeline
from app.web.utils.logger import configure_logging, get_logger

app = typer.Typer(help="NSE Analytics backend CLI")
console = Console()


def _bootstrap() -> tuple[Settings, SupabaseConnection]:
    settings = get_settings()
    configure_logging(settings.logs_dir / "nse_be.log", settings.log_level)
    return settings, SupabaseConnection(settings)


@app.command("inspect-metadata")
def inspect_metadata(output_file: Path | None = None) -> None:
    """Inspect Supabase table metadata and sample JSON structures."""
    settings, conn = _bootstrap()
    logger = get_logger("app.cli.inspect_metadata")
    payload = json.dumps(inspect_all(settings, conn), indent=2, default=str)
    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(payload, encoding="utf-8")
        console.print(f"[green]Metadata report written:[/green] {output_file}")
    else:
        console.print(payload)
    logger.info("metadata_inspected", output_file=str(output_file) if output_file else None)


@app.command("inspect-price-history")
def inspect_price_history(limit: int = typer.Option(5, min=1, max=20)) -> None:
    """Inspect the price_history structure in the stockanalysis_stocks table."""
    settings, conn = _bootstrap()
    logger = get_logger("app.cli.inspect_price_history")

    response = conn.execute_with_retry(
        lambda: conn.client.table(settings.stockanalysis_table)
        .select("ticker_symbol, company_name, scraped_at, price_history")
        .order("scraped_at", desc=True)
        .limit(limit)
        .execute(),
        "inspect_price_history",
    )
    rows: list[dict[str, Any]] = list(getattr(response, "data", []))

    console.print(f"[cyan]Sample price_history data ({len(rows)} rows):[/cyan]\n")
    for row in rows:
        history = row.get("price_history")
        console.print(f"[bold]{row.get('ticker_symbol', 'N/A')}[/bold] - {row.get('company_name')}")
        console.print(f"  Scraped At: {row.get('scraped_at')}")
        console.print(f"  Type: {type(history).__name__}")
        if isinstance(history, list):
            console.print(f"  Length: {len(history)}")
            if history:
                console.print(f"  First: {json.dumps(history[0], default=str)[:300]}")
                console.print(f"  Last:  {json.dumps(history[-1], default=str)[:300]}")
        elif isinstance(history, dict):
            console.print(f"  Keys: {list(history)}")
        console.print()

    logger.info("price_history_inspected", rows=len(rows))


@app.command("check-feasibility")
def check_feasibility() -> None:
    """Analyze which catalogued indicators are calculable with current data."""
    settings = get_settings()
    definitions = parse_indicators(settings.indicators_file)
    summary = summarize_feasibility(analyze_feasibility(definitions))

    table = Table(title="Indicator Feasibility")
    table.add_column("Status")
    table.add_column("Count", justify="right")
    table.add_row("Calculable", str(summary.get("calculable", 0)))
    table.add_row("Partially Calculable", str(summary.get("partially_calculable", 0)))
    table.add_row("Not Calculable", str(summary.get("not_calculable", 0)))
    console.print(table)
    console.print(
        f"[cyan]Categories discovered:[/cyan] {len(build_indicator_map(definitions))}"
    )


@app.command("pull-data")
def pull_data() -> None:
    """Pull the latest source rows from the stockanalysis_stocks table."""
    settings, conn = _bootstrap()
    rows = DataFetcher(settings, conn).fetch_daily_window()
    console.print(f"[green]Pulled rows[/green] {settings.stockanalysis_table}={len(rows)}")


@app.command("calculate-indicators")
def calculate_indicators(limit: int = typer.Option(100, min=1, max=2000)) -> None:
    """Calculate core market indicators for the latest rows."""
    settings, conn = _bootstrap()
    data = load_market_data(settings, conn)
    console.print(f"[green]Calculated indicator rows:[/green] {len(data.calculated[:limit])}")


def _generate(kind: ReportKind, label: str) -> None:
    settings, conn = _bootstrap()
    logger = get_logger(f"app.cli.generate_{kind.value}")
    result = run_pipeline(kind, settings, conn)
    logger.info(
        f"{kind.value}_report_generated",
        report_path=str(result.report_path),
        instruments=result.instruments_analyzed,
    )
    console.print(f"[green]{label} generated:[/green] {result.report_path}")
    console.print(
        f"  ranked: {result.market_summary.get('ranked_instruments', 0)}"
        f"  excluded (no change data): {result.market_summary.get('excluded_missing_change', 0)}"
    )


@app.command("generate-report")
def generate_report() -> None:
    """Generate the daily markdown report."""
    _generate(ReportKind.DAILY, "Report")


@app.command("run-daily")
def run_daily() -> None:
    """Run the full daily pipeline: pull, validate, calculate, report."""
    _generate(ReportKind.DAILY, "Daily pipeline")


@app.command("generate-weekly-report")
def generate_weekly_report() -> None:
    """Generate the weekly report (typically run on Fridays)."""
    _generate(ReportKind.WEEKLY, "Weekly report")


@app.command("generate-monthly-report")
def generate_monthly_report() -> None:
    """Generate the monthly report (typically run on the last day of the month)."""
    _generate(ReportKind.MONTHLY, "Monthly report")


@app.command("seed-instruments")
def seed_instruments() -> None:
    """Seed the instrument master from research/data/ticker_master.parquet."""
    from app.celery_app.tasks.ingest_tasks import seed_instruments as task

    console.print(task())


@app.command("backfill-prices")
def backfill_prices(start_year: int | None = typer.Option(None, min=2007, max=2100)) -> None:
    """Backfill price_bars from the cleaned 18-year canonical archive."""
    from app.celery_app.tasks.ingest_tasks import backfill_price_bars_from_parquet as task

    console.print(task(start_year))


__all__ = ["app"]
