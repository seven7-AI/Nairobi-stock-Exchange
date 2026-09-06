"""Data-source connectors configured per organization.

Administrative surface: only ``platform_admin`` and ``org_admin`` may see or
change how an organization pulls its data.

    codegraph explore "connectors views.py Connector SupabaseConnection health_check"
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.web.api.deps import CurrentUser, SessionDep, SettingsDep, SupabaseDep
from app.web.api.routers.connectors.schema import (
    ConnectorCreate,
    ConnectorRead,
    ConnectorTestResult,
)
from app.web.core.exceptions import ResourceNotFoundError
from app.web.core.security import ADMIN_ROLES, require_roles
from app.web.db.models.enums import ConnectorStatus, ConnectorType
from app.web.db.services import report_service
from app.web.utils.logger import get_logger

router = APIRouter(prefix="/connectors", tags=["connectors"])
logger = get_logger("app.web.api.connectors")

AdminUser = Depends(require_roles(*ADMIN_ROLES))


@router.get("", response_model=list[ConnectorRead])
async def list_connectors(
    session: SessionDep, current_user: CurrentUser = AdminUser
) -> list[ConnectorRead]:
    """Connectors configured for the caller's organization."""
    rows = await report_service.list_connectors(session, current_user.organization_id)
    return [ConnectorRead.model_validate(row) for row in rows]


@router.post("", response_model=ConnectorRead, status_code=status.HTTP_201_CREATED)
async def create_connector(
    payload: ConnectorCreate, session: SessionDep, current_user: CurrentUser = AdminUser
) -> ConnectorRead:
    """Configure a new data source. The org is taken from the caller's token."""
    connector = await report_service.create_connector(
        session,
        organization_id=current_user.organization_id,
        connector_type=payload.connector_type,
        name=payload.name,
        config=payload.config,
        credential_ref=payload.credential_ref,
    )
    logger.info(
        "connector_created",
        connector_id=str(connector.id),
        connector_type=payload.connector_type.value,
    )
    return ConnectorRead.model_validate(connector)


@router.get("/{connector_id}", response_model=ConnectorRead)
async def read_connector(
    connector_id: uuid.UUID, session: SessionDep, current_user: CurrentUser = AdminUser
) -> ConnectorRead:
    """Fetch one connector."""
    connector = await report_service.get_connector(session, connector_id)
    if connector is None:
        raise ResourceNotFoundError(detail=f"connector {connector_id}")
    current_user.assert_can_access_organization(connector.organization_id)
    return ConnectorRead.model_validate(connector)


@router.post("/{connector_id}/test", response_model=ConnectorTestResult)
async def test_connector(
    connector_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    supabase: SupabaseDep,
    current_user: CurrentUser = AdminUser,
) -> ConnectorTestResult:
    """Check that the upstream source is reachable and record the outcome."""
    connector = await report_service.get_connector(session, connector_id)
    if connector is None:
        raise ResourceNotFoundError(detail=f"connector {connector_id}")
    current_user.assert_can_access_organization(connector.organization_id)

    if connector.connector_type != ConnectorType.SUPABASE or supabase is None:
        await report_service.set_connector_status(
            session, connector, ConnectorStatus.UNCONFIGURED
        )
        return ConnectorTestResult(
            connector_id=connector.id,
            status=ConnectorStatus.UNCONFIGURED,
            reachable=False,
            message="No reachability check is implemented for this connector type.",
        )

    try:
        supabase.health_check(settings.stockanalysis_table)
    except Exception as exc:
        # The exception text can name the host and key; keep it out of the response.
        logger.warning(
            "connector_test_failed",
            connector_id=str(connector.id),
            error=type(exc).__name__,
        )
        await report_service.set_connector_status(
            session, connector, ConnectorStatus.ERROR, error=type(exc).__name__
        )
        return ConnectorTestResult(
            connector_id=connector.id,
            status=ConnectorStatus.ERROR,
            reachable=False,
            message="The upstream data source could not be reached.",
        )

    await report_service.set_connector_status(session, connector, ConnectorStatus.CONNECTED)
    return ConnectorTestResult(
        connector_id=connector.id,
        status=ConnectorStatus.CONNECTED,
        reachable=True,
        message="Connected.",
    )


__all__ = ["router"]
