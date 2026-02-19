#!/usr/bin/env bash
set -euo pipefail

# Weekly report runner for Linux/macOS
# Usage: ./scripts/run_weekly_task.sh

REPO_PATH="${1:-$(pwd)}"
LOG_DIR="${REPO_PATH}/logs"
LOG_FILE="${LOG_DIR}/weekly_task_scheduler.log"

mkdir -p "${LOG_DIR}"

cd "${REPO_PATH}"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting weekly pipeline" >> "${LOG_FILE}"
uv run nse-analysis generate-weekly-report >> "${LOG_FILE}" 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Weekly pipeline finished" >> "${LOG_FILE}"

# Commit and push if git is available
if command -v git &> /dev/null; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Committing weekly report" >> "${LOG_FILE}"
    git add reports/weekly/*.md 2>&1 || true
    if git diff --cached --quiet reports/weekly/*.md 2>/dev/null; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] No changes to commit" >> "${LOG_FILE}"
    else
        git config user.name "NSE-Report-Bot" 2>&1 || true
        git config user.email "nse-report-bot@localhost" 2>&1 || true
        git commit -m "chore: add weekly NSE report" >> "${LOG_FILE}" 2>&1
        git push >> "${LOG_FILE}" 2>&1
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Weekly report committed and pushed" >> "${LOG_FILE}"
    fi
fi
