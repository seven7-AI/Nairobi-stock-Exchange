"""The optional AI narrative layer over the research profile.

codegraph explore "narrate build_context check_numbers"
"""

from __future__ import annotations

from app.web.services.analytics.ai.narrative import (
    NarrativeClient,
    NarrativeResult,
    build_context,
    check_numbers,
    latest_narrative,
    narrate,
)

__all__ = [
    "NarrativeClient",
    "NarrativeResult",
    "build_context",
    "check_numbers",
    "latest_narrative",
    "narrate",
]
