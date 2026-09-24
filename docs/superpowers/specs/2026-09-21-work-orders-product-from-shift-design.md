# Work orders: product from the shift report, and the OF view rework

Date: 2026-09-21. Builds on `2026-09-20-shift-report-core-design.md` and `2026-09-21-shift-form-rework-design.md`.

## Why

An OF is now created with only its line (plus PC/PL type, date and an optional supervisor). Its product used to be named by the first Conditionnement report; that flow is gone from the UI. Nothing in the shift report names the finished product today, so an OF made from the screen keeps no product for good (OF-000037 in the client's screenshot). The packing derivation, the stock posting at validation and the OF card all depend on it.

The client's rule: **an OF has no product until its first report is validated; then it takes the product from the report. If the reports show several products, the OF shows all of them.** A PC mold change mid-shift is the real case of several products on one OF.

While reproducing this, a second bug turned up. The Conditionnement column "De la production" (`run_id`, required) lists only production rows already **saved** in the Production section, so on a fresh shift it is an empty required dropdown and the section cannot be filled. Choosing the product directly removes it.

Two milestones, in this order. Milestone 2 shows nothing that milestone 1 cannot produce.

## Decisions (agreed 2026-09-21)

1. Packing rows carry their own finished product. "De la production" becomes **"Produit"**, a required dropdown of finished products.
2. **"Type de conditionnement" comes from the chosen product** (its net weight: 200 g, 500 g, 4540 g; the existing rule also prefixes the classified packaging format, e.g. "Sachet 500 g").
3. Until the first validated report, the OF card shows no product. After it, it shows every distinct product of its validated packing rows.
4. Validated figures are the official ones; pending (open or submitted) shifts are shown beside them, never mixed in.
5. Layout: compact cards in PC | PL columns, closed and cancelled OFs folded.
6. Creation stays as it is: line required, PC/PL and date as today, supervisor optional. The stale hint about Conditionnement naming the product is replaced.

## Milestone 1: finished product on the packing row

### 1.1 Screen (`frontend/src/features/production/shift/`)

`sectionConfig.ts`, packing part:

| Before | After |
|---|---|
| `run_id` "De la production" (required, source `runs`) | `product_id` "Produit" (required, new source `finishedProducts`) |
| (none) | `of_id` "OF" (optional select; choices = the OFs of this shift's runs; the server fills it when it can) |
| `packing_type` read-only, shown after save | still read-only, but shown as soon as a product is picked |

- `finishedProducts` in `useShiftReferenceData.ts`: products classified `finished_good`; every product while classifications are unreadable (the fallback `productsOrMp` already uses).
- The type label is shown immediately by a small client function of the product's net weight and classified packaging format, mirroring the backend rule. The server value is the truth and replaces it on the next load.
- `run_id` stays in the payload and the table (a packing row can still name its production); the screen just stops asking for it.
- Column order: Produit, OF, N° lot, Type de conditionnement, then the packaging items as today.

### 1.2 Schema (migration `0055`)

- `production.shift_packing_rows.product_id TEXT` (opaque, like `equipment_id`); backfilled from `production.work_orders.product_id` of the row's OF.
- `production.conditionnement_reports.product_id TEXT`; backfilled the same way. This is the old-shaped table validation still posts stock from; without its own product a second product on an OF would post under the first.
- `convert_legacy_reports()` is left as it is: a row it creates has no product of its own, and every reader falls back to the OF's product (`COALESCE(row product, OF product)`), which is what such a row made.

### 1.2b Several rows of one OF in one shift (migration `0056`, found while building)

The old-shaped header table had a unique index on (tenant, OF, type, date, shift): one report per OF per shift. The shift form already let a team enter two rows for the same OF (two products after a mold change), but validation then failed with "cannot be posted as entered". `production_reports` gains `shift_report_id` (set by `legacy_report_ledger` and backfilled from the run and packing ids), and the index is re-created as partial (`WHERE shift_report_id IS NULL`), so the old rule still holds for reports the old flow files, while a shift's own uniqueness (one report per line, date and shift) protects the rest. This also lets one OF have two runs in a shift.

### 1.3 Backend rules (`packing_derivation_service.py`, `shift_sections.py`)

Resolving a packing row's OF, in order:
1. The row's own `of_id`, if given and the OF accepts reports.
2. The OFs of the shift's runs: if exactly one, that one.
3. If several, the ones whose product equals the row's product: if exactly one, that one.
4. Otherwise `OF_AMBIGUOUS` (several candidates) or `PRODUCTION_FIRST` (the shift has no saved production yet), with a message the screen shows inline.

The row's product is what the team picked; a row that names none takes its OF's product (so existing data and OFs that already have a product keep working). The row's production link (`run_id`) is filled when the resolved OF has exactly one run on the shift, else left empty, and is no longer sent back by the screen. The screen clears the row's `of_id` when its product changes, so the OF is resolved again.

Derived from the row's **own** product (not the OF's): `packing_type`, `packets_counted` from cartons x `packets_per_carton`, the finished-goods store (line store, else the product's default location). `PACKAGING_STORES_DIFFER` is unchanged.

Submit refuses a packing row with no product (`PRODUCT_REQUIRED`); a draft may save without one.

### 1.4 Validation and stock

One helper, `finished_product_of_report`, returns the packing report's own `product_id`, else its OF's. It replaces the direct reads of `work_orders.product_id` in:
- `production_report_service.py` validate (line ~621) and reverse (~721),
- `conditionnement_service.py` (~161, the frozen packaging parameters),
- `legacy_report_ledger._finished_goods_store` (~86),
- `packing_derivation_service` (the runs query, which stops joining the OF's product).

`legacy_report_ledger` writes the row's product onto the old-shaped report it materialises.

At validation, each OF of the shift whose `product_id` is null is stamped with the product of its first packing row, in one transaction with the posting. It is only ever set when null. Reversing the shift leaves it (the card lists products from the rows, so it cannot go stale).

### 1.4b Several products on one OF (decided 2026-09-21: the OF supports them)

The OF's own `product_id` stays as its "primary" product (the first one stamped) for anything that still needs exactly one. Every reader that would otherwise mix products is made product-aware:

- `packaging_variance_service.by_product` groups by the packing report's own product (`COALESCE(c.product_id, w.product_id)`), not the OF's.
- `packaging_variance_service.for_of`: with one product across the OF's validated packing reports it is unchanged. With several, tonnage (declared per OF, from the daily reports) cannot be split by product and one net weight cannot serve 200 g and 500 g packets, so it returns `multi_product: true` and a per-product breakdown computed with each product's own parameters (the `by_product` logic restricted to this OF). The OF page shows one variance panel per product.
- `of_consolidation_service` keeps `product_id` and adds `product_ids` (distinct products of the validated packing rows). Its sums are product-independent.
- `recipe-check` reads the OF's recipe and poured components, not its product: no change.
- The OF page's packet unit is the products' common unit, and none (a bare number) when they differ, the same rule consolidation already applies to mixed items.

### 1.5 Existing data

The dev DB has 117 validated, 12 submitted and 3 returned shifts. The backfill gives every existing packing row its OF's product, so nothing changes for them and the seeded month keeps validating.

## Milestone 2: OF list and OF page

### 2.1 Overview read

`GET /production/work-orders/overview` (permission `production.view_work_orders`), one row per non-regrind OF, SQL aggregates only (no per-OF consolidation):

| Field | Meaning |
|---|---|
| `of_id` | |
| `products` | distinct product ids of the OF's validated packing rows, first appearance first; falls back to `[work_orders.product_id]` for an OF that has one and no validated rows yet (Planning, seeds); `[]` otherwise |
| `produced_quantity` | tonnes, validated packing rows |
| `completion_ratio` | produced / planned; null when the OF has no planned quantity |
| `yield_ratio` | validated; null when no validated shift |
| `shifts` | counts `{validated, submitted, in_progress, returned}` of the shifts holding a run or packing row of this OF |
| `last_shift_date` | |
| `pending_quantity` | tonnes on packing rows of `open` or `submitted` shifts, never added to the validated figure |
| `live` | an `open` or `submitted` shift for the current shift window (the board's `current_shift` rule) holds a run of this OF |

`GET /production/shift-reports` gains an `of_id` filter (shifts with a run or packing row for that OF). `/work-orders/yields` stays (Analytics uses it).

### 2.2 OF list (`WorkOrdersTab.tsx`)

- Compact cards in PC | PL columns: reference, status, line, product(s), supervisor, start date; a **real** progress bar (produced / planned tonnes; with no planned quantity just the produced tonnes, no bar and no percentage); yield ("—" until a shift is validated, not 0.0%); a shift line such as "12 validated · 1 waiting · live now" with the pending tonnes muted beside the official figure, in the board's "NON VALIDÉ" style.
- A card without a product says "Product set at the first validated report" in muted text. With several products they are listed, wrapping.
- Closed and cancelled OFs fold under a "show closed" control; type and status filters stay; a search box (reference, line, product, supervisor) replaces the column filters.
- Removed: the Colonnes menu, column filters and table sort (they act on a table that is no longer rendered), the per-card details dialog and its five queries, the looping animations, the decorative shield and flow illustration.
- Edit and close dialogs mount once at tab level, not three per card. The card and the lifecycle actions move to their own files (`WorkOrderCard.tsx`, `useWorkOrderActions.ts`); the tab is 1,300 lines today.
- Every string goes through i18n (the hard-coded "Active", "Closed", "Planned", "No PC orders…", "aucune OF trouvée" today).
- Create dialog: the stale product hint is replaced by a line saying the product appears after the first validated report.

### 2.3 OF page (`WorkOrderDetailsPage.tsx`)

- "Rapports" lists the OF's **shifts** (date, shift, line, status) from `GET /shift-reports?of_id=`. A row opens the shift screen on that shift through `?tab=shift-report&line=&date=&shift=`, which `ShiftReportTab` learns to read (it has no URL parameters today). The legacy report dialogs are no longer opened from this page.
- The progress card gains the pending line ("+ 3.2 t waiting validation"). The header lists every product.
- Consolidation, quality, recipe check, packaging variance and the flow stay. The flow's stage states are derived from the old report tables by `useOfStageStates`; they keep working because validation still fills those tables, and porting them is out of scope.

## Out of scope

- Planning tab, board OF cards, Analytics OF tab.
- Retiring the old report tables (M6b of the shift program).
- Classifying packaging items (the five packing dropdowns stay empty until the client sets a packaging kind in Classifications; that is data, not code).
- Commits: the branch holds a large uncommitted body and none was requested.

## Testing

Milestone 1 (backend integration, in the style of `test_shift_wiring_integration.py`):
- a packing row saves and derives from its own product (type label, packets from cartons, store);
- OF resolution: one run OF; several run OFs disambiguated by product; `OF_AMBIGUOUS`; `PRODUCTION_FIRST`;
- submit refuses no product; draft saves without;
- validating a shift with two products posts each under its own product; reversing undoes each;
- a two-product OF: `by_product` groups by the row's product, `for_of` returns the per-product breakdown, consolidation lists both products;
- the first validation stamps a null `work_orders.product_id`, never overwrites a set one;
- the migration backfill and `convert_legacy_reports()` carry the product.
Existing suites (production, warehouse, qc, maintenance, core) stay green; `tsc -b --force` clean.

Milestone 2:
- overview: validated and pending kept apart; regrind OFs excluded; no shifts gives nulls and empty lists; several products; tenant isolation; permission;
- `of_id` filter on shift reports;
- `tsc -b --force`, then the screen driven in a real browser against the dev DB's 28 OFs: list, folded closed OFs, a multi-product card, the OF page's shift list opening the right shift.
Verification uses read-only interactions; any shift created for a check is proved mine through the audit log and deleted.
