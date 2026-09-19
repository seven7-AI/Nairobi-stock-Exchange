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

from app.cli.analytics import _settings
from app.web.services.corporate.config import DEFAULT_CORPORATE_CONFIG
from app.web.services.corporate.extract.capabilities import detect_capabilities

corporate_app = typer.Typer(help="Corporate structure, geographic footprint and expansion facts.")
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


__all__ = ["corporate_app"]
