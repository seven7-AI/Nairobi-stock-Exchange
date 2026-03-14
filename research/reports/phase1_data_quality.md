# Phase 1A — Data Quality Report

Generated from `01_data_foundation.ipynb`

## Raw Data Summary

- **total_rows**: 267,527
- **valid_rows_approx**: 267310
- **duplicate_date_ticker_pairs**: 432
- **missing_close_price**: 1
- **non_positive_close**: 0
- **missing_volume**: 46,136
- **zero_volume**: 14,347
- **change_vs_price_mismatch**: 40,367
- **completeness_pct**: 99.92

## Cleaning Applied

- Removed exact duplicate (date, ticker) pairs
- Removed rows with missing or non-positive close prices
- Final dataset: **267,310** rows

## Coverage

- Date range: 2007-01-02 to 2024-12-31
- Unique tickers: 88
- Unique trading days: 4478

## Sector Distribution

| Sector | Tickers | Active |
|---|---:|---:|
| Agricultural | 6 | 6 |
| Automobiles and Accessories | 1 | 1 |
| Banking | 12 | 12 |
| Commercial and Services | 13 | 13 |
| Construction and Allied | 5 | 5 |
| Energy and Petroleum | 7 | 6 |
| Exchange Traded Funds | 1 | 1 |
| Insurance | 6 | 6 |
| Investment | 5 | 5 |
| Investment Services | 1 | 1 |
| Manufacturing and Allied | 8 | 8 |
| Real Estate Investment Trusts | 1 | 1 |
| Telecommunication | 1 | 1 |
| Unknown | 21 | 1 |