# Phase 1A — EDA Summary

Generated from `01_data_foundation.ipynb`

## Dataset

- **267,310** price observations across **88** tickers
- Date range: **2007-01-02** to **2024-12-31**
- **88** tickers in master map (67 currently active)

## Return Characteristics

| Horizon | Mean | Std | Skewness | Kurtosis |
|---|---:|---:|---:|---:|
| Daily | -0.00038 | 0.0892 | -0.034 | 274.5 |
| Weekly | -0.00175 | 0.1462 | -1.083 | 111.0 |
| Monthly | -0.00725 | 0.1478 | -3.107 | 135.6 |

## Top 10 by Risk-Adjusted Composite Score

| Rank | Ticker | Sector | CAGR | Sharpe | Max DD | Score |
|---:|---|---|---:|---:|---:|---:|
| 1 | GLD | Exchange Traded Funds | 10.5% | 0.78 | -14.4% | 0.974 |
| 2 | CITY | Unknown | 15.5% | 0.10 | -57.2% | 0.949 |
| 3 | KUKZ | Agricultural | 12.9% | 0.10 | -66.6% | 0.928 |
| 4 | KPLC-P7 | Energy and Petroleum | 1.1% | 0.09 | -9.1% | 0.914 |
| 5 | COOP | Banking | 3.5% | 0.04 | -59.4% | 0.898 |
| 6 | SCOM | Telecommunication | 5.1% | 0.05 | -74.1% | 0.890 |
| 7 | LAPR | Real Estate Investment Trusts | 6.5% | 0.11 | -78.9% | 0.883 |
| 8 | KAPC | Agricultural | 4.0% | 0.05 | -75.3% | 0.878 |
| 9 | BAT | Manufacturing and Allied | 2.8% | 0.03 | -70.4% | 0.861 |
| 10 | SCBK | Banking | 1.4% | 0.02 | -65.1% | 0.855 |

## Bottom 10 by Composite Score

| Rank | Ticker | Sector | CAGR | Sharpe | Max DD | Score |
|---:|---|---|---:|---:|---:|---:|
| 1 | CABL | Construction and Allied | -19.1% | -0.20 | -98.6% | 0.171 |
| 2 | KPLC-R | Unknown | -88.4% | -10.05 | -86.2% | 0.161 |
| 3 | DCON | Commercial and Services | -20.7% | -0.49 | -97.0% | 0.151 |
| 4 | MSC | Manufacturing and Allied | -24.5% | -0.18 | -99.5% | 0.142 |
| 5 | UCHM | Commercial and Services | -24.3% | -0.21 | -99.3% | 0.132 |
| 6 | NIC-R | Unknown | -32.5% | -3.18 | -94.9% | 0.120 |
| 7 | HAFR | Investment | -30.8% | -0.46 | -98.9% | 0.099 |
| 8 | TCL | Investment | -28.5% | -0.42 | -99.4% | 0.099 |
| 9 | KCB-R | Unknown | -65.0% | -5.22 | -97.5% | 0.068 |
| 10 | HFCK-R | Unknown | -33.8% | -5.92 | -99.9% | 0.039 |

## Sector Drawdown Summary

| Sector | Median DD | Worst DD | Tickers |
|---|---:|---:|---:|
| Construction and Allied | -97.0% | -98.9% | 5 |
| Investment | -94.4% | -99.4% | 5 |
| Commercial and Services | -94.3% | -99.3% | 13 |
| Banking | -90.6% | -96.3% | 12 |
| Insurance | -88.3% | -97.2% | 6 |
| Manufacturing and Allied | -86.7% | -99.5% | 8 |
| Investment Services | -81.3% | -81.3% | 1 |
| Real Estate Investment Trusts | -78.9% | -78.9% | 1 |
| Unknown | -78.9% | -99.9% | 21 |
| Agricultural | -78.5% | -97.4% | 6 |
| Energy and Petroleum | -77.2% | -99.6% | 7 |
| Automobiles and Accessories | -76.3% | -76.3% | 1 |
| Telecommunication | -74.1% | -74.1% | 1 |
| Exchange Traded Funds | -14.4% | -14.4% | 1 |

## Next Steps

- Notebook 2: overlay global events and detect market regimes
- Test momentum and mean-reversion signals on this clean dataset
- Integrate live Supabase data for forward-looking analysis