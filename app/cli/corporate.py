"""``nse-analysis corporate`` - the corporate expansion & geographic intelligence layer.

Thin wrappers over ``app/web/services/corporate``; the job runner and the dashboard
call the same services. Commands arrive with the layer: universe, collect,
extract, structure, validate, review, macro, events, status, metrics.

    codegraph explore "corporate_app CorporateConfig detect_capabilities"
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from app.cli.analytics import _scraper_source, _settings
from app.web.services.corporate.config import DEFAULT_CORPORATE_CONFIG
from app.web.services.corporate.extract.capabilities import detect_capabilities

corporate_app = typer.Typer(help="Corporate structure, geographic footprint and expansion facts.")
universe_app = typer.Typer(help="The canonical company universe.")
corporate_app.add_typer(universe_app, name="universe")
entities_app = typer.Typer(help="Legal entities and their identifiers.")
corporate_app.add_typer(entities_app, name="entities")
gleif_app = typer.Typer(help="GLEIF LEI enrichment.")
corporate_app.add_typer(gleif_app, name="gleif")
documents_app = typer.Typer(help="Collected documents.")
corporate_app.add_typer(documents_app, name="documents")
sources_app = typer.Typer(help="Document sources and their health.")
corporate_app.add_typer(sources_app, name="sources")
console = Console()


@corporate_app.command("config")
def show_config() -> None:
    """Print the corporate thresholds and their hash (separate from the analytics hash)."""
    config = DEFAULT_CORPORATE_CONFIG
    digest = config.config_hash()[:16]
    console.print(f"[bold]corporate config[/bold] v{config.version}  hash {digest}")
    table = Table(show_header=True)
    table.add_column("threshold")
    table.add_column("value", justify="right")
    for key, value in sorted(config.as_dict().items()):
        if key != "version":
            table.add_row(key, str(value))
    console.print(table)


@corporate_app.command("capabilities")
def capabilities() -> None:
    """Which extraction stages this box can run, and why the others cannot."""
    settings = _settings()
    caps = detect_capabilities(
        ocr_enabled=settings.corporate_ocr_enabled,
        llm_cleanup_enabled=settings.corporate_llm_cleanup_enabled,
    )
    table = Table(title="extraction stages")
    table.add_column("stage")
    table.add_column("available")
    table.add_column("why not")
    for stage, (available, why) in caps.stages().items():
        table.add_row(stage, "[green]yes[/green]" if available else "[yellow]no[/yellow]", why)
    console.print(table)
    console.print(f"documents: {settings.corporate_documents_dir}")
    console.print(f"cache:     {settings.corporate_cache_dir}")


@universe_app.command("build")
def universe_build(
    no_network: bool = typer.Option(
        False, "--no-network", help="Skip the NSE listed-companies page; use stored sightings."
    ),
) -> None:
    """Rebuild corporate_companies from the scraper, the NSE page and stored sightings."""
    from app.web.services.corporate.universe.service import refresh_universe

    settings, source = _scraper_source()
    result = refresh_universe(settings, source, network=not no_network)
    console.print(
        f"[green]universe:[/green] {result.companies} companies - "
        f"created {result.created}, updated {result.updated}, unchanged {result.unchanged}; "
        f"sightings recorded {result.sightings_recorded}; page: {result.page}"
    )
    for ticker, (before, after) in sorted(result.status_changes.items()):
        console.print(f"  {ticker:7s} {before or '-'} -> {after}")
    for line in result.unmatched_listings:
        console.print(f"  [yellow]unmatched[/yellow] {line}")
    for warning in result.warnings:
        console.print(f"  [yellow]warning[/yellow] {warning}")


@universe_app.command("show")
def universe_show(
    ticker: str | None = typer.Argument(None, help="One company; omit for the whole universe."),
) -> None:
    """The universe, or one company with every field's source and confidence."""
    from app.web.db.analytics import analytics_session
    from app.web.db.analytics.services.corporate_companies import (
        load_companies,
        load_company,
        sightings_for,
    )

    settings = _settings()
    with analytics_session(settings) as session:
        if ticker is None:
            table = Table(title="corporate universe")
            for column in ("ticker", "name", "status", "home", "sector", "isin", "conf"):
                table.add_column(column)
            for row in load_companies(session):
                table.add_row(
                    row.ticker_symbol,
                    row.canonical_name,
                    row.listing_status,
                    row.home_country,
                    row.sector_code or "-",
                    row.isin or "-",
                    f"{row.confidence:.2f}",
                )
            console.print(table)
            return
        row = load_company(session, ticker)  # type: ignore[assignment]
        if row is None:
            raise typer.BadParameter(f"{ticker} is not in the universe (run `universe build`)")
        console.print(f"[bold]{row.ticker_symbol}[/bold] {row.canonical_name}")
        console.print(f"  legal name : {row.legal_name}")
        console.print(f"  status     : {row.listing_status} - {row.status_reason}")
        console.print(f"  home       : {row.home_country}   sector: {row.sector_code or '-'}")
        console.print(f"  isin       : {row.isin or '-'}   lei: {row.lei or '-'}")
        console.print(f"  website    : {row.website or '-'}")
        console.print(
            f"  listed     : {row.first_listed or '-'}   delisted: {row.delisted_on or '-'}"
        )
        table = Table(title="field sources")
        table.add_column("field")
        table.add_column("source")
        table.add_column("confidence", justify="right")
        table.add_column("evidence")
        for name, src in sorted(row.field_sources.items()):
            table.add_row(
                name, str(src["source"]), f"{src['confidence']:.2f}", str(src["evidence"])
            )
        console.print(table)
        if row.name_history:
            console.print("  name history:")
            for entry in row.name_history:
                console.print(
                    f"    {entry.get('ticker')} ({entry.get('reason')}): {entry.get('evidence')}"
                )
        if row.status_history:
            console.print("  status history:")
            for entry in row.status_history:
                console.print(
                    f"    {entry.get('recorded')} {entry.get('from_status') or '-'} -> "
                    f"{entry.get('status')}: {entry.get('reason')}"
                )
        sightings = sightings_for(session, ticker)
        console.print(
            f"  sightings  : {len(sightings)} (latest {sightings[0].seen_at:%Y-%m-%d} "
            if sightings
            else "  sightings  : none"
        )


@universe_app.command("diff")
def universe_diff(
    days: int = typer.Option(7, "--days", min=1, help="Status changes recorded within N days."),
) -> None:
    """Companies whose listing status changed recently, with the reason."""
    from datetime import UTC, datetime, timedelta

    from app.web.db.analytics import analytics_session
    from app.web.db.analytics.services.corporate_companies import load_companies

    settings = _settings()
    since = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    changes = 0
    with analytics_session(settings) as session:
        for row in load_companies(session):
            for entry in row.status_history:
                if str(entry.get("recorded", "")) >= since:
                    changes += 1
                    console.print(
                        f"{row.ticker_symbol:7s} {entry.get('recorded')} "
                        f"{entry.get('from_status') or '-'} -> {entry.get('status')}: "
                        f"{entry.get('reason')}"
                    )
    console.print(f"{changes} status change(s) in the last {days} days")


@gleif_app.command("sync")
def gleif_sync(
    ticker: list[str] | None = typer.Option(None, "--ticker", help="Limit to these tickers."),
) -> None:
    """Look every company up on GLEIF; write LEIs, legal names, registration numbers."""
    from app.web.services.corporate.entities.service import sync_gleif

    settings = _settings()
    result = sync_gleif(settings, tickers=ticker or None)
    console.print(
        f"[green]gleif:[/green] {result.companies} companies - matched {result.matched}, "
        f"unchanged {result.unchanged}, no LEI {result.unmatched}; "
        f"{result.requests} requests, {result.cache_hits} cache hits; "
        f"{result.entities_created} listed entities created"
    )
    for line in result.ambiguous:
        console.print(f"  [yellow]near match (review)[/yellow] {line}")
    for line in result.errors:
        console.print(f"  [red]error[/red] {line}")


@entities_app.command("show")
def entities_show(ticker: str = typer.Argument(..., help="Listed company ticker")) -> None:
    """The listed company's own entity and every entity resolved under its group."""
    from app.web.db.analytics import analytics_session
    from app.web.db.analytics.services.corporate_entities import entities_for_group

    settings = _settings()
    with analytics_session(settings) as session:
        rows = entities_for_group(session, ticker)
        if not rows:
            console.print(f"no entities for {ticker.upper()} (run `corporate gleif sync`)")
            return
        table = Table(title=f"entities under {ticker.upper()}")
        for column in ("id", "legal name", "juris", "type", "lei", "reg. no", "method", "conf"):
            table.add_column(column)
        for row in rows:
            table.add_row(
                str(row.id),
                row.legal_name,
                row.jurisdiction,
                row.entity_type,
                row.lei or "-",
                row.registration_number or "-",
                row.resolution_method,
                f"{row.confidence:.2f}",
            )
        console.print(table)


@corporate_app.command("collect")
def collect(
    ticker: list[str] | None = typer.Option(None, "--ticker", help="Limit to these companies."),
    source: list[str] | None = typer.Option(
        None, "--source", help="Limit to these sources (ir, nse, cbk, bot, cma or ir:KCB)."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Discover only; fetch nothing."),
    max_documents: int | None = typer.Option(
        None, "--max", min=1, help="Override CORPORATE_MAX_DOCUMENTS_PER_RUN for this run."
    ),
) -> None:
    """Discover and fetch annual reports, statements, announcements and regulator reports."""
    from app.web.services.corporate.collect.service import collect_documents

    settings = _settings()
    result = collect_documents(
        settings,
        tickers=ticker or None,
        sources=source or None,
        dry_run=dry_run,
        max_documents=max_documents,
    )
    console.print(
        f"[green]collect:[/green] {result.sources} sources, {result.discovered} candidates"
        + (" (dry run)" if result.dry_run else "")
        + f" - fetched {result.fetched}, new versions {result.new_versions}, "
        f"unchanged {result.unchanged}, too large {result.too_large}, failed {result.failed}, "
        f"over budget {result.skipped_budget}"
    )
    for name, (status, detail) in sorted(result.health.items()):
        colour = {"ok": "green", "degraded": "yellow"}.get(status, "red")
        console.print(f"  [{colour}]{status:9s}[/{colour}] {name}: {detail[:120]}")
    for title in result.fetched_titles:
        console.print(f"  [green]+[/green] {title}")
    for line in result.failures:
        console.print(f"  [yellow]![/yellow] {line}")


@documents_app.command("list")
def documents_list(
    ticker: str | None = typer.Option(None, "--ticker"),
    status: str | None = typer.Option(
        None, "--status", help="pending, extracted, ocr_pending, ..."
    ),
    kind: str | None = typer.Option(None, "--kind"),
) -> None:
    """Current document versions in the store (files live under CORPORATE_DOCUMENTS_DIR)."""
    from app.web.db.analytics import analytics_session
    from app.web.db.analytics.services.corporate_documents import document_counts, load_documents

    settings = _settings()
    with analytics_session(settings) as session:
        rows = load_documents(session, ticker_symbol=ticker, parse_status=status, kind=kind)
        counts = document_counts(session)
        table = Table(title="corporate documents")
        for column in ("id", "ticker", "source", "kind", "FY", "title", "MB", "v", "status"):
            table.add_column(column)
        for row in rows:
            table.add_row(
                str(row.id),
                row.ticker_symbol or "-",
                row.source,
                row.kind,
                str(row.fiscal_year or "-"),
                row.title[:60],
                f"{row.bytes / 1e6:.1f}",
                str(row.version_no),
                row.parse_status,
            )
        console.print(table)
        console.print(
            f"{len(rows)} shown; store: {counts['by_parse_status']} "
            f"{counts['bytes'] / 1e6:.0f} MB across {counts['tickers']} tickers"
        )


@sources_app.command("health")
def sources_health() -> None:
    """Every registered source with its last outcome."""
    from app.web.db.analytics import analytics_session
    from app.web.db.analytics.services.corporate_documents import load_sources

    settings = _settings()
    with analytics_session(settings) as session:
        table = Table(title="document sources")
        for column in ("name", "kind", "health", "last ok", "failures", "last error / notes"):
            table.add_column(column)
        for row in load_sources(session):
            colour = {"ok": "green", "degraded": "yellow"}.get(row.health, "red")
            table.add_row(
                row.name,
                row.kind,
                f"[{colour}]{row.health}[/{colour}]",
                row.last_ok_at.strftime("%Y-%m-%d") if row.last_ok_at else "-",
                str(row.consecutive_failures),
                (row.last_error or row.notes or "")[:80],
            )
        console.print(table)


__all__ = ["corporate_app"]
