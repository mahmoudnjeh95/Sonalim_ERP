# QC on the shift report: per-product conformity, Contrôle des paramètres, and the release gate

Date: 2026-09-24. Builds on `2026-09-20-shift-report-core-design.md` (shift reports, `shift_packing_rows`), `2026-09-22-shift-report-lifecycle-design.md`. QC's "project 4" (Contrôle des paramètres) from the core spec's roadmap is folded into this spec instead of standing alone, because it lives on the QC report, not on a new shift section (decision 2 below).

## Why

The QC module (`backend/modules/qc/`) still opens a quality report against a **legacy** `production.production_reports` / `conditionnement_reports` row (`conditionnement_report_id`), resolved through `ProductionReportService`. Daily and Conditionnement reports are retired from the team's path (core spec, decision 11) — production files everything through the shift report now. QC was never repointed, so it is inspecting data nothing produces any more.

Two other problems, reported by the client:

1. A QC report today records **one** conforming/non-conforming carton count for the whole report, but a shift's packing section can name several products (a mold change mid-shift). Conformity needs to be known per product, not blended into one shift total.
2. `POST /production/board/release` (the Libéré dialog) lets a supervisor move packed goods from the line store to the product's own store **before QC has looked at them**. He should be able to see what is packed and pending, but only release what QC has validated as conforming.

The paper "Contrôle des paramètres" sheet (photographed by the client: Presse, Pompe à vide, Séchage, Chaudière, Compresseurs, Traitement d'eau, Chiller, Additif, Propreté des locaux) is not captured anywhere in the app. It is filled by the QC team after the shift, alongside their conformity judgement — not by the production team live, so it belongs on the QC report, not as a tenth shift section.

## Decisions (agreed 2026-09-24)

1. **One QC report per shift report** (1:1 with `production.shift_reports`, so per line/date/shift/team already). `qc.quality_reports.shift_report_id` replaces `conditionnement_report_id`; `ProductionReportService`/`production_reports`/`conditionnement_reports` are no longer read by QC.
2. **Contrôle des paramètres belongs to the QC report**, filled by the QC team after the shift — not a new production shift section. Nine groups, each a repeatable rows list (not a fixed 2–3-slot snapshot): the paper's times and machine numbers vary shift to shift, so every group is a small table the inspector adds rows to, same UI pattern (`ShiftGrid`-style) already used for shift sections.
3. **Conformity moves from one total per report to a list, one line per product packed that shift** (`conformity_lines`, one row per `shift_packing_row`'s product): `product_id`, `of_id`, `conforming_cartons`, `non_conforming_cartons`, `defect_details`. `of_id` moves from the report header onto each line — a shift can span several OFs, and a non-conformity raised from a line uses that line's own `of_id`/`product_id`, unchanged from today's pair.
4. **The five process indices (pre-dryer, humidity, cooling, PF, SUMO) are removed.** They're superseded by the paramètres groups (e.g. séchage, chaudière already cover drying/temperature ground); nothing in the codebase besides QC's own report/detail/analytics reads them (confirmed by grep — no cross-module callers).
5. **Comments and corrective action stay once per report** (shift-wide notes); only `defect_details` moves onto each conformity line, required when that line's `non_conforming_cartons > 0` (same rule as today, now per line).
6. **Follow-ups open one per conformity line** (per product/OF), not one per report — each keeps its own `window_ends_on` from the existing per-product policy (`FollowUpPolicyService`, unchanged) and its own `quality_report_id` + conformity-line reference, so `count_open_for_of` still gates OF closure correctly per OF.
7. **Existing QC data is not migrated.** No real production QC history exists yet (confirmed with the client). Migration truncates `qc.quality_reports` and its child tables and the demo/dev seeds are rewritten against shift reports.
8. **The release dialog's releasable cap becomes `min(line-store on-hand, packed, QC-validated conforming quantity)` per product per day.** Packed-but-pending (shift's QC report not yet validated) and non-conforming quantity are both shown, greyed out / non-selectable, never counted toward `releasable`. No change to the release transaction itself (still an ordinary warehouse transfer) — only the number the dialog offers changes.

## 1. Data model

Module: `backend/modules/qc/`. New migration numbers continue after `0004`.

### 1.1 `qc.quality_reports` (existing table, altered)

- Drop `conditionnement_report_id`, `pre_dryer_index`, `humidity_percentage`, `cooling_index`, `pf_index`, `sumo_index`, `conforming_cartons`, `non_conforming_cartons`, `defect_details` from `qc.quality_report_details` (the per-report totals/indices are gone — see 1.2/1.3).
- Add `shift_report_id TEXT NOT NULL` (FK-shaped, no cross-module FK per architecture rules — `production.shift_reports` is a different module) with a unique index `(tenant_id, shift_report_id)`, mirroring the old `conditionnement_report_id` uniqueness.
- `of_id` column is dropped from the header; it now lives per conformity line (1.2).
- `team`, `shift`, `report_date`, `status`, `revision`, `created_by`, `submitted_at`, `validated_by`, `validated_at`, `rejection_reason` are unchanged in shape, still resolved from the shift report on create/re-link (mirrors today's `_resolve_conditionnement`, renamed `_resolve_shift`).

### 1.2 `qc.quality_conformity_lines` (new, replaces the conforming/non-conforming/defect_details columns)

`id, tenant_id, report_id, shift_packing_row_id, of_id, product_id, conforming_cartons, non_conforming_cartons, defect_details, created_at, updated_at`. One row per `shift_packing_row` on the linked shift at report creation; edited via the same draft/admin-update paths as today, keyed by `shift_packing_row_id` so re-linking or a packing-row change can reconcile it (new rows added for new packing rows, no deletion of a line with an attached non-conformity — same rule as `delete_report`'s guard today, applied per line).

### 1.3 `qc.quality_report_details` (kept, trimmed)

Only `comments`, `corrective_action` remain — the report-wide notes. (If nothing else remains on this table after trimming, it may be folded into `qc.quality_reports` directly; left to the plan to decide against the actual column list.)

### 1.4 `qc.quality_parameters` (new — Contrôle des paramètres)

One row per group entry, since every group is a rows-list (decision 2): `id, tenant_id, report_id, group_key, entry_label, fields JSONB, created_at`. `group_key` one of the nine groups below; `entry_label` is the row's own key text — a free time (`"07h38"`) for most groups, a machine number for `presse`/`compresseurs`. `fields` holds that group's fixed columns as JSON (simplest schema given nine different column sets; validated in the domain layer against a fixed per-group field list, not a generic key/value table per decision in the brainstorm — see 1.4.1).

**1.4.1 Why JSONB and not one table per group:** nine tables of 4–10 float/text columns each is a lot of schema for data nothing but the QC screen and PDF-style report reads; JSONB keeps the migration small while the domain layer (`domain/parameters.py`) still declares each group's fixed field list and types, so validation is exactly as strict as fixed columns would be — this is an implementation-detail choice for the plan to confirm, not a client decision.

Groups and fields (from the photographed sheet):

| `group_key` | Fields |
|---|---|
| `presse` | press number (entry_label), pression, débit_bar, niveau_moulange_percent |
| `pompe_vide` | niveau_huile, temperature_c, niveau_vide_bar |
| `sechage` | temperature_c, delta |
| `chaudiere` | t_aller_c, p_aller_bar, t_retour_c, p_retour_bar, t_digit_c, signal_a_elec, niveau_bac_exp, niveau_bac_alim, compteur_cuve1, compteur_cuve2 |
| `compresseurs` | compressor number (entry_label), pression_bar, temperature_c |
| `traitement_eau` | niveau_cuve1, niveau_cuve2, niveau_sel, niveau_bicore, niveau_bache, niveau_chateau |
| `chiller` | t_entree_c, t_sortie_c, p_entree_bar, p_sortie_bar, t_digit_entree_c, t_digit_sortie_c, proprete_radiateur, observation |
| `additif` | line (PL/PC, entry_label), tableau, niveau_tremie, observation |
| `proprete_locaux` | lave_m, chaud, tri_eau, compr, b_eau, presse, pres_en_h, sech_en_h, silo |

(Exact field list/labels confirmed against the photo at plan time with the client if any reading was misread.)

### 1.5 `qc.quality_follow_ups` (existing table, altered)

Add `conformity_line_id TEXT` (nullable only for rows created before this change, which won't exist post-migration since data is truncated — so effectively `NOT NULL` going forward). `of_id` stays on the follow-up row itself (copied from the conformity line at open time, same as today's copy from the report), since `count_open_for_of` and the follow-up list filter by it directly.

### 1.6 Everything downstream of `conditionnement_report_id`

`report_product.py`'s `finished_product_of_report`/`finished_products_of_reports` (currently reading `production_reports`/`conditionnement_reports`) are QC's only remaining caller once this ships — QC no longer calls them (it reads `shift_packing_rows` directly through `shift_report_id`/conformity lines). No change needed to those functions themselves; just confirm no other module still needs them once QC stops (out of scope to remove them here if something else uses them — the plan checks).

## 2. Domain (`backend/modules/qc/domain/`)

- `quality.py`: `QualityReport` drops `of_id`, `product_id` (was already resolved elsewhere), gains `shift_report_id`. `QualityReportDetail` shrinks to `comments`, `corrective_action`. New `ConformityLine` dataclass (`product_id`, `of_id`, `conforming_cartons`, `non_conforming_cartons`, `defect_details`). `validate_quality_detail` splits into `validate_conformity_line` (per-line: non-negative, integer cartons, defect_details required if `non_conforming_cartons > 0` — same checks as today, scoped per line) and a (now much smaller) report-level check, if any remains.
- `is_conforming(detail)` becomes `is_conforming(lines)` — true only if every line has zero `non_conforming_cartons` (matches the current all-or-nothing semantics of the report-level flag, now correctly computed from the real per-product data instead of one blended total).
- New `domain/parameters.py`: the nine groups' field lists/types (1.4.1) and a `validate_parameter_entry(group_key, fields)` — same "refuse impossible values, not disappointing ones" stance as `validate_quality_detail` (numeric ranges only where physically bounded, e.g. a percentage 0–100; nothing else judged).

## 3. Service layer (`backend/modules/qc/api/`)

### 3.1 `QualityReportService`

- `_resolve_shift(tenant_id, shift_report_id)` replaces `_resolve_conditionnement`: reads `production.shift_reports` + `production.shift_packing_rows` via a new synchronous call into a production service (mirrors today's cross-module call direction), returning header fields plus the packing rows' `(shift_packing_row_id, of_id, product_id)` triples to seed conformity lines.
- `list_inspectable_shift_reports` replaces `list_inspectable_conditionnement_reports`: shift reports with status `validated` (stock already posted — matches today's implicit assumption that a conditionnement report worth inspecting is a finished one; confirm against today's actual status filter in the plan) and no QC report yet.
- `create_report(shift_report_id, ...)`: seeds one `quality_conformity_lines` row per packing row at creation (zeroed), same pattern as a blank detail row today; the inspector fills each line's counts, not a blank form.
- `update_draft`/`admin_update_report`: take a list of conformity-line edits (`{shift_packing_row_id, conforming_cartons, non_conforming_cartons, defect_details}`) plus the report-level `comments`/`corrective_action`, replacing the single-detail signature.
- `submit_report`: validates every conformity line (was: the one detail) plus every parameter entry present.
- `validate_report`: opens one follow-up per conformity line (decision 6), publishes `qc.quality_report.validated` with `is_conforming` computed across all lines (decision 4's `is_conforming`).
- `reject_report`: cleans up non-conformities the same way, now iterating conformity lines' linked NCs instead of one report-wide set (same query shape, scoped correctly since NCs already carry `quality_report_id`).
- `get_conformity_summary(of_id)`, `_reports_needing_nc(of_id)`, `team_conformity`, `index_trend`: rewritten to join through `quality_conformity_lines` instead of `quality_report_details` — `team_conformity`/`index_trend` group by report's `team`/`report_date` as today (unchanged shape) but sum `conformity_lines.conforming_cartons`/`non_conforming_cartons` across all lines of validated reports; `index_trend`'s five `AVG(...)` columns are dropped entirely (decision 4) — replaced by nothing, since no reader besides QC's own dashboard used them (confirmed by grep, see Why).
- New `list_parameters(report_id)` / `save_parameters(report_id, group_key, entries)` on `QualityReportService` (or a small `QualityParametersService` if the plan finds the file growing too large — see file-size note in decision principles).

### 3.2 `NonConformityService`

- `_quantity_from_quality_report` reads `qc.quality_conformity_lines` by `(report_id, shift_packing_row's of_id/product_id)` instead of `qc.quality_report_details` by `(report_id, of_id)` — same derivation (`non_conforming_cartons * packets_per_carton`), just a one-table swap since the caller already supplies `of_id`/`product_id`.
- `raise_non_conformity`'s signature is unchanged; only the internal lookup moves.

### 3.3 New: releasable-quantity lookup for `StockReleaseService`

`QualityReportService` gains `get_validated_conforming(tenant_id, day)` → `dict[product_id, float]`: conforming cartons summed from `quality_conformity_lines` of **validated** QC reports whose shift report's `report_date = day`, joined to `shift_packing_rows` for the packets-per-carton conversion already used elsewhere (`finished_quantity_from_count`, same helper `stock_release_service.py` already imports). Called from `StockReleaseService`, not the other way — this is production asking qc a question, the same direction as `get_conformity_summary`.

## 4. `StockReleaseService` (`backend/modules/production/api/stock_release_service.py`)

`_list_for` gains a `qc_validated_conforming = QualityReportService(...).get_validated_conforming(tenant_id, day)` call. Per item:

- `releasable` becomes `min(remaining, on_hand, qc_validated_conforming.get(product_id, 0.0) - already_released)` (already-released stays subtracted exactly as today).
- New response field `pending_qc: float` = `packed - qc_validated_conforming.get(product_id, 0.0)` clamped to ≥ 0 — packed quantity whose shift QC report is not yet validated, or that QC marked non-conforming. Shown by the frontend as an info line, never enterable.
- `release()` itself is unchanged (it already validates `quantity <= on_hand` and `<= packed - released`; the new cap flows in purely through what `releasable` the dialog offers — a caller who somehow posts more than the QC-validated amount is still blocked by the existing `left`/`on_hand` checks only, so **the plan must add the QC cap as a third server-side check in `release()` too**, not just in the read path, or a stale/forged request could still move unvalidated stock).

## 5. API surface

QC (`backend/modules/qc/api/router.py`), replacing the conditionnement-report endpoints:
- `GET /qc/shift-reports` (was `/qc/conditionnement-reports`) — inspectable shift reports.
- `POST /qc/quality-reports` — body `{shift_report_id}`.
- `PATCH /qc/quality-reports/{id}` / `.../admin` — conformity-line edits + report-level fields, per 3.1.
- `GET/PUT /qc/quality-reports/{id}/parameters` — list/save parameter entries (one call per group or one call for the whole set; plan decides based on how the frontend batches saves, likely per-group to match the rows-list UI pattern).
- Everything else (`submit`, `validate`, `reject`, `revise`, `delete`, follow-ups, non-conformities) keeps its existing path and method, bodies adjusted per 3.1/3.3.

Production (`backend/modules/production/api/router.py`): `GET /production/board/release` response gains `pending_qc` per item (3.4); no path change.

## 6. Frontend

### 6.1 `frontend/src/features/qc/`

- `api.ts`: types follow the new shapes — `QualityReport` drops `conditionnement_report_id`/`of_id`/indices, gains `shift_report_id`; new `ConformityLine`, `ParameterEntry` types; `listInspectableConditionnementReports` → `listInspectableShiftReports`.
- `QualityReportsTab.tsx`: the create form's single conditionnement picker becomes a shift-report picker; the detail/edit view's single conforming/non-conforming/defect inputs become a small editable table (one row per product packed that shift, reusing the existing `ShiftGrid`-style row-table component from `production/shift/` if it can be shared, else a lighter local table — plan decides). A new "Paramètres" tab/section within the report detail with the nine group tables (add-row, same interaction pattern as a shift section's rows list). The five process-index fields and their inputs are removed.
- `QualityDashboardTab.tsx`, `TeamPerformanceTab.tsx` (analytics), `ProductionDashboardTab.tsx`, `ValidationCenterTab.tsx`: update to the new `team_conformity`/`index_trend` response shapes (index_trend's five averages gone; team_conformity's conforming/non-conforming now correctly summed across products, same field names).

### 6.2 `frontend/src/features/production/board/`

- `api.ts`: `ReleaseItem` gains `pending_qc: number`.
- `ReleaseStockDialog.tsx`: shows `pending_qc` next to `releasable` per row when > 0 (e.g. "12 en attente QC" greyed, non-interactive) — a product with `releasable = 0` and `pending_qc > 0` is listed but unselectable (`canRelease` already keys off `releasable > 0`, unchanged), so the existing "not yet in line store" empty-state text needs a QC-specific variant ("en attente de validation qualité") to distinguish the two reasons a row can't be released.
- `QualityBlock.tsx`: `listInspectableConditionnementReports` → `listInspectableShiftReports`; otherwise unchanged (already reads `team_conformity` and NCs, both keeping compatible shapes).

Every new/changed string goes through `i18n.tsx` (fr/en), per repo convention.

## 7. Migration and seed data

- New QC migrations (continuing after `0004`): drop old columns/table pieces, create `quality_conformity_lines`, `quality_parameters`, alter `quality_follow_ups`. Truncates `qc.quality_reports` and its children first (decision 7) — no data to carry forward, so no conversion function needed (unlike the shift-report core migration's `convert_legacy_reports()`).
- `backend/scripts/seed_qc_month.py` (and any other QC seed script) rewritten to create QC reports against seeded shift reports instead of conditionnement reports, with conformity lines per packing row and a sampling of parameter entries.

## 8. Testing

- Backend integration (real DB, existing pattern):
  - `create_report`/`update_draft`/`submit_report`/`validate_report` against a multi-product shift (≥2 packing rows, different OFs) — conformity lines seeded correctly, per-line validation, one follow-up opened per line with the right per-product window.
  - `reject_report` cleans up only the NCs linked to this report's lines, restores quarantine stock per line.
  - `_quantity_from_quality_report` derives correctly per line.
  - `get_conformity_summary`/`_reports_needing_nc`/`team_conformity` against the new schema, values matching a hand-computed expectation.
  - `get_validated_conforming` and the `StockReleaseService.release()` server-side cap: a release request for more than QC-validated conforming quantity is refused even when line-store on-hand would otherwise allow it.
  - Parameter entries: save/read per group, `validate_parameter_entry` range checks.
  - Existing QC test files (`test_qc_flow_integration.py`, `test_team_conformity_integration.py`, `test_disposition_summary_integration.py`) ported to the new shapes — these are the safety net that the per-line rewrite didn't change observable behavior where it shouldn't have.
- Frontend: `tsc -b --force`; browser pass covering: create a QC report from a multi-product validated shift, edit per-product conformity + defect details, fill a few parameter group rows, submit, validate from the Validation Center path (if QC reports show there) or QC's own screen; raise an NC from one conformity line; open the Libéré dialog and confirm a product with a non-validated shift shows `pending_qc` and cannot be released, then validate its QC report and confirm it becomes releasable.

## 9. Out of scope

- No change to the non-conformity/disposition state machine or warehouse-side quarantine mechanics — only how a non-conformity derives its quantity and which report it links to.
- No roles/permission changes — reuses the existing `qc.*` permission keys as-is.
- No PDF/print rendering of the Contrôle des paramètres sheet — data capture only.
- No live/real-time parameter entry — filled after the shift by QC, per decision, not synced from any instrument.
- Milestone 6b of the shift-report core spec (old tables → views) is unrelated and untouched by this work.

## 10. Risks

- `report_product.py`'s `finished_product_of_report`/`finished_products_of_reports` may still be needed by other callers after QC stops using them (1.6) — the plan must check before deciding whether to leave them, not assume QC was the only caller.
- JSONB parameter fields (1.4.1) trade schema simplicity for weaker DB-level typing; the domain-layer validation (`validate_parameter_entry`) is what keeps this safe, and the plan should add a test that a malformed/missing field for a group's declared shape is rejected, not silently stored.
- The release dialog's `pending_qc` distinction (line-store-absent vs. QC-pending) touches user-facing copy the client should see before ship — flag for a screenshot/review pass once built, same as other UI-facing decisions in this program.
- Multi-OF shifts mean a QC report's non-conformity cleanup on `reject_report` must not cross-contaminate lines belonging to a different OF — covered by the per-line NC query in 3.1, but worth an explicit test with two OFs in one shift, one of which has an NC and one which doesn't.
