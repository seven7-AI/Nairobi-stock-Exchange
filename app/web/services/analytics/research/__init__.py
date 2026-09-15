"""The research profile: every stored number about an instrument, with its status.

codegraph explore "build_profile render_profile ResearchProfile"
"""

from __future__ import annotations

from app.web.services.analytics.research.profile import (
    ResearchProfile,
    build_profile,
    render_profile,
)

__all__ = ["ResearchProfile", "build_profile", "render_profile"]
