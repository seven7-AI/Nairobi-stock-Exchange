#!/usr/bin/env bash
# Run the quality gates. Starts a disposable PostgreSQL for the integration
# suite unless TEST_DATABASE_URL already points somewhere.
set -euo pipefail
cd "$(dirname "$0")/.."

CONTAINER=nse-test-postgres
STARTED=0

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
    -e POSTGRES_PASSWORD=postgres -e POSTGRES_USER=postgres -e POSTGRES_DB=nse \
    -p 55433:5432 postgres:16-alpine >/dev/null
  STARTED=1
  for _ in $(seq 1 30); do
    docker exec "${CONTAINER}" pg_isready -U postgres -d nse >/dev/null 2>&1 && break
    sleep 1
  done
  export TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:55433/nse"
  DATABASE_URL="${TEST_DATABASE_URL}" uv run alembic upgrade head
fi

echo "--- codegraph sync ---"
command -v codegraph >/dev/null 2>&1 && codegraph sync . || echo "(codegraph not installed; skipping)"

echo "--- ruff ---";   uv run ruff check .
echo "--- mypy ---";   uv run mypy app/
echo "--- pytest ---"; uv run pytest "${@}"
