"""Report generation orchestration for daily, weekly, and monthly reports."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from nse_analysis.config import Settings
from nse_analysis.reports.formatter import now_utc_iso
from nse_analysis.reports.templates import (
    render_daily_markdown,
    render_weekly_markdown,
    render_monthly_markdown,
)
from nse_analysis.utils.exceptions import ReportGenerationError


def write_daily_report(
    settings: Settings,
    market_summary: dict[str, Any],
    indicator_rows: list[dict[str, Any]],
    feasibility_summary: dict[str, int],
    not_calculable: dict[str, list[str]],
    data_quality: dict[str, Any],
) -> Path:
    """Render and persist daily markdown report to reports directory."""
    try:
        report_date = datetime.now(tz=timezone.utc).date().isoformat()
        content = render_daily_markdown(
            report_date=report_date,
            generated_at=now_utc_iso(),
            market_summary=market_summary,
            indicator_rows=indicator_rows,
            feasibility_summary=feasibility_summary,
            not_calculable=not_calculable,
            data_quality=data_quality,
        )
        output = settings.reports_dir / f"{report_date}.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        return output
    except Exception as exc:  # noqa: BLE001
        raise ReportGenerationError(f"Failed to generate report: {exc}") from exc


def write_weekly_report(
    settings: Settings,
    market_summary: dict[str, Any],
    indicator_rows: list[dict[str, Any]],
    week_start_date: str,
    week_end_date: str,
) -> Path:
    """Render and persist weekly markdown report."""
    try:
        report_date = datetime.now(tz=timezone.utc).date().isoformat()
        content = render_weekly_markdown(
            report_date=report_date,
            generated_at=now_utc_iso(),
            market_summary=market_summary,
            indicator_rows=indicator_rows,
            week_start_date=week_start_date,
            week_end_date=week_end_date,
        )
        output = settings.weekly_reports_dir / f"{week_end_date}.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        return output
    except Exception as exc:  # noqa: BLE001
        raise ReportGenerationError(f"Failed to generate weekly report: {exc}") from exc


def write_monthly_report(
    settings: Settings,
    market_summary: dict[str, Any],
    indicator_rows: list[dict[str, Any]],
    month: str,
    year: int,
) -> Path:
    """Render and persist monthly markdown report."""
    try:
        report_date = datetime.now(tz=timezone.utc).date().isoformat()
        content = render_monthly_markdown(
            report_date=report_date,
            generated_at=now_utc_iso(),
            market_summary=market_summary,
            indicator_rows=indicator_rows,
            month=month,
            year=year,
        )
        # Use format YYYY-MM for filename
        month_str = f"{year}-{month:02d}" if isinstance(month, int) else f"{year}-{month}"
        output = settings.monthly_reports_dir / f"{month_str}.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        return output
    except Exception as exc:  # noqa: BLE001
        raise ReportGenerationError(f"Failed to generate monthly report: {exc}") from exc
