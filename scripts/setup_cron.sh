#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/setup_cron.sh "0 6 * * *" "/absolute/path/to/repo"
# Defaults:
#   cron schedule: 0 6 * * * (06:00 daily)
#   repo path: current working directory

SCHEDULE="${1:-0 6 * * *}"
REPO_PATH="${2:-$(pwd)}"
LOG_PATH="${REPO_PATH}/logs/cron.log"

mkdir -p "${REPO_PATH}/logs"

CRON_CMD="cd \"${REPO_PATH}\" && uv run nse-analysis run-daily >> \"${LOG_PATH}\" 2>&1"
CRON_ENTRY="${SCHEDULE} ${CRON_CMD}"

(crontab -l 2>/dev/null; echo "${CRON_ENTRY}") | sort -u | crontab -
echo "Installed cron entry:"
echo "${CRON_ENTRY}"
