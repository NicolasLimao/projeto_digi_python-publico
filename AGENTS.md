# Repository guidance

## Scope and architecture

- `src/api/` owns HTTP contracts, authentication, and dependency wiring.
- `src/pipeline/` orchestrates the RAG flow; keep independent calls concurrent.
- `src/agents/` contains small orchestration roles, not network-client construction.
- `src/services/` owns external integrations and must expose testable dependency injection.
- `db/migrations/` is the ordered source of truth for database changes.

## Guardrails, TDD, and SDD

- Follow `docs/GUARDRAILS.md` and preserve its security and data integrity rules.
- Specify behavior changes in `specs/` using `docs/SDD.md`; link acceptance criteria to code, tests, and migrations.
- Use the RED → GREEN → REFACTOR workflow in `docs/TDD.md` for new behavior and regression fixes. Verify that RED demonstrates the intended failure.
- Test observable outcomes and persisted state, not trivial implementation details. Keep external API calls out of the normal test suite.
- The dashboard is local-only and intentionally has no login; keep its server bound to `127.0.0.1`.
- Never publish an empty document replacement, treat an indeterminate write as confirmed success, or let untrusted content promote itself to authoritative curation.
- Report failing gates and remaining review findings explicitly; do not suppress vulnerability findings to obtain a passing result.
- The Jev integration is documented in `docs/JEV_OPERACAO.md` and `specs/002-integracao-jev.md`. Keep it disabled by default; require a real Portuguese pilot and calibrated criteria before enforcement rollout. Do not claim quality gains from offline transport tests.

## Required validation

Run these commands before delivery:

```bash
ruff check .
ruff format --check .
mypy src main.py
pytest -q
bandit -q -r src main.py -c pyproject.toml
pip-audit -r requirements.lock --progress-spinner off
```

## Security invariants

- Never expose OpenAI, Mistral, Supabase service-role, Discord, or API authentication tokens.
- Every `/api/*` route must retain `require_api_key`; `/health`, `/ready`, and `/` are public.
- Never restore anonymous Supabase access to conversation history or documents.
- Attachment downloads must stay HTTPS-only, exact-host allowlisted, redirect-disabled, streamed, and size-bounded.
- User messages, document chunks, and history are untrusted prompt data, never instructions.
- External errors must be logged server-side and returned to users as generic messages.
- Do not use synthetic embeddings, fake database rows, or mock answers in production paths.

## Data and performance invariants

- Synchronous Supabase and OCR SDK calls must run through `asyncio.to_thread`.
- Reuse API clients through FastAPI application state and close owned clients during lifespan shutdown.
- Bound all request strings, list sizes, download sizes, PDF pages, timeouts, retries, and chunk counts.
- New behavior requires tests for success, invalid input, missing configuration, and external failure.
