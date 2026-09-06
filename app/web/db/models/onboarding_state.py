"""Onboarding wizard progress — one row per organization.

The wizard has seven steps and is strictly ordered, except that step 5
(data connectors) may be skipped.

    codegraph explore "OnboardingState ONBOARDING_STEPS onboarding views.py"
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.web.db.base import Base
from app.web.db.models.base import TimestampMixin, UUIDMixin
from app.web.db.models.enums import OnboardingStatus, pg_enum

if TYPE_CHECKING:
    from app.web.db.models.organization import Organization

#: Ordered wizard steps. The index + 1 is the step number stored on the row.
ONBOARDING_STEPS: tuple[str, ...] = (
    "organization_profile",
    "team_invitations",
    "market_coverage",
    "watchlist_setup",
    "data_connectors",
    "report_preferences",
    "review_activate",
)

TOTAL_ONBOARDING_STEPS: int = len(ONBOARDING_STEPS)

#: Steps that may be skipped without blocking completion.
OPTIONAL_ONBOARDING_STEPS: frozenset[int] = frozenset({5})


class OnboardingState(UUIDMixin, TimestampMixin, Base):
    """Tracks how far an organization has progressed through the wizard."""

    __tablename__ = "onboarding_state"
    __table_args__ = (
        CheckConstraint(
            f"current_step >= 1 AND current_step <= {TOTAL_ONBOARDING_STEPS}",
            name="current_step_in_range",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    completed_steps: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, default=list
    )
    skipped_steps: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False, default=list)
    status: Mapped[OnboardingStatus] = mapped_column(
        pg_enum(OnboardingStatus, "onboarding_status"),
        nullable=False,
        default=OnboardingStatus.NOT_STARTED,
    )
    step_data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    last_completed_step_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="onboarding_state")

    def is_step_complete(self, step: int) -> bool:
        return step in self.completed_steps or step in self.skipped_steps

    def can_start_step(self, step: int) -> bool:
        """A step is reachable only once every prior step is complete or skipped."""
        return all(self.is_step_complete(prior) for prior in range(1, step))

    def __repr__(self) -> str:
        return f"<OnboardingState org={self.organization_id} step={self.current_step}>"


__all__ = [
    "ONBOARDING_STEPS",
    "OPTIONAL_ONBOARDING_STEPS",
    "TOTAL_ONBOARDING_STEPS",
    "OnboardingState",
]
