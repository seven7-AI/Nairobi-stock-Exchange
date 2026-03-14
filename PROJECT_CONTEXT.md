# Nairobi Stock Exchange (NSE) Analytics Pipeline - Full Project Context

## Overview

This is a **production-grade Python analytics pipeline** that automatically fetches live Nairobi Securities Exchange (NSE) stock data from a Supabase database, calculates financial indicators, and generates structured Markdown market reports on daily, weekly, and monthly schedules. The pipeline runs via GitHub Actions bots and/or local Windows Task Scheduler / Linux cron jobs, committing reports to the repository automatically.

The project also contains a **historical dataset archive** (`NSE_DATA/`) with CSV files covering every traded NSE stock from **2007 through 2024** (18 years of data), plus sector classification mappings.

**Author:** Kevin Kipkoech
**License:** Apache 2.0
**Python:** 3.12 (minimum 3.11)
**Package Manager:** uv (with hatch build backend)

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      AUTOMATION LAYER                       │
│                                                             │
│  GitHub Actions          Windows Task Scheduler     Cron    │
│  ┌──────────────┐       ┌────────────────────┐   ┌──────┐  │
│  │ daily  7PM   │       │ run_daily_task.ps1  │   │ bash │  │
│  │ weekly Fri   │       │ run_weekly_task.ps1 │   │ jobs │  │
│  │ monthly last │       │ run_monthly_task.ps1│   │      │  │
│  └──────┬───────┘       └────────┬───────────┘   └──┬───┘  │
│         │                        │                   │      │
│         └────────────────────────┼───────────────────┘      │
│                                  ▼                          │
│                        CLI (Typer): nse-analysis             │
│                        ┌────────────────────┐               │
│                        │ run-daily          │               │
│                        │ generate-weekly    │               │
│                        │ generate-monthly   │               │
│                        │ pull-data          │               │
│                        │ calculate-indicators│               │
│                        │ check-feasibility  │               │
│                        │ inspect-metadata   │               │
│                        │ inspect-price-hist.│               │
│                        │ generate-report    │               │
│                        └────────┬───────────┘               │
└─────────────────────────────────┼───────────────────────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼              ▼
            ┌──────────┐  ┌────────────┐  ┌──────────────┐
            │ Supabase │  │ Indicator  │  │ Report       │
            │ Data     │  │ Calculator │  │ Generator    │
            │ Fetcher  │  │            │  │              │
            └─────┬────┘  └─────┬──────┘  └──────┬───────┘
                  │             │                 │
                  ▼             ▼                 ▼
         ┌──────────────┐  Computes:     ┌────────────────┐
         │ Supabase DB  │  - 1D/1W/1M    │ reports/       │
         │ (cloud)      │    price Δ%    │  ├── daily/    │
         │              │  - MAs (20,50, │  ├── weekly/   │
         │ Table:       │    200 day)    │  └── monthly/  │
         │ stockanalysis│  - RSI         │                │
         │ _stocks      │  - CAGR        │ Markdown files │
         └──────────────┘  - ATH/ATL     │ auto-committed │
                           - Volatility   └────────────────┘
```

---

## Two Data Sources

### 1. Live Data: Supabase `stockanalysis_stocks` Table (Primary)

This is the **primary data source** used by the pipeline. A separate scraper (not in this repo) populates a Supabase PostgreSQL table called `stockanalysis_stocks` with current NSE stock data. Each row contains:

| Field | Description |
|---|---|
| `ticker_symbol` | Stock ticker code (e.g., `SCOM`, `EQTY`, `KCB`) |
| `company_name` | Full company name |
| `stock_price` | Current trading price (KES) |
| `stock_change` | Absolute price change from previous day |
| `market_cap` | Market capitalization in KES |
| `revenue` | Annual revenue in KES |
| `dividend_yield` | Dividend yield percentage |
| `pe_ratio` | Price-to-earnings ratio |
| `ps_ratio` | Price-to-sales ratio |
| `pb_ratio` | Price-to-book ratio |
| `week_52_low` | 52-week low price |
| `week_52_high` | 52-week high price |
| `price_history` | JSON array of historical price entries `[{"date": "...", "price": ...}, ...]` |
| `scraped_at` | UTC timestamp of when the data was scraped |

The pipeline connects using `SUPABASE_URL` and `SUPABASE_KEY` environment variables (stored in `.env` locally, GitHub Secrets in CI).

### 2. Historical Archive: `NSE_DATA/` Folder (Reference / Legacy)

This folder contains **18 CSV files** (one per year, 2007-2024) with daily trading data for all NSE-listed stocks, plus **5 sector classification files**. These CSVs are currently marked as **deprecated** in the codebase - the pipeline now pulls historical data from the `price_history` field in Supabase rather than from these files. However, they remain a valuable reference dataset.

#### Stock Price CSV Structure (18 files)

Files: `NSE_data_all_stocks_2007.csv` through `NSE_data_all_stocks_2024.csv`

| Column | Description |
|---|---|
| `DATE` | Trading date (format varies: `1/2/2007` in older files, `2-Jan-24` in newer) |
| `CODE` | Stock ticker code |
| `NAME` | Company name |
| `12m Low` | 12-month low price |
| `12m High` | 12-month high price |
| `Day Low` | Intraday low |
| `Day High` | Intraday high |
| `Day Price` | Closing price for the day |
| `Previous` | Previous day's closing price |
| `Change` | Absolute price change |
| `Change%` | Percentage change |
| `Volume` | Number of shares traded |
| `Adjust` / `Adjusted Price` | Adjusted price (column name varies across years) |

**Example rows:**

2007 data:
```
1/2/2007, EGAD, Eaagads, 22, 57, 52, 52, 52, 52, -, -, 300, 26
1/2/2007, BBK, Barclays Bank, 11.75, 18.5, 74, 84.5, 83.5, 76, 7.5, 8.98%, 398300, 20.88
```

2024 data:
```
2-Jan-24, EGAD, Eaagads Ltd, 10.35, 14.5, 12.8, 12.8, 12.8, 13.95, -1.15, -8.24%, 100, -
2-Jan-24, SCOM, Safaricom PLC, 14.3, 22.75, 17.2, 17.75, 17.5, 17.15, 0.35, 2.04%, 24889900, -
```

**Scale:** Files range from ~10,600 rows (2007) to ~18,100 rows (2024), reflecting the growing number of listed companies and trading days.

#### Sector Classification CSV Structure (5 files)

Files: `NSE_data_stock_market_sectors_2013.csv` through `NSE_data_stock_market_sectors_2023_2024.csv`

| Column | Description |
|---|---|
| `Sector` | Market sector (e.g., Agricultural, Banking, Insurance) |
| `Stock_code` | Ticker code |
| `Stock_name` | Full company name |

---

## Stocks Tracked (59 Active as of February 2026)

The pipeline currently tracks **59 stocks** across these NSE sectors:

### Agricultural (6)
| Ticker | Company |
|---|---|
| EGAD | Eaagads Limited |
| KUKZ | Kakuzi Plc |
| KAPC | Kapchorua Tea Kenya Plc |
| LIMT | Limuru Tea Plc |
| SASN | Sasini PLC |
| WTK | Williamson Tea Kenya Plc |

### Banking (12)
| Ticker | Company |
|---|---|
| ABSA | Absa Bank Kenya PLC |
| BKG | BK Group PLC |
| COOP | Co-operative Bank of Kenya |
| DTK | Diamond Trust Bank Kenya |
| EQTY | Equity Group Holdings Plc |
| HFCK | HF Group Plc |
| IMH | I&M Group PLC |
| KCB | KCB Group PLC |
| NBK | National Bank of Kenya |
| NCBA | NCBA Group PLC |
| SBIC | Stanbic Holdings Plc |
| SCBK | Standard Chartered Bank Kenya |

### Commercial & Services (12)
| Ticker | Company |
|---|---|
| DCON | Deacons (East Africa) Plc |
| EVRD | Eveready East Africa PLC |
| XPRS | Express Kenya PLC |
| HBE | Homeboyz Entertainment Plc |
| KQ | Kenya Airways Plc |
| LKL | Longhorn Publishers Plc |
| NBV | Nairobi Business Ventures |
| NMG | Nation Media Group PLC |
| SCAN | WPP Scangroup Plc |
| SGL | Standard Group PLC |
| SMER | Sameer Africa PLC |
| TPSE | TPS Eastern Africa (Serena Hotels) |

### Construction & Allied (5)
| Ticker | Company |
|---|---|
| ARM | ARM Cement |
| BAMB | Bamburi Cement Plc |
| CABL | East African Cables PLC |
| CRWN | Crown Paints Kenya PLC |
| PORT | East African Portland Cement |

### Energy & Petroleum (4+)
| Ticker | Company |
|---|---|
| KEGN | KenGen (Kenya Electricity Generating) |
| KPLC | Kenya Power and Lighting |
| TOTL | TotalEnergies Marketing Kenya |
| UMME | Umeme Limited (Uganda) |

### Insurance (6)
| Ticker | Company |
|---|---|
| BRIT | Britam Holdings Plc |
| CIC | CIC Insurance Group Plc |
| JUB | Jubilee Holdings Limited |
| KNRE | Kenya Reinsurance Corporation |
| LBTY | Liberty Kenya Holdings |
| SLAM | Sanlam Allianz Holdings (Kenya) |

### Investment (5)
| Ticker | Company |
|---|---|
| CTUM | Centum Investment Company |
| HAFR | Home Afrika Limited |
| KURV | Kurwitu Ventures Limited |
| OCH | Olympia Capital Holdings |
| TCL | TransCentury PLC |

### Investment Services (1)
| Ticker | Company |
|---|---|
| NSE | Nairobi Securities Exchange Plc |

### Manufacturing & Allied (8)
| Ticker | Company |
|---|---|
| BAT | British American Tobacco Kenya |
| BOC | BOC Kenya Plc |
| CARB | Carbacid Investments Plc |
| EABL | East African Breweries PLC |
| FTGH | FTG Holdings Ltd (Flame Tree) |
| MSC | Mumias Sugar |
| ORCH | Kenya Orchards |
| UNGA | Unga Group Plc |

### Telecommunication (1)
| Ticker | Company | Market Cap (Feb 2026) |
|---|---|---|
| SCOM | Safaricom PLC | KES 1.33 Trillion (largest on NSE) |

### Other
| Ticker | Company | Type |
|---|---|---|
| CGEN | Car & General (Kenya) Plc | Automobiles |
| GLD | ABSA NewGold ETF | ETF |
| LAPR | Laptrust Imara I-REIT | REIT |
| AMAC | Africa Mega Agricorp Plc | Other |
| SKL | Shri Krishana Overseas PLC | Other |

---

## How the Pipeline Works

### Daily Pipeline (`run-daily`)

This is the core operation, run at **7 PM UTC daily** via GitHub Actions or Task Scheduler:

1. **Pull Data** - `DataFetcher` connects to Supabase and fetches the latest 1000 rows from `stockanalysis_stocks`, ordered by `scraped_at` descending
2. **Merge & Deduplicate** - Keeps only the most recent row per `ticker_symbol`, producing ~59 unique stock records
3. **Validate** - `validate_merged_rows()` checks for missing tickers, missing prices, and calculates data completeness ratio
4. **Load Historical** - Extracts price history from the `price_history` JSON field in each row (or falls back to fetching older rows by date range)
5. **Calculate Indicators** - For each stock, computes:
   - 1-day price change % (from `stock_change` field)
   - 1-week price change % (from 5-day historical lookback)
   - 1-month price change % (from 22-day historical lookback)
   - Moving averages (20-day, 50-day, 200-day)
   - RSI (14-day relative strength index)
   - CAGR (compound annual growth rate)
   - All-time high/low from available history
   - Annualized volatility
6. **Classify Market** - Determines overall market trend (bullish/bearish/flat) based on mean daily change
7. **Generate Report** - Renders a Markdown file with: executive summary, top 5 gainers, top 5 losers, valuation snapshot (top 20 by market cap), feasibility summary, data quality metrics
8. **Auto-Commit** - Runner scripts (or GitHub Actions) commit the report file and push to the repository as "NSE-Report-Bot" / "github-actions[bot]"

### Weekly Pipeline (`generate-weekly-report`)

Run on **Fridays at 7 PM UTC**:

- Same data fetch and calculation as daily
- Uses `classify_weekly_market_insights()` for weekly trend classification
- Report includes: top 10 weekly gainers/losers, performance overview for top 30 stocks by market cap
- Saved to `reports/weekly/YYYY-MM-DD.md` (using the week-ending date)

### Monthly Pipeline (`generate-monthly-report`)

Run on the **last day of each month at 7 PM UTC**:

- Same data fetch and calculation as daily
- Uses `classify_monthly_market_insights()` for monthly trend classification
- Report includes: top 15 monthly gainers/losers, full performance overview for top 50 stocks (with PE ratio column)
- Saved to `reports/monthly/YYYY-MM.md`

### Yearly Pipeline

**Not yet implemented.** The project structure anticipates it (no `reports/yearly/` directory exists yet), but no yearly report generation or template has been built. The historical CSV archive (2007-2024) provides the raw data that could power yearly analysis.

---

## Report Examples

### Daily Report Example (2026-02-19)

```markdown
# NSE Daily Market Report - 2026-02-19

- Generated At (UTC): `2026-02-19T18:14:06.367242+00:00`
- Data Sources: `stockanalysis_stocks`
- Stocks Analyzed: `59`

## Executive Summary

- Market Trend: **bearish**
- Mean Daily Change: **-6.88%**
- Data Completeness: **100.00%**

## Top Gainers

| Ticker | 1D Change |
|---|---:|
| SLAM | 219.05% |
| EGAD | 38.19% |
| UMME | 27.54% |
| NSE | 14.62% |
| CRWN | 9.24% |

## Top Losers

| Ticker | 1D Change |
|---|---:|
| EVRD | -85.70% |
| CIC | 0.00% |
| UCHM | 0.00% |

## Valuation Snapshot

| Ticker | Price | Market Cap | Revenue | Dividend Yield | 52W Low | 52W High |
|---|---:|---:|---:|---:|---:|---:|
| SCOM | 32.15 | 1,326,165,666,800 | 399,964,500,000 | 4.53% | 17.00 | 34.20 |
| EQTY | 74.25 | 282,082,191,450 | 176,545,609,000 | 5.69% | 41.20 | 78.00 |
| KCB | 74.75 | 241,009,711,125 | 180,683,048,000 | 5.33% | 35.00 | 76.50 |
...
```

### Weekly Report Example (Week Ending 2026-02-19)

```markdown
# NSE Weekly Market Report - Week Ending 2026-02-19

- Week Period: `2026-02-13` to `2026-02-19`
- Stocks Analyzed: `59`

## Executive Summary
- Market Trend: **flat**
- Mean Weekly Change: **0.00%**

## Top Weekly Gainers
| Ticker | Company | Weekly Change | Current Price |
|---|---:|---:|---:|
| SCOM | Safaricom PLC | 0.00% | 32.15 |
| EQTY | Equity Group Holdings Plc | 0.00% | 74.25 |
...

## Weekly Performance Overview
| Ticker | Company | Price | Weekly Change | Market Cap |
|---|---:|---:|---:|---:|
| SCOM | Safaricom PLC | 32.15 | N/A | 1,326,165,666,800 |
...
```

### Monthly Report Example (February 2026)

```markdown
# NSE Monthly Market Report - February 2026

- Month: `February 2026`
- Stocks Analyzed: `59`

## Executive Summary
- Market Trend: **flat**
- Mean Monthly Change: **0.00%**

## Monthly Performance Overview
| Ticker | Company | Price | Monthly Change | Market Cap | PE Ratio |
|---|---:|---:|---:|---:|---:|
| SCOM | Safaricom PLC | 32.15 | N/A | 1,326,165,666,800 | N/A |
...
```

**Note:** The weekly and monthly reports currently show 0.00% changes and N/A for many metrics. This is because the `price_history` JSON field in Supabase doesn't yet have enough accumulated historical data points (the scraper needs to have been running for at least 5 days for weekly and 22 days for monthly calculations to work).

---

## Financial Indicators

### Currently Calculable (22 of 280+)

The pipeline defines **280+ financial indicators** across 21 categories in `indicators.txt`, but only **22 are currently calculable** with available Supabase data:

| Indicator | Source |
|---|---|
| Stock Price | Direct from `stock_price` field |
| Price Change 1D (%) | Calculated from `stock_change` / previous price |
| Price Change 1W (%) | From 5-day historical lookback |
| Price Change 1M (%) | From 22-day historical lookback |
| Market Cap | Direct from `market_cap` field |
| Revenue | Direct from `revenue` field |
| PE Ratio | Direct from `pe_ratio` field |
| PS Ratio | Direct from `ps_ratio` field |
| PB Ratio | Direct from `pb_ratio` field |
| Dividend Yield | Direct from `dividend_yield` field |
| 52-Week High | Direct from `week_52_high` field |
| 52-Week Low | Direct from `week_52_low` field |
| Volume | Direct from `volume` field |
| 20-Day Moving Average | Calculated from 20 data points of history |
| 50-Day Moving Average | Calculated from 50 data points of history |
| 200-Day Moving Average | Calculated from 200 data points of history |
| RSI (14-day) | Calculated from 15+ data points of history |
| CAGR | Calculated from historical start/end prices + time span |
| All-Time High | Max of all historical prices |
| All-Time Low | Min of all historical prices |
| Annualized Volatility | Standard deviation of daily returns, annualized |
| Company Name | Direct from `company_name` field |

### Not Yet Calculable (216)

These require additional data sources or field mappings not yet available: EPS, EBITDA, Free Cash Flow, Debt ratios, Beta, Forward PE, Balance Sheet items, Cash Flow items, etc. The full list is documented in each daily report under "Indicators Not Calculable."

### Indicator Categories (from `indicators.txt`)

1. Basic Information (11 indicators)
2. Price and Volume (7)
3. Valuation Ratios (16)
4. Performance Metrics (15)
5. Price Levels (12)
6. Company Information (10)
7. Revenue and Growth (7)
8. Profitability (6)
9. Earnings (8)
10. Cash Flow (9)
11. Balance Sheet (12)
12. Margins and Ratios (10)
13. Debt and Leverage (12)
14. Efficiency and Turnover (3)
15. Dividends and Shareholder Returns (14)
16. Market and Technical Indicators (16)
17. Shares and Ownership (8)
18. Earnings and Dividend Dates (5)
19. Return on Investment (8)
20. Employee and Revenue Metrics (3)
21. Miscellaneous (8)

---

## Automation & Scheduling

### GitHub Actions (3 workflows in `.github/workflows/`)

| Workflow | Schedule | What it does |
|---|---|---|
| `daily-report.yml` | `0 19 * * *` (7 PM UTC daily) | Runs `uv run nse-analysis run-daily`, commits to `reports/daily/` |
| `weekly-report.yml` | `0 19 * * 5` (7 PM UTC Fridays) | Runs `uv run nse-analysis generate-weekly-report`, commits to `reports/weekly/` |
| `monthly-report.yml` | `0 19 28-31 * *` (7 PM UTC, last days of month) | Runs `uv run nse-analysis generate-monthly-report`, commits to `reports/monthly/` |

All workflows: checkout repo, install uv, install Python, sync dependencies, run CLI command, then `git add/commit/push` as `github-actions[bot]`.

### Local Runner Scripts (`scripts/`)

Each report type has PowerShell (.ps1), CMD (.cmd), and bash (.sh) variants:

- **Daily:** `run_daily_task.ps1` / `.cmd` - runs `uv run nse-analysis run-daily`, logs to `logs/task_scheduler.log`, auto-commits as "NSE-Report-Bot"
- **Weekly:** `run_weekly_task.ps1` / `.cmd` / `.sh` - runs `uv run nse-analysis generate-weekly-report`
- **Monthly:** `run_monthly_task.ps1` / `.cmd` / `.sh` - runs `uv run nse-analysis generate-monthly-report` (bash version includes last-day-of-month guard)

### Scheduler Setup Scripts

- `setup_windows_task.ps1` - Creates Windows Task Scheduler task "NSE-Daily-Report" via `schtasks.exe`
- `setup_weekly_task.ps1` - Creates "NSE-Weekly-Report" task for Fridays
- `setup_monthly_task.ps1` - Creates "NSE-Monthly-Report" task for the 28th of each month
- `setup_cron.sh` - Installs crontab entry for daily Linux/macOS runs

---

## Project Structure

```
Nairobi-stock-Exchange/
├── .github/workflows/
│   ├── daily-report.yml
│   ├── weekly-report.yml
│   └── monthly-report.yml
│
├── NSE_DATA/                              # Historical CSV archive (LEGACY/REFERENCE)
│   ├── NSE_data_all_stocks_2007.csv       # ~10,600 rows
│   ├── NSE_data_all_stocks_2008.csv
│   ├── ...
│   ├── NSE_data_all_stocks_2024.csv       # ~18,100 rows
│   ├── NSE_data_stock_market_sectors_2013.csv
│   ├── NSE_data_stock_market_sectors_2020.csv
│   ├── NSE_data_stock_market_sectors_2021.csv
│   ├── NSE_data_stock_market_sectors_2022.csv
│   └── NSE_data_stock_market_sectors_2023_2024.csv
│
├── reports/                               # Auto-generated market reports
│   ├── daily/
│   │   ├── 2026-02-18.md
│   │   └── 2026-02-19.md
│   ├── weekly/
│   │   └── 2026-02-19.md
│   └── monthly/
│       └── 2026-02.md
│
├── scripts/                               # Automation runner + scheduler scripts
│   ├── run_daily_task.ps1 / .cmd
│   ├── run_weekly_task.ps1 / .cmd / .sh
│   ├── run_monthly_task.ps1 / .cmd / .sh
│   ├── setup_windows_task.ps1
│   ├── setup_weekly_task.ps1
│   ├── setup_monthly_task.ps1
│   └── setup_cron.sh
│
├── src/nse_analysis/                      # Main Python package
│   ├── __init__.py
│   ├── cli.py                             # Typer CLI with 9 commands
│   ├── config.py                          # Pydantic settings from .env
│   ├── data/
│   │   ├── fetcher.py                     # DataFetcher: Supabase data ingestion
│   │   └── validator.py                   # Row validation and completeness check
│   ├── database/
│   │   ├── connection.py                  # Supabase client with retry logic
│   │   ├── metadata.py                    # Table structure inspection
│   │   └── queries.py                     # Reusable query utilities
│   ├── indicators/
│   │   ├── calculator.py                  # Financial indicator computation
│   │   ├── feasibility.py                 # Indicator feasibility analysis
│   │   └── registry.py                    # Parses indicators.txt definitions
│   ├── reports/
│   │   ├── formatter.py                   # Number/percent formatting helpers
│   │   ├── generator.py                   # Report writing orchestrator
│   │   └── templates.py                   # Markdown templates (daily/weekly/monthly)
│   └── utils/
│       ├── exceptions.py                  # Custom exception hierarchy
│       └── logger.py                      # Structured JSON event logging
│
├── tests/
│   ├── test_calculator.py
│   ├── test_validator.py
│   └── test_registry_and_feasibility.py
│
├── .env                                   # (gitignored) SUPABASE_URL + SUPABASE_KEY
├── .python-version                        # 3.12
├── indicators.txt                         # 280+ indicator definitions (21 categories)
├── pyproject.toml                         # Project config, dependencies, CLI entry
├── uv.lock                                # Dependency lock file
├── README.md
├── REPORT_COMMANDS.md                     # Command reference documentation
└── LICENSE                                # Apache 2.0
```

---

## Key Dependencies

| Package | Purpose |
|---|---|
| `supabase` | Supabase Python client for database access |
| `pandas` | Data manipulation and historical analysis |
| `numpy` | Numerical computations (RSI, volatility, etc.) |
| `pydantic` / `pydantic-settings` | Configuration validation and typed settings |
| `typer` | CLI framework (9 commands) |
| `rich` | Terminal output formatting (tables, colors) |
| `structlog` | Structured JSON logging |
| `python-dotenv` | Environment variable loading |
| `requests` | HTTP requests |
| `pyyaml` | YAML parsing |

Dev tools: `ruff` (linting/formatting), `mypy` (strict type checking), `pytest` (testing)

---

## Configuration

The pipeline requires a `.env` file (gitignored) with:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key-here
STOCKANALYSIS_TABLE=stockanalysis_stocks   # optional, this is the default
```

For GitHub Actions, these are stored as repository secrets: `SUPABASE_URL` and `SUPABASE_KEY`.

---

## Current State & Known Limitations

1. **Weekly/Monthly reports show 0.00% changes** - The `price_history` field in Supabase needs enough accumulated data points (5+ days for weekly, 22+ for monthly) before these calculations produce meaningful results.

2. **Only 22 of 280+ indicators are calculable** - Most advanced financial indicators (EPS, EBITDA, debt ratios, cash flow metrics, etc.) require financial statement data not currently available in the Supabase table. The missing field mappings are documented in every daily report.

3. **No yearly report** - The infrastructure for daily/weekly/monthly is complete, but yearly reports have not been implemented yet.

4. **Historical CSVs are deprecated** - The `NSE_DATA/` folder CSVs are no longer used by the pipeline (data now comes from Supabase), but they contain 18 years of valuable historical data that could be leveraged for deeper analysis.

5. **Date format inconsistencies** - The historical CSV files use different date formats across years (`1/2/2007` vs `2-Jan-24`), which would need normalization if used for analysis.

6. **Scraper is external** - The component that populates the Supabase `stockanalysis_stocks` table is not part of this repository.

---

## CLI Commands Reference

```bash
# Full daily pipeline (fetch + validate + calculate + report)
uv run nse-analysis run-daily

# Generate just a report (same as run-daily)
uv run nse-analysis generate-report

# Weekly report (best run on Fridays)
uv run nse-analysis generate-weekly-report

# Monthly report (best run on last day of month)
uv run nse-analysis generate-monthly-report

# Just fetch data without generating a report
uv run nse-analysis pull-data

# Calculate indicators without generating a report
uv run nse-analysis calculate-indicators --limit 100

# Check which of the 280+ indicators can be calculated
uv run nse-analysis check-feasibility

# Inspect Supabase table structure
uv run nse-analysis inspect-metadata

# Inspect price_history field structure
uv run nse-analysis inspect-price-history --limit 5
```
