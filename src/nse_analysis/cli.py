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
    classify_monthly_market_insights,
    classify_weekly_market_insights,
    unavailable_requirements,
)
from nse_analysis.indicators.feasibility import analyze_feasibility, summarize_feasibility
from nse_analysis.indicators.registry import build_indicator_map, parse_indicators
from nse_analysis.reports.generator import (
    write_daily_report,
    write_monthly_report,
    write_weekly_report,
)
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


@app.command("inspect-price-history")
def inspect_price_history(limit: int = typer.Option(5, min=1, max=20)) -> None:
    """Inspect price_history structure from stockanalysis_stocks table."""
    settings, conn = _bootstrap()
    logger = get_logger("nse_analysis.cli.inspect_price_history")
    
    # Fetch sample rows with price_history
    response = conn.execute_with_retry(
        lambda: conn.client.table(settings.stockanalysis_table)
        .select("ticker_symbol, company_name, scraped_at, price_history")
        .order("scraped_at", desc=True)
        .limit(limit)
        .execute(),
        "inspect_price_history",
    )
    rows = list(getattr(response, "data", []))
    
    console.print(f"[cyan]Sample price_history data (showing {len(rows)} rows):[/cyan]\n")
    for row in rows:
        ticker = row.get("ticker_symbol", "N/A")
        company = row.get("company_name", "N/A")
        scraped_at = row.get("scraped_at", "N/A")
        price_history = row.get("price_history", [])
        
        console.print(f"[bold]{ticker}[/bold] - {company}")
        console.print(f"  Scraped At: {scraped_at}")
        console.print(f"  Price History Type: {type(price_history).__name__}")
        if isinstance(price_history, list):
            console.print(f"  Price History Length: {len(price_history)}")
            if price_history:
                console.print(f"  First Entry: {json.dumps(price_history[0], indent=2, default=str)}")
                if len(price_history) > 1:
                    console.print(f"  Last Entry: {json.dumps(price_history[-1], indent=2, default=str)}")
        elif isinstance(price_history, dict):
            console.print(f"  Price History Keys: {list(price_history.keys())}")
            console.print(f"  Sample: {json.dumps(price_history, indent=2, default=str)[:500]}")
        else:
            console.print(f"  Price History Value: {price_history}")
        console.print()
    
    logger.info("price_history_inspected", rows=len(rows))


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
    """Pull daily source data from stockanalysis_stocks table."""
    settings, conn = _bootstrap()
    fetcher = DataFetcher(settings, conn)
    analysis_rows = fetcher.fetch_daily_window()
    console.print(
        f"[green]Pulled rows[/green] stockanalysis_stocks={len(analysis_rows)}"
    )


@app.command("calculate-indicators")
def calculate_indicators(limit: int = typer.Option(100, min=1, max=2000)) -> None:
    """Calculate core market indicators for latest rows."""
    settings, conn = _bootstrap()
    fetcher = DataFetcher(settings, conn)
    analysis_rows = fetcher.fetch_daily_window()
    merged = fetcher.merge_current_data(analysis_rows)[:limit]
    historical = fetcher.load_historical_from_supabase()
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


@app.command("generate-weekly-report")
def generate_weekly_report() -> None:
    """Generate weekly report (typically run on Fridays)."""
    from datetime import timedelta
    
    settings, conn = _bootstrap()
    logger = get_logger("nse_analysis.cli.generate_weekly_report")
    fetcher = DataFetcher(settings, conn)
    
    # Get current date and calculate week range
    now_utc = datetime.now(tz=timezone.utc)
    week_end = now_utc.date()
    week_start = week_end - timedelta(days=6)  # Last 7 days
    
    analysis_rows = fetcher.fetch_daily_window(as_of_utc=now_utc)
    merged_rows = fetcher.merge_current_data(analysis_rows)
    historical = fetcher.load_historical_from_supabase()
    calculated = calculate_batch(merged_rows, historical)
    
    market_summary = classify_weekly_market_insights(calculated)
    
    report_path = write_weekly_report(
        settings=settings,
        market_summary=market_summary,
        indicator_rows=calculated,
        week_start_date=week_start.isoformat(),
        week_end_date=week_end.isoformat(),
    )
    logger.info("weekly_report_generated", report_path=str(report_path))
    console.print(f"[green]Weekly report generated:[/green] {report_path}")


@app.command("generate-monthly-report")
def generate_monthly_report() -> None:
    """Generate monthly report (typically run on last day of month)."""
    from calendar import monthrange
    
    settings, conn = _bootstrap()
    logger = get_logger("nse_analysis.cli.generate_monthly_report")
    fetcher = DataFetcher(settings, conn)
    
    # Get current date
    now_utc = datetime.now(tz=timezone.utc)
    current_month = now_utc.month
    current_year = now_utc.year
    
    analysis_rows = fetcher.fetch_daily_window(as_of_utc=now_utc)
    merged_rows = fetcher.merge_current_data(analysis_rows)
    historical = fetcher.load_historical_from_supabase()
    calculated = calculate_batch(merged_rows, historical)
    
    market_summary = classify_monthly_market_insights(calculated)
    
    report_path = write_monthly_report(
        settings=settings,
        market_summary=market_summary,
        indicator_rows=calculated,
        month=current_month,
        year=current_year,
    )
    logger.info("monthly_report_generated", report_path=str(report_path))
    console.print(f"[green]Monthly report generated:[/green] {report_path}")


def run_daily_pipeline(settings: Any, conn: SupabaseConnection) -> Path:
    """Shared orchestration used by generate-report and run-daily."""
    logger = get_logger("nse_analysis.cli.run_daily")
    fetcher = DataFetcher(settings, conn)
    analysis_rows = fetcher.fetch_daily_window(as_of_utc=datetime.now(tz=timezone.utc))
    merged_rows = fetcher.merge_current_data(analysis_rows)
    validation = validate_merged_rows(merged_rows)
    historical = fetcher.load_historical_from_supabase()
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
