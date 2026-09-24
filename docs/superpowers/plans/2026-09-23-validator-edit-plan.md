# Validator In-Place Edit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a validator with `production.shift.validate` fix a mistake directly in a submitted shift's section, from the Validation Center, instead of always sending the whole section back to the team — tagged and auditable, and without breaking the existing `CHANGED_SINCE_OPENED` race guard.

**Architecture:** One new service method (`edit_section_as_validator`) reuses the existing `save_section_rows`/`_freeze_revision` machinery `ShiftReportService.save_section` already uses, adds an `edited_by_validator` flag to the revision it freezes, and is exposed on its own endpoint (not the team's save endpoint) so the two paths' gating stays independent. The Validation Center's review dialog becomes editable in place by reusing the existing `SectionCard`/`Part` components with a new save path.

**Tech Stack:** FastAPI + psycopg (backend, `backend/modules/production`), React + TanStack Query + TypeScript (frontend, `frontend/src/features/production/shift`).

**Spec:** `docs/superpowers/specs/2026-09-23-analytics-shift-rewrite-design.md` (Part A), which implements `docs/superpowers/specs/2026-09-22-shift-report-lifecycle-design.md` §3 exactly, scoped to that section only.

## Global Constraints

- `reason` is mandatory for a validator edit; empty/whitespace is refused. Reuse the existing `MISSING_REASON` error code (the codebase's established name for this case — `reject_sections` already uses it; do not invent `REASON_REQUIRED`).
- The validator-edit path requires `production.shift.validate` and shift status `submitted` — it never changes section or shift status.
- Every validator edit is tagged `edited_by_validator = TRUE` on the revision it freezes, recorded at write time (never inferred later from the actor's current permissions).
- No change to `validate_shift`'s `CHANGED_SINCE_OPENED` guard itself — the fix is entirely in the frontend refreshing its `seen_revisions` baseline after a successful validator edit.
- No change to the section state machine, `reject_sections`, or `reverse_shift`.
- Follow existing patterns exactly: `Result`/`Err`/`Ok`, `record_audit`, `_shift_result`, `TenantContext`/`require_permission`, TanStack Query mutation style already used in `SectionCard.tsx`.

## Review Focus

- A validator edit with no `reason` (empty string or whitespace-only) must be refused with `MISSING_REASON`, not silently accepted with a null reason — mirrors `reject_sections`' existing check exactly.
- A validator editing a section on a shift that is `validated` or `open`/`returned` (not `submitted`) must be refused with `INVALID_TRANSITION` — the endpoint must not silently no-op or succeed.
- Two validators (or a validator and a concurrent team edit) racing on the same shift: the validator's own edit must not trip `CHANGED_SINCE_OPENED` on their own subsequent Approve, but a genuine concurrent edit by someone else must still trip it — both directions need a test, not just the happy path.
- A user with `production.shift.validate` but attempting to hit the validator-edit endpoint on a section key that doesn't exist (typo, stale frontend) must get `INVALID_SECTION`, matching `_editable_section`'s existing behavior, not a 500.
- The revision-history dialog (`RevisionHistory.tsx`) must render the `edited_by_validator` badge on the correct revision (not on the most recent one by default, on the one row that actually carries the flag) once several revisions exist, including cases where a normal team revision follows a validator edit.

---

## Task 1: Migration — `edited_by_validator` column

**Files:**
- Create: `backend/modules/production/migrations/0058_production_shift_validator_edit.sql`

**Interfaces:**
- Produces: `production.shift_section_revisions.edited_by_validator BOOLEAN NOT NULL DEFAULT FALSE`, consumed by Task 2's service method and Task 5's query.

- [ ] **Step 1: Write the migration**

```sql
-- Validator in-place edit (shift-report-lifecycle spec §3): tags a revision as
-- written by the validator during review, not by the team. Recorded at write
-- time so history stays correct if permissions change afterwards.
ALTER TABLE production.shift_section_revisions
    ADD COLUMN IF NOT EXISTS edited_by_validator BOOLEAN NOT NULL DEFAULT FALSE;
```

- [ ] **Step 2: Apply the migration to the dev DB**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp .venv/Scripts/python.exe -m core.migrate` (use whatever the project's existing migration-runner invocation is — check `backend/core/migrate.py` or the project's documented migrate command if this exact invocation errors).

Expected: migration `0058` applies with no error; re-running is a no-op (`IF NOT EXISTS`).

- [ ] **Step 3: Commit**

```bash
git add backend/modules/production/migrations/0058_production_shift_validator_edit.sql
git commit -m "Add edited_by_validator column to shift_section_revisions"
```

---

## Task 2: `edit_section_as_validator` service method

**Files:**
- Modify: `backend/modules/production/api/shift_validation_service.py`
- Test: `backend/modules/production/api/test_shift_validation_integration.py`

**Interfaces:**
- Consumes: `ShiftReportService._editable_section` is section-team-only (checks `header["status"] != "validated"`, not `== "submitted"`), so this task does NOT reuse it — it writes its own status check. Reuses `save_section_rows(connection, *, tenant_id, shift_report_id, section_key, payload, custom_waste_categories)` from `modules.production.api.shift_sections` (same signature `shift_report_service.save_section` calls, see `shift_report_service.py:330-341`) and `custom_waste_categories` from `modules.production.api.production_report_service` (already imported in `shift_report_service.py` — copy the same two-key dict: `{"daily": custom_waste_categories(...), "conditionnement": custom_waste_categories(...)}`).
- Produces: `ShiftValidationService.edit_section_as_validator(*, tenant_id: str, actor_id: str, shift_report_id: str, section_key: str, payload: dict, reason: str) -> Result[dict]`, returning the same shape as `ShiftReportService._section_result` (a dict with `key`, `status`, `revision`, `revised_after_submit`, `submitted_by`, `submitted_at`, `return_reason`, `shift_status`), consumed by Task 3's endpoint.

- [ ] **Step 1: Write the failing test — happy path**

Add to `backend/modules/production/api/test_shift_validation_integration.py`, near the other validate tests:

```python
def test_validator_can_edit_a_submitted_section_with_a_reason(db, env):
    shift_id = _submitted_shift(db, env)
    of_id = _of(db, env)
    run_ids = [r["id"] for r in _shift(db, shift_id)["sections"][0]["payload"]["runs"]]

    edited = ShiftValidationService(db).edit_section_as_validator(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs",
        payload={"runs": [_run(env, of_id, semolina=1200)]}, reason="corrected the semoule quantity",
    )
    assert isinstance(edited, Ok), getattr(edited, "message", "")
    assert edited.value["status"] == "submitted"  # stays submitted, not draft
    assert edited.value["shift_status"] == "submitted"

    stored = _shift(db, shift_id)["sections"][0]["payload"]["runs"][0]
    assert float(stored["semolina_lines"][0]["quantity"]) == 1200

    history = _ok(ShiftReportService(db).list_revisions(tenant_id=TENANT, shift_report_id=shift_id, section_key="runs"))
    assert history[0]["reason"] == "corrected the semoule quantity"
    assert history[0]["edited_by_validator"] is True


def test_validator_edit_requires_a_reason(db, env):
    shift_id = _submitted_shift(db, env)
    of_id = _of(db, env)
    result = ShiftValidationService(db).edit_section_as_validator(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs",
        payload={"runs": [_run(env, of_id)]}, reason="   ",
    )
    assert isinstance(result, Err) and result.code == "MISSING_REASON"


def test_validator_edit_refused_when_shift_is_not_submitted(db, env):
    shift_id = _submitted_shift(db, env)
    _ok(_validate(db, env, shift_id))  # now 'validated'
    of_id = _of(db, env)
    result = ShiftValidationService(db).edit_section_as_validator(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs",
        payload={"runs": [_run(env, of_id)]}, reason="too late",
    )
    assert isinstance(result, Err) and result.code == "INVALID_TRANSITION"


def test_validator_edit_rejects_unknown_section(db, env):
    shift_id = _submitted_shift(db, env)
    result = ShiftValidationService(db).edit_section_as_validator(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="not_a_section",
        payload={}, reason="typo",
    )
    assert isinstance(result, Err) and result.code == "INVALID_SECTION"


def test_validator_edit_does_not_trip_changed_since_opened_on_own_edit(db, env):
    shift_id = _submitted_shift(db, env)
    seen = {s["key"]: s["revision"] for s in _shift(db, shift_id)["sections"]}
    of_id = _of(db, env)

    edited = ShiftValidationService(db).edit_section_as_validator(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs",
        payload={"runs": [_run(env, of_id, semolina=1100)]}, reason="fix",
    )
    assert isinstance(edited, Ok)

    # Stale baseline (what the reviewer's screen showed before their own edit) still fails, as expected --
    # this proves the guard is real. The frontend's job (not tested here) is to refresh seen_revisions
    # after a successful validator edit before the next Approve call.
    stale = _validate(db, env, shift_id, seen_revisions=seen)
    assert isinstance(stale, Err) and stale.code == "CHANGED_SINCE_OPENED"

    # A refreshed baseline (post-edit revisions) passes.
    refreshed = {s["key"]: s["revision"] for s in _shift(db, shift_id)["sections"]}
    ok = _validate(db, env, shift_id, seen_revisions=refreshed)
    assert isinstance(ok, Ok), getattr(ok, "message", "")


def test_validator_edit_by_someone_else_still_trips_changed_since_opened(db, env):
    """A genuine concurrent edit (team or another validator) after the reviewer opened
    the shift must still refuse validation -- only the *same* validator's own edit,
    refreshed into their own next call, is exempted."""
    shift_id = _submitted_shift(db, env)
    seen = {s["key"]: s["revision"] for s in _shift(db, shift_id)["sections"]}
    of_id = _of(db, env)
    edited = ShiftValidationService(db).edit_section_as_validator(
        tenant_id=TENANT, actor_id=env["actor"], shift_report_id=shift_id, section_key="runs",
        payload={"runs": [_run(env, of_id, semolina=1300)]}, reason="someone else's fix",
    )
    assert isinstance(edited, Ok)

    stale_result = _validate(db, env, shift_id, seen_revisions=seen)
    assert isinstance(stale_result, Err) and stale_result.code == "CHANGED_SINCE_OPENED"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_validation_integration.py -k validator_edit -v`
Expected: FAIL with `AttributeError: 'ShiftValidationService' object has no attribute 'edit_section_as_validator'`.

- [ ] **Step 3: Implement `edit_section_as_validator`**

In `backend/modules/production/api/shift_validation_service.py`, add the import and method:

```python
from modules.production.api.production_report_service import custom_waste_categories
from modules.production.api.shift_sections import SECTIONS, save_section_rows
```

(add these alongside the existing imports at the top of the file; `SECTIONS` is the dict of known section keys from `shift_sections.py`, already used by `ShiftReportService._editable_section` for its `INVALID_SECTION` check — reuse the same membership test here, `if section_key not in SECTIONS`).

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
        """A validator's own in-place fix to a submitted section, distinct from
        sending it back to the team (reject_sections) or the team's own save
        (ShiftReportService.save_section, which that service still gates by
        `status != 'validated'` -- this gate is deliberately narrower: only
        while the shift is `submitted`, mid-review).

        Always freezes a revision and tags it `edited_by_validator`, whatever
        the section's own dirty-tracking would otherwise decide -- a
        validator's edit is a correction worth a permanent record every time.
        """
        if section_key not in SECTIONS:
            return Err("INVALID_SECTION", f"unknown section {section_key!r}")
        if not (reason or "").strip():
            return Err("MISSING_REASON", "editing a section as validator must record why")

        status = self._locked_status(tenant_id, shift_report_id)
        if status is None:
            return Err("NOT_FOUND", f"shift report {shift_report_id} not found")
        if status != "submitted":
            return Err("INVALID_TRANSITION", f"a shift that is {status} cannot be edited by a validator")

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

        revision = self._freeze_revision(tenant_id, actor_id, shift_report_id, section_key, reason.strip())
        self._connection.execute(
            "UPDATE production.shift_section_revisions SET edited_by_validator = TRUE "
            "WHERE shift_report_id = %s AND section_key = %s AND revision = %s",
            (shift_report_id, section_key, revision),
        )
        self._connection.execute(
            "UPDATE production.shift_report_sections SET revision = %s, updated_at = NOW() "
            "WHERE shift_report_id = %s AND tenant_id = %s AND section_key = %s",
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
        return Ok(self._shifts._section_result(tenant_id, shift_report_id, section_key))
```

`_freeze_revision` is defined on `ShiftReportService` (`shift_report_service.py:266-287`), not on `ShiftValidationService`. `ShiftValidationService.__init__` already holds `self._shifts = ShiftReportService(connection)` — call `self._shifts._freeze_revision(...)` instead of `self._freeze_revision(...)` in the snippet above (this reuses `ShiftReportService`'s private helper across the two service classes in the same module the way `_section_result` already is below it; both are same-package internals, matching how `_shifts._section_result` and `_shifts.list_section_states` are already called from `ShiftValidationService` elsewhere in this file).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_validation_integration.py -k validator_edit -v`
Expected: all 6 new tests PASS.

- [ ] **Step 5: Run the full production suite**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production -v`
Expected: all pass, no regressions (baseline ~975+ per memory).

- [ ] **Step 6: Commit**

```bash
git add backend/modules/production/api/shift_validation_service.py backend/modules/production/api/test_shift_validation_integration.py
git commit -m "Add ShiftValidationService.edit_section_as_validator"
```

---

## Task 3: `edited_by_validator` on `list_revisions` + endpoint

**Files:**
- Modify: `backend/modules/production/api/shift_report_service.py` (wherever `list_revisions` selects/serializes revision rows)
- Modify: `backend/modules/production/api/router.py`
- Test: `backend/modules/production/api/test_shift_validation_integration.py` (Task 2's test already asserts `history[0]["edited_by_validator"] is True`, so this task makes that assertion pass)

**Interfaces:**
- Consumes: Task 2's `ShiftValidationService.edit_section_as_validator`.
- Produces: `list_revisions` dicts now include `"edited_by_validator": bool`; new endpoint `PUT /production/shift-reports/{shift_report_id}/sections/{section_key}/validator-edit`, consumed by Task 4's frontend `shiftApi.ts`.

- [ ] **Step 1: Find and update `list_revisions`' SQL/serialization**

Read the current implementation first:

```bash
grep -n "def list_revisions" -A 25 backend/modules/production/api/shift_report_service.py
```

Add `edited_by_validator` to the `SELECT` column list and to the returned dict alongside `revision`, `snapshot`, `reason`, `actor_id`, `created_at` — matching whatever column-list/dict-building style that method already uses (it will look like a tuple unpack from a `fetchall()`, same pattern as `_freeze_revision`'s insert). Do not change the method's existing filtering or ordering.

- [ ] **Step 2: Add the endpoint**

In `backend/modules/production/api/router.py`, near `save_shift_report_section` (around line 2960):

```python
class ValidatorEditSectionRequest(BaseModel):
    payload: dict
    reason: str


@router.put("/shift-reports/{shift_report_id}/sections/{section_key}/validator-edit")
def validator_edit_shift_report_section(
    shift_report_id: str,
    section_key: str,
    body: ValidatorEditSectionRequest,
    tenant: TenantContext = Depends(require_permission("production.shift.validate")),
) -> dict:
    with get_connection() as connection:
        result = ShiftValidationService(connection).edit_section_as_validator(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            shift_report_id=shift_report_id,
            section_key=section_key,
            payload=body.payload,
            reason=body.reason,
        )
        return _shift_result(connection, result)
```

Place this after `save_shift_report_section` and before `submit_shift_report_section`, keeping the file's existing endpoint order (by section-lifecycle concept) intact.

- [ ] **Step 3: Add `MISSING_REASON` to the 409 list if not already covered**

Check `_report_err_status` (`router.py:1841`) — `MISSING_REASON` should map to a 4xx; confirm by reading the current tuple. If `MISSING_REASON` is not already in the 409 tuple, leave it falling through to the default `400 BAD_REQUEST` (matching `reject_sections`' own `MISSING_REASON` behavior today — do not special-case it differently here than the existing reject path already does; check what status `reject_sections`' `MISSING_REASON` currently returns and match it exactly).

- [ ] **Step 4: Run the Task 2 test again to confirm `edited_by_validator` now appears in history**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_validation_integration.py -k validator_can_edit -v`
Expected: PASS (the `history[0]["edited_by_validator"] is True` assertion now succeeds).

- [ ] **Step 5: Write an endpoint-level test**

Find the existing router/API-level test pattern for shift endpoints (likely `test_shift_report_api_integration.py` or similar — search first):

```bash
grep -rl "TestClient\|client.put.*shift-reports" backend/modules/production/api/test_*.py
```

Add a test hitting `PUT /production/shift-reports/{id}/sections/{key}/validator-edit` through the FastAPI test client (matching whatever fixture that file already uses for an authenticated client), asserting: 200 with a valid reason, 403 without `production.shift.validate`, 400/409 with an empty reason.

- [ ] **Step 6: Run that test file**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest modules/production/api/test_shift_report_api_integration.py -v` (adjust filename to whatever Step 5 found)
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/production/api/shift_report_service.py backend/modules/production/api/router.py backend/modules/production/api/test_shift_validation_integration.py backend/modules/production/api/test_shift_report_api_integration.py
git commit -m "Expose validator in-place edit endpoint and surface edited_by_validator in revision history"
```

---

## Task 4: Frontend API client — `validatorEditSection`

**Files:**
- Modify: `frontend/src/features/production/shift/shiftApi.ts`

**Interfaces:**
- Consumes: Task 3's endpoint `PUT /production/shift-reports/{id}/sections/{key}/validator-edit`.
- Produces: `validatorEditSection(token: string, id: string, key: SectionKey, payload: SectionPayload, reason: string): Promise<SectionState>`, consumed by Task 5. `SectionRevision.edited_by_validator: boolean` added to the existing interface, consumed by Task 6.

- [ ] **Step 1: Add the type field and function**

In `frontend/src/features/production/shift/shiftApi.ts`, extend the existing `SectionRevision` interface (around line 61):

```typescript
export interface SectionRevision {
  revision: number;
  snapshot: SectionPayload;
  reason: string | null;
  actor_id: string | null;
  created_at: string;
  edited_by_validator: boolean;
}
```

Add the new function near `saveShiftSection` (around line 102-104), same style:

```typescript
export function validatorEditSection(token: string, id: string, key: SectionKey, payload: SectionPayload, reason: string) {
  return apiFetch<SectionState>(`${base}/${id}/sections/${key}/validator-edit`, {
    method: "PUT",
    body: { payload, reason },
    token,
  });
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc -b --force`
Expected: no new errors (this is an additive, unused-so-far export at this point — should compile clean).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/production/shift/shiftApi.ts
git commit -m "Add validatorEditSection API client function"
```

---

## Task 5: Editable review sections in the Validation Center

**Files:**
- Modify: `frontend/src/features/production/shift/ShiftValidationPanel.tsx`
- Modify: `frontend/src/features/production/shift/shiftText.ts` (new labels)

**Interfaces:**
- Consumes: Task 4's `validatorEditSection`; `Part` from `SectionCard.tsx` (existing, unchanged signature: `{ part, sectionKey, value, onChange, options, disabled }`); `toDraft`/`toPayload`/`Draft` from `shiftModel.ts` (existing, same functions `SectionCard.tsx` already uses at lines 64 and 95).
- Produces: `ReviewSection` becomes stateful and editable; no change to its exported surface (still rendered the same way from `ShiftReviewDialog`).

- [ ] **Step 1: Add new labels to `shiftText.ts`**

Find the `T` object (starts around line 22) and add, near `sendBackReason`/`sendBackReasonHint`:

```typescript
  editSection: L("Edit this section", "Modifier cette section"),
  editSectionReason: L("Why are you correcting this?", "Pourquoi corrigez-vous ceci ?"),
  saveCorrection: L("Save correction", "Enregistrer la correction"),
  savingCorrection: L("Saving…", "Enregistrement…"),
  correctionSaved: L("Correction saved", "Correction enregistrée"),
```

- [ ] **Step 2: Make `ReviewSection` stateful**

In `frontend/src/features/production/shift/ShiftValidationPanel.tsx`, `ReviewSection` currently takes `state: SectionState` and always renders `Part` with `disabled` and a no-op `onChange`. Replace it with a version that tracks local edit state and offers a "Modifier cette section" toggle, gated by whether the caller can validate (the whole panel already requires `production.shift.validate` to render at all — see `allowed` at line 40 — so no additional permission check is needed inside `ReviewSection` itself).

Replace the `ReviewSection` function (lines 281-341) with:

```tsx
function ReviewSection({
  def,
  state,
  options,
  open,
  onToggle,
  ticked,
  onTick,
  shiftId,
  onEdited,
}: {
  def: SectionDef;
  state: SectionState;
  options: OptionMap;
  open: boolean;
  onToggle: () => void;
  ticked: boolean;
  onTick: () => void;
  shiftId: string;
  onEdited: () => void;
}) {
  const { session } = useAuth();
  const token = session!.token;
  const label = useLabel();
  const Icon = def.icon;
  const empty = state.status === "nothing_to_report";

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft>(() => toDraft(def, state.payload));
  const [reason, setReason] = useState("");

  useEffect(() => {
    setDraft(toDraft(def, state.payload));
  }, [def, state.payload]);

  const save = useMutation({
    mutationFn: () => validatorEditSection(token, shiftId, def.key, toPayload(def, draft), reason.trim()),
    onSuccess: () => {
      toast.success(label(T.correctionSaved));
      setEditing(false);
      setReason("");
      onEdited();
    },
    onError: (error: unknown) =>
      toast.error(label(T.failed), { description: error instanceof ApiError ? error.message : undefined }),
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
        {open && !empty && (
          <Button size="sm" variant="ghost" onClick={() => setEditing((v) => !v)}>
            {label(T.editSection)}
          </Button>
        )}
      </div>
      {open && (
        <div className="space-y-3 px-3 py-3">
          {empty ? (
            <p className="text-sm text-muted-foreground">{label(T.nothingSection)}</p>
          ) : (
            <>
              {def.parts.map((part) => (
                <Part
                  key={part.payloadKey}
                  part={part}
                  sectionKey={`review-${def.key}`}
                  value={draft[part.payloadKey]}
                  onChange={(value) => setDraft((current) => ({ ...current, [part.payloadKey]: value }))}
                  options={options}
                  disabled={!editing}
                />
              ))}
              {editing && (
                <div className="space-y-1.5 rounded-md border border-primary/30 bg-primary/5 px-3 py-2.5">
                  <Input
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder={label(T.editSectionReason)}
                    aria-label={label(T.editSectionReason)}
                  />
                  <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending || !reason.trim()}>
                    {save.isPending ? label(T.savingCorrection) : label(T.saveCorrection)}
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
```

Add the needed imports at the top of the file: `useState` and `useEffect` are already imported; add `Draft` from `./shiftModel` and `toPayload` alongside the existing `toDraft` import, and `validatorEditSection` alongside the other `shiftApi` imports, and `Input` is already imported.

- [ ] **Step 3: Wire `onEdited` from `ShiftReviewDialog`**

In `ShiftReviewDialog`, the section renders `<ReviewSection ... />` around line 232-243. Add `shiftId={shiftId}` and `onEdited={() => queryClient.invalidateQueries({ queryKey: [...SHIFT_REPORTS_QUERY_KEY, "review", shiftId] })}` — this refetches the shift detail query (`detail` at line 128), which refreshes `shift.sections[].revision`, which in turn is what `approve.mutate()`'s `seen_revisions` reads from at call time (line 164) — so the very next Approve after an edit automatically carries the fresh revision, satisfying the CHANGED_SINCE_OPENED exemption without any separate "baseline" state to manage.

- [ ] **Step 4: Type-check**

Run: `cd frontend && npx tsc -b --force`
Expected: no errors.

- [ ] **Step 5: Browser verification**

Use the `run` skill or drive it manually: log in as the demo user (must hold `production.shift.validate`), open the Validation Center, review a submitted shift, click "Modifier cette section" on a section, change a value, type a reason, save, confirm the toast, confirm the value persisted (reopen the review dialog), then Approve the shift and confirm it validates without a `CHANGED_SINCE_OPENED` error.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/production/shift/ShiftValidationPanel.tsx frontend/src/features/production/shift/shiftText.ts
git commit -m "Let validators edit shift sections in place during review"
```

---

## Task 6: Revision-history badge

**Files:**
- Modify: `frontend/src/features/production/shift/RevisionHistory.tsx`
- Modify: `frontend/src/features/production/shift/shiftText.ts`

**Interfaces:**
- Consumes: `SectionRevision.edited_by_validator` from Task 4.

- [ ] **Step 1: Add the label**

In `shiftText.ts`, near `history`/`latest`:

```typescript
  editedByValidator: L("Edited by validator", "Modifié par le validateur"),
```

- [ ] **Step 2: Render the badge**

In `RevisionHistory.tsx`, inside the `<button>` for each revision (around line 92-105), after the existing `{index === 0 && <Badge variant="primary">...}` line, add:

```tsx
{revision.edited_by_validator && <Badge variant="warning">{label(T.editedByValidator)}</Badge>}
```

This renders per-revision (the `.map` at line 90 iterates every revision in the list), so it lands on whichever specific revision actually carries the flag — not hardcoded to the first/latest one.

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc -b --force`
Expected: no errors.

- [ ] **Step 4: Browser verification**

After Task 5's browser check leaves a validator-edited revision in place, open that section's revision history (the "Historique" button in the normal shift editor, not the review dialog) and confirm the badge appears on the correct revision, with the reason text also shown next to it (existing `{revision.reason && ...}` rendering at line 104 already shows the reason — confirm both render together, badge plus reason).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/production/shift/RevisionHistory.tsx frontend/src/features/production/shift/shiftText.ts
git commit -m "Show edited-by-validator badge in section revision history"
```

---

## Task 7: Full-suite verification and wrap-up

**Files:** none (verification only)

- [ ] **Step 1: Full backend suite**

Run: `cd backend && DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m pytest -v`
Expected: all green, no regressions anywhere (not just `modules/production`).

- [ ] **Step 2: Full frontend type-check**

Run: `cd frontend && npx tsc -b --force`
Expected: clean.

- [ ] **Step 3: Confirm this plan's scope boundary**

Confirm no changes were made outside Part A's scope: no touch to `production.shift.delete`, autosave/localStorage, or the day-view list (those are separate, out-of-scope pieces of the 2026-09-22 lifecycle spec per this plan's own spec section).

- [ ] **Step 4: Update memory**

This is a note for whoever executes the plan, not a code step: update `project-shift-report-program` (or add a new linked memory) noting Part A shipped — migration `0058`, `edit_section_as_validator`, the `validator-edit` endpoint, and that it unblocks the Shift Health analytics panel in the Part B plan.
