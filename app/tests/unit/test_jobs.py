"""Job runner: idempotent pipelines, watermark skips, resume after failure, status, CLI,
Celery wrapper, cron script.

codegraph explore "run_pipeline run_steps job_status run_pipeline_task"
"""

from __future__ import annotations

import sqlite3
import subprocess
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import FundamentalMetric, JobRun, MarketMetric
from app.web.services.analytics.classification.service import classify_instruments
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.jobs import PIPELINES, job_status, run_pipeline
from app.web.services.jobs.pipelines import DAILY, FUNDAMENTALS
from app.web.services.jobs.runner import JobContext, Step, StepOutcome
from app.web.services.market_data.sources import NseScraperSource

pytestmark = pytest.mark.unit

AS_OF = date(2019, 12, 31)


@pytest.fixture
def populated(fixture_db_path: Path, tmp_path: Path) -> tuple[Settings, NseScraperSource, Path]:
    db = tmp_path / "scraper.sqlite3"
    db.write_bytes(fixture_db_path.read_bytes())
    settings = Settings(
        NSE_SCRAPER_DB_PATH=str(db),
        NSE_SCRAPER_PATH=str(tmp_path / "scraper"),
        ANALYTICS_DB_PATH=str(tmp_path / "a.sqlite3"),
    )
    upgrade_analytics_db(settings.analytics_db_path)
    source = NseScraperSource(settings)
    classify_instruments(settings, source)
    return settings, source, db


def _counts(settings: Settings) -> dict[str, int]:
    return {k: v for k, v in job_status(settings).tables.items() if k != "job_runs"}


def _step_rows(settings: Settings, name: str) -> list[JobRun]:
    with analytics_session(settings) as session:
        return list(
            session.execute(
                select(JobRun).where(JobRun.job_name == f"step:{name}").order_by(JobRun.id)
            ).scalars()
        )


def test_daily_pipeline_is_idempotent_and_skips_unchanged_inputs(
    populated: tuple[Settings, NseScraperSource, Path],
) -> None:
    settings, source, _ = populated
    first = run_pipeline(settings, source, "daily", as_of=AS_OF)
    assert first.succeeded and [s.name for s in first.steps] == [s.name for s in DAILY]
    assert first.counts == {"succeeded": len(DAILY)}
    after_first = _counts(settings)
    assert after_first["market_metrics"] > 0 and after_first["stock_rankings"] > 0
    second = run_pipeline(settings, source, "daily", as_of=AS_OF)
    assert second.counts == {"skipped": len(DAILY)}
    assert all(s.reason == "inputs unchanged" for s in second.steps)
    assert _counts(settings) == after_first
    forced = run_pipeline(settings, source, "daily", as_of=AS_OF, force=True)
    assert forced.counts == {"succeeded": len(DAILY)}
    assert _counts(settings) == after_first  # every service is idempotent on its key
    with analytics_session(settings) as session:
        pipelines = (
            session.execute(
                select(JobRun).where(JobRun.job_name == "pipeline:daily").order_by(JobRun.id)
            )
            .scalars()
            .all()
        )
        assert [p.status for p in pipelines] == ["succeeded"] * 3
        assert (pipelines[1].details or {})["counts"] == {"skipped": len(DAILY)}
        assert "observations" in (pipelines[0].details or {})["watermarks"]
    returns_runs = _step_rows(settings, "returns")
    assert [r.status for r in returns_runs] == ["succeeded", "skipped", "succeeded"]
    assert returns_runs[0].watermark == returns_runs[1].watermark == returns_runs[2].watermark


def test_changed_inputs_rerun_only_the_dependent_steps(
    populated: tuple[Settings, NseScraperSource, Path],
) -> None:
    settings, source, db = populated
    run_pipeline(settings, source, "fundamentals", as_of=AS_OF)
    again = run_pipeline(settings, source, "fundamentals", as_of=AS_OF)
    assert again.counts == {"skipped": len(FUNDAMENTALS)}
    # a new statement row arrives (append-only, first seen now): everything reruns
    with sqlite3.connect(db) as conn:
        # copy one row as a new fiscal period first seen "now"
        conn.execute(
            "insert into financial_statements (ticker_symbol, source_ticker, statement, "
            "period_type, fiscal_period_end, fiscal_label, line_item, label, row_key, value, "
            "value_raw, unit, currency, data_source, source_url, first_seen_at, last_seen_at) "
            "select ticker_symbol, source_ticker, statement, period_type, '2099-12-31', "
            "'FY 2099', line_item, label, row_key, value, value_raw, unit, currency, "
            "data_source, source_url, '2099-01-01T00:00:00+00:00', '2099-01-01T00:00:00+00:00' "
            "from financial_statements limit 1"
        )
        conn.commit()
    third = run_pipeline(settings, source, "fundamentals", as_of=AS_OF)
    assert third.counts == {"succeeded": len(FUNDAMENTALS)}
    with analytics_session(settings) as session:
        rows = session.execute(select(func.count(FundamentalMetric.id))).scalar()
        assert rows and rows > 0


def test_failure_stops_downstream_and_resumes_without_duplicates(
    populated: tuple[Settings, NseScraperSource, Path],
) -> None:
    settings, source, _ = populated
    attempts = {"n": 0}

    def flaky(ctx: JobContext) -> StepOutcome:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("simulated crash mid-run")
        return StepOutcome(0, {"attempt": attempts["n"]})

    returns, momentum = DAILY[1], DAILY[2]
    steps = [
        returns,
        Step("flaky", flaky, ("observations",), ("returns",)),
        Step(momentum.name, momentum.body, momentum.inputs, ("flaky",)),
    ]
    first = run_pipeline(settings, source, "custom", as_of=AS_OF, steps=steps)
    assert not first.succeeded
    assert [(s.name, s.status) for s in first.steps] == [
        ("returns", "succeeded"),
        ("flaky", "failed"),
        ("momentum", "skipped"),
    ]
    assert first.steps[1].reason == "RuntimeError: simulated crash mid-run"
    assert first.steps[2].reason == "an upstream step failed"
    with analytics_session(settings) as session:
        pipeline = (
            session.execute(select(JobRun).where(JobRun.job_name == "pipeline:custom"))
            .scalars()
            .one()
        )
        assert pipeline.status == "failed" and "simulated crash" in (pipeline.error or "")
        before = session.execute(select(func.count(MarketMetric.id))).scalar()
    second = run_pipeline(settings, source, "custom", as_of=AS_OF, steps=steps)
    assert second.succeeded
    assert [(s.name, s.status) for s in second.steps] == [
        ("returns", "skipped"),
        ("flaky", "succeeded"),
        ("momentum", "succeeded"),
    ]
    with analytics_session(settings) as session:
        after = session.execute(select(func.count(MarketMetric.id))).scalar()
    clean = run_pipeline(settings, source, "custom", as_of=AS_OF, steps=steps, force=True)
    with analytics_session(settings) as session:
        forced = session.execute(select(func.count(MarketMetric.id))).scalar()
    assert clean.succeeded and after == forced and (after or 0) > (before or 0)
    assert [r.status for r in _step_rows(settings, "flaky")] == ["failed", "succeeded", "succeeded"]


def test_always_run_steps_never_skip(populated: tuple[Settings, NseScraperSource, Path]) -> None:
    settings, source, _ = populated
    calls = {"n": 0}

    def tick(ctx: JobContext) -> StepOutcome:
        calls["n"] += 1
        return StepOutcome(0)

    steps = [Step("tick", tick, ("observations",), always_run=True)]
    run_pipeline(settings, source, "custom", as_of=AS_OF, steps=steps)
    run_pipeline(settings, source, "custom", as_of=AS_OF, steps=steps)
    assert calls["n"] == 2


def test_job_status_reports_tables_jobs_and_models(
    populated: tuple[Settings, NseScraperSource, Path],
) -> None:
    settings, source, _ = populated
    empty = job_status(settings)
    assert empty.revision == empty.head and empty.jobs == [] and empty.models == []
    run_pipeline(settings, source, "weekly", as_of=AS_OF)
    status = job_status(settings)
    assert status.last_update["forecasts"] is not None and status.last_update["regimes"] is not None
    names = {j.job_name for j in status.jobs}
    assert {"pipeline:weekly", "step:forecasts", "step:regime", "forecasts", "regime"} <= names
    weekly = next(j for j in status.jobs if j.job_name == "pipeline:weekly")
    assert weekly.status == "succeeded" and weekly.as_of == "2019-12-31"
    assert {m["name"] for m in status.models} >= {"naive", "mean", "ewma", "ar1", "factor-model"}
    assert status.open_findings == 0  # the weekly pipeline runs no quality checks
    assert "^NASI" not in status.tables


def test_cli_jobs_and_status(
    populated: tuple[Settings, NseScraperSource, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from app.cli.main import app
    from app.web.config import get_settings

    settings, _, _ = populated
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(settings.analytics_db_path))
    monkeypatch.setenv("NSE_SCRAPER_DB_PATH", str(settings.scraper_database_path))
    monkeypatch.setenv("NSE_SCRAPER_PATH", str(settings.nse_scraper_path))
    get_settings.cache_clear()
    try:
        runner = CliRunner()
        first = runner.invoke(app, ["analytics", "jobs", "fundamentals", "--as-of", "2019-12-31"])
        assert first.exit_code == 0, first.output
        assert f"succeeded {len(FUNDAMENTALS)}" in first.output
        second = runner.invoke(app, ["analytics", "jobs", "fundamentals", "--as-of", "2019-12-31"])
        assert second.exit_code == 0 and f"skipped {len(FUNDAMENTALS)}" in second.output
        status = runner.invoke(app, ["analytics", "jobs", "status"])
        assert status.exit_code == 0, status.output
        assert "pipeline:fundamentals: succeeded as of 2019-12-31" in status.output
        assert "factor-model" in status.output

        def boom(ctx: JobContext) -> StepOutcome:
            raise RuntimeError("boom")

        monkeypatch.setitem(PIPELINES, "weekly", (Step("boom", boom),))
        failed = runner.invoke(app, ["analytics", "jobs", "weekly", "--as-of", "2019-12-31"])
        assert failed.exit_code == 1 and "RuntimeError: boom" in failed.output
    finally:
        get_settings.cache_clear()


def test_celery_task_runs_the_same_pipeline(
    populated: tuple[Settings, NseScraperSource, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.celery_app.tasks.analytics_tasks import run_pipeline_task
    from app.web.config import get_settings

    settings, _, _ = populated
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(settings.analytics_db_path))
    monkeypatch.setenv("NSE_SCRAPER_DB_PATH", str(settings.scraper_database_path))
    monkeypatch.setenv("NSE_SCRAPER_PATH", str(settings.nse_scraper_path))
    get_settings.cache_clear()
    try:
        payload = run_pipeline_task.apply(args=("fundamentals", "2019-12-31")).get()
        assert payload["succeeded"] and payload["counts"] == {"succeeded": len(FUNDAMENTALS)}
        assert payload["steps"][0]["name"] == "fundamentals"
        again = run_pipeline_task.apply(args=("fundamentals", "2019-12-31")).get()
        assert again["counts"] == {"skipped": len(FUNDAMENTALS)}
    finally:
        get_settings.cache_clear()


def test_cron_script_prints_the_chained_entries() -> None:
    root = Path(__file__).resolve().parents[3]
    out = subprocess.run(
        ["bash", str(root / "scripts" / "install_analytics_cron.sh"), "--print"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    lines = out.strip().splitlines()
    assert lines[0] == "CRON_TZ=Africa/Nairobi"
    assert lines[1].startswith("40 09 * * * ") and lines[1].endswith("run_analytics_jobs.sh daily")
    assert lines[2].startswith("10 10 * * * ") and lines[2].endswith("fundamentals")
    assert lines[3].startswith("30 10 * * 6 ") and lines[3].endswith("weekly")
    assert (root / "scripts" / "run_analytics_jobs.sh").exists()
