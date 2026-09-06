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

import typer
from rich.console import Console
from rich.table import Table

from app.web.api.routers.market_data.views import MONTHLY_WINDOW, WEEKLY_WINDOW
from app.web.config import Settings, get_settings
from app.web.db.models.enums import ReportKind
from app.web.services.indicators.feasibility import analyze_feasibility, summarize_feasibility
from app.web.services.indicators.registry import build_indicator_map, parse_indicators
from app.web.services.market_data.fetcher import DataFetcher
from app.web.services.market_data.sources import (
    MarketDataSource,
    NseScraperSource,
    build_market_data_source,
)
from app.web.services.reports.pipeline import load_market_data, run_pipeline
from app.web.utils.logger import configure_logging, get_logger

app = typer.Typer(help="NSE Analytics backend CLI")
console = Console()


def _bootstrap() -> tuple[Settings, MarketDataSource]:
    """Settings plus the wired market-data source.

    The source is the ``~/nse-stock-scraper`` project's daily SQLite output; see
    ``app/web/services/market_data/sources/registry.py``.
    """
    settings = get_settings()
    configure_logging(settings.logs_dir / "nse_be.log", settings.log_level)
    return settings, build_market_data_source(settings)


@app.command("inspect-source")
def inspect_source(output_file: Path | None = None) -> None:
    """Inspect the configured NSE market-data source.

    Reports where the data comes from, how fresh it is, whether the scraper's own
    quality gate passed, and how deep each ticker's price history runs - which is
    what decides whether weekly and monthly indicators can be computed at all.
    """
    _settings, source = _bootstrap()
    logger = get_logger("app.cli.inspect_source")
    health = source.health_check()

    console.print(f"[bold cyan]Market data source:[/bold cyan] {health.name}")
    console.print(f"  Location : {health.location}")
    console.print(f"  Status   : {_status_markup(health.status)}")
    console.print(f"  Detail   : {health.detail}")
    if health.newest_scraped_at:
        console.print(
            f"  Newest   : {health.newest_scraped_at.isoformat()} "
            f"({health.age_hours}h ago{', STALE' if health.is_stale else ''})"
        )
    if health.quality_ok is not None:
        verdict = "passed" if health.quality_ok else "[red]FAILED[/red]"
        console.print(f"  Last scrape quality gate: {verdict}")

    if health.tables:
        table = Table(title="Tables")
        table.add_column("Table")
        table.add_column("Rows", justify="right")
        table.add_column("Newest scraped_at")
        for stat in health.tables:
            table.add_row(
                stat.name,
                str(stat.row_count),
                stat.newest_scraped_at.isoformat() if stat.newest_scraped_at else "N/A",
            )
        console.print(table)

    if isinstance(source, NseScraperSource):
        _print_scraper_detail(source)

    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(health.to_dict(), indent=2), encoding="utf-8")
        console.print(f"[green]Source report written:[/green] {output_file}")

    logger.info("source_inspected", source=health.name, status=health.status)


def _status_markup(status: str) -> str:
    colour = {"ok": "green", "stale": "yellow", "degraded": "yellow"}.get(status, "red")
    return f"[{colour}]{status}[/{colour}]"


def _print_scraper_detail(source: NseScraperSource) -> None:
    """Scraper-specific detail: history depth, quality gate, failed writes."""
    depth = source.price_history_depth()
    if depth:
        weekly = sum(count for entries, count in depth.items() if entries >= WEEKLY_WINDOW)
        monthly = sum(count for entries, count in depth.items() if entries >= MONTHLY_WINDOW)
        total = sum(depth.values())
        console.print("\n[bold]Price history depth[/bold] (observations per ticker)")
        console.print(f"  {'entries':>8}  tickers")
        for entries, count in sorted(depth.items()):
            console.print(f"  {entries:>8}  {count}")
        console.print(
            f"  [cyan]{weekly}/{total}[/cyan] tickers support weekly (>={WEEKLY_WINDOW}), "
            f"[cyan]{monthly}/{total}[/cyan] support monthly (>={MONTHLY_WINDOW})"
        )

    gate = source.read_quality_gate()
    if gate:
        console.print("\n[bold]Last run per spider[/bold]")
        for spider, report in sorted(gate.items()):
            ok = "[green]OK[/green]" if report.get("quality_ok") else "[red]FAILED[/red]"
            console.print(
                f"  {spider:24s} {ok}  items={report.get('item_scraped_count')} "
                f"db_ok={report.get('db_upsert_ok')} db_failed={report.get('db_upsert_failed')} "
                f"finished={report.get('finished_at')}"
            )

    dates = source.list_fallback_dates()
    if dates:
        today = source.read_fallback_records()
        console.print(
            f"\n[bold]Failed writes[/bold]: {len(dates)} day(s) with fallback files, "
            f"newest {dates[0]} ({len(today)} record(s) for today)"
        )


@app.command("inspect-price-history")
def inspect_price_history(limit: int = typer.Option(5, min=1, max=20)) -> None:
    """Inspect the price_history structure the source provides."""
    _settings, source = _bootstrap()
    logger = get_logger("app.cli.inspect_price_history")
    rows = source.fetch_latest_rows(limit=limit)

    console.print(f"[cyan]Sample price_history from {source.name} ({len(rows)} rows):[/cyan]\n")
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

    logger.info("price_history_inspected", source=source.name, rows=len(rows))


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
    console.print(f"[cyan]Categories discovered:[/cyan] {len(build_indicator_map(definitions))}")


@app.command("pull-data")
def pull_data() -> None:
    """Pull the latest source rows from the stockanalysis_stocks table."""
    settings, source = _bootstrap()
    rows = DataFetcher(settings, source).fetch_daily_window()
    console.print(f"[green]Pulled rows[/green] source={source.name} rows={len(rows)}")


@app.command("calculate-indicators")
def calculate_indicators(limit: int = typer.Option(100, min=1, max=2000)) -> None:
    """Calculate core market indicators for the latest rows."""
    settings, source = _bootstrap()
    data = load_market_data(settings, source)
    console.print(f"[green]Calculated indicator rows:[/green] {len(data.calculated[:limit])}")


def _generate(kind: ReportKind, label: str) -> None:
    settings, source = _bootstrap()
    logger = get_logger(f"app.cli.generate_{kind.value}")
    result = run_pipeline(kind, settings, source)
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


@app.command("backfill-from-scraper")
def backfill_from_scraper() -> None:
    """Load the scraper's price_history into nse-be's own price_bars table."""
    from app.celery_app.tasks.ingest_tasks import backfill_price_bars_from_scraper as task

    console.print(task())


@app.command("backfill-prices")
def backfill_prices(start_year: int | None = typer.Option(None, min=2007, max=2100)) -> None:
    """Backfill price_bars from the cleaned 18-year canonical archive."""
    from app.celery_app.tasks.ingest_tasks import backfill_price_bars_from_parquet as task

    console.print(task(start_year))


__all__ = ["app"]
