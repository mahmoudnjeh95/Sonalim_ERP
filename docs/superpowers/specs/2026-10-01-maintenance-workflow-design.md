# Maintenance workflow — design

Date: 2026-10-01 · Branch: `maintenance-workflow` (worktree `.worktrees/maintenance-workflow`)

## Goal

Turn `maintenance` from an equipment registry into the plant's maintenance workflow:

1. **Planning** — recurring preventive programs per machine, plus urgent / corrective jobs a supervisor raises at any time.
2. **Checkpoint maps** — every machine has several photos (face, gauche, droite, dessus…) with points pinned on them (roulement, graissage de telle vis, serrage…).
3. **Guided execution** — supervisor assigns a job to a chef d'atelier, the chef delegates checks to team members, and a step-by-step wizard records, per point, who did it, when, how long, and the outcome. Everything is kept.
4. **Review loop** — supervisor reviews each point, then closes the job or sends it back to rework (only the rejected points reopen). Every attempt stays in history.
5. **Parts** — the chef requests spare parts on a job; the supervisor validates; lines in stock are issued from the warehouse, lines not in stock become a draft purchase order in procurement.
6. **Calendar** — what was done, what is in progress, what is next (including projected program occurrences).
7. **Notifications** — in-app bell: job due soon (program), urgent job raised, job assigned/delegated, submitted for review, sent back to rework, parts awaiting validation, parts decided.

## Decisions taken by default (user may override)

| # | Decision | Why |
|---|---|---|
| D1 | The wizard is run by a **user** (chef or delegate with `maintenance.execute_jobs`); each point records the **performer as an HR employee** (team member) plus `recorded_by` user. Technicians don't need app accounts. | Most technicians have no login; HR already lists them. |
| D2 | Point time = live **timer** (Start → Terminé). If the point was done off-screen, a manual duration is allowed and flagged `duration_source='manual'`. | User asked "how much time he spends"; manual flag keeps the data honest. |
| D3 | Programs recur on the **calendar only** (every N days / weeks / months), fixed schedule anchored on the program start date (not on completion). Notice lead time is a field on each program. | No machine-hour counters are recorded anywhere — no invented triggers. |
| D4 | Notifications are **in-app only** (bell + list), stored in a new shared-kernel `core.notifications` table so other modules can use it later. No email/SMS/push. | Nothing exists yet; smallest useful step. |
| D5 | Teams are a maintenance table: team name, chef (a user), members (HR employee ids). | Delegation needs a team list; HR has no "team" concept. |
| D6 | Creating a job **snapshots** the checkpoints into job checks. Editing a machine's map later never rewrites past jobs. | Tracking must stay true to what was asked at the time. |
| D7 | Parts not in stock → event → procurement drafts a purchase order (no supplier, price 0), same pattern as warehouse replenishment. Lines in stock → `StockService.issue_stock(move_type='maintenance')` from a location chosen by the supervisor at validation. | Reuses the existing, tested paths. |
| D8 | A job may flag `stops_machine`. Starting it moves the equipment to `maintenance`; closing it moves it back to `operational`. | Equipment status already has these transitions. |

## Roles and permissions (`maintenance/module.json`)

Existing: `maintenance.view_equipment`, `manage_equipment`, `admin_equipment`, `delete_equipment`.

New:
- `maintenance.view_jobs` — see calendar, jobs, programs, parts requests.
- `maintenance.plan_jobs` — **supervisor**: programs, urgent/corrective jobs, assign to chef, review / close / rework, cancel, validate parts requests.
- `maintenance.execute_jobs` — **chef d'atelier**: delegate checks, run the wizard, submit, request parts.
- `maintenance.manage_checkpoints` — edit machine photos and pins.
- `maintenance.manage_teams` — teams and members.

Notification recipients: "supervisors" = users holding `maintenance.plan_jobs` (directly or via a role).

## Data model (schema `maintenance`, one new migration `0005_maintenance_workflow.sql`)

All tables carry `tenant_id TEXT NOT NULL`, ids are ULID `TEXT`. Cross-module refs (user ids, HR employee ids, product ids, uom ids, location ids, PO ids) are opaque `TEXT`, no FK — same rule as `work_center_id`.

```
teams                id, tenant_id, name, chef_user_id, created_at, archived_at
team_members         team_id → teams, employee_id, PRIMARY KEY (team_id, employee_id)

equipment_views      id, tenant_id, equipment_id → equipment, label, sort_order,
                     image BYTEA, image_mime, created_at, updated_at
checkpoints          id, tenant_id, view_id → equipment_views (ON DELETE CASCADE),
                     x_pct NUMERIC(5,2) 0..100, y_pct NUMERIC(5,2) 0..100,
                     label, action ('inspect','lubricate','tighten','clean','replace','measure','other'),
                     instructions TEXT NULL, measure_unit TEXT NULL,
                     requires_photo BOOL DEFAULT false, sort_order, archived_at

programs             id, tenant_id, equipment_id, name, description,
                     interval_value INT > 0, interval_unit ('day','week','month'),
                     start_date DATE, lead_days INT >= 0, estimated_minutes INT NULL,
                     default_team_id NULL, stops_machine BOOL,
                     active BOOL, created_by, created_at
program_checkpoints  program_id, checkpoint_id, PRIMARY KEY (both)
                     -- empty set = every active checkpoint of the machine

jobs                 id, tenant_id, number TEXT (e.g. 'MT-2026-0001', unique per tenant),
                     equipment_id, kind ('preventive','corrective'), priority ('normal','urgent'),
                     title, description, program_id NULL, occurrence_date DATE NULL,
                     UNIQUE (program_id, occurrence_date),
                     due_date DATE, stops_machine BOOL,
                     status ('planned','assigned','in_progress','submitted','rework','closed','cancelled'),
                     team_id NULL, chef_user_id NULL,
                     created_by, created_at, assigned_at, started_at, submitted_at,
                     closed_at, closed_by, cancelled_at, cancel_reason
job_checks           id, tenant_id, job_id → jobs, sort_order,
                     checkpoint_id NULL, view_id NULL, x_pct NULL, y_pct NULL,   -- snapshot (NULL for ad-hoc task)
                     label, action, instructions, measure_unit, requires_photo,
                     assignee_employee_id NULL,
                     state ('pending','done','accepted','rejected')            -- current state, derived on write
check_entries        id, tenant_id, check_id → job_checks, attempt INT,
                     performer_employee_id, recorded_by,
                     started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
                     duration_seconds INT, duration_source ('timer','manual'),
                     outcome ('ok','issue','not_done'), note, measured_value NUMERIC NULL,
                     photo BYTEA NULL, photo_mime NULL, created_at
                     -- append-only: one row per attempt; a rework adds a new row
check_reviews        id, tenant_id, check_id, attempt, verdict ('accepted','rejected'),
                     reason NULL (required when rejected), reviewer_id, created_at
job_events           id, tenant_id, job_id, at, actor_id, kind, payload JSONB
                     -- timeline: created, assigned, delegated, started, check_done,
                     -- submitted, reviewed, rework, closed, cancelled, parts_*

part_requests        id, tenant_id, job_id, status ('pending','approved','rejected'),
                     requested_by, requested_at, decided_by, decided_at, decision_note
part_request_lines   id, tenant_id, request_id, product_id, uom_id, quantity NUMERIC > 0,
                     location_id NULL, issued_quantity NUMERIC NULL, purchase_quantity NUMERIC NULL
                     -- set on approval; fulfilment is derived: stock / purchase / split
```

Images: max 10 MB, `image/jpeg|png|webp`. Served by `GET .../image` with `Cache-Control: private, max-age=86400` and an `updated_at`-based `?v=` from the frontend.

## Domain rules (`modules/maintenance/domain/`, pure, unit-tested)

**Job lifecycle** (`jobs.py`)

```
planned ──assign──▶ assigned ──start──▶ in_progress ──submit──▶ submitted ──close──▶ closed
   │                   │                     ▲                       │
   │                   │                     └──────── rework ◀──────┘ (≥1 check rejected)
   └──────── cancel (any state except closed) ─────────▶ cancelled
```
- `assign`: needs a chef (team optional; a team with a chef pre-fills it). Re-assigning while `assigned` is allowed.
- `start`: happens on the first check entry if not already started; sets `started_at`; if `stops_machine`, the equipment goes to `maintenance` (skip silently if already `maintenance`; `down → maintenance` allowed).
- `submit`: every check has a latest entry for the current attempt (`done` state). Checks with `requires_photo` must carry a photo; `measure` checks must carry a `measured_value`.
- `review`: supervisor posts verdicts for the submitted checks. All accepted → may `close`. Any rejected → job goes `rework`; rejected checks return to `pending` with `attempt + 1`; accepted ones stay accepted and are not redone.
- `close`: only when every check is `accepted`; if `stops_machine` and the equipment is `maintenance`, it goes back to `operational`.
- Urgent jobs (`priority='urgent'`) are created by a supervisor directly in `assigned` when a chef is given.

**Recurrence** (`programs.py`)
- `occurrences(program, from, to)` → dates `start_date + k·interval` (month arithmetic clamps day-of-month, e.g. Jan 31 → Feb 28).
- `due_to_materialise(program, today)` → occurrences with `date - lead_days <= today` that have no job yet (the service checks the unique `(program_id, occurrence_date)`).
- Never back-fills occurrences older than the program's `created_at` date.

**Durations** — timer: `finished_at - started_at` in seconds, must be > 0; manual: minutes > 0 given by the user, `started_at = finished_at - duration`.

**Parts decision** (`parts.py`) — per line, the supervisor chooses a location and the quantity to issue from stock (≤ available there); the rest is `purchase_quantity` (`quantity - issue`). Fulfilment is derived for display: only issued → stock, only purchase → purchase, both → split.

## API (`/maintenance/...`, router errors `{"code","message","message_fr"}` via the existing `Err`)

Teams — `GET/POST /teams`, `PATCH /teams/{id}`, `PUT /teams/{id}/members` (`{employee_ids}`), `GET /team-candidates` (active HR employees: id, name, position) — view_jobs / manage_teams.

Checkpoint maps — manage_checkpoints to write, view_equipment to read
- `GET /equipment/{id}/views` → views with their checkpoints (no image bytes)
- `POST /equipment/{id}/views` (multipart: label, image) · `PATCH /views/{id}` (label, sort_order, optional new image) · `DELETE /views/{id}` (only if no checkpoint of it was ever snapshotted into a job; else 409 `VIEW_IN_USE` → archive its checkpoints instead)
- `GET /views/{id}/image`
- `POST /views/{id}/checkpoints` · `PATCH /checkpoints/{id}` (move x/y, edit fields) · `POST /checkpoints/{id}/archive`

Programs — `GET /programs`, `POST /programs`, `PATCH /programs/{id}`, `PUT /programs/{id}/checkpoints`, `POST /programs/{id}/activate|deactivate` — plan_jobs. `POST /programs/run-due` (plan_jobs) runs the same sweep the worker runs, for the current tenant.

Jobs
- `GET /jobs?status=&equipment_id=&from=&to=&mine=true` — list (number, title, machine, kind, priority, status, due_date, chef, team, progress `done/total`, total minutes).
- `GET /jobs/{id}` — job + checks (with latest entry and review per check) + parts requests + timeline.
- `POST /jobs` — supervisor creates corrective/urgent job: equipment, title, description, priority, due_date, stops_machine, checkpoint_ids (optional) + ad-hoc tasks `[{label, action, instructions}]` (optional; at least one check total), optional team/chef.
- `POST /jobs/{id}/assign` `{team_id?, chef_user_id}` — plan_jobs.
- `POST /jobs/{id}/delegate` `{assignments: [{check_id, employee_id|null}]}` — execute_jobs (chef of the job or plan_jobs holder).
- `POST /jobs/{id}/checks/{check_id}/entries` (multipart: performer_employee_id, started_at, finished_at | manual_minutes, outcome, note, measured_value, photo) — execute_jobs.
- `GET /check-entries/{id}/photo`.
- `POST /jobs/{id}/submit` — execute_jobs.
- `POST /jobs/{id}/review` `{verdicts: [{check_id, verdict, reason?}]}` → returns job (status `rework` if any rejection, else stays `submitted`).
- `POST /jobs/{id}/close`, `POST /jobs/{id}/cancel` `{reason}` — plan_jobs.

Calendar — `GET /calendar?from=&to=` → `{jobs: [...list shape], projected: [{program_id, program_name, equipment_id, equipment_name, date}]}` (projected = occurrences without a job yet, inside the window).

Parts
- `GET /part-requests?status=` · `POST /jobs/{id}/part-requests` `{lines:[{product_id, uom_id, quantity}], note?}` — execute_jobs.
- `GET /part-requests/{id}/availability` → per line, stock per location (via warehouse `StockService.list_stock_items` / `get_available_quantity`).
- `POST /part-requests/{id}/approve` `{lines:[{line_id, location_id?, issue_quantity}]}` · `POST /part-requests/{id}/reject` `{note}` — plan_jobs.
  Approve, in one transaction: issue each stock quantity (`issue_stock`, `move_type='maintenance'`, `reference='maintenance:<job number>'`); for remainders publish **`maintenance.parts.purchase_requested`** `{request_id, job_number, lines:[{line_id, product_id, uom_id, quantity}]}`.
- Procurement consumer `procurement.maintenance_parts` drafts one PO (no supplier, unit price 0, XOF) with `notes='maintenance:<request_id>'`, idempotent on that note. Register the event in `backend/events/CATALOG.md`, add it to maintenance `publishes_events` and procurement `subscribes_events` (procurement needs no module dependency: it only reads the payload).

Notifications (shared kernel, `core/notifications.py` + router mounted at `/core/notifications`)
- `core.notifications`: id, tenant_id, user_id, kind, title, title_fr, body, body_fr, link (SPA path), created_at, read_at. Index `(tenant_id, user_id, read_at, created_at DESC)`.
- Python API: `notify(connection, *, tenant_id, user_ids, kind, title, title_fr, body=None, body_fr=None, link=None)`, `users_with_permission(connection, tenant_id, code) -> list[str]` (direct grants ∪ role grants, active users).
- Routes (require_session): `GET /core/notifications?unread=` (latest 50), `GET /core/notifications/unread-count`, `POST /core/notifications/{id}/read`, `POST /core/notifications/read-all`.

Who gets notified:
| Event | Recipients |
|---|---|
| Program job materialised (due soon) | supervisors + program's default team chef |
| Urgent job created | supervisors + chef if assigned |
| Job assigned | chef |
| Job submitted | supervisors |
| Job sent to rework | chef |
| Job closed / cancelled | chef |
| Job overdue (due_date < today, not closed; once per job) | supervisors + chef |
| Parts requested | supervisors |
| Parts approved / rejected | requester |

## Worker

`worker/main.py` gets `run_maintenance_programs()`: every `MAINTENANCE_SWEEP_INTERVAL_SECONDS` (default 3600) for each tenant with active programs: materialise due jobs (status `assigned` if the program has a default team with a chef, else `planned`; checks snapshotted from `program_checkpoints` or every active checkpoint), notify; then flag overdue jobs (once — `job_events` kind `overdue_notified`). Same try/except-per-tick pattern as replenishment.

## Frontend (`frontend/src/features/maintenance/`)

Tabs on `MaintenancePage` (URL `?tab=`): **Calendrier** (default), **Interventions**, **Programmes**, **Pièces**, **Équipements** (existing), **Équipes**.

- **Bell** in `AppLayout` header: unread count badge (poll 60 s via TanStack Query `refetchInterval`), popover list, click → mark read + navigate to `link`, "Tout marquer comme lu".
- **Calendrier** — month grid (week view on phone): job chips coloured by status (closed = muted green, in progress/rework = amber, submitted = blue, planned/assigned = neutral, urgent = red border, overdue = red text), projected occurrences as dashed chips; day click → list. Legend. Filter by machine.
- **Interventions** — list with status filter chips and "Mes interventions"; "Nouvelle intervention urgente" dialog (supervisor). Row → **job page** `/maintenance/jobs/:id`: header (number, machine, status line, due date, chef/team), actions by role (Assigner, Déléguer, Lancer l'assistant, Soumettre, Revoir, Clôturer, Annuler), checks table (point, assignee, state, performer, duration, outcome), parts requests block, timeline.
- **Machine map editor** (from Équipements row → "Plan de points"): view tabs (Face, Gauche, …), upload/replace photo, click on photo to drop a pin, drag to move, side panel to edit label/action/instructions/unit/requires photo, numbered pins.
- **Wizard** `/maintenance/jobs/:id/run` — full-screen, mobile-first: progress bar "Point 3 / 12", the photo of the point's view with the current pin pulsing (others dimmed, done ones ticked), action icon + label + instructions, performer select (defaults to the check's assignee), big **Démarrer** → running timer → **Terminé**, outcome buttons (OK / Anomalie / Non fait), measure input when `measure`, note, photo capture (reuse scan's camera/`imagePrep` resize), "Saisie manuelle de la durée" link, Précédent / Suivant, final summary screen with Soumettre. In rework only rejected points are shown, with the supervisor's reason on top.
- **Review** (supervisor, on the job page when `submitted`): each check shows entries timeline (attempts), photo, measure, duration; Accepter / Rejeter (reason required); "Clôturer" enabled when all accepted, otherwise "Renvoyer en correction".
- **Programmes** — list (machine, name, every N unit, next date, lead days, team, active) + create/edit dialog with checkpoint multi-select grouped by view.
- **Pièces** — requests list (job, requester, status); supervisor validation dialog showing availability per location, issue qty per line, remainder → "à commander".
- **Équipes** — teams with chef (user select) and members (HR employee multi-select).

All strings en + fr in `lib/i18n.tsx`. One branded loader per screen, Skeleton for sub-blocks. Currency not involved. Mobile: wizard and job page must work at 390 px.

## Testing

- Domain unit tests: lifecycle transitions (every allowed/forbidden edge), rework re-opening only rejected checks, submit preconditions, recurrence (month clamp, lead days, no back-fill), duration rules, parts split.
- Integration tests (`*_integration.py`, `db` fixture): teams, views+checkpoints with image upload, program sweep idempotency (run twice → one job), full job flow assign → entries → submit → review reject → rework → submit → accept → close with equipment status round-trip, parts approve with stock issue + event in outbox, procurement consumer drafts one PO and is idempotent, notifications fan-out + read.
- Migration guard test stays green (no data inserts).
- Frontend: `npx tsc -b --force`; browser check of calendar, map editor, wizard at 390 px.

## Dev data

`backend/scripts/seed_maintenance.py` (dev only, never a migration): one team with demo user as chef + 3 HR employees, two machines with 2 views each (generated placeholder images) and ~6 points, two programs, a few jobs across states, one parts request; grants the new permissions to the demo user.

## Out of scope (later)

Machine-hour / counter-based triggers, email/SMS/push, offline wizard, cost roll-up of parts + labour per machine, MTBF/MTTR analytics, linking production stops to corrective jobs automatically.
