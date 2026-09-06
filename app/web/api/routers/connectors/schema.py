"""Connector schemas.

No schema here exposes a credential. ``credential_ref`` is a pointer into the
secret store; the secret itself never travels through this API.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.web.db.models.enums import ConnectorStatus, ConnectorType

#: Config keys that would smuggle a secret into a readable row.
FORBIDDEN_CONFIG_KEYS = frozenset(
    {"password", "secret", "token", "api_key", "apikey", "key", "credential"}
)


class ConnectorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    connector_type: ConnectorType
    status: ConnectorStatus
    name: str
    is_enabled: bool
    config: dict[str, Any]
    credential_ref: str | None
    last_synced_at: datetime | None
    last_error: str | None
    created_at: datetime


class ConnectorCreate(BaseModel):
    connector_type: ConnectorType
    name: str = Field(min_length=1, max_length=120)
    config: dict[str, Any] = Field(default_factory=dict)
    credential_ref: str | None = Field(
        default=None,
        description="Pointer into the secret store. Never the credential itself.",
    )

    @field_validator("config")
    @classmethod
    def _reject_inline_secrets(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Refuse secret-looking keys.

        ``config`` is readable by anyone who can read the organization, so a
        credential placed here would be exposed to every member of it.
        """
        offending = sorted(
            key for key in value if any(part in key.lower() for part in FORBIDDEN_CONFIG_KEYS)
        )
        if offending:
            raise ValueError(
                f"config must not contain secrets: {', '.join(offending)}. "
                "Store the secret externally and pass credential_ref instead."
            )
        return value


class ConnectorTestResult(BaseModel):
    connector_id: uuid.UUID
    status: ConnectorStatus
    reachable: bool
    message: str


__all__ = [
    "FORBIDDEN_CONFIG_KEYS",
    "ConnectorCreate",
    "ConnectorRead",
    "ConnectorTestResult",
]
