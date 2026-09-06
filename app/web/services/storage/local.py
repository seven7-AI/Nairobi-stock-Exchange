"""Report artifact storage.

Local filesystem today. The interface is deliberately narrow so an object-store
backend can replace it without touching callers.
"""

from __future__ import annotations

from pathlib import Path

from app.web.config import Settings
from app.web.db.models.enums import ReportKind


class StorageService:
    """Resolves and reads the markdown report artifacts on disk."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def directory_for(self, kind: ReportKind) -> Path:
        return {
            ReportKind.DAILY: self._settings.reports_dir,
            ReportKind.WEEKLY: self._settings.weekly_reports_dir,
            ReportKind.MONTHLY: self._settings.monthly_reports_dir,
        }[kind]

    def list_reports(self, kind: ReportKind) -> list[Path]:
        """Newest first."""
        directory = self.directory_for(kind)
        if not directory.exists():
            return []
        return sorted(directory.glob("*.md"), reverse=True)

    def read_report(self, kind: ReportKind, name: str) -> str | None:
        """Read one report by file stem. Returns ``None`` if it does not exist.

        ``name`` is resolved strictly inside the report directory, so a caller
        cannot traverse out of it with ``..`` or an absolute path.
        """
        directory = self.directory_for(kind).resolve()
        candidate = (directory / f"{name}.md").resolve()
        if directory not in candidate.parents:
            return None
        if not candidate.is_file():
            return None
        return candidate.read_text(encoding="utf-8")


__all__ = ["StorageService"]
