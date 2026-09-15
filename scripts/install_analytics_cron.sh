#!/usr/bin/env bash
# Chain the analytics pipelines after the scraper's 09:00 Africa/Nairobi job.
#
#   scripts/install_analytics_cron.sh            # append the entries (idempotent)
#   scripts/install_analytics_cron.sh --print    # show the entries, change nothing
#   scripts/install_analytics_cron.sh --verify   # exit 1 when an entry is missing
#
# Appends; never rewrites the crontab (another project running `crontab <file>`
# replaces the whole user crontab - `--verify` is how that is caught).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRON_TZ_NAME="Africa/Nairobi"
RUNNER="cd ${REPO_ROOT} && bash scripts/run_analytics_jobs.sh"
# The scrape fires at 09:00 and takes minutes; daily analytics at 09:40, the
# fundamentals pass (skips itself when statements are unchanged) at 10:10, and
# the weekly pass on Saturdays at 10:30.
ENTRIES=(
  "40 09 * * * ${RUNNER} daily"
  "10 10 * * * ${RUNNER} fundamentals"
  "30 10 * * 6 ${RUNNER} weekly"
)
INSTALLED_COPY="${REPO_ROOT}/deployment/cron/analytics-cron.installed"

mode="${1:-install}"

if [[ "${mode}" == "--print" ]]; then
  printf 'CRON_TZ=%s\n' "${CRON_TZ_NAME}"
  printf '%s\n' "${ENTRIES[@]}"
  exit 0
fi

EXISTING="$(crontab -l 2>/dev/null || true)"

if [[ "${mode}" == "--verify" ]]; then
  missing=0
  for entry in "${ENTRIES[@]}"; do
    if ! printf '%s\n' "${EXISTING}" | grep -Fq "${entry}"; then
      echo "MISSING: ${entry}"
      missing=1
    fi
  done
  [[ ${missing} -eq 0 ]] && echo "analytics cron entries present"
  exit "${missing}"
fi

to_add=()
for entry in "${ENTRIES[@]}"; do
  if printf '%s\n' "${EXISTING}" | grep -Fq "${entry}"; then
    echo "already installed: ${entry}"
  else
    to_add+=("${entry}")
  fi
done
if [[ ${#to_add[@]} -eq 0 ]]; then
  exit 0
fi
{
  printf '%s\n' "${EXISTING}"
  if ! printf '%s\n' "${EXISTING}" | grep -Fq "CRON_TZ=${CRON_TZ_NAME}"; then
    printf 'CRON_TZ=%s\n' "${CRON_TZ_NAME}"
  fi
  printf '%s\n' "${to_add[@]}"
} | crontab -
mkdir -p "$(dirname "${INSTALLED_COPY}")"
{ printf 'CRON_TZ=%s\n' "${CRON_TZ_NAME}"; printf '%s\n' "${ENTRIES[@]}"; } > "${INSTALLED_COPY}"
echo "installed:"
printf '  %s\n' "${to_add[@]}"
echo "host local now: $(date +'%H:%M %Z'); ${CRON_TZ_NAME} now: $(TZ="${CRON_TZ_NAME}" date +'%H:%M %Z')"
echo "If the scraper's 09:00 entry fires host-local rather than Nairobi time, these do too."
