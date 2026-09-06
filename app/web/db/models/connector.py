"""Connector — a data-source integration configured per organization.

``config`` holds non-secret settings only. Credentials live in the secret store
and are referenced by ``credential_ref``; a raw key must never be written here,
because this row is readable by anyone who can read the organization.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.web.db.base import Base
from app.web.db.models.base import TimestampMixin, UUIDMixin
from app.web.db.models.enums import ConnectorStatus, ConnectorType, pg_enum

if TYPE_CHECKING:
    from app.web.db.models.organization import Organization


class Connector(UUIDMixin, TimestampMixin, Base):
    """An organization's configured link to an upstream data source."""

    __tablename__ = "connectors"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connector_type: Mapped[ConnectorType] = mapped_column(
        pg_enum(ConnectorType, "connector_type"), nullable=False
    )
    status: Mapped[ConnectorStatus] = mapped_column(
        pg_enum(ConnectorStatus, "connector_status"),
        nullable=False,
        default=ConnectorStatus.UNCONFIGURED,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    #: Non-secret configuration only.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    #: Pointer into the secret store. NEVER the credential itself.
    credential_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="connectors")

    def __repr__(self) -> str:
        return f"<Connector {self.connector_type} org={self.organization_id}>"


__all__ = ["Connector"]
