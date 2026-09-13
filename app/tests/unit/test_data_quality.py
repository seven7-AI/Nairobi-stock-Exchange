"""Data quality: each check on injected defects, the finding lifecycle, the runner.

The runner tests use the real-data fixture and assert on the genuine defects it
carries (a decimal slip in the NSE 20 archive, two closes outside a zero-width
day range), then inject more and check they are found and later resolved.

    codegraph explore "run_data_quality reconcile_findings price_jumps"
"""

from __future__ import annotations

import gzip
import shutil
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.web.config import Settings
from app.web.db.analytics import analytics_session
from app.web.db.analytics.models import DataQualityFinding, JobRun, Severity
from app.web.db.analytics.services.data_quality import open_findings, reconcile_findings
from app.web.services.analytics.classification.service import classify_instruments
from app.web.services.analytics.config import DEFAULT_CONFIG, AnalyticsConfig, DataQualityConfig
from app.web.services.analytics.quality import checks
from app.web.services.analytics.quality.checks import Finding
from app.web.services.analytics.quality.runner import run_data_quality
from app.web.services.analytics.store import upgrade_analytics_db
from app.web.services.market_data.sources import NseScraperSource

pytestmark = pytest.mark.unit

CONFIG = DEFAULT_CONFIG


def obs(day: str, close: float, **extra: object) -> dict[str, object]:
    row: dict[str, object] = {"trade_date": day, "close_price": close, "quality_flags": []}
    row.update(extra)
    return row


# --- checks ---------------------------------------------------------------------------


def test_duplicate_observations() -> None:
    rows = [obs("2024-01-02", 10), obs("2024-01-02", 11), obs("2024-01-03", 12)]
    (finding,) = checks.duplicate_observations("X", rows)
    assert finding.severity is Severity.ERROR and finding.trade_date == date(2024, 1, 2)
    assert list(checks.duplicate_observations("X", rows[1:])) == []


def test_impossible_values() -> None:
    rows = [
        obs("2024-01-02", 0),
        obs("2024-01-03", 10, day_low=12, day_high=11),
        obs("2024-01-04", 20, day_low=9, day_high=11),
        obs("2024-01-05", 10, year_low=50, year_high=40),
        obs("2024-01-08", 10, volume=-5),
        obs("2024-01-09", 10.04, day_low=9, day_high=10),  # within rounding tolerance
    ]
    found = list(checks.impossible_values("X", rows, CONFIG))
    kinds = [(f.trade_date.isoformat(), f.severity.value) for f in found if f.trade_date]
    assert kinds == [
        ("2024-01-02", "error"),
        ("2024-01-03", "error"),
        ("2024-01-04", "warning"),
        ("2024-01-05", "warning"),
        ("2024-01-08", "error"),
    ]


def test_price_jumps_flagged_vs_unflagged() -> None:
    rows = [
        obs("2024-01-02", 100),
        obs("2024-01-03", 40),  # -60 %, unflagged
        obs("2024-01-04", 41),
        obs("2024-01-05", 10, quality_flags=["suspected_corporate_action"]),
    ]
    found = list(checks.price_jumps("X", rows, CONFIG))
    assert [(f.trade_date.isoformat(), f.severity.value) for f in found if f.trade_date] == [
        ("2024-01-03", "warning"),
        ("2024-01-05", "info"),
    ]
    assert found[0].context["change"] == pytest.approx(-0.6)
    tight = AnalyticsConfig(quality=DataQualityConfig(price_jump_threshold=0.01))
    assert len(list(checks.price_jumps("X", rows, tight))) == 3


def test_price_jumps_skip_non_positive_closes_and_data_gaps() -> None:
    rows = [obs("2024-01-02", 100), obs("2024-01-03", 0), obs("2024-01-04", 100)]
    assert list(checks.price_jumps("X", rows, CONFIG)) == []
    across_gap = [obs("2024-12-31", 10), obs("2026-07-26", 30)]
    assert list(checks.price_jumps("X", across_gap, CONFIG)) == []


def test_missing_periods_and_the_universe_gap() -> None:
    rows = [obs("2024-12-30", 1), obs("2024-12-31", 1), obs("2026-07-26", 1), obs("2026-07-27", 1)]
    (gap,) = checks.missing_periods("X", rows, CONFIG)
    assert gap.context == {"gap_start": "2024-12-31", "gap_end": "2026-07-26", "days": 572}
    assert list(checks.missing_periods("X", rows[:2], CONFIG)) == []
    spans = {f"T{i}": (date(2007, 1, 1), date(2026, 7, 27), 100) for i in range(12)}
    shared = [
        Finding("missing_periods", Severity.WARNING, "x", f"T{i}", None, gap.context)
        for i in range(6)
    ]
    (universe,) = checks.universe_gap(spans, shared, CONFIG)
    assert universe.severity is Severity.ERROR and universe.context["instruments"] == 6
    assert list(checks.universe_gap(spans, shared[:2], CONFIG)) == []


def test_zero_volume_streaks() -> None:
    config = AnalyticsConfig(quality=DataQualityConfig(zero_volume_streak_days=3))
    volumes = [0, 0, 0, 5, 0, 0, None, 0, 0, 0]
    rows = [
        obs(f"2024-01-{d:02d}", 1, volume=v) for d, v in zip(range(2, 12), volumes, strict=True)
    ]
    found = list(checks.zero_volume_streaks("X", rows, config))
    assert [(f.context["streak_start"], f.context["days"]) for f in found] == [
        ("2024-01-02", 3),
        ("2024-01-09", 3),
    ]
    # a missing volume (None) is not a zero
    assert all(f.severity is Severity.INFO for f in found)


def test_thin_history_and_stale_data() -> None:
    (thin,) = checks.thin_history("X", [obs("2024-01-02", 1)] * 5, CONFIG)
    assert thin.context == {"observations": 5}
    assert list(checks.thin_history("X", [], CONFIG)) == []
    now = datetime(2026, 9, 13, 12, tzinfo=UTC)
    assert list(checks.stale_data(date(2026, 9, 13), now, 36)) == []
    (stale,) = checks.stale_data(date(2026, 9, 1), now, 36)
    assert stale.severity is Severity.ERROR and stale.context["age_days"] == 12
    (none,) = checks.stale_data(None, now, 36)
    assert none.detail == "no observations at all"


def test_broken_scrape_and_unclassified() -> None:
    gate: dict[str, dict[str, object]] = {
        "stockanalysis_scraper": {"quality_ok": False, "failures": ["scraped 0 items"]},
        "afx": {"quality_ok": True},
    }
    (broken,) = checks.broken_scrape(gate)
    assert broken.severity is Severity.ERROR and "scraped 0 items" in broken.detail
    instruments = [{"ticker_symbol": "A"}, {"ticker_symbol": "B"}, {"ticker_symbol": "C"}]
    spans = {
        "A": (date(2007, 1, 1), date(2024, 12, 31), 10),
        "B": (date(2007, 1, 1), date(2024, 12, 31), 10),
    }
    classified: dict[str, list[tuple[date, date | None]]] = {
        "A": [(date(2007, 1, 1), None)],
        "B": [(date(2007, 1, 1), date(2020, 1, 1))],
    }
    (missing,) = checks.unclassified_instruments(instruments, classified, spans)
    assert missing.ticker_symbol == "B"


def test_balance_sheet_consistency() -> None:
    def row(item: str, value: float | None, end: str = "2024-12-31") -> dict[str, object]:
        return {
            "statement": "balance",
            "period_type": "annual",
            "fiscal_period_end": end,
            "line_item": item,
            "value": value,
        }

    good = [
        row("total_assets", 1000),
        row("total_liabilities", 800),
        row("shareholders_equity", 200),
    ]
    assert list(checks.balance_sheet_consistency("X", good, CONFIG)) == []
    bad = [row("total_assets", 1000), row("total_liabilities_and_equity", 900)]
    (finding,) = checks.balance_sheet_consistency("X", bad, CONFIG)
    assert finding.context["drift"] == pytest.approx(0.1)
    dash = [row("total_assets", 1000), row("total_liabilities_and_equity", None)]
    assert list(checks.balance_sheet_consistency("X", dash, CONFIG)) == []


def test_missing_fundamentals() -> None:
    span = (date(2007, 1, 1), date(2026, 9, 12), 100)
    (finding,) = checks.missing_fundamentals("X", False, span, date(2025, 1, 1))
    assert finding.severity is Severity.INFO
    assert list(checks.missing_fundamentals("X", True, span, date(2025, 1, 1))) == []
    delisted = (date(2007, 1, 1), date(2012, 12, 31), 5)
    assert list(checks.missing_fundamentals("X", False, delisted, date(2025, 1, 1))) == []


# --- lifecycle ----------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(ANALYTICS_DB_PATH=str(tmp_path / "a.sqlite3"))
    upgrade_analytics_db(s.analytics_db_path)
    return s


def test_findings_are_created_kept_open_and_resolved(settings: Settings) -> None:
    a = Finding("price_jumps", Severity.WARNING, "A jumped", "A", date(2024, 1, 3), {"change": 0.6})
    b = Finding("stale_data", Severity.ERROR, "stale", None, None, {})
    t0 = datetime(2026, 9, 13, 10, tzinfo=UTC)
    with analytics_session(settings) as session:
        first = reconcile_findings(session, [a, b], run_id=1, now=t0)
        assert (first.created, first.still_open, first.resolved) == (2, 0, 0)
        again = reconcile_findings(session, [a, b], run_id=2, now=t0 + timedelta(days=1))
        assert (again.created, again.still_open, again.resolved) == (0, 2, 0)
        third = reconcile_findings(session, [a], run_id=3, now=t0 + timedelta(days=2))
        assert (third.created, third.still_open, third.resolved) == (0, 1, 1)
    with analytics_session(settings) as session:
        rows = (
            session.execute(select(DataQualityFinding).order_by(DataQualityFinding.id))
            .scalars()
            .all()
        )
        assert len(rows) == 2
        jump, stale = rows
        assert jump.is_open and jump.last_seen_run_id == 3 and jump.first_seen_run_id == 1
        assert not stale.is_open and stale.resolved_at == t0 + timedelta(days=2)
        assert open_findings(session, severity="warning")[0].check_name == "price_jumps"
        # a resolved finding that comes back is a new row, so the history is kept
        reconcile_findings(session, [a, b], run_id=4, now=t0 + timedelta(days=3))
        assert len(session.execute(select(DataQualityFinding)).scalars().all()) == 3


# --- the runner on the real-data fixture ----------------------------------------


def _defective_copy(fixture_db_path: Path, target: Path) -> Path:
    shutil.copy(fixture_db_path, target)
    connection = sqlite3.connect(target)
    try:
        # a decimal-point slip on KCB, a zero close on EQTY, a corrupt balance sheet on SCOM
        connection.execute(
            "UPDATE stock_observations SET close_price = close_price * 10 "
            "WHERE ticker_symbol='KCB' AND trade_date='2019-06-14'"
        )
        connection.execute(
            "UPDATE stock_observations SET close_price = 0 "
            "WHERE ticker_symbol='EQTY' AND trade_date='2018-03-05'"
        )
        connection.execute(
            "UPDATE financial_statements SET value = value * 2 WHERE ticker_symbol='SCOM' "
            "AND statement='balance' AND line_item='total_assets' AND fiscal_label='FY 2025'"
        )
        connection.commit()
    finally:
        connection.close()
    return target


@pytest.fixture
def fixture_settings_with_store(fixture_db_path: Path, tmp_path: Path) -> Settings:
    s = Settings(
        NSE_SCRAPER_DB_PATH=str(fixture_db_path),
        NSE_SCRAPER_PATH=str(tmp_path / "scraper"),
        ANALYTICS_DB_PATH=str(tmp_path / "a.sqlite3"),
    )
    upgrade_analytics_db(s.analytics_db_path)
    return s


def test_fixture_reports_its_genuine_defects_and_nothing_else(
    fixture_settings_with_store: Settings, tmp_path: Path
) -> None:
    settings = fixture_settings_with_store
    source = NseScraperSource(settings)
    classify_instruments(settings, source)
    now = datetime(2026, 9, 13, 12, tzinfo=UTC)
    report = run_data_quality(settings, source, now=now, report_dir=tmp_path / "dq")

    assert report.instruments == 12
    assert "duplicate_observations" not in report.counts_by_check
    assert "unclassified_instruments" not in report.counts_by_check
    # two genuine archive inconsistencies: a close outside a zero-width day range
    impossible = sorted(
        (f.ticker_symbol, f.trade_date.isoformat())
        for f in report.findings
        if f.check == "impossible_values" and f.trade_date
    )
    assert impossible == [("KCB", "2022-07-26"), ("NCBA", "2022-12-13")]
    # a genuine decimal slip in the NSE 20 index archive (18,845 between 1,884 and 1,881)
    slip = [f for f in report.findings if f.check == "price_jumps" and f.ticker_symbol == "^N20I"]
    assert [f.trade_date.isoformat() for f in slip if f.trade_date] == ["2024-11-26", "2024-11-27"]
    # the 2007 KCB 10:1 split and the 2011 ABSA x0.26 step are jumps; a move across the
    # 2025 gap is not
    jumps = {(f.ticker_symbol, f.trade_date) for f in report.findings if f.check == "price_jumps"}
    assert ("KCB", date(2007, 4, 3)) in jumps and ("ABSA", date(2011, 5, 31)) in jumps
    assert not any(day == date(2026, 7, 26) for _, day in jumps)
    # the 2025 hole, once per surviving instrument and once for the universe
    gaps = [
        f
        for f in report.findings
        if f.check == "missing_periods" and f.context["gap_start"] == "2024-12-31"
    ]
    assert {f.ticker_symbol for f in gaps} >= {"KCB", "EQTY", "SCOM", "KEGN"}
    (universe,) = [f for f in report.findings if f.check == "universe_gap"]
    assert universe.context["gap_end"] == "2026-07-26" and universe.severity is Severity.ERROR
    # captured 2026-09-13; checked the same day, so not stale
    assert "stale_data" not in report.counts_by_check
    assert (tmp_path / "dq" / "2026-09-13.md").exists()
    assert (tmp_path / "dq" / "latest.md").exists()
    with analytics_session(settings) as session:
        run = session.execute(select(JobRun)).scalar_one()
        assert run.status == "succeeded"
        assert run.details is not None and run.details["findings"] == len(report.findings)
        assert run.finished_at is not None and run.finished_at.tzinfo is not None


def test_injected_defects_are_found_and_resolve_when_fixed(
    fixture_db_path: Path, tmp_path: Path
) -> None:
    defective = _defective_copy(fixture_db_path, tmp_path / "defective.sqlite3")
    settings = Settings(
        NSE_SCRAPER_DB_PATH=str(defective),
        NSE_SCRAPER_PATH=str(tmp_path / "scraper"),
        ANALYTICS_DB_PATH=str(tmp_path / "a.sqlite3"),
    )
    upgrade_analytics_db(settings.analytics_db_path)
    source = NseScraperSource(settings)
    classify_instruments(settings, source)
    now = datetime(2026, 9, 13, 12, tzinfo=UTC)
    report = run_data_quality(settings, source, now=now, report_dir=tmp_path / "dq")

    slip = [
        f
        for f in report.findings
        if f.check == "price_jumps"
        and f.ticker_symbol == "KCB"
        and f.trade_date in (date(2019, 6, 14), date(2019, 6, 17))
    ]
    assert len(slip) == 2  # up ten-fold, then back down
    zero = [
        f for f in report.findings if f.check == "impossible_values" and f.ticker_symbol == "EQTY"
    ]
    assert zero and zero[0].trade_date == date(2018, 3, 5)
    balance = [
        f
        for f in report.findings
        if f.check == "balance_sheet_consistency" and f.ticker_symbol == "SCOM"
    ]
    assert balance and balance[0].context["period_end"] == "2025-03-31"  # SCOM FY2025 ends March
    assert report.errors >= 2

    # fix the data, run again: the defect findings resolve, nothing duplicates
    fixed = Settings(
        NSE_SCRAPER_DB_PATH=str(fixture_db_path),
        NSE_SCRAPER_PATH=str(tmp_path / "scraper"),
        ANALYTICS_DB_PATH=str(tmp_path / "a.sqlite3"),
    )
    second = run_data_quality(
        fixed, NseScraperSource(fixed), now=now + timedelta(days=1), report_dir=tmp_path / "dq"
    )
    assert second.reconciled.created == 0
    assert second.reconciled.resolved >= 4
    with analytics_session(fixed) as session:
        eqty = session.execute(
            select(DataQualityFinding).where(
                DataQualityFinding.ticker_symbol == "EQTY",
                DataQualityFinding.check_name == "impossible_values",
            )
        ).scalars()
        assert not any(r.is_open for r in eqty)


def test_cli_dq_exit_code(
    fixture_settings_with_store: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from app.cli.main import app
    from app.web.config import get_settings

    settings = fixture_settings_with_store
    monkeypatch.setenv("ANALYTICS_DB_PATH", str(settings.analytics_db_path))
    monkeypatch.setenv("NSE_SCRAPER_DB_PATH", str(settings.scraper_database_path))
    monkeypatch.setenv("NSE_SCRAPER_PATH", str(settings.nse_scraper_path))
    get_settings.cache_clear()
    try:
        CliRunner().invoke(app, ["analytics", "classify"])
        result = CliRunner().invoke(app, ["analytics", "dq", "--fail-on", "never"])
        assert result.exit_code == 0, result.output
        assert "universe_gap" in result.output
        strict = CliRunner().invoke(app, ["analytics", "dq"])
        assert strict.exit_code == 1  # the universe gap is an error
    finally:
        get_settings.cache_clear()


@pytest.mark.realdata
def test_live_database_findings(live_source: NseScraperSource, tmp_path: Path) -> None:
    settings = Settings(ANALYTICS_DB_PATH=str(tmp_path / "live.sqlite3"))
    upgrade_analytics_db(settings.analytics_db_path)
    classify_instruments(settings, live_source)
    report = run_data_quality(settings, live_source, report_dir=tmp_path / "dq")
    assert report.instruments >= 102
    assert "universe_gap" in report.counts_by_check
    assert "duplicate_observations" not in report.counts_by_check
    assert "unclassified_instruments" not in report.counts_by_check
    assert report.counts_by_check.get("impossible_values", 0) >= 2


def test_fixture_is_the_shipped_one(fixture_db_path: Path, repo_root: Path) -> None:
    """Guard: the tests above assume the gz on disk is what conftest decompressed."""
    shipped = repo_root / "app" / "tests" / "fixtures" / "nse_fixture.sqlite3.gz"
    with gzip.open(shipped, "rb") as handle:
        assert handle.read(16) == fixture_db_path.read_bytes()[:16]
