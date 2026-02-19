# Nairobi Stock Exchange Analytics

Production-grade daily analytics pipeline for NSE market data using Supabase `stockanalysis_stocks` table.

## Setup

1. Ensure `.env` contains `SUPABASE_URL`, `SUPABASE_KEY`, `STOCKANALYSIS_TABLE`.
2. Install dependencies:
   - `uv sync --dev`

## CLI Commands

- `uv run nse-analysis inspect-metadata --output-file reports/metadata/latest.json`
- `uv run nse-analysis inspect-price-history` - Inspect price_history structure
- `uv run nse-analysis check-feasibility`
- `uv run nse-analysis pull-data`
- `uv run nse-analysis calculate-indicators --limit 200`
- `uv run nse-analysis generate-report` - Generate daily report
- `uv run nse-analysis run-daily` - Run full daily pipeline
- `uv run nse-analysis generate-weekly-report` - Generate weekly report
- `uv run nse-analysis generate-monthly-report` - Generate monthly report

## Report Output

- Daily reports: `reports/daily/YYYY-MM-DD.md`
- Weekly reports: `reports/weekly/YYYY-MM-DD.md` (week ending date)
- Monthly reports: `reports/monthly/YYYY-MM.md`

## Scheduling

### Daily Reports

**Linux/macOS (cron):**
```bash
bash scripts/setup_cron.sh "0 19 * * *" "/absolute/path/to/repo"
```

**Windows Task Scheduler:**
```powershell
powershell -ExecutionPolicy Bypass -File "scripts/setup_windows_task.ps1" -Time "19:00" -RepoPath "D:\2026 Projects\Nairobi-stock-Exchange"
```

**Manual Run:**
```powershell
powershell -ExecutionPolicy Bypass -File "scripts/run_daily_task.ps1"
```

### Weekly Reports (Fridays at 7 PM)

**Windows Task Scheduler:**
```powershell
powershell -ExecutionPolicy Bypass -File "scripts/setup_weekly_task.ps1" -Time "19:00" -RepoPath "D:\2026 Projects\Nairobi-stock-Exchange"
```

**Manual Run:**
```powershell
powershell -ExecutionPolicy Bypass -File "scripts/run_weekly_task.ps1"
```

**Linux/macOS (cron - Fridays at 7 PM UTC):**
```bash
# Add to crontab: 0 19 * * 5 /path/to/repo/scripts/run_weekly_task.sh
```

### Monthly Reports (Last Day of Month at 7 PM)

**Windows Task Scheduler:**
```powershell
powershell -ExecutionPolicy Bypass -File "scripts/setup_monthly_task.ps1" -Time "19:00" -RepoPath "D:\2026 Projects\Nairobi-stock-Exchange"
```

**Manual Run:**
```powershell
powershell -ExecutionPolicy Bypass -File "scripts/run_monthly_task.ps1"
```

**Linux/macOS (cron - Last day of month at 7 PM UTC):**
```bash
# Add to crontab: 0 19 28-31 * * [ $(date -d tomorrow +\%d) -eq 1 ] && /path/to/repo/scripts/run_monthly_task.sh
```

## GitHub Automation

All reports are automatically generated and committed via GitHub Actions:

- **Daily**: `.github/workflows/daily-report.yml` - Runs at 7 PM UTC daily
- **Weekly**: `.github/workflows/weekly-report.yml` - Runs Fridays at 7 PM UTC
- **Monthly**: `.github/workflows/monthly-report.yml` - Runs on last day of month at 7 PM UTC

Ensure repository secrets are configured:
- `SUPABASE_URL`
- `SUPABASE_KEY`

Reports are automatically committed and pushed to the repository.

## Log Files

- Daily: `logs/task_scheduler.log`
- Weekly: `logs/weekly_task_scheduler.log`
- Monthly: `logs/monthly_task_scheduler.log`
