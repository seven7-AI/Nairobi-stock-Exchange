"""Unit tests for the dashboard services that do not need a populated store: the
store-stamp cache, status sanitising, the cron pin, and the layering rule that keeps
the public surface away from platform data."""

from __future__ import annotations

import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path

from app.web.config import Settings
from app.web.services.dashboard.cache import DashboardCache, StoreStamp, file_mtime_ns, store_stamp
from app.web.services.dashboard.common import equity_universe, sanitise_text, severity_counts
from app.web.services.dashboard.status import CRON_SCHEDULE, CRON_TIMEZONE, _job_row
from app.web.services.jobs.status import JobLast

REPO = Path(__file__).resolve().parents[3]
DASHBOARD_PACKAGES = (REPO / "app/web/services/dashboard", REPO / "app/web/api/routers/dashboard")


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        ANALYTICS_DB_PATH=str(tmp_path / "a.sqlite3"),
        NSE_SCRAPER_DB_PATH=str(tmp_path / "s.sqlite3"),
        NSE_SCRAPER_PATH=str(tmp_path),
    )


def test_store_stamp_follows_both_files_and_their_wal(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert store_stamp(settings) == StoreStamp(0, 0)  # nothing on disk yet
    (tmp_path / "a.sqlite3").write_bytes(b"x")
    (tmp_path / "s.sqlite3").write_bytes(b"y")
    first = store_stamp(settings)
    assert first.analytics_mtime_ns > 0 and first.scraper_mtime_ns > 0
    wal = tmp_path / "a.sqlite3-wal"
    wal.write_bytes(b"w")
    os.utime(
        wal, ns=(first.analytics_mtime_ns + 5_000_000_000, first.analytics_mtime_ns + 5_000_000_000)
    )
    second = store_stamp(settings)
    assert (
        second.analytics_mtime_ns
        == file_mtime_ns(tmp_path / "a.sqlite3")
        > first.analytics_mtime_ns
    )
    assert second.scraper_mtime_ns == first.scraper_mtime_ns
    assert second.version != first.version and re.fullmatch(r"[0-9a-f]+-[0-9a-f]+", second.version)


def test_cache_hits_on_same_stamp_and_misses_on_change() -> None:
    cache = DashboardCache(max_age_seconds=60)
    calls = {"n": 0}

    def compute() -> int:
        calls["n"] += 1
        return calls["n"]

    stamp = StoreStamp(1, 1)
    assert cache.get_or_compute(("k",), stamp, compute) == 1
    assert cache.get_or_compute(("k",), stamp, compute) == 1
    assert cache.get_or_compute(("k",), StoreStamp(2, 1), compute) == 2
    assert cache.get_or_compute(("other",), StoreStamp(2, 1), compute) == 3
    assert cache.stats() == {"hits": 1, "misses": 3, "entries": 2}
    cache.clear()
    assert cache.stats()["entries"] == 0


def test_cache_expires_by_age_and_bounds_entries() -> None:
    cache = DashboardCache(max_age_seconds=0.0, max_entries=2)
    stamp = StoreStamp(1, 1)
    assert cache.get_or_compute(("a",), stamp, lambda: "1") == "1"
    assert cache.get_or_compute(("a",), stamp, lambda: "2") == "2"  # max_age 0 -> always recompute
    cache.get_or_compute(("b",), stamp, lambda: "b")
    cache.get_or_compute(("c",), stamp, lambda: "c")
    assert cache.stats()["entries"] == 2


def test_cache_is_thread_safe() -> None:
    cache = DashboardCache(max_age_seconds=60)
    stamp = StoreStamp(1, 1)
    results: list[int] = []

    def worker(i: int) -> None:
        results.append(cache.get_or_compute((i % 4,), stamp, lambda: i % 4))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(32)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(set(results)) == [0, 1, 2, 3] and cache.stats()["entries"] == 4


def test_cron_schedule_matches_the_installer() -> None:
    script = (REPO / "scripts/install_analytics_cron.sh").read_text()
    assert f'CRON_TZ_NAME="{CRON_TIMEZONE}"' in script
    for pipeline, expression, _ in CRON_SCHEDULE:
        if pipeline == "scrape":
            continue  # lives in the scraper repository's installer
        assert f'"{expression} ${{RUNNER}} {pipeline}"' in script, (pipeline, expression)


def test_job_row_strips_paths_and_keeps_only_safe_details() -> None:
    last = JobLast(
        "pipeline:daily",
        "failed",
        datetime(2026, 9, 16, 7, 0, tzinfo=UTC),
        datetime(2026, 9, 16, 7, 5, 30, tzinfo=UTC),
        "2026-09-16",
        0,
        "ExternalServiceError: could not open /home/kevin/nse-stock-scraper/data/x.sqlite3\n"
        "Traceback ...",
        {
            "steps": [
                {
                    "name": "returns",
                    "status": "failed",
                    "rows": 0,
                    "seconds": 1.0,
                    "reason": "boom at /srv/app/x.py",
                }
            ],
            "counts": {"failed": 1},
            "watermarks": {"observations": "2026-09-16:288041"},
            "force": False,
        },
    )
    row = _job_row(last)
    assert row.seconds == 330.0
    assert row.error == "ExternalServiceError: could not open <path>"
    assert set(row.details) == {"steps", "counts", "force"}  # watermarks never leave the process
    assert row.details["steps"][0]["reason"] == "boom at <path>"


def test_sanitise_text_and_severity_counts() -> None:
    assert sanitise_text(None) is None and sanitise_text("   ") is None
    assert sanitise_text("a" * 500, limit=10) == "a" * 10
    assert sanitise_text("first /tmp/x/y.txt\nsecond") == "first <path>"

    class F:
        def __init__(self, severity: str) -> None:
            self.severity = severity

    assert severity_counts([F("error"), F("warning"), F("warning"), F("info")]) == {
        "error": 1,
        "warning": 2,
        "info": 1,
    }


def test_equity_universe_excludes_indices_and_etfs() -> None:
    from datetime import date

    from app.web.db.analytics.models import Classification
    from app.web.services.analytics.classification.lookup import ClassificationIndex

    def row(ticker: str, code: str) -> Classification:
        return Classification(
            ticker_symbol=ticker,
            sector_code=code,
            sector_label=code.title(),
            industry=None,
            valid_from=date(2007, 1, 1),
            valid_to=None,
            source="test",
            evidence="",
        )

    index = ClassificationIndex(
        [
            row("KCB", "banking"),
            row("^NASI", "indices"),
            row("GLD", "etf"),
            row("SCOM", "telecommunication"),
        ]
    )
    assert equity_universe(index, date(2024, 12, 31)) == ["KCB", "SCOM"]


def test_dashboard_packages_never_reach_platform_data() -> None:
    """The public surface reads SQLite only: no platform ORM models, no Postgres
    session, no Redis, no Supabase, no settings dump."""
    forbidden = re.compile(
        r"app\.web\.db\.models|SessionDep|get_async_session|RedisDep|SupabaseDep|supabase_client|model_dump\(\)"
    )
    offenders = []
    for package in DASHBOARD_PACKAGES:
        for path in package.rglob("*.py"):
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                if forbidden.search(line):
                    offenders.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")
    assert offenders == []
