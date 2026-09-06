#!/usr/bin/env bash
# Run the quality gates. Starts a disposable PostgreSQL for the integration
# suite unless TEST_DATABASE_URL already points somewhere.
set -euo pipefail
cd "$(dirname "$0")/.."

CONTAINER=nse-test-postgres
STARTED=0
PGUSER="${PGUSER:-postgres}"
PGPORT="${PGPORT:-55433}"
PGDB="${PGDB:-nse}"

cleanup() {
  if [[ "${STARTED}" == "1" ]]; then
    docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [[ -z "${TEST_DATABASE_URL:-}" ]] && command -v docker >/dev/null 2>&1; then
  echo "Starting disposable PostgreSQL for integration tests..."
  docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
  docker run -d --name "${CONTAINER}" \
    -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_USER="${PGUSER}" \
    -e POSTGRES_DB="${PGDB}" \
    -p "${PGPORT}:5432" postgres:16-alpine >/dev/null
  STARTED=1
  for _ in $(seq 1 30); do
    docker exec "${CONTAINER}" pg_isready -U "${PGUSER}" -d "${PGDB}" >/dev/null 2>&1 && break
    sleep 1
  done
  # The container runs with trust auth, so there is no password here to build
  # into the DSN and none to commit.
  export TEST_DATABASE_URL="postgresql+asyncpg://${PGUSER}@localhost:${PGPORT}/${PGDB}"
  DATABASE_URL="${TEST_DATABASE_URL}" uv run alembic upgrade head
fi

echo "--- codegraph sync ---"
command -v codegraph >/dev/null 2>&1 && codegraph sync . || echo "(codegraph not installed; skipping)"

echo "--- ruff ---";   uv run ruff check .
echo "--- mypy ---";   uv run mypy app/
echo "--- pytest ---"; uv run pytest "${@}"
