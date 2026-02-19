"""CLI entrypoint for NSE analytics workflows."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from nse_analysis.config import get_settings
from nse_analysis.data.fetcher import DataFetcher
from nse_analysis.data.validator import validate_merged_rows
from nse_analysis.database.connection import SupabaseConnection
from nse_analysis.database.metadata import inspect_all
from nse_analysis.indicators.calculator import (
    calculate_batch,
    classify_market_insights,
    unavailable_requirements,
)
from nse_analysis.indicators.feasibility import analyze_feasibility, summarize_feasibility
from nse_analysis.indicators.registry import build_indicator_map, parse_indicators
from nse_analysis.reports.generator import write_daily_report
from nse_analysis.utils.logger import configure_logging, get_logger

app = typer.Typer(help="Nairobi Stock Exchange analytics pipeline CLI")
console = Console()


def _bootstrap() -> tuple[Any, SupabaseConnection]:
    settings = get_settings()
    configure_logging(settings.logs_dir / "nse_analysis.log", settings.log_level)
    conn = SupabaseConnection(settings)
    return settings, conn


@app.command("inspect-metadata")
def inspect_metadata(output_file: Path | None = None) -> None:
    """Inspect Supabase table metadata and sample JSON structures."""
    settings, conn = _bootstrap()
    logger = get_logger("nse_analysis.cli.inspect_metadata")
    metadata = inspect_all(settings, conn)
    payload = json.dumps(metadata, indent=2, default=str)
    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(payload, encoding="utf-8")
        console.print(f"[green]Metadata report written:[/green] {output_file}")
    else:
        console.print(payload)
    logger.info("metadata_inspected", output_file=str(output_file) if output_file else None)


@app.command("check-feasibility")
def check_feasibility() -> None:
    """Analyze which indicators are calculable with current data."""
    settings, _ = _bootstrap()
    indicators = parse_indicators(settings.indicators_file)
    records = analyze_feasibility(indicators)
    summary = summarize_feasibility(records)
    table = Table(title="Indicator Feasibility")
    table.add_column("Status")
    table.add_column("Count", justify="right")
    table.add_row("Calculable", str(summary.get("calculable", 0)))
    table.add_row("Partially Calculable", str(summary.get("partially_calculable", 0)))
    table.add_row("Not Calculable", str(summary.get("not_calculable", 0)))
    console.print(table)

    grouped = build_indicator_map(indicators)
    console.print(f"[cyan]Categories discovered:[/cyan] {len(grouped)}")


@app.command("pull-data")
def pull_data() -> None:
    """Pull daily source data from both Supabase tables."""
    settings, conn = _bootstrap()
    fetcher = DataFetcher(settings, conn)
    stock_rows, analysis_rows = fetcher.fetch_daily_window()
    console.print(
        f"[green]Pulled rows[/green] stock_data={len(stock_rows)} stockanalysis_stocks={len(analysis_rows)}"
    )


@app.command("calculate-indicators")
def calculate_indicators(limit: int = typer.Option(100, min=1, max=2000)) -> None:
    """Calculate core market indicators for latest merged rows."""
    settings, conn = _bootstrap()
    fetcher = DataFetcher(settings, conn)
    stock_rows, analysis_rows = fetcher.fetch_daily_window()
    merged = fetcher.merge_current_data(stock_rows, analysis_rows)[:limit]
    historical = fetcher.load_historical_csv()
    calculations = calculate_batch(merged, historical)
    console.print(f"[green]Calculated indicator rows:[/green] {len(calculations)}")


@app.command("generate-report")
def generate_report() -> None:
    """Generate a markdown report using current data and indicators."""
    settings, conn = _bootstrap()
    report_path = run_daily_pipeline(settings, conn)
    console.print(f"[green]Report generated:[/green] {report_path}")


@app.command("run-daily")
def run_daily() -> None:
    """Run full daily pipeline: pull, validate, calculate, report."""
    settings, conn = _bootstrap()
    report_path = run_daily_pipeline(settings, conn)
    console.print(f"[green]Daily pipeline completed:[/green] {report_path}")


def run_daily_pipeline(settings: Any, conn: SupabaseConnection) -> Path:
    """Shared orchestration used by generate-report and run-daily."""
    logger = get_logger("nse_analysis.cli.run_daily")
    fetcher = DataFetcher(settings, conn)
    stock_rows, analysis_rows = fetcher.fetch_daily_window(as_of_utc=datetime.now(tz=timezone.utc))
    merged_rows = fetcher.merge_current_data(stock_rows, analysis_rows)
    validation = validate_merged_rows(merged_rows)
    historical = fetcher.load_historical_csv()
    calculated = calculate_batch(merged_rows, historical)

    indicators = parse_indicators(settings.indicators_file)
    feasibility_records = analyze_feasibility(indicators)
    feasibility_summary = summarize_feasibility(feasibility_records)
    missing_requirements = unavailable_requirements(feasibility_records)
    market_summary = classify_market_insights(calculated)

    report_path = write_daily_report(
        settings=settings,
        market_summary=market_summary,
        indicator_rows=calculated,
        feasibility_summary=feasibility_summary,
        not_calculable=missing_requirements,
        data_quality=validation.model_dump(),
    )
    logger.info(
        "daily_pipeline_done",
        report_path=str(report_path),
        merged_rows=len(merged_rows),
        calculated_rows=len(calculated),
    )
    return report_path
