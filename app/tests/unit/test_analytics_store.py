"""The analytics store: its Alembic chain, pragmas and first three tables.

Runs the real migrations against a temporary SQLite file - the same code path
``nse-analysis analytics upgrade`` uses - rather than ``create_all``, so a
model/migration mismatch fails here before it reaches the drift probe.

    codegraph explore "upgrade_analytics_db analytics_db_status JobRun CalcVersion"
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from app.web.config import Settings
from app.web.db.analytics import AnalyticsBase, analytics_session, build_analytics_engine
from app.web.db.analytics.models import (
    CalcVersion,
    JobRun,
    JobStatus,
    ModelKind,
    ModelRegistryEntry,
    ModelStatus,
)
from app.web.services.analytics.store import (
    analytics_db_status,
    current_revision,
    downgrade_analytics_db,
    head_revision,
    upgrade_analytics_db,
)

pytestmark = pytest.mark.unit

EXPECTED_TABLES = {"job_runs", "calc_versions", "model_registry"}


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "nested" / "analytics.sqlite3"


@pytest.fixture
def settings(db_path: Path) -> Settings:
    return Settings(SUPABASE_URL="x", SUPABASE_KEY="y", ANALYTICS_DB_PATH=str(db_path))


# --- migrations ---------------------------------------------------------------


def test_upgrade_creates_the_file_and_every_table(db_path: Path) -> None:
    assert not db_path.exists()
    revision = upgrade_analytics_db(db_path)

    assert db_path.exists()
    assert revision == head_revision(db_path) is not None
    engine = build_analytics_engine(db_path)
    try:
        assert set(inspect(engine).get_table_names()) >= EXPECTED_TABLES
    finally:
        engine.dispose()


def test_upgrade_is_idempotent(db_path: Path) -> None:
    first = upgrade_analytics_db(db_path)
    second = upgrade_analytics_db(db_path)
    assert first == second == current_revision(db_path)


def test_downgrade_to_base_then_upgrade_round_trips(db_path: Path) -> None:
    upgrade_analytics_db(db_path)
    assert downgrade_analytics_db(db_path, "base") is None

    engine = build_analytics_engine(db_path)
    try:
        assert not (EXPECTED_TABLES & set(inspect(engine).get_table_names()))
    finally:
        engine.dispose()

    assert upgrade_analytics_db(db_path) == head_revision(db_path)


def test_migrations_and_models_describe_the_same_schema(db_path: Path) -> None:
    """The drift probe, in-process: autogenerate against the migrated file finds nothing."""
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    upgrade_analytics_db(db_path)
    engine = build_analytics_engine(db_path)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"compare_type": True, "compare_server_default": True}
            )
            diff = compare_metadata(context, AnalyticsBase.metadata)
    finally:
        engine.dispose()
    assert diff == [], diff


# --- engine ---------------------------------------------------------------------


def test_engine_enables_wal_and_foreign_keys(db_path: Path) -> None:
    upgrade_analytics_db(db_path)
    engine = build_analytics_engine(db_path)
    try:
        raw = engine.raw_connection()
        try:
            cursor = raw.cursor()
            assert cursor.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert cursor.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        finally:
            raw.close()
    finally:
        engine.dispose()


def test_status_reports_missing_file_without_creating_it(db_path: Path) -> None:
    report = analytics_db_status(db_path)
    assert report.exists is False
    assert report.current_revision is None
    assert report.head_revision is not None
    assert report.is_current is False
    assert not db_path.exists()


def test_status_counts_rows_per_table(settings: Settings) -> None:
    upgrade_analytics_db(settings.analytics_db_path)
    with analytics_session(settings) as session:
        session.add(JobRun(job_name="daily", status=JobStatus.SUCCEEDED, rows_written=3))
    report = analytics_db_status(settings.analytics_db_path)
    assert report.is_current
    assert report.tables["job_runs"] == 1
    assert report.tables["calc_versions"] == 0
    assert "alembic_version" not in report.tables


# --- tables --------------------------------------------------------------------


def _run(session: Session) -> JobRun:
    run = JobRun(
        job_name="daily",
        as_of_date=date(2024, 12, 31),
        watermark="2024-12-31",
        details={"processed": ["KCB"], "skipped": {"XYZ": "no observations"}},
    )
    session.add(run)
    session.flush()
    return run


def test_job_run_round_trips_with_utc_timestamps_and_json_details(settings: Settings) -> None:
    upgrade_analytics_db(settings.analytics_db_path)
    with analytics_session(settings) as session:
        run = _run(session)
        assert run.status == JobStatus.RUNNING
        run.status = JobStatus.SUCCEEDED
        run.finished_at = datetime.now(UTC)

    with analytics_session(settings) as session:
        stored = session.execute(select(JobRun)).scalar_one()
        assert stored.status == "succeeded"
        assert stored.started_at.year >= 2026
        assert stored.details == {"processed": ["KCB"], "skipped": {"XYZ": "no observations"}}
        assert stored.as_of_date == date(2024, 12, 31)


def test_calc_version_is_unique_per_name_and_hash(settings: Settings) -> None:
    upgrade_analytics_db(settings.analytics_db_path)
    with analytics_session(settings) as session:
        session.add(
            CalcVersion(name="analytics", version="1.0", config_hash="a" * 64, config_json={})
        )
    with pytest.raises(IntegrityError), analytics_session(settings) as session:
        session.add(
            CalcVersion(name="analytics", version="1.1", config_hash="a" * 64, config_json={})
        )
    with analytics_session(settings) as session:  # a different name with the same hash is fine
        session.add(
            CalcVersion(name="factor-model", version="1.0", config_hash="a" * 64, config_json={})
        )
        assert session.execute(select(CalcVersion)).scalars().all()


def test_model_registry_defaults_and_unique_version(settings: Settings) -> None:
    upgrade_analytics_db(settings.analytics_db_path)
    with analytics_session(settings) as session:
        session.add(ModelRegistryEntry(name="factor-model", version="1", kind=ModelKind.FACTOR))
    with analytics_session(settings) as session:
        entry = session.execute(select(ModelRegistryEntry)).scalar_one()
        assert entry.status == ModelStatus.CANDIDATE
        assert entry.features == []
        assert entry.params == {}
        assert entry.performance is None
    with pytest.raises(IntegrityError), analytics_session(settings) as session:
        session.add(ModelRegistryEntry(name="factor-model", version="1", kind=ModelKind.FACTOR))


def test_session_rolls_back_on_error(settings: Settings) -> None:
    upgrade_analytics_db(settings.analytics_db_path)
    with pytest.raises(RuntimeError), analytics_session(settings) as session:
        session.add(JobRun(job_name="weekly"))
        raise RuntimeError("boom")
    assert analytics_db_status(settings.analytics_db_path).tables["job_runs"] == 0


def test_store_is_a_plain_sqlite_file_readable_by_other_tools(db_path: Path) -> None:
    upgrade_analytics_db(db_path)
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        names = {row[0] for row in rows}
    finally:
        connection.close()
    assert names >= EXPECTED_TABLES


# --- CLI ---------------------------------------------------------------------


def test_cli_upgrade_then_status(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.cli.main import app

    monkeypatch.setenv("SUPABASE_URL", "x")
    monkeypatch.setenv("SUPABASE_KEY", "y")
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(db_path))
    from app.web.config import get_settings

    get_settings.cache_clear()
    try:
        runner = CliRunner()
        created = runner.invoke(app, ["analytics", "upgrade"])
        assert created.exit_code == 0, created.output
        assert "created" in created.output

        again = runner.invoke(app, ["analytics", "upgrade"])
        assert again.exit_code == 0, again.output
        assert "already at" in again.output

        status = runner.invoke(app, ["analytics", "status"])
        assert status.exit_code == 0, status.output
        assert "job_runs" in status.output
    finally:
        get_settings.cache_clear()
