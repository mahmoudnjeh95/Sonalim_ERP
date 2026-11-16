# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current mission

All work is driven by `docs/ROADMAP.md` (market-readiness roadmap): read it at the start of every session, take one work package per session, and update its Progress log and checkboxes before stopping.

## Commands

Windows box; backend venv lives at `backend/.venv`. 
- Backend tests: `.venv/Scripts/python -m pytest modules/production -q`
- Single test: `.venv/Scripts/python -m pytest modules/production/api/test_shift_validation_integration.py::test_name -q`
- Seed dev data: `.venv/Scripts/python -m scripts.seed_dev` (demo login `demo@sonalim-erp.local` / `demo1234`); other month seeds in `backend/scripts/seed_*.py`

CI: `.github/workflows/tests.yml` runs the backend suite (fresh Postgres: `backend/docker/postgres/init.sql`, all migrations, `seed_dev`) and frontend `tsc` + vitest on every PR and push to `main`; `deploy.yml` will not build or deploy unless it passes.

Tests: `test_*.py` sit next to the code. Domain tests (`*/domain/test_*.py`) need no DB. `*_integration.py` tests use the `db` fixture from `backend/conftest.py`, which connects to `TEST_DATABASE_URL` → `DATABASE_URL` → `postgresql://erp:erp@localhost:5432/erp`, requires migrated schema, rolls back every test, and **skips** (not fails) when no DB is reachable — a green run with many skips means nothing was tested.

Env: a repo-root `.env` is auto-loaded by `app/main.py` (see `.env.example`). Missing `REDIS_URL` only logs harmless rate-limit tracebacks. Set `PYTHONUTF8=1` when piping API JSON through Python (accented French names).

## Architecture

Modular monolith: FastAPI + raw SQL via `psycopg` (no ORM), React SPA. Full rules in `.claude/skills/erp-platform-architecture/SKILL.md` — load it before touching module boundaries, events, or migrations.

- `backend/core/` — shared kernel (auth, tenancy, users/roles/permissions, products, partners, UoM, currencies/exchange rates, audit, outbox events, migration runner).
- `backend/modules/<module>/` — bounded contexts (warehouse, production, crm, sales, finance, hr, procurement, qc, maintenance), each with `domain/` (pure logic), `api/` (services + `router.py`), `events/` (consumers), `migrations/` (numbered SQL), and `module.json` (manifest: deps, provided services, events, **permissions**).
- Modules never read each other's tables; they call the other module's `api/` services or react to events. Only shared-kernel tables are referenced across modules.
- Events: transactional outbox row written in the same transaction as the change; `backend/worker/main.py` dispatches the outbox to RabbitMQ and runs consumers (must be idempotent on `event_id`). Register every new event in `backend/events/CATALOG.md`.
- Migrations: numbered SQL files per module, applied in `MODULE_ORDER` by `core/migrations/runner.py` and tracked in `core.module_migrations`. Add a new file with the next number; never edit an applied one. App and worker startup call `migrate_on_startup()`, which applies them when `AUTO_MIGRATE=true` (the default, in `compose.yaml` and locally) under a Postgres advisory lock; with `AUTO_MIGRATE=false` it just logs the pending ones. Migrations are schema only -- never test/demo data (no `INSERT ... VALUES` rows, no demo tenant); `core/migrations/test_migration_data_guard.py` enforces it. Backfills derived from existing rows (`INSERT ... SELECT`) are fine.
- Auth/tenancy: routes depend on `core.tenancy.require_session` / `require_permission("<code>")`; permission codes are declared in the module's `module.json` (the catalog is aggregated from these). New permissions are not auto-granted to the demo user — grant via `POST /core/users/{id}/permissions`.
- Router errors raise `HTTPException` with `detail={"code", "message"}`; `frontend/src/lib/api.ts` (`apiFetch`) relies on that shape and fires `auth:unauthorized` on 401.

Frontend (`frontend/src/`): Vite + React 18 + TS, TanStack Query for server state, React Router, Tailwind + hand-written Radix primitives in `components/ui/`, React Hook Form + Zod, Recharts, Framer Motion. `features/<module>/` holds pages and an `api.ts` of query hooks per module; `routes/` has the router, layout and sidebar; `lib/` has fetch, auth (session in `sessionStorage["sonalim-erp.session"]`), i18n and table helpers. SVGs are imported as React components with `?react`; placement/sizing rules are in `.github/copilot-instructions.md` (and the `svg-asset-rules` skill).

Production is the largest and most active module. The per-shift report (`shift_report_service.py`, `shift_sections.py`, `shift_validation_service.py`, `shift_stock_service.py`) is replacing the legacy Daily + Conditionnement reports; validating a shift is what posts stock. Design specs and plans live in `docs/superpowers/specs` and `docs/superpowers/plans`.

## Deployment and safety

- Every push to `huge_production_migration` builds and deploys to the live server (`.github/workflows/deploy.yml`). Don't push without the user asking.
- A deploy applies pending schema migrations automatically (`AUTO_MIGRATE` defaults to true in `compose.yaml`) but never loads data: no seed script runs, and migrations can't carry test data (guard test above). To apply by hand instead, set `AUTO_MIGRATE=false` in the server `.env` and use `docker compose exec -T app python -m scripts.migration_sql > pending.sql` then `docker compose exec -T postgres psql -U erp -d erp < pending.sql`.
- Git hooks: `git config core.hooksPath tools/git-hooks` — the pre-commit hook refuses DB dumps/backups (`*.dump`, `*.bak`, …), which may contain real customer data.
- UI is bilingual (en/fr) via `frontend/src/lib/i18n.tsx` — add both keys for new strings. The currency is F CFA.
