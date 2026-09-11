# Recipe statistics — future work, not yet built

Requested by the user 2026-09-04, alongside three smaller `DailyReportsTab`
fixes (mold reference on its own line, two new déchet stages, a tooltip on
"Pâte"). This file is the "we'll review it later" perspective the user asked
for — nothing here is implemented beyond the data capture described below.

**Update 2026-09-10:** a first shift-level correlation view now exists —
`WorkOrderYieldService.list_recipe_correlation` and the "Water dosage and flow
rate against yield" card on the production dashboard (`ProductionDashboardTab
.tsx`). It answers question 3 below the coarse way (shift inputs against the
OF's own yield, reusing `_to_result`) and question 4 (a table replaces the old
2-3-point scatter below `RECIPE_CORRELATION_SCATTER_MIN_ROWS` = 20 rows; the
scatter only renders above that). It also flags a shift whose `water_percentage`
drifted outside its OF's recipe's own water line (`water_target_min/max`,
joined from `production.recipe_lines` + `product_classifications.is_water`).
Questions 1, 2 and "best recipe" ranking are still open and still deliberately
unbuilt — this is a readability/sample-size fix and a per-shift compliance
flag, not the cross-recipe analytics feature this file describes.

## The goal

The plant wants to eventually correlate a shift's inputs against its outcome
— yield, conformity, waste — to find which combination of settings (which
recette, which water dosage, which line speed) performs best for a given
product or mold. That is a statistics/analytics feature: it reads history
across many validated reports and ranks or charts it. It does not exist yet.

## What changed now, to make it possible later

Two figures the plant already tracks on paper are now captured on the daily
report (`modules/production/migrations/0028_production_daily_report_flow_data.sql`):

- **`water_percentage`** — water dosed as a percentage of the semoule poured.
  This is how the mixer is actually set, so it is now the operator's real
  input; the existing `water_quantity` (litres) is derived from it
  automatically in the form rather than typed twice, and stays the figure
  consolidation and the cockpit already read.
- **`semolina_flow_rate`** — débit de semoule, in tonnes/hour. Recorded only;
  nothing reads it yet.

Both are plain columns on `production.daily_reports`, validated the same way
as every other daily quantity (`>= 0`, and `water_percentage <= 100`). No
aggregation, no dashboard, no export exists for them yet — they just ride
along with the rest of the shift's figures through create/update/correct/
validate and the report detail views, same as `dough_quantity` always has.

## What the later feature would actually need

Not decided, and deliberately not guessed at here — these are the questions
to work through with the user when this gets picked up:

1. **What counts as "best."** Highest yield, best conformity rate, lowest
   waste, lowest cost, or some weighted mix? These can disagree — a recipe
   with excellent yield and mediocre conformity is not unambiguously better
   than the reverse.
2. **Grouped by what.** Per product, per mold, per product+mold pair, per
   work center? The daily report already names the mold (`mold_id`) and the
   OF names the product, so the grouping key exists — the analysis over it
   does not.
3. **Where the correlation reads from.** Yield and conformity already live in
   `of_consolidation_service.py` and `QualityReportService.get_conformity_summary`
   at the OF level, not the shift level. A water%/débit correlation is a
   shift-level question, so either the comparison happens at OF granularity
   (coarser, but reuses what exists) or a new per-shift yield/conformity join
   is built (finer, but new work, and quality findings arrive well after the
   shift per the existing follow-up window design).
4. **Sample size and confidence.** A plant runs a limited number of shifts;
   the feature needs to say when it has too little data to recommend
   anything, not just rank whatever exists.
5. **Where it lives.** A new read-only view/dashboard is the obvious shape
   (matching the existing cockpit and OF consolidation pattern), but whether
   it is its own module surface or a tab on the existing production dashboard
   is unsettled.

## Explicitly out of scope for now

- No aggregation of `water_percentage` or `semolina_flow_rate` at the OF
  level (`of_consolidation_service.py` / `WorkOrderDetailsPage.tsx` are
  untouched) — averaging a percentage or a rate across several shifts is a
  different kind of arithmetic than the sums the consolidation already does,
  and doing it without a defined purpose would just be a number nobody asked
  for.
- No "best recipe" ranking, export, or dashboard.
- No change to `recipe_check_service.py` (the existing hard/soft recipe-limit
  warnings) — that already compares an OF's actual mix against its recipe's
  percentages; this is a different question (which recipe performs best over
  time), not an extension of it.

Delete or rewrite this file once the feature is actually scoped with the
user — like `PRODUCTION_REBUILD.md`, it exists to carry the idea between
sessions, not as permanent documentation.
