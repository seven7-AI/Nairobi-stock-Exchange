#!/usr/bin/env bash
# Start a Celery worker consuming every queue.
set -euo pipefail
cd "$(dirname "$0")/.."

exec uv run python start_celery.py "${1:-worker}"
