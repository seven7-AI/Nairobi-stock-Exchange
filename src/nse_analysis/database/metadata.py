"""Metadata inspection utilities for Supabase tables."""

from __future__ import annotations

from collections import Counter
from typing import Any

from nse_analysis.config import Settings
from nse_analysis.database.connection import SupabaseConnection


def inspect_table_metadata(
    conn: SupabaseConnection,
    table_name: str,
    sample_limit: int = 100,
) -> dict[str, Any]:
    """Inspect basic field availability, null patterns, and JSON key samples."""
    response = conn.execute_with_retry(
        lambda: conn.client.table(table_name).select("*").limit(sample_limit).execute(),
        f"inspect_table_metadata:{table_name}",
    )
    rows: list[dict[str, Any]] = list(getattr(response, "data", []))
    field_counter: Counter[str] = Counter()
    null_counter: Counter[str] = Counter()
    json_key_samples: dict[str, set[str]] = {}
    for row in rows:
        for key, value in row.items():
            field_counter[key] += 1
            if value is None:
                null_counter[key] += 1
            if isinstance(value, dict):
                sample = json_key_samples.setdefault(key, set())
                sample.update(value.keys())
    return {
        "table": table_name,
        "sample_size": len(rows),
        "fields": sorted(field_counter.keys()),
        "null_counts": dict(null_counter),
        "json_key_samples": {k: sorted(v)[:100] for k, v in json_key_samples.items()},
    }


def inspect_all(settings: Settings, conn: SupabaseConnection) -> dict[str, Any]:
    """Inspect stockanalysis_stocks table."""
    return {
        "stockanalysis_stocks": inspect_table_metadata(conn, settings.stockanalysis_table),
    }
