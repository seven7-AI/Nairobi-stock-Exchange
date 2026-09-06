"""ReportRun — an execution record for a generated market report.

Written by both entry paths: the Celery task and the ``nse-analysis`` CLI.
``triggered_by`` records which one, and by whom when a user asked for it.
"""

from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.web.db.base import Base
from app.web.db.models.base import TimestampMixin, UUIDMixin
from app.web.db.models.enums import ReportKind, ReportRunStatus, pg_enum

if TYPE_CHECKING:
    from app.web.db.models.organization import Organization


class ReportRun(UUIDMixin, TimestampMixin, Base):
    """One attempt at generating one report."""

    __tablename__ = "report_runs"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    kind: Mapped[ReportKind] = mapped_column(
        pg_enum(ReportKind, "report_kind"), nullable=False, index=True
    )
    status: Mapped[ReportRunStatus] = mapped_column(
        pg_enum(ReportRunStatus, "report_run_status"),
        nullable=False,
        default=ReportRunStatus.PENDING,
        index=True,
    )
    period_start: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date_type | None] = mapped_column(Date, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    output_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(32), nullable=False, default="api")
    instruments_analyzed: Mapped[int | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    organization: Mapped[Organization | None] = relationship()

    def __repr__(self) -> str:
        return f"<ReportRun {self.kind} {self.status}>"


__all__ = ["ReportRun"]
