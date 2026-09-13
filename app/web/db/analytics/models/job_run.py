"""JobRun - one execution of one analytics job.

The job runner (``app/web/services/jobs``) opens a row before it starts, and
closes it with a status, a watermark and counts. Re-running a job reads the
last succeeded watermark to skip inputs it has already consumed; a failed row
keeps its error so ``nse-analysis analytics jobs status`` can show why.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Date, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.web.db.analytics.base import AnalyticsBase
from app.web.db.analytics.models.mixins import IntIdMixin, UTCDateTime, utcnow


class JobStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class JobRun(IntIdMixin, AnalyticsBase):
    """One attempt at running one job."""

    __tablename__ = "job_runs"

    job_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=JobStatus.RUNNING)
    started_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    #: The date the job computed "as of" - the latest observation it was allowed to see.
    as_of_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    #: Opaque marker of the newest input consumed (e.g. max trade_date), used to
    #: skip work when nothing upstream changed.
    watermark: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Free-form diagnostics: tickers processed/skipped and why, timings.
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<JobRun {self.job_name} {self.status} {self.started_at:%Y-%m-%d %H:%M}>"


__all__ = ["JobRun", "JobStatus"]
