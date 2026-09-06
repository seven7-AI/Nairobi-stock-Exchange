from pathlib import Path

import pytest

from app.web.services.indicators.feasibility import analyze_feasibility, summarize_feasibility
from app.web.services.indicators.registry import build_indicator_map, parse_indicators


@pytest.mark.unit
def test_parse_indicators_reads_content(indicators_file: Path) -> None:
    indicators = parse_indicators(indicators_file)
    assert indicators
    names = {item.name for item in indicators}
    assert "Market Cap" in names


@pytest.mark.unit
def test_build_indicator_map_groups_categories(indicators_file: Path) -> None:
    indicators = parse_indicators(indicators_file)
    grouped = build_indicator_map(indicators)
    assert "Valuation Ratios" in grouped
    assert isinstance(grouped["Valuation Ratios"], list)


@pytest.mark.unit
def test_feasibility_summary_counts(indicators_file: Path) -> None:
    indicators = parse_indicators(indicators_file)
    records = analyze_feasibility(indicators)
    summary = summarize_feasibility(records)
    assert sum(summary.values()) == len(records)
