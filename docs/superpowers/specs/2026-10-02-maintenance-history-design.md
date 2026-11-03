# Maintenance history — design

Date: 2026-10-02 · Branch: `huge_production_migration` · Builds on `2026-10-01-maintenance-workflow-design.md` and the spare-parts follow-up.

## Goal

Today maintenance tracks a single **job** well (timeline, every attempt of every point), but not a **machine**: nobody can answer "what happened to the Extrudeuse ligne 1 this year?", "how often does it break down?", "what did this bearing measure over the last six checks?". This feature adds the machine's history, read-only, in four views:

1. **Carnet machine** — one page per machine: its indicators, a chronological timeline (interventions, production stops, status changes) and its checkpoints.
2. **Historique par point** — every check of one checkpoint across all jobs, attempt by attempt, with the measure trend.
3. **Journal global + export** — every intervention closed or cancelled in a period, filterable, exported to Excel; a printable PDF sheet per machine.
4. **Indicateurs machine** — per machine, production's breakdown figures and maintenance's breakdown figures side by side.

It must also be one of the most polished screens of the app: brand palette, the existing icon family plus a few new icons and illustrations, restrained motion.

## User decisions (2026-10-02)

| # | Decision |
|---|---|
| U1 | All four views are in scope. |
| U2 | Breakdown figures are shown **from both sources, side by side, never merged**: production's corrective stops and maintenance's corrective jobs/status changes. |
| U3 | Export: the journal → **Excel**; the machine logbook → **printable PDF sheet** (browser print, payslip pattern). |
| U4 | Approach: **assemble at read time** from existing records — no new maintenance table, no backfill. |
| U5 | Layout direction **A**: white app surface, machine photo on a navy tile, two white indicator blocks, timeline + checkpoints list (mockups in `.superpowers/brainstorm/`, screens `logbook-layout-v3.html`, `history-screens.html`). |
| U6 | Costs are shown in **XOF** (never "F CFA"; `lib/currency.ts` `formatXof`). |

## Defaults taken without asking (user may override)

| # | Default | Why |
|---|---|---|
| H1 | Default period = current calendar year up to today; presets Ce mois / Mois dernier / 3 mois / Cette année / Personnalisée. | A year is what an owner reviews; presets avoid typing dates. |
| H2 | The journal lists jobs **closed** in the period by default (filter: Clôturées / Annulées / Toutes); a row's date is `closed_at` (or `cancelled_at`). Open jobs stay in the Interventions tab and on the logbook timeline. | The journal is the record of what was done. |
| H3 | Anyone with `maintenance.view_jobs` sees the production stops of a machine (type, system, reason, duration, shift, note) in its logbook, without production permissions. | The logbook is the machine's record; stops are part of it. |
| H4 | The indicators list every active machine, plus archived machines that have activity in the period. | An archived machine's past still counts. |
| H5 | The Excel export follows the UI language (`lang=fr|en`, default `fr`). | Bilingual rule. |
| H6 | A point's "anomalies" = entries recorded with outcome `issue`, across every attempt. | Each one was a real finding on the floor. |
| H7 | A status change is **not** labelled with the job that caused it. | The audit row carries no job id and job events use `clock_timestamp()`; matching by time would be a guess. The job's own timeline entry says whether it stopped / restarted the machine (from its `started` / `closed` / `cancelled` event payloads). |
| H8 | Dates are taken in UTC, which is Mali time. A period `[from, to]` is `from 00:00Z` to `to + 1 day 00:00Z`, capped at now. | No timezone setting exists; the plant is UTC+0. |

## Indicator definitions

Every figure comes from a recorded field. Where a figure cannot be computed it is `null` and shown as "—" with the reason (e.g. "aucune panne"); never infinity, never a guessed value. No thresholds, targets or limits are invented.

### Production block — "Selon la production"

Source: production's validated shift reports whose `report_date` is in the period, stops naming this machine (`StopsAnalyticsService`), running time from `MachinePerformanceService.production_minutes` (same scope production's own analytics use).

| Figure | Definition |
|---|---|
| Arrêts | Count and minutes of all stops, split by `downtime_type` (préventif / correctif / maintenance / nettoyage / admin-added types as typed). |
| Pannes | Stops with `downtime_type = 'corrective'`: count and minutes. |
| Pannes par système | Corrective-stop minutes per `classification` (mécanique, électrique, …; labels via production's `downtimeLabel`). |
| MTTR | Breakdown minutes ÷ breakdowns. |
| MTBF | Running minutes ÷ breakdowns. |

Stops with no machine are not attributable; the Indicateurs view shows them on a separate line ("N arrêts sans machine, X min — non attribués").

### Maintenance block — "Selon la maintenance"

| Figure | Definition |
|---|---|
| Pannes | Corrective jobs on the machine **created** in the period, cancelled ones excluded. |
| Préventives | Preventive jobs **due** in the period, cancelled ones excluded: `due`, `closed`, `closed_on_time` (closed on or before `due_date`), `overdue` (due date passed, not closed). |
| Immobilisation | Minutes the machine's status was `down` or `maintenance`, rebuilt from its status changes, clipped to the period; an ongoing one counts up to now. **Status at the period start** = `to_status` of the last change before it; if none, `from_status` of the first change in or after it; if the machine never changed, its current status. |
| Durée moyenne d'immobilisation | Immobilisation ÷ number of immobilisation episodes overlapping the period (an episode = a maximal stretch of non-operational status). |
| Temps moyen entre pannes (calendaire) | (Period minutes up to now − immobilisation) ÷ Pannes. Labelled "calendaire": maintenance records no running time. |
| Temps technicien | Sum of `duration_seconds` of the entries whose `finished_at` is in the period — latest entry of each (check, attempt), same rule as the job list. |
| Pièces | Lines of part requests approved (`decided_at`) in the period on this machine's jobs: issued quantity (from stock) and purchase quantity ("commandé"). |
| Coût pièces | FIFO cost (XOF) of what left stock under the jobs' references `maintenance:<job number>`, read through warehouse's `ValuationService` (never its tables), plus the quantity no layer valued ("non valorisé"). Purchased parts carry no cost on the job (the receipt is not tied back to it). Visible only with `warehouse.view_valuation`. |

### Journal row

Date = `closed_at` / `cancelled_at`. Outcomes = latest entry of each check (`ok` / `issue` / `not_done`, checks without an entry = `pending`). Time = same rule as above over the whole job. Parts and cost = that job's approved requests and its reference's cost.

## Architecture

Read-only. No new maintenance table, no event, no new permission.

```
                    ┌──────────────────────── maintenance ────────────────────────┐
 HTTP ──► history_router ──► history_service ──► domain/history.py (pure rules)    │
                    │              │  own tables: equipment, equipment_views,       │
                    │              │  checkpoints, jobs, job_checks, check_entries, │
                    │              │  check_reviews, job_events, part_requests(+lines)
                    │              ├─► core.audit_log (shared kernel): status changes
                    │              ├─► production api: StopsAnalyticsService,        │
                    │              │                   MachinePerformanceService     │
                    │              └─► warehouse api:  ValuationService             │
                    └─────────────────────────────────────────────────────────────┘
```

- `production` is added to maintenance's `optional_depends` (warehouse and hr already are). If a module is absent, its part of the response is `null` and the screen says "non disponible".
- Status changes are read from `core.audit_log` (`entity_type = 'equipment'`, `action = 'equipment.status_changed'`, payload `from_status`/`to_status`). Every transition already goes through `EquipmentService.transition_status`, including the ones jobs make (D8), so history exists from day one. The architecture rule "`core.audit_log` is the single cross-module history path, no per-module audit table" is why no status table is added.

### Backend changes

| File | Change |
|---|---|
| `core/migrations/0029_core_audit_log_entity_index.sql` | `CREATE INDEX IF NOT EXISTS core_audit_log_entity_idx ON core.audit_log (tenant_id, entity_type, entity_id, occurred_at)`. Schema only; also speeds up `GET /core/audit-log`. |
| `modules/production/api/stops_analytics_service.py` | `list_stops(..., equipment_id: str | None = None)` filter; each row also returns `shift_report_id`, `note`, `corrective_action`. Additive — existing callers unchanged. |
| `modules/warehouse/api/valuation_service.py` | `costs_of_references(*, tenant_id, references: list[str]) -> dict[str, dict]` — one query, same shape per reference as `cost_of_reference`. |
| `modules/maintenance/domain/history.py` | Pure, no DB: status → intervals (period clipping, start-status rule, ongoing), episodes, every formula above, journal outcome counts. |
| `modules/maintenance/api/history_service.py` | `HistoryService(connection)`: `indicators`, `journal`, `equipment_history`, `checkpoint_history`. Reuses `job_queries` check/entry serialisation and `people.employee_names`/`user_names`. |
| `modules/maintenance/api/history_export.py` | Journal → `.xlsx` with openpyxl and the shared helpers of `modules/production/api/xlsx_report_style.py` (title, header, data, total rows, autofit). |
| `modules/maintenance/api/history_router.py` | Endpoints below; mounted from `api/router.py` like the other sub-routers. |
| `modules/maintenance/module.json` | `optional_depends` += `production`; version 0.3.0. |
| `scripts/seed_maintenance.py` | Dev only: a few months of closed jobs with entries (incl. measures, a reject + rework), status changes through `EquipmentService.transition_status`, approved parts — so the logbook is not empty locally. Never run on the server. |

### API (all `maintenance.view_jobs`; errors `{"code","message","message_fr"}` via `Err`)

Every response carries `costs_visible` (holder of `warehouse.view_valuation`) and `production_available`. Costs are `null` when not visible.

- `GET /maintenance/history/indicators?from&to&equipment_id`
  ```
  { from, to, costs_visible, production_available,
    machines: [{ equipment_id, code, name, work_center_id, production_stage, status, archived_at, photo_view_id,
                 production: { stops, stop_minutes, stops_by_type:[{type,count,minutes}],
                               breakdowns, breakdown_minutes, breakdowns_by_system:[{classification,count,minutes}],
                               running_minutes, mtbf_minutes|null, mttr_minutes|null } | null,
                 maintenance: { breakdowns, preventive:{due,closed,closed_on_time,overdue},
                                immobilised_minutes, immobilisations, mean_immobilisation_minutes|null,
                                calendar_minutes, calendar_mtbf_minutes|null, technician_seconds,
                                parts:{issued_lines,purchase_lines}, parts_cost|null, parts_unvalued_quantity|null } }],
    unattributed_stops: { count, minutes } | null }
  ```
  `photo_view_id` = the machine's first view (by `sort_order`) that has an image, for the thumbnail (`GET /maintenance/views/{id}/image`).
- `GET /maintenance/history/journal?from&to&equipment_id&kind=preventive|corrective&status=closed|cancelled|all`
  ```
  { from, to, costs_visible,
    rows: [{ job_id, number, equipment_id, equipment_code, equipment_name, kind, priority, title, status,
             date, due_date, closed_on_time|null, cancel_reason|null,
             performers:[{employee_id,name}], technician_seconds,
             checks_total, outcomes:{ok,issue,not_done,pending},
             parts:{issued_lines,purchase_lines}, parts_cost|null }] }
  ```
- `GET /maintenance/history/journal/export?<same>&lang=fr|en` → `.xlsx` (`maintenance-journal-<from>_<to>.xlsx`): title row (period, filters), header, rows, totals (time, cost). Cost column only when `costs_visible`.
- `GET /maintenance/equipment/{id}/history?from&to` → `EQUIPMENT_NOT_FOUND` (404) if unknown.
  ```
  { equipment:{...as above}, indicators:{production, maintenance}, costs_visible, production_available,
    timeline: [ {kind:"job", at, job:{...journal row fields, created_at, started_at, chef_name,
                                      checks_done, machine_stopped:bool, machine_restarted:bool}},
                {kind:"production_stop", at, stop:{started_at, ended_at, minutes, downtime_type, classification,
                                                  motif, note, corrective_action, report_date, team, shift_report_id}},
                {kind:"status_change", at, from_status, to_status, actor_name} ],
    checkpoints: [{ checkpoint_id, view_id, view_label, label, action, measure_unit, sort_order, archived,
                    checks_count, issues_count, last_checked_at|null, last_outcome|null,
                    last_measured_value|null, recent_measures:[{at,value}] }] }
  ```
  Timeline = jobs created, closed or cancelled in the period, or still open (placed at `closed_at`/`cancelled_at`, else `created_at`), validated-shift stops in the period, status changes in the period; newest first. `recent_measures` = the last 8 measured values (sparkline). Checkpoints include archived ones that have history.
- `GET /maintenance/checkpoints/{id}/history` → `CHECKPOINT_NOT_FOUND` (404).
  ```
  { checkpoint:{id,label,action,instructions,measure_unit,requires_photo,view_id,view_label,x_pct,y_pct,
                equipment_id,equipment_name,archived_at},
    summary:{checks_count, issues_count, last_checked_at|null},
    measures:[{at, value, outcome, job_number}],
    checks:[{ job_id, job_number, job_kind, job_status, check_id,
              attempts:[{ attempt, entries:[{entry_id, performer_name, recorded_by_name, started_at, finished_at,
                                             duration_seconds, duration_source, outcome, note, measured_value, has_photo}],
                          review:{verdict, reason, reviewer_name, created_at}|null }] }] }
  ```
  Scope = `job_checks.checkpoint_id = id` (the snapshot keeps it), all job statuses, newest first. Photos use the existing `GET /maintenance/check-entries/{id}/photo`.

## Frontend

### Screens

- **New tab "Historique"** on `MaintenancePage` (`?tab=history`, `maintenance.view_jobs`, icon `history.svg`). Toolbar: period presets + `DateRangeFilter` for custom, machine select, segmented switch **Indicateurs | Journal** (`?view=`). Period, machine and view live in the URL.
  - **Indicateurs**: four `StatCard`s (pannes production, pannes maintenance, immobilisation, coût pièces XOF — hidden without cost visibility), then a table with a `GroupHeaderRow` ("Selon la production" | "Selon la maintenance", each with its icon), per-column filter row (`ColumnFilterRow`), machine cell = photo thumbnail + name + code. Row → logbook. Footer line for unattributed stops. `no-breakdown.svg` when no machine broke down.
  - **Journal**: `FilterTabs` Clôturées / Annulées / Toutes and type chips, `ColumnFilterRow`, technicians as initials, result as a small OK / anomaly / not-done bar, **Exporter Excel** button (raw `fetch` + blob download, same pattern as `features/production/api.ts` month-recap export, errors through `apiErrorFromResponse`). Row → job page. `history-empty.svg` when empty.
- **Carnet machine** `/maintenance/equipment/:equipmentId` (inside the app layout):
  - Header card: machine photo (first view with an image, via `useAuthedImage`) on a navy radial tile, fallback the stage artwork `stage-extrusion.webp` / `stage-conditionnement.webp` / `stage-melange.webp` (versement), then `machine.svg`; eyebrow "CARNET MACHINE", name, code, line, stage, status chip (with `machine-health-pulse` / `alert-pulse` as in analytics); period control; **Fiche PDF** button.
  - Two indicator cards (`IndicatorBlocks`): Production (4 tiles + "pannes par système" bars, the largest in gold) and Maintenance (4 tiles + preventive ring "6/8" with on-time / overdue line).
  - Body, two columns: **Fil chronologique** (filter chips Tout / Interventions / Arrêts production / Changements d'état / Anomalies; month headers; node icon per kind; the open job's node glows gold with "● En cours") and **Points de contrôle** (pin number, label, last check + outcome, sparkline + last value for measure points, anomaly count chip; "jamais contrôlé" greyed). Click a point → sheet.
  - Entry points: "Historique" button on each `EquipmentTab` row, the machine name on `JobPage`, rows of the two history views.
- **Historique d'un point** — right-side sheet: header (pin, label, action, instructions), the view photo with the pin pulsing gold (reuse `PinnedPhoto`), summary strip (contrôlé N fois · anomalies · dernier), measure chart for measure points (Recharts line, navy; latest point gold; `issue` points red; caption "aucune limite enregistrée"), then each check with its attempts (rejected attempt tinted red, reviewer reason, photo thumbnail → existing `EntryPhoto`). `checkpoint-never.svg` when empty.
- **Fiche PDF** `/maintenance/equipment/:equipmentId/print?from&to`: `PrintShell` page — Sonalim logo mark + wordmark (SONALIM navy, ERP gold) and a gold rule, machine and period, both indicator blocks, interventions table, production stops table, status changes table, checkpoints summary, printed on / by.

### Files

`features/maintenance/history/`: `HistoryTab.tsx`, `IndicatorsView.tsx`, `JournalView.tsx`, `EquipmentHistoryPage.tsx`, `IndicatorBlocks.tsx`, `HistoryTimeline.tsx`, `CheckpointList.tsx`, `CheckpointHistorySheet.tsx`, `MeasureTrendChart.tsx`, `EquipmentHistoryPrintPage.tsx`, `api.ts` (query hooks + types), `historyFormat.ts` (+ `historyFormat.test.ts`: "6 h 40", "57 min", "—" for null).

Shared: `components/ui/sheet.tsx` (new hand-written Radix Dialog primitive sliding from the right, full screen under `sm`; separate from `dialog.tsx`, which rewrites `max-w-*` at runtime); `PrintShell` moves from `features/payroll/print/` to `components/patterns/PrintShell.tsx` with `company` optional (payroll imports updated). Routes added to `routes/router.tsx`.

### Visual design (brand profile)

- Palette only: navy `#071F43` / `#123B6D`, gold `#F5B51B` / `#F5A900` as **the one highlight per view** (live job, latest measure, largest system bar, preventive ring), success `#20A464`, error `#E5484D`, border `#D7E0EA`, 12 px cards, Inter; through the existing Tailwind tokens, no new colours.
- Motion (app rule: only where it explains a state): KPI figures count up in 350 ms, the preventive ring fills in 450–700 ms, timeline items enter 0.45 s with stagger 0.07 s on `EASE = [0.22, 1, 0.36, 1]`; gold ripple on the live job node and on the selected pin. All animated SVGs inside `MotionSafeSvg`; reduced motion shows the end state.
- Loading: one branded loader per screen; Skeleton for sub-blocks (period change keeps blocks mounted).
- Phone (390 px): header stacks, each indicator block becomes 2×2 (figures shrink, never rounded), tables become `MobileCardList`, timeline full width, checkpoints under a toggle, sheet full screen.
- Charts follow the `dataviz` skill when implemented.

### New assets (per `svg-asset-rules`; drafts in the brainstorm mockup)

- `assets/icons/maintenance/`: `history.svg`, `status-change.svg`, `measure.svg`, `checkpoint.svg`, `immobilisation.svg`, `mtbf.svg`, `mttr.svg` — 64×64, 3 px round stroke, `currentColor`, same grammar as the existing set.
- `assets/illustrations/maintenance/`: `history-empty.svg` (open logbook, machine on the left page, timeline with a gold live dot on the right), `checkpoint-never.svg` (photo frame with a gold pin dropping in), `no-breakdown.svg` (machine with a green check halo) — 240×200, same animation vocabulary as `empty-all-clear.svg` (float, halo, ripple, twinkling stars), each with a `prefers-reduced-motion` block.
- Reused: `corrective`, `preventive`, `spare_parts`, `machine`, `alert`, `wrench`, `production/downtime`, `machine-health-pulse`, `alert-pulse`, `stage-*.webp`, `logo-mark.svg`.

All strings en + fr in `lib/i18n.tsx` (`maintenance.history.*`); production's downtime labels reused.

## Testing

- **Domain** `domain/test_history.py`: start-status rule (change before / only after / never), clipping at both ends, ongoing stoppage capped at now, back-to-back `down → maintenance` is one episode, `null` MTBF/MTTR with zero breakdowns, calendar MTBF capped at now, journal outcome counts with rework (latest entry wins).
- **Integration** `api/test_history_integration.py` (`db` fixture):
  - closed job → journal row (outcomes, time, performers, parts, cost via a received + issued part);
  - status changes made through `EquipmentService` → immobilisation minutes and episodes;
  - checkpoint history across two jobs including a rejected attempt and its rework;
  - production block counts only corrective stops of **validated** shifts on that machine, and reports unattributed stops;
  - archived machine with activity is listed, without activity is not;
  - `costs_of_references` and the `equipment_id` filter of `list_stops` (in their own modules' tests).
- **Router** `api/test_history_router_integration.py`: permission `view_jobs` required; `parts_cost` null and `costs_visible` false without `warehouse.view_valuation`; 404 codes; the `.xlsx` opens with openpyxl and holds the rows and totals.
- Migration guard test stays green (index only).
- **Frontend**: `npx tsc -b --force`; `historyFormat.test.ts`; browser check (private headless Chrome, never stash) of the tab (both views), logbook, sheet and print page on desktop and at 390 px, plus `prefers-reduced-motion`.

## Out of scope

Linking production stops to maintenance jobs or raising a job from a stop; limits, alerts or targets on measures; labour cost (no hourly rates exist); machine-hour counters; live (not yet validated) stops in the production block; editing anything from the history screens; changes to the Analytics module's downtime panel.
