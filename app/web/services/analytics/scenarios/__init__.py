"""Scenario engine: named what-ifs with their assumptions.

codegraph explore "scenario_outcomes compute_scenarios"
"""

from __future__ import annotations

from app.web.services.analytics.scenarios.engine import ScenarioOutcome, scenario_outcomes
from app.web.services.analytics.scenarios.service import compute_scenarios

__all__ = ["ScenarioOutcome", "compute_scenarios", "scenario_outcomes"]
