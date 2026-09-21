# Shift report core — Milestone 2: section services and permissions

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox syntax. Written more tersely than plan M1: the interfaces and test lists below are the contract, code is written test-first in the named files.

**Goal:** Let a team open a shift report and save, submit, edit (with revisions) and declare "nothing to report" on each section, through a service and REST endpoints guarded by per-section permissions. The old report flows are untouched (cutover is the last milestone, M6).

**Architecture:** Pure state rules in `domain/shift_report.py`; a data-driven section registry plus generic upsert-sync in `api/shift_sections.py`; `ShiftReportService` orchestrates state, revisions, audit; router endpoints check `production.shift.edit.<section>` dynamically via a new `user_has_permission` helper (roles work automatically, the core already resolves them).

**Tech Stack:** as M1 (psycopg 3, FastAPI, pytest `db` fixture).

**Spec:** `docs/superpowers/specs/2026-09-20-shift-report-core-design.md` (5.1, 5.4, 4.2). **Previous:** `2026-09-20-shift-report-m1-schema-and-conversion.md`.

## Global Constraints

- Migration `0050` continues after `0049`; additive except one FK change (waste lines survive deleting their run: `ON DELETE SET NULL`).
- Section keys, in screen order: `runs`, `waste_production`, `stops`, `silo`, `staffing`, `packing`, `packet_checks`, `waste_packing`, `energy`.
- Permissions: `production.shift.view`, `production.shift.validate` (used in M3), `production.shift.edit.<section_key>` for each key.
- Row ids: the server generates ULIDs; a client-supplied id is honoured only if it already belongs to the same shift, otherwise ignored.
- No stock posting, no reads of `maintenance.*`, no writes outside `production` and `core.audit_log`.
- Error codes: `NOT_FOUND`, `NOT_EDITABLE` (shift validated), `INVALID_SECTION`, `INVALID_TRANSITION`, `EMPTY_SECTION`, `INVALID_VALUE`, `OF_NOT_OPEN`, `DUPLICATE_ROW`.
- No commits (branch carries uncommitted work); checkpoints only run tests.
- Commands from `D:/mahmoud repo/Sonalim_ERP/backend`; python `.venv/Scripts/python.exe`.

---

### Task 1: Migration 0050 (small section tables, FK change, section rows)

**Files:** Create `backend/modules/production/migrations/0050_production_shift_small_sections.sql`; extend `backend/modules/production/api/test_shift_schema_integration.py`.

**Produces:** `production.shift_silo_states(id, tenant_id, shift_report_id, side, phase, format, lot_number, level_percent, line_state)` unique `(shift_report_id, side, phase)`; `shift_staffing(shift_report_id PK, control_room, petrin, semoule, broyage)`; `shift_mold_washes(id, tenant_id, shift_report_id, mold_id, washed_at, state, line_order)`; `shift_packet_checks(id, tenant_id, shift_report_id, checked_at, film_state, packet_weight_grams, long_weld, vertical_weld, date_print, note, line_order)`.

- [ ] Tests first (append): the four tables exist; `(shift_report_id, side, phase)` unique; `level_percent` outside 0-100 refused; deleting a run keeps its waste line with `run_id` NULL; every existing shift has `silo`, `staffing`, `packet_checks` section rows.
- [ ] Run, see them fail. Write the migration, apply, run, see them pass.

### Task 2: Pure rules (`domain/shift_report.py`)

**Files:** Create `backend/modules/production/domain/shift_report.py`, `backend/modules/production/domain/test_shift_report.py`.

**Produces:**
```python
SECTION_KEYS: tuple[str, ...]
def permission_for_section(section_key: str) -> str            # "production.shift.edit.<key>"
def status_after_save(section_status: str) -> tuple[str, bool] # (new_status, is_edit_after_submit)
def can_submit(section_status: str) -> bool                    # draft or returned
def can_declare_nothing(section_status: str) -> bool           # any but nothing_to_report handled as idempotent
def derive_shift_status(current: str, section_statuses: Iterable[str]) -> str
```
Rules: save from `empty|draft|returned|nothing_to_report` -> `draft`; from `submitted` -> stays `submitted` and is an edit-after-submit. Shift: `validated` never changes; any `returned` section -> `returned`; all sections `submitted|nothing_to_report` -> `submitted`; else `open`.

- [ ] Write the unit tests for each rule (table-driven), run red, implement, run green.

### Task 3: Section registry and row sync (`api/shift_sections.py`)

**Files:** Create `backend/modules/production/api/shift_sections.py`.

**Produces:**
```python
SECTIONS: dict[str, SectionSpec]
def load_section(connection, *, tenant_id, shift_report_id, section_key) -> dict     # JSON-safe payload
def save_section_rows(connection, *, tenant_id, shift_report_id, section_key, payload, custom_waste_categories) -> Result[dict]
def section_is_empty(payload: dict) -> bool
```
Payload shapes: `runs` `{"runs":[{..., "semolina_lines":[..]}]}`; `waste_production` `{"waste_lines":[..], "mold_washes":[..]}`; `stops` `{"stops":[..]}`; `silo` `{"states":[..]}`; `staffing` `{"staffing":{..}|null}`; `packing` `{"rows":[..]}`; `packet_checks` `{"checks":[..]}`; `waste_packing` `{"waste_lines":[..]}`; `energy` `{"energy":{..}|null}`.
Sync = upsert by id within the shift, delete rows absent from the payload, `line_order` from position. Validation: non-negative numbers, required `of_id` (runs/packing) and `started_at` (stops), `ended_at >= started_at`, stop motif in `DOWNTIME_MOTIFS`, waste via `validate_waste_lines`, referenced run/packing ids must belong to the shift, silo `(side, phase)` unique, OF status must accept reports (checked only for new or changed `of_id`).

- [ ] Covered by Task 4's integration tests (registry is exercised through the service); no separate test file.

### Task 4: `ShiftReportService`

**Files:** Create `backend/modules/production/api/shift_report_service.py`, `backend/modules/production/api/test_shift_report_service_integration.py`.

**Produces:**
```python
class ShiftReportService:
    def __init__(self, connection)
    def open_shift(self, *, tenant_id, actor_id, work_center_id, report_date, shift, team=None) -> Result[dict]
    def get_shift(self, *, tenant_id, shift_report_id) -> Result[dict]
    def list_shifts(self, *, tenant_id, report_date=None, work_center_id=None, status=None) -> list[dict]
    def update_header(self, *, tenant_id, actor_id, shift_report_id, fields: dict) -> Result[dict]
    def save_section(self, *, tenant_id, actor_id, shift_report_id, section_key, payload, reason=None) -> Result[dict]
    def submit_section(self, *, tenant_id, actor_id, shift_report_id, section_key) -> Result[dict]
    def declare_nothing(self, *, tenant_id, actor_id, shift_report_id, section_key) -> Result[dict]
    def list_revisions(self, *, tenant_id, shift_report_id, section_key) -> Result[list[dict]]
```
`open_shift` is find-or-create on `(work_center, date, shift)` and creates all nine section rows as `empty`. Saving a submitted section writes a revision and sets `revised_after_submit`; submitting writes a revision and clears it. `declare_nothing` clears the section's rows. Shift status is recomputed after every change. A validated shift refuses edits (`NOT_EDITABLE`). Every state change writes `core.audit_log`.

- [ ] Tests (fixtures: reuse the `env` and `_open_of` patterns of `test_report_flow_integration.py`): open twice returns the same shift and nine empty sections; save runs then get returns them with server ids; re-saving keeps ids and does not delete waste lines pointing at kept runs; removing a run keeps its waste line unassigned; submit an empty draft -> `EMPTY_SECTION`; nothing-to-report then submit-all -> shift `submitted`; edit after submit -> revision 2 + `revised_after_submit`; resubmitting a returned section clears the flag and the return reason; validated shift -> `NOT_EDITABLE`; waste category from the other report type refused; stop end before start refused; closed OF refused on a new run but allowed on an existing one; silo duplicate `(side, phase)` refused; other tenant's shift -> `NOT_FOUND`.
- [ ] Run red, implement, run green.

### Task 5: Permissions and endpoints

**Files:** Modify `backend/core/tenancy.py` (add `user_has_permission`, reuse it in `require_permission`), `backend/modules/production/module.json` (permissions, `ShiftReportService` in `provides_api`), `backend/modules/production/api/router.py` (endpoints); create `backend/core/test_user_has_permission_integration.py`.

Endpoints: `GET/POST /production/shift-reports`, `GET /production/shift-reports/{id}`, `PATCH .../{id}/header`, `PUT .../{id}/sections/{key}`, `POST .../sections/{key}/submit`, `POST .../sections/{key}/nothing-to-report`, `GET .../sections/{key}/revisions`. View endpoints need `production.shift.view`; writes need `production.shift.edit.<key>` (opening needs any edit permission).

- [ ] Test `user_has_permission` for a direct grant, a role grant, and none. Run red, implement, green.
- [ ] Import the router module and list its routes to confirm the endpoints register (`python -c "from modules.production.api.router import router; print([r.path for r in router.routes if 'shift-reports' in r.path])"`).
- [ ] Run `pytest modules/production modules/warehouse modules/qc core -q` and confirm all green.


## Outcome (2026-09-20)

Done. 25 service + 7 router + 3 permission + 24 domain + 19 schema tests; full production/warehouse/qc/core run: 802 passed, 1 pre-existing flaky test (`test_waste_types_integration.py::test_creating_and_updating_are_both_audited` orders two same-transaction audit rows by ULID; passes 9 of 10 runs, unrelated).

Deviations from the plan text: `httpx==0.28.1` added to `requirements-dev.txt` for the FastAPI test client; the router test was added (plan said permission-helper test plus a route listing).
