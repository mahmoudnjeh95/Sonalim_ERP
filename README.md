# Sonalim ERP

Modular-monolith ERP platform. Architecture rules live in `.claude/skills/erp-platform-architecture/SKILL.md`.

## Run locally


```

Services:

- API: http://localhost:8000 and http://localhost:8000/docs
- Web (CRM UI): http://localhost:5173
- RabbitMQ management: http://localhost:15672 (`erp` / `erp`)
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000

## Deploy the API to Vercel

The API requires an external PostgreSQL database. Vercel does not provide the
Compose `postgres` service, so add these environment variables in the Vercel
project settings for the relevant environments:

- `DATABASE_URL`: the connection string for a hosted PostgreSQL database
- `FRONTEND_ORIGINS`: the deployed frontend origin, for example
	`https://your-frontend.example.com`

Deploy from the repository root; `vercel.json` points the build at
`backend/api/index.py`, the Vercel ASGI entrypoint.
The application runs migrations during startup, so the database must be
reachable from Vercel and the configured database user must be allowed to
create and alter the application tables. Do not use the Compose URL
`postgresql://erp:erp@postgres:5432/erp` on Vercel; `postgres` is only the
internal Docker service hostname.

Stop the stack with `Ctrl+C`, or run `docker compose down`. Add `-v` only when you intentionally want to delete local database, Redis, and Grafana data.

The application and worker share the same image. Modules remain inside the monolith and must communicate through their public APIs and events; containers provide infrastructure, not module boundaries.

## Modules

`backend/core` is the shared kernel (Product, Partner, UoM, Currency, Company, tenancy, auth, audit). Business modules live under `backend/modules/`: `warehouse`, `production`, `crm`, `sales`, `finance`, `hr`, `procurement`, `qc`, and `maintenance`. Each ships a `module.json` manifest, `domain/`, `api/`, and `migrations/`; migrations run automatically on app/worker startup and are tracked per-module in `core.module_migrations`.

Migration load order is `core → warehouse → production → crm → sales → finance → hr → procurement → qc → maintenance` (`backend/core/migrations/runner.py`). `core` runs first because other schemas reference its tables; `qc` runs after `production` for readability rather than necessity — it holds `of_id` as an opaque column with no foreign key into `production`, because a module may not reference another's tables. `maintenance` runs last of all: its own `equipment` registry was split out of `production.machines`, and its init migration copies that table's rows across before a second migration drops it — both steps need `production`'s migrations to have already run.

Seed a demo tenant (user, UoM, product, partner) once the stack is up:

```powershell
docker compose exec app python -m scripts.seed_dev
```

Then log in and use the token as a bearer token against any endpoint:

```powershell
curl -X POST http://localhost:8000/core/auth/login -H "Content-Type: application/json" -d "{\"email\":\"demo@sonalim-erp.local\",\"password\":\"demo1234\"}"
```

`sales.order.confirmed` demonstrates the full event flow: confirming a sales order synchronously checks and reserves stock via the warehouse module's API (an immediate cross-module answer, not an event), then publishes an event that the `worker` process relays through RabbitMQ and `finance` consumes idempotently to auto-draft an invoice.

## Frontend

`frontend/` is a separate React + TypeScript SPA (Vite, TanStack Query, Tailwind) that talks to the API over HTTP — it is not part of the Python image and has no access to module internals, only the public `/api` routes every other caller uses. It builds inside Docker (`web` service above), so no local Node install is required to run the stack. Auth is a bearer token from `/core/auth/login` held in `sessionStorage`; this is an interim choice pending a dedicated security pass (see `frontend/README.md`).

## Tests

Domain-layer unit tests run without a database:

```powershell
cd backend
pip install -r requirements-dev.txt
pytest
```

Integration tests (files ending `_integration.py`) exercise the real SQL against a
migrated database. They pick the first reachable one of `TEST_DATABASE_URL`,
`DATABASE_URL`, then `postgresql://erp:erp@localhost:5432/erp`, and **skip** when
none is reachable or migrated — so the command above stays green on a machine
without a database. Every test runs inside a transaction that is rolled back, which
makes them safe to point at a development database:

```powershell
$env:TEST_DATABASE_URL = "postgresql://erp:erp@localhost:5432/erp"
pytest
```