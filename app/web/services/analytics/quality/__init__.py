"""Automated data-quality checks over the canonical data.

codegraph explore "run_data_quality Finding reconcile_findings"
"""

from __future__ import annotations

from app.web.services.analytics.quality.checks import Finding
from app.web.services.analytics.quality.runner import DataQualityReport, run_data_quality

__all__ = ["DataQualityReport", "Finding", "run_data_quality"]
