from pathlib import Path

from nse_analysis.indicators.feasibility import analyze_feasibility, summarize_feasibility
from nse_analysis.indicators.registry import build_indicator_map, parse_indicators


def test_parse_indicators_reads_content() -> None:
    indicators = parse_indicators(Path("indicators.txt"))
    assert indicators
    names = {item.name for item in indicators}
    assert "Market Cap" in names


def test_build_indicator_map_groups_categories() -> None:
    indicators = parse_indicators(Path("indicators.txt"))
    grouped = build_indicator_map(indicators)
    assert "Valuation Ratios" in grouped
    assert isinstance(grouped["Valuation Ratios"], list)


def test_feasibility_summary_counts() -> None:
    indicators = parse_indicators(Path("indicators.txt"))
    records = analyze_feasibility(indicators)
    summary = summarize_feasibility(records)
    assert sum(summary.values()) == len(records)
