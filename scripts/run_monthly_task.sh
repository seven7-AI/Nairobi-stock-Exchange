#!/usr/bin/env bash
set -euo pipefail

# Monthly report runner for Linux/macOS
# Usage: ./scripts/run_monthly_task.sh
# Note: This script checks if today is the last day of the month

REPO_PATH="${1:-$(pwd)}"
LOG_DIR="${REPO_PATH}/logs"
LOG_FILE="${LOG_DIR}/monthly_task_scheduler.log"

mkdir -p "${LOG_DIR}"

cd "${REPO_PATH}"

# Check if today is the last day of the month
TODAY=$(date +%d)
TOMORROW=$(date -d tomorrow +%d 2>/dev/null || date -v+1d +%d 2>/dev/null || echo "32")

if [ "$TOMORROW" -eq "01" ] || [ "$TODAY" -ge "28" ]; then
    # Check if it's actually the last day
    LAST_DAY=$(cal $(date +%m) $(date +%Y) | awk 'NF {DAYS = $NF}; END {print DAYS}')
    if [ "$TODAY" -eq "$LAST_DAY" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting monthly pipeline (last day of month)" >> "${LOG_FILE}"
        uv run nse-analysis generate-monthly-report >> "${LOG_FILE}" 2>&1
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Monthly pipeline finished" >> "${LOG_FILE}"
        
        # Commit and push if git is available
        if command -v git &> /dev/null; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Committing monthly report" >> "${LOG_FILE}"
            git add reports/monthly/*.md 2>&1 || true
            if git diff --cached --quiet reports/monthly/*.md 2>/dev/null; then
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] No changes to commit" >> "${LOG_FILE}"
            else
                git config user.name "NSE-Report-Bot" 2>&1 || true
                git config user.email "nse-report-bot@localhost" 2>&1 || true
                git commit -m "chore: add monthly NSE report" >> "${LOG_FILE}" 2>&1
                git push >> "${LOG_FILE}" 2>&1
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] Monthly report committed and pushed" >> "${LOG_FILE}"
            fi
        fi
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Not the last day of month, skipping monthly report" >> "${LOG_FILE}"
    fi
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Not the last day of month, skipping monthly report" >> "${LOG_FILE}"
fi
