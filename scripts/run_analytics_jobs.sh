#!/usr/bin/env bash
# Run the analytics pipelines after the scraper's daily job.
#
#   scripts/run_analytics_jobs.sh daily          # every day (cron)
#   scripts/run_analytics_jobs.sh weekly         # Saturdays (cron)
#   scripts/run_analytics_jobs.sh fundamentals   # every day; skips itself when statements are unchanged
#
# Every run appends to reports/analytics-jobs.log with its exit status; the
# pipelines themselves record every step in the analytics store (job_runs).

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${REPO_ROOT}/reports"
LOG_PATH="${LOG_DIR}/analytics-jobs.log"
PIPELINE="${1:-daily}"
shift || true

mkdir -p "${LOG_DIR}"
cd "${REPO_ROOT}"

log() {
  printf '[%s] %s\n' "$(date +"%Y-%m-%dT%H:%M:%S%z")" "$1" >> "${LOG_PATH}"
}

UV_BIN="${UV_BIN:-$(command -v uv || echo "${HOME}/.local/bin/uv")}"

log "START pipeline=${PIPELINE} args=$*"
"${UV_BIN}" run nse-analysis analytics upgrade >> "${LOG_PATH}" 2>&1
"${UV_BIN}" run nse-analysis analytics jobs "${PIPELINE}" "$@" >> "${LOG_PATH}" 2>&1
status=$?
if [[ ${status} -eq 0 ]]; then
  log "OK pipeline=${PIPELINE}"
else
  log "FAILED pipeline=${PIPELINE} exit=${status}"
fi
exit "${status}"
