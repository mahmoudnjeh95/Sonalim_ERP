# Shift report core — design

Date: 2026-09-20. Status: approved in conversation, spec review deferred to after implementation (client owner's instruction).

**Build status:** milestones 1-5 implemented and verified (backend 829 tests, frontend typecheck, browser walkthrough). Milestone 6 is split. **6a done:** the Daily reports and Conditionnement tabs are retired from the Production navigation (old links redirect to the shift report), legacy reports re-converted (30 of 30), the progress rail is slim and collapsible, and grid columns are resizable (widths remembered per device). **6b not done** (old tables -> views, drop `legacy_report_ledger` and `convert_legacy_reports`): it needs the old write paths retired, and 20 test files with 71 call sites seed data through the old report services, plus six non-test files that write the old tables; validation must also be ported onto the shift tables (the `validate_report` helpers read and write the old tables by report id). Recommended only if the duplication in the schema is worth that cost; nothing user-visible depends on it. Since built: name suggestions (decision 10), supplier fields on the energy section, and a revision-history panel. Not built: the live Stop/Resume control (project 2) and milestone 6b. A month of test data (2026-08-20 to 2026-09-20) is loaded by `backend/scripts/seed_shift_month.py`.

## 1. Goal

Each team, at the end of each shift, submits the paper fiches it fills today as **one shift report** on **one screen**:
Fiche fabrication, Fiche conditionnement, and later Fiche changement bobines and Contrôle des paramètres.
The Validation Center shows the entire shift report. Access is defined per section so that roles can be added later without redesign.

This is **project 1 of 4**:

1. **Shift report core** (this spec): the true merge of Daily and Conditionnement reports, sections, per-section save/submit/revisions, per-section permissions, whole-shift validation, migration of existing (test) data. Includes the `machine_stops` event model as the storage for arrêts, with manual entry only.
2. Live stops: Stop/Resume control, highlighted machine on board and dashboard, late entry flag. (Own spec.)
3. Fiche changement bobines section. (Own spec.)
4. Contrôle des paramètres section. (Own spec.)

## 2. Decisions taken with the client owner

| # | Decision |
|---|---|
| 1 | One entry screen per shift; **sections are collapsible tables** the team scrolls and adds rows to. The team's way of working must not change: sections follow the paper order. |
| 2 | **True merge**: one shift report replaces the Daily and Conditionnement report types. No layered "shift report over two reports". |
| 3 | The screen is anchored on header fields (date, line, team, shift, names), **not on an OF**. Each production run and each packing row names its own product/OF (a PC mold change mid-shift changes the finished product). |
| 4 | Energy (fuel, gasoil, electricity, generator hours) is typed once per shift by the same team and **split across runs by production time** (HD→HF duration). The last run takes the rounding remainder so the total is exact. |
| 5 | Each **section** has its own Save draft and Submit. A submitted section can still be edited; every save writes a revision. |
| 6 | Validation: **one approval for the whole shift**; stock posts once. Rejection is **targeted**: the validator picks sections to return, with a reason. |
| 7 | A shift can only be submitted when **every section is submitted**. An empty section is submitted as **Nothing to report**. |
| 8 | Existing reports are **test data**: convert them best-effort, fill missing values from our side, do not build special handling for ambiguous cases. |
| 9 | Per-section permissions now (granted per user), roles later as bundles of the same keys. |
| 10 | Names of people (conducteur, agent de fabrication, machiniste, aide machiniste) are free text with autocomplete from earlier entries, not linked to user accounts. |
| 11 | The team no longer reaches the old Daily/Conditionnement create dialogs; validators review and correct through the Validation Center. |

Choices made by the implementer, open to correction at review:

- An edit after submit keeps the section submitted and saves a revision; the section shows a "revised after submit" badge.
- Reversal after validation reverses the whole shift and reopens all sections (snapshots kept).
- Migrated shifts get *Nothing to report* on sections that never had data (silo, headcount, mold washes, packet checks, energy where absent) instead of invented readings.

## 3. Paper forms → sections

Section keys, in screen order. `Exists` = the current app already stores it.

| Key | Section (paper origin) | Content | Exists |
|---|---|---|---|
| `runs` | Production runs (Fiche fabrication, table "Production") | one row per run: product/format, mold, lot, HD, HF, semoule lines (quality/silo, bags, T), regrind (lot, %, kg), % eau, humidité | partly: no humidité, no bags/lot on semoule |
| `waste_production` | Pâtes non conformes + Produit fini + Lavage des moules | waste rows: time, run, lot, qty, cause; mold-wash rows: mold, time, state | waste yes (no time/lot); mold wash no |
| `stops` | Arrêts (both fiches) | machine, start, end, type, classification, motif, note, corrective action | minutes-only lines, no machine/times |
| `silo` | État de silo (both fiches) | start/end: format, lot, level %, line state | no |
| `staffing` | Présence personnel | control room, pétrin, semoule, broyage headcount | no |
| `packing` | Conditionnement (Fiche conditionnement) | one row per lot: OF, format, lot, date fab, packing type, film type, cartons, reels, scotch, ruban, packets | mostly; no packing/film type |
| `packet_checks` | Vérification d'état de paquet | hourly: film, packet weight, long weld, vertical weld, date print, note | no |
| `waste_packing` | Déchets pâtes ou intrants (packing side) | type, qty kg, cause, time | yes (no time) |
| `energy` | Énergie | fuel, gasoil, electricity, generator hours | yes (per report) |

Later sections: `reels` (project 3), `parameters` (project 4). Adding one = a new section key + its own data table, no change to the core.

Header names and the visa: names live on `shift_reports`; the visa du responsable is validation.

## 4. Data model

Module: `backend/modules/production`. New migration numbers continue after `0046`.

### 4.1 Core

- `production.shift_reports`
  id, tenant_id, work_center_id (line), report_date, shift, team, conducteur, agent_fabrication, machiniste, aide_machiniste (text), status (`open | submitted | validated | returned`), revision, created_by, submitted_at, validated_by, validated_at, rejection_reason, timestamps.
  Unique `(tenant_id, work_center_id, report_date, shift)`.
- `production.shift_report_sections`
  shift_report_id, tenant_id, section_key, status (`empty | draft | submitted | nothing_to_report | returned`), revision, submitted_by, submitted_at, return_reason. Primary key `(shift_report_id, section_key)`. Only place section state lives.
- `production.shift_section_revisions`
  id, tenant_id, shift_report_id, section_key, revision, snapshot JSONB, reason, actor_id, created_at. Same pattern as `report_revisions`, per section. Validation additionally freezes a whole-shift snapshot (`section_key = '*'`).

### 4.2 Section tables (typed)

| Table | Replaces |
|---|---|
| `shift_runs` (of_id, product, mold_id, lot_number, dlc_date, start/end time, water %, humidity, regrind figures, semoule/flow figures) | `daily_reports` |
| `shift_run_semolina_lines` | `report_semolina_lines` |
| `shift_waste_lines` (adds occurred_at, run_id, lot) | `report_waste_lines` |
| `machine_stops` (id, tenant_id, equipment_id (opaque id into `maintenance.equipment`, no FK across modules; NULL when unknown), shift_report_id, run_id / packing_row_id (both nullable), started_at, ended_at nullable, type, classification, motif, note, corrective_action, source `live | added_after | manual | migrated`) | `report_downtime_lines` |
| `shift_packing_rows` (of_id, format, lot, date_fab, packing_type, film_type, cartons, reels, scotch, ruban, packets, …) | `conditionnement_reports` |
| `shift_energy` | energy columns of `daily_reports` (one row per shift) |
| `shift_silo_states`, `shift_staffing`, `shift_mold_washes`, `shift_packet_checks` | new (created in milestone 2 with their sections) |

Energy is stored once per shift in `shift_energy`; per-run shares are derived at read time by production time, never stored.

### 4.3 Untouched

Warehouse module, `work_orders`, `work_centers`, `molds`, `waste_types`, `shift_windows`, recipes. Machines are `maintenance.equipment` (they left `production.machines`); production only holds `equipment_id` as an opaque reference and a machine's side comes from its `production_stage`.

## 5. Behaviour

### 5.1 State machines

Section: `empty → draft → submitted`, `empty|draft → nothing_to_report`, `submitted → returned` (by validator), `returned → draft → submitted`.
Editing a `submitted` section: stays `submitted`, writes a revision, sets a `revised_after_submit` marker until validation.

Shift: `open` while any section is not submitted/nothing_to_report; `submitted` when every section is; `validated` on approval; `returned` while any returned section is outstanding, back to `submitted` when all are resubmitted.

### 5.2 Validation and stock

- The validator opens a shift; the API returns the section revisions it saw. `validate` sends them back; if any section revision changed, validation is refused ("changed since you opened it").
- Validate posts stock for every run and packing row in **one DB transaction** through the existing `StockService.post_daily_report` / `post_conditionnement_report` (module boundary kept). Any failure rolls the whole shift back.
- Existing validation rules are preserved and run per run/row: recipe check, lot registration, OF consolidation, packaging variance, DLC hand-off to QC.
- Reject: `{sections: [...], reason}`. Chosen sections → `returned`, shift → `returned`.
- Reversal after validation reverses the whole shift using the existing undo posting calls and reopens all sections.

### 5.3 Energy split and stop assignment

- Run share = run production minutes / shift production minutes (derived from `machine_stops` and HD/HF). Last run takes the remainder; a single run gets 100 %.
- A stop, waste row or mold wash is assigned to the run whose HD–HF window contains its time; unassigned rows default to the run in progress and may be changed.

### 5.4 Permissions

`production.shift.view`, `production.shift.validate`, `production.shift.edit.<section_key>` per section. Enforced in the backend router/service; the frontend renders sections read-only and disables actions when missing. Granted per user now; roles later are bundles of the same keys.

### 5.5 Compatibility views and cutover

Views over several tables are not writable, so the old tables can only be replaced by views **in the same step that retires the old write paths**. That step is the last milestone (6), after the new screens exist, so the running app keeps working throughout; milestones 1-5 are additive and the old tables stay authoritative until then.

At cutover the old tables are renamed `*_legacy` and views with the old names and shapes serve the ~20 existing readers (yield, consumption, consolidation, lot suggestion, team/machine performance, Day sheet, QC, dashboards). The old write-path tests are ported to the new services (whole-shift validation changes their semantics, so they cannot pass unchanged); the readers' own tests stay unchanged and are the safety net for the views. Readers are then moved to the new tables one at a time, and each view is dropped when its last reader is gone.

Row ids: a migrated run reuses its old Daily report id and a migrated packing row reuses its old Conditionnement report id. Posted `warehouse.stock_moves` and `warehouse.lots` carry `source_id` = that old id, so they stay valid without any write into the warehouse module.

## 6. Migration (existing test data)

- Group Daily + Conditionnement reports by (work_center, report_date, shift) → one shift report. Each Daily → a run; each Conditionnement → a packing row. Waste/semoule lines carried. Old revisions → section revisions. Statuses map 1:1 (validated stays validated; a mixed group takes the least advanced state).
- Posted stock is undisturbed because runs and packing rows reuse the old report ids (see 5.5). No mapping table.
- Old downtime minutes → `machine_stops`, `source = 'migrated'`, with start/end laid out sequentially from the shift window's start (session time zone), on the report's own `equipment_id` when it has one, otherwise NULL (production may not read `maintenance.equipment`, and maintenance migrates after production).
- Energy: the per-report figures of a shift's Daily reports are summed into one `shift_energy` row. The per-run split is recomputed by production time, so per-run energy of migrated shifts may differ from what was typed; the shift total is exact.
- Conversion is a SQL function `production.convert_legacy_reports()` (deterministic ids, `ON CONFLICT DO NOTHING`, safe to re-run) called by the migration and by tests.
- Required values with no source get neutral defaults; sections with no source data are `nothing_to_report`.
- Old report tables renamed `*_legacy`; views created (5.5).

## 7. Frontend

Location `frontend/src/features/production/shift/`.

- Route `/production/shift`: sticky header (date, line, team, shift suggested from `shift_windows`, four names with autocomplete) with an animated **shift progress** indicator (sections done / total). Below, one **section card** per section: outline icon, title, status chip, row count, collapse/expand with animated height. Card body is a shared `ShiftGrid` (scroll, add row, delete row, keyboard navigation, inline validation). Per section: Save draft, Submit, Nothing to report. Bottom sticky bar: overall status and Submit shift (enabled per rule 7).
- Reuse: `QuantityExpressionInput` (film/cello sums), lot suggestion, `useWasteTypes`, `useShiftWindow`, `ShiftTeamFields`, existing downtime motif options.
- The two ~1,700-line dialogs are split into section components, then removed from the team's path.
- Validation Center: one row per shift with section status chips; the detail view shows the whole shift, per-section revision history, Approve, and Reject-sections.
- Design direction: polished, consistent with the existing Tailwind/shadcn look. An outline icon per section, animated status transitions (draft → submitted check, returned shake/pulse), smooth collapse, subtle row-add/remove motion, skeleton loading, `prefers-reduced-motion` respected. Any new SVG asset follows the `svg-asset-rules` skill. Every string goes through `i18n.tsx` (fr/en).
- Local draft copy in `localStorage` (wrapped in try/catch) so a refresh does not lose typed rows; the server draft remains the source of truth.

## 7a. API surface (indicative, finalised in the plan)

`GET/POST /production/shift-reports`, `GET /production/shift-reports/{id}`, `PUT /production/shift-reports/{id}/sections/{key}` (save draft), `POST …/sections/{key}/submit`, `POST …/sections/{key}/nothing-to-report`, `POST /production/shift-reports/{id}/validate`, `…/reject`, `…/reverse`, `GET …/sections/{key}/revisions`.

## 8. Testing

- Milestone 1: reconciliation of the converted data against the old tables (counts, quantity sums, ids, stock-move sources).
- Cutover: the readers' existing tests pass unchanged against the compatibility views; the old write-path tests are ported to the new services.
- New: section state machine; targeted rejection and re-submission; "changed since opened" refusal; one-transaction validation of a two-run shift including rollback on a failing post; energy split sums exactly; stop → run assignment by time; permission enforcement per section; migration test on a fixture database.
- Frontend: `tsc -b --force`; Playwright pass with the demo login and session seeding (see project memory) covering entry, collapse, submit, revision, validation.

## 9. Milestones

1. Additive schema for the core, runs, packing, waste, stops and energy; conversion of existing reports; reconciliation tests. No behaviour change.
2. The four new small section tables; section save/submit/revision services and permissions (not yet used by the old flows).
3. Validate, reject, reverse on the new tables, built **alongside** the old flow (the app keeps working).
4. Shift report screen.
5. Validation Center.
6. **Cutover**: old tables become views, remaining old writes are removed, the old Daily/Conditionnement tabs are retired, readers are moved to the new tables and the views dropped. `convert_legacy_reports()` is re-run first to pick up anything filed through the old flow in the meantime.

## 10. Out of scope

Live Stop/Resume UI and board highlighting (project 2); Bobines (3); Paramètres (4); user roles; controlled vocabularies for stop type/classification (decided in project 2); linking names to user accounts.

## 11. Risks

- Porting `validate_report` (~700 lines of stock posting and checks) per run/row. Mitigation: keep rules verbatim, old tests as the safety net.
- Compat views hide query-shape differences. Mitigation: the readers' tests run unchanged against the views at cutover, and the conversion is reconciled against the old data in milestone 1.
- Uncommitted work already on the branch (day sheet, waste types, lot/DLC, board). Mitigation: commit or stash that work first so this project starts from a clean baseline.
