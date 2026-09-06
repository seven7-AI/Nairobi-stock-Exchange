## What changed

<!-- One or two sentences. Reference the conventional-commit scope you used. -->

## Why

<!-- The problem this solves. Link an issue if there is one. -->

## CodeGraph review (required)

This repo is CodeGraph-indexed. Every change is expected to have been made with the blast
radius in view, not by grep-and-hope.

- [ ] I queried CodeGraph before editing (`codegraph explore "..."` or `codegraph_explore`)
- [ ] I reviewed the **blast radius** for every symbol I changed and updated its callers
- [ ] `make graph` was run after structural changes so the index matches the tree

**Queries I ran:**

```
codegraph explore "..."
```

**What the blast radius showed:**

<!-- e.g. "calculate_for_row has 7 callers across cli.py and report_tasks.py; updated all." -->

## Checklist

- [ ] `make check` passes (codegraph sync + ruff + mypy + pytest)
- [ ] Every new protected route declares `Depends(require_roles(...))`
- [ ] Every new list endpoint is paginated
- [ ] New/changed routes have an RBAC matrix test (allowed role 2xx, disallowed role 403)
- [ ] No credentials, tokens, or password hashes reachable by a log statement
- [ ] `alembic revision --autogenerate` produces **no** diff against `stockanalysis_stocks`
- [ ] Commit messages follow `<type>(<scope>): <description>`
