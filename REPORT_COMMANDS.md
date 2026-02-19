# NSE Report Generation Commands

This document provides all commands needed to run daily, weekly, and monthly reports. **All scripts automatically commit and push** the generated reports to GitHub when there are changes.

## Commands to Run (with commit and push)

From the repo root (e.g. `D:\2026 Projects\Nairobi-stock-Exchange`):

**Daily report** (generates report, then commits and pushes `reports/daily/*.md`):
```powershell
powershell -ExecutionPolicy Bypass -File "scripts/run_daily_task.ps1"
```

**Weekly report** (generates report, then commits and pushes `reports/weekly/*.md`):
```powershell
powershell -ExecutionPolicy Bypass -File "scripts/run_weekly_task.ps1"
```

**Monthly report** (generates report, then commits and pushes `reports/monthly/*.md`):
```powershell
powershell -ExecutionPolicy Bypass -File "scripts/run_monthly_task.ps1"
```

Or using CMD from the repo root:
```cmd
scripts\run_daily_task.cmd
scripts\run_weekly_task.cmd
scripts\run_monthly_task.cmd
```

Logs: `logs/task_scheduler.log` (daily), `logs/weekly_task_scheduler.log` (weekly), `logs/monthly_task_scheduler.log` (monthly).

---

## Quick Reference

### Daily Reports
- **Schedule**: Every day at 7 PM UTC
- **Manual Run**: `uv run nse-analysis run-daily` or `powershell -ExecutionPolicy Bypass -File "scripts/run_daily_task.ps1"`
- **Output**: `reports/daily/YYYY-MM-DD.md`

### Weekly Reports
- **Schedule**: Every Friday at 7 PM UTC
- **Manual Run**: `uv run nse-analysis generate-weekly-report` or `powershell -ExecutionPolicy Bypass -File "scripts/run_weekly_task.ps1"`
- **Output**: `reports/weekly/YYYY-MM-DD.md` (week ending date)

### Monthly Reports
- **Schedule**: Last day of month at 7 PM UTC
- **Manual Run**: `uv run nse-analysis generate-monthly-report` or `powershell -ExecutionPolicy Bypass -File "scripts/run_monthly_task.ps1"`
- **Output**: `reports/monthly/YYYY-MM.md`

---

## Windows Task Scheduler Setup

### Daily Report (Every Day at 7 PM)
```powershell
powershell -ExecutionPolicy Bypass -File "scripts/setup_windows_task.ps1" -Time "19:00" -RepoPath "D:\2026 Projects\Nairobi-stock-Exchange"
```

### Weekly Report (Every Friday at 7 PM)
```powershell
powershell -ExecutionPolicy Bypass -File "scripts/setup_weekly_task.ps1" -Time "19:00" -RepoPath "D:\2026 Projects\Nairobi-stock-Exchange"
```

### Monthly Report (28th of each month at 7 PM - script checks if last day)
```powershell
powershell -ExecutionPolicy Bypass -File "scripts/setup_monthly_task.ps1" -Time "19:00" -RepoPath "D:\2026 Projects\Nairobi-stock-Exchange"
```

---

## Manual Execution (Windows)

### Daily Report
```powershell
# PowerShell
powershell -ExecutionPolicy Bypass -File "scripts/run_daily_task.ps1"

# Or CMD
scripts\run_daily_task.cmd

# Or direct CLI
uv run nse-analysis run-daily
```

### Weekly Report
```powershell
# PowerShell
powershell -ExecutionPolicy Bypass -File "scripts/run_weekly_task.ps1"

# Or CMD
scripts\run_weekly_task.cmd

# Or direct CLI
uv run nse-analysis generate-weekly-report
```

### Monthly Report
```powershell
# PowerShell
powershell -ExecutionPolicy Bypass -File "scripts/run_monthly_task.ps1"

# Or CMD
scripts\run_monthly_task.cmd

# Or direct CLI
uv run nse-analysis generate-monthly-report
```

---

## Linux/macOS Cron Setup

### Daily Report (Every day at 7 PM UTC)
```bash
bash scripts/setup_cron.sh "0 19 * * *" "/absolute/path/to/repo"
```

### Weekly Report (Every Friday at 7 PM UTC)
Add to crontab:
```bash
0 19 * * 5 cd /absolute/path/to/repo && bash scripts/run_weekly_task.sh
```

### Monthly Report (Last day of month at 7 PM UTC)
Add to crontab:
```bash
0 19 28-31 * * [ $(date -d tomorrow +\%d) -eq 1 ] && cd /absolute/path/to/repo && bash scripts/run_monthly_task.sh
```

Or manually add:
```bash
0 19 28-31 * * cd /absolute/path/to/repo && bash scripts/run_monthly_task.sh
```
(The script checks if it's the last day of the month)

---

## Manual Execution (Linux/macOS)

### Daily Report
```bash
bash scripts/run_daily_task.sh
# Or
uv run nse-analysis run-daily
```

### Weekly Report
```bash
bash scripts/run_weekly_task.sh
# Or
uv run nse-analysis generate-weekly-report
```

### Monthly Report
```bash
bash scripts/run_monthly_task.sh
# Or
uv run nse-analysis generate-monthly-report
```

---

## GitHub Actions (Automatic)

Reports are automatically generated and committed via GitHub Actions workflows:

- **Daily**: Runs at 7 PM UTC daily (`.github/workflows/daily-report.yml`)
- **Weekly**: Runs Fridays at 7 PM UTC (`.github/workflows/weekly-report.yml`)
- **Monthly**: Runs on last day of month at 7 PM UTC (`.github/workflows/monthly-report.yml`)

All workflows automatically:
1. Generate the report
2. Commit changes to Git
3. Push to the repository

**Required GitHub Secrets:**
- `SUPABASE_URL`
- `SUPABASE_KEY`

---

## Git Commit & Push

All scripts (Windows and Linux) automatically commit and push reports to Git if:
- Git is installed and available
- Repository is initialized
- Remote is configured
- User has push permissions

**Commit Messages:**
- Daily: `chore: add daily NSE report`
- Weekly: `chore: add weekly NSE report`
- Monthly: `chore: add monthly NSE report`

---

## Log Files

All scripts log their output to:
- Daily: `logs/task_scheduler.log`
- Weekly: `logs/weekly_task_scheduler.log`
- Monthly: `logs/monthly_task_scheduler.log`

---

## Troubleshooting

### Scripts don't commit/push
1. Ensure Git is installed: `git --version`
2. Check repository status: `git status`
3. Verify remote is configured: `git remote -v`
4. Check log files for errors

### Reports not generating
1. Check `.env` file has correct Supabase credentials
2. Verify database connection: `uv run nse-analysis pull-data`
3. Check log files for errors
4. Ensure `reports/` directories exist (created automatically)

### Windows Task Scheduler not running
1. Check task exists: `schtasks /Query /TN "NSE-Daily-Report"`
2. Verify task is enabled
3. Check "Run whether user is logged on or not" is selected
4. Review task history in Task Scheduler

---

## Testing Commands

Test each report type manually before scheduling:

```bash
# Test daily
uv run nse-analysis run-daily

# Test weekly
uv run nse-analysis generate-weekly-report

# Test monthly
uv run nse-analysis generate-monthly-report
```

Check the output directories:
- `reports/daily/`
- `reports/weekly/`
- `reports/monthly/`
