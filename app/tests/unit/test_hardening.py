"""Failure scenarios and validation for the live system: a missing scraper database, a
locked analytics store, partial statements, an empty universe, the quality gate, the
migration chain step by step, and the no-secrets / no-os.environ rules.

codegraph explore "run_pipeline DataQualityGateError new_error_findings BUSY_TIMEOUT_SECONDS"
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import select

from app.tests.unit.test_nse_scraper_source import OBSERVATIONS_SCHEMA, SCHEMA
from app.web.config import Settings
from app.web.core.exceptions import ExternalServiceError
from app.web.db.analytics import analytics_session
from app.web.db.analytics import base as analytics_base
from app.web.db.analytics.models import DataQualityFinding, JobRun
from app.web.services.analytics.classification.service import classify_instruments
from app.web.services.analytics.config import AnalyticsConfig, DataQualityConfig
from app.web.services.analytics.fundamentals import compute_fundamentals
from app.web.services.analytics.research import build_profile
from app.web.services.analytics.store import (
    analytics_alembic_config,
    current_revision,
    downgrade_analytics_db,
    upgrade_analytics_db,
)
from app.web.services.jobs import run_pipeline
from app.web.services.jobs.pipelines import DAILY, DataQualityGateError
from app.web.services.jobs.runner import JobContext, Step, StepOutcome
from app.web.services.market_data.sources import NseScraperSource

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]


def _settings(tmp_path: Path, scraper_db: Path) -> Settings:
    return Settings(
        NSE_SCRAPER_DB_PATH=str(scraper_db),
        NSE_SCRAPER_PATH=str(tmp_path / "scraper"),
        ANALYTICS_DB_PATH=str(tmp_path / "a.sqlite3"),
    )


def test_missing_scraper_database_is_a_clean_domain_error(tmp_path: Path) -> None:
    settings = _settings(tmp_path, tmp_path / "does-not-exist.sqlite3")
    upgrade_analytics_db(settings.analytics_db_path)
    source = NseScraperSource(settings)
    with pytest.raises(ExternalServiceError, match="not available"):
        source.fetch_instruments()
    with pytest.raises(ExternalServiceError):
        run_pipeline(settings, source, "daily", as_of=date(2024, 12, 31))  # watermarks read first
    with analytics_session(settings) as session:
        assert session.execute(select(JobRun)).scalars().all() == []  # nothing half-recorded


def test_empty_universe_runs_to_completion_with_nothing_written(tmp_path: Path) -> None:
    db = tmp_path / "empty.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.executescript(SCHEMA + OBSERVATIONS_SCHEMA)
    settings = _settings(tmp_path, db)
    upgrade_analytics_db(settings.analytics_db_path)
    source = NseScraperSource(settings)
    classify_instruments(settings, source)
    result = run_pipeline(settings, source, "daily", as_of=date(2024, 12, 31))
    assert result.succeeded and result.counts == {"succeeded": len(DAILY)}
    assert all(s.rows_written == 0 for s in result.steps if s.name != "data_quality")
    weekly = run_pipeline(settings, source, "weekly", as_of=date(2024, 12, 31))
    assert weekly.succeeded
    assert build_profile(settings, "KCB") is None


def test_partial_statements_are_missing_not_zero(fixture_db_path: Path, tmp_path: Path) -> None:
    db = tmp_path / "partial.sqlite3"
    db.write_bytes(fixture_db_path.read_bytes())
    with sqlite3.connect(db) as conn:
        conn.execute(
            "delete from financial_statements where ticker_symbol = 'KCB' "
            "and statement in ('balance', 'cashflow')"
        )
        conn.commit()
    settings = _settings(tmp_path, db)
    upgrade_analytics_db(settings.analytics_db_path)
    source = NseScraperSource(settings)
    classify_instruments(settings, source)
    result = compute_fundamentals(
        settings, source, as_of=date(2024, 12, 31), tickers=["KCB", "EQTY"]
    )
    assert "KCB" in result.tickers_processed
    profile = build_profile(settings, "KCB")
    assert profile is not None
    quality = profile.metrics["quality"]
    assert quality["net_margin"]["status"] == "known"  # income statement still there
    assert quality["roe"]["status"] == "missing" and "equity" in quality["roe"]["reason"]
    assert quality["fcf"]["status"] == "missing" and quality["fcf"]["value"] is None
    equity = build_profile(settings, "EQTY")
    assert equity is not None and equity.metrics["quality"]["roe"]["status"] == "known"


def test_locked_store_waits_then_fails_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "a.sqlite3"
    upgrade_analytics_db(db)
    monkeypatch.setattr(analytics_base, "BUSY_TIMEOUT_SECONDS", 1)
    settings = Settings(ANALYTICS_DB_PATH=str(db))
    holder = sqlite3.connect(db, isolation_level=None)
    holder.execute("begin immediate")  # the single SQLite writer, held elsewhere
    holder.execute(
        "insert into calc_versions (name, version, config_hash, config_json, created_at) "
        "values ('x', '1', 'h', '{}', '2026-01-01')"
    )
    try:
        with pytest.raises(Exception, match="locked"), analytics_session(settings) as session:
            session.add(JobRun(job_name="probe", started_at=datetime.now(UTC)))
            session.flush()
    finally:
        holder.execute("rollback")
        holder.close()
    # released: the same write now succeeds
    with analytics_session(settings) as session:
        session.add(JobRun(job_name="probe", started_at=datetime.now(UTC)))
        session.flush()
    with analytics_session(settings) as session:
        assert session.execute(select(JobRun)).scalars().one().job_name == "probe"


def test_quality_gate_halts_on_new_errors_and_can_be_overridden(
    fixture_db_path: Path, tmp_path: Path
) -> None:
    db = tmp_path / "defect.sqlite3"
    db.write_bytes(fixture_db_path.read_bytes())
    settings = _settings(tmp_path, db)
    upgrade_analytics_db(settings.analytics_db_path)
    source = NseScraperSource(settings)
    classify_instruments(settings, source)
    # a first run establishes the known findings
    first = run_pipeline(settings, source, "daily", as_of=date(2019, 12, 31), steps=[DAILY[0]])
    assert first.succeeded
    # then the next scrape lands a broken KCB row (day low above day high, close
    # outside the range): new rows move the input watermark, the quality step reruns
    # and finds a new error-severity defect
    with sqlite3.connect(db) as conn:
        conn.execute(
            "insert into stock_observations (ticker_symbol, trade_date, source_ticker, "
            "company_name, close_price, day_low, day_high, data_source, quality_flags, "
            "created_at, updated_at) select ticker_symbol, '2026-09-14', source_ticker, "
            "company_name, close_price * 10, day_high, day_low, data_source, '[]', "
            "created_at, updated_at from stock_observations where ticker_symbol = 'KCB' "
            "and day_low < day_high order by trade_date desc limit 1"
        )
        conn.commit()
    gated = run_pipeline(
        settings, source, "daily", as_of=date(2019, 12, 31), steps=[DAILY[0], DAILY[1]]
    )
    assert not gated.succeeded
    assert gated.steps[0].status == "failed" and "new error-severity finding" in (
        gated.steps[0].reason or ""
    )
    assert "--ignore-quality-gate" in (gated.steps[0].reason or "")
    assert gated.steps[1].status == "skipped" and gated.steps[1].reason == "an upstream step failed"
    with analytics_session(settings) as session:
        new_errors = (
            session.execute(
                select(DataQualityFinding).where(
                    DataQualityFinding.severity == "error",
                    DataQualityFinding.ticker_symbol == "KCB",
                )
            )
            .scalars()
            .all()
        )
        assert new_errors
    forced = run_pipeline(
        settings,
        source,
        "daily",
        as_of=date(2019, 12, 31),
        steps=[DAILY[0], DAILY[1]],
        ignore_quality_gate=True,
    )
    assert forced.succeeded and forced.steps[1].status == "succeeded"
    lenient = AnalyticsConfig(quality=DataQualityConfig(halt_on_new_errors=0))
    # the finding is no longer new on a rerun, and the gate is off anyway
    relaxed = run_pipeline(
        settings,
        source,
        "daily",
        as_of=date(2019, 12, 31),
        steps=[DAILY[0]],
        config=lenient,
        force=True,
    )
    assert relaxed.succeeded


def test_step_failure_error_is_recorded_not_raised(tmp_path: Path, fixture_db_path: Path) -> None:
    settings = _settings(tmp_path, fixture_db_path)
    upgrade_analytics_db(settings.analytics_db_path)
    source = NseScraperSource(settings)

    def broken(ctx: JobContext) -> StepOutcome:
        raise DataQualityGateError("3 new error-severity finding(s)")

    result = run_pipeline(
        settings, source, "custom", as_of=date(2019, 12, 31), steps=[Step("gate", broken)]
    )
    assert result.steps[0].status == "failed"
    assert result.steps[0].reason == "DataQualityGateError: 3 new error-severity finding(s)"
    with analytics_session(settings) as session:
        rows = {r.job_name: r for r in session.execute(select(JobRun)).scalars()}
        assert rows["step:gate"].status == "failed" and rows["pipeline:custom"].status == "failed"


def test_migration_chain_walks_down_and_up_one_step_at_a_time(tmp_path: Path) -> None:
    db = tmp_path / "chain.sqlite3"
    head = upgrade_analytics_db(db)
    script = ScriptDirectory.from_config(analytics_alembic_config(db))
    revisions = [r.revision for r in script.walk_revisions()]  # head first
    assert head == revisions[0] and len(revisions) >= 13
    for revision in revisions[1:]:
        assert downgrade_analytics_db(db, revision) == revision
    assert downgrade_analytics_db(db, "base") is None
    for revision in reversed(revisions):
        assert upgrade_analytics_db(db, revision) == revision
    assert current_revision(db) == head


def test_no_os_environ_and_no_secret_literals_in_app_code() -> None:
    offenders: list[str] = []
    secret = re.compile(
        r"(sk-ant-[A-Za-z0-9_-]{8,}|sb[a-z]?_[A-Za-z0-9_-]{16,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})"
    )
    for path in (REPO / "app").rglob("*.py"):
        if "tests" in path.parts:
            continue
        text = path.read_text()
        for number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if (
                "os.environ" in line
                and not stripped.startswith(("#", '"', "'"))
                and "``os.environ``" not in line
            ):
                offenders.append(f"{path.relative_to(REPO)}:{number} os.environ")
            if secret.search(line):
                offenders.append(f"{path.relative_to(REPO)}:{number} secret-shaped literal")
    assert offenders == []


def test_settings_never_expose_keys_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    from app.web.utils.logger import get_logger

    logger = get_logger("test.hardening")
    with caplog.at_level("INFO"):
        logger.info(
            "probe",
            anthropic_api_key="sk-ant-secretsecretsecret",
            supabase_key="sb_secretsecretsecret",
            note="sk-ant-secretsecretsecret",
        )
    assert "secretsecret" not in caplog.text


def test_analytics_cli_runs_without_supabase_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cron chain runs `nse-analysis analytics …` with no Supabase environment at
    all (found by the first unattended 09:40 run): settings must not demand it."""
    from typer.testing import CliRunner

    from app.cli.main import app
    from app.web.config import get_settings

    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(tmp_path / "a.sqlite3"))
    get_settings.cache_clear()
    try:
        assert Settings().supabase_url == ""
        result = CliRunner().invoke(app, ["analytics", "upgrade"])
        assert result.exit_code == 0, result.output
    finally:
        get_settings.cache_clear()
