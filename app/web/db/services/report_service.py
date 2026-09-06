"""Report run and connector persistence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from datetime import date as date_type
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.web.db.models.connector import Connector
from app.web.db.models.enums import (
    ConnectorStatus,
    ConnectorType,
    ReportKind,
    ReportRunStatus,
)
from app.web.db.models.report_run import ReportRun


async def create_report_run(
    session: AsyncSession,
    *,
    kind: ReportKind,
    organization_id: uuid.UUID | None = None,
    requested_by_user_id: uuid.UUID | None = None,
    period_start: date_type | None = None,
    period_end: date_type | None = None,
    triggered_by: str = "api",
) -> ReportRun:
    run = ReportRun(
        kind=kind,
        organization_id=organization_id,
        requested_by_user_id=requested_by_user_id,
        period_start=period_start,
        period_end=period_end,
        triggered_by=triggered_by,
        status=ReportRunStatus.PENDING,
    )
    session.add(run)
    await session.flush()
    return run


async def get_report_run(session: AsyncSession, run_id: uuid.UUID) -> ReportRun | None:
    return await session.get(ReportRun, run_id)


async def list_report_runs(
    session: AsyncSession,
    *,
    limit: int,
    kind: ReportKind | None = None,
    organization_id: uuid.UUID | None = None,
    created_before: datetime | None = None,
) -> list[ReportRun]:
    stmt = select(ReportRun)
    if kind is not None:
        stmt = stmt.where(ReportRun.kind == kind)
    if organization_id is not None:
        stmt = stmt.where(ReportRun.organization_id == organization_id)
    if created_before is not None:
        stmt = stmt.where(ReportRun.created_at < created_before)
    stmt = stmt.order_by(ReportRun.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def mark_running(session: AsyncSession, run: ReportRun) -> ReportRun:
    run.status = ReportRunStatus.RUNNING
    run.started_at = datetime.now(tz=UTC)
    await session.flush()
    return run


async def mark_succeeded(
    session: AsyncSession,
    run: ReportRun,
    *,
    output_path: str,
    instruments_analyzed: int,
    summary: dict[str, Any] | None = None,
) -> ReportRun:
    run.status = ReportRunStatus.SUCCEEDED
    run.finished_at = datetime.now(tz=UTC)
    run.output_path = output_path
    run.instruments_analyzed = instruments_analyzed
    run.summary = summary or {}
    await session.flush()
    return run


async def mark_failed(session: AsyncSession, run: ReportRun, *, error: str) -> ReportRun:
    run.status = ReportRunStatus.FAILED
    run.finished_at = datetime.now(tz=UTC)
    run.error_message = error
    await session.flush()
    return run


# --- connectors -------------------------------------------------------------
async def list_connectors(session: AsyncSession, organization_id: uuid.UUID) -> list[Connector]:
    result = await session.execute(
        select(Connector)
        .where(Connector.organization_id == organization_id)
        .order_by(Connector.created_at.desc())
    )
    return list(result.scalars().all())


async def get_connector(session: AsyncSession, connector_id: uuid.UUID) -> Connector | None:
    return await session.get(Connector, connector_id)


async def create_connector(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    connector_type: ConnectorType,
    name: str,
    config: dict[str, Any],
    credential_ref: str | None = None,
) -> Connector:
    connector = Connector(
        organization_id=organization_id,
        connector_type=connector_type,
        name=name,
        config=config,
        credential_ref=credential_ref,
        status=ConnectorStatus.UNCONFIGURED,
    )
    session.add(connector)
    await session.flush()
    return connector


async def set_connector_status(
    session: AsyncSession,
    connector: Connector,
    status: ConnectorStatus,
    *,
    error: str | None = None,
) -> Connector:
    connector.status = status
    connector.last_error = error
    if status == ConnectorStatus.CONNECTED:
        connector.last_synced_at = datetime.now(tz=UTC)
    await session.flush()
    return connector


__all__ = [
    "create_connector",
    "create_report_run",
    "get_connector",
    "get_report_run",
    "list_connectors",
    "list_report_runs",
    "mark_failed",
    "mark_running",
    "mark_succeeded",
    "set_connector_status",
]
