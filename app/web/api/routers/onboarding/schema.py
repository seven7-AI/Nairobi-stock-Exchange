"""Onboarding wizard schemas — one payload model per step."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.web.db.models.enums import OnboardingStatus, UserRole


class OrganizationProfileStep(BaseModel):
    """Step 1."""

    legal_name: str = Field(min_length=2, max_length=255)
    country: str = Field(default="KE", min_length=2, max_length=2)
    timezone: str = Field(default="Africa/Nairobi", max_length=64)
    contact_email: EmailStr | None = None


class TeamInvitation(BaseModel):
    email: EmailStr
    role: UserRole


class TeamInvitationsStep(BaseModel):
    """Step 2."""

    invitations: list[TeamInvitation] = Field(default_factory=list, max_length=50)


class MarketCoverageStep(BaseModel):
    """Step 3."""

    exchanges: list[str] = Field(default=["NSE"], min_length=1)
    sectors: list[str] = Field(default_factory=list)


class WatchlistSetupStep(BaseModel):
    """Step 4."""

    name: str = Field(default="Default", min_length=1, max_length=120)
    tickers: list[str] = Field(default_factory=list, max_length=500)


class DataConnectorsStep(BaseModel):
    """Step 5 — optional, may be skipped."""

    connector_type: str
    name: str = Field(min_length=1, max_length=120)
    #: Non-secret settings only; a credential belongs in the secret store.
    config: dict[str, Any] = Field(default_factory=dict)


class ReportPreferencesStep(BaseModel):
    """Step 6."""

    daily_enabled: bool = True
    weekly_enabled: bool = True
    monthly_enabled: bool = True
    delivery_emails: list[EmailStr] = Field(default_factory=list, max_length=20)


class ReviewActivateStep(BaseModel):
    """Step 7."""

    confirmed: bool = Field(description="Must be true to activate the organization.")


class StepDescriptor(BaseModel):
    number: int
    name: str
    is_complete: bool
    is_skipped: bool
    is_optional: bool


class OnboardingStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: uuid.UUID
    current_step: int
    current_step_name: str
    completed_steps: list[int]
    skipped_steps: list[int]
    status: OnboardingStatus
    progress_percent: float
    total_steps: int
    steps: list[StepDescriptor]


__all__ = [
    "DataConnectorsStep",
    "MarketCoverageStep",
    "OnboardingStateRead",
    "OrganizationProfileStep",
    "ReportPreferencesStep",
    "ReviewActivateStep",
    "StepDescriptor",
    "TeamInvitation",
    "TeamInvitationsStep",
    "WatchlistSetupStep",
]
