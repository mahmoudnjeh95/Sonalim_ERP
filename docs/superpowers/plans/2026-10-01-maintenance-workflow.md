# Maintenance Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preventive programs + urgent jobs, machine checkpoint maps, a guided step-by-step check wizard with who/when/how-long per point, supervisor review loop (close / rework), spare-parts requests (stock issue or draft PO), a calendar and in-app notifications.

**Architecture:** All new tables live in the `maintenance` schema (migration `0005`), plus one shared-kernel table `core.notifications`. Pure rules (job lifecycle, recurrence, durations, parts split) live in `modules/maintenance/domain/` and are unit-tested without a DB; services in `modules/maintenance/api/` do raw SQL via psycopg and call other modules only through their `api/` services (HR `EmployeeService`, warehouse `StockService`) or events (procurement drafts the PO from `maintenance.parts.purchase_requested`). The frontend adds tabs to `MaintenancePage`, a job page, a full-screen wizard route and a notification bell.

**Tech Stack:** FastAPI, psycopg 3 raw SQL, python-ulid, pytest; React 18 + TS, TanStack Query, React Router, Tailwind, Radix primitives in `components/ui/`, Framer Motion, lucide-react.

**Spec:** `docs/superpowers/specs/2026-10-01-maintenance-workflow-design.md` — read it first; this plan adds exact names/shapes.

## Global Constraints

- Work only in the worktree `D:\mahmoud repo\Sonalim_ERP\.worktrees\maintenance-workflow`. Python: `"D:/mahmoud repo/Sonalim_ERP/backend/.venv/Scripts/python.exe"` run from `<worktree>/backend`. Frontend: run `npm` in `<worktree>/frontend` (if `node_modules` is missing there, create a junction: PowerShell `New-Item -ItemType Junction -Path "<worktree>\frontend\node_modules" -Target "D:\mahmoud repo\Sonalim_ERP\frontend\node_modules"`).
- Never `git stash`. Commit only your own paths (`git add <paths>`, never `git add -A`). If `index.lock` exists, wait a few seconds and retry — two streams commit in the same worktree. End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.
- Migrations are schema only: no `INSERT ... VALUES`. Never edit an applied migration; `core/migrations/test_migration_data_guard.py` must stay green.
- Ids are `str(ULID())` (`from ulid import ULID`). Cross-module ids are opaque `TEXT`, no FK.
- Service methods return `core.domain.result.Ok/Err`; `Err(code, message_en, message_fr)`. Routers turn `Err` into `HTTPException(status, err_detail(result))` after `connection.rollback()`; success → `connection.commit()`. Follow `modules/maintenance/api/router.py`.
- Every user-visible string in both `frontend/src/lib/i18n.en.ts` and `i18n.fr.ts` (French is the plant language: Intervention, Programme, Point de contrôle, Chef d'atelier, Équipe, Pièces, Clôturer, Renvoyer en correction…).
- Frontend typecheck: `npx tsc -b --force` (never plain `tsc -b`). One branded loader per screen (`components/patterns/AppLoader`), `Skeleton` for sub-blocks.
- Integration tests use the `db` fixture (rolled back per test) and **skip** without a DB — report "N passed, M skipped" honestly. The dev DB at `postgresql://erp:erp@localhost:5432/erp` must have the new migrations applied before integration tests run: `"<venv python>" -c "from core.migrations.runner import apply_all_migrations; apply_all_migrations()"` from `<worktree>/backend` (reads `DATABASE_URL`; export `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp` if unset). The dev DB is shared with the main checkout: only additive migrations, never drop/rename.
- No invented thresholds: no default lead days, intervals or durations hard-coded except where the spec states them (sweep interval 3600 s, image limit 10 MB, notifications list 50, bell poll 60 s).

## Review Focus

1. Program sweep running twice (or worker + manual "run due") must never create two jobs for the same occurrence → unique `(program_id, occurrence_date)` + `ON CONFLICT DO NOTHING`; test in Task B5.
2. A rework must reopen only the rejected points and keep every earlier attempt's entry visible → test in Task B4 (`test_rework_reopens_only_rejected_checks_and_keeps_history`).
3. Approving a parts request with more to issue than is on hand must fail the whole approval (no partial stock issue, no event) → test in Task B6.
4. Wizard opened on a job with ad-hoc tasks (no photo / no pin) must still work → frontend Task F5 handles `view_id === null` with a plain card; backend B4 test creates a job with only ad-hoc tasks.
5. Editing or deleting a machine's map after jobs exist must not change those jobs → B3 test `test_view_with_snapshotted_checkpoints_cannot_be_deleted` and B4 snapshot test.

---

## API contract (both streams build against this — do not change names)

All under `/maintenance` unless stated. Dates `YYYY-MM-DD`, timestamps ISO-8601 with offset. `*_name` fields are resolved server-side (user `full_name` falling back to `email`; employee `first_name last_name`; equipment `name`).

```ts
type JobStatus = "planned"|"assigned"|"in_progress"|"submitted"|"rework"|"closed"|"cancelled";
type CheckState = "pending"|"done"|"accepted"|"rejected";   // "rejected" is never stored long: reject → pending with attempt+1; kept for typing completeness
type CheckAction = "inspect"|"lubricate"|"tighten"|"clean"|"replace"|"measure"|"other";
type Outcome = "ok"|"issue"|"not_done";

interface Team { id; name; chef_user_id: string|null; chef_name: string|null; archived_at: string|null; members: {employee_id; name}[] }
interface Person { id: string; name: string }          // GET /team-candidates (HR active employees), GET /chef-candidates (users with maintenance.execute_jobs)

interface Checkpoint { id; view_id; x_pct: number; y_pct: number; label; action: CheckAction; instructions: string|null; measure_unit: string|null; requires_photo: boolean; sort_order: number; archived_at: string|null }
interface EquipmentView { id; equipment_id; label; sort_order: number; image_mime: string|null; updated_at; checkpoints: Checkpoint[] }   // image at GET /views/{id}/image?v=<updated_at>

interface JobListItem { id; number; equipment_id; equipment_code; equipment_name; kind: "preventive"|"corrective"; priority: "normal"|"urgent"; title; status: JobStatus; due_date: string; team_id: string|null; team_name: string|null; chef_user_id: string|null; chef_name: string|null; program_id: string|null; occurrence_date: string|null; stops_machine: boolean; checks_total: number; checks_done: number; minutes_spent: number; overdue: boolean; created_at; started_at: string|null; submitted_at: string|null; closed_at: string|null }
interface CheckEntry { id; attempt: number; performer_employee_id; performer_name; recorded_by; recorded_by_name; started_at; finished_at; duration_seconds: number; duration_source: "timer"|"manual"; outcome: Outcome; note: string|null; measured_value: number|null; has_photo: boolean }   // photo at GET /check-entries/{id}/photo
interface CheckReview { id; attempt: number; verdict: "accepted"|"rejected"; reason: string|null; reviewer_id; reviewer_name; created_at }
interface JobCheck { id; sort_order: number; checkpoint_id: string|null; view_id: string|null; x_pct: number|null; y_pct: number|null; label; action: CheckAction; instructions: string|null; measure_unit: string|null; requires_photo: boolean; assignee_employee_id: string|null; assignee_name: string|null; state: CheckState; attempt: number; entries: CheckEntry[]; reviews: CheckReview[] }
interface JobEvent { id; at; actor_id: string|null; actor_name: string|null; kind: string; payload: Record<string, unknown> }
interface JobDetail extends JobListItem { description: string|null; created_by; created_by_name; cancel_reason: string|null; checks: JobCheck[]; part_requests: PartRequest[]; timeline: JobEvent[] }

interface Program { id; equipment_id; equipment_name; name; description: string|null; interval_value: number; interval_unit: "day"|"week"|"month"; start_date; lead_days: number; estimated_minutes: number|null; default_team_id: string|null; default_team_name: string|null; stops_machine: boolean; active: boolean; checkpoint_ids: string[]; next_occurrence: string|null }
interface CalendarResponse { jobs: JobListItem[]; projected: { program_id; program_name; equipment_id; equipment_name; date: string }[] }

interface PartRequestLine { id; product_id; product_name; uom_id; uom_code; quantity: number; location_id: string|null; issued_quantity: number|null; purchase_quantity: number|null }
interface PartRequest { id; job_id; job_number; equipment_name; status: "pending"|"approved"|"rejected"; note: string|null; requested_by; requested_by_name; requested_at; decided_by: string|null; decided_by_name: string|null; decided_at: string|null; decision_note: string|null; lines: PartRequestLine[] }
interface Availability { lines: { line_id; product_id; locations: { location_id; location_name; available: number }[] }[] }

interface AppNotification { id; kind; title; title_fr; body: string|null; body_fr: string|null; link: string|null; created_at; read_at: string|null }
```

Endpoints (method path → body → response; permission):

| Endpoint | Body | Response | Permission |
|---|---|---|---|
| GET /teams | – | Team[] | view_jobs |
| POST /teams | {name, chef_user_id?} | Team | manage_teams |
| PATCH /teams/{id} | {name?, chef_user_id?, archived?: bool} | Team | manage_teams |
| PUT /teams/{id}/members | {employee_ids: string[]} | Team | manage_teams |
| GET /team-candidates | – | Person[] | view_jobs |
| GET /chef-candidates | – | Person[] | view_jobs |
| GET /equipment/{id}/views | – | EquipmentView[] (checkpoints exclude archived unless `?include_archived=true`) | view_equipment |
| POST /equipment/{id}/views | multipart: label, image | EquipmentView | manage_checkpoints |
| PATCH /views/{id} | multipart: label?, sort_order?, image? | EquipmentView | manage_checkpoints |
| DELETE /views/{id} | – | 204, or 409 VIEW_IN_USE | manage_checkpoints |
| GET /views/{id}/image | – | bytes | view_equipment |
| POST /views/{id}/checkpoints | {x_pct, y_pct, label, action, instructions?, measure_unit?, requires_photo?} | Checkpoint | manage_checkpoints |
| PATCH /checkpoints/{id} | any of the above + sort_order | Checkpoint | manage_checkpoints |
| POST /checkpoints/{id}/archive | – | Checkpoint | manage_checkpoints |
| GET /jobs | query status (comma list), equipment_id, from, to, mine (bool: chef_user_id = me) | JobListItem[] | view_jobs |
| GET /jobs/{id} | – | JobDetail | view_jobs |
| POST /jobs | {equipment_id, title, description?, priority, due_date, stops_machine, checkpoint_ids: string[], tasks: {label, action, instructions?}[], team_id?, chef_user_id?} | JobDetail | plan_jobs |
| POST /jobs/{id}/assign | {team_id?, chef_user_id} | JobDetail | plan_jobs |
| POST /jobs/{id}/delegate | {assignments: {check_id, employee_id: string|null}[]} | JobDetail | execute_jobs |
| POST /jobs/{id}/checks/{check_id}/entries | multipart: performer_employee_id, outcome, note?, measured_value?, started_at+finished_at **or** manual_minutes, photo? | JobDetail | execute_jobs |
| GET /check-entries/{id}/photo | – | bytes | view_jobs |
| POST /jobs/{id}/submit | – | JobDetail | execute_jobs |
| POST /jobs/{id}/review | {verdicts: {check_id, verdict, reason?}[]} | JobDetail | plan_jobs |
| POST /jobs/{id}/close | – | JobDetail | plan_jobs |
| POST /jobs/{id}/cancel | {reason} | JobDetail | plan_jobs |
| GET /programs | – | Program[] | view_jobs |
| POST /programs | {equipment_id, name, description?, interval_value, interval_unit, start_date, lead_days, estimated_minutes?, default_team_id?, stops_machine, checkpoint_ids: string[]} | Program | plan_jobs |
| PATCH /programs/{id} | same fields optional + active? | Program | plan_jobs |
| POST /programs/run-due | – | {created: number, overdue_notified: number} | plan_jobs |
| GET /calendar | query from, to (required) | CalendarResponse | view_jobs |
| GET /part-requests | query status? | PartRequest[] | view_jobs |
| POST /jobs/{id}/part-requests | {lines: {product_id, uom_id, quantity}[], note?} | PartRequest | execute_jobs |
| GET /part-requests/{id}/availability | – | Availability | plan_jobs |
| POST /part-requests/{id}/approve | {lines: {line_id, location_id: string|null, issue_quantity: number}[], note?} | PartRequest | plan_jobs |
| POST /part-requests/{id}/reject | {note} | PartRequest | plan_jobs |
| GET /core/notifications?unread=true | – | AppNotification[] (latest 50) | session |
| GET /core/notifications/unread-count | – | {count} | session |
| POST /core/notifications/{id}/read | – | 204 | session |
| POST /core/notifications/read-all | – | 204 | session |

`delegate` and `entries` are allowed for the job's chef or any `plan_jobs` holder; another `execute_jobs` user gets 403 `NOT_JOB_CHEF`.

Notification `link`s: job → `/maintenance/jobs/<id>`, parts → `/maintenance?tab=parts`.

---

## Stream B — backend (tasks run in order)

### Task B1: Shared-kernel notifications

**Files:**
- Create: `backend/core/migrations/0028_core_notifications.sql`
- Create: `backend/core/notifications.py`
- Create: `backend/core/test_notifications_integration.py`
- Modify: `backend/app/main.py` (import + `app.include_router(core_notifications_router)`)

**Interfaces — Produces:**
- `notify(connection, *, tenant_id: str, user_ids: Iterable[str], kind: str, title: str, title_fr: str, body: str | None = None, body_fr: str | None = None, link: str | None = None) -> int` (dedupes user ids, skips empty, returns rows written)
- `users_with_permission(connection, tenant_id: str, permission: str) -> list[str]` (direct `core.user_permissions` ∪ `core.role_permissions` via `core.user_roles`, users of that tenant, sorted)
- `router` with the four `/core/notifications` routes (use `require_session` from `core.tenancy`; read `tenant.user_id`, `tenant.tenant_id`).

- [ ] **Step 1: Migration**

```sql
-- In-app notifications for any module. A row belongs to one user; read_at is
-- set when they open it. Modules write through core.notifications.notify().
CREATE TABLE IF NOT EXISTS core.notifications (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES core.users (id),
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    title_fr TEXT NOT NULL,
    body TEXT,
    body_fr TEXT,
    link TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS core_notifications_user_idx
    ON core.notifications (tenant_id, user_id, read_at, created_at DESC);
```

- [ ] **Step 2: Failing integration tests** (`core/test_notifications_integration.py`, users inserted like `modules/maintenance/api/test_equipment_integration.py` fixture `actor`):

```python
def test_notify_writes_one_row_per_distinct_user_and_skips_empty(db, two_users):
    a, b = two_users
    assert notify(db, tenant_id=TENANT, user_ids=[a, b, a, ""], kind="k", title="T", title_fr="T fr", link="/x") == 2

def test_users_with_permission_unions_direct_and_role_grants(db, two_users):
    a, b = two_users
    db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, 'maintenance.plan_jobs')", (a,))
    role_id = str(ULID())
    db.execute("INSERT INTO core.roles (id, tenant_id, code, name) VALUES (%s, %s, %s, 'R')", (role_id, TENANT, role_id))
    db.execute("INSERT INTO core.role_permissions (role_id, permission) VALUES (%s, 'maintenance.plan_jobs')", (role_id,))
    db.execute("INSERT INTO core.user_roles (user_id, role_id) VALUES (%s, %s)", (b, role_id))
    assert users_with_permission(db, TENANT, "maintenance.plan_jobs") == sorted([a, b])

def test_list_unread_count_and_mark_read(db, two_users):
    a, _ = two_users
    notify(db, tenant_id=TENANT, user_ids=[a], kind="k", title="1", title_fr="1")
    notify(db, tenant_id=TENANT, user_ids=[a], kind="k", title="2", title_fr="2")
    rows = list_notifications(db, tenant_id=TENANT, user_id=a, unread_only=True)
    assert [r["title"] for r in rows] == ["2", "1"]
    mark_read(db, tenant_id=TENANT, user_id=a, notification_id=rows[0]["id"])
    assert unread_count(db, tenant_id=TENANT, user_id=a) == 1
    mark_all_read(db, tenant_id=TENANT, user_id=a)
    assert unread_count(db, tenant_id=TENANT, user_id=a) == 0
```
(`list_notifications`, `unread_count`, `mark_read`, `mark_all_read` are module functions in `core/notifications.py` used by the router; `mark_read` only touches the caller's own row.)

- [ ] **Step 3:** Apply migrations to the dev DB, run tests → fail; implement; run → pass. Also run `.venv python -m pytest core/migrations/test_migration_data_guard.py -q`.
- [ ] **Step 4: Commit** `feat(core): in-app notifications table, notify() and /core/notifications routes`.

### Task B2: Maintenance schema, permissions and pure domain rules

**Files:**
- Create: `backend/modules/maintenance/migrations/0005_maintenance_workflow.sql`
- Create: `backend/modules/maintenance/domain/jobs.py`, `domain/programs.py`, `domain/parts.py`
- Create: `backend/modules/maintenance/domain/test_jobs.py`, `test_programs.py`, `test_parts.py`
- Modify: `backend/modules/maintenance/module.json` (version `0.2.0`; permissions add `maintenance.view_jobs`, `maintenance.plan_jobs`, `maintenance.execute_jobs`, `maintenance.manage_checkpoints`, `maintenance.manage_teams`; `optional_depends: ["hr", "warehouse"]`; `provides_api` add `"JobService"`; `publishes_events: ["maintenance.parts.purchase_requested"]`)

- [ ] **Step 1: Migration** — exactly the spec's data model, with these precisions:
  - every table has `tenant_id TEXT NOT NULL`; FKs only inside `maintenance`;
  - `checkpoints.x_pct/y_pct NUMERIC(5,2) NOT NULL CHECK (x_pct BETWEEN 0 AND 100)` (same for y);
  - CHECK constraints on every enum column (`action`, `interval_unit`, `kind`, `priority`, `status`, `state`, `duration_source`, `outcome`, `verdict`, part request `status`);
  - `jobs.number TEXT NOT NULL`, `UNIQUE (tenant_id, number)`, `UNIQUE (program_id, occurrence_date)`; `jobs.overdue_notified_at TIMESTAMPTZ`;
  - `job_checks.attempt INT NOT NULL DEFAULT 1`;
  - `check_entries.duration_seconds INT NOT NULL CHECK (duration_seconds > 0)`;
  - `part_requests.note TEXT`;
  - indexes: `jobs (tenant_id, status)`, `jobs (tenant_id, due_date)`, `jobs (equipment_id)`, `job_checks (job_id)`, `check_entries (check_id)`, `equipment_views (equipment_id)`, `checkpoints (view_id)`, `programs (tenant_id, active)`, `part_requests (tenant_id, status)`, `job_events (job_id, at)`.
  - Header comment: user/employee/product/uom/location ids are opaque references (no FK), same rule as `equipment.work_center_id`.

- [ ] **Step 2: Domain — `jobs.py`** (pure; dataclasses frozen):

```python
JOB_STATUSES = ("planned", "assigned", "in_progress", "submitted", "rework", "closed", "cancelled")
CHECK_ACTIONS = ("inspect", "lubricate", "tighten", "clean", "replace", "measure", "other")
OUTCOMES = ("ok", "issue", "not_done")

@dataclass(frozen=True)
class EntrySummary:
    attempt: int
    outcome: str
    has_photo: bool
    measured_value: float | None

@dataclass(frozen=True)
class CheckSnapshot:
    id: str
    state: str          # pending | done | accepted
    attempt: int
    action: str
    requires_photo: bool
    latest_entry: EntrySummary | None   # latest entry of the current attempt

def can_assign(status: str) -> Result[None]            # planned|assigned → Ok; else Err("INVALID_TRANSITION", ...)
def can_record_entry(status: str, check_state: str) -> Result[None]   # job in assigned|in_progress|rework AND check pending|done; accepted → Err("CHECK_LOCKED")
def status_after_entry(status: str) -> str             # assigned → in_progress; others unchanged
def validate_submit(status: str, checks: list[CheckSnapshot]) -> Result[None]
    # status in_progress|rework; no check pending (Err "CHECKS_PENDING" listing count);
    # each done check: requires_photo and outcome != not_done → has_photo (Err "PHOTO_REQUIRED");
    # action == measure and outcome != not_done → measured_value not None (Err "MEASURE_REQUIRED")
@dataclass(frozen=True)
class ReviewOutcome:
    accepted_ids: tuple[str, ...]
    rejected_ids: tuple[str, ...]
    next_status: str     # "rework" if any rejected else "submitted"
def apply_review(status: str, checks: list[CheckSnapshot], verdicts: list[tuple[str, str, str | None]]) -> Result[ReviewOutcome]
    # status submitted; every check in state done gets exactly one verdict and no other check does
    # (Err "REVIEW_INCOMPLETE" / "UNKNOWN_CHECK"); verdict in accepted|rejected; rejected needs non-blank reason (Err "REASON_REQUIRED")
def can_close(status: str, checks: list[CheckSnapshot]) -> Result[None]    # submitted and all accepted (Err "NOT_ALL_ACCEPTED")
def can_cancel(status: str) -> Result[None]            # not closed/cancelled
@dataclass(frozen=True)
class Timing:
    started_at: datetime.datetime
    finished_at: datetime.datetime
    seconds: int
    source: str
def entry_timing(*, started_at, finished_at, manual_minutes, now) -> Result[Timing]
    # exactly one mode: timer (both stamps, finished > started, finished <= now + 2 min clock skew) or manual (minutes > 0, finished_at = now, started_at = now - minutes);
    # Err "INVALID_TIMING" otherwise
```

Tests (`test_jobs.py`) — one per rule, e.g.:

```python
def _check(id, state="done", action="inspect", photo=False, entry=EntrySummary(1, "ok", False, None), requires_photo=False):
    return CheckSnapshot(id=id, state=state, attempt=1, action=action, requires_photo=requires_photo, latest_entry=entry if state != "pending" else None)

def test_submit_refused_while_a_check_is_pending():
    assert validate_submit("in_progress", [_check("a"), _check("b", state="pending")]).code == "CHECKS_PENDING"

def test_submit_requires_photo_unless_not_done():
    no_photo = EntrySummary(1, "ok", False, None)
    assert validate_submit("in_progress", [_check("a", requires_photo=True, entry=no_photo)]).code == "PHOTO_REQUIRED"
    skipped = EntrySummary(1, "not_done", False, None)
    assert isinstance(validate_submit("in_progress", [_check("a", requires_photo=True, entry=skipped)]), Ok)

def test_measure_needs_a_value():
    assert validate_submit("rework", [_check("a", action="measure")]).code == "MEASURE_REQUIRED"

def test_review_with_a_rejection_sends_the_job_to_rework():
    out = apply_review("submitted", [_check("a"), _check("b")], [("a", "accepted", None), ("b", "rejected", "graisse oubliée")]).value
    assert out.next_status == "rework" and out.rejected_ids == ("b",)

def test_review_must_cover_every_done_check_and_only_them():
    assert apply_review("submitted", [_check("a"), _check("b")], [("a", "accepted", None)]).code == "REVIEW_INCOMPLETE"
    assert apply_review("submitted", [_check("a")], [("a", "accepted", None), ("z", "accepted", None)]).code == "UNKNOWN_CHECK"

def test_rejection_needs_a_reason():
    assert apply_review("submitted", [_check("a")], [("a", "rejected", "  ")]).code == "REASON_REQUIRED"

def test_accepted_check_is_locked():
    assert can_record_entry("rework", "accepted").code == "CHECK_LOCKED"

def test_close_needs_every_check_accepted():
    assert can_close("submitted", [_check("a", state="accepted"), _check("b")]).code == "NOT_ALL_ACCEPTED"

def test_first_entry_starts_the_job():
    assert status_after_entry("assigned") == "in_progress" and status_after_entry("rework") == "rework"

def test_timing_modes():
    now = datetime.datetime(2026, 10, 1, 10, tzinfo=datetime.timezone.utc)
    t = entry_timing(started_at=now - datetime.timedelta(minutes=7), finished_at=now, manual_minutes=None, now=now).value
    assert (t.seconds, t.source) == (420, "timer")
    m = entry_timing(started_at=None, finished_at=None, manual_minutes=15, now=now).value
    assert (m.seconds, m.source, m.finished_at) == (900, "manual", now)
    assert entry_timing(started_at=now, finished_at=now, manual_minutes=None, now=now).code == "INVALID_TIMING"
    assert entry_timing(started_at=now, finished_at=now, manual_minutes=5, now=now).code == "INVALID_TIMING"
```
Also cover every forbidden lifecycle edge (`can_assign("closed")`, `can_cancel("closed")`, `can_record_entry("submitted", "done")`, `validate_submit("assigned", ...)`, `apply_review("rework", ...)`).

- [ ] **Step 3: Domain — `programs.py`**

```python
INTERVAL_UNITS = ("day", "week", "month")
def validate_program(*, interval_value: int, interval_unit: str, lead_days: int, name: str) -> Result[None]   # value >= 1, unit known, lead_days >= 0, name non-blank
def nth_occurrence(start: date, value: int, unit: str, n: int) -> date    # month: add n*value months, clamp day to month length (computed from start each time, so Jan 31 → Feb 28 → Mar 31)
def occurrences(start: date, value: int, unit: str, from_date: date, to_date: date) -> list[date]   # inclusive window, ascending
def due_occurrences(start: date, value: int, unit: str, lead_days: int, today: date, not_before: date) -> list[date]
    # occurrences in [max(start, not_before), today + lead_days]
def next_occurrence(start: date, value: int, unit: str, after: date) -> date   # first occurrence >= after
```
Tests: monthly clamp `nth_occurrence(date(2026,1,31),1,"month",1) == date(2026,2,28)` and `n=2 → date(2026,3,31)`; weekly window; `due_occurrences` with lead 3 on today = occurrence − 3 includes it, − 4 excludes it; `not_before` excludes older dates; `validate_program` codes `INVALID_INTERVAL`, `INVALID_LEAD_DAYS`, `NAME_REQUIRED`.

- [ ] **Step 4: Domain — `parts.py`**

```python
def split_line(*, quantity: float, issue_quantity: float, available: float) -> Result[tuple[float, float]]
    # 0 <= issue <= quantity (Err "INVALID_QUANTITY"), issue <= available (Err "INSUFFICIENT_STOCK"); returns (issue, quantity - issue)
def fulfilment(issued: float | None, purchase: float | None) -> str | None   # None before decision; "stock" | "purchase" | "split"
```
Tests for each branch.

- [ ] **Step 5:** Run `.venv python -m pytest modules/maintenance/domain -q` (all pass), apply migrations to the dev DB, run the migration guard test.
- [ ] **Step 6: Commit** `feat(maintenance): workflow schema, permissions and pure job/program/parts rules`.

### Task B3: Teams and checkpoint maps

**Files:**
- Create: `backend/modules/maintenance/api/team_service.py`, `api/map_service.py`, `api/people.py`
- Create: `backend/modules/maintenance/api/teams_router.py`, `api/maps_router.py`
- Modify: `backend/modules/maintenance/api/router.py` (at the bottom: `router.include_router(teams_router.router)` etc.; sub-routers have **no** prefix, the parent carries `/maintenance`)
- Test: `backend/modules/maintenance/api/test_teams_maps_integration.py`

**Interfaces — Produces:**
- `people.py`: `user_names(connection, tenant_id, user_ids) -> dict[str, str]` (reads `core.users` — shared kernel, allowed), `employee_names(connection, tenant_id, employee_ids) -> dict[str, str]` and `active_employees(connection, tenant_id) -> list[dict(id,name)]` (both via `modules.hr.api.employee_service.EmployeeService.list_employees` / `get_employee` — **never** SQL on `hr.*`).
- `TeamService(conn)`: `list_teams(tenant_id) -> list[dict]`, `create_team(tenant_id, actor_id, name, chef_user_id)`, `update_team(...)`, `set_members(tenant_id, actor_id, team_id, employee_ids)`, `get_team(tenant_id, team_id) -> dict | None` — dicts in the `Team` contract shape.
- `MapService(conn)`: `list_views(tenant_id, equipment_id, include_archived=False) -> list[dict]`, `create_view(tenant_id, actor_id, equipment_id, label, image: bytes, mime: str)`, `update_view(...)`, `delete_view(...)` (Err `VIEW_IN_USE` when any `job_checks.view_id` references it), `get_image(tenant_id, view_id) -> tuple[bytes, str] | None`, `add_checkpoint(...)`, `update_checkpoint(...)`, `archive_checkpoint(...)`, `active_checkpoints(tenant_id, equipment_id) -> list[dict]`, `checkpoints_by_ids(tenant_id, ids) -> list[dict]` (used by B4 to snapshot; Err `UNKNOWN_CHECKPOINT` if any id is missing/archived/of another machine is checked in B4).
- Image validation: mime in `image/jpeg|image/png|image/webp`, size ≤ 10 * 1024 * 1024 → else Err `INVALID_IMAGE` (422). Equipment must exist in tenant → Err `NOT_FOUND` (404).

- [ ] **Step 1: Failing tests** — `test_team_lists_chef_and_member_names`, `test_set_members_replaces_the_list`, `test_view_upload_rejects_non_images_and_oversize`, `test_checkpoint_outside_0_100_is_refused`, `test_archived_checkpoint_hidden_unless_asked`, `test_view_with_snapshotted_checkpoints_cannot_be_deleted` (insert a `maintenance.jobs` + `job_checks` row referencing the view by SQL in the test), `test_delete_view_cascades_its_checkpoints_when_unused`. For HR names, create an employee through `EmployeeService.create_employee` if its `EmployeeFile` is simple enough; otherwise insert into `hr.employees` in the **test only** (tests may set up fixtures directly).
- [ ] **Step 2:** Implement services; routers per the contract (multipart via `UploadFile = File(...)`, `label: str = Form(...)`; image response `Response(content, media_type=mime, headers={"Cache-Control": "private, max-age=86400"})` like `modules/scan/api/router.py:142`). `/chef-candidates` = `users_with_permission(conn, tenant, "maintenance.execute_jobs")` mapped through `user_names`.
- [ ] **Step 3:** Run `pytest modules/maintenance -q` → pass (report skips).
- [ ] **Step 4: Commit** `feat(maintenance): teams and machine checkpoint maps (photos + pins)`.

### Task B4: Jobs — create, assign, delegate, wizard entries, submit, review, close, cancel

**Files:**
- Create: `backend/modules/maintenance/api/job_service.py`, `api/job_queries.py` (list/detail SQL + serialisation), `api/jobs_router.py`, `api/notifications.py` (maintenance-side helpers wrapping `core.notifications.notify` with the en/fr texts)
- Modify: `api/router.py` include
- Test: `backend/modules/maintenance/api/test_jobs_integration.py`

**Interfaces — Produces:**
- `JobService(conn)`:
  - `create_job(*, tenant_id, actor_id, equipment_id, title, description, kind, priority, due_date, stops_machine, checkpoint_ids, tasks, team_id=None, chef_user_id=None, program_id=None, occurrence_date=None) -> Result[str]` (returns job id). Status `assigned` if `chef_user_id` (or team's chef) is known, else `planned`. Snapshots checkpoints (ordered by view sort_order, checkpoint sort_order) then ad-hoc tasks. Needs ≥ 1 check → Err `NO_CHECKS`. Number `MT-<year>-<4-digit seq>`: take `pg_advisory_xact_lock(hashtext(tenant_id || ':maintenance_job_number'))` then `max+1` for that year. For `program_id` callers: `INSERT ... ON CONFLICT (program_id, occurrence_date) DO NOTHING` → returns Err `ALREADY_EXISTS` when nothing inserted. Writes `job_events` `created` (+ `assigned`). Notifies per the spec's table (urgent → supervisors + chef; assigned → chef).
  - `assign_job(*, tenant_id, actor_id, job_id, team_id, chef_user_id) -> Result[None]`
  - `delegate(*, tenant_id, actor_id, job_id, assignments: list[tuple[str, str | None]], actor_can_plan: bool) -> Result[None]`
  - `record_entry(*, tenant_id, actor_id, job_id, check_id, performer_employee_id, outcome, note, measured_value, started_at, finished_at, manual_minutes, photo: tuple[bytes, str] | None, actor_can_plan: bool, now) -> Result[None]` — uses `can_record_entry`, `entry_timing`, `status_after_entry`; sets check state `done`; on first move to `in_progress` sets `started_at` and, if `stops_machine`, `EquipmentService(conn).transition_status(... new_status="maintenance")` when the equipment is `operational` or `down`. Performer must be an active HR employee → Err `UNKNOWN_EMPLOYEE`. Photo validated like B3 images.
  - `submit(*, tenant_id, actor_id, job_id, actor_can_plan) -> Result[None]` → `submitted`, `submitted_at`, notify supervisors.
  - `review(*, tenant_id, actor_id, job_id, verdicts) -> Result[None]` → inserts `check_reviews` for the current attempt; accepted → state `accepted`; rejected → state `pending`, `attempt = attempt + 1`; job → `rework` (notify chef) or stays `submitted`.
  - `close(...)` → `closed`, `closed_at/by`; equipment back to `operational` if `stops_machine` and it is `maintenance`; notify chef. `cancel(..., reason)` → reason required (Err `REASON_REQUIRED`); notify chef.
  - Every mutation writes one `job_events` row and one `record_audit(... entity_type="maintenance_job")`.
- `job_queries.py`: `list_jobs(conn, tenant_id, *, statuses=None, equipment_id=None, date_from=None, date_to=None, chef_user_id=None, today) -> list[dict]` (JobListItem; `overdue = due_date < today and status not in (closed, cancelled)`; `minutes_spent` = sum of the latest entry per check per attempt, rounded) and `job_detail(conn, tenant_id, job_id, today) -> dict | None` (JobDetail; `part_requests` via B6's `list_part_requests(conn, tenant_id, job_id=...)` — until B6 lands return `[]` and leave a single import to switch on in B6).
- Router: `TenantContext` only has `tenant_id, user_id, session_token`, so `actor_can_plan = tenant.user_id in users_with_permission(conn, tenant.tenant_id, "maintenance.plan_jobs")` (B1 helper; add a small `user_has_permission(conn, tenant_id, user_id, permission) -> bool` to `core/notifications.py`'s neighbour `core/permissions_lookup.py` if you prefer a direct check). Non-chef executor → 403 `NOT_JOB_CHEF`; `NOT_FOUND` → 404; others → 422.

- [ ] **Step 1: Failing integration tests** (fixtures: two users — supervisor and chef —, one equipment via `EquipmentService.create_equipment`, one view + 3 checkpoints via `MapService`, two HR employees):

```python
def test_full_flow_with_rework(db, ctx):
    jobs = JobService(db)
    job_id = jobs.create_job(tenant_id=T, actor_id=ctx.sup, equipment_id=ctx.machine, title="Graissage", description=None,
                             kind="corrective", priority="urgent", due_date=TODAY, stops_machine=True,
                             checkpoint_ids=ctx.points[:2], tasks=[{"label": "Nettoyer la trémie", "action": "clean"}],
                             chef_user_id=ctx.chef).value
    detail = job_detail(db, T, job_id, TODAY)
    assert detail["status"] == "assigned" and len(detail["checks"]) == 3 and detail["checks"][2]["view_id"] is None
    for check in detail["checks"]:
        assert isinstance(_entry(jobs, ctx, job_id, check["id"]), Ok)
    assert _equipment_status(db, ctx.machine) == "maintenance"
    assert isinstance(jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=job_id, actor_can_plan=False), Ok)
    ids = [c["id"] for c in detail["checks"]]
    jobs.review(tenant_id=T, actor_id=ctx.sup, job_id=job_id,
                verdicts=[(ids[0], "accepted", None), (ids[1], "rejected", "vis non graissée"), (ids[2], "accepted", None)])
    after = job_detail(db, T, job_id, TODAY)
    assert after["status"] == "rework"
    assert [c["state"] for c in after["checks"]] == ["accepted", "pending", "accepted"]
    assert after["checks"][1]["attempt"] == 2 and len(after["checks"][1]["entries"]) == 1
    _entry(jobs, ctx, job_id, ids[1])
    jobs.submit(tenant_id=T, actor_id=ctx.chef, job_id=job_id, actor_can_plan=False)
    jobs.review(tenant_id=T, actor_id=ctx.sup, job_id=job_id, verdicts=[(ids[1], "accepted", None)])
    assert isinstance(jobs.close(tenant_id=T, actor_id=ctx.sup, job_id=job_id), Ok)
    final = job_detail(db, T, job_id, TODAY)
    assert final["status"] == "closed" and len(final["checks"][1]["entries"]) == 2
    assert _equipment_status(db, ctx.machine) == "operational"
```
Plus: `test_rework_reopens_only_rejected_checks_and_keeps_history` (covered above — keep as its own named test asserting the accepted check refuses a new entry with `CHECK_LOCKED`), `test_snapshot_is_not_changed_by_later_map_edits` (edit checkpoint label after creation → job check keeps old label), `test_job_with_only_adhoc_tasks`, `test_job_numbers_increment_per_tenant`, `test_other_executor_cannot_record_on_someone_elses_job` (`NOT_JOB_CHEF`), `test_unknown_performer_refused`, `test_notifications_fan_out_on_urgent_and_submit` (supervisor has `maintenance.plan_jobs` granted in fixture; count rows in `core.notifications`), `test_cancel_requires_reason`.
- [ ] **Step 2:** Implement; routers per contract (entries endpoint multipart with `photo: UploadFile | None = File(None)`, `started_at: datetime | None = Form(None)` …).
- [ ] **Step 3:** Run `pytest modules/maintenance -q` → pass.
- [ ] **Step 4: Commit** `feat(maintenance): jobs lifecycle with guided check entries, review loop and timeline`.

### Task B5: Programs, sweep, calendar, worker thread

**Files:**
- Create: `backend/modules/maintenance/api/program_service.py`, `api/programs_router.py` (also holds `GET /calendar`)
- Modify: `backend/worker/main.py` (new `run_maintenance_programs()` thread started next to `run_replenishment`, interval constant `MAINTENANCE_SWEEP_INTERVAL_SECONDS = int(os.environ.get("MAINTENANCE_SWEEP_INTERVAL_SECONDS", "3600"))`)
- Modify: `api/router.py` include
- Test: `backend/modules/maintenance/api/test_programs_integration.py`

**Interfaces — Produces:**
- `ProgramService(conn)`: `list_programs(tenant_id, today) -> list[dict]` (Program shape; `next_occurrence = next_occurrence(start, v, u, today)` when active else null), `create_program(...)`, `update_program(...)`, `set_checkpoints(...)`, `tenants_with_active_programs() -> list[str]`, `run_due(*, tenant_id, today) -> dict(created=int, overdue_notified=int)`, `calendar(tenant_id, date_from, date_to, today) -> dict` (CalendarResponse: jobs with `due_date` in window via `list_jobs`; projected = `occurrences(...)` in window for active programs minus those with a job (`program_id, occurrence_date`) and minus dates before today).
- `run_due`: for each active program, `due_occurrences(start, v, u, lead_days, today, not_before=created_at::date)`; for each date `JobService.create_job(kind="preventive", priority="normal", due_date=date, title=program.name, description=program.description, stops_machine=program.stops_machine, checkpoint_ids=program checkpoint ids or every active checkpoint of the machine, tasks=[], team_id=default_team_id, program_id, occurrence_date=date, actor_id="system:maintenance-sweep")`; `ALREADY_EXISTS` is skipped silently; `NO_CHECKS` (machine has no points) still creates the job with one ad-hoc task labelled with the program name (action `other`) so a due program is never silently dropped. Then overdue: jobs `due_date < today`, not closed/cancelled, `overdue_notified_at IS NULL` → notify supervisors + chef, set `overdue_notified_at`.
- Worker thread mirrors `run_replenishment` (try/except per tick, commit, print count).

- [ ] **Step 1: Failing tests:** `test_run_due_twice_creates_one_job_per_occurrence`, `test_lead_days_controls_when_the_job_appears`, `test_program_without_points_still_creates_a_job`, `test_program_checkpoint_subset_is_snapshotted`, `test_overdue_notified_once`, `test_calendar_projects_future_occurrences_without_jobs`, `test_inactive_program_is_not_run_or_projected`, `test_no_backfill_before_program_creation` (set `created_at` to today in an old-start program; occurrences before today are not created).
- [ ] **Step 2:** Implement + router + worker.
- [ ] **Step 3:** Run `pytest modules/maintenance -q` → pass. `python -c "import worker.main"` from backend to check imports.
- [ ] **Step 4: Commit** `feat(maintenance): recurring programs, due-job sweep worker and calendar`.

### Task B6: Spare-parts requests → stock issue or draft purchase order

**Files:**
- Create: `backend/modules/maintenance/api/parts_service.py`, `api/parts_router.py`
- Modify: `api/job_queries.py` (fill `part_requests`), `api/router.py` include
- Modify: `backend/modules/procurement/events/consumers.py` (new consumer `procurement.maintenance_parts` on `maintenance.parts.purchase_requested`), `backend/modules/procurement/module.json` (`subscribes_events` add the event)
- Modify: `backend/events/CATALOG.md` (event entry: producer maintenance, consumer procurement, payload)
- Test: `backend/modules/maintenance/api/test_parts_integration.py`, `backend/modules/procurement/events/test_maintenance_parts_consumer_integration.py`

**Interfaces — Produces:**
- `PartsService(conn)`: `create_request(*, tenant_id, actor_id, job_id, lines, note, actor_can_plan) -> Result[str]` (job not closed/cancelled; quantity > 0; product exists — use `core.api.service.CoreService(conn).get_product_uom` or the products table in the shared kernel; notify supervisors), `list_part_requests(conn-level fn) (tenant_id, *, status=None, job_id=None) -> list[dict]`, `availability(tenant_id, request_id) -> dict` (warehouse `StockService(conn).list_stock_items(tenant_id)` filtered to the line products, `available = on_hand - reserved` > 0; location names via `modules.warehouse.api.location_service` — find the list method), `approve(*, tenant_id, actor_id, request_id, lines, note, correlation_id) -> Result[None]`, `reject(*, ..., note)` (note required).
- `approve` in one transaction: every line of the request must be listed once; for each line `split_line(quantity, issue_quantity, available_at(location))`; issue > 0 requires `location_id`; then `StockService.issue_stock(tenant_id, product_id, location_id, quantity=issue, reference=f"maintenance:{job_number}", actor_id, move_type="maintenance")` — any `Err` → return it (router rolls back everything); store `location_id, issued_quantity, purchase_quantity`; if any purchase > 0 publish `maintenance.parts.purchase_requested` with payload `{request_id, job_number, lines: [{line_id, product_id, uom_id, quantity}]}` (purchase lines only); status `approved`, `job_events` `parts_approved`, notify requester. Check `issue_stock`'s accepted `move_type` values (grep `move_type` CHECK in warehouse migrations); if `"maintenance"` is not allowed, add a warehouse migration widening it — **that is a warehouse-owned migration file** `modules/warehouse/migrations/00NN_warehouse_move_type_maintenance.sql`.
- Consumer: like `_handle_replenishment_approved`; `notes = f"maintenance:{request_id}"`; idempotent on that note; one PO with all lines, `unit_price 0`, `unit_price_currency "XOF"`, no supplier.

- [ ] **Step 1: Failing tests:** `test_request_then_approve_issues_stock_and_publishes_purchase_for_remainder` (seed stock with `StockService.receive_stock` on a location created via the warehouse location service; assert `warehouse.stock_moves` row with `move_type='maintenance'` and one `events.outbox` row with `event_type = 'maintenance.parts.purchase_requested'`), `test_approve_more_than_available_fails_and_changes_nothing` (Review Focus 3: no stock move, no outbox row, status still pending after rollback — call through the router-like pattern: service returns Err, test asserts nothing written because `issue_stock` is only called after all lines validate), `test_reject_requires_note`, `test_cannot_request_on_closed_job`, consumer: `test_consumer_drafts_one_po_and_is_idempotent`.
- [ ] **Step 2:** Implement (validate **all** lines before the first `issue_stock`).
- [ ] **Step 3:** Run `pytest modules/maintenance modules/procurement -q` → pass.
- [ ] **Step 4: Commit** `feat(maintenance): spare-parts requests issued from stock or drafted as a purchase order`.

### Task B7: Dev seed + permissions for the demo user

**Files:**
- Create: `backend/scripts/seed_maintenance.py` (dev only; idempotent: skips when a team named `Équipe maintenance` exists)

- [ ] **Step 1:** Script, using services (not raw SQL where a service exists): find demo tenant/user (`demo@sonalim-erp.local`); grant `maintenance.view_jobs, plan_jobs, execute_jobs, manage_checkpoints, manage_teams` to the demo user (`INSERT ... ON CONFLICT DO NOTHING` into `core.user_permissions`); pick 2 existing equipment (create `MAINT-DEMO-1/2` if none); 2 views each with generated placeholder PNGs (Pillow if available in the venv — check; else a tiny hand-built PNG via `zlib` + `struct` with a labelled-less flat colour and grid) and ~6 checkpoints mixing actions (one `measure` with unit `°C`, one `requires_photo`); a team with demo as chef and 3 active HR employees (if HR has none, skip members and print a warning); 2 programs (weekly graissage, monthly serrage) starting 3 weeks ago; run `ProgramService.run_due`; one urgent job in progress with 2 entries; one closed job with full history; one pending parts request on a product that exists.
- [ ] **Step 2:** Run it against the dev DB twice (second run is a no-op). Print a summary.
- [ ] **Step 3: Commit** `chore(scripts): seed maintenance demo data`.

---

## Stream F — frontend (tasks run in order; builds against the API contract; may start in parallel with Stream B)

Common: `frontend/src/features/maintenance/api.ts` gets every type of the contract and `apiFetch` functions; hooks in the same file or `features/maintenance/hooks.ts` using TanStack Query (look at an existing feature, e.g. `features/procurement` or `features/qc`, for the `useQuery`/`useMutation` + token pattern from `lib/auth`). Multipart: build `FormData` and pass it as body — check `lib/api.ts` handles `FormData` without forcing JSON content-type (scan's `features/scan` upload code shows how).

### Task F1: Notification bell

**Files:** Create `frontend/src/features/notifications/api.ts`, `frontend/src/features/notifications/NotificationBell.tsx`; Modify `routes/Sidebar.tsx` (bell beside the user menu / language toggle; collapsed sidebar shows icon only) and `routes/AppLayout.tsx` (bell in the mobile top bar, right side); i18n keys `notifications.*`.

- [ ] Bell icon (lucide `Bell`) with a red count badge (hidden at 0, `9+` above 9); `useQuery(["notifications","unread-count"], refetchInterval: 60_000)`. Popover (`components/ui/popover`) lists latest 50 (title/body in current language, relative time, unread dot); click → `POST /{id}/read`, invalidate, `navigate(link)`; "Tout marquer comme lu". Empty state text.
- [ ] `npx tsc -b --force` → 0 errors. Commit `feat(notifications): header bell with unread count`.

### Task F2: Maintenance API layer, tabs and Teams tab

**Files:** Modify `features/maintenance/api.ts`, `MaintenancePage.tsx`; Create `features/maintenance/TeamsTab.tsx`, `features/maintenance/labels.ts` (status/action/outcome → i18n key + colour classes + lucide icon: inspect `Eye`, lubricate `Droplet`, tighten `Wrench`, clean `Sparkles`, replace `RefreshCw`, measure `Gauge`, other `CircleDot`); i18n.

- [ ] All contract types + functions + query hooks (`useJobs(filters)`, `useJob(id)`, `useCalendar(from,to)`, `usePrograms()`, `useTeams()`, `usePartRequests(status)`, `useEquipmentViews(equipmentId)`, mutations for every POST/PATCH/PUT/DELETE invalidating `["maintenance", ...]` keys).
- [ ] Tabs: `calendar` (default), `jobs`, `programs`, `parts`, `equipment`, `teams` — keep `?tab=` URL behaviour; placeholder components for not-yet-built tabs are acceptable only until F4/F6/F7 land in this same stream.
- [ ] Teams tab: card list (name, chef, member chips), create/edit dialog (name, chef select from `/chef-candidates`), members multi-select (checkbox list from `/team-candidates` with search), archive toggle.
- [ ] tsc → 0. Commit `feat(maintenance-ui): API layer, workflow tabs and teams`.

### Task F3: Machine checkpoint-map editor

**Files:** Create `features/maintenance/map/CheckpointMapEditor.tsx`, `map/PinnedPhoto.tsx` (reused by wizard and job page), `map/CheckpointForm.tsx`; Modify `EquipmentTab.tsx` (row action "Plan de points" opens the editor as a full-height dialog or route `/maintenance/equipment/:id/map` — prefer the route, add it to `routes/router.tsx`).

- [ ] `PinnedPhoto` props: `{ src: string; pins: {id: string; x: number; y: number; n: number; tone: "default"|"active"|"done"|"issue"|"dim"}[]; onPick?(x,y): void; onPinClick?(id): void; onPinMove?(id,x,y): void; className? }` — image `object-contain` inside a relative box sized to the image aspect; pins absolutely positioned at `left: x%`, `top: y%`, numbered circles, `active` pulses (Framer Motion scale loop), drag with pointer events converting to % of the image box, clamped 0–100.
- [ ] Editor: view tabs (label + count), "Ajouter une vue" (label + file/camera input `accept="image/*" capture="environment"`; reuse `features/scan/imagePrep.ts` to shrink before upload if it exposes a resize function), replace photo, delete view (show the 409 message), click on photo in "add point" mode → new pin + side form (label, action select with icons, instructions, unit when measure, requires photo switch), drag pin → PATCH x/y, archive point. Points list under the photo on phones.
- [ ] tsc → 0. Commit `feat(maintenance-ui): machine photo map editor with draggable checkpoints`.

### Task F4: Jobs list, job page, urgent job, assign/delegate, review

**Files:** Create `features/maintenance/JobsTab.tsx`, `jobs/JobPage.tsx`, `jobs/NewJobDialog.tsx`, `jobs/AssignDialog.tsx`, `jobs/DelegateDialog.tsx`, `jobs/ReviewPanel.tsx`, `jobs/JobTimeline.tsx`; Modify `routes/router.tsx` (`/maintenance/jobs/:jobId`).

- [ ] Jobs tab: status filter chips (Tous, À assigner=planned, Assignées, En cours=in_progress+rework, À valider=submitted, Clôturées, Annulées), "Mes interventions" toggle (`mine=true`), machine filter, table on desktop / `MobileCardList` on phone: number, title, machine, kind+priority badge (urgent red), status badge, due date (red when `overdue`), chef, progress bar `checks_done/checks_total`, minutes. "Nouvelle intervention" button (visible with plan_jobs — read permissions from the session in `lib/auth`).
- [ ] NewJobDialog: machine select → loads its views; checkpoint multi-select grouped by view (thumbnail + label), ad-hoc tasks repeater (label, action), title, description, priority (Normale/Urgente), due date, stops machine switch, team (pre-fills chef) + chef select. Zod: title required, ≥1 point or task.
- [ ] JobPage: header (number, title, machine, status line, due date, chef/team, stops-machine badge), action bar by status + permission (Assigner, Déléguer, Lancer l'assistant → `/maintenance/jobs/:id/run`, Demander des pièces (F7), Soumettre, Clôturer, Annuler with reason). Checks table: #, point (action icon + label), assignee, state badge, attempt, performer, duration (mm:ss), outcome, photo thumbnail. Views strip with `PinnedPhoto` showing all points coloured by state. Part requests block (F7 fills). `JobTimeline` (icon per kind, actor, relative time, payload summary).
- [ ] ReviewPanel (status `submitted`, plan_jobs): per done check — entries of all attempts (performer, start–end, duration, outcome, note, measure + unit, photo lightbox), previous reviews; Accepter / Rejeter (reason textarea required); footer: "Valider la revue" posts all verdicts; then "Clôturer" when all accepted.
- [ ] tsc → 0. Commit `feat(maintenance-ui): jobs list, job page, assignment, delegation and review`.

### Task F5: Guided check wizard

**Files:** Create `features/maintenance/wizard/CheckWizard.tsx`, `wizard/StepTimer.tsx`, `wizard/WizardSummary.tsx`; Modify `routes/router.tsx` (`/maintenance/jobs/:jobId/run`, rendered **outside** the sidebar layout if the router allows a full-screen route; otherwise a fixed full-screen overlay `fixed inset-0 z-50`).

- [ ] Steps = checks with state `pending` (in rework, only those; show the latest rejection reason on top of each) — if every check is done, open on the summary. Header: back arrow, job number, "Point 3 / 12", progress bar. Body: `PinnedPhoto` of the check's view (current pin `active`, done `done`, others `dim`) or, for `view_id === null`, a plain card with the action icon (Review Focus 4). Action icon + label + instructions. Performer select (team members from the job's team via `useTeams`, fallback all `/team-candidates`; default = check assignee, else last used, remembered in `localStorage` with try/catch).
- [ ] `StepTimer`: big "Démarrer" → records `started_at` (client clock, ISO) and shows elapsed `mm:ss`; "Terminé" freezes `finished_at`. Elapsed survives a page reload (persist `{checkId, startedAt}` in `sessionStorage`, try/catch). Link "Saisir la durée manuellement" → minutes input instead.
- [ ] After Terminé: outcome buttons OK / Anomalie / Non fait (large, coloured), measure input with unit when `measure` (required unless Non fait), note (required when Anomalie or Non fait — client-side only), photo capture when `requires_photo` (required unless Non fait) — camera input + `imagePrep` resize. "Enregistrer et suivant" posts the entry (FormData) then advances; errors shown inline (API `message`/`message_fr` per language).
- [ ] Précédent/Suivant navigation; already-recorded steps show their entry read-only with "Refaire" (posts a new entry). Summary: list of points with outcome/duration/performer, total time, issues highlighted, "Soumettre pour validation" → POST submit → back to job page with a success toast/animation.
- [ ] Must be usable at 390 px: single column, sticky bottom action bar, tap targets ≥ 44 px.
- [ ] tsc → 0. Commit `feat(maintenance-ui): step-by-step check wizard with timer, outcome, measure and photo proof`.

### Task F6: Calendar and Programs tabs

**Files:** Create `features/maintenance/CalendarTab.tsx`, `calendar/MonthGrid.tsx`, `ProgramsTab.tsx`, `programs/ProgramDialog.tsx`.

- [ ] Calendar: month grid Monday-first (week list on < 640 px), prev/next/today, machine filter. Chips: job (number + machine code) coloured by status — closed muted green, in_progress/rework amber, submitted blue, planned/assigned neutral; urgent = red left border; overdue = red text — click → job page. Projected occurrences = dashed outline chip (program name), click → Programs tab. Day click on phone → list below. Legend row. Data `useCalendar(firstVisibleDay, lastVisibleDay)`.
- [ ] Programs tab: table (machine, name, "Tous les N jours/semaines/mois", next occurrence, lead days, team, active switch) + "Lancer les échéances" button (POST run-due, toast with counts). ProgramDialog: machine, name, description, interval value + unit, start date, lead days, estimated minutes, default team, stops machine, checkpoint multi-select grouped by view (none selected = all points, say so in helper text).
- [ ] tsc → 0. Commit `feat(maintenance-ui): maintenance calendar and preventive programs`.

### Task F7: Parts requests

**Files:** Create `features/maintenance/PartsTab.tsx`, `parts/PartRequestDialog.tsx`, `parts/ApproveDialog.tsx`, `parts/PartRequestCard.tsx`; Modify `jobs/JobPage.tsx` (part requests block + "Demander des pièces").

- [ ] PartRequestDialog (from job page): lines repeater with `components/patterns/ProductSelect` (+ its uom), quantity, note.
- [ ] Parts tab: status filter (En attente / Approuvées / Refusées), cards: job number (link), machine, requester, date, lines; per line after decision "Sorti du stock: X @ location" / "À commander: Y". Supervisor: "Valider" opens ApproveDialog — per line, availability per location (from `/availability`), location select + issue quantity (default = min(quantity, available at chosen location)), remainder shown as "à commander"; note; Approve. "Refuser" with note.
- [ ] tsc → 0. Commit `feat(maintenance-ui): spare-parts requests with stock-or-purchase validation`.

---

## Final integration (controller, after both streams)

- [ ] Apply migrations to the dev DB, run `pytest modules/maintenance modules/procurement core -q` (report passed/skipped), run seed B7.
- [ ] Restart backend (see memory: kill stale uvicorn on 8000), open the app in a private headless Chrome, walk: calendar → job page → wizard (390 px) → submit → review reject → wizard rework → review accept → close; notifications bell counts; map editor; parts approve.
- [ ] Fix contract mismatches found; commit.
