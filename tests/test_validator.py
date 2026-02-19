from nse_analysis.data.validator import validate_merged_rows


def test_validate_merged_rows_success() -> None:
    rows = [
        {"ticker_symbol": "KCB", "stock_price": 21.95},
        {"ticker_symbol": "EQTY", "stock_price": 34.2},
        {"ticker_symbol": "SCOM", "stock_price": 19.45},
    ]
    summary = validate_merged_rows(rows)
    assert summary.valid_rows == 3
    assert summary.invalid_rows == 0
    assert summary.completeness_ratio == 1.0
