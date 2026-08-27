# Sonalim ERP

Modular-monolith ERP platform. Architecture rules live in `.claude/skills/erp-platform-architecture/SKILL.md`.

## Run locally

Prerequisite: Docker Desktop with Compose enabled.

```powershell
docker compose build
docker compose up
```

Services:

- API: http://localhost:8000 and http://localhost:8000/docs
- Web (CRM UI): http://localhost:5173
- RabbitMQ management: http://localhost:15672 (`erp` / `erp`)
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000

Stop the stack with `Ctrl+C`, or run `docker compose down`. Add `-v` only when you intentionally want to delete local database, Redis, and Grafana data.

The application and worker share the same image. Modules remain inside the monolith and must communicate through their public APIs and events; containers provide infrastructure, not module boundaries.

## Modules

`core` is the shared kernel (Product, Partner, UoM, Currency, Company, tenancy, auth, audit). Business modules live under `modules/`: `warehouse`, `production`, `crm`, `sales`, `finance`, and `hr`. Each ships a `module.json` manifest, `domain/`, `api/`, and `migrations/`; migrations run automatically on app/worker startup and are tracked per-module in `core.module_migrations`.

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
pip install -r requirements-dev.txt
pytest
```