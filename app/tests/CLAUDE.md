# Tests — `app/tests/`

## Start here, every time

```bash
codegraph explore "<symbol you are about to test>"
```

The blast radius section tells you what else depends on the symbol — that is your list of
integration cases, and it is usually more honest than reading the function alone. When
CodeGraph reports "no tests found within 3 caller hops" for something, that is a coverage
gap worth closing while you are there.

## Rules

- Mark every test: `@pytest.mark.unit`, `@pytest.mark.integration`, or `@pytest.mark.slow`.
  `--strict-markers` is on, so an unknown marker fails the run.
- `unit/` — no database, no Redis, no network. Fast enough to run on every save.
- `integration/` — httpx `AsyncClient` against the app, real session fixtures.
- **RBAC is tested as a matrix**: for each protected route, assert the allowed roles get
  2xx and at least one disallowed role gets 403. A new protected route without a matrix
  entry is an incomplete change.
- The onboarding wizard is tested as a state machine: in-order steps succeed, out-of-order
  steps 400, and step 5 skip succeeds.
- Never assert on a log line containing a credential; assert that logs are **redacted**.
- Fixtures live in `conftest.py`. No network in `unit/`, ever.

```bash
uv run pytest -m unit          # fast loop
uv run pytest -m integration
uv run pytest                  # everything, with coverage
```
