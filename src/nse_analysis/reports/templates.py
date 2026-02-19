"""Markdown report templates."""

from __future__ import annotations

from typing import Any

from nse_analysis.reports.formatter import fmt_number, fmt_percent


def render_daily_markdown(
    report_date: str,
    generated_at: str,
    market_summary: dict[str, Any],
    indicator_rows: list[dict[str, Any]],
    feasibility_summary: dict[str, int],
    not_calculable: dict[str, list[str]],
    data_quality: dict[str, Any],
) -> str:
    """Render markdown report with concise sections."""
    trend = market_summary.get("market_trend", "unknown")
    mean_change = fmt_percent(market_summary.get("mean_daily_change_pct"))
    lines: list[str] = []
    lines.append(f"# NSE Daily Market Report - {report_date}")
    lines.append("")
    lines.append(f"- Generated At (UTC): `{generated_at}`")
    lines.append("- Data Sources: `stock_data`, `stockanalysis_stocks`, `NSE_DATA/*.csv`")
    lines.append(f"- Stocks Analyzed: `{len(indicator_rows)}`")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(f"- Market Trend: **{trend}**")
    lines.append(f"- Mean Daily Change: **{mean_change}**")
    lines.append(f"- Data Completeness: **{fmt_percent(data_quality.get('completeness_ratio', 0) * 100)}**")
    lines.append("")
    lines.append("## Top Gainers")
    lines.append("")
    lines.append("| Ticker | 1D Change |")
    lines.append("|---|---:|")
    for row in market_summary.get("top_gainers", []):
        lines.append(f"| {row.get('ticker_symbol', 'N/A')} | {fmt_percent(row.get('price_change_1d_pct'))} |")
    lines.append("")
    lines.append("## Top Losers")
    lines.append("")
    lines.append("| Ticker | 1D Change |")
    lines.append("|---|---:|")
    for row in market_summary.get("top_losers", []):
        lines.append(f"| {row.get('ticker_symbol', 'N/A')} | {fmt_percent(row.get('price_change_1d_pct'))} |")
    lines.append("")
    lines.append("## Valuation Snapshot")
    lines.append("")
    lines.append("| Ticker | Price | Market Cap | Revenue | Dividend Yield | 52W Low | 52W High |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for row in indicator_rows[:20]:
        lines.append(
            f"| {row.get('ticker_symbol', 'N/A')} | {fmt_number(row.get('stock_price'))} | "
            f"{fmt_number(row.get('market_cap'))} | {fmt_number(row.get('revenue'))} | "
            f"{fmt_percent(row.get('dividend_yield'))} | {fmt_number(row.get('week_52_low'))} | "
            f"{fmt_number(row.get('week_52_high'))} |"
        )
    lines.append("")
    lines.append("## Feasibility Summary")
    lines.append("")
    lines.append(f"- Calculable: `{feasibility_summary.get('calculable', 0)}`")
    lines.append(f"- Partially Calculable: `{feasibility_summary.get('partially_calculable', 0)}`")
    lines.append(f"- Not Calculable: `{feasibility_summary.get('not_calculable', 0)}`")
    lines.append("")
    lines.append("## Indicators Not Calculable (Missing Data)")
    lines.append("")
    if not not_calculable:
        lines.append("- None")
    else:
        for indicator, missing in sorted(not_calculable.items()):
            needed = ", ".join(missing) if missing else "additional financial statement fields"
            lines.append(f"- `{indicator}`: needs `{needed}`")
    lines.append("")
    lines.append("## Data Quality")
    lines.append("")
    lines.append(f"- Total Rows: `{data_quality.get('total_rows', 0)}`")
    lines.append(f"- Valid Rows: `{data_quality.get('valid_rows', 0)}`")
    lines.append(f"- Invalid Rows: `{data_quality.get('invalid_rows', 0)}`")
    lines.append(f"- Missing Ticker: `{data_quality.get('missing_ticker', 0)}`")
    lines.append(f"- Missing Price: `{data_quality.get('missing_price', 0)}`")
    lines.append("")
    return "\n".join(lines)
