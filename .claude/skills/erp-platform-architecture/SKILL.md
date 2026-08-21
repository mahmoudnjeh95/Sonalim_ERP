---
name: erp-platform-architecture
description: Apply the 3S ERP modular-monolith architecture when designing, implementing, reviewing, or extending modules, APIs, events, migrations, persistence, security, observability, and tests.
---

# ERP Platform Architecture

Use this skill as the source of truth for architectural decisions in the 3S ERP repository. Keep it accurate as the platform evolves.

## Architecture

The platform is a modular monolith. Each business domain (warehouse, production, CRM, sales, finance, HR, and so on) is an independent bounded context with its own schema, service layer, and public API. Modules never access one another's tables directly.

```text
/core            shared kernel: Product, Partner, UoM, Currency, Company,
                 Sequence/Numbering, Auth, Tenancy, Audit
/events          event catalog, schemas, outbox dispatcher
/modules
  /warehouse
    /domain      entities, value objects, business rules
    /api         public service interface; the only cross-module interface
    /events      publishers and subscribers
    /migrations
    module.json  manifest
  /production
  /crm
  /sales
  /finance
```

## Hard Rules

- Never access another module's tables, including read-only joins. Use that module's `/api` service layer.
- Only shared-kernel tables may be referenced directly across modules: Product, Partner, UoM, Currency, and Company.
- Cross-module side effects use events. Direct synchronous calls are only for immediate answers required by the caller, such as current stock availability.
- Commands are imperative and synchronous (`ReserveStock`); events are past-tense and asynchronous (`warehouse.stock.reserved`).
- A database write that emits an event must insert its transactional outbox row in the same transaction. Never publish directly mid-transaction.
- Every event consumer must be idempotent by checking `event_id` in a processed-events log before acting. Delivery is at least once.
- A new module must ship `module.json` before domain code. Declare dependencies up front.

## Module Manifest

Every module manifest follows this shape:

```json
{
  "name": "warehouse",
  "version": "0.1.0",
  "depends": ["core"],
  "optional_depends": ["production"],
  "provides_api": ["StockService", "InventoryValuationService"],
  "publishes_events": ["warehouse.stock.reserved", "warehouse.stock_move.completed"],
  "subscribes_events": ["sales.order.confirmed", "production.work_order.completed"],
  "migrations_path": "./migrations",
  "permissions": ["warehouse.view_moves", "warehouse.manage_stock"]
}
```

## Events

Name events `{module}.{aggregate}.{past_tense_verb}`. Every event uses this envelope:

```json
{
  "event_id": "ulid",
  "event_type": "warehouse.stock_move.completed",
  "event_version": "1.0",
  "occurred_at": "iso8601",
  "producer": "warehouse",
  "tenant_id": "...",
  "correlation_id": "...",
  "causation_id": "...",
  "payload": {}
}
```

Payloads are thin: IDs and minimal context, not full snapshots. Audit and compliance events are the exception and may contain fat, immutable snapshots. Add every new event to `/events/CATALOG.md` before merging the publishing code.

## Transactional Outbox

For every publishing module:

1. Perform the business write and insert the outbox row in one database transaction.
2. Have a background dispatcher publish pending rows and then mark them sent.
3. Deduplicate consumers by `event_id`.

## Testing

- Unit tests cover module domain logic without a database or other modules.
- Contract tests cover every published event and public API method and run in CI before merge.
- Integration tests use the module's own database and API with a mocked event bus.
- Keep cross-module end-to-end tests deliberately small and focused on critical flows.
- Every event handler has an idempotency test that delivers the same event twice and verifies no duplicate side effects.

## Migrations

- Each module owns independently tracked migrations in a `module_migrations` table containing module name and version.
- Migrations must remain backward-compatible with the previous module version during rolling deploys. Do not drop a column in the same release that stops writing it.
- Every up-migration needs a down-migration in development. Production data-loss risk for down-migrations must be documented.

## Errors and Resilience

- Return typed results for domain errors; raise exceptions for infrastructure errors and apply retry or circuit-breaker behavior at the boundary.
- Failed event handling goes to a dead-letter queue. Do not silently drop failures or retry forever in place.
- Public APIs expose typed error codes such as `INSUFFICIENT_STOCK` and `INVALID_UOM_CONVERSION`; never leak database or stack-trace details across module boundaries.

## Observability

- Propagate `correlation_id` through every event and API call and log it across the full business transaction.
- Use structured JSON logs with module name, event type, tenant ID, and correlation ID as standard fields.
- Emit per-module metrics for event publish and consume rates, handler latency, dead-letter queue depth, and API error rates.

## Security and Tenancy

- `tenant_id` is mandatory on every table and event. Enforce tenant scoping in the ORM or query builder, not by convention.
- Permission checks belong in the module API layer.
- Derive tenant identity from the authenticated server-side session; never trust client-provided `tenant_id` alone.

## API and Event Versioning

- The `/api` folder is a public contract. Breaking changes require a new version such as `StockServiceV2`; retain the old version until callers migrate.
- Event schema additive changes bump the minor version. Breaking changes bump the major version and run in parallel during migration.

## Coding Conventions

Language, framework, naming, folder, dependency-injection, lint, and formatting conventions are intentionally pending until the implementation stack is chosen. Update this section when that decision is made.

## New Module Checklist

1. Write `module.json` with dependencies, APIs, published events, and subscribed events before domain code.
2. Add new events to `/events/CATALOG.md`.
3. Define the public `/api` surface before internal implementation.
4. Write API and event contract tests first.
5. Verify there is no direct table access into another module.
6. Add the module to dependency-graph and load-order documentation.