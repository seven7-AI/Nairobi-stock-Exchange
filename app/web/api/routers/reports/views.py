"""Market reports — list runs, read artifacts, trigger generation.

Generation is dispatched to Celery rather than run inline: a full daily
pipeline reads a year of history for every instrument and would hold the
request open for far too long.

Triggering is restricted to analyst-and-above. Reading is open to every
research role, including ``research_viewer``.

    codegraph explore "reports views.py generate_report_task ReportRun StorageService"
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.web.api.deps import CurrentUser, SessionDep, StorageDep
from app.web.api.pagination import Cursor, CursorPage, PageSize, decode_cursor
from app.web.api.routers.reports.schema import (
    GenerateReportRequest,
    GenerateReportResponse,
    ReportArtifact,
    ReportArtifactList,
    ReportRunRead,
)
from app.web.core.exceptions import ResourceNotFoundError
from app.web.core.security import require_roles
from app.web.db.models.enums import ReportKind, UserRole
from app.web.db.services import report_service
from app.web.utils.datetime_utils import cursor_datetime
from app.web.utils.logger import get_logger

router = APIRouter(prefix="/reports", tags=["reports"])
logger = get_logger("app.web.api.reports")

#: Reading a report is broad; asking the platform to build one is not.
READ_ROLES = (
    UserRole.PLATFORM_ADMIN,
    UserRole.ORG_ADMIN,
    UserRole.ANALYST,
    UserRole.PORTFOLIO_MANAGER,
    UserRole.TRADER,
    UserRole.RESEARCH_VIEWER,
)
GENERATE_ROLES = (UserRole.PLATFORM_ADMIN, UserRole.ORG_ADMIN, UserRole.ANALYST)

ReportReader = Depends(require_roles(*READ_ROLES))
ReportGenerator = Depends(require_roles(*GENERATE_ROLES))


@router.get("/runs", response_model=CursorPage[ReportRunRead])
async def list_runs(
    session: SessionDep,
    page_size: PageSize = 50,
    cursor: Cursor = None,
    kind: ReportKind | None = Query(default=None),
    current_user: CurrentUser = ReportReader,
) -> CursorPage[ReportRunRead]:
    """Report generation history for the caller's organization."""
    created_before = cursor_datetime(decode_cursor(cursor)) if cursor else None
    organization_id = (
        None if current_user.can_read_across_organizations else current_user.organization_id
    )
    rows = await report_service.list_report_runs(
        session,
        limit=page_size + 1,
        kind=kind,
        organization_id=organization_id,
        created_before=created_before,
    )
    items = [ReportRunRead.model_validate(row) for row in rows]
    return CursorPage.build(
        items,
        page_size=page_size,
        cursor_for=lambda item: {"created_at": item.created_at.isoformat()},
    )


@router.get("/runs/{run_id}", response_model=ReportRunRead)
async def read_run(
    run_id: uuid.UUID, session: SessionDep, current_user: CurrentUser = ReportReader
) -> ReportRunRead:
    """One report run."""
    run = await report_service.get_report_run(session, run_id)
    if run is None:
        raise ResourceNotFoundError(detail=f"report run {run_id}")
    if run.organization_id is not None:
        current_user.assert_can_access_organization(run.organization_id)
    return ReportRunRead.model_validate(run)


@router.get("/{kind}", response_model=ReportArtifactList)
async def list_artifacts(
    kind: ReportKind, storage: StorageDep, current_user: CurrentUser = ReportReader
) -> ReportArtifactList:
    """Available generated reports of one kind, newest first."""
    names = [path.stem for path in storage.list_reports(kind)]
    return ReportArtifactList(kind=kind, names=names, count=len(names))


@router.get("/{kind}/{name}", response_model=ReportArtifact)
async def read_artifact(
    kind: ReportKind, name: str, storage: StorageDep, current_user: CurrentUser = ReportReader
) -> ReportArtifact:
    """Read one generated report. ``name`` is the file stem, e.g. ``2026-02-19``."""
    content = storage.read_report(kind, name)
    if content is None:
        raise ResourceNotFoundError(f"No {kind.value} report named {name}.")
    return ReportArtifact(kind=kind, name=name, content=content)


@router.post(
    "/generate", response_model=GenerateReportResponse, status_code=status.HTTP_202_ACCEPTED
)
async def generate_report(
    payload: GenerateReportRequest,
    session: SessionDep,
    current_user: CurrentUser = ReportGenerator,
) -> GenerateReportResponse:
    """Queue report generation and return immediately with a run id."""
    run = await report_service.create_report_run(
        session,
        kind=payload.kind,
        organization_id=current_user.organization_id,
        requested_by_user_id=current_user.id,
        triggered_by="api",
    )
    # Flush so the worker can load the row it is about to be handed.
    await session.flush()

    from app.celery_app.tasks.report_tasks import generate_report_task

    task = generate_report_task.delay(str(run.id), payload.kind.value)
    logger.info(
        "report_generation_queued",
        run_id=str(run.id),
        kind=payload.kind.value,
        task_id=str(task.id),
    )
    return GenerateReportResponse(
        run_id=run.id,
        kind=payload.kind,
        status=run.status,
        task_id=str(task.id),
        message="Report generation queued.",
    )


__all__ = ["router"]
