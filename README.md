# Nairobi Stock Exchange Analytics

Production-grade daily analytics pipeline for NSE market data using Supabase and historical CSV archives.

## Setup

1. Ensure `.env` contains `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_TABLE`, `STOCKANALYSIS_TABLE`.
2. Install dependencies:
   - `uv sync --dev`

## CLI Commands

- `uv run nse-analysis inspect-metadata --output-file reports/metadata/latest.json`
- `uv run nse-analysis check-feasibility`
- `uv run nse-analysis pull-data`
- `uv run nse-analysis calculate-indicators --limit 200`
- `uv run nse-analysis generate-report`
- `uv run nse-analysis run-daily`

## Report Output

Daily reports are written to `reports/daily/YYYY-MM-DD.md`.

## Scheduling

Use `scripts/setup_cron.sh` for Linux/macOS cron installation:

- `bash scripts/setup_cron.sh "0 6 * * *" "/absolute/path/to/repo"`

For Windows Task Scheduler (daily at 9:20 AM):

- `powershell -ExecutionPolicy Bypass -File "scripts/setup_windows_task.ps1" -Time "09:20" -RepoPath "D:\2026 Projects\Nairobi-stock-Exchange"`

The scheduled job runs:

- `scripts/run_daily_task.ps1`
- Output log: `logs/task_scheduler.log`

For GitHub automation, configure repository secrets and use `.github/workflows/daily-report.yml`.
