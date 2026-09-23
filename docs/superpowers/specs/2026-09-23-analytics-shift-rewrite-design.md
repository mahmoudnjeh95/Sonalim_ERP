# Analytics module rewrite onto shift-report data + validator-edit prerequisite

Date: 2026-09-23. Builds on [[project-shift-report-program]], [[project-shift-form-rework]], [[project-analytics-data-constraints]], [[feedback_no_invented_thresholds]], and the 2026-09-22 lifecycle design (`2026-09-22-shift-report-lifecycle-design.md`).

## Why

Daily/Conditionnement reports are gone from the UI; the shift report (`shift_reports` + its section tables) is now the only way production data enters the system. Most of Analytics already reads through this correctly, because `legacy_report_ledger.materialize_shift` back-fills the old report tables `TeamPerformanceService`/`MachinePerformanceService` query. But several kinds of data exist **only** in the shift model and have no old-report equivalent, so Analytics has never surfaced them: structured stop classification (`machine_stops.downtime_type/classification/source`), per-shift energy (`shift_energy`), and the shift's own submit/validate lifecycle. This rewrite audits the existing tabs against the new model, adds tabs for what shift data now makes possible, and regroups the cost-related tabs that already exist into their own visual group.

One new panel (validator-edit rate) depends on a feature — validator in-place editing — that was only ever spec'd (2026-09-22 design, section 3), never built. Building that panel honestly requires building the feature first; the decision made here is to build it in full rather than fake a data source, per [[feedback_no_invented_thresholds]].

## Program order

1. **Part A — Validator-edit feature** (prerequisite): implements 2026-09-22 spec section 3 in full — migration, service method, endpoint, revision tagging, `CHANGED_SINCE_OPENED` exemption, Validation Center UI.
2. **Part B — Analytics rewrite**: tab regrouping, audit of the 4 existing production tabs against shift data, 3 new tabs (Downtime, Energy, Shift Health), humidity/DLC additions folded into Yield & Waste.

Part B's Shift Health tab depends on Part A only for its 5th panel (validator-edit rate); the other 4 panels and everything else in Part B do not depend on Part A and could ship independently if needed.

## Part A — Validator-edit feature

Implements `2026-09-22-shift-report-lifecycle-design.md` §3 exactly, scoped to that section only (no autosave/localStorage §1, no delete §2, no day view §4 — those are separate, already-shipped-or-separate concerns per the lifecycle memory).

### A.1 Schema
New migration `0058_production_shift_validator_edit.sql`: `ALTER TABLE production.shift_section_revisions ADD COLUMN edited_by_validator BOOLEAN NOT NULL DEFAULT FALSE`.

### A.2 Backend
`shift_validation_service.py` gains `edit_section_as_validator(*, tenant_id, actor_id, shift_report_id, section_key, payload, reason)`:
- requires `production.shift.validate`;
- shift status must be `submitted` (else `INVALID_TRANSITION`);
- `reason` mandatory, empty/whitespace → `REASON_REQUIRED`;
- writes rows via the same `save_section_rows` helper `shift_report_service.save_section` uses;
- calls `_freeze_revision(..., reason)` then marks that revision's row `edited_by_validator = TRUE` (single UPDATE by id after insert, or pass the flag into `_freeze_revision` — implementer's call, both correct);
- does **not** change section or shift status (stays `submitted`);
- `record_audit("shift_report.section_edited_by_validator", ...)`.

New endpoint `PUT /production/shift-reports/{id}/sections/{key}/validator-edit`, same auth/error pattern as the team's `PUT .../sections/{key}`, kept as a separate route (not a shared handler) so gating/required-reason don't have to share one signature, per the spec.

### A.3 CHANGED_SINCE_OPENED exemption
No backend change to `validate_shift`'s guard. Frontend: after a successful validator-edit call, the review dialog refetches the shift and updates its `seen_revisions` baseline before the next Approve call — same pattern already used after a reject.

### A.4 Frontend
`ShiftValidationPanel.tsx`'s review dialog: sections become editable in place (reusing `SectionCard`) when the reviewing user holds `production.shift.validate`, even though shift status is `submitted`. Saving from this path calls the new validator-edit endpoint, not the team's save endpoint, and always prompts for a reason first (reuse the existing reject-reason dialog's input pattern). Revision-history panel shows an "Modifié par le validateur — `<reason>`" badge next to the normal revision entry when `edited_by_validator` is true.

### A.5 Testing
Backend integration test (real DB, existing pattern): permission gate, status gate (`submitted` only), `REASON_REQUIRED`, revision tagged correctly, section/shift status unchanged, and a case proving the validator's own edit does not trip `CHANGED_SINCE_OPENED` on their own subsequent approve while a genuine concurrent team edit still does (mirrors the lifecycle spec's own test list). Frontend: `tsc -b --force`, then a real-browser pass — edit a section from the Validation Center with a reason, approve, confirm the badge appears in revision history.

## Part B — Analytics rewrite

### B.1 Tab structure
`AnalyticsPage.tsx`'s `TABS` array gets a `group` field (`"production" | "cost"`) rendered as a labelled grouping in the tab list (visual grouping only — still one `Tabs` bar, still one `?tab=` param, no routing change):

- **Production**: Overview, Yield & Waste, Team Performance, Machine Performance, Downtime (new), Energy (new), Shift Health (new)
- **Cost & Pricing**: Production Recap, Consumption Report, Price History (all three unchanged, just regrouped)

### B.2 Audit of existing tabs — kept, not rebuilt
`AnalyticsOverviewSection`, `YieldWasteTab`, `TeamPerformanceTab`, `MachinePerformanceTab` already read validated shift data correctly (`TeamPerformanceService`/`MachinePerformanceService` query through `legacy_report_ledger`'s materialized rows, and `MachinePerformanceService` already reads `machine_stops` directly for shift-era downtime). Work here is verification, not rewrite:
- Re-drive each tab in a real browser against the seeded shift month (`backend/scripts/seed_shift_month.py` data, 2026-08-20..2026-09-20) and confirm figures are sane (yield, downtime, waste) post-migration.
- Confirm the known gap — stops with no `equipment_id` are not attributed to any machine (189 min in dev per memory) — is visible somewhere (it currently is not, in `MachinePerformanceTab`). Add an explicit "unattributed downtime" line to that tab (small addition, not a rebuild) rather than leaving it silently excluded from every machine's total.

### B.3 New tab — Downtime (stop classification)
New backend `backend/modules/production/api/stops_analytics_service.py`, `StopsAnalyticsService.list_stops(*, tenant_id, date_from, date_to)`: reads `production.machine_stops` joined to `shift_reports` (for `team`, `report_date`, `work_center_id`) for `status = 'validated'` shifts, `ended_at IS NOT NULL`. Returns per-stop rows: `equipment_id`, `line` (work_center_id), `team`, `started_at`, `ended_at`, `minutes`, `downtime_type`, `classification`, `motif`, `source`.

New endpoint `GET /production/analytics/stops?date_from=&date_to=`, permission `production.view_reports` (matching every existing analytics endpoint).

Frontend `DowntimeAnalyticsTab.tsx` + `useStopsAnalytics.ts`:
1. Pareto by `classification` (bar chart, minutes lost, whatever values exist — no fixed enum). Click a bar filters the motif pareto below to that classification.
2. Pareto by `motif` (existing pattern, re-pointed at this endpoint).
3. Capture-quality stat row: % of stop-minutes by `source` (live / added_after / manual / migrated) — real recorded field, stated as fact, no "good/bad" framing.
4. Unattributed downtime: count + minutes where `equipment_id IS NULL`, shown as its own explicit stat, never folded into a total.
5. Existing `MachineDowntimePanel` re-pointed at this endpoint so it also gets `classification`, not just `motif` text.

### B.4 New tab — Energy
New `EnergyAnalyticsService.list_energy(*, tenant_id, date_from, date_to, work_center_id=None)` reading `production.shift_energy` joined to `shift_reports` for `status = 'validated'`, returning per-shift rows: `report_date`, `work_center_id`, `team`, `fuel_quantity`, `gasoil_quantity`, `gasoil_flow_rate`, `generator_hours`, `electricity_quantity`.

New endpoint `GET /production/analytics/energy`, same permission.

Frontend `EnergyAnalyticsTab.tsx` + `useEnergyAnalytics.ts`. Physical units only (F CFA costing explicitly excluded per decision):
1. Consumption trend — fuel / gasoil / electricity as separate series (never merged, per [[project-analytics-data-constraints]]'s fuel-vs-gasoil rule) over the selected window.
2. Energy per tonne produced — each of fuel/gasoil/electricity divided by tonnes produced in the same window (joined from the shift's own runs, same window/line), trended, compared to the previous equal period by direction only (reuses `compareQuantity` from `metrics.ts`).
3. By-line comparison — bar chart of energy-per-tonne across work centers.
4. Generator usage — `generator_hours` as its own stat + trend (grid-outage proxy, no cost attached).

### B.5 New tab — Shift Health
New `ShiftHealthService.get_shift_health(*, tenant_id, date_from, date_to)` reading `shift_reports` + `shift_report_sections` + `shift_section_revisions`, all real recorded fields, no invented judgement:
1. **Submission funnel** — count of shifts by current `status` in the window, stacked over time.
2. **Time-to-validate** — median/average `validated_at - submitted_at` for validated shifts in the window (minutes/hours, stated as fact).
3. **Return rate by section** — per `section_key`, % of that section's revisions across shifts in the window that carry a `return_reason` (i.e. were sent back at least once) — surfaces which fiche teams get wrong most.
4. **Validator-edit rate** — per section, % of submitted sections with at least one revision where `edited_by_validator = TRUE` (Part A's column). Depends on Part A shipping first; until then this panel is omitted, not faked.
5. **Section completeness** — for shifts opened in the window, average count of sections with `status != 'empty'` out of the 9 defined section keys.

New endpoint `GET /production/analytics/shift-health`, same permission. Frontend `ShiftHealthTab.tsx` + `useShiftHealth.ts`.

### B.6 Humidity & lot/DLC — folded into existing tabs, not a new tab
- `YieldWasteTab.tsx` gains a humidity trend panel: average `shift_runs.humidity_percentage` per line/period, from validated shifts only, trended like everything else on that tab. Skips runs with a null humidity (not everyone records it yet) rather than treating null as 0.
- A small "packing rows with a lot but no DLC yet" coverage stat added to `DataCoveragePanel`, linking to QC's existing `LotDlcTab` queue (`/quality?tab=lot-dlc`) rather than duplicating that queue's logic in Analytics.

### B.7 What is explicitly out of scope
- No cost/pricing rebuild — `ProductionRecapExportTab`, `ConsumptionReportTab`, `PriceHistoryTab` are regrouped only, not touched.
- No sales sell-price trend (explicitly declined).
- No new hard-coded thresholds, targets, or "healthy/unhealthy" bands anywhere in B — every new panel either states a recorded figure or compares direction-only against the previous equal period, per [[feedback_no_invented_thresholds]].
- `team_rotation` (migration 0057) is not used by this rewrite unless investigation during implementation shows it's directly relevant (unconfirmed at spec time).

## Testing (Part B)

- Backend integration tests (real DB, existing pattern) for each new service: `StopsAnalyticsService`, `EnergyAnalyticsService`, `ShiftHealthService` — tenant isolation, validated-only filtering, date-range filtering, empty-window behavior.
- Full backend suites stay green.
- Frontend: `tsc -b --force`, then a real-browser pass against the seeded shift month for every new/changed tab — Downtime (classification pareto + drill, capture-quality stat, unattributed line), Energy (trend, per-tonne, by-line, generator), Shift Health (funnel, latency, return rate, completeness, and validator-edit rate once Part A ships), Yield & Waste's new humidity panel, and the regrouped tab bar.

## Risks

- `shift_energy`'s per-run energy split ("derived at read time," per its migration's own comment) is not yet implemented anywhere — Energy tab B.4 works at the shift grain only (not per-run/per-product), which is consistent with what's actually stored; per-product energy attribution is out of scope here.
- Return rate (B.5.3) reads `return_reason` off revisions; confirm during implementation that a returned section's history actually carries the reason on the revision row it produced, not only on the live `shift_report_sections.return_reason` column that gets overwritten on the next save — get this precisely right against the schema, not assumed.
- Time-to-validate (B.5.2) is meaningless for the 20 test files' worth of backdated seed timestamps (memory: seed data has "backdated timestamps" for validated shifts) — verify seed data doesn't produce a misleading distribution before treating the browser-verification pass as confirming correctness on real timing.
