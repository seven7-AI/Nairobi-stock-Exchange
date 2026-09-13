"""Run every data-quality check over the scraper database and record what it found.

The one entry point the CLI (``nse-analysis analytics dq``) and, later, the daily
job call. Reads are through ``NseScraperSource`` (read-only); findings go to the
analytics store via ``reconcile_findings``; a Markdown report is written to
``reports/data_quality/``.

    codegraph explore "run_data_quality DataQualityReport reconcile_findings"
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import JobRun, JobStatus
from app.web.db.analytics.services.classifications import load_classifications
from app.web.db.analytics.services.data_quality import ReconcileResult, reconcile_findings
from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig
from app.web.services.analytics.quality import checks
from app.web.services.analytics.quality.checks import Finding
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.utils.logger import get_logger

logger = get_logger(__name__)

JOB_NAME = "data_quality"
#: Observations dated on/after this come from the daily scraper, not the archive.
SCRAPER_ERA_START = date(2025, 1, 1)


@dataclass(frozen=True)
class DataQualityReport:
    run_id: int | None
    checked_at: datetime
    instruments: int
    findings: tuple[Finding, ...]
    reconciled: ReconcileResult
    report_path: Path | None
    counts_by_check: dict[str, int] = field(default_factory=dict)
    counts_by_severity: dict[str, int] = field(default_factory=dict)

    @property
    def errors(self) -> int:
        return self.counts_by_severity.get("error", 0)

    @property
    def warnings(self) -> int:
        return self.counts_by_severity.get("warning", 0)


def collect_findings(
    source: NseScraperSource,
    config: AnalyticsConfig,
    *,
    classified: dict[str, list[tuple[date, date | None]]],
    stale_after_hours: int,
    now: datetime,
) -> tuple[list[Finding], int]:
    """Every check over the whole universe. Pure apart from the source reads."""
    instruments = source.fetch_instruments()
    spans = source.fetch_observation_spans()
    tickers = [i["ticker_symbol"] for i in instruments]
    series = source.fetch_observations_bulk(tickers)
    has_statements_table = source.has_financial_statements()
    findings: list[Finding] = []
    per_ticker_gaps: list[Finding] = []
    for ticker in tickers:
        rows = series.get(ticker, [])
        if not rows:
            continue
        findings.extend(checks.duplicate_observations(ticker, rows))
        findings.extend(checks.impossible_values(ticker, rows, config))
        findings.extend(checks.price_jumps(ticker, rows, config))
        gaps = list(checks.missing_periods(ticker, rows, config))
        per_ticker_gaps.extend(gaps)
        findings.extend(gaps)
        findings.extend(checks.zero_volume_streaks(ticker, rows, config))
        findings.extend(checks.thin_history(ticker, rows, config))
        statements = source.fetch_financial_statements(ticker) if has_statements_table else []
        findings.extend(checks.balance_sheet_consistency(ticker, statements, config))
        findings.extend(
            checks.missing_fundamentals(
                ticker, bool(statements), spans.get(ticker), SCRAPER_ERA_START
            )
        )
    findings.extend(checks.universe_gap(spans, per_ticker_gaps, config))
    latest = max((span[1] for span in spans.values()), default=None)
    findings.extend(checks.stale_data(latest, now, stale_after_hours))
    findings.extend(checks.broken_scrape(source.read_quality_gate()))
    findings.extend(checks.unclassified_instruments(instruments, classified, spans))
    return findings, len(instruments)


def write_report(
    path: Path, report_findings: list[Finding], checked_at: datetime, instruments: int
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    by_check = Counter(f.check for f in report_findings)
    by_severity = Counter(f.severity.value for f in report_findings)
    lines = [
        f"# Data quality — {checked_at:%Y-%m-%d %H:%M} UTC",
        "",
        f"{instruments} instruments checked · {len(report_findings)} findings "
        f"({by_severity.get('error', 0)} error, {by_severity.get('warning', 0)} warning, "
        f"{by_severity.get('info', 0)} info)",
        "",
        "| Check | Findings |",
        "|---|---:|",
        *[f"| {check} | {count} |" for check, count in sorted(by_check.items())],
        "",
    ]
    for severity in ("error", "warning", "info"):
        rows = [f for f in report_findings if f.severity.value == severity]
        if not rows:
            continue
        lines += [f"## {severity.upper()} ({len(rows)})", ""]
        lines += [f"- `{f.check}` {f.detail}" for f in rows[:200]]
        if len(rows) > 200:
            lines.append(f"- … {len(rows) - 200} more")
        lines.append("")
    path.write_text("\n".join(lines))
    return path


def run_data_quality(
    settings: Settings,
    source: NseScraperSource,
    config: AnalyticsConfig = DEFAULT_CONFIG,
    *,
    now: datetime | None = None,
    report_dir: Path | None = None,
) -> DataQualityReport:
    checked_at = now or datetime.now(UTC)
    with analytics_session(settings) as session:
        run = JobRun(job_name=JOB_NAME, started_at=checked_at, as_of_date=checked_at.date())
        session.add(run)
        session.flush()
        run_id = run.id
        classified: dict[str, list[tuple[date, date | None]]] = {}
        for row in load_classifications(session):
            classified.setdefault(row.ticker_symbol, []).append((row.valid_from, row.valid_to))
        try:
            findings, instruments = collect_findings(
                source,
                config,
                classified=classified,
                stale_after_hours=settings.nse_scraper_stale_after_hours,
                now=checked_at,
            )
            reconciled = reconcile_findings(session, findings, run_id=run_id, now=checked_at)
        except Exception as exc:
            run.status = JobStatus.FAILED
            run.error = f"{type(exc).__name__}: {exc}"
            run.finished_at = datetime.now(UTC)
            raise
        by_check = dict(Counter(f.check for f in findings))
        by_severity = dict(Counter(f.severity.value for f in findings))
        run.status = JobStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)
        run.rows_written = reconciled.created
        run.watermark = checked_at.date().isoformat()
        run.details = {
            "instruments": instruments,
            "findings": len(findings),
            "by_check": by_check,
            "by_severity": by_severity,
            "resolved": reconciled.resolved,
        }
    directory = report_dir or (settings.reports_dir.parent / "data_quality")
    report_path = write_report(
        directory / f"{checked_at:%Y-%m-%d}.md", findings, checked_at, instruments
    )
    (directory / "latest.md").write_text(report_path.read_text())
    logger.info(
        "data_quality_done",
        run_id=run_id,
        instruments=instruments,
        findings=len(findings),
        by_severity=by_severity,
        resolved=reconciled.resolved,
        report=str(report_path),
    )
    return DataQualityReport(
        run_id=run_id,
        checked_at=checked_at,
        instruments=instruments,
        findings=tuple(findings),
        reconciled=reconciled,
        report_path=report_path,
        counts_by_check=by_check,
        counts_by_severity=by_severity,
    )


__all__ = [
    "JOB_NAME",
    "SCRAPER_ERA_START",
    "DataQualityReport",
    "collect_findings",
    "run_data_quality",
    "write_report",
]
