"""Indicator feasibility analysis against available datasets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nse_analysis.indicators.registry import IndicatorDefinition


@dataclass(frozen=True)
class FeasibilityRecord:
    """Result row for indicator feasibility output."""

    indicator: str
    category: str
    status: str
    source: str
    missing_data: list[str]
    notes: str


# Coverage map can be expanded as data quality improves.
INDICATOR_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "Stock Price": {"fields": {"stock_price"}, "source": "stockanalysis_stocks"},
    "Price Change 1D (%)": {"fields": {"stock_change"}, "source": "stockanalysis_stocks"},
    "Volume": {"fields": {"price_metrics.volume"}, "source": "stockanalysis_stocks"},
    "Market Cap": {"fields": {"overview_metrics.marketCap"}, "source": "stockanalysis_stocks"},
    "PE Ratio": {"fields": {"overview_metrics.pe_ratio"}, "source": "stockanalysis_stocks"},
    "PB Ratio": {"fields": {"overview_metrics.pb_ratio"}, "source": "stockanalysis_stocks"},
    "PS Ratio": {"fields": {"overview_metrics.ps_ratio"}, "source": "stockanalysis_stocks"},
    "Dividend Yield": {"fields": {"dividends_metrics.dividendYield"}, "source": "stockanalysis_stocks"},
    "52 Week Low": {"fields": {"price_metrics.low52"}, "source": "stockanalysis_stocks"},
    "52 Week High": {"fields": {"price_metrics.high52"}, "source": "stockanalysis_stocks"},
    "Price Change 1W": {"fields": {"historical_prices"}, "source": "stockanalysis_stocks"},
    "Price Change 1M": {"fields": {"historical_prices"}, "source": "stockanalysis_stocks"},
    "Price Change 3M": {"fields": {"historical_prices"}, "source": "stockanalysis_stocks"},
    "Total Return 1M": {"fields": {"performance_metrics.tr1m"}, "source": "stockanalysis_stocks"},
    "Total Return 1Y": {"fields": {"performance_metrics.tr1y"}, "source": "stockanalysis_stocks"},
    "Total Return 6M": {"fields": {"performance_metrics.tr6m"}, "source": "stockanalysis_stocks"},
    "Total Return YTD": {"fields": {"performance_metrics.trYTD"}, "source": "stockanalysis_stocks"},
    "Return CAGR 1Y": {"fields": {"historical_prices"}, "source": "stockanalysis_stocks"},
    "20-Day Moving Average": {"fields": {"historical_prices"}, "source": "stockanalysis_stocks"},
    "50-Day Moving Average": {"fields": {"historical_prices"}, "source": "stockanalysis_stocks"},
    "200-Day Moving Average": {"fields": {"historical_prices"}, "source": "stockanalysis_stocks"},
    "Relative Strength Index (RSI)": {"fields": {"historical_prices"}, "source": "stockanalysis_stocks"},
}


AVAILABLE_FIELD_HINTS = {
    "stockanalysis_stocks": {
        "ticker_symbol",
        "company_name",
        "rank",
        "stock_price",
        "stock_change",
        "scraped_at",
        "overview_metrics",
        "performance_metrics",
        "dividends_metrics",
        "price_metrics",
        "profile_metrics",
        "overview_metrics.marketCap",
        "overview_metrics.revenue",
        "overview_metrics.revenueGrowth",
        "overview_metrics.pe_ratio",
        "overview_metrics.pb_ratio",
        "overview_metrics.ps_ratio",
        "dividends_metrics.dividendYield",
        "dividends_metrics.dps",
        "dividends_metrics.payoutRatio",
        "price_metrics.low52",
        "price_metrics.high52",
        "price_metrics.volume",
        "performance_metrics.tr1m",
        "performance_metrics.tr1y",
        "performance_metrics.tr6m",
        "performance_metrics.trYTD",
        "historical_prices",  # Historical prices now come from stockanalysis_stocks table
    },
}


def analyze_feasibility(indicators: list[IndicatorDefinition]) -> list[FeasibilityRecord]:
    """Mark each indicator as calculable, partial, or missing."""
    records: list[FeasibilityRecord] = []
    for indicator in indicators:
        req = INDICATOR_REQUIREMENTS.get(indicator.name)
        if req is None:
            # Default for unmapped indicators: likely needs full statements not present in current schema.
            records.append(
                FeasibilityRecord(
                    indicator=indicator.name,
                    category=indicator.category,
                    status="not_calculable",
                    source="unknown",
                    missing_data=["explicit field mapping not yet available"],
                    notes="Needs additional mapped fields or financial statements.",
                )
            )
            continue
        source = str(req["source"])
        required_fields: set[str] = set(req["fields"])
        available = AVAILABLE_FIELD_HINTS.get(source, set())
        missing = sorted(field for field in required_fields if field not in available)
        if missing:
            status = "partially_calculable"
            notes = "Some required fields are missing."
        else:
            status = "calculable"
            notes = "Required fields available."
        records.append(
            FeasibilityRecord(
                indicator=indicator.name,
                category=indicator.category,
                status=status,
                source=source,
                missing_data=missing,
                notes=notes,
            )
        )
    return records


def summarize_feasibility(records: list[FeasibilityRecord]) -> dict[str, int]:
    """Summarize feasibility statuses for report headers."""
    summary = {"calculable": 0, "partially_calculable": 0, "not_calculable": 0}
    for record in records:
        summary[record.status] = summary.get(record.status, 0) + 1
    return summary
