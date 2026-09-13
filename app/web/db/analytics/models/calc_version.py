"""CalcVersion - the exact configuration a result was computed with.

Every metric, score, valuation, forecast and backtest row points at one of
these. When the risk-free rate, a factor weight or a threshold changes, a new
row is created and the old results keep pointing at the old one - nothing is
silently overwritten and every historical number stays explainable.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.web.db.analytics.base import AnalyticsBase
from app.web.db.analytics.models.mixins import CreatedAtMixin, IntIdMixin


class CalcVersion(IntIdMixin, CreatedAtMixin, AnalyticsBase):
    """A named, hashed configuration snapshot."""

    __tablename__ = "calc_versions"
    __table_args__ = (UniqueConstraint("name", "config_hash", name="uq_calc_version_name_hash"),)

    #: What the configuration is for: "analytics" for the engine-wide config,
    #: or a narrower name such as "factor-model".
    name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: Human-readable version label carried by the config (e.g. "1.0").
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    #: sha256 of the canonical JSON of the configuration.
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    def __repr__(self) -> str:
        return f"<CalcVersion {self.name} v{self.version} {self.config_hash[:8]}>"


__all__ = ["CalcVersion"]
