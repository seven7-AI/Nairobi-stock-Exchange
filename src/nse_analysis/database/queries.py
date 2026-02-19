"""Reusable Supabase query utilities."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from nse_analysis.database.connection import SupabaseConnection


def fetch_latest_rows(
    conn: SupabaseConnection,
    table_name: str,
    timestamp_column: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Fetch latest rows by timestamp descending."""
    response = conn.execute_with_retry(
        lambda: conn.client.table(table_name).select("*").order(timestamp_column, desc=True).limit(limit).execute(),
        f"fetch_latest_rows:{table_name}",
    )
    return list(getattr(response, "data", []))


def fetch_rows_by_date_range(
    conn: SupabaseConnection,
    table_name: str,
    timestamp_column: str,
    start_dt: datetime,
    end_dt: datetime,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    """Fetch rows between datetime boundaries, inclusive."""
    start_iso = start_dt.astimezone(timezone.utc).isoformat()
    end_iso = end_dt.astimezone(timezone.utc).isoformat()
    response = conn.execute_with_retry(
        lambda: conn.client.table(table_name)
        .select("*")
        .gte(timestamp_column, start_iso)
        .lte(timestamp_column, end_iso)
        .limit(limit)
        .execute(),
        f"fetch_rows_by_date_range:{table_name}",
    )
    return list(getattr(response, "data", []))


def fetch_latest_day_rows(
    conn: SupabaseConnection,
    table_name: str,
    timestamp_column: str,
    now_utc: datetime | None = None,
) -> list[dict[str, Any]]:
    """Fetch rows for the last 24h window as daily operational baseline."""
    current = now_utc or datetime.now(tz=timezone.utc)
    start = current - timedelta(days=1)
    return fetch_rows_by_date_range(conn, table_name, timestamp_column, start, current)


def fetch_rows_by_ticker(
    conn: SupabaseConnection,
    table_name: str,
    ticker_symbol: str,
    limit: int = 3650,
) -> list[dict[str, Any]]:
    """Fetch full ticker history ordered by recency."""
    response = conn.execute_with_retry(
        lambda: conn.client.table(table_name)
        .select("*")
        .eq("ticker_symbol", ticker_symbol)
        .order("created_at", desc=True)
        .limit(limit)
        .execute(),
        f"fetch_rows_by_ticker:{table_name}:{ticker_symbol}",
    )
    return list(getattr(response, "data", []))


def extract_json_metrics(row: dict[str, Any], metrics_column: str) -> dict[str, Any]:
    """Normalize JSONB payload into dict."""
    value = row.get(metrics_column)
    if isinstance(value, dict):
        return value
    return {}
