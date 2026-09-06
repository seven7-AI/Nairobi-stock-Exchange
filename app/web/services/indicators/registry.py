"""Indicator registry parser for indicators.txt."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class IndicatorDefinition:
    """Single indicator entry with grouped category."""

    name: str
    category: str


SECTION_NAMES = {
    "Basic Information",
    "Price and Volume",
    "Valuation Ratios",
    "Performance Metrics",
    "Price Levels",
    "Company Information",
    "Revenue and Growth",
    "Profitability",
    "Earnings",
    "Cash Flow",
    "Balance Sheet",
    "Margins and Ratios",
    "Debt and Leverage",
    "Efficiency and Turnover",
    "Dividends and Shareholder Returns",
    "Market and Technical Indicators",
    "Shares and Ownership",
    "Earnings and Dividend Dates",
    "Return on Investment",
    "Employee and Revenue Metrics",
    "Miscellaneous",
}


SKIP_ITEMS = {
    "No.",
    "Symbol",
    "Company Name",
}


def parse_indicators(indicators_path: Path) -> list[IndicatorDefinition]:
    """Parse the indicator reference text file into structured categories."""
    lines = [line.strip() for line in indicators_path.read_text(encoding="utf-8").splitlines()]
    current_section = "Uncategorized"
    parsed: list[IndicatorDefinition] = []
    for line in lines:
        if not line:
            continue
        if line in SECTION_NAMES:
            current_section = line
            continue
        if line in SKIP_ITEMS:
            continue
        parsed.append(IndicatorDefinition(name=line, category=current_section))
    return parsed


def build_indicator_map(indicators: list[IndicatorDefinition]) -> dict[str, list[str]]:
    """Create category -> indicator list mapping."""
    out: dict[str, list[str]] = {}
    for indicator in indicators:
        out.setdefault(indicator.category, []).append(indicator.name)
    return out
