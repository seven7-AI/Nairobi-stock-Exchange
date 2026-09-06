"""Shared pytest fixtures.

Before adding a fixture here, query CodeGraph for what you are about to test:
``codegraph explore "<symbol>"`` — the blast radius names the callers you should
also be exercising.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Absolute repo root, so tests do not depend on the working directory."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def indicators_file(repo_root: Path) -> Path:
    """Path to the indicator reference file parsed by the registry."""
    return repo_root / "indicators.txt"
