#!/usr/bin/env bash
# Start the API. Applies migrations first so a fresh container is usable.
set -euo pipefail
cd "$(dirname "$0")/.."

uv run alembic upgrade head
exec uv run uvicorn app.web.main:app \
  --host "${API_HOST:-0.0.0.0}" \
  --port "${API_PORT:-8000}" \
  "${@}"
