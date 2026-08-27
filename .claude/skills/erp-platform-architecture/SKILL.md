---
name: erp-platform-architecture
description: Apply the Sonalim ERP modular-monolith architecture when designing, implementing, reviewing, or extending modules, APIs, events, migrations, persistence, security, observability, and tests.
---

# ERP Platform Architecture

Use this skill as the source of truth for architectural decisions in the Sonalim ERP repository. Keep it accurate as the platform evolves.

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

Language, framework, naming, folder, and dependency-injection conventions largely follow the existing modules — see `frontend/README.md` and each module's `api`/`domain` layout for examples. Lint and formatting conventions remain pending.

### Frontend i18n

Every user-facing string in `frontend/` must go through `useI18n()` — no hardcoded English text in JSX (labels, table headers, dialog copy, toasts, placeholders that convey meaning, status/category labels). Add the key to **both** the `en` and `fr` dictionaries in `frontend/src/lib/i18n.tsx` in the same edit that introduces the string; the `fr` object is typed as `Record<TranslationKey, string>` so `tsc` fails if a key is missing from either language — treat that as the enforcement mechanism, not a style suggestion.

Namespace keys per feature (`production.workOrders.*`, `warehouse.receipts.*`, `sales.*`, ...), mirroring the existing `crm.leads.*` / `partners.*` pattern. Reuse the shared `status.*` namespace only for statuses that are genuinely shared across modules and already listed there (draft, confirmed, completed, ...); if a module has its own status vocabulary not in that shared set (e.g. a recipe's `trial`), give it its own `*.status.*` keys instead of stretching the shared ones.

**Why:** the CRM pages, login, settings, and nav were built with `useI18n` from the start, but Warehouse, Production, Sales, Finance, and Admin/Users were built with hardcoded English and silently ignored the language switch until this was caught and fixed (all 14 files retrofitted 2026-08-24). New modules must not repeat this — wire `useI18n` in from the first commit of any user-facing component, not as a follow-up pass.

The `t()` function only returns fixed strings — no interpolation. For dynamic sentences (counts, names), either split into fixed fragments concatenated in code (acceptable for short pluralized fragments, e.g. "N record(s)") or keep the fully-dynamic part (an id, a raw number) outside `t()` entirely. Don't add an interpolation layer to `i18n.tsx` without a real need for it.

### Frontend data fetching

Every view that reads or writes server data goes through **TanStack Query** (`useQuery`/`useMutation`) — never a bare `fetch`/`useEffect` data-loading pattern. This is already the stack choice in `erp-frontend-stack` SKILL.md; this line makes it an enforced convention for this repo specifically, not just a recommendation. Follow the existing pattern in any feature's `*Tab.tsx`/`*Page.tsx`: a module-level `const X_QUERY_KEY = [...] as const`, `useQuery({ queryKey, queryFn })` for reads, `useMutation` for writes with `onSuccess` calling `queryClient.invalidateQueries({ queryKey })` on every query key the write affects (including cross-feature ones, e.g. a stock-affecting mutation invalidates both its own list and `["warehouse", "stock"]`).

### Audit logging (ISO 9001 traceability)

Every mutating action in every module — create, update, delete, and every state transition — must call `record_audit()` (`core/audit.py`) in the same database transaction as the write, so the change and its audit row commit or roll back together. This is mandatory platform-wide, not opt-in per module.

Pattern (see `modules/warehouse/api/material_receipt_service.py` for the reference implementation):

1. Every mutating service method takes `actor_id: str` (no default — a mutation with no identifiable actor is a bug, not an edge case to tolerate silently).
2. Every router endpoint that calls a mutating method passes `actor_id=tenant.user_id` from the `TenantContext` — never a client-supplied value.
3. Call `record_audit(connection, tenant_id=..., actor_id=..., action="<module>.<entity>.<verb>", entity_type="<entity>", entity_id=..., payload={...})` right before (or as part of) the commit. Action names are `snake_case`, past-tense verb last (`material_receipt.status_changed`, `partner.archived`, `invoice.issued`). Payload is thin — before/after values that matter for an audit trail (e.g. `{"from_status": ..., "to_status": ...}`), not a full entity dump.
4. Deletes are audited too, with enough payload to reconstruct what was deleted (id, key identifying fields, status at deletion) — the audit row is the only record left once the row itself is gone.
5. Read `GET /core/audit-log` (filterable by `entity_type`/`entity_id`) is the single cross-module read path — do not build a per-module audit table or a parallel history endpoint.

**Why:** ISO 9001-style traceability ("who did what, when") was required for warehouse material receipts and built there first (2026-08-24) — `core.audit_log` and `record_audit()` already existed platform-wide before that (unused dead code). The requirement is platform-wide, not warehouse-specific; every module's mutating actions need the same trail. Retrofitting existing modules (CRM, sales, finance, production) is tracked as ongoing work — new mutating endpoints in any module must ship with audit logging from the start, not as a follow-up pass, exactly like the i18n lesson above.

### Frontend list filtering

Every list/table view needs two independent, composable filtering layers — build both from day one, not as a follow-up pass, exactly like the i18n and audit-logging lessons above:

1. **Enum/status filters** — `<FilterTabs>` (`components/patterns/FilterTabs.tsx`) rendered above the table, one pill per fixed value plus "All". This is for any column with a small closed set of values (status, stage, category, a boolean like blocked/available). Reuse the shared `status.*` i18n keys where the vocabulary is genuinely shared; give a module its own `*.status.*` keys otherwise (see the i18n section above).
2. **Per-column filters** — a filter-input row rendered immediately under the column-header row, one cell per column, for every column that isn't already covered by a FilterTabs control:
   - Free text / id / name columns → a text input, case-insensitive substring match.
   - Numeric columns (quantities, amounts, counts, rates) → a min/max range, two number inputs.
   - A column already driven by FilterTabs (status, category) → leave its filter-row cell blank; don't build two controls for the same field.
   - Columns that aren't meaningfully filterable (an action/buttons column, a progress bar, a raw timestamp, a derived boolean badge with no real query value) → leave the cell blank rather than forcing a control in.

Use the shared primitives — don't hand-roll this per table:

- `useColumnFilters<Row>(fields)` (`lib/useColumnFilters.ts`) — takes a `FilterField<Row>[]` (each either `{ key, kind: "text", getValue }` or `{ key, kind: "range", getValue }`) and returns `{ text, range, setTextValue, setRangeValue, isActive, reset, apply }`. Call `.apply(rows)` **after** any FilterTabs-based filtering, so the two layers compose (AND together) rather than duplicate each other.
- `<ColumnFilterRow cells={...}>` (`components/patterns/ColumnFilterRow.tsx`) — renders the input row; pass one `FilterCell` per column in the same order as the header `<TableHead>` cells (`{ type: "text" | "range" | "blank", ... }`), placed as a second `<TableRow>` inside `<TableHeader>` right after the header row.
- Show a "Clear filters" button (`t("common.clearFilters")`) next to the FilterTabs row whenever `columnFilters.isActive` is true, calling `columnFilters.reset()`.

**Exception:** if a table has exactly one column worth searching and the rest aren't filterable (e.g. `UsersPage` — email is the only free-text column; permissions/grant aren't), a single search `<Input>` above the table is an acceptable substitute for a full filter row. Don't force the row pattern where it would just be one input wide.

**Why:** built for Material Receipts first per an explicit request to filter by every column in the table (2026-08-24), then swept across all ~15 list views in the same pass — same rollout shape as the i18n and audit-logging retrofits. New list views must ship with both filtering layers from the start.

### Edit-in-place

Every entity that has a create action must also have an edit action — do not ship create-only CRUD and treat editing as a follow-up. This is a platform-wide requirement (2026-08-24), same rollout shape as the lessons above: new entities ship with edit from day one, existing ones are retrofitted incrementally.

1. **Permission:** edit is gated by a *separate* `<module>.admin_<entity>` permission — distinct from the `manage_*` permission the entity's create/transition actions use, not reused from it. This is deliberate: being able to create or progress a record through its normal workflow is a different, more common trust level than being able to reach in and directly overwrite a field on an existing one. Reference implementation: `warehouse.admin_material_receipts` (`modules/warehouse/api/material_receipt_service.py`'s `admin_update_receipt`/`admin_force_status`, `modules/warehouse/api/router.py`), built before this was generalized into a platform rule. Every entity's edit permission follows the same `admin_<entity>` naming. Nobody has it by default — it's granted per user through the existing Admin → Users flow, same mechanism as every other permission.
2. **Backend:** add `update_x(*, tenant_id, actor_id, entity_id, field=None, ...) -> Result[X]` (or `admin_update_x` for entities that already have a plain `update_x`/other method at that name) to the entity's service, alongside `create_x`. Every parameter besides `tenant_id`/`actor_id`/`entity_id` is optional and defaults to `None`, meaning "leave unchanged" — build the updated entity by falling back to the current stored value field-by-field, then run it through the *same* domain validation function `create_x` already uses before writing. Expose it as `PATCH /module/entities/{id}`, gated by the entity's `admin_<entity>` permission. Edits are allowed regardless of the record's current status/state — the elevated permission is what limits blast radius, not a status check; don't also bolt on a "only while draft" restriction, that's redundant with the permission gate and the material-receipts reference implementation doesn't do it either.
3. **Audit:** exactly like every other mutation — call `record_audit(..., action="<entity>.updated", entity_id=..., payload={...the fields that changed and their new values...})` in the same transaction as the write. Not optional for edits; a user correcting a record is exactly the kind of change ISO 9001 traceability exists to capture (who changed what, and when).
4. **Frontend:** a pencil/edit affordance per row opens the same dialog used for creation, pre-filled with the row's current values, submitting through an `update` mutation instead of `create`; `onSuccess` invalidates the same query key create does.

**Why:** every screen built this session shipped create + status-transitions but no way to fix a mistake in an existing row, across every module — confirmed as a real, deliberate gap (2026-08-24) rather than an oversight in any one feature, so it's the platform convention now, not a one-off fix. The permission design was refined the same day after finding `warehouse.admin_material_receipts` already existed as a working reference — a separate elevated permission per entity, not reuse of `manage_*`, is the actual established pattern to follow, not a first draft.

### Column resize & visibility

Every list/table view lets the signed-in user resize columns and show/hide them, persisted per-user so the layout survives reloads and follows them across devices. This is a platform-wide requirement (2026-08-26), same rollout shape as the lessons above: new tables ship with this from day one, existing ones were retrofitted in one pass across all ~26 list views.

1. **Define columns as data, not parallel JSX.** Every table's header row and body cells must be driven by a single `ColumnDef<Row>[]` array (`lib/useTableColumns.ts`) — `{ key, header, cell(row), defaultWidth?, alwaysVisible?, headerClassName?, cellClassName?, filterCell? }` — not two hand-synced lists of `<TableHead>`/`<TableCell>`. This is what makes "hide column N" safe: header, body, and (where present) the `<ColumnFilterRow>` all derive from the same array instead of three things that must stay in sync by position.
2. **Wire it with `useTableColumns(tableKey, columns)`.** `tableKey` must be a stable, globally unique id for the table (e.g. `"warehouse.stock"`, `"production.workOrders"` — module-qualified, matches the existing query-key naming style). Returns `visibleColumns`, `colWidths`, `isVisible`/`toggleVisible`, `getWidth`/`setWidth`, `resetAll`. Render the header via `visibleColumns.map(col => <ResizableTableHead .../>)`, pass `colWidths` to `<Table colWidths={...}>` (renders a `<colgroup>` — the correct HTML mechanism for column widths, not per-cell inline styles), and body cells via `visibleColumns.map(col => <TableCell>{col.cell(row)}</TableCell>)`. Add `<ColumnVisibilityMenu columns={columns} isVisible={...} onToggle={...} onReset={...} />` (`components/patterns/ColumnVisibilityMenu.tsx`) next to the table's existing filter controls.
3. **An actions/buttons column is `alwaysVisible: true`** — it can be resized but never hidden, so a user can't hide their way into a table with no way to act on a row.
4. **A cell that needs its own hooks** (a per-row `useQuery`/`useFieldArray`/`useEffect`, e.g. Purchase Orders' or Work Orders' receive/complete dialogs) must delegate to a real named subcomponent invoked via JSX (`cell: (row) => <RowActions row={row} .../>`), never call a plain function containing hooks from inside `.map()` — that violates the Rules of Hooks since the call count/order would vary with row count.
5. **Persistence is backend-owned, not `localStorage`.** `GET`/`PUT /core/table-preferences/{table_key}` (`core/table_preferences.py`), backed by `core.user_table_preferences (user_id, tenant_id, table_key, columns jsonb)`. Gated by `require_session` only — no `admin_*`/`manage_*` permission, since it's strictly self-scoped (a user can only ever read/write their own row, keyed by their own `user_id` from the session). Resize commits on drag-end, not per pixel; visibility commits immediately on toggle.
6. **Deliberately not audited.** Unlike every other mutating endpoint on the platform, `save_table_preferences` does **not** call `record_audit()`. This is an intentional, one-off exception to the "every mutation is audited" rule elsewhere in this document: a column-width drag is a personal display setting, not a business record, and logging it would be pure noise in the ISO 9001 audit trail. Don't treat this as precedent for skipping audit logging anywhere else — it applies only to this endpoint.

**Why:** requested as a platform-wide, apply-to-every-table feature (2026-08-26), so it was built once as a shared primitive and swept across every existing list view in the same pass, rather than one-off per table. The column-array refactor was necessary, not optional — the prior hand-rolled header/body JSX had no single source of truth to hide a column from safely.

## New Module Checklist

1. Write `module.json` with dependencies, APIs, published events, and subscribed events before domain code.
2. Add new events to `/events/CATALOG.md`.
3. Define the public `/api` surface before internal implementation.
4. Write API and event contract tests first.
5. Verify there is no direct table access into another module.
6. Add the module to dependency-graph and load-order documentation.