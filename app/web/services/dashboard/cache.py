"""A small in-process cache for dashboard payloads, keyed by the state of the two
SQLite files.

Every dashboard read is a handful of SQLite queries that only change when a job
writes the analytics store or the scraper writes its database. ``StoreStamp``
captures both files' modification times (WAL-aware: a write lands in ``-wal``
first), so an entry stays valid exactly as long as the data it was computed from.
A maximum age is a belt-and-braces bound, not the invalidation mechanism.
``functools.lru_cache`` is deliberately not used - it cannot see a file change.

    codegraph explore "DashboardCache store_stamp StoreStamp"
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from app.web.config import Settings

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class StoreStamp:
    """Modification times (ns) of the analytics store and the scraper database."""

    analytics_mtime_ns: int
    scraper_mtime_ns: int

    @property
    def version(self) -> str:
        return f"{self.analytics_mtime_ns:x}-{self.scraper_mtime_ns:x}"


def file_mtime_ns(path: Path) -> int:
    """The newest mtime among a SQLite file and its ``-wal`` journal; 0 when absent."""
    newest = 0
    for candidate in (path, path.with_name(path.name + "-wal")):
        try:
            newest = max(newest, candidate.stat().st_mtime_ns)
        except OSError:
            continue
    return newest


def store_stamp(settings: Settings) -> StoreStamp:
    """Four ``stat`` calls; never opens a database."""
    return StoreStamp(
        analytics_mtime_ns=file_mtime_ns(settings.analytics_db_path),
        scraper_mtime_ns=file_mtime_ns(settings.scraper_database_path),
    )


@dataclass(slots=True)
class _Entry:
    stamp: StoreStamp
    stored_at: float
    value: Any


class DashboardCache:
    """``get_or_compute`` returns the cached value while the stamp is unchanged and the
    entry is younger than ``max_age_seconds``; otherwise it recomputes. The compute
    runs outside the lock, so two concurrent misses may both compute - harmless."""

    def __init__(self, *, max_age_seconds: float = 300.0, max_entries: int = 256) -> None:
        self._max_age = max_age_seconds
        self._max_entries = max_entries
        self._entries: dict[tuple[Any, ...], _Entry] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get_or_compute(
        self, key: tuple[Any, ...], stamp: StoreStamp, compute: Callable[[], T]
    ) -> T:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.stamp == stamp and now - entry.stored_at < self._max_age:
                self.hits += 1
                return entry.value
            self.misses += 1
        value = compute()
        with self._lock:
            if len(self._entries) >= self._max_entries:
                oldest = min(self._entries, key=lambda k: self._entries[k].stored_at)
                del self._entries[oldest]
            self._entries[key] = _Entry(stamp, time.monotonic(), value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"hits": self.hits, "misses": self.misses, "entries": len(self._entries)}


_CACHE: DashboardCache | None = None
_CACHE_LOCK = threading.Lock()


def get_dashboard_cache(settings: Settings) -> DashboardCache:
    """The process-wide cache (one uvicorn worker serves the dashboard)."""
    global _CACHE
    with _CACHE_LOCK:
        if _CACHE is None:
            _CACHE = DashboardCache(max_age_seconds=settings.dashboard_cache_max_age_seconds)
        return _CACHE


def reset_dashboard_cache() -> None:
    """Drop the process-wide cache (tests, or after settings change)."""
    global _CACHE
    with _CACHE_LOCK:
        _CACHE = None


__all__ = [
    "DashboardCache",
    "StoreStamp",
    "file_mtime_ns",
    "get_dashboard_cache",
    "reset_dashboard_cache",
    "store_stamp",
]
