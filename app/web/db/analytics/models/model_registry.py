"""ModelRegistryEntry - the research history of every scoring/forecast model.

Answers "which methodology produced this score?" and "did v2 beat v1 out of
sample?". A model is registered once per version; its performance is filled in
by the backtester or the forecast evaluator and its status moves
candidate -> active -> retired.
"""

from __future__ import annotations

from datetime import date as date_type
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Date, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.web.db.analytics.base import AnalyticsBase
from app.web.db.analytics.models.mixins import CreatedAtMixin, IntIdMixin


class ModelKind(StrEnum):
    FACTOR = "factor"
    FORECAST = "forecast"
    VALUATION = "valuation"
    REGIME = "regime"


class ModelStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    RETIRED = "retired"


class ModelRegistryEntry(IntIdMixin, CreatedAtMixin, AnalyticsBase):
    """One version of one model."""

    __tablename__ = "model_registry"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_model_registry_name_version"),)

    name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ModelStatus.CANDIDATE, index=True
    )
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    #: Inputs the model consumes (metric names, factor names).
    features: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    #: Weights, thresholds, hyper-parameters.
    params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    training_start: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    training_end: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    backtest_start: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    backtest_end: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    #: Out-of-sample performance summary as reported by the evaluator.
    performance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<Model {self.name} v{self.version} {self.status}>"


__all__ = ["ModelKind", "ModelRegistryEntry", "ModelStatus"]
