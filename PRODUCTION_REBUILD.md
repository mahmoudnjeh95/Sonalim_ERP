# Production module rebuild — working tracker

**Temporary file.** It exists to carry the plan and its status between sessions
while `modules/production` is rebuilt around the OF. Delete it once Phase 8 lands.

Source of truth for the plan: the approved artifact
<https://claude.ai/code/artifact/5c2c9d17-a9f3-4bde-8487-cc31ae766cbb>. Reading it
through the Artifact tool returned HTTP 403 on 2026-08-28, which is why the
substance is copied here.

Last updated: 2026-09-02, after Phase 8 — all eight phases built.

---

## Status at a glance

| # | Phase | State |
|---|-------|-------|
| 01 | OF lifecycle, stripped of stock | **Done & verified** — migrated on local `erp` |
| 02 | Report header and daily report | **Done & verified** — migrated on local `erp` |
| 03 | Conditionnement report | **Done & verified** — migrated on local `erp` |
| 04 | The qc module | **Done & verified** — migrated on local `erp` |
| 05 | Validation posts stock | **Done & verified** — migrated on local `erp` |
| 06 | OF consolidation | **Done & verified** — migrated on local `erp` |
| 07 | Termination and closure | **Done & verified** — no migration needed |
| 08 | Screens and dashboard | **Done** — needs your eyes |

Gates currently passing: `276 backend tests` (108 of them integration tests against
a real database), `tsc --noEmit`, `vite build`. Production migrations 0013–0020,
warehouse 0009 and qc 0001 are applied to the local `erp` database, which also
carries a seeded demo scenario (three OFs in different states).

---

## The pivot

Stock stops following the OF and starts following the report. The OF plans work
and records that it happened; it moves nothing. Inventory is touched only by a
supervisor validating a report, or by quality pulling non-conforming product back
out of stock.

| On validation of | Out of stock | Into stock | Recorded only |
|---|---|---|---|
| Daily report | Semolina and other raw material | — | Dough, finished-product figure, waste, water, fuel, electricity, time. Rebroyat above zero opens a regrind OF. |
| Conditionnement report | Film, cartons, tape | Finished product | Product / film / carton waste, speed, downtime, DLC |
| Quality report | — | — | Indices, conformity, defects — opens the 40-day follow-up |
| Non-conformity raised | Finished product, to quarantine | — | Defect, quantity, the OF it came from |
| NC dispositioned | — | Finished product, out of quarantine | Film, carton and tape as déchet — already deducted at conditionnement |
| Draft or rejected report | — | — | Nothing official |

---

## Locked decisions

Settled with the user on 2026-08-28. Do not re-open these.

1. **Report validation is the only event that posts stock.** The OF's create,
   start and close paths post nothing.
2. **Follow the specification.** `daily_consumption` and `work_order_consumption`
   fold into the report tables and are dropped. `scrap_records` stays —
   `regrind_batch_inputs` is a foreign key into it — but becomes a derived ledger.
3. **"Machine" means the work center.** The OF's required `machine_id` is its
   existing `work_center_id`. No new column, no new entity.
4. **Recipes, packaging BOM and regrind stay in scope**, though the specification
   documents never mention them.
5. **Quality control and non-conformity live in a new `modules/qc`**, not in
   production.
6. **Clean rebuild.** Existing OF data is deleted, not migrated.
7. **Each report posts one side.** The daily report deducts raw material only.
   The conditionnement report records the finished product. The daily report's own
   finished-product figure posts nothing — it feeds yield and consolidation, so the
   same tonnage is never counted twice and no intermediate bulk product is needed.
8. **Quality also posts stock, via non-conformity.** Packaging inside a rejected
   packet was already deducted at conditionnement and must never be deducted twice.
   NC must work on a closed OF.
9. **Quarantine is not optional.** Non-conforming product moves to a blocked
   location on raise and leaves it on disposition — never a straight write-off.
   Quarantine stock is excluded from `get_available_quantity`.
10. **Semoule is always available.** A raw-material shortfall never blocks
    validation. The control is `core.products.stock_alert_threshold`, which already
    exists — no second minimum. Reservation paths keep their `INSUFFICIENT_STOCK`
    refusal.
11. **Rebroyat opens its own OF.** A daily report validating with rebroyat above
    zero writes the scrap record and opens a regrind OF in the same transaction.
    Blocked until a default regrind output product is configured.
12. **The validator may correct the figures before validating.** Gated by
    `production.admin_reports`, separate from `production.validate_reports`.
    Submitting freezes the team's figures into a revision that is never overwritten.

Two judgement calls in the plan were inferred rather than confirmed. **Both were
put to the user on 2026-09-02 and confirmed:** quality lives wholly in `qc`, and
regrind keeps its own stock path.

Four further decisions settled the same day:

13. **Quality reports live wholly in `qc`.** The specification files all three
    report types under one header, but a module may not read another's tables, so
    `qc` owns the quality report, its follow-up and non-conformity end to end,
    mirroring production's header shape. The Validation Center calls both services.
14. **The follow-up window is configurable per product**, not a hard-coded 40 days
    — a tenant-wide default with an optional per-product override, the same shape
    the plan already describes for `regrind_defaults`. 40 stays the default.
15. **The OF's work center is required.** `work_orders.work_center_id` is NOT NULL
    as of `0017`, and regrind batches name their line like any other OF. Phase 5's
    automatic regrind OF uses the validating report's work center.
16. **A shift reports once.** `production_reports` is unique on
    (tenant, OF, type, date, shift) with `NULLS NOT DISTINCT`, so a shift-less
    report cannot be duplicated either. Without it a double entry double-counts
    tonnage and rebroyat — and from Phase 5, double-posts stock.

Five further decisions, settled with the user on 2026-09-10 — outside the original
specification, requested directly:

17. **Decision 3 is superseded.** "Machine" no longer means the work center. A
    work center like `Line_1_PL` can carry more than one machine running at
    once — `maintenance.equipment` already modeled this (migration 0004, moved
    to its own module in `maintenance` 0001/0002) but nothing in production
    referenced it. `production.production_reports.equipment_id` (migration
    0033) is the new opaque, nullable reference into it.
18. **An OF may name a supervisor, but is never required to.** Unlike
    `work_center_id`, `work_orders.supervisor_id` (migration 0033) is nullable
    with no create-time enforcement — settable at creation or later via
    `admin_update_work_order`. The picker is scoped to users holding the
    `Production` role (`core.roles.code = 'production'`), via
    `WorkOrderService.list_supervisor_options`.
19. **A report must name its machine before it can leave draft.** Optional to
    save as a draft, but `submit_report` refuses with `MISSING_MACHINE` if
    `equipment_id` is unset — the same point stock-target completeness is
    enforced, and for the same reason: a report at the validation desk that
    still doesn't say which machine ran it never will.
20. **Machine productivity is a first-class aggregate**, mirroring team
    performance: `MachinePerformanceService.list_machine_performance` groups
    validated reports by `equipment_id` (produced quantity, minutes run,
    downtime) — `GET /production/reports/machine-performance`.
21. **Production never holds a live reference into `maintenance`'s schema.**
    `GET /production/machines` (optional `work_center_id` filter) is a thin
    in-process pass-through into `EquipmentService.list_equipment`, gated by
    `production.view_reports` rather than `maintenance.view_equipment` — a
    floor user filing a report must never need a Maintenance permission just
    to pick which machine they ran. `production/module.json` now lists
    `maintenance` under `optional_depends`.
22. **Machine performance got its UI**, closing the loop decision 20 only
    wired server-side: a "Machine performance" card on the Production
    dashboard (`ProductionDashboardTab.tsx`), folded across the selected date
    range the same way the team-semoule-waste table is — one row per
    `equipment_id`, most produced first, resolved to a code/name via
    `GET /production/machines`. `Line_1_PL` was given its second machine
    (`PL-02`, same "Pate long machine" activity as `PL-01`) via
    `EquipmentService.create_equipment` so the multi-machine line the plant
    described has real data to show.

---

## Status vocabularies

| Object | Values | Transitions |
|---|---|---|
| OF | `planned · ongoing · suspended · closed · cancelled` | planned → ongoing → {suspended, closed}; suspended → {ongoing, cancelled}; planned → cancelled |
| Report | `draft · submitted · validated · rejected` | draft → submitted → {validated, rejected}; rejected → draft (revision + 1) |
| Quality follow-up | `open · in_progress · completed` | open → in_progress → completed |
| Non-conformity | `raised · quarantined · dispositioned · closed` | raised → quarantined → dispositioned → closed |

---

## Phases

### 01 — OF lifecycle, stripped of stock ✅

Migration truncating existing OF data, renaming `quantity`, adding the planning and
closure columns, installing the five-value vocabulary. Service loses every stock
call; gains suspend, resume, canc<!--  -->el, close. Regrind completion moves its
receive-and-consume into `RegrindService.complete_batch()` before the OF path goes
inert. New `production.suspend_work_orders` and `production.close_work_orders`.

Shipped: `migrations/0013_production_of_lifecycle.sql` · `domain/entities.py` ·
`api/service.py` · `api/regrind_service.py` · `module.json` · minimal frontend
alignment (status vocabulary, `planned_quantity`, lifecycle buttons, regrind
completion dialog).

`RegrindService.complete_batch()` is now the only stock call in the whole module.

### 02 — Report header and daily report ✅

Migrations for `production_reports` and `daily_reports`; `daily_consumption` and
`work_order_consumption` dropped with their services and endpoints. `scrap_records`
kept and no longer exposed as the primary hand entry — validated report waste
writes it. `ProductionReportService` with create-draft, update-draft, submit,
validate, reject and revise, every transition guarded by `SELECT … FOR UPDATE`.
`of_id` mandatory and captured once. Revision snapshots: submitting freezes the
team's detail; a correction appends a new revision with its reason.

Shipped: `migrations/0014_production_report_header.sql` ·
`migrations/0015_production_daily_report.sql` · `domain/production_report.py` ·
`api/production_report_service.py` · `api/resource_type_service.py` (split out) ·
`api/router.py` · `module.json` · frontend `api.ts` client.

### 03 — Conditionnement report ✅

Migration and detail service reusing the Phase 2 header and validation machinery.
DLC becomes a real `warehouse.lots` row with `expiry_date` and `source_type`,
written through the warehouse service on validation.

Shipped: `migrations/0016_production_conditionnement_report.sql` ·
`api/conditionnement_service.py` · `domain/production_report.py`
(`ConditionnementReportDetail` + `validate_conditionnement_detail`) ·
`modules/warehouse/api/lot_service.py` (new `register_lot`) ·
`modules/warehouse/domain/lot.py` (`validate_lot_number` split out of
`validate_new_lot`) · `api/router.py` (3 endpoints) · `module.json` · frontend
`api.ts` client · 10 integration tests.

The prerequisite is done: `ProductionReportService` now dispatches on
`report_type` for detail loading, validation and the post-validation effect
(daily → scrap record, conditionnement → lot). Submit, validate, reject and
revise stayed shared — the packing report grew no parallel state machine.

`LotService.register_lot()` was added rather than reusing `receive_lot()`
deliberately: Phase 3 registers the lot's *identity and expiry*, while the
quantity that lands in it is a stock movement and therefore Phase 5's job.
`test_the_lot_carries_no_stock_yet` pins that boundary.

### 04 — The qc module ✅

`module.json` **first**, per the new-module checklist. Register `qc` in the
migration runner's module map and order, and its router in `app/main.py`. Quality
report with its own validation, and the follow-up window derived from the report
date — **configurable per product** (decision 14), so it needs a
`qc.follow_up_policies`-style table: a tenant-wide default of 40 days with an
optional per-product override. Non-conformity tickets and disposition lines, raised against an OF
whether or not it is still open. No table access into `production`: `of_id` is an
opaque column with no foreign key.

Shipped: `modules/qc/module.json` · `migrations/0001_qc_init.sql` ·
`domain/quality.py` + `domain/non_conformity.py` (26 unit tests) ·
`api/quality_service.py` (`QualityReportService`, `FollowUpService`,
`FollowUpPolicyService`) · `api/non_conformity_service.py` · `api/router.py`
(15 endpoints) · `core/migrations/runner.py` + `app/main.py` registration ·
`events/CATALOG.md` (3 events) · `frontend/src/features/qc/api.ts` ·
21 integration tests.

Tables: `qc.quality_reports`, `qc.quality_report_details`, `qc.follow_up_policies`,
`qc.quality_follow_ups`, `qc.non_conformities`, `qc.nc_dispositions`.

**New-module checklist, all six steps:** manifest written before domain code;
the three events added to `events/CATALOG.md` before the publishing code; the
`/api` surface defined before internals; contract behaviour covered by tests; no
direct table access into another module (asserted by
`test_nothing_in_qc_writes_into_productions_schema`); load order documented in the
README and `runner.py`.

**Reports per shift** (clarified by the user, 2026-09-02): every shift files three
reports — daily, conditionnement and quality — so **one OF carries many quality
reports**, one per date and shift. `quality_reports_one_per_shift` enforces one per
(OF, date, shift) with `NULLS NOT DISTINCT`, matching production's rule.

Events are published in Phase 4; production **consumes**
`qc.non_conformity.dispositioned` in Phase 5. The NC state machine
(`raised → quarantined → dispositioned → closed`) and the disposition lines are
established here so Phase 5 only has to add the stock movements —
`test_non_conformity_posts_no_stock_yet` pins that boundary.

### 05 — Validation posts stock ✅

The phase the whole rebuild was for: report validation became the only door
inventory moves through, and the OF stayed inert.

Shipped: `modules/warehouse/migrations/0009_*` (`source_type`, `source_id`,
`of_id` on `stock_moves`; `is_blocked` on `locations`) ·
`migrations/0018_production_regrind_defaults.sql` ·
`migrations/0019_production_report_stock_targets.sql` ·
`api/report_stock_service.py` · `StockService.post_production_movement`,
`would_go_negative`, `transfer_to_quarantine`, `release_from_quarantine` ·
`RegrindDefaultsService` · `modules/production/events/consumers.py` ·
router + frontend clients · 25 new tests.

**What each validation moves.** Daily: raw material out, and nothing else — its
finished-product figure stays a recorded number, because the conditionnement
report owns that tonnage and counting both would double the same pasta.
Conditionnement: finished product in, film / carton / tape out. Quality: nothing.
NC raise: finished product into a blocked quarantine location. NC disposition:
out of quarantine, with component waste recorded and never deducted twice.

**Products and locations are named on each report** (user decision, 2026-09-02),
not inferred from the OF's recipe and BOM — so a shift that substitutes a
material records what it actually used. `daily_reports` gained
`semolina_product_id` and `raw_material_location_id`; `conditionnement_reports`
gained the three packaging product ids plus packaging and finished-goods
locations. The finished product is deliberately **not** restated: it is the OF's
product, so a report cannot contradict the order it belongs to. Completeness is
required at submit, not at draft, so a team can still save a half-finished shift.

**A shortfall posts anyway, but must be explained** (user decision). Validation
checks for a negative outcome before writing anything and refuses with
`SHORTFALL_COMMENT_REQUIRED` until the validator accounts for it; then the
movement posts and the balance may go negative.
`StockService.post_production_movement` is the only method that permits this —
every reservation path keeps its `INSUFFICIENT_STOCK` refusal, because those are
promises about the future rather than records of the past.

**Rebroyat opens its own OF**, using `regrind_defaults`. Missing configuration
**blocks** validation rather than silently skipping the OF, which would lose the
rebroyat entirely.

**Quarantine happens at raise, not as a second step.** Phase 4 had
`raise` → `quarantine` as two calls, which left a window where product was
rejected on paper but still sellable. `raise_non_conformity` now requires the
blocked location and transfers the stock in the same transaction; the standalone
endpoint is gone. `transfer_to_quarantine` refuses a destination that is not
actually blocked, and `get_available_quantity` returns 0 for blocked locations —
so no other module can promise quarantined product, though it stays on the books
at value because it is awaiting a decision, not written off.

**The cross-module loop closed.** qc publishes
`qc.non_conformity.dispositioned`; production consumes it and writes the rebroyat
scrap record, idempotent on `event_id` via `events.processed_events`. qc never
writes into production's schema. Only regrind lines become scrap — déchet is
reported by component, never re-deducted.

`production.work_order.completed` was renamed to `production.work_order.closed`
(the parked item), and `production.report.validated`,
`production.report.rejected` and `warehouse.stock.issued` were added to the
catalog before their publishing code.

### 06 — OF consolidation ✅

Shipped: `api/of_consolidation_service.py` · rewritten
`api/work_order_yield_service.py` ·
`migrations/0020_production_drop_stored_output.sql` ·
`QualityReportService.get_conformity_summary` ·
`GET /production/work-orders/{id}/consolidation` · frontend client and details
dialog · 16 integration tests.

**Nothing is stored.** `work_orders.actual_output_quantity` is dropped: it was a
cached answer to "how much did this OF produce?", and a cached total can disagree
with the reports it came from. Everything — finished product, raw material,
utilities, packaging, waste by category, production and downtime minutes — is
summed live from **validated** reports only. Drafts and rejected reports are
excluded, which matters more now than before: from Phase 5 a validated report is
also what moved stock.

**The daily report's finished-product figure is still not added to
`produced_quantity`** (locked decision 7). Only the conditionnement reports count
that tonnage. `test_the_daily_finished_product_figure_is_not_added_to_produced`
pins it.

**Regrind keeps its actual output**, moved from `work_orders` onto
`regrind_batches` — a rebroyat batch has no report behind it, so the figure is a
fact about the batch rather than a cached total on an OF.

**Yield recomputes off the reports**: (finished product + rebroyat) / semoule,
every term from validated reports. It is now available **before closure** — a
yield that only appears once an OF is closed tells the plant nothing while it can
still act.

**Quality crosses the module boundary through a service call.** Production calls
`QualityReportService.get_conformity_summary`, never a join into qc's schema;
`production/module.json` declares `qc` in `optional_depends` accordingly.
`conformity_rate` is `None` rather than 100% when nothing was inspected — "no
data" and "everything passed" are different answers.

### 07 — Termination and closure ✅

Shipped: `WorkOrderService.pre_close_check` · closure guard and `force` override
in `close_work_order` · `FollowUpService.count_open_for_of` and
`NonConformityService.count_open_for_of` ·
`GET /production/work-orders/{id}/pre-close-check` · frontend client ·
14 integration tests. No migration — closure was already archival from Phase 1.

**Blockers versus warnings, and why the line falls there.** Blockers are
unfinished *production* work: reports still in draft, still waiting at the
validation desk, or rejected and never revised. Closing over a submitted report
would strand figures that never posted stock. Warnings are everything else, and
**quality never blocks**: the follow-up window deliberately outlives production,
so holding an order open until it expires would keep every OF open for weeks and
make the closed state meaningless. An open non-conformity is the same — it is
usually found after the run is over.

Warnings also cover an OF with no validated reports (odd, not unfinished) and a
missing start date.

**`force` exists so an order cannot be held open forever** by a draft nobody will
finish. It requires a reason, and that reason is audited as
`work_order.closed_over_blockers` alongside the blockers it overrode.

**Closure still changes nothing but `closed_at` and `closed_by`.** Reports,
validations, posted stock movements and quality history all stay readable, and
`test_a_closed_of_still_accepts_quality_work` pins the failure mode the whole
design guards against.

### 08 — Screens and dashboard ✅

Shipped: `DailyReportsTab` · `ConditionnementTab` · `ValidationCenterTab` ·
`ProductionDashboardTab` · `WorkOrderDetailsPage` (a real route,
`/production/work-orders/:id`) · `qc/QualityPage` with `QualityReportsTab` and
`NonConformitiesTab` · sidebar and router entries · ~200 i18n keys in both
languages · `StatusBadge` extended with the rebuild's five vocabularies.

Every list view ships with the platform conventions from day one: `ColumnDef`
arrays through `useTableColumns` (resize + per-user visibility, actions column
`alwaysVisible`), `FilterTabs` for status plus `ColumnFilterRow` for the rest,
TanStack Query for every read and write with cross-feature invalidation, and en
+ fr keys added in the same edit.

**The Validation Center is one queue over two services** — production owns the
daily and conditionnement reports, qc owns the quality report, and the screen
calls both rather than either module reaching into the other. Its shortfall field
is the interesting part: a `SHORTFALL_COMMENT_REQUIRED` refusal is surfaced as a
prompt rather than an error, because the movement *is* allowed — it just needs an
explanation first.

**A gap Phase 5 left was found and closed here.** `warehouse.locations.is_blocked`
existed but nothing could set it, so quarantine — and therefore the whole
non-conformity flow — was unusable from the UI. `LocationService` create/update
and both endpoints now carry `is_blocked` and `blocked_reason`, and the NC form
offers only blocked locations.

**Demo data** was seeded through the live API (`scratchpad/seed_v2.py`): OF-000001
fully validated with two shifts, OF-000002 with three reports at the validation
desk, OF-000003 holding an unfinished draft, plus NC-000001 in quarantine. It
proved the chain end to end — 1065/1200 produced, yield 0.949, conformity 98.5%,
two rebroyat OFs opened automatically, and a pre-close check that permits closure
while warning about open quality work.

---

## Verification — 2026-09-01

The environment runs **native PostgreSQL 18 on localhost:5432** (`erp:erp@localhost/erp`),
not the Compose stack — Docker is not on PATH. The `erp` role cannot create
databases, so a copy could not be taken; verification was done by running
everything inside one transaction and rolling back, which Postgres allows for DDL.

**71 of 71 checks passed** against the real old-shaped schema and data. Covered:
the three migrations; the `status` CHECK rejecting `in_progress`; the whole OF
lifecycle posting zero stock moves; submit freezing revision 1; a correction
appending revision 2 without overwriting revision 1; validation using the
corrected figure for the scrap record; a second `validate` being refused;
reject → revise → resubmit keeping the rejected original; regrind being the one
path that still posts stock; and closure deleting nothing while refusing new
reports.

**Migrations 0013–0015 are now applied to the local `erp` database** (user
approved, 2026-09-01). 9 work orders, 11 poured inputs, 8 scrap records and 2
regrind batches were deleted per locked decision 6; `daily_consumption` and
`work_order_consumption` were dropped. Recipes, BOMs, work centers, machines,
classifications and all 93 stock moves are untouched. The six new permissions were
granted to `demo@sonalim-erp.local`. Both servers start and the new endpoints
answer over HTTP.

### Still unverified

1. **The finished-goods tables in `warehouse/FinishedGoodsAnalysisTab.tsx` were
   reconstructed, not restored.** Removing the consumption card over-cut the file
   and took `dailyColumns` / `byProductColumns` with it; they were recovered from
   the pre-edit production bundle, which later builds have since overwritten — so
   they can no longer be diffed against the original. Needs a visual check in the
   running app: Warehouse → Finished Goods Analysis, both tables.
**Now covered by `pytest`.** The throwaway verification script was replaced by
`conftest.py`'s `db` fixture (transaction per test, always rolled back, skips when
no migrated database is reachable) plus
`modules/production/api/test_report_flow_integration.py` (17) and
`test_conditionnement_flow_integration.py` (10). They build their own reference
rows under `integration-test*` tenants, so they pass against any migrated
database, seeded or empty. Suite is now **179 tests**.

The assertions that matter for later phases: the OF lifecycle posts zero stock
moves, validation posts zero stock moves *for now*, a second `validate` is refused
and writes no second scrap record, and a correction never overwrites revision 1.
**Phase 5 will deliberately break `test_validation_posts_no_stock_yet`** — that is
the signal to update it, not a regression.

---

## Open questions and deliberate gaps


- **`cancel` reuses `production.close_work_orders`** rather than adding a third
  permission.
- **`production.work_order.completed` kept its name** but now fires on closure with
  a `planned_quantity` payload. Nothing consumes it. Phase 5 should rename it to
  `production.work_order.closed`.
- **`VALID_SCRAP_TYPES` gained `"daily_report"`.** The NC sources join it in Phase 4/5.
- **New reports are refused on `closed` / `cancelled` OFs**, allowed on planned,
  ongoing and suspended. Not specified by the plan.
- **`production.resource_types` was kept but is API-only.** The plan left its fate to
  the Phase 8 dashboard. Its only UI went with `daily_consumption`, so **recording
  water / fuel / electricity has no UI until Phase 8.**
- **Yield reads blank for normal OFs until Phase 6** — it still reads
  `actual_output_quantity`, which only regrind writes now.

- **37 stock moves reference OFs that no longer exist.** They were posted by the old
  OF lifecycle and survived the rebuild, so balances stay correct but their
  free-text `work_order:{id}` references are dangling. The user chose (2026-09-01)
  to **settle this at Phase 5**, when `stock_moves` gains real `source_type`,
  `source_id` and `of_id` columns and the old references have to be handled anyway.

---

## Standing requirements every phase carries

- `record_audit()` in the same transaction as each mutation.
- An `admin_*` permission for edit-in-place.
- English and French i18n keys added together — `fr` is typed as
  `Record<TranslationKey, string>`, so an English-only key fails `tsc`.
- TanStack Query for all reads and writes.
- The shared column filter, resize and visibility primitives on every table.
- No cross-module table access; events for cross-module side effects; consumers
  idempotent on `event_id`.
