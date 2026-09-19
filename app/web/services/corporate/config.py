"""Thresholds that shape corporate facts, hashed separately from the analytics config.

``AnalyticsConfig.config_hash()`` is part of every job-step fingerprint
(``app/web/services/jobs/runner.py``). Nesting these numbers there would change
that hash and force a one-off recompute of every existing pipeline, so the
corporate layer versions its own configuration under ``calc_versions.name ==
"corporate"``.

    codegraph explore "CorporateConfig register_corporate_version register_calc_version"
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.web.db.analytics.models.calc_version import CalcVersion

#: Bump when the *meaning* of a threshold or of an extraction rule changes.
CORPORATE_CONFIG_VERSION = "1.0"

CALC_VERSION_NAME = "corporate"


class CorporateConfig(BaseModel):
    """Frozen, hashable. Every number here changes what is written as a fact."""

    model_config = ConfigDict(frozen=True)

    version: str = CORPORATE_CONFIG_VERSION

    # --- entity resolution -------------------------------------------------
    #: Token-set similarity at or above which two names in the same jurisdiction
    #: and group are the same entity (when no distinguishing token differs).
    fuzzy_accept: float = Field(default=0.92, ge=0.5, le=1.0)
    #: The runner-up must score at or below this, else the match is ambiguous.
    fuzzy_margin_below: float = Field(default=0.80, ge=0.0, le=1.0)
    #: Below this a fact goes to the review queue instead of being trusted.
    low_confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    gleif_cache_ttl_days: int = Field(default=7, ge=1)

    # --- validation --------------------------------------------------------
    #: |sum of segments - consolidated| / consolidated above this is a finding.
    segment_sum_tolerance: float = Field(default=0.01, ge=0.0, le=1.0)

    # --- universe status rules ------------------------------------------------
    listed_observation_days: int = Field(default=30, ge=1)
    delist_missing_runs: int = Field(default=3, ge=1)
    delist_missing_days: int = Field(default=60, ge=1)

    # --- events ----------------------------------------------------------------
    event_dedupe_days: int = Field(default=30, ge=1)
    event_verify_window_days: int = Field(default=365, ge=1)
    event_candidate_ttl_days: int = Field(default=540, ge=1)
    event_min_score: float = Field(default=0.6, ge=0.0, le=1.0)

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def config_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


DEFAULT_CORPORATE_CONFIG = CorporateConfig()


def register_corporate_version(session: Session, config: CorporateConfig) -> CalcVersion:
    """Get-or-create the ``calc_versions`` row for this exact corporate configuration."""
    digest = config.config_hash()
    existing = session.execute(
        select(CalcVersion).where(
            CalcVersion.name == CALC_VERSION_NAME, CalcVersion.config_hash == digest
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = CalcVersion(
        name=CALC_VERSION_NAME,
        version=config.version,
        config_hash=digest,
        config_json=config.as_dict(),
    )
    session.add(row)
    session.flush()
    return row


__all__ = [
    "CALC_VERSION_NAME",
    "CORPORATE_CONFIG_VERSION",
    "DEFAULT_CORPORATE_CONFIG",
    "CorporateConfig",
    "register_corporate_version",
]
