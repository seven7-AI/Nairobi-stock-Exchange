"""Validation checks for merged daily stock datasets."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from nse_analysis.utils.exceptions import DataValidationError


class ValidationSummary(BaseModel):
    """Validation summary metadata for reporting."""

    model_config = ConfigDict(frozen=True)

    total_rows: int
    valid_rows: int
    invalid_rows: int
    missing_ticker: int
    missing_price: int
    completeness_ratio: float = Field(ge=0.0, le=1.0)


def validate_merged_rows(rows: list[dict[str, Any]]) -> ValidationSummary:
    """Validate required fields for analysis pipeline."""
    total = len(rows)
    missing_ticker = 0
    missing_price = 0
    valid = 0
    for row in rows:
        ticker = row.get("ticker_symbol")
        price = row.get("stock_price")
        if ticker in (None, "", "nan"):
            missing_ticker += 1
            continue
        if price in (None, "", "nan"):
            missing_price += 1
            continue
        valid += 1

    invalid = total - valid
    if total > 0 and valid == 0:
        raise DataValidationError("All merged rows are invalid; cannot proceed with report generation.")

    ratio = (valid / total) if total else 0.0
    return ValidationSummary(
        total_rows=total,
        valid_rows=valid,
        invalid_rows=invalid,
        missing_ticker=missing_ticker,
        missing_price=missing_price,
        completeness_ratio=ratio,
    )
