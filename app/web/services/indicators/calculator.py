"""Indicator calculation engine."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import pandas as pd

from app.web.core.exceptions import IndicatorCalculationError
from app.web.services.indicators.feasibility import FeasibilityRecord


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def calculate_for_row(row: dict[str, Any], historical: pd.DataFrame) -> dict[str, Any]:
    """Compute concise, insight-focused indicators for one ticker."""
    ticker = str(row.get("ticker_symbol", "")).strip()
    if not ticker:
        raise IndicatorCalculationError("Missing ticker symbol in merged row.")

    history = (
        historical.loc[historical["ticker_symbol"] == ticker].copy()
        if not historical.empty
        else pd.DataFrame()
    )
    history = history.sort_values("date")
    latest_price = _to_float(row.get("stock_price"))
    if latest_price is None and not history.empty:
        latest_price = _to_float(history["stock_price"].iloc[-1])
    if latest_price is None:
        raise IndicatorCalculationError(f"Missing latest price for {ticker}.")

    stock_change = _to_float(row.get("stock_change"))

    metrics: dict[str, Any] = {
        "ticker_symbol": ticker,
        "company_name": row.get("company_name") or row.get("stock_name") or ticker,
        "stock_price": latest_price,
        "stock_change": stock_change,
    }

    # Calculate 1D change percentage from stock_price and stock_change (primary method)
    if stock_change is not None and latest_price is not None:
        # stock_change is absolute change, so previous_price = current_price - stock_change
        prev_price = latest_price - stock_change
        if prev_price > 0:
            metrics["price_change_1d_pct"] = (stock_change / prev_price) * 100.0
        elif abs(stock_change) < 0.0001:
            # If stock_change is essentially zero, percentage is 0
            metrics["price_change_1d_pct"] = 0.0
        else:
            # Edge case: if prev_price is 0 or negative, set to None
            metrics["price_change_1d_pct"] = None

    # Use historical data for weekly/monthly calculations, and as a 1D fallback
    # when stock_change is unavailable.
    if not history.empty:
        history_prices = pd.to_numeric(history["stock_price"], errors="coerce").dropna()

        # Fallback: if 1D change not calculated from stock_change, try historical data
        if metrics.get("price_change_1d_pct") is None and len(history_prices) >= 2:
            metrics["price_change_1d_pct"] = (
                (history_prices.iloc[-1] / history_prices.iloc[-2]) - 1.0
            ) * 100.0

        # Weekly and monthly calculations from historical data
        if len(history_prices) >= 5:
            metrics["price_change_1w_pct"] = (
                (history_prices.iloc[-1] / history_prices.iloc[-5]) - 1.0
            ) * 100.0
        if len(history_prices) >= 22:
            metrics["price_change_1m_pct"] = (
                (history_prices.iloc[-1] / history_prices.iloc[-22]) - 1.0
            ) * 100.0
            metrics["moving_average_20d"] = float(history_prices.tail(20).mean())
        if len(history_prices) >= 50:
            metrics["moving_average_50d"] = float(history_prices.tail(50).mean())
        if len(history_prices) >= 200:
            metrics["moving_average_200d"] = float(history_prices.tail(200).mean())

        metrics["all_time_high"] = float(history_prices.max())
        metrics["all_time_low"] = float(history_prices.min())
        metrics["distance_from_ath_pct"] = ((latest_price / metrics["all_time_high"]) - 1.0) * 100.0

        returns = history_prices.pct_change().dropna()
        if len(returns) >= 14:
            gains = returns.clip(lower=0.0).tail(14).mean()
            losses = -returns.clip(upper=0.0).tail(14).mean()
            if losses == 0:
                metrics["rsi_14"] = 100.0
            else:
                rs = gains / losses
                metrics["rsi_14"] = float(100 - (100 / (1 + rs)))
        if len(history_prices) >= 252:
            cagr_years = len(history_prices) / 252.0
            start = history_prices.iloc[0]
            end = history_prices.iloc[-1]
            if start > 0 and cagr_years > 0:
                metrics["return_cagr"] = float((end / start) ** (1.0 / cagr_years) - 1.0)

    overview: dict[str, Any] = (
        row["overview_metrics"] if isinstance(row.get("overview_metrics"), dict) else {}
    )
    dividends: dict[str, Any] = (
        row["dividends_metrics"] if isinstance(row.get("dividends_metrics"), dict) else {}
    )
    price_metrics: dict[str, Any] = (
        row["price_metrics"] if isinstance(row.get("price_metrics"), dict) else {}
    )

    performance: dict[str, Any] = (
        row["performance_metrics"] if isinstance(row.get("performance_metrics"), dict) else {}
    )

    metrics["market_cap"] = _extract_metric(overview, ["marketCap", "market_cap", "Market Cap"])
    metrics["revenue"] = _extract_metric(overview, ["revenue", "Revenue"])
    metrics["pe_ratio"] = _extract_metric(overview, ["peRatio", "pe_ratio", "PE Ratio"])
    metrics["pb_ratio"] = _extract_metric(overview, ["pbRatio", "pb_ratio", "PB Ratio"])
    metrics["ps_ratio"] = _extract_metric(overview, ["psRatio", "ps_ratio", "PS Ratio"])
    metrics["dividend_yield"] = _extract_metric(
        dividends, ["dividendYield", "dividend_yield", "Dividend Yield"]
    )
    metrics["week_52_low"] = _extract_metric(price_metrics, ["low52", "52 Week Low", "52_week_low"])
    metrics["week_52_high"] = _extract_metric(
        price_metrics, ["high52", "52 Week High", "52_week_high"]
    )
    metrics["total_return_1m"] = _extract_metric(performance, ["tr1m", "Total Return 1M"])
    metrics["total_return_1y"] = _extract_metric(performance, ["tr1y", "Total Return 1Y"])

    return metrics


def _extract_metric(payload: dict[str, Any], keys: Iterable[str]) -> Any:
    normalized = {_norm_key(k): v for k, v in payload.items()}
    for key in keys:
        direct = payload.get(key)
        if direct is not None:
            return direct
        candidate = normalized.get(_norm_key(key))
        if candidate is not None:
            return candidate
    return None


def _norm_key(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def calculate_batch(rows: list[dict[str, Any]], historical: pd.DataFrame) -> list[dict[str, Any]]:
    """Calculate indicators for all rows, skipping records with fatal issues."""
    results: list[dict[str, Any]] = []
    for row in rows:
        try:
            results.append(calculate_for_row(row, historical))
        except IndicatorCalculationError:
            continue
    return results


#: Columns every classifier reports alongside the change it ranks on.
_BASE_COLUMNS = ("ticker_symbol", "company_name", "stock_price")


def _records(frame: pd.DataFrame, columns: Sequence[str]) -> list[dict[str, Any]]:
    """Frame rows as plain dicts with NaN rendered as ``None``, not ``0.0``.

    ``fillna(0.0)`` here is what used to turn "we have no data for this ticker"
    into "this ticker moved 0.00%". ``None`` flows through ``fmt_percent`` as
    ``N/A``, which is what the reader needs to see.
    """
    subset = frame.reindex(columns=list(columns))
    return [
        {key: (None if pd.isna(value) else value) for key, value in record.items()}
        for record in subset.to_dict("records")
    ]


def _classify_market(
    indicators: list[dict[str, Any]],
    *,
    change_column: str,
    mean_key: str,
    top_n: int,
) -> dict[str, Any]:
    """Rank gainers and losers on one change column.

    Instruments whose change could not be computed are **excluded from the
    ranking**, not coerced to zero. Ranking them as 0.00% both invented a
    number and pushed genuine movers out of the table: the loser list ended up
    mostly NaN rows sitting at the bottom of a descending sort.

    The count of excluded instruments is returned so a report can disclose it.
    """
    empty = {
        "market_trend": "insufficient_data",
        mean_key: None,
        "top_gainers": [],
        "top_losers": [],
        "ranked_instruments": 0,
        "excluded_missing_change": 0,
    }
    if not indicators:
        return empty

    frame = pd.DataFrame(indicators)
    for column in (*_BASE_COLUMNS, change_column):
        if column not in frame.columns:
            frame[column] = np.nan
    frame[change_column] = pd.to_numeric(frame[change_column], errors="coerce")
    frame["stock_price"] = pd.to_numeric(frame["stock_price"], errors="coerce")

    ranked = frame.dropna(subset=[change_column])
    excluded = len(frame) - len(ranked)
    if ranked.empty:
        return {**empty, "excluded_missing_change": excluded}

    mean_change = float(ranked[change_column].mean())
    trend = "bullish" if mean_change > 0 else "bearish" if mean_change < 0 else "flat"

    columns = (*_BASE_COLUMNS, change_column)
    ascending = ranked.sort_values(change_column, ascending=True)
    descending = ranked.sort_values(change_column, ascending=False)

    # With fewer than 2*top_n ranked instruments the two tables would overlap and
    # the same ticker would be reported as both a top gainer and a top loser.
    # Split the available universe instead.
    effective_n = top_n if len(ranked) >= 2 * top_n else max(1, len(ranked) // 2)

    return {
        "market_trend": trend,
        mean_key: mean_change,
        # Best first in gainers, worst first in losers. Previously losers were
        # `tail(n)` of a descending sort, so the biggest loser came out last.
        "top_gainers": _records(descending.head(effective_n), columns),
        "top_losers": _records(ascending.head(effective_n), columns),
        "ranked_instruments": len(ranked),
        "excluded_missing_change": excluded,
    }


def classify_market_insights(indicators: list[dict[str, Any]]) -> dict[str, Any]:
    """Daily market-level summary insights."""
    return _classify_market(
        indicators,
        change_column="price_change_1d_pct",
        mean_key="mean_daily_change_pct",
        top_n=5,
    )


def classify_weekly_market_insights(indicators: list[dict[str, Any]]) -> dict[str, Any]:
    """Weekly market-level summary insights."""
    return _classify_market(
        indicators,
        change_column="price_change_1w_pct",
        mean_key="mean_weekly_change_pct",
        top_n=10,
    )


def classify_monthly_market_insights(indicators: list[dict[str, Any]]) -> dict[str, Any]:
    """Monthly market-level summary insights."""
    return _classify_market(
        indicators,
        change_column="price_change_1m_pct",
        mean_key="mean_monthly_change_pct",
        top_n=15,
    )


def unavailable_requirements(feasibility_records: list[FeasibilityRecord]) -> dict[str, list[str]]:
    """Compile missing-data explanation for non-calculable indicators."""
    missing: dict[str, list[str]] = {}
    for record in feasibility_records:
        if record.status == "not_calculable":
            missing[record.indicator] = record.missing_data
    return missing
