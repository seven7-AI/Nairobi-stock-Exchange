.DEFAULT_GOAL := help
.PHONY: help install hooks ci graph graph-status explore lint format typecheck test test-unit \
        test-integration check api worker beat flower migrate migration downgrade \
        report-daily report-weekly report-monthly up down logs clean

# ---------------------------------------------------------------------------
# CodeGraph — always the first stop when navigating this codebase
# ---------------------------------------------------------------------------
graph: ## Sync the CodeGraph index with the working tree
	codegraph sync .

graph-status: ## Show CodeGraph index status and statistics
	codegraph status .

graph-index: ## Rebuild the CodeGraph index from scratch
	codegraph index .

explore: ## Query CodeGraph: make explore Q="require_roles rbac.py"
	@test -n "$(Q)" || (echo 'usage: make explore Q="symbols or question"' && exit 1)
	codegraph explore "$(Q)"

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
install: ## Install dependencies from the lockfile and the local git hooks
	uv sync --dev
	$(MAKE) hooks

# ---------------------------------------------------------------------------
# Quality gates
# ---------------------------------------------------------------------------
lint: ## Ruff check
	uv run ruff check .

format: ## Ruff format
	uv run ruff format .

typecheck: ## mypy
	uv run mypy app/

test: ## Full test suite with coverage
	uv run pytest

test-unit: ## Fast unit tests only
	uv run pytest -m unit

test-integration: ## Integration tests only
	uv run pytest -m integration

check: graph lint typecheck test ## Sync the graph, then run every quality gate

ci: ## Run the FULL local gate — exactly what pre-push runs. There is no hosted CI.
	./.githooks/pre-push

hooks: ## Install the git hooks that enforce the gate locally
	git config core.hooksPath .githooks
	# git opens the SSH connection BEFORE running pre-push; a multi-minute gate can
	# outlive GitHub's idle timeout and the push then dies with SIGPIPE (exit 141).
	# Keepalives, scoped to this repo, hold the connection open for the hook's duration.
	git config core.sshCommand "ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=60"
	@echo "core.hooksPath -> .githooks (pre-commit: lint; pre-push: full gate); ssh keepalive set"

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
api: ## Run the API on :8000 with reload
	uv run uvicorn app.web.main:app --host 0.0.0.0 --port 8000 --reload

worker: ## Run a Celery worker
	uv run python start_celery.py worker

beat: ## Run the Celery beat scheduler
	uv run python start_celery.py beat

flower: ## Run Flower on :5555
	uv run python start_celery.py flower

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
migrate: ## Apply all migrations
	uv run alembic upgrade head

migration: ## Autogenerate a migration: make migration M="add watchlists"
	@test -n "$(M)" || (echo 'usage: make migration M="description"' && exit 1)
	uv run alembic revision --autogenerate -m "$(M)"

downgrade: ## Roll back one migration
	uv run alembic downgrade -1

# ---------------------------------------------------------------------------
# Reports (CLI path — same services the API uses)
# ---------------------------------------------------------------------------
report-daily: ## Generate the daily report
	uv run nse-analysis run-daily

report-weekly: ## Generate the weekly report
	uv run nse-analysis generate-weekly-report

report-monthly: ## Generate the monthly report
	uv run nse-analysis generate-monthly-report

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------
up: ## Start the full stack
	cd deployment && docker compose up --build -d

down: ## Stop the stack
	cd deployment && docker compose down

logs: ## Tail the API logs
	cd deployment && docker compose logs -f api

clean: ## Remove caches
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
