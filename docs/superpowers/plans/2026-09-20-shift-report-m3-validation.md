# Shift report core — Milestone 3: whole-shift validation

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Terse like M2: interfaces and test lists are the contract; code is written test-first in the named files.

**Goal:** A validator approves a whole shift in one action (stock posts once, all-or-nothing), can send back chosen sections with a reason, and an admin can reverse a validated shift.

**Architecture (transitional, on purpose):** stock posting, regrind, lot registration and packaging-variance rules already live in `ProductionReportService.validate_report` / `delete_report` and are keyed on the old report id. A run or packing row **has that same id**, so validation first *materialises* old-shaped, `submitted` report rows from the shift's new tables (`api/legacy_report_ledger.py`) and then calls the existing methods per row inside one savepoint. Nothing about stock is re-implemented, and dashboards and readers (which read the old tables) see new shifts as soon as they are validated. The cutover milestone replaces the ledger with views and retargets the few remaining writes; it does not change what validation does.

**Spec:** `docs/superpowers/specs/2026-09-20-shift-report-core-design.md` (5.2, 5.3). **Previous:** M2 plan.

## Global Constraints

- One savepoint around the whole validation: any `Err` from any row rolls the shift back to exactly how it was, independent of what the caller does.
- Validation refuses unless the shift is `submitted`; a stale view is refused (`CHANGED_SINCE_OPENED`) when the caller's `seen_revisions` differ from the sections' current revisions.
- An open stop (no `ended_at`) blocks validation (`OPEN_STOP`). A shift with no run and no packing row cannot be validated (`NOTHING_TO_VALIDATE`).
- Energy is split across the shift's runs by `production_minutes`, the last run taking the remainder; with no minutes at all the first run takes everything.
- Unassigned waste and stops attach to the first run (production side) or first packing row (packing side); a stop with no machine side attaches to the first run, else the first packing row.
- Reject needs a reason and at least one section; only `submitted` shifts can be rejected.
- Reverse needs a reason; it deletes the materialised old rows through `delete_report` (which reverses stock), then returns every section that has data to `returned`.
- Permissions: validate and reject need `production.shift.validate`; reverse needs `production.admin_reports`.
- No commits; commands from `backend/`.

## Tasks

### Task 1: `split_proportionally` (pure)

`domain/shift_report.py`: `split_proportionally(total: float, weights: Sequence[float]) -> list[float]`. Tests in `domain/test_shift_report.py`: proportional shares, last takes remainder so the sum is exact, one weight gets all, all-zero weights give everything to the first, empty weights give `[]`.

### Task 2: Ledger materialisation (`api/legacy_report_ledger.py`)

`materialize_shift(connection, *, tenant_id, shift_report_id, actor_id) -> Result[list[tuple[str, str]]]` returns `[(report_id, report_type)]`, runs first. Writes `production_reports` (status `submitted`), `daily_reports` / `conditionnement_reports`, and the report waste, semoule and downtime lines. Replaces any non-validated old rows with the same ids; refuses when one is already validated (`ALREADY_POSTED`).

### Task 3: `ShiftValidationService` (`api/shift_validation_service.py`)

```python
validate_shift(*, tenant_id, actor_id, shift_report_id, seen_revisions=None, shortfall_comment=None,
               regrind_work_center_id=None, correlation_id=None) -> Result[dict]
reject_sections(*, tenant_id, actor_id, shift_report_id, section_keys, reason) -> Result[dict]
reverse_shift(*, tenant_id, actor_id, shift_report_id, reason, force=False) -> Result[dict]
```
Tests in `api/test_shift_validation_integration.py` (real stock, packaging stock, in the rolled-back transaction).

### Task 4: Endpoints and permissions

`POST /production/shift-reports/{id}/validate`, `/reject`, `/reverse`, guarded as above. Add the error codes `CHANGED_SINCE_OPENED`, `OPEN_STOP`, `NOTHING_TO_VALIDATE`, `ALREADY_POSTED` to the router's 409 set. Router tests for the guards.

### Task 5: Regression

Full production, warehouse, qc and core run.


## Outcome (2026-09-20)

Done. `domain/shift_report.split_proportionally`, `api/legacy_report_ledger.py`, `api/shift_validation_service.py`, three endpoints (`/validate`, `/reject`, `/reverse`), 14 validation + 3 extra router tests; full production/warehouse/qc/core run: 829 passed.

Deviations from the plan text:
- Section **submit** now enforces the completeness the old flow demanded on report submit (`check_ready_to_submit` in `shift_sections.py`: stock targets for semoule/regrind/packaging and an item on every waste line), so a team hears about a missing item at its own screen instead of the validator at validation. M2 test fixtures were updated to name items and stores.
- Atomicity is proven at validation time (a shortfall with no comment on the packing row rolls the already-posted run back; the same shift then validates once explained).
- The ledger names its rows with the shift's own ids, so posted stock and lots keep pointing at the right report.
