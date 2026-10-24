# Contributing to Agentrum

Thanks for your interest in contributing to Agentrum!

## Development setup

```bash
uv sync                       # install dependencies
make compose-up               # PostgreSQL on :5433
make migrate                  # alembic upgrade head
make serve                    # API on :12122
make test                     # unit tests
make test-integration         # integration tests (uses the compose DB)
make lint                     # ruff
```

The UI lives in `ui/` (`npm install && npm run dev`, Next.js static export,
bilingual via react-i18next).

## Pull requests

- One logical change per PR; keep refactors separate from features.
- Add/adjust tests for behavior changes (unit + integration).
- `make lint && make test` must pass; CI runs the same plus the Helm template check.
- Sign off your commits (`git commit -s`) — the DCO applies
  (<https://developercertificate.org/>).
- PRs must include a `# Description` section and a changelog note.

## Reporting bugs & proposing features

Open a GitHub issue. For security issues use the process in
[SECURITY.md](SECURITY.md) — never public issues.

## Code style

- Python: ruff-enforced, line length 100, type-hinted, async SQLAlchemy.
- Errors: raise domain errors from `agentrum.errors`; routers stay thin.
- Database access lives in services via SQLAlchemy models only.
