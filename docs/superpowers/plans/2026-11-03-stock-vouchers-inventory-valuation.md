# Stock vouchers, inventory and valuation — Implementation Plan (Part A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add document vouchers (receipt, issue, transfer, return), a physical inventory with a location freeze, weighted-average valuation and the valued-stock/movements reports to the `warehouse` module.

**Architecture:** Pure domain code in `modules/warehouse/domain/` (`valuation.py`, `inventory.py`, `voucher_rules.py`) decides every rule; `modules/warehouse/api/voucher_service.py` and `inventory_service.py` orchestrate and call the existing `StockService` methods inside one transaction; `StockService` gains a single `_assert_not_frozen` guard in each write path. No other module's tables are touched. The treasury module and the minimal purchase invoice are **separate plans** (Part B) that follow this one.

**Tech Stack:** FastAPI, raw SQL with psycopg 3, pytest; React 18 + TypeScript, TanStack Query, React Hook Form + Zod, Tailwind.

**Spec:** `docs/superpowers/specs/2026-11-03-stock-vouchers-inventory-treasury-design.md` (Part A and the confirmed decisions).

## Global Constraints

- "Depot" in the manual = `warehouse.locations` here. Stock is per `(tenant_id, location_id, product_id)` in `warehouse.stock_items`.
- Migrations: next number is `0012_*` in `backend/modules/warehouse/migrations/`. Never edit an applied one. Apply before integration tests from `backend/`: `.venv/Scripts/python -c "from dotenv import load_dotenv; load_dotenv('../.env'); from core.migrations.runner import apply_all_migrations; apply_all_migrations()"`.
- Money is `NUMERIC` F CFA, `decimal.Decimal` in Python for costs; quantities follow the existing service convention (`float` through `StockService`, validated by `_validate_quantity` against the product UoM). Do not mix: convert at the service boundary only.
- Errors are `Err(code, message_en, message_fr)`; router uses `err_detail(err)`. New codes: `STOCK_INSUFFICIENT`, `ORDER_QTY_EXCEEDED`, `RETURN_QTY_EXCEEDED`, `LOCATION_FROZEN`, `INVENTORY_ALREADY_OPEN`, `INVENTORY_NOT_OPEN`, `COUNT_REQUIRED`, `OBSERVATION_REQUIRED`, `VOUCHER_NOT_DRAFT`, `COST_REQUIRED`. `core/test_error_translations.py` must stay green.
- Every mutation calls `record_audit()` in the same transaction; routers pass `actor_id=tenant.user_id`.
- Permissions added to `warehouse/module.json`: `warehouse.manage_vouchers`, `warehouse.post_vouchers`, `warehouse.manage_inventory`, `warehouse.close_inventory`, `warehouse.view_valuation`. Not auto-granted; grant via `POST /core/users/{id}/permissions`.
- Events registered in `backend/events/CATALOG.md`: `warehouse.voucher.posted {voucher_id, type, number}`, `warehouse.inventory.closed {inventory_id, location_id, adjustments}`; add to `publishes_events`.
- Production shift validation keeps posting through `post_production_movement` unchanged **except** that it now refuses a frozen location (`LOCATION_FROZEN`). Production does not get vouchers.
- Every user-facing string uses `useI18n()` with keys in **both** `en` and `fr` (`frontend/src/lib/i18n.tsx`).
- Tests: domain tests need no DB; `*_integration.py` use the `db` fixture and **skip** without a DB — read the skip count. Run from `backend/`: `.venv/Scripts/python -m pytest modules/warehouse -q`. Frontend: `npx tsc -b --force` from `frontend/`.
- Shared working tree: never `git stash`; `git add` only listed files. Commits end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. **Do not push** (a push to `huge_production_migration` deploys to the live server).

## Decisions this plan makes where the spec is silent

1. **Numbering:** `RCP-2026-000001`, `ISS-…`, `TRF-…`, `RET-…`, `INV-…`; per tenant, type and calendar year, allocated at **post** time (drafts have no number) from a `warehouse.voucher_counters` row locked `FOR UPDATE`.
2. **Reserved stock counts as unavailable** for manual issues (available = on hand − reserved, blocked locations excluded), reusing `StockService.get_available_quantity`.
3. **Lots:** a voucher line may carry `lot_id`; when present, the lot-stock quantity is checked and moved through `LotService`. Lines without a lot behave as today.
4. **Return cost:** a return line copies the `unit_cost` of the issue line it references (`return_of_voucher_id`, `return_of_line_id`); averages are not recomputed from it.
5. **Inventory snapshot:** `theoretical_qty` is frozen at open time (the location is frozen from then on, so it cannot drift). Adjustment on close = `final_qty − theoretical_qty`, posted as `adjustment` moves with `source_type='inventory'`.
6. **Interim inventory** uses the same tables with `type='interim'`: no freeze, close records variances but posts no moves.
7. **Valuation seed:** existing stock has no cost history. A one-off backfill sets `avg_cost` from the catalog purchase price (the figure the overview already uses) and flags the row `cost_source='catalog'`; the valued report shows these rows with a marker until the first costed receipt replaces them.

## File map

Create:
- `backend/modules/warehouse/migrations/0012_warehouse_vouchers_inventory_valuation.sql`
- `backend/modules/warehouse/domain/valuation.py`, `inventory.py`, `voucher_rules.py` (+ `test_*.py` each)
- `backend/modules/warehouse/api/voucher_service.py`, `inventory_service.py`, `valuation_service.py` (+ `test_*_integration.py`)
- `frontend/src/features/warehouse/VouchersTab.tsx`, `VoucherDialog.tsx`, `InventoryTab.tsx`, `InventoryCountView.tsx`, `ValuedStockTab.tsx`

Modify:
- `backend/modules/warehouse/api/service.py` (freeze guard, `unit_cost` on receipt moves)
- `backend/modules/warehouse/api/router.py`, `module.json`, `backend/events/CATALOG.md`
- `frontend/src/features/warehouse/api.ts`, `WarehousePage.tsx`, `frontend/src/lib/i18n.tsx`

---

## Task 1 — Domain: weighted-average cost

**Files:** Create `domain/valuation.py`, `domain/test_valuation.py`.

- [ ] Write failing tests: `weighted_average(old_qty, old_cost, in_qty, in_cost)` → `(old_qty·old_cost + in_qty·in_cost)/(old_qty+in_qty)`; old_qty = 0 → `in_cost`; old_qty < 0 (production drove stock negative) → treat old_qty as 0 for the average; in_qty ≤ 0 raises `ValueError`; result rounded half-up to 4 decimals; `Decimal` in and out.
- [ ] Run `.venv/Scripts/python -m pytest modules/warehouse/domain/test_valuation.py -q` → fails.
- [ ] Implement `weighted_average` and `value_of(qty, avg_cost)` (negative qty values at 0 and is flagged by the caller).
- [ ] Run → passes. Commit `feat(warehouse): weighted-average cost domain function`.

## Task 2 — Domain: inventory count resolution

**Files:** Create `domain/inventory.py`, `domain/test_inventory.py`.

- [ ] Failing tests for `resolve_count(theoretical, c1, c2, c3) -> CountResult(final_qty, variance, needs_third, observation_required)`:
  - c1 == c2 → `final = c1`, `needs_third=False`.
  - c1 != c2, c3 None → `needs_third=True`, no final yet (`COUNT_REQUIRED` raised by the service on close).
  - c1 != c2, c3 given → `final = c3`.
  - `variance = final − theoretical`; `observation_required = variance != 0`.
  - Missing c1 or c2 → not resolvable.
- [ ] Implement as a frozen dataclass + pure function. Run → passes. Commit.

## Task 3 — Domain: voucher rules

**Files:** Create `domain/voucher_rules.py`, `domain/test_voucher_rules.py`.

- [ ] Failing tests for: `check_issue_available(available, qty)`; `check_order_cumulative(ordered, already_issued, qty)` → `ORDER_QTY_EXCEEDED`; `check_return(issued, already_returned, qty)` → `RETURN_QTY_EXCEEDED`; `check_transfer(source_id, dest_id, available, qty)` (same location refused); `below_minimum_warning(on_hand_after, minimum)` returns a bool (non-blocking); `require_cost(type, lines)` → receipts need `unit_cost` (`COST_REQUIRED`).
- [ ] Implement returning `Result` types matching the repo's `Ok/Err` convention (look at `core` for the import). Run → passes. Commit.

## Task 4 — Migration

**Files:** Create `migrations/0012_warehouse_vouchers_inventory_valuation.sql`.

- [ ] Tables (all `tenant_id TEXT NOT NULL`, ULID text ids, no cross-module FKs; FK to `core.products` allowed per 0010/0011):
  - `warehouse.voucher_counters (tenant_id, voucher_type, year, last_number, PK(tenant_id, voucher_type, year))`
  - `warehouse.vouchers (id, tenant_id, number NULL, type CHECK IN ('receipt','issue','transfer','return'), status CHECK IN ('draft','posted','cancelled') DEFAULT 'draft', source_location_id, dest_location_id, partner_id, ref_type, ref_id, return_of_voucher_id, note, created_by, created_at, posted_by, posted_at)`; unique `(tenant_id, number)` where number is not null.
  - `warehouse.voucher_lines (id, voucher_id, product_id, lot_id NULL, quantity NUMERIC CHECK > 0, unit_cost NUMERIC NULL, return_of_line_id NULL)`
  - `warehouse.inventories (id, tenant_id, number, location_id, type CHECK IN ('full','interim'), status CHECK IN ('open','closed','cancelled'), opened_by, opened_at, closed_by, closed_at, note)`; **partial unique index** `(tenant_id, location_id) WHERE status='open' AND type='full'` (one open full inventory per location).
  - `warehouse.inventory_lines (id, inventory_id, product_id, lot_id NULL, theoretical_qty, count_1, count_2, count_3 NULL, final_qty NULL, variance NULL, observation)`
  - `warehouse.stock_valuation (tenant_id, product_id, avg_cost NUMERIC NOT NULL, cost_source TEXT CHECK IN ('catalog','receipt'), updated_at, PK(tenant_id, product_id))`
- [ ] `ALTER TABLE warehouse.stock_moves ADD COLUMN IF NOT EXISTS unit_cost NUMERIC;`
- [ ] Backfill `stock_valuation` from the catalog purchase price (find the column the overview uses in `analytics_service.py`; products without one are skipped, not zeroed).
- [ ] Apply the migration; confirm with `\d` or a quick select. Commit.

## Task 5 — Freeze guard in `StockService`

**Files:** Modify `api/service.py`; Create `api/test_freeze_integration.py`.

- [ ] Failing integration test: open a full inventory row on a location (insert directly), then `receive_stock`, `issue_stock`, `transfer_stock` (either end), `adjust_stock`, `post_production_movement` each return `Err("LOCATION_FROZEN")`; a different location is unaffected; after closing the inventory they succeed.
- [ ] Add `_assert_not_frozen(tenant_id, location_id) -> Err | None` (`SELECT 1 FROM warehouse.inventories WHERE … status='open' AND type='full'`) and call it at the top of every write path. Give `adjust_stock` (and a new internal path) a keyword `_from_inventory: bool = False` that skips the guard **only** for the inventory-close service; never expose it on the router.
- [ ] Add `unit_cost: Decimal | None = None` to `receive_stock` and store it in `stock_moves.unit_cost`; after storing, call `ValuationService.apply_receipt` (Task 7) when a cost is present.
- [ ] Run `.venv/Scripts/python -m pytest modules/warehouse modules/production -q`; confirm existing tests are still green and read the skip count. Commit.

## Task 6 — Voucher service

**Files:** Create `api/voucher_service.py`, `api/test_voucher_service_integration.py`; Modify `api/router.py`, `module.json`.

- [ ] Failing integration tests, one per rule: draft CRUD (edit only while `draft`, else `VOUCHER_NOT_DRAFT`); post receipt (stock up, move has `source_type='voucher'`, number allocated, `unit_cost` stored); post issue with insufficient stock → `STOCK_INSUFFICIENT` and **no partial moves** (atomicity); cumulative order cap across two issues; transfer posts matching out/in moves; return capped by issued − returned and restocks at the chosen location; posting twice is idempotent-safe (`VOUCHER_NOT_DRAFT`); event `warehouse.voucher.posted` written to the outbox.
- [ ] Implement `VoucherService`: `create_draft`, `update_draft`, `cancel`, `post`, `get`, `list(filters)`, `create_issue_from_order(order_id, location_id, quantities)` (reads the sales order through the sales module's public `api/` service — look it up, never SQL on sales tables). Post runs all lines in one transaction, calls `StockService` methods, the caller commits.
- [ ] Router: `GET/POST /warehouse/vouchers`, `PATCH /warehouse/vouchers/{id}`, `POST /warehouse/vouchers/{id}/post`, `POST /warehouse/vouchers/{id}/cancel`, `POST /warehouse/vouchers/from-order/{order_id}`; permissions `manage_vouchers` (create/edit) and `post_vouchers` (post/cancel).
- [ ] Update `module.json` (permissions, `publishes_events`) and `events/CATALOG.md`. Run the warehouse tests + `core/test_error_translations.py`. Commit.

## Task 7 — Valuation service and reports

**Files:** Create `api/valuation_service.py`, `api/test_valuation_integration.py`; Modify `api/router.py`.

- [ ] Failing tests: receipt with cost updates `avg_cost` and flips `cost_source` to `receipt`; issue/transfer leave it unchanged; receipt without cost keeps the average and is listed under `missing_cost` in the report; negative on-hand counts as 0 in the average.
- [ ] Implement `ValuationService.apply_receipt(tenant_id, product_id, location_id?, qty, unit_cost)` (average is per product across locations: total on hand from `stock_items`), `valued_stock(tenant_id, location_id?)` → rows `{product_id, qty, avg_cost, value, cost_source}` + total, and `movements_report(filters)` joining voucher numbers via `source_id`.
- [ ] Router: `GET /warehouse/valuation` (`view_valuation`), `GET /warehouse/stock/movements-report` (existing `view_moves`), both with `?format=xlsx`. Reuse the repo's existing export helper if there is one (grep for `openpyxl`/`xlsx` in `backend`); if none, return CSV and say so in the commit — do not add a dependency without asking.
- [ ] Switch `analytics_service.py` stock value to `avg_cost` where present, falling back to catalog price; update its test. Commit.

## Task 8 — Inventory service

**Files:** Create `api/inventory_service.py`, `api/test_inventory_integration.py`; Modify `api/router.py`.

- [ ] Failing integration tests: open full → snapshot lines for every product (and lot) with stock at the location, location frozen, second open on the same location → `INVENTORY_ALREADY_OPEN`; record counts (c1, c2, c3) and verify `final_qty`/`variance` via Task 2; close with an unresolved line → `COUNT_REQUIRED`; close with variance and no observation → `OBSERVATION_REQUIRED`; close posts one `adjustment` per non-zero variance with `source_type='inventory'` and unfreezes; interim inventory neither freezes nor posts; blank sheet endpoint returns theoretical quantities with empty counts; cancel unfreezes.
- [ ] Implement `InventoryService`: `open(location_id, type, product_filter?)`, `record_count(inventory_id, line_id, which, qty, observation?)`, `close`, `cancel`, `get`, `list`, `blank_sheet`. Close calls `adjust_stock(..., _from_inventory=True)`. Number via the counters table.
- [ ] Router: `/warehouse/inventories` (list/create), `/{id}` (get), `/{id}/lines/{line_id}/count` (PATCH), `/{id}/close`, `/{id}/cancel`, `/{id}/blank-sheet`; `manage_inventory` for open/count/cancel, `close_inventory` for close.
- [ ] Event `warehouse.inventory.closed`. Run all warehouse + production tests. Commit.

## Task 9 — Frontend: vouchers

**Files:** Modify `features/warehouse/api.ts`, `WarehousePage.tsx`, `i18n.tsx`; Create `VouchersTab.tsx`, `VoucherDialog.tsx`.

- [ ] Add query hooks (`useVouchers`, `useVoucher`, `useCreateVoucher`, `usePostVoucher`, …) following the existing hooks in `api.ts`.
- [ ] `VouchersTab`: list with type/status filters (reuse the table helpers used by `StockHistoryTab`), badge for draft/posted/cancelled, post/cancel actions gated by permission.
- [ ] `VoucherDialog`: type-specific form (React Hook Form + Zod), product lines via the shared `ProductSelect`, available-stock hint per line, below-minimum warning (non-blocking), error display from `detail.message`.
- [ ] "Create issue from order" entry point on the sales-order side is a small button that navigates here with the order id; wire it only if the sales page exposes the order id cleanly, otherwise note as follow-up.
- [ ] i18n keys en + fr. `npx tsc -b --force` clean. Commit.

## Task 10 — Frontend: inventory and valued stock

**Files:** Create `InventoryTab.tsx`, `InventoryCountView.tsx`, `ValuedStockTab.tsx`; Modify `api.ts`, `WarehousePage.tsx`, `i18n.tsx`.

- [ ] `InventoryTab`: list, "Open inventory" dialog (location, full/interim), frozen-location badge.
- [ ] `InventoryCountView`: grid of lines with count 1/2/3 inputs (count 3 enabled only when 1≠2), live variance, observation required marker, close button disabled until every line resolves; blank-sheet print view.
- [ ] `ValuedStockTab`: valued table with total, marker for `cost_source='catalog'`, export button.
- [ ] Show an inline notice on the Stock tab for frozen locations. i18n en + fr. `npx tsc -b --force` clean. Commit.

## Task 11 — End-to-end check and handoff

- [ ] Full backend run: `.venv/Scripts/python -m pytest modules/warehouse modules/production core -q`; report passed/skipped counts honestly (skips mean no DB).
- [ ] Seed or manually exercise against the dev DB (`python -m scripts.seed_dev` if needed): receive with cost → check average; open inventory → confirm a production shift validation is refused with `LOCATION_FROZEN`; close → check adjustments.
- [ ] Use the `run` skill to start the app and confirm the Vouchers, Inventory and Valued stock tabs render in both languages.
- [ ] Grant the new permissions to the demo user via the API for the walkthrough.
- [ ] Update `docs/superpowers/specs/2026-09-24-warehouse-module-review.md` next steps 2 and 5 as delivered. Do not push.

## Follow-up plans (not in this plan)

- Part B1: minimal purchase invoice (module owner to be chosen).
- Part B2: `treasury` module — master data, receipts, disbursements, instrument lifecycle, statement import, alerts, deferred ledger-posting consumers.
- Returns wired to a sales delivery flow, if sales adds one.
