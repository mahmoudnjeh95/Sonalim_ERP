# Versement MP replaces Dough / Semoule as the source of "MP versée"

## Problem

The Board's "MP versée" KPI (labeled "Semoule versée" in the UI) and every
downstream yield/consumption/analytics figure are currently built from two
per-run raw-material inputs on `shift_runs`:

- `shift_run_semolina_lines` — a list of (product, quantity, store) lines
  attached to one run ("Semoule").
- `regrind_input_quantity` / `regrind_input_product_id` — a single rebroyat
  figure per run.
- `dough_quantity` ("Dough (t)") — a manual, unvalidated number on the run
  that feeds no stock and only display/consolidation.

The client wants raw material poured recorded as a proper list of
versements per shift instead: several MP products (e.g. semoule blé dur +
a small quantity of semoule extra fine) plus rebroyat, and "MP versée"
becomes the sum of all versement rows + all rebroyat versement rows.

Two tables for this already exist as unused migrations
(`0059_production_shift_versements.sql`, `0060_production_shift_rebroyat_versements.sql`)
and the shift-form UI and `shift_sections.py` wiring for them is already
built (`sectionConfig.ts` "Versement"/"Rebroyat" blocks, `_VERSEMENTS` /
`_REBROYAT_VERSEMENTS` RowSets, `_derive_versement_locations`). They are
shift-scoped (one `shift_report_id`, no `run_id`), not run-scoped, and
today they are pure UI: no service reads them, nothing posts stock from
them, and no analytics query joins them.

## Goal

Versement + rebroyat versement become the **only** source of raw material
poured into a shift. `shift_run_semolina_lines`, `dough_quantity`, and the
per-run `regrind_input_quantity` / `regrind_input_product_id` fields are
retired. Every place that reads the old fields is repointed at the new
tables, with the same behavior it has today wherever a per-run figure is
needed from shift-level data.

## Attribution: shift-level data, run/OF-level consumers

Versement rows are recorded once per shift, not per run. Two kinds of
consumer exist downstream and get different treatment:

1. **Shift/period-level aggregates** (they already read shift-level data
   today and never needed per-run attribution): read `shift_versements` /
   `shift_rebroyat_versements` directly, summed by product. No split.
   - `mp_consumption_service.py` (costed MP consumption — rebroyat stays
     excluded, same as today, since it has no landed cost)
   - `of_consolidation_service.py`'s `semolina_by_product` breakdown can
     read shift-level too where it currently reads per-report lines, since
     an OF's daily reports already all point back to one materialized
     shift's rows

2. **Run/OF/equipment-level consumers** (they need a number per run
   today): the shift's total versement tonnage and total rebroyat tonnage
   are each split across the shift's runs proportionally by
   `production_minutes`, using the existing `split_proportionally` helper
   in `domain/shift_report.py` (same technique already used there for
   `shift_energy` columns). A run with zero minutes and all other runs
   also at zero takes the whole amount (existing helper behavior,
   unchanged).
   - `legacy_report_ledger.materialize_shift` (writes the per-run legacy
     rows that stock posting and `of_consolidation_service` read)
   - `machine_performance_service.py`
   - `work_order_yield_service.py`
   - `recipe_check_service.py`'s `_poured_mix`

Splitting is done **per product**: if a shift poured 8t semoule blé dur +
1t semoule extra fine + 0.5t rebroyat across two runs, each run gets its
own share of each of the three quantities, keeping the per-product
breakdown intact rather than collapsing to one number first and splitting
that.

## Legacy bridge (`legacy_report_ledger.py`)

`materialize_shift` currently copies `shift_run_semolina_lines` verbatim
into `report_semolina_lines` (one row per line, same run/product/quantity/
store) and copies `dough_quantity` / `regrind_input_quantity` /
`regrind_input_product_id` straight into `daily_reports`.

New behavior:

- Load `shift_versements` and `shift_rebroyat_versements` for the shift
  once (not per run).
- For each product in `shift_versements`, split its quantity across the
  shift's runs by `production_minutes` (same weights already computed for
  energy) and write one `report_semolina_lines` row per (run, product)
  with a nonzero share, using the versement's derived `location_id`. This
  preserves `report_semolina_lines`' existing shape (multi-product, per
  report/run, with its own store) so every downstream reader of that table
  — stock posting, `mp_consumption_service` equivalents keyed off it,
  dashboard queries — keeps working unchanged.
- For `shift_rebroyat_versements`, sum to one total tonnage and one
  product per shift (same simplifying assumption `regrind_input_product_id`
  already made — "only ever one rebroyat product tenant-wide", per the
  domain comment in `production_report.py`), split by production_minutes,
  and write it into each run's `daily_reports.regrind_input_quantity` /
  `regrind_input_product_id` exactly as today. If a shift's rebroyat
  versements name more than one product, that's a validation error at
  save time (see Validation below) — the assumption is enforced before it
  ever reaches the bridge.
- Stop reading `shift_runs.dough_quantity` for `daily_reports.dough_quantity`.
  `dough_quantity` becomes computed, not stored: it is deleted from
  `shift_runs`, `daily_reports` keeps its column (other code reads it) but
  its value becomes each run's own split share of the shift's total
  versement + rebroyat tonnage — i.e. "Dough (t)" is no longer typed by
  hand, it *is* the sum the client asked for, attributed per run the same
  way as everything else.

## Stock posting (`report_stock_service.py`)

`_daily_lines` currently reads `detail.semolina_lines` (each with its own
store) plus one `(regrind_input_quantity, regrind_input_product_id,
raw_material_location_id)` tuple. Because `report_semolina_lines` keeps
its shape (see above), `_daily_lines` needs **no change**: it already
reads whatever is in `detail.semolina_lines`, which is now populated from
versements instead of the old semolina lines table. The rebroyat tuple
also needs no change, since `regrind_input_quantity` /
`regrind_input_product_id` / `raw_material_location_id` on `daily_reports`
keep being populated, just from the rebroyat versement split instead of a
manually typed run field.

Net effect: stock posting is unaffected at the `report_stock_service`
layer. All the real change is upstream, in what `materialize_shift` writes
into `report_semolina_lines` and `daily_reports` before stock posting ever
runs.

## Validation (`shift_sections.py` / `domain/production_report.py`)

- A versement row requires `product_id` and `quantity > 0` (already
  enforced — `product_id` is `required=True` in `sectionConfig.ts`).
- New rule: all rows in a shift's `shift_rebroyat_versements` must name the
  same `product_id` (enforced in `_validate_part` for that table) — this
  is what lets the bridge collapse rebroyat to one product per shift, same
  as the assumption `regrind_input_product_id` already relied on.
- `check_ready_to_submit` for the `runs` section gains a check mirroring
  today's semolina-lines check: a versement or rebroyat versement with a
  quantity but no resolvable store (i.e. the named product has no default
  location) blocks submission with `MISSING_STOCK_TARGET`, same code
  already used by `validate_daily_stock_targets`.
- A shift with runs but no versement rows at all is allowed to submit
  (matches today: a report can be saved with no semoule poured, e.g. a
  shift that only ran packing).

## Frontend (`sectionConfig.ts`, i18n)

- Remove the `dough_quantity` column ("Dough (t)" / "Pâte (t)") from the
  `runs` row columns.
- Remove the `semolina_lines` child block from the `runs` row (the
  Versement/Rebroyat blocks above the runs list already replace it).
- Remove `regrind_input_product_id` / `raw_material_location_id` /
  `regrind_input_quantity` columns from the run row — rebroyat is now
  entered once per shift in the Rebroyat versement block, not per run.
  (`regrind_quantity`, the *output* of regrind made by this run, is
  untouched — that is a different figure, regrind produced vs. rebroyat
  consumed.)
- Board and Analytics labels ("Semoule versée", "MP versée", "Matière
  versée") keep their existing i18n keys and wording — only what feeds
  them changes.

## Migration of existing data

This repo's migrations never edit an applied file, and per `CLAUDE.md` no
production DB dump/backup is available to reason about here. Since
`shift_run_semolina_lines`, `dough_quantity`, and
`regrind_input_quantity`/`regrind_input_product_id` on `shift_runs` are
being retired, add one more numbered migration
(`0061_production_shift_versement_backfill_and_drop.sql`) that:

1. Backfills `shift_versements` from existing `shift_run_semolina_lines`
   (one versement row per shift per product, summed across that shift's
   runs) and `shift_rebroyat_versements` from existing
   `shift_runs.regrind_input_quantity`/`regrind_input_product_id` (summed
   per shift, only where a product is named), for shifts that have none
   yet.
2. Drops `shift_run_semolina_lines`, and drops `dough_quantity`,
   `regrind_input_quantity`, `regrind_input_product_id` from `shift_runs`.

This runs after the implementation lands and is verified end-to-end, not
before — see the plan for sequencing.

## Testing

- Existing integration tests referencing `shift_run_semolina_lines`,
  `dough_quantity`, or per-run `regrind_input_quantity` on `shift_runs`
  (`test_shift_legacy_conversion_integration.py`,
  `test_shift_stock_service_integration.py`,
  `test_shift_schema_integration.py`, others found in the grep) are
  rewritten to seed `shift_versements` / `shift_rebroyat_versements`
  instead and assert the same downstream figures.
- New tests: `materialize_shift` splits a multi-product versement across
  two runs by production_minutes and preserves per-product stores;
  rebroyat with mixed products is rejected at save; a versement product
  with no default location blocks submission.
