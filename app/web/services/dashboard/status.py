"""System status for the dashboard: what the store holds, what each pipeline last did,
whether the scraper is fresh, and a cheap version stamp the client polls.

Built on ``job_status`` (the CLI's ``jobs status``) plus the scraper source's
``health_check``; nothing here computes analytics. Everything that leaves the process
is sanitised: no filesystem paths, no raw job details, no settings.

    codegraph explore "build_status build_version DashboardStatus job_status"
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import StockRanking
from app.web.db.analytics.services.summaries import latest_as_of, latest_runs
from app.web.services.dashboard.cache import StoreStamp, store_stamp
from app.web.services.dashboard.common import sanitise_text
from app.web.services.jobs.status import JobLast, job_status
from app.web.services.market_data.sources.nse_scraper import NseScraperSource

#: The installed chain (``scripts/install_analytics_cron.sh`` and the scraper's own
#: entry). Duplicated here on purpose - the script cannot be imported - and pinned by a
#: unit test that reads the script.
CRON_TIMEZONE = "Africa/Nairobi"
CRON_SCHEDULE: tuple[tuple[str, str, str], ...] = (
    ("scrape", "00 09 * * *", "prices + statements (nse-stock-scraper)"),
    (
        "daily",
        "40 09 * * *",
        "quality gate, market metrics, factors, rankings, fair value, scenarios",
    ),
    ("fundamentals", "10 10 * * *", "fundamental metrics when statements changed, then dependants"),
    ("weekly", "30 10 * * 6", "regime, forecasts and their evaluation, Monte Carlo"),
)
PIPELINES: tuple[str, ...] = ("daily", "fundamentals", "weekly")

#: Keys of ``JobRun.details`` that are safe and useful to serve.
_DETAIL_KEYS: tuple[str, ...] = ("counts", "steps", "force", "ignore_quality_gate")


@dataclass(frozen=True)
class JobRow:
    job_name: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    as_of: str | None
    rows_written: int
    seconds: float | None
    error: str | None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineStatus:
    pipeline: str
    schedule: str
    timezone: str
    description: str
    last_run: JobRow | None
    last_success: JobRow | None
    steps: list[dict[str, Any]]


@dataclass(frozen=True)
class CronEntry:
    pipeline: str
    expression: str
    timezone: str
    description: str


@dataclass(frozen=True)
class VersionStamp:
    version: str
    analytics_updated_at: datetime | None
    scraper_updated_at: datetime | None
    latest_market_date: date | None
    latest_analytics_date: date | None
    generated_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DashboardStatus:
    version: VersionStamp
    store: dict[str, Any]
    pipelines: list[PipelineStatus]
    jobs: list[JobRow]
    models: list[dict[str, Any]]
    open_findings: int
    source: dict[str, Any]
    watermarks: dict[str, str]
    cron: list[CronEntry]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _stamp_datetime(mtime_ns: int) -> datetime | None:
    return datetime.fromtimestamp(mtime_ns / 1e9, tz=UTC) if mtime_ns else None


def _job_row(last: JobLast) -> JobRow:
    seconds = (
        (last.finished_at - last.started_at).total_seconds()
        if last.finished_at is not None
        else None
    )
    details = {k: v for k, v in last.details.items() if k in _DETAIL_KEYS}
    for step in details.get("steps", []) or []:
        if isinstance(step, dict) and step.get("reason"):
            step["reason"] = sanitise_text(str(step["reason"]))
    return JobRow(
        last.job_name,
        last.status,
        last.started_at,
        last.finished_at,
        last.as_of,
        last.rows_written,
        round(seconds, 1) if seconds is not None else None,
        sanitise_text(last.error),
        details,
    )


def _job_row_from_run(run: Any) -> JobRow:
    return _job_row(
        JobLast(
            run.job_name,
            str(run.status),
            run.started_at,
            run.finished_at,
            run.as_of_date.isoformat() if run.as_of_date else None,
            run.rows_written,
            run.error,
            dict(run.details or {}),
        )
    )


def _source_dict(source: NseScraperSource) -> dict[str, Any]:
    health = source.health_check().to_dict()
    health.pop("location", None)
    health["detail"] = sanitise_text(str(health.get("detail") or "")) or ""
    return health


def build_version(
    settings: Settings, source: NseScraperSource, stamp: StoreStamp | None = None
) -> VersionStamp:
    """The stamp the client polls: file mtimes plus the two dates a reader cares about."""
    stamp = stamp or store_stamp(settings)
    latest_market = source.latest_trade_date() if settings.scraper_database_path.exists() else None
    latest_analytics: date | None = None
    if settings.analytics_db_path.exists():
        with analytics_session(settings) as session:
            latest_analytics = latest_as_of(session, StockRanking)
    return VersionStamp(
        stamp.version,
        _stamp_datetime(stamp.analytics_mtime_ns),
        _stamp_datetime(stamp.scraper_mtime_ns),
        latest_market,
        latest_analytics,
        datetime.now(UTC),
    )


def build_status(settings: Settings, source: NseScraperSource) -> DashboardStatus:
    stamp = store_stamp(settings)
    js = job_status(settings)
    jobs = [_job_row(j) for j in js.jobs]
    by_name = {j.job_name: j for j in jobs}
    schedule = {name: (expr, desc) for name, expr, desc in CRON_SCHEDULE}
    pipelines: list[PipelineStatus] = []
    if settings.analytics_db_path.exists():
        with analytics_session(settings) as session:
            for name in PIPELINES:
                job_name = f"pipeline:{name}"
                last_run = by_name.get(job_name)
                success_rows = latest_runs(session, job_name, status="succeeded")
                last_success = _job_row_from_run(success_rows[0]) if success_rows else None
                expr, desc = schedule[name]
                steps = list((last_run.details.get("steps") if last_run else None) or [])
                pipelines.append(
                    PipelineStatus(name, expr, CRON_TIMEZONE, desc, last_run, last_success, steps)
                )
    try:
        watermarks = source.input_watermarks() if settings.scraper_database_path.exists() else {}
    except Exception:  # the health block reports the failure; watermarks are optional
        watermarks = {}
    store = {
        "revision": js.revision,
        "head": js.head,
        "migrated": js.revision is not None and js.revision == js.head,
        "tables": js.tables,
        "last_update": js.last_update,
    }
    return DashboardStatus(
        build_version(settings, source, stamp),
        store,
        pipelines,
        jobs,
        [dict(m) for m in js.models],
        js.open_findings,
        _source_dict(source),
        watermarks,
        [CronEntry(n, e, CRON_TIMEZONE, d) for n, e, d in CRON_SCHEDULE],
    )


__all__ = [
    "CRON_SCHEDULE",
    "CRON_TIMEZONE",
    "PIPELINES",
    "DashboardStatus",
    "JobRow",
    "PipelineStatus",
    "VersionStamp",
    "build_status",
    "build_version",
]
