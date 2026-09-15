"""The job runner: dependency-ordered pipelines with input watermarks and resume.

A *pipeline* is an ordered list of *steps*; each step calls one analytics service
(the same function the CLI command calls) and records a ``job_runs`` row named
``step:<name>``. Before running, a step computes a fingerprint of everything it
depends on - the source tables it reads, the analytics config, the date, and the
fingerprints of the steps upstream of it - and is **skipped** when the last
succeeded run of the same step for the same date carries the same fingerprint.
So a second ``daily`` run on unchanged data writes nothing, a failed step leaves
the steps before it succeeded (and skippable next time) and the pipeline resumes
from the failure, and a config change re-runs everything downstream of it.

Every service is idempotent on its natural key, so even a forced re-run yields the
same row counts.

    codegraph explore "run_pipeline PIPELINES Step fingerprint_for"
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import JobRun, JobStatus
from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig
from app.web.services.market_data.sources.nse_scraper import NseScraperSource
from app.web.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class JobContext:
    settings: Settings
    source: NseScraperSource
    as_of: date
    config: AnalyticsConfig
    watermarks: Mapping[str, str]


@dataclass(frozen=True)
class StepOutcome:
    rows_written: int
    details: dict[str, Any] = field(default_factory=dict)


#: A step body: runs the service and reports what it wrote.
StepBody = Callable[[JobContext], StepOutcome]


@dataclass(frozen=True)
class Step:
    name: str
    body: StepBody
    #: Source tables the step reads (keys of ``NseScraperSource.input_watermarks``).
    inputs: tuple[str, ...] = ("observations",)
    #: Steps whose output this one reads (their fingerprints join this one's).
    depends_on: tuple[str, ...] = ()
    #: Steps that never skip (they act on time passing, not on data changing).
    always_run: bool = False


@dataclass(frozen=True)
class StepResult:
    name: str
    status: str  # succeeded, skipped, failed
    rows_written: int
    seconds: float
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineResult:
    pipeline: str
    as_of: date
    steps: tuple[StepResult, ...]
    run_id: int

    @property
    def succeeded(self) -> bool:
        return all(s.status != "failed" for s in self.steps)

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self.steps:
            out[s.status] = out.get(s.status, 0) + 1
        return out


def fingerprint_for(step: Step, ctx: JobContext, upstream: Mapping[str, str]) -> str:
    """sha256 over the step's inputs, the config, the date and upstream fingerprints."""
    parts = [f"as_of={ctx.as_of.isoformat()}", f"config={ctx.config.config_hash()}"]
    for name in step.inputs:
        parts.append(f"{name}={ctx.watermarks.get(name, 'absent')}")
    for name in step.depends_on:
        parts.append(f"{name}={upstream.get(name, 'unknown')}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]


def has_succeeded_with(settings: Settings, step_name: str, as_of: date, fingerprint: str) -> bool:
    """Whether any succeeded run of the step for the date carries this fingerprint.

    Any, not the latest: the same step sits in several pipelines with different
    upstream sets (so different fingerprints), and each must recognise its own.
    """
    with analytics_session(settings) as session:
        row = session.execute(
            select(JobRun.id)
            .where(
                JobRun.job_name == f"step:{step_name}",
                JobRun.as_of_date == as_of,
                JobRun.status == JobStatus.SUCCEEDED,
                JobRun.watermark == fingerprint,
            )
            .limit(1)
        ).scalar_one_or_none()
        return row is not None


def _record(
    settings: Settings,
    step: Step,
    as_of: date,
    *,
    status: JobStatus,
    fingerprint: str,
    started: datetime,
    rows: int,
    details: dict[str, Any],
    error: str | None = None,
) -> None:
    with analytics_session(settings) as session:
        session.add(
            JobRun(
                job_name=f"step:{step.name}",
                status=status,
                started_at=started,
                finished_at=datetime.now(UTC),
                as_of_date=as_of,
                watermark=fingerprint,
                rows_written=rows,
                error=error,
                details=details,
            )
        )


def run_steps(
    steps: Sequence[Step], ctx: JobContext, *, force: bool = False, stop_on_failure: bool = True
) -> list[StepResult]:
    results: list[StepResult] = []
    fingerprints: dict[str, str] = {}
    failed = False
    for step in steps:
        fingerprint = fingerprint_for(step, ctx, fingerprints)
        fingerprints[step.name] = fingerprint
        if failed and stop_on_failure:
            results.append(StepResult(step.name, "skipped", 0, 0.0, "an upstream step failed"))
            continue
        started = datetime.now(UTC)
        clock = time.perf_counter()
        if (
            not force
            and not step.always_run
            and has_succeeded_with(ctx.settings, step.name, ctx.as_of, fingerprint)
        ):
            _record(
                ctx.settings,
                step,
                ctx.as_of,
                status=JobStatus.SKIPPED,
                fingerprint=fingerprint,
                started=started,
                rows=0,
                details={"reason": "inputs unchanged"},
            )
            results.append(
                StepResult(step.name, "skipped", 0, time.perf_counter() - clock, "inputs unchanged")
            )
            continue
        try:
            outcome = step.body(ctx)
        except Exception as exc:  # the row must say why; the pipeline reports it
            failed = True
            message = f"{type(exc).__name__}: {exc}"
            _record(
                ctx.settings,
                step,
                ctx.as_of,
                status=JobStatus.FAILED,
                fingerprint=fingerprint,
                started=started,
                rows=0,
                details={"reason": message},
                error=message,
            )
            logger.error(
                "job_step_failed", step=step.name, as_of=ctx.as_of.isoformat(), error=message
            )
            results.append(StepResult(step.name, "failed", 0, time.perf_counter() - clock, message))
            continue
        _record(
            ctx.settings,
            step,
            ctx.as_of,
            status=JobStatus.SUCCEEDED,
            fingerprint=fingerprint,
            started=started,
            rows=outcome.rows_written,
            details=outcome.details,
        )
        results.append(
            StepResult(
                step.name,
                "succeeded",
                outcome.rows_written,
                time.perf_counter() - clock,
                None,
                outcome.details,
            )
        )
    return results


def run_pipeline(
    settings: Settings,
    source: NseScraperSource,
    pipeline: str,
    *,
    as_of: date | None = None,
    force: bool = False,
    config: AnalyticsConfig = DEFAULT_CONFIG,
    steps: Sequence[Step] | None = None,
) -> PipelineResult:
    from app.web.services.jobs.pipelines import PIPELINES

    chosen = list(steps) if steps is not None else PIPELINES[pipeline]
    day = as_of or datetime.now(UTC).date()
    started = datetime.now(UTC)
    ctx = JobContext(settings, source, day, config, source.input_watermarks())
    with analytics_session(settings) as session:
        run = JobRun(job_name=f"pipeline:{pipeline}", started_at=started, as_of_date=day)
        session.add(run)
        session.flush()
        run_id = run.id
    results = run_steps(chosen, ctx, force=force)
    result = PipelineResult(pipeline, day, tuple(results), run_id)
    with analytics_session(settings) as session:
        stored = session.get(JobRun, run_id)
        assert stored is not None
        stored.status = JobStatus.SUCCEEDED if result.succeeded else JobStatus.FAILED
        stored.finished_at = datetime.now(UTC)
        stored.rows_written = sum(s.rows_written for s in results)
        stored.watermark = day.isoformat()
        stored.error = next((s.reason for s in results if s.status == "failed"), None)
        stored.details = {
            "force": force,
            "counts": result.counts,
            "steps": [
                {
                    "name": s.name,
                    "status": s.status,
                    "rows": s.rows_written,
                    "seconds": round(s.seconds, 2),
                    "reason": s.reason,
                }
                for s in results
            ],
            "watermarks": dict(ctx.watermarks),
        }
    logger.info("pipeline_finished", pipeline=pipeline, as_of=day.isoformat(), counts=result.counts)
    return result


__all__ = [
    "JobContext",
    "PipelineResult",
    "Step",
    "StepBody",
    "StepOutcome",
    "StepResult",
    "fingerprint_for",
    "has_succeeded_with",
    "run_pipeline",
    "run_steps",
]
