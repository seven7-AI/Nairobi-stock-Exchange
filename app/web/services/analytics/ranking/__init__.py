"""Composite ranking: overall score, classification, value-trap and compounder detectors.

codegraph explore "rank_universe compute_rankings Ranking"
"""

from __future__ import annotations

from app.web.services.analytics.ranking.engine import (
    CLASSES,
    Detector,
    FactorInput,
    Ranking,
    TrapRisk,
    rank_universe,
)
from app.web.services.analytics.ranking.service import RankingRunResult, compute_rankings

__all__ = [
    "CLASSES",
    "Detector",
    "FactorInput",
    "Ranking",
    "RankingRunResult",
    "TrapRisk",
    "compute_rankings",
    "rank_universe",
]
