"""Report schemas."""

from __future__ import annotations

import uuid
from datetime import date as date_type
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.web.db.models.enums import ReportKind, ReportRunStatus


class ReportRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: ReportKind
    status: ReportRunStatus
    period_start: date_type | None
    period_end: date_type | None
    started_at: datetime | None
    finished_at: datetime | None
    output_path: str | None
    triggered_by: str
    instruments_analyzed: int | None
    error_message: str | None
    summary: dict[str, Any]
    created_at: datetime


class ReportArtifact(BaseModel):
    """A generated markdown report."""

    kind: ReportKind
    name: str
    content: str


class ReportArtifactList(BaseModel):
    kind: ReportKind
    names: list[str]
    count: int


class GenerateReportRequest(BaseModel):
    kind: ReportKind


class GenerateReportResponse(BaseModel):
    run_id: uuid.UUID
    kind: ReportKind
    status: ReportRunStatus
    task_id: str | None = None
    message: str


__all__ = [
    "GenerateReportRequest",
    "GenerateReportResponse",
    "ReportArtifact",
    "ReportArtifactList",
    "ReportRunRead",
]
