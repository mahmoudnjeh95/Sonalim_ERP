# Shift report lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add draft persistence (autosave + local backup + "unfinished" strip), a delete right for not-yet-submitted shifts, validator edits on submitted sections (reasoned, revision-tagged), and a day view listing every shift report for a date.

**Architecture:** Backend changes are additive to the existing `ShiftReportService`/`ShiftValidationService` pair: one new column, one new service method for delete, one for validator edit, and two new router endpoints, all reusing the section-save/revision machinery that already exists. Frontend changes are additive to the existing `frontend/src/features/production/shift/` module: `SectionCard` gains a debounce timer and a `localStorage` mirror, `ShiftReportTab` is restructured so a date shows a day list before it shows a single shift, and `ShiftValidationPanel`'s review dialog gains an edit mode per section.

**Tech Stack:** FastAPI + psycopg (raw SQL, no ORM) on the backend; React + TanStack Query + Tailwind on the frontend. No frontend test runner exists in this repo — frontend tasks verify with `npx tsc -b --force` plus a real-browser pass, matching the rest of this module's history.

**Spec:** `docs/superpowers/specs/2026-09-22-shift-report-lifecycle-design.md`

## Global Constraints

- Every new backend error code must be added to `_report_err_status` in `backend/modules/production/api/router.py` if it should map to 409; anything else defaults to 400 (existing behavior, do not change the default).
- Every new permission goes in `backend/modules/production/module.json`'s flat `permissions` array — no descriptions, no grouping, matches the existing eleven `production.shift.*` entries.
- Every new backend string the frontend can see funnels through `record_audit(...)` with an `action` name in the existing `shift_report.<verb>` style.
- Every new frontend string goes in `frontend/src/features/production/shift/shiftText.ts`'s `T` object as an `L(en, fr)` pair — never inline text in a component.
- Migrations are numbered sequentially in `backend/modules/production/migrations/`; the next free number is `0058` (`0057_production_team_rotation.sql` is the last one on disk).
- `shift_reports` already cascades to `shift_report_sections`, `shift_section_revisions`, `shift_runs`, `shift_packing_rows`, `shift_waste_lines`, `machine_stops` and `shift_energy` via `ON DELETE CASCADE` (migrations `0047`/`0048`) — do not add manual cleanup code for those tables.
- Backend tests for this module live beside the code, not in a separate `tests/` directory (e.g. `backend/modules/production/api/test_shift_report_service_integration.py`); every test runs inside the `db` fixture's rolled-back transaction.

## Review Focus

- Autosave must not spam error toasts once a section becomes uneditable mid-type (e.g. the shift is validated by someone else while a team member is still typing) — Task 7.
- A day-list "Nouveau" row must not appear for a line/shift combo the viewer holds no edit permission for — Task 9.
- Deleting a shift must stay refused once another actor has moved it to `submitted` or `validated`, even though the button was rendered before that happened — Task 6.
- A second validator's edit on the same section, after a first one, must freeze cleanly with strictly increasing, correctly tagged revisions rather than colliding — Task 5.
- The `localStorage` restore banner must never resurface a draft older than what the server already holds (e.g. after a save from another tab or device) — Task 7.

---

## Task 1: Migration — tag a validator's own edit on a revision

**Files:**
- Create: `backend/modules/production/migrations/0058_production_shift_delete_and_validator_edit.sql`

**Interfaces:**
- Produces: column `production.shift_section_revisions.edited_by_validator BOOLEAN NOT NULL DEFAULT FALSE`, read and written by Task 4/5.

- [ ] **Step 1: Write the migration**

```sql
-- Shift lifecycle: draft persistence, delete, validator edits, day view (2026-09-22).
--
-- Only one schema change: a validator's own fix to a submitted section is tagged apart
-- from the team's own edits, so revision history can say so without guessing from the
-- actor's current permissions (which may change later). Delete needs no new column:
-- shift_reports already cascades to every child table (0047, 0048), and a shift that is
-- 'open' or 'returned' never has a materialized legacy report or posted stock behind it.
ALTER TABLE production.shift_section_revisions
    ADD COLUMN IF NOT EXISTS edited_by_validator BOOLEAN NOT NULL DEFAULT FALSE;
```

- [ ] **Step 2: Apply it to the dev database and confirm it is idempotent**

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=backend .venv/Scripts/python.exe -m core.migrate` (or however this repo's migration runner is invoked — check `backend/core/migrate.py` / the project's usual command if this fails) twice in a row.
Expected: succeeds both times; `\d production.shift_section_revisions` in `psql` shows the new column.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/production/migrations/0058_production_shift_delete_and_validator_edit.sql
git commit -m "feat(production): add edited_by_validator to shift section revisions"
```

---

## Task 2: Backend — `delete_shift` service method

**Files:**
- Modify: `backend/modules/production/api/shift_report_service.py`
- Test: `backend/modules/production/api/test_shift_report_service_integration.py`

**Interfaces:**
- Consumes: `self._load_header(tenant_id, shift_report_id) -> dict | None` (existing), `record_audit(...)` (existing import).
- Produces: `ShiftReportService.delete_shift(*, tenant_id: str, actor_id: str, shift_report_id: str) -> Result[dict]`, returning `Ok({"deleted": True, "id": shift_report_id})` or `Err("NOT_FOUND", ...)` / `Err("DELETE_NOT_ALLOWED", ...)`. Consumed by Task 3's router endpoint.

- [ ] **Step 1: Write the failing tests**

Add to `backend/modules/production/api/test_shift_report_service_integration.py`, after the existing `# ---- opening ----` tests (anywhere before the `# ---- sections ----` heading, or at end of file if there is none):

```python
# ---- deleting ---------------------------------------------------------------


def test_deleting_an_open_shift_removes_it_and_its_sections(db, env):
    shift_id = _open(db, env)
    _save(db, env, shift_id, "energy", {"energy": {"fuel_quantity": 5}})
    deleted = _ok(ShiftReportService(db).delete_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id))
    assert deleted == {"deleted": True, "id": shift_id}
    assert isinstance(ShiftReportService(db).get_shift(tenant_id=TENANT, shift_report_id=shift_id), Err)
    remaining = db.execute(
        "SELECT count(*) FROM production.shift_report_sections WHERE shift_report_id = %s", (shift_id,)
    ).fetchone()[0]
    assert remaining == 0


def test_deleting_a_returned_shift_is_allowed(db, env):
    shift_id = _open(db, env)
    db.execute("UPDATE production.shift_reports SET status = 'returned' WHERE id = %s", (shift_id,))
    result = ShiftReportService(db).delete_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id)
    assert isinstance(result, Ok)


def test_a_submitted_or_validated_shift_cannot_be_deleted(db, env):
    shift_id = _open(db, env)
    for blocked_status in ("submitted", "validated"):
        db.execute("UPDATE production.shift_reports SET status = %s WHERE id = %s", (blocked_status, shift_id))
        result = ShiftReportService(db).delete_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id)
        assert isinstance(result, Err) and result.code == "DELETE_NOT_ALLOWED", blocked_status


def test_deleting_an_unknown_shift_is_not_found(db, env):
    result = ShiftReportService(db).delete_shift(tenant_id=TENANT, actor_id=env["actor"], shift_report_id="nope")
    assert isinstance(result, Err) and result.code == "NOT_FOUND"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_report_service_integration.py -k deleting -v`
Expected: 4 failures, each with `AttributeError: 'ShiftReportService' object has no attribute 'delete_shift'`.

- [ ] **Step 3: Implement `delete_shift`**

In `backend/modules/production/api/shift_report_service.py`, add this method to `ShiftReportService`, right after `update_header` (before the `# ---- sections ----` comment at line 238):

```python
    def delete_shift(self, *, tenant_id: str, actor_id: str, shift_report_id: str) -> Result[dict]:
        """Remove a shift report that was never fully submitted.

        Nothing has posted to stock while a shift is 'open' or 'returned' — validation is
        the only thing that posts, and a validated shift that was later reversed lands back
        on 'returned' with its stock already undone (`ShiftValidationService.reverse_shift`).
        So the row and everything under it can simply be removed; the schema cascades
        sections, revisions, runs, packing rows, waste, stops and energy (0047, 0048).
        """
        header = self._load_header(tenant_id, shift_report_id)
        if header is None:
            return Err("NOT_FOUND", f"shift report {shift_report_id} not found")
        if header["status"] not in ("open", "returned"):
            return Err("DELETE_NOT_ALLOWED", f"a shift that is {header['status']} cannot be deleted")
        self._connection.execute(
            "DELETE FROM production.shift_reports WHERE id = %s AND tenant_id = %s", (shift_report_id, tenant_id)
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="shift_report.deleted",
            entity_type="shift_report",
            entity_id=shift_report_id,
            payload={
                "work_center_id": header["work_center_id"],
                "report_date": header["report_date"],
                "shift": header["shift"],
                "status": header["status"],
            },
        )
        return Ok({"deleted": True, "id": shift_report_id})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_report_service_integration.py -v`
Expected: PASS (the whole file, not just the new tests — confirms nothing else broke).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/production/api/shift_report_service.py backend/modules/production/api/test_shift_report_service_integration.py
git commit -m "feat(production): let a shift report be deleted before it is fully submitted"
```

---

## Task 3: Backend — `DELETE /shift-reports/{id}` endpoint and permission

**Files:**
- Modify: `backend/modules/production/module.json`
- Modify: `backend/modules/production/api/router.py`
- Test: `backend/modules/production/api/test_shift_report_router_integration.py`

**Interfaces:**
- Consumes: `ShiftReportService.delete_shift(...)` (Task 2), `_shift_result(connection, result)` (existing helper at `router.py:2894`), `require_permission("production.shift.delete")`.
- Produces: `DELETE /production/shift-reports/{shift_report_id}` → `{"deleted": true, "id": "..."}` on success.

- [ ] **Step 1: Write the failing tests**

Add to `backend/modules/production/api/test_shift_report_router_integration.py`, after `test_the_header_is_editable_with_any_section_right` (before the `# ---- validating, rejecting, reversing --------------------------------------` heading):

```python
# ---- deleting ----------------------------------------------------------


def test_delete_needs_its_own_permission_and_only_works_before_submission(world):
    world["grant"]("production.shift.view", "production.shift.edit.energy")
    shift_id = _open(world)
    client = world["client"]

    forbidden = client.delete(f"/production/shift-reports/{shift_id}")
    assert forbidden.status_code == 403

    world["grant"]("production.shift.delete")
    world["db"].execute("UPDATE production.shift_reports SET status = 'submitted' WHERE id = %s", (shift_id,))
    blocked = client.delete(f"/production/shift-reports/{shift_id}")
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "DELETE_NOT_ALLOWED"

    world["db"].execute("UPDATE production.shift_reports SET status = 'open' WHERE id = %s", (shift_id,))
    ok = client.delete(f"/production/shift-reports/{shift_id}")
    assert ok.status_code == 200 and ok.json()["deleted"] is True
    assert client.get(f"/production/shift-reports/{shift_id}").status_code == 404


def test_deleting_an_unknown_shift_is_a_404(world):
    world["grant"]("production.shift.delete")
    response = world["client"].delete("/production/shift-reports/nope")
    assert response.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_report_router_integration.py -k delet -v`
Expected: FAIL — `405 Method Not Allowed` (no DELETE route yet) instead of 403/409/200.

- [ ] **Step 3: Add the permission**

In `backend/modules/production/module.json`, in the `permissions` array, change:

```json
    "production.shift.view",
    "production.shift.validate",
```

to:

```json
    "production.shift.view",
    "production.shift.validate",
    "production.shift.delete",
```

- [ ] **Step 4: Add `DELETE_NOT_ALLOWED` to the 409 mapping and add the route**

In `backend/modules/production/api/router.py`, in `_report_err_status` (starting at line 1841), add `"DELETE_NOT_ALLOWED"` to the tuple of codes that map to 409:

```python
        "EMPTY_SECTION",
        "DUPLICATE_ROW",
        "CHANGED_SINCE_OPENED",
        "OPEN_STOP",
        "NOTHING_TO_VALIDATE",
        "ALREADY_POSTED",
```

becomes:

```python
        "EMPTY_SECTION",
        "DUPLICATE_ROW",
        "CHANGED_SINCE_OPENED",
        "OPEN_STOP",
        "NOTHING_TO_VALIDATE",
        "ALREADY_POSTED",
        "DELETE_NOT_ALLOWED",
```

Then add the endpoint right after `list_shift_report_section_revisions` (after line 3013, before the `# --- validating a shift ---` comment):

```python
@router.delete("/shift-reports/{shift_report_id}")
def delete_shift_report(
    shift_report_id: str,
    tenant: TenantContext = Depends(require_permission("production.shift.delete")),
) -> dict:
    """Delete a shift report that was never fully submitted — while it is 'open' or 'returned'."""
    with get_connection() as connection:
        result = ShiftReportService(connection).delete_shift(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, shift_report_id=shift_report_id
        )
        return _shift_result(connection, result)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_report_router_integration.py -v`
Expected: PASS (whole file).

- [ ] **Step 6: Run the full production suite**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production modules/core -q`
Expected: all green, same count as before plus the new tests.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/production/module.json backend/modules/production/api/router.py backend/modules/production/api/test_shift_report_router_integration.py
git commit -m "feat(production): add the DELETE /shift-reports/{id} endpoint and its permission"
```

---

## Task 4: Backend — `edit_section_as_validator` service method

**Files:**
- Modify: `backend/modules/production/api/shift_report_service.py`
- Test: `backend/modules/production/api/test_shift_report_service_integration.py`
- Test: `backend/modules/production/api/test_shift_validation_integration.py`

**Interfaces:**
- Consumes: `self._editable_section(...)`, `self._freeze_revision(...)`, `save_section_rows(...)`, `custom_waste_categories(...)` (all existing, same as `save_section`).
- Produces: `ShiftReportService._freeze_revision(..., *, edited_by_validator: bool = False) -> int` (extended signature — existing callers unaffected by the default), `ShiftReportService.edit_section_as_validator(*, tenant_id, actor_id, shift_report_id, section_key, payload, reason) -> Result[dict]`, and `list_revisions(...)` results now carry `"edited_by_validator": bool`. Consumed by Task 5's router endpoint and Task 10's frontend.

- [ ] **Step 1: Write the failing tests**

Add to `backend/modules/production/api/test_shift_report_service_integration.py` (near the other section-editing tests, e.g. after the `save_section` tests — anywhere in the `# ---- sections ----` region is fine):

```python
def test_a_validator_edit_needs_a_reason_and_a_submitted_shift(db, env):
    shift_id = _open(db, env)
    _save(db, env, shift_id, "energy", {"energy": {"fuel_quantity": 5}})
    service = ShiftReportService(db)

    no_reason = service.edit_section_as_validator(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="energy",
        payload={"energy": {"fuel_quantity": 9}}, reason=" ",
    )
    assert isinstance(no_reason, Err) and no_reason.code == "MISSING_REASON"

    not_submitted = service.edit_section_as_validator(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="energy",
        payload={"energy": {"fuel_quantity": 9}}, reason="typo",
    )
    assert isinstance(not_submitted, Err) and not_submitted.code == "INVALID_TRANSITION"


def test_a_validator_edit_freezes_a_tagged_revision_and_keeps_the_section_submitted(db, env):
    shift_id = _open(db, env)
    _save(db, env, shift_id, "energy", {"energy": {"fuel_quantity": 5}})
    _ok(_submit(db, env, shift_id, "energy"))
    service = ShiftReportService(db)

    edited = _ok(
        service.edit_section_as_validator(
            tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="energy",
            payload={"energy": {"fuel_quantity": 9}}, reason="figure looked wrong",
        )
    )
    assert edited["status"] == "submitted"
    assert edited["revised_after_submit"] is True

    revisions = _ok(service.list_revisions(tenant_id=TENANT, shift_report_id=shift_id, section_key="energy"))
    assert revisions[0]["edited_by_validator"] is True
    assert revisions[0]["reason"] == "figure looked wrong"
    assert revisions[1]["edited_by_validator"] is False  # the original hand-in

    shift = _get(db, shift_id)
    assert _section(shift, "energy")["payload"]["energy"]["fuel_quantity"] == 9


def test_a_second_validator_edit_freezes_its_own_higher_tagged_revision(db, env):
    shift_id = _open(db, env)
    _save(db, env, shift_id, "energy", {"energy": {"fuel_quantity": 5}})
    _ok(_submit(db, env, shift_id, "energy"))
    service = ShiftReportService(db)
    _ok(
        service.edit_section_as_validator(
            tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="energy",
            payload={"energy": {"fuel_quantity": 9}}, reason="first fix",
        )
    )
    _ok(
        service.edit_section_as_validator(
            tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="energy",
            payload={"energy": {"fuel_quantity": 11}}, reason="second fix",
        )
    )
    revisions = _ok(service.list_revisions(tenant_id=TENANT, shift_report_id=shift_id, section_key="energy"))
    assert [r["revision"] for r in revisions] == [3, 2, 1]
    assert [r["edited_by_validator"] for r in revisions] == [True, True, False]
    assert revisions[0]["reason"] == "second fix"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_report_service_integration.py -k validator_edit -v`
Expected: 3 failures with `AttributeError: 'ShiftReportService' object has no attribute 'edit_section_as_validator'`.

- [ ] **Step 3: Extend `_freeze_revision` to accept the tag**

In `backend/modules/production/api/shift_report_service.py`, replace `_freeze_revision` (lines 269–289):

```python
    def _freeze_revision(
        self, tenant_id: str, actor_id: str, shift_report_id: str, section_key: str, reason: str | None
    ) -> int:
        """Snapshot the section as it stands now under the next revision number."""
        revision = self._connection.execute(
            "SELECT COALESCE(MAX(revision), 0) + 1 FROM production.shift_section_revisions "
            "WHERE shift_report_id = %s AND section_key = %s",
            (shift_report_id, section_key),
        ).fetchone()[0]
        snapshot = load_section(
            self._connection, tenant_id=tenant_id, shift_report_id=shift_report_id, section_key=section_key
        )
        self._connection.execute(
            """
            INSERT INTO production.shift_section_revisions
                (id, tenant_id, shift_report_id, section_key, revision, snapshot, reason, actor_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (str(ULID()), tenant_id, shift_report_id, section_key, revision, Jsonb(snapshot), reason, actor_id),
        )
        return revision
```

with:

```python
    def _freeze_revision(
        self,
        tenant_id: str,
        actor_id: str,
        shift_report_id: str,
        section_key: str,
        reason: str | None,
        *,
        edited_by_validator: bool = False,
    ) -> int:
        """Snapshot the section as it stands now under the next revision number."""
        revision = self._connection.execute(
            "SELECT COALESCE(MAX(revision), 0) + 1 FROM production.shift_section_revisions "
            "WHERE shift_report_id = %s AND section_key = %s",
            (shift_report_id, section_key),
        ).fetchone()[0]
        snapshot = load_section(
            self._connection, tenant_id=tenant_id, shift_report_id=shift_report_id, section_key=section_key
        )
        self._connection.execute(
            """
            INSERT INTO production.shift_section_revisions
                (id, tenant_id, shift_report_id, section_key, revision, snapshot, reason, actor_id, edited_by_validator)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(ULID()), tenant_id, shift_report_id, section_key, revision, Jsonb(snapshot), reason, actor_id,
                edited_by_validator,
            ),
        )
        return revision
```

- [ ] **Step 4: Make `list_revisions` return the tag**

Replace `list_revisions` (lines 141–158):

```python
    def list_revisions(self, *, tenant_id: str, shift_report_id: str, section_key: str) -> Result[list[dict]]:
        if self._load_header(tenant_id, shift_report_id) is None:
            return Err("NOT_FOUND", f"shift report {shift_report_id} not found")
        rows = self._connection.execute(
            """
            SELECT revision, snapshot, reason, actor_id, created_at
            FROM production.shift_section_revisions
            WHERE shift_report_id = %s AND tenant_id = %s AND section_key = %s
            ORDER BY revision DESC
            """,
            (shift_report_id, tenant_id, section_key),
        ).fetchall()
        return Ok(
            [
                {"revision": rev, "snapshot": snap, "reason": reason, "actor_id": actor, "created_at": _iso(at)}
                for rev, snap, reason, actor, at in rows
            ]
        )
```

with:

```python
    def list_revisions(self, *, tenant_id: str, shift_report_id: str, section_key: str) -> Result[list[dict]]:
        if self._load_header(tenant_id, shift_report_id) is None:
            return Err("NOT_FOUND", f"shift report {shift_report_id} not found")
        rows = self._connection.execute(
            """
            SELECT revision, snapshot, reason, actor_id, created_at, edited_by_validator
            FROM production.shift_section_revisions
            WHERE shift_report_id = %s AND tenant_id = %s AND section_key = %s
            ORDER BY revision DESC
            """,
            (shift_report_id, tenant_id, section_key),
        ).fetchall()
        return Ok(
            [
                {
                    "revision": rev, "snapshot": snap, "reason": reason, "actor_id": actor, "created_at": _iso(at),
                    "edited_by_validator": tagged,
                }
                for rev, snap, reason, actor, at, tagged in rows
            ]
        )
```

- [ ] **Step 5: Add `edit_section_as_validator`**

Add this method right after `save_section` (after line 368, before `submit_section`):

```python
    def edit_section_as_validator(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        shift_report_id: str,
        section_key: str,
        payload: dict,
        reason: str,
    ) -> Result[dict]:
        """A validator's own fix to a section awaiting their approval.

        Unlike the team's save, this never changes section status (it stays 'submitted')
        and always freezes a reasoned, tagged revision — the team's own edit-after-submit
        path (`save_section`) already covers every other status the state machine allows.
        """
        if not (reason or "").strip():
            return Err("MISSING_REASON", "a validator's edit must record why")
        found = self._editable_section(tenant_id, shift_report_id, section_key)
        if isinstance(found, Err):
            return found
        header, _ = found.value
        if header["status"] != "submitted":
            return Err("INVALID_TRANSITION", f"a shift that is {header['status']} has nothing for a validator to fix")

        saved = save_section_rows(
            self._connection,
            tenant_id=tenant_id,
            shift_report_id=shift_report_id,
            section_key=section_key,
            payload=payload,
            custom_waste_categories={
                report_type: custom_waste_categories(self._connection, tenant_id=tenant_id, report_type=report_type)
                for report_type in ("daily", "conditionnement")
            },
        )
        if isinstance(saved, Err):
            return saved

        revision = self._freeze_revision(
            tenant_id, actor_id, shift_report_id, section_key, reason.strip(), edited_by_validator=True
        )
        self._connection.execute(
            """
            UPDATE production.shift_report_sections
            SET revision = %s, revised_after_submit = TRUE, updated_at = NOW()
            WHERE shift_report_id = %s AND tenant_id = %s AND section_key = %s
            """,
            (revision, shift_report_id, tenant_id, section_key),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="shift_report.section_edited_by_validator",
            entity_type="shift_report",
            entity_id=shift_report_id,
            payload={"section": section_key, "revision": revision, "reason": reason.strip()},
        )
        return Ok(self._section_result(tenant_id, shift_report_id, section_key))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_report_service_integration.py -v`
Expected: PASS (whole file — confirms the `_freeze_revision`/`list_revisions` signature changes did not break the existing revision tests).

- [ ] **Step 7: Write and run the CHANGED_SINCE_OPENED interaction test**

Add to `backend/modules/production/api/test_shift_validation_integration.py`, after `_shift` (around line 140, before the first `def test_...`):

```python
def test_a_validator_edit_moves_the_revision_so_stale_seen_revisions_are_refused(db, env):
    shift_id = _submitted_shift(db, env)
    stale_seen = {s["key"]: s["revision"] for s in _shift(db, shift_id)["sections"]}

    _ok(
        ShiftReportService(db).edit_section_as_validator(
            tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="energy",
            payload={"energy": {"fuel_quantity": 12}}, reason="fuel figure was wrong",
        )
    )

    refused = _validate(db, env, shift_id, seen_revisions=stale_seen)
    assert isinstance(refused, Err) and refused.code == "CHANGED_SINCE_OPENED"

    fresh_seen = {s["key"]: s["revision"] for s in _shift(db, shift_id)["sections"]}
    assert isinstance(_validate(db, env, shift_id, seen_revisions=fresh_seen), Ok)
```

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_validation_integration.py -v`
Expected: PASS (whole file).

- [ ] **Step 8: Commit**

```bash
git add backend/modules/production/api/shift_report_service.py backend/modules/production/api/test_shift_report_service_integration.py backend/modules/production/api/test_shift_validation_integration.py
git commit -m "feat(production): let a validator edit a submitted section with a tagged, reasoned revision"
```

---

## Task 5: Backend — validator-edit router endpoint

**Files:**
- Modify: `backend/modules/production/api/router.py`
- Test: `backend/modules/production/api/test_shift_report_router_integration.py`

**Interfaces:**
- Consumes: `ShiftReportService.edit_section_as_validator(...)` (Task 4), `require_permission("production.shift.validate")`.
- Produces: `PUT /production/shift-reports/{shift_report_id}/sections/{section_key}/validator-edit` → the section's state (same shape as the team's save endpoint).

- [ ] **Step 1: Write the failing test**

Add to `backend/modules/production/api/test_shift_report_router_integration.py`, after the delete tests from Task 3:

```python
# ---- validator edit ------------------------------------------------------


def test_validator_edit_needs_the_validate_right_a_reason_and_a_submitted_shift(world):
    world["grant"]("production.shift.view", "production.shift.edit.energy")
    shift_id = _open(world)
    client = world["client"]
    client.put(f"/production/shift-reports/{shift_id}/sections/energy", json={"payload": {"energy": {"fuel_quantity": 5}}})
    client.post(f"/production/shift-reports/{shift_id}/sections/energy/submit")

    # Section-edit permission alone is not enough: it must be the validate right.
    forbidden = client.put(
        f"/production/shift-reports/{shift_id}/sections/energy/validator-edit",
        json={"payload": {"energy": {"fuel_quantity": 9}}, "reason": "typo"},
    )
    assert forbidden.status_code == 403

    world["grant"]("production.shift.validate")
    no_reason = client.put(
        f"/production/shift-reports/{shift_id}/sections/energy/validator-edit",
        json={"payload": {"energy": {"fuel_quantity": 9}}, "reason": " "},
    )
    assert no_reason.status_code == 400 and no_reason.json()["detail"]["code"] == "MISSING_REASON"

    edited = client.put(
        f"/production/shift-reports/{shift_id}/sections/energy/validator-edit",
        json={"payload": {"energy": {"fuel_quantity": 9}}, "reason": "figure looked wrong"},
    )
    assert edited.status_code == 200 and edited.json()["status"] == "submitted"
    revisions = client.get(f"/production/shift-reports/{shift_id}/sections/energy/revisions").json()
    assert revisions[0]["edited_by_validator"] is True


def test_validator_editing_an_unknown_shift_is_a_404(world):
    world["grant"]("production.shift.validate")
    response = world["client"].put(
        "/production/shift-reports/nope/sections/energy/validator-edit",
        json={"payload": {}, "reason": "x"},
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_report_router_integration.py -k validator_edit -v`
Expected: FAIL — `404 Not Found` / `405 Method Not Allowed` (no route yet).

- [ ] **Step 3: Add the request model and the route**

In `backend/modules/production/api/router.py`, right after `class SaveShiftSectionRequest` (line 861), add:

```python
class ValidatorEditSectionRequest(BaseModel):
    payload: dict
    reason: str
```

Then add the endpoint right after `save_shift_report_section` (after line 2976, before `submit_shift_report_section`):

```python
@router.put("/shift-reports/{shift_report_id}/sections/{section_key}/validator-edit")
def edit_shift_report_section_as_validator(
    shift_report_id: str,
    section_key: str,
    body: ValidatorEditSectionRequest,
    tenant: TenantContext = Depends(require_permission("production.shift.validate")),
) -> dict:
    with get_connection() as connection:
        result = ShiftReportService(connection).edit_section_as_validator(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            shift_report_id=shift_report_id,
            section_key=section_key,
            payload=body.payload,
            reason=body.reason,
        )
        return _shift_result(connection, result)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_report_router_integration.py -v`
Expected: PASS (whole file).

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production modules/core modules/warehouse modules/maintenance modules/qc -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/production/api/router.py backend/modules/production/api/test_shift_report_router_integration.py
git commit -m "feat(production): expose the validator-edit endpoint for a submitted section"
```

---

## Task 6: Frontend — delete a shift report

**Files:**
- Modify: `frontend/src/features/production/shift/shiftApi.ts`
- Modify: `frontend/src/features/production/shift/shiftText.ts`
- Modify: `frontend/src/features/production/shift/ShiftReportTab.tsx`

**Interfaces:**
- Consumes: `DELETE /production/shift-reports/{id}` (Task 3).
- Produces: `deleteShiftReport(token: string, id: string): Promise<{ deleted: boolean; id: string }>`, exported from `shiftApi.ts`, reused by Task 9's day list.

- [ ] **Step 1: Add the API call**

In `frontend/src/features/production/shift/shiftApi.ts`, after `reverseShiftReport` (end of file), add:

```ts
export function deleteShiftReport(token: string, id: string) {
  return apiFetch<{ deleted: boolean; id: string }>(`${base}/${id}`, { method: "DELETE", token });
}
```

- [ ] **Step 2: Add the strings**

In `frontend/src/features/production/shift/shiftText.ts`, after `confirmNothing` (the last entry before the closing `} as const;`), add:

```ts
  deleteShift: L("Delete this report", "Supprimer ce rapport"),
  confirmDeleteShift: L(
    "This permanently deletes this shift report and everything in it. This cannot be undone. Continue?",
    "Cela supprime définitivement ce rapport de shift et tout ce qu'il contient. Action irréversible. Continuer ?",
  ),
  deleted: L("Shift report deleted", "Rapport de shift supprimé"),
```

- [ ] **Step 3: Add the delete button**

In `frontend/src/features/production/shift/ShiftReportTab.tsx`:

Add `Trash2` to the lucide-react import (line 5):

```tsx
import { CalendarDays, ClipboardList, Lock, RotateCcw, ShieldCheck, Trash2 } from "lucide-react";
```

Add `deleteShiftReport` to the `shiftApi` import (in the block starting line 22):

```tsx
import {
  SECTION_KEYS,
  SHIFT_REPORTS_QUERY_KEY,
  deleteShiftReport,
  getShiftReport,
  listShiftReports,
  openShiftReport,
  updateShiftHeader,
  type HeaderFields,
  type SectionKey,
  type ShiftReport,
} from "./shiftApi";
```

Add a `remove` mutation right after the `open` mutation (after line 123):

```tsx
  const remove = useMutation({
    mutationFn: () => deleteShiftReport(token, shift!.id),
    onSuccess: () => {
      toast.success(label(T.deleted));
      refresh();
    },
    onError: fail,
  });
```

In the filter `Card`, replace the line-and-shift/status row's last cell (lines 206–208):

```tsx
            <div className="flex items-end">
              {shift && <ShiftStatusBadge status={shift.status} />}
            </div>
```

with:

```tsx
            <div className="flex items-end gap-2">
              {shift && <ShiftStatusBadge status={shift.status} />}
              {shift && (shift.status === "open" || shift.status === "returned") && hasPermission("production.shift.delete") && (
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => {
                    if (window.confirm(label(T.confirmDeleteShift))) remove.mutate();
                  }}
                  disabled={remove.isPending}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  {label(T.deleteShift)}
                </Button>
              )}
            </div>
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc -b --force`
Expected: no errors.

- [ ] **Step 5: Verify in the browser**

Log in as the demo user (grant them `production.shift.delete` in the dev DB if they don't have it — same pattern as the other 11 shift permissions per project memory). Open a fresh, never-submitted shift, save something in one section, then click "Delete this report", confirm, and check it disappears from the screen and from `GET /production/shift-reports?report_date=...`. Then submit a shift fully and confirm the Delete button does not appear once it is `submitted`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/production/shift/shiftApi.ts frontend/src/features/production/shift/shiftText.ts frontend/src/features/production/shift/ShiftReportTab.tsx
git commit -m "feat(production): let a team member delete a shift report before it is submitted"
```

---

## Task 7: Frontend — autosave, local backup, and restore

**Files:**
- Modify: `frontend/src/features/production/shift/SectionCard.tsx`
- Modify: `frontend/src/features/production/shift/shiftText.ts`

**Interfaces:**
- Consumes: `saveShiftSection(token, shiftId, key, payload)` (existing).
- Produces: no new exports — this task is self-contained inside `SectionCard`.

- [ ] **Step 1: Add the strings**

In `frontend/src/features/production/shift/shiftText.ts`, add (near `unsaved`/`revised`, e.g. right after `sentBackBy`):

```ts
  savedAt: L("Saved at", "Enregistré à"),
  restoreFound: L(
    "Unsaved changes from an earlier visit were found on this device.",
    "Des modifications non enregistrées d'une visite précédente ont été retrouvées sur cet appareil.",
  ),
  restore: L("Restore them", "Les restaurer"),
  discard: L("Discard them", "Les ignorer"),
```

- [ ] **Step 2: Add the debounce, local backup, and restore banner**

In `frontend/src/features/production/shift/SectionCard.tsx`:

Change the React import (line 1) to add `useRef`:

```tsx
import { useEffect, useRef, useState } from "react";
```

Replace the body of `SectionCard` from the `draft`/`dirty` declarations (lines 64–65) through the end of the `nothing` mutation and `busy`/`declareNothing` block (lines 64–130) with:

```tsx
  const lotNumber = shift.default_lot_number ?? null;
  const storageKey = `sonalim-erp.shift-draft.${shift.id}.${def.key}`;
  const [draft, setDraft] = useState<Draft>(() => toDraft(def, state.payload, !locked, lotNumber));
  const [dirty, setDirty] = useState(false);
  const [autoSavedAt, setAutoSavedAt] = useState<number | null>(null);
  const [restoreAvailable, setRestoreAvailable] = useState(false);

  const draftRef = useRef(draft);
  draftRef.current = draft;
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;

  // What the server holds is the truth: when it changes (a save, a validator's return),
  // the grids follow it and the section is clean again.
  const serverKey = `${state.revision}|${state.status}|${locked}|${JSON.stringify(state.payload ?? {})}`;
  useEffect(() => {
    setDraft(toDraft(def, state.payload, !locked, lotNumber));
    setDirty(false);
    if (!locked) {
      try {
        setRestoreAvailable(window.localStorage.getItem(storageKey) !== null);
      } catch {
        setRestoreAvailable(false);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverKey]);

  // Naming the team gives the shift a lot: lines still untouched pick it up. Not an edit, so not unsaved.
  useEffect(() => {
    if (!locked) setDraft((current) => followLot(def, current, lotNumber));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lotNumber]);

  const filled = hasData(def, draft);
  const count = rowCount(def, draft);
  const submitted = state.status === "submitted";

  const edit = (partKey: string, value: GridRow[] | Row) => {
    setDraft((current) => {
      const next = { ...current, [partKey]: value };
      try {
        window.localStorage.setItem(storageKey, JSON.stringify(next));
      } catch {
        // private browsing / full quota: the debounced server save is still authoritative
      }
      return next;
    });
    setDirty(true);
    setRestoreAvailable(false);
  };

  const fail = (error: unknown) =>
    toast.error(label(T.failed), { description: error instanceof ApiError ? error.message : undefined });

  const save = useMutation({
    mutationFn: (opts?: { silent?: boolean }) => saveShiftSection(token, shift.id, def.key, toPayload(def, draft)),
    onSuccess: (_data, opts) => {
      try {
        window.localStorage.removeItem(storageKey);
      } catch {
        // best effort only
      }
      setAutoSavedAt(Date.now());
      if (!opts?.silent) toast.success(label(T.saved));
      onChanged();
    },
    onError: (error, opts) => {
      // A silent (autosave) failure still needs to reach the user — reuse one toast id so
      // it replaces itself instead of stacking while they keep typing into a stuck save.
      if (opts?.silent) {
        toast.error(label(T.failed), { id: `autosave-${shift.id}-${def.key}`, description: error instanceof ApiError ? error.message : undefined });
        return;
      }
      fail(error);
    },
  });

  // Debounced autosave: 1.5s after the last change, as long as the section is still editable.
  useEffect(() => {
    if (locked || !dirty) return;
    const timer = window.setTimeout(() => save.mutate({ silent: true }), 1500);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, locked, dirty]);

  // Flush on unmount (switching sections, shifts or tabs): the local copy is always current
  // (written on every edit above), this only tries the extra network round trip.
  useEffect(() => {
    return () => {
      if (dirtyRef.current) save.mutate({ silent: true });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = useMutation({
    mutationFn: async () => {
      if (dirty) await saveShiftSection(token, shift.id, def.key, toPayload(def, draft));
      return submitShiftSection(token, shift.id, def.key);
    },
    onSuccess: () => {
      try {
        window.localStorage.removeItem(storageKey);
      } catch {
        // best effort only
      }
      toast.success(label(T.handedIn));
      onChanged();
    },
    onError: (error) => {
      fail(error);
      // The save may have gone through before the hand-in was refused.
      onChanged();
    },
  });
  const nothing = useMutation({
    mutationFn: () => declareSectionEmpty(token, shift.id, def.key),
    onSuccess: () => {
      toast.success(label(T.markedEmpty));
      onChanged();
    },
    onError: fail,
  });
  const busy = save.isPending || submit.isPending || nothing.isPending;

  const declareNothing = () => {
    if (filled && !window.confirm(label(T.confirmNothing))) return;
    nothing.mutate();
  };

  const restoreDraft = () => {
    try {
      const raw = window.localStorage.getItem(storageKey);
      if (raw) {
        setDraft(JSON.parse(raw));
        setDirty(true);
      }
    } catch {
      // ignore — nothing to restore
    }
    setRestoreAvailable(false);
  };
  const discardRestore = () => {
    try {
      window.localStorage.removeItem(storageKey);
    } catch {
      // ignore
    }
    setRestoreAvailable(false);
  };
```

This keeps `filled`, `count`, `submitted`, `fail`, `busy`, `declareNothing` where they already were relative to the rest of the component — only the section between `draft`/`dirty` and `busy` changes shape. The `restoreAvailable` flag relies on `save`'s `onSuccess` always clearing `storageKey`, so a leftover entry can only mean "never reached the server" — never a stale copy of something already saved, which is what keeps the restore banner from resurfacing an outdated draft (Review Focus item 5).

- [ ] **Step 3: Show the indicator and the restore banner**

Replace the unsaved badge (line 160):

```tsx
          {dirty && !locked && <Badge variant="warning">{label(T.unsaved)}</Badge>}
```

with:

```tsx
          {dirty && !locked && <Badge variant="warning">{label(T.unsaved)}</Badge>}
          {!dirty && !locked && autoSavedAt && (
            <span className="text-xs text-muted-foreground">
              {label(T.savedAt)} {new Date(autoSavedAt).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
```

Then, in the expanded body, right after the `return_reason` alert block (after line 199, before `{def.parts.map(...)}`), add the restore banner:

```tsx
              {restoreAvailable && !locked && (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-warning/40 bg-warning-soft px-3 py-2 text-sm">
                  <span>{label(T.restoreFound)}</span>
                  <div className="flex gap-2">
                    <Button size="sm" variant="outline" onClick={discardRestore}>
                      {label(T.discard)}
                    </Button>
                    <Button size="sm" onClick={restoreDraft}>
                      {label(T.restore)}
                    </Button>
                  </div>
                </div>
              )}
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc -b --force`
Expected: no errors.

- [ ] **Step 5: Verify in the browser**

Open an editable section, type a row without clicking Save, and confirm the "Enregistré à HH:MM" text appears about 1.5s later without a toast, and that the row is still there after switching to another section and back. Then, with dev tools open, type again, and hard-reload the page before the debounce fires (or throttle the network to Offline right after typing) — reopen the section and confirm the restore banner appears and "Restore them" brings the row back. Also validate a shift from the Validation Center while a team member has an open, mid-type section on it in another tab, and confirm the autosave failure shows one toast, not a stack of them, as it keeps failing.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/production/shift/SectionCard.tsx frontend/src/features/production/shift/shiftText.ts
git commit -m "feat(production): autosave shift sections and back them up to localStorage"
```

---

## Task 8: Frontend — "My unfinished reports" strip

**Files:**
- Create: `frontend/src/features/production/shift/UnfinishedStrip.tsx`
- Modify: `frontend/src/features/production/shift/shiftText.ts`
- Modify: `frontend/src/features/production/shift/ShiftReportTab.tsx`

**Interfaces:**
- Consumes: `listShiftReports(token, { status })` (existing, called twice: `open` and `returned`).
- Produces: `UnfinishedStrip({ workCenterName, onPick }: { workCenterName: (id: string) => string; onPick: (shift: ShiftReport) => void })`, mounted by `ShiftReportTab` (this task) and left in place by Task 9's rework.

- [ ] **Step 1: Add the string**

In `frontend/src/features/production/shift/shiftText.ts`, add:

```ts
  unfinishedTitle: L("Continue where you left off", "Reprendre là où vous en étiez"),
```

- [ ] **Step 2: Create the component**

```tsx
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ListRestart } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { Badge } from "../../../components/ui/badge";
import { SHIFT_REPORTS_QUERY_KEY, listShiftReports, type ShiftReport } from "./shiftApi";
import { T, useLabel } from "./shiftText";

/**
 * Shifts nobody has finished: still 'open', or sent back by a validator. Shown across
 * every date so a team does not have to remember which day they left off on.
 */
export function UnfinishedStrip({
  workCenterName,
  onPick,
}: {
  workCenterName: (id: string) => string;
  onPick: (shift: ShiftReport) => void;
}) {
  const { session } = useAuth();
  const token = session!.token;
  const label = useLabel();

  const open = useQuery({
    queryKey: [...SHIFT_REPORTS_QUERY_KEY, "unfinished", "open"],
    queryFn: () => listShiftReports(token, { status: "open" }),
  });
  const returned = useQuery({
    queryKey: [...SHIFT_REPORTS_QUERY_KEY, "unfinished", "returned"],
    queryFn: () => listShiftReports(token, { status: "returned" }),
  });

  const shifts = useMemo(
    () =>
      [...(open.data ?? []), ...(returned.data ?? [])]
        .sort((a, b) => (a.report_date < b.report_date ? 1 : a.report_date > b.report_date ? -1 : 0))
        .slice(0, 8),
    [open.data, returned.data],
  );

  if (shifts.length === 0) return null;

  return (
    <div className="flex items-center gap-2 overflow-x-auto rounded-lg border border-border bg-muted/30 px-3 py-2">
      <ListRestart className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
      <span className="shrink-0 text-xs font-medium text-muted-foreground">{label(T.unfinishedTitle)}</span>
      <div className="flex items-center gap-2">
        {shifts.map((shift) => (
          <button
            key={shift.id}
            type="button"
            onClick={() => onPick(shift)}
            className="flex shrink-0 items-center gap-2 rounded-md border border-border bg-background px-2.5 py-1 text-xs hover:bg-muted"
          >
            <span className="font-medium">{workCenterName(shift.work_center_id)}</span>
            <span className="text-muted-foreground">
              {shift.report_date} · {shift.shift}
            </span>
            {shift.status === "returned" && <Badge variant="destructive">{label(T.shiftStatus.returned)}</Badge>}
          </button>
        ))}
      </div>
    </div>
  );
}
```

Save this as `frontend/src/features/production/shift/UnfinishedStrip.tsx`.

- [ ] **Step 3: Mount it in `ShiftReportTab`**

In `frontend/src/features/production/shift/ShiftReportTab.tsx`, add the import (with the other local component imports, near `import { ShiftRail } from "./ShiftRail";`):

```tsx
import { UnfinishedStrip } from "./UnfinishedStrip";
```

Add a `workCenterName` helper next to the existing `workCenters`/`windows` destructuring (after line 85):

```tsx
  const workCenterName = (id: string) => workCenters.data?.find((w) => w.id === id)?.name ?? "—";
```

Mount the strip right after the filter `Card` closes (after line 221, before the `{!linesReady && ...}` block):

```tsx
      <UnfinishedStrip
        workCenterName={workCenterName}
        onPick={(picked) => {
          setDate(picked.report_date);
          setWorkCenterId(picked.work_center_id);
          setShiftName(picked.shift);
        }}
      />
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc -b --force`
Expected: no errors.

- [ ] **Step 5: Verify in the browser**

With a mix of `open` and `returned` shifts in the dev DB (the seeded month already has some — see project memory on `seed_shift_month.py`), confirm the strip appears above the shift filters, shows both kinds, and clicking a chip jumps the date/line/shift pickers to that shift and loads it.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/production/shift/UnfinishedStrip.tsx frontend/src/features/production/shift/shiftText.ts frontend/src/features/production/shift/ShiftReportTab.tsx
git commit -m "feat(production): show unfinished shift reports as a strip on the shift screen"
```

---

## Task 9: Frontend — day view (every report for a date)

**Files:**
- Create: `frontend/src/features/production/shift/ShiftDayList.tsx`
- Modify: `frontend/src/features/production/shift/shiftText.ts`
- Modify: `frontend/src/features/production/shift/ShiftReportTab.tsx`

**Interfaces:**
- Consumes: `listShiftReports(token, { report_date })` (existing, `work_center_id` omitted — already returns every line for that tenant).
- Produces: `ShiftDayList({ date, workCenters, windows, currentShiftName, onOpen })`, rendered by `ShiftReportTab` in place of the old auto-narrowed single-shift lookup whenever nothing is drilled into yet.

- [ ] **Step 1: Add the strings**

In `frontend/src/features/production/shift/shiftText.ts`, add:

```ts
  lastTouched: L("Last touched by", "Dernière modification par"),
  noReportYet: L("Not started yet", "Pas encore commencé"),
  continueShift: L("Current shift", "Shift en cours"),
  newShift: L("New", "Nouveau"),
  backToDay: L("Back to the day", "Retour à la journée"),
```

- [ ] **Step 2: Create the day list**

```tsx
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { currentLocale } from "../../../lib/i18n";
import { listUserDirectory, userDisplayName } from "../../../lib/usersApi";
import { cn } from "../../../lib/utils";
import { Badge } from "../../../components/ui/badge";
import { SECTIONS } from "./sectionConfig";
import { SECTION_KEYS, SHIFT_REPORTS_QUERY_KEY, listShiftReports, type ShiftReport } from "./shiftApi";
import { T, useLabel } from "./shiftText";
import { AppLoader } from "../../../components/patterns/AppLoader";

const DONE = new Set(["submitted", "nothing_to_report"]);

interface Combo {
  workCenterId: string;
  workCenterName: string;
  shiftName: string;
  shift: ShiftReport | null;
}

/** One row per line-and-shift for a date, across every line — what the paper folder for that day would show. */
export function ShiftDayList({
  date,
  workCenters,
  windows,
  currentShiftName,
  onOpen,
}: {
  date: string;
  workCenters: { id: string; name: string }[];
  windows: { shift: string }[];
  /** The shift the plant clock is in right now, or "" when today is not the date shown. */
  currentShiftName: string;
  onOpen: (workCenterId: string, shiftName: string) => void;
}) {
  const { session, hasPermission } = useAuth();
  const token = session!.token;
  const label = useLabel();
  const canCreate = SECTION_KEYS.some((k) => hasPermission(`production.shift.edit.${k}`));

  const day = useQuery({
    queryKey: [...SHIFT_REPORTS_QUERY_KEY, "day", date],
    queryFn: () => listShiftReports(token, { report_date: date }),
  });
  const users = useQuery({ queryKey: ["core", "user-directory"], queryFn: () => listUserDirectory(token) });
  const who = (id: string | null) => {
    const user = users.data?.find((u) => u.id === id);
    return user ? userDisplayName(user) : null;
  };

  const combos = useMemo<Combo[]>(() => {
    const byLineShift = new Map((day.data ?? []).map((s) => [`${s.work_center_id}|${s.shift.trim().toLowerCase()}`, s]));
    const out: Combo[] = [];
    for (const wc of workCenters) {
      for (const w of windows) {
        const shift = byLineShift.get(`${wc.id}|${w.shift.trim().toLowerCase()}`) ?? null;
        if (!shift && !canCreate) continue; // nothing to see and nothing this viewer could create
        out.push({ workCenterId: wc.id, workCenterName: wc.name, shiftName: w.shift, shift });
      }
    }
    return out;
  }, [day.data, workCenters, windows, canCreate]);

  if (day.isLoading) return <AppLoader label={label(T.loading)} className="py-8" />;

  return (
    <div className="space-y-2">
      {combos.map((combo) => {
        const isCurrent = combo.shiftName.trim().toLowerCase() === currentShiftName.trim().toLowerCase();
        const total = SECTIONS.length;
        const done = combo.shift ? combo.shift.sections.filter((s) => DONE.has(s.status)).length : 0;
        const lastTouched = combo.shift
          ? [...combo.shift.sections]
              .filter((s) => s.submitted_at)
              .sort((a, b) => (a.submitted_at! < b.submitted_at! ? 1 : -1))[0]
          : undefined;
        return (
          <button
            key={`${combo.workCenterId}|${combo.shiftName}`}
            type="button"
            onClick={() => onOpen(combo.workCenterId, combo.shiftName)}
            className={cn(
              "flex w-full flex-wrap items-center gap-3 rounded-lg border bg-background px-4 py-3 text-left transition-colors hover:bg-muted",
              isCurrent ? "border-primary/50 ring-1 ring-primary/30" : "border-border",
            )}
          >
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">
                {combo.workCenterName} — {combo.shiftName}
              </p>
              <p className="text-xs text-muted-foreground">
                {combo.shift
                  ? lastTouched
                    ? `${label(T.lastTouched)} ${who(lastTouched.submitted_by) ?? "—"}, ${new Date(lastTouched.submitted_at!).toLocaleString(currentLocale(), { dateStyle: "medium", timeStyle: "short" })}`
                    : label(T.status.empty)
                  : label(T.noReportYet)}
              </p>
            </div>
            {combo.shift ? (
              <>
                <span className="text-xs tabular-nums text-muted-foreground">
                  {done}/{total}
                </span>
                <Badge
                  variant={
                    combo.shift.status === "validated"
                      ? "success"
                      : combo.shift.status === "returned"
                        ? "destructive"
                        : combo.shift.status === "submitted"
                          ? "primary"
                          : "warning"
                  }
                  dot
                >
                  {label(T.shiftStatus[combo.shift.status])}
                </Badge>
                {isCurrent && <Badge variant="primary">{label(T.continueShift)}</Badge>}
              </>
            ) : (
              <Badge variant="outline" className="gap-1">
                <Plus className="h-3 w-3" />
                {label(T.newShift)}
              </Badge>
            )}
          </button>
        );
      })}
    </div>
  );
}
```

Save this as `frontend/src/features/production/shift/ShiftDayList.tsx`.

- [ ] **Step 3: Rework `ShiftReportTab` to show the day list before a single shift**

In `frontend/src/features/production/shift/ShiftReportTab.tsx`:

Add the import:

```tsx
import { ShiftDayList } from "./ShiftDayList";
```

Remove the now-unused `Select` import (line 15) — the line/shift pickers it drove are being replaced by the day list.

Replace the state and derived values from `const [params] = useSearchParams();` through the two default-picking `useEffect`s (lines 76–95) with:

```tsx
  // A link from an OF page names the line, date and shift to open directly, bypassing the day list.
  const [params] = useSearchParams();
  const [date, setDate] = useState(() => params.get("date") || todayIso());
  const [selected, setSelected] = useState<{ workCenterId: string; shiftName: string } | null>(() => {
    const line = params.get("line");
    const shiftParam = params.get("shift");
    return line && shiftParam ? { workCenterId: line, shiftName: shiftParam } : null;
  });
  const [openKeys, setOpenKeys] = useState<Set<SectionKey>>(new Set());

  // ---- reference data -------------------------------------------------------
  const reference = useShiftReferenceData(canView);
  const workCenters = { data: reference.workCenters, isLoading: reference.workCentersLoading };
  const windows = reference.windows;
  const workCenterName = (id: string) => workCenters.data?.find((w) => w.id === id)?.name ?? "—";
  const clockShiftName = useMemo(() => currentShift(windows), [windows]);
```

Note: `setWorkCenterId`/`setShiftName`/`workCenterId`/`shiftName` no longer exist as separate state — every remaining use in this file becomes `selected?.workCenterId` / `selected?.shiftName` (or `selected!.` where a `selected` guard already applies), as covered below. `UnfinishedStrip`'s `onPick` (Task 8) also needs its three-setter body replaced.

Replace the whole block from `const found = useQuery(...)` through the end of the `remove` mutation that Task 6 added right after `open` — i.e. everything from `// ---- the drilled-into shift, if any ----` down to `remove`'s closing `});` — with:

```tsx
  // ---- the drilled-into shift, if any ---------------------------------------
  const found = useQuery({
    queryKey: [...SHIFT_REPORTS_QUERY_KEY, "find", date, selected?.workCenterId],
    queryFn: () => listShiftReports(token, { report_date: date, work_center_id: selected!.workCenterId }),
    enabled: canView && !!selected,
  });
  const existing = found.data?.find((s) => s.shift.trim().toLowerCase() === selected?.shiftName.trim().toLowerCase());
  const detail = useQuery({
    queryKey: [...SHIFT_REPORTS_QUERY_KEY, "one", existing?.id],
    queryFn: () => getShiftReport(token, existing!.id),
    enabled: canView && !!existing,
  });
  const shift = detail.data;

  const refresh = () => queryClient.invalidateQueries({ queryKey: SHIFT_REPORTS_QUERY_KEY });

  const fail = (error: unknown) =>
    toast.error(label(T.failed), { description: error instanceof ApiError ? error.message : undefined });

  const open = useMutation({
    mutationFn: () => openShiftReport(token, { work_center_id: selected!.workCenterId, report_date: date, shift: selected!.shiftName }),
    onSuccess: () => {
      toast.success(label(T.opened));
      refresh();
    },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: () => deleteShiftReport(token, shift!.id),
    onSuccess: () => {
      toast.success(label(T.deleted));
      setSelected(null);
      refresh();
    },
    onError: fail,
  });
```

(`remove` moves up from Task 6's placement — this replaces it, and now also clears `selected` on success so the screen drops back to the day list.)

Replace the filter `Card`'s whole contents (as they stand after Task 6's delete button) with:

```tsx
      <Card>
        <CardContent className="space-y-4 py-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <FieldLabel htmlFor="shift-date" className="text-xs text-muted-foreground">
                {label(T.date)}
              </FieldLabel>
              <Input
                id="shift-date"
                type="date"
                value={date}
                onChange={(e) => {
                  setDate(e.target.value || todayIso());
                  setSelected(null);
                }}
              />
            </div>
            {selected && (
              <Button size="sm" variant="outline" onClick={() => setSelected(null)}>
                <CalendarDays className="h-3.5 w-3.5" />
                {label(T.backToDay)}
              </Button>
            )}
            {shift && <ShiftStatusBadge status={shift.status} />}
            {shift && (shift.status === "open" || shift.status === "returned") && hasPermission("production.shift.delete") && (
              <Button
                size="sm"
                variant="destructive"
                onClick={() => {
                  if (window.confirm(label(T.confirmDeleteShift))) remove.mutate();
                }}
                disabled={remove.isPending}
              >
                <Trash2 className="h-3.5 w-3.5" />
                {label(T.deleteShift)}
              </Button>
            )}
          </div>

          {shift && (
            <HeaderNames
              key={shift.id}
              shift={shift}
              locked={shift.status === "validated" || !SECTION_KEYS.some((k) => hasPermission(`production.shift.edit.${k}`))}
              onSaved={refresh}
              onError={fail}
            />
          )}
        </CardContent>
      </Card>

      <UnfinishedStrip
        workCenterName={workCenterName}
        onPick={(picked) => {
          setDate(picked.report_date);
          setSelected({ workCenterId: picked.work_center_id, shiftName: picked.shift });
        }}
      />
```

Replace the "no lines" block and the old found/not-found blocks that followed the filter `Card` with:

```tsx
      {!linesReady && !workCenters.isLoading && (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">{label(T.noLines)}</CardContent>
        </Card>
      )}

      {linesReady && !selected && (
        <ShiftDayList
          date={date}
          workCenters={workCenters.data ?? []}
          windows={windows}
          currentShiftName={date === todayIso() ? clockShiftName : ""}
          onOpen={(workCenterId, shiftName) => setSelected({ workCenterId, shiftName })}
        />
      )}

      {linesReady && selected && (found.isLoading || (existing && detail.isLoading)) && (
        <AppLoader label={label(T.loading)} className="py-8" />
      )}

      {linesReady && selected && !found.isLoading && !existing && (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
            <CalendarDays className="h-8 w-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">{label(T.openHint)}</p>
            <Button
              onClick={() => open.mutate()}
              disabled={open.isPending || !SECTION_KEYS.some((k) => hasPermission(`production.shift.edit.${k}`))}
            >
              {label(T.openShift)}
            </Button>
          </CardContent>
        </Card>
      )}
```

The rest of the component (the `shift && (...)` section-list block, `ShiftStatusBadge`, `HeaderNames`, `ShiftStatusBar`) is unchanged — `HeaderNames`, `SECTIONS.map`, etc. never referenced `workCenterId`/`shiftName` directly, only `shift`, so nothing else needs editing. The `options` memo (`reference.buildOptions(shift, workCenterId)`) becomes `reference.buildOptions(shift, selected?.workCenterId ?? "")`.

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc -b --force`
Expected: no errors — this is the step that will surface any leftover reference to the removed `workCenterId`/`shiftName` state.

- [ ] **Step 5: Verify in the browser**

Open the shift screen on today's date: confirm it shows the day list (not a single shift), with the current line/shift combo(s) highlighted. Click a row with an existing shift and confirm it opens the familiar single-shift editor with a working "Back to the day" button. Click a "Nouveau" row for a combo with no report and confirm it leads to the existing "Open this shift" prompt. Pick an older date from the seeded month and confirm it lists that day's shifts (several lines, mixed statuses) with no highlighted row. Log in as a user with no edit permission on any section and confirm "Nouveau" rows disappear for combos with no report, while existing reports still show. Follow a link from an OF page (`?date=&line=&shift=`) and confirm it still drills straight into that shift.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/production/shift/ShiftDayList.tsx frontend/src/features/production/shift/shiftText.ts frontend/src/features/production/shift/ShiftReportTab.tsx
git commit -m "feat(production): show a day's shift reports as a list before drilling into one"
```

---

## Task 10: Frontend — validator edit in the review dialog

**Files:**
- Modify: `frontend/src/features/production/shift/shiftApi.ts`
- Modify: `frontend/src/features/production/shift/shiftText.ts`
- Modify: `frontend/src/features/production/shift/RevisionHistory.tsx`
- Modify: `frontend/src/features/production/shift/ShiftValidationPanel.tsx`

**Interfaces:**
- Consumes: `PUT /shift-reports/{id}/sections/{key}/validator-edit` (Task 5).
- Produces: `editSectionAsValidator(token, id, key, payload, reason): Promise<SectionState>`, exported from `shiftApi.ts`.

- [ ] **Step 1: Add the API call and extend `SectionRevision`**

In `frontend/src/features/production/shift/shiftApi.ts`, add `edited_by_validator` to `SectionRevision` (in the interface, after `created_at: string;`):

```ts
export interface SectionRevision {
  revision: number;
  snapshot: SectionPayload;
  reason: string | null;
  actor_id: string | null;
  created_at: string;
  edited_by_validator: boolean;
}
```

Add the call after `listSectionRevisions`:

```ts
export function editSectionAsValidator(token: string, id: string, key: SectionKey, payload: SectionPayload, reason: string) {
  return apiFetch<SectionState>(`${base}/${id}/sections/${key}/validator-edit`, {
    method: "PUT",
    body: { payload, reason },
    token,
  });
}
```

- [ ] **Step 2: Add the strings**

In `frontend/src/features/production/shift/shiftText.ts`, add:

```ts
  validatorEditStart: L("Edit", "Modifier"),
  validatorEditSave: L("Save edit", "Enregistrer la modification"),
  validatorEditSaved: L("Section updated", "Section mise à jour"),
  validatorEditReasonPlaceholder: L("Why are you changing this?", "Pourquoi modifiez-vous ceci ?"),
  cancel: L("Cancel", "Annuler"),
  validatorEditBadge: L("Edited by the validator", "Modifié par le validateur"),
```

- [ ] **Step 3: Badge tagged revisions in the history dialog**

In `frontend/src/features/production/shift/RevisionHistory.tsx`, in the revision list item's button (around line 104), replace:

```tsx
                  {revision.reason && <span className="min-w-0 flex-1 truncate text-muted-foreground">“{revision.reason}”</span>}
```

with:

```tsx
                  {revision.edited_by_validator && <Badge variant="warning">{label(T.validatorEditBadge)}</Badge>}
                  {revision.reason && <span className="min-w-0 flex-1 truncate text-muted-foreground">“{revision.reason}”</span>}
```

- [ ] **Step 4: Make `ReviewSection` editable**

In `frontend/src/features/production/shift/ShiftValidationPanel.tsx`:

Add to the imports: `useEffect` and `useState` are already imported from `react`; add `Pencil` to the lucide-react import (line 3):

```tsx
import { CircleCheck, ClipboardCheck, Pencil, RotateCcw } from "lucide-react";
```

Add `editSectionAsValidator` to the `shiftApi` import (line 18) and `toPayload` plus `type Draft` to the `shiftModel`/`ShiftGrid` imports:

```tsx
import type { GridRow, OptionMap } from "./ShiftGrid";
...
import { toDraft, toPayload, type Draft } from "./shiftModel";
import {
  SHIFT_REPORTS_QUERY_KEY,
  editSectionAsValidator,
  getShiftReport,
  listShiftReports,
  rejectShiftSections,
  validateShiftReport,
  type Row,
  type SectionKey,
  type SectionState,
} from "./shiftApi";
```

Add a `refreshReview` helper in `ShiftReviewDialog`, right after `const done = ...` (after line 145):

```tsx
  const refreshReview = () => queryClient.invalidateQueries({ queryKey: SHIFT_REPORTS_QUERY_KEY });
```

Pass `shiftId` and `onEdited` to `ReviewSection` at its call site (lines 232–243):

```tsx
              return (
                <ReviewSection
                  key={def.key}
                  shiftId={shift.id}
                  def={def}
                  state={state}
                  options={options}
                  open={opened.has(def.key)}
                  onToggle={() => toggleOpen(def.key)}
                  ticked={ticked.has(def.key)}
                  onTick={() => toggleTick(def.key)}
                  onEdited={refreshReview}
                />
              );
```

Replace the whole `ReviewSection` function (lines 281–341) with:

```tsx
function ReviewSection({
  shiftId,
  def,
  state,
  options,
  open,
  onToggle,
  ticked,
  onTick,
  onEdited,
}: {
  shiftId: string;
  def: SectionDef;
  state: SectionState;
  options: OptionMap;
  open: boolean;
  onToggle: () => void;
  ticked: boolean;
  onTick: () => void;
  onEdited: () => void;
}) {
  const { session } = useAuth();
  const token = session!.token;
  const label = useLabel();
  const Icon = def.icon;
  const empty = state.status === "nothing_to_report";

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft>(() => toDraft(def, state.payload, true));
  const [reason, setReason] = useState("");

  useEffect(() => {
    setDraft(toDraft(def, state.payload, true));
    setEditing(false);
    setReason("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.revision]);

  const editRow = (partKey: string, value: GridRow[] | Row) => setDraft((current) => ({ ...current, [partKey]: value }));

  const fail = (error: unknown) =>
    toast.error(label(T.failed), { description: error instanceof ApiError ? error.message : undefined });

  const save = useMutation({
    mutationFn: () => editSectionAsValidator(token, shiftId, def.key, toPayload(def, draft), reason.trim()),
    onSuccess: () => {
      toast.success(label(T.validatorEditSaved));
      setEditing(false);
      onEdited();
    },
    onError: fail,
  });

  return (
    <section className={cn("overflow-hidden rounded-lg border", ticked ? "border-destructive/50" : "border-border")}>
      <div className="flex items-center gap-3 bg-muted/50 px-3 py-2">
        <label className="flex items-center gap-2 text-xs text-muted-foreground" title={label(T.tickToSendBack)}>
          <input type="checkbox" checked={ticked} onChange={onTick} className="h-4 w-4 accent-[#123B6D]" aria-label={`${label(T.tickToSendBack)}: ${label(def.title)}`} />
        </label>
        <button type="button" onClick={onToggle} aria-expanded={open} className="flex min-w-0 flex-1 items-center gap-3 text-left">
          <Icon className="h-4 w-4 shrink-0 text-primary" />
          <span className="min-w-0 flex-1 truncate text-sm font-medium">{label(def.title)}</span>
          {state.revised_after_submit && (
            <Badge variant="warning">
              {label(T.revisedNote)} ({label(T.revision).toLowerCase()} {state.revision})
            </Badge>
          )}
          <StatusNode status={state.status} size={18} />
        </button>
      </div>
      {open && (
        <div className="space-y-3 px-3 py-3">
          {empty && !editing && <p className="text-sm text-muted-foreground">{label(T.nothingSection)}</p>}
          {(!empty || editing) &&
            def.parts.map((part) => (
              <Part
                key={part.payloadKey}
                part={part}
                sectionKey={`review-${def.key}`}
                value={draft[part.payloadKey]}
                onChange={editing ? (value) => editRow(part.payloadKey, value) : () => undefined}
                options={options}
                disabled={!editing}
              />
            ))}
          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-2">
            {editing ? (
              <>
                <Input
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder={label(T.validatorEditReasonPlaceholder)}
                  aria-label={label(T.validatorEditReasonPlaceholder)}
                  className="max-w-xs"
                />
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setEditing(false);
                    setDraft(toDraft(def, state.payload, true));
                    setReason("");
                  }}
                  disabled={save.isPending}
                >
                  {label(T.cancel)}
                </Button>
                <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending || !reason.trim()}>
                  <Pencil className="h-3.5 w-3.5" />
                  {label(T.validatorEditSave)}
                </Button>
              </>
            ) : (
              <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
                <Pencil className="h-3.5 w-3.5" />
                {label(T.validatorEditStart)}
              </Button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npx tsc -b --force`
Expected: no errors.

- [ ] **Step 6: Verify in the browser**

As the demo user (holding `production.shift.validate`), open the Validation Center, review a submitted shift, click "Edit" on a section, change a value, try to save with an empty reason (button stays disabled), type a reason and save — confirm the section updates, the section stays "Handed in" (not reopened to the team), and "Approve shift" still succeeds afterward without a `CHANGED_SINCE_OPENED` error. Open the section's revision history and confirm the new revision shows the "Edited by the validator" badge and the reason. Then, in a second browser tab, save a team edit to a different section of the same shift while the first tab's dialog is still open, and confirm Approve in the first tab is refused with the existing "changed since" message (proving the exemption is scoped to the validator's own edit, not a blanket bypass).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/production/shift/shiftApi.ts frontend/src/features/production/shift/shiftText.ts frontend/src/features/production/shift/RevisionHistory.tsx frontend/src/features/production/shift/ShiftValidationPanel.tsx
git commit -m "feat(production): let a validator edit a submitted section from the review dialog"
```

---

## Final check

- [ ] Run the full backend suite once more: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules -q`
- [ ] Run `cd frontend && npx tsc -b --force` once more on the finished branch.
- [ ] Re-read the spec (`docs/superpowers/specs/2026-09-22-shift-report-lifecycle-design.md`) section by section against the ten tasks above and confirm nothing was dropped.
