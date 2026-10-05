# HR Phase 1 — Employee core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the thin `hr` employee/contract tables into a full employee file (identity, NINA/INPS/AMO, family, payment methods, documents, positions and grades, typed contracts with amendments and a one-signed-contract-per-day guard, termination), hide pay/identity/bank data from callers without `hr.view_sensitive`, expose `PayrollSnapshotService` and `EmployeeService.get_by_user` for phases 3 and 5, and ship the `/hr/employees`, `/hr/employees/:id` and `/hr/organisation` screens plus a 60-employee Mali seed.

**Architecture:** Everything stays in the existing `hr` bounded context. Pure rules live in `backend/modules/hr/domain/*.py` (tested without a database); services in `backend/modules/hr/api/*_service.py` load rows, call the domain, write rows and call `record_audit()` in the caller's transaction and never commit; every route stays in `backend/modules/hr/api/router.py` (it keeps its module-level `get_connection` and `fail()`, which phase 5's tests patch and extend). Masking is decided at the HTTP layer: services return full records, the router runs every employee/contract/payment record through `domain/sensitive.py` and refuses a write that sets a hidden field from a caller who could not read it back. The database backs the key rules: a partial unique index for badges and linked users, and a `btree_gist` exclusion constraint so no employee has two signed contracts on the same day.

**Tech Stack:** FastAPI 0.116 + psycopg 3.2 (raw SQL, no ORM), pytest 8 with the `db` fixture (real PostgreSQL 18, rolled back per test) and FastAPI `TestClient`; React 18 + TypeScript (strict, `noUnusedLocals`) + TanStack Query 5 + React Hook Form + Zod + Tailwind/Radix primitives; verification `npx tsc -b --force`.

**Spec:** `docs/superpowers/specs/2026-09-25-hr-payroll-finance-design.md` (section "Phase 1 — Employee core"), cross-phase contract `docs/superpowers/plans/2026-09-25-hr-payroll-finance-interfaces.md`.

## Global Constraints

- Names shared with other phases are exactly the contract's: `PayrollSnapshotService.employees_for_period(*, tenant_id, period, employee_ids=None) -> list[dict]` in `backend/modules/hr/api/payroll_snapshot_service.py` with the contract's dict keys; `EmployeeService.get_by_user(*, tenant_id, user_id) -> dict | None`, importable from `modules.hr.api.service`; `hr.employees.user_id`.
- `hr` migrations of this phase are `0003_*`..`0009_*` only (this plan uses all seven). Never edit an applied migration; if an applied but uncommitted one is wrong, drop what it created, `DELETE FROM core.module_migrations WHERE module_name = 'hr' AND version = '<file>'`, fix it and re-apply.
- Money columns are `NUMERIC(18,0)` in XOF (whole F CFA, no sub-unit); Python uses `decimal.Decimal`, never float. A "period" is a `datetime.date` equal to the first day of a month.
- New contracts are always XOF (`currency` default becomes `'XOF'`); `weekly_hours` defaults to 40 (spec value).
- Statutory or client values (grid minimums, allowances, horizons) are seed data printed under a TO CONFIRM banner, never constants in logic. `hr.settings` horizon columns start empty (NULL = that alert list is off).
- `hr.settings` columns are named `contract_expiry_horizon_days`, `trial_end_horizon_days`, `document_expiry_horizon_days` (phase 5 assumption A5 uses these names).
- Every mutation calls `record_audit()` in the same transaction; every entity with create has an edit behind `hr.admin_<entity>` (`admin_employees`, `admin_departments`, `admin_positions` for positions and grades, `admin_contracts`); audit payloads carry only the *names* of changed sensitive fields (the audit log is readable without `hr.view_sensitive`).
- Every `Err(...)` carries French as its third argument; every `HTTPException` detail is `{"code", "message", "message_fr"}` (`core/test_error_translations.py` enforces it).
- Integration tests use the `db` fixture and **skip** when no migrated database is reachable: a run must show `passed`, not only `skipped`. Apply migrations before running them.
- `backend/scripts/reset_operational_data.py` must classify every new table (`scripts/test_reset_operational_data_integration.py` fails otherwise): purge people data, keep configuration.
- No database CHECK ties `status = 'terminated'` to the termination columns: phase 2's test kit inserts employees with `termination_date` set and no reason. That rule lives in the domain.
- Do not create these paths, later phases create them: `frontend/src/features/hr/format.ts` (phase 5), `backend/modules/hr/domain/expiry.py` (phase 5), `frontend/src/features/hr/HrListTable.tsx` (phase 2). This plan's helpers are `employeeFormat.ts`, `employeeLabels.ts`, `HrTable.tsx`.
- UI strings go through `useI18n()` with both `en` and `fr` keys in `frontend/src/lib/i18n.tsx`; F CFA is formatted with `Intl.NumberFormat(currentLocale(), { style: "currency", currency: "XOF", maximumFractionDigits: 0 })`.
- Lists use `useTableColumns` (resize/visibility), `ColumnFilterRow` and `FilterTabs` where a closed set exists; one branded loader per screen, `Skeleton` inside it; server state only through TanStack Query.
- Shared working tree: never `git stash`; stage only the paths each task names; do not push.
- Commands run from `backend/` (Git Bash): tests `.venv/Scripts/python -m pytest <path> -q`; migrations `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -c "from core.migrations.runner import apply_all_migrations; apply_all_migrations()"`. Frontend check from `frontend/`: `npx tsc -b --force`.

## Review Focus

- **A caller without `hr.view_sensitive` saves an edit** (employee file, contract, payment arrangement) whose form showed masked fields as empty: the hidden values must stay exactly as stored, and any request that does carry a hidden field must be refused with 403 rather than overwrite it blind. (Tasks 1, 3, 4, 5, 11)
- **The contract migrations run on a database that already has legacy contracts** — free-text `'permanent'`, USD, overlapping or starting the same day: the app must still start, types are mapped, overlaps are closed the day before the next contract, and the exclusion constraint is added. (Tasks 5, 6)
- **A payment split whose shares do not add up to 100 % or carry three decimals** (33.333 / 66.667): refused before PostgreSQL's `NUMERIC(5,2)` silently rounds it into a split that no longer adds up. (Task 4)
- **A CDD that was already renewed, or a medical certificate that was already replaced, or a person who left**: no alert keeps showing for them. (Task 8)
- **An amendment or an exit in the middle of the month**: the payroll snapshot gives one contract (the latest that touches the month) and the exit date and reason, and a draft contract never puts anyone on the payroll. (Task 9)

## What this phase owns for later phases

| Consumer | What it relies on | Where |
|---|---|---|
| Phase 2 | `hr.employees.badge_no` (unique per tenant when set), `termination_date`, `status` incl. `'terminated'`; presence permission codes in `module.json`; `scripts/seed_hr_payroll.py` | Tasks 1, 3, 15 |
| Phase 3 | `PayrollSnapshotService.employees_for_period`; contract components keyed by `component_code` (seed uses `TRANSPORT`, `HOUSING`; `rate` is a percentage, `10` = 10 %) | Tasks 5, 9, 15 |
| Phase 5 | `EmployeeService.get_by_user` via `modules.hr.api.service`; `hr.settings` horizon columns; `hr.employee_documents (id, tenant_id, employee_id, kind, expires_on)`; `hr.positions (id, tenant_id, title)`; router `fail()` with a `_NOT_FOUND_CODES` set | Tasks 1, 3, 8 |

---

## File structure

Backend (`backend/modules/hr/`):

| File | Responsibility |
|---|---|
| `__init__.py`, `api/__init__.py`, `domain/__init__.py` (create, empty) | make hr a package like every other module (test module names stay unique) |
| `module.json` (modify) | every new hr permission code from the spec; new provided services |
| `migrations/0003_hr_positions_grades.sql` | `hr.positions`, `hr.grades`, `hr.employees.position_id/grade_id` |
| `migrations/0004_hr_employee_file.sql` | identity/social/badge/user/site/termination columns, `'terminated'` status, unique badge and user |
| `migrations/0005_hr_dependants_payment_methods.sql` | `hr.dependants`, `hr.payment_methods` |
| `migrations/0006_hr_contract_terms.sql` | contract types/terms columns, legacy type mapping, `hr.contract_components` |
| `migrations/0007_hr_contract_overlap_guard.sql` | legacy overlap clean-up, `btree_gist`, exclusion constraint |
| `migrations/0008_hr_employee_documents.sql` | `hr.employee_documents` |
| `migrations/0009_hr_settings.sql` | `hr.settings` (alert horizons, empty by default) |
| `domain/sensitive.py` | which fields are hidden, masking, which fields a write sets |
| `domain/money.py` | whole-F CFA rule |
| `domain/organisation.py` | department / position / grade validation |
| `domain/employee.py` | `EmployeeFile`, validation, `terminate()`, end/termination reasons |
| `domain/dependant.py` | `Dependant`, validation, tax-dependant count on a day |
| `domain/payment.py` | `PaymentMethod`, split validation, set in force on a day |
| `domain/contract.py` | `ContractTerms`, components, validation, overlap rule, end status |
| `domain/document.py` | `EmployeeDocument`, validation |
| `domain/alerts.py` | horizons, alert window, document expiry state |
| `domain/snapshot.py` | month bounds, which contract payroll pays from |
| `domain/entities.py` (modify) | keep only the leave rules (employee rules move to `employee.py`) |
| `api/support.py` | guarded write (savepoint + constraint → refusal), audit payload helpers, reference check |
| `api/access.py` | `can_view_sensitive`, `require`, `require_sensitive_for` |
| `api/schemas.py` | request bodies of every phase-1 route |
| `api/organisation_service.py` | `DepartmentService`, `PositionService`, `GradeService` |
| `api/employee_service.py` | `EmployeeService` (list, get, get_by_user, create, update, terminate) |
| `api/dependant_service.py` | `DependantService` |
| `api/payment_method_service.py` | `PaymentMethodService` (sets replaced as a whole) |
| `api/contract_service.py` (rewrite) | `ContractService` (create, edit, activate, end, amend, close on exit) |
| `api/document_service.py` | `DocumentService` |
| `api/settings_service.py` | `HrSettingsService` |
| `api/alert_service.py` | `HrAlertService.expiry_alerts` |
| `api/payroll_snapshot_service.py` | `PayrollSnapshotService` (contract with phase 3) |
| `api/service.py` (modify) | keeps `LeaveService`; re-exports `EmployeeService`, `DepartmentService` |
| `api/router.py` (modify) | every route; `fail()` code sets; `respond()` |
| `api/conftest.py` | `hr_api` fixture (router over HTTP inside the test transaction) |

Also: `backend/core/permissions_registry.py` (keep `hr.view_sensitive` out of the everyday HR role), `backend/scripts/reset_operational_data.py` (classify new tables), `backend/scripts/seed_dev.py` (contracts in XOF with a valid type), `backend/scripts/seed_hr_payroll.py` (new).

Frontend (`frontend/src/`):

| File | Responsibility |
|---|---|
| `features/hr/api.ts` (rewrite, legacy exports kept) | types, enums, query keys and fetchers |
| `features/hr/employeeFormat.ts` | F CFA, dates, today, blank → null |
| `features/hr/employeeLabels.ts` | enum → i18n key and badge variant maps |
| `features/hr/HrTable.tsx` | list table: columns as data, filter row, visibility, loader/skeleton, empty state |
| `features/hr/FormField.tsx` | label + control + hint + error |
| `features/hr/Masked.tsx` | the "hidden" value marker |
| `features/hr/EmployeesPage.tsx` | `/hr/employees` |
| `features/hr/EmployeeFormDialog.tsx` | create / edit the employee file (sends only changed fields) |
| `features/hr/ExpiryAlertsCard.tsx` | contracts / trials / documents coming up |
| `features/hr/employee/EmployeeFilePage.tsx` | `/hr/employees/:id` with `?tab=` tabs |
| `features/hr/employee/IdentityTab.tsx`, `TerminateDialog.tsx`, `FamilyTab.tsx`, `LeaveTab.tsx`, `PayslipsTab.tsx`, `ContractsTab.tsx`, `ContractFormDialog.tsx`, `EndContractDialog.tsx`, `PaymentTab.tsx`, `DocumentsTab.tsx` | the file's tabs and dialogs |
| `features/hr/organisation/OrganisationPage.tsx`, `DepartmentsTab.tsx`, `PositionsTab.tsx`, `GradesTab.tsx`, `HrSettingsTab.tsx` | `/hr/organisation` |
| `features/hr/HrPage.tsx` (modify) | legacy page keeps only leave, attendance, payroll |
| `routes/router.tsx`, `routes/Sidebar.tsx`, `lib/i18n.tsx` (modify) | routes, HR nav, strings |

---

### Task 1: Permission codes, package files and the sensitive-data rule

**Files:**
- Create: `backend/modules/hr/__init__.py`, `backend/modules/hr/api/__init__.py`, `backend/modules/hr/domain/__init__.py` (empty)
- Modify: `backend/modules/hr/module.json`
- Modify: `backend/core/permissions_registry.py:62-99`
- Create: `backend/core/test_permissions_registry.py`
- Create: `backend/modules/hr/domain/sensitive.py`, `backend/modules/hr/domain/test_sensitive.py`
- Create: `backend/modules/hr/api/access.py`, `backend/modules/hr/api/test_access_integration.py`
- Modify: `backend/modules/hr/api/router.py:1-11, 67-69` (imports, `fail`, new `respond`)
- Create: `backend/modules/hr/api/conftest.py`, `backend/modules/hr/api/test_router_harness_integration.py`

**Interfaces:**
- Produces: `modules.hr.domain.sensitive` — `VIEW_SENSITIVE = "hr.view_sensitive"`, `EMPLOYEE_FIELDS = ("national_id", "inps_no", "amo_no")`, `CONTRACT_FIELDS = ("base_salary",)`, `CONTRACT_WRITE_FIELDS = ("base_salary", "components")`, `PAYMENT_FIELDS = ("account_no", "mobile_number")`, `mask(record, fields, *, visible) -> dict` (adds `sensitive_hidden: bool`), `mask_contract(record, *, visible) -> dict`, `written(changes, fields) -> list[str]`, `filled(record, fields) -> list[str]`.
- Produces: `modules.hr.api.access` — `can_view_sensitive(connection, tenant) -> bool`, `require(connection, tenant, permission) -> None` (403), `require_sensitive_for(connection, tenant, fields: Iterable[str]) -> None`.
- Produces: in `router.py` — `_NOT_FOUND_CODES`, `_CONFLICT_CODES`, `fail(result: Err) -> NoReturn`, `respond(connection, result) -> value` (commit on `Ok`, rollback + raise on `Err`).
- Produces: pytest fixture `hr_api` (in `modules/hr/api/conftest.py`) → `SimpleNamespace(client, grant(*permissions), db, user_id, tenant_id)`; tenant `"hr-router-test"`.

- [ ] **Step 1: Write the failing tests**

`backend/core/test_permissions_registry.py`:

```python
"""The permission catalog comes from the module manifests; the default roles are derived from it."""
from __future__ import annotations

from core.permissions_registry import ADMINISTRATOR_ROLE_CODE, default_role_catalog, permission_catalog

PHASE_ONE_HR_CODES = {
    "hr.view_presence",
    "hr.manage_presence",
    "hr.import_clock",
    "hr.close_presence",
    "hr.admin_presence",
    "hr.view_positions",
    "hr.manage_positions",
    "hr.admin_positions",
    "hr.view_sensitive",
    "hr.self_service",
}


def _role(code: str) -> dict:
    return next(role for role in default_role_catalog() if role["code"] == code)


def test_hr_declares_every_code_the_spec_lists():
    declared = {entry["permission"] for entry in permission_catalog() if entry["module"] == "hr"}
    assert PHASE_ONE_HR_CODES <= declared
    assert {"hr.view_attendance", "hr.manage_attendance"} <= declared  # kept, phase 2 maps them to presence


def test_view_sensitive_is_granted_deliberately_not_bundled_in_the_hr_role():
    hr_role = _role("hr")["permissions"]
    assert "hr.view_sensitive" not in hr_role
    assert "hr.view_positions" in hr_role and "hr.self_service" in hr_role
    assert "hr.admin_positions" not in hr_role


def test_the_administrator_role_still_holds_every_code():
    assert PHASE_ONE_HR_CODES <= set(_role(ADMINISTRATOR_ROLE_CODE)["permissions"])
```

`backend/modules/hr/domain/test_sensitive.py`:

```python
from decimal import Decimal

from modules.hr.domain.sensitive import (
    CONTRACT_WRITE_FIELDS,
    EMPLOYEE_FIELDS,
    PAYMENT_FIELDS,
    filled,
    mask,
    mask_contract,
    written,
)


def test_a_caller_without_the_right_sees_the_fields_emptied_and_flagged():
    record = {"id": "e1", "first_name": "Awa", "national_id": "NINA-1", "inps_no": "INPS-1", "amo_no": None}
    shown = mask(record, EMPLOYEE_FIELDS, visible=False)
    assert shown == {
        "id": "e1",
        "first_name": "Awa",
        "national_id": None,
        "inps_no": None,
        "amo_no": None,
        "sensitive_hidden": True,
    }
    assert record["national_id"] == "NINA-1"  # the service's own record is left untouched


def test_a_caller_with_the_right_sees_everything():
    record = {"account_no": "ML-0001", "mobile_number": None}
    assert mask(record, PAYMENT_FIELDS, visible=True) == {"account_no": "ML-0001", "mobile_number": None, "sensitive_hidden": False}


def test_a_field_the_record_does_not_carry_is_not_invented():
    assert "inps_no" not in mask({"id": "e1"}, EMPLOYEE_FIELDS, visible=False)


def test_a_hidden_contract_keeps_its_component_codes_but_not_their_values():
    contract = {
        "base_salary": Decimal("150000"),
        "components": [{"component_code": "TRANSPORT", "amount": Decimal("15000"), "rate": None}],
    }
    shown = mask_contract(contract, visible=False)
    assert shown["base_salary"] is None
    assert shown["components"] == [{"component_code": "TRANSPORT", "amount": None, "rate": None}]
    assert shown["sensitive_hidden"] is True


def test_written_lists_the_sensitive_fields_a_patch_mentions_even_to_clear_them():
    assert written({"first_name": "Awa", "national_id": None}, EMPLOYEE_FIELDS) == ["national_id"]


def test_filled_ignores_blank_values_and_empty_lists_but_not_zero():
    assert filled({"base_salary": Decimal("0"), "components": []}, CONTRACT_WRITE_FIELDS) == ["base_salary"]
    assert filled({"account_no": "", "mobile_number": None}, PAYMENT_FIELDS) == []
```

`backend/modules/hr/api/test_access_integration.py`:

```python
"""hr.view_sensitive decides who reads and who writes pay, national ids and bank details."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from ulid import ULID

from core.tenancy import TenantContext
from modules.hr.api.access import can_view_sensitive, require_sensitive_for

TENANT = "hr-access-test"


@pytest.fixture
def caller(db):
    user_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (user_id, TENANT, f"{user_id}@test.local"),
    )
    return TenantContext(tenant_id=TENANT, user_id=user_id, session_token="t")


def test_a_write_without_sensitive_fields_needs_nothing_more(db, caller):
    require_sensitive_for(db, caller, [])


def test_a_write_with_a_sensitive_field_needs_hr_view_sensitive(db, caller):
    with pytest.raises(HTTPException) as refused:
        require_sensitive_for(db, caller, ["national_id"])
    assert refused.value.status_code == 403
    assert refused.value.detail["code"] == "FORBIDDEN"
    assert refused.value.detail["message_fr"] == "permission manquante : hr.view_sensitive"


def test_the_right_opens_both_reading_and_writing(db, caller):
    assert can_view_sensitive(db, caller) is False
    db.execute("INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, 'hr.view_sensitive')", (caller.user_id,))
    assert can_view_sensitive(db, caller) is True
    require_sensitive_for(db, caller, ["base_salary"])


def test_the_right_can_come_from_a_role(db, caller):
    role_id = str(ULID())
    db.execute("INSERT INTO core.roles (id, tenant_id, code, name) VALUES (%s, %s, %s, 'Paie')", (role_id, TENANT, f"paie-{role_id}"))
    db.execute("INSERT INTO core.role_permissions (role_id, permission) VALUES (%s, 'hr.view_sensitive')", (role_id,))
    db.execute("INSERT INTO core.user_roles (user_id, role_id) VALUES (%s, %s)", (caller.user_id, role_id))
    assert can_view_sensitive(db, caller) is True
```

`backend/modules/hr/api/test_router_harness_integration.py`:

```python
"""The hr router over HTTP, inside the test transaction (see conftest.hr_api)."""
from __future__ import annotations

from ulid import ULID


def test_a_caller_without_the_route_permission_is_refused(hr_api):
    response = hr_api.client.get("/hr/departments")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "FORBIDDEN"


def test_a_caller_with_it_reads_through_the_test_transaction(hr_api):
    hr_api.grant("hr.view_departments")
    hr_api.db.execute(
        "INSERT INTO hr.departments (id, tenant_id, code, name) VALUES (%s, %s, 'PROD', 'Production')",
        (str(ULID()), hr_api.tenant_id),
    )
    assert [row["code"] for row in hr_api.client.get("/hr/departments").json()] == ["PROD"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest core/test_permissions_registry.py modules/hr/domain/test_sensitive.py modules/hr/api/test_access_integration.py modules/hr/api/test_router_harness_integration.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.hr.domain.sensitive'` / `'modules.hr.api.access'`, `fixture 'hr_api' not found`, and the registry assertions on the missing codes.

- [ ] **Step 3: Declare the codes and make hr a package**

Create the three empty files `backend/modules/hr/__init__.py`, `backend/modules/hr/api/__init__.py`, `backend/modules/hr/domain/__init__.py`.

Replace `backend/modules/hr/module.json` with:

```json
{
  "name": "hr",
  "version": "0.2.0",
  "depends": ["core"],
  "optional_depends": [],
  "provides_api": [
    "EmployeeService",
    "DepartmentService",
    "PositionService",
    "GradeService",
    "ContractService",
    "LeaveService",
    "HrDashboardService",
    "HrAlertService",
    "PayrollSnapshotService"
  ],
  "publishes_events": [],
  "subscribes_events": [],
  "migrations_path": "./migrations",
  "permissions": [
    "hr.view_employees",
    "hr.manage_employees",
    "hr.admin_employees",
    "hr.view_departments",
    "hr.manage_departments",
    "hr.admin_departments",
    "hr.view_contracts",
    "hr.manage_contracts",
    "hr.admin_contracts",
    "hr.view_leave",
    "hr.manage_leave",
    "hr.admin_leave",
    "hr.view_dashboard",
    "hr.view_attendance",
    "hr.manage_attendance",
    "hr.view_payroll",
    "hr.manage_payroll",
    "hr.admin_payroll",
    "hr.view_presence",
    "hr.manage_presence",
    "hr.import_clock",
    "hr.close_presence",
    "hr.admin_presence",
    "hr.view_positions",
    "hr.manage_positions",
    "hr.admin_positions",
    "hr.view_sensitive",
    "hr.self_service"
  ]
}
```

In `backend/core/permissions_registry.py`, add below `ADMINISTRATOR_ROLE_CODE = "administrateur"`:

```python
# Permissions that open personal data (salary, national id, bank details). Like admin_*, they
# are granted one at a time on purpose and never bundled into a module's everyday role.
DELIBERATE_GRANT_PERMISSIONS = {"hr.view_sensitive"}
```

and in `default_role_catalog()` replace the per-module comprehension with:

```python
        permissions = [
            entry["permission"]
            for entry in catalog
            if entry["module"] == module
            and not entry["permission"].split(".", 1)[1].startswith("admin_")
            and entry["permission"] not in DELIBERATE_GRANT_PERMISSIONS
        ]
```

(`ensure_default_roles` only ever adds rows, so a tenant whose HR role was created earlier never had this new code and does not get it.)

- [ ] **Step 4: Write the sensitive-data rule**

`backend/modules/hr/domain/sensitive.py`:

```python
"""What a caller without hr.view_sensitive may not see: pay, national identifiers, bank details.

The HTTP layer runs every employee, contract and payment-method record through these before
answering, and refuses a write that sets one of these fields from a caller who could not read
it back: they would be typing blind over a value they cannot see.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping

VIEW_SENSITIVE = "hr.view_sensitive"

EMPLOYEE_FIELDS = ("national_id", "inps_no", "amo_no")
CONTRACT_FIELDS = ("base_salary",)
# A contract's components are pay too: writing them needs the right, reading them is masked below.
CONTRACT_WRITE_FIELDS = ("base_salary", "components")
PAYMENT_FIELDS = ("account_no", "mobile_number")


def mask(record: Mapping[str, object], fields: tuple[str, ...], *, visible: bool) -> dict:
    """A copy of `record` with `fields` emptied when not `visible`, flagged either way."""
    shown = dict(record)
    if not visible:
        for name in fields:
            if name in shown:
                shown[name] = None
    shown["sensitive_hidden"] = not visible
    return shown


def mask_contract(record: Mapping[str, object], *, visible: bool) -> dict:
    """Like mask(), and a hidden contract keeps its component codes but not their amounts or rates."""
    shown = mask(record, CONTRACT_FIELDS, visible=visible)
    if not visible:
        shown["components"] = [{**component, "amount": None, "rate": None} for component in record.get("components", [])]
    return shown


def written(changes: Mapping[str, object], fields: Iterable[str]) -> list[str]:
    """The sensitive fields a PATCH mentions; clearing one is a write too."""
    return [name for name in fields if name in changes]


def filled(record: Mapping[str, object], fields: Iterable[str]) -> list[str]:
    """The sensitive fields a create or a replaced list actually sets (0 is a value, '' is not)."""
    return [name for name in fields if record.get(name) not in (None, "", [])]
```

`backend/modules/hr/api/access.py`:

```python
"""Permission checks an hr route can only make once it has read the request body."""
from __future__ import annotations

from collections.abc import Iterable

from fastapi import HTTPException, status

from core.tenancy import TenantContext, user_has_permission
from modules.hr.domain.sensitive import VIEW_SENSITIVE


def require(connection, tenant: TenantContext, permission: str) -> None:
    if not user_has_permission(connection, user_id=tenant.user_id, permission=permission):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {
                "code": "FORBIDDEN",
                "message": f"missing permission: {permission}",
                "message_fr": f"permission manquante : {permission}",
            },
        )


def can_view_sensitive(connection, tenant: TenantContext) -> bool:
    return user_has_permission(connection, user_id=tenant.user_id, permission=VIEW_SENSITIVE)


def require_sensitive_for(connection, tenant: TenantContext, fields: Iterable[str]) -> None:
    """A write that sets pay, a national identifier or bank details needs hr.view_sensitive."""
    if list(fields):
        require(connection, tenant, VIEW_SENSITIVE)
```

- [ ] **Step 5: Give the router its refusal map and `respond()`, and the test harness**

In `backend/modules/hr/api/router.py`, add `from typing import NoReturn` after `import datetime`, and replace the existing `def fail(result: Err) -> None:` function (lines 67-69) with:

```python
# Refusals answered 404 / 409; every other refusal is a 422. Later phases add their codes here.
_NOT_FOUND_CODES = {"NOT_FOUND"}
_CONFLICT_CODES = {
    "BADGE_TAKEN",
    "USER_ALREADY_LINKED",
    "CONTRACT_OVERLAP",
    "ALREADY_TERMINATED",
    "EMPLOYEE_TERMINATED",
    "CONTRACT_AFTER_TERMINATION",
    "INVALID_TRANSITION",
}


def fail(result: Err) -> NoReturn:
    if result.code in _NOT_FOUND_CODES:
        code = status.HTTP_404_NOT_FOUND
    elif result.code in _CONFLICT_CODES or result.code.startswith("DUPLICATE"):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    raise HTTPException(code, err_detail(result))


def respond(connection, result):
    """Commit a successful write and return its value; roll back and raise on a refusal."""
    if isinstance(result, Err):
        connection.rollback()
        fail(result)
    connection.commit()
    return result.value
```

Keep `from core.db import get_connection` and every existing `with get_connection() as connection:` in `router.py` as they are: tests (this plan's and phase 5's) patch `router_module.get_connection`.

`backend/modules/hr/api/conftest.py`:

```python
"""A throwaway FastAPI app carrying the hr router, for tests that go through HTTP.

The session is overridden, and every connection the router or the permission check opens is the
`db` fixture's rolled-back one (commit and rollback made no-ops), so nothing reaches the
development data.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from ulid import ULID

from core.tenancy import TenantContext, require_session

TENANT = "hr-router-test"


class _Connection:
    """The fixture's connection, with the transaction left to the fixture."""

    def __init__(self, connection) -> None:
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


@pytest.fixture
def hr_api(db, monkeypatch):
    pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
    from fastapi.testclient import TestClient

    from modules.hr.api import router as router_module

    user_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (user_id, TENANT, f"{user_id}@test.local"),
    )
    wrapped = _Connection(db)
    monkeypatch.setattr(router_module, "get_connection", lambda: wrapped)
    monkeypatch.setattr("core.tenancy.get_connection", lambda: wrapped)

    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[require_session] = lambda: TenantContext(tenant_id=TENANT, user_id=user_id, session_token="t")

    def grant(*permissions: str) -> None:
        for permission in permissions:
            db.execute(
                "INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (user_id, permission),
            )

    return SimpleNamespace(client=TestClient(app), grant=grant, db=db, user_id=user_id, tenant_id=TENANT)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest core/test_permissions_registry.py core/test_error_translations.py modules/hr -q`
Expected: PASS, with the integration tests counted as passed (not skipped).

- [ ] **Step 7: Commit**

```bash
git add backend/modules/hr/__init__.py backend/modules/hr/api/__init__.py backend/modules/hr/domain/__init__.py backend/modules/hr/module.json backend/core/permissions_registry.py backend/core/test_permissions_registry.py backend/modules/hr/domain/sensitive.py backend/modules/hr/domain/test_sensitive.py backend/modules/hr/api/access.py backend/modules/hr/api/test_access_integration.py backend/modules/hr/api/router.py backend/modules/hr/api/conftest.py backend/modules/hr/api/test_router_harness_integration.py
git commit -m "feat(hr): phase 1 permission codes and the hr.view_sensitive rule

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Organisation — positions, grades and editable departments

**Files:**
- Create: `backend/modules/hr/migrations/0003_hr_positions_grades.sql`
- Create: `backend/modules/hr/domain/money.py`, `backend/modules/hr/domain/organisation.py`, `backend/modules/hr/domain/test_organisation.py`
- Create: `backend/modules/hr/api/support.py`, `backend/modules/hr/api/organisation_service.py`, `backend/modules/hr/api/schemas.py`
- Modify: `backend/modules/hr/api/service.py` (drop the `DepartmentService` class, re-export it)
- Modify: `backend/modules/hr/api/router.py` (replace the legacy department routes, add positions and grades)
- Modify: `backend/scripts/reset_operational_data.py` (classify `hr.positions`, `hr.grades`)
- Test: `backend/modules/hr/api/test_organisation_integration.py`, `backend/modules/hr/api/test_organisation_routes_integration.py`

**Interfaces:**
- Consumes: `respond`, `fail`, `hr_api` (Task 1).
- Produces: `modules.hr.domain.money` — `is_whole_amount(value: Decimal | None) -> bool`, `invalid_amount(label_en: str, label_fr: str) -> Err` (code `INVALID_AMOUNT`).
- Produces: `modules.hr.api.support` — `execute_guarded(connection, query, params, refusals: Mapping[str, Err]) -> Err | None`, `iso_dates(value)`, `json_safe(value)`, `change_payload(before, after, sensitive=()) -> {"changed": {...}, "sensitive_changed": [...]}`, `missing_reference(connection, table, tenant_id, row_id, label_en, label_fr) -> Err | None`.
- Produces: `DepartmentService.list_departments(tenant_id) -> list[dict]` (keys `id, code, name, manager_employee_id, manager_name, employee_count`), `get_department(*, tenant_id, department_id)`, `create_department(*, tenant_id, actor_id, code, name, manager_employee_id=None) -> Result[dict]`, `update_department(*, tenant_id, actor_id, department_id, changes) -> Result[dict]`; `PositionService.list_positions(tenant_id)` (keys `id, code, title, department_id, department_name, headcount_budget, headcount`), `create_position(*, tenant_id, actor_id, code, title, department_id=None, headcount_budget=None)`, `update_position(*, tenant_id, actor_id, position_id, changes)`; `GradeService.list_grades(tenant_id)` (keys `id, code, category, echelon, base_salary: Decimal, valid_from: iso str`), `create_grade(*, tenant_id, actor_id, code, category, echelon, base_salary, valid_from)`, `update_grade(*, tenant_id, actor_id, grade_id, changes)`.
- Produces: routes `GET/POST /hr/departments`, `PATCH /hr/departments/{id}`; `GET/POST /hr/positions`, `PATCH /hr/positions/{id}`; `GET/POST /hr/grades`, `PATCH /hr/grades/{id}` (view/manage/admin: `hr.*_departments`; `hr.*_positions` for both positions and grades).
- Produces: columns `hr.employees.position_id`, `hr.employees.grade_id`.

- [ ] **Step 1: Write the failing tests**

`backend/modules/hr/domain/test_organisation.py`:

```python
import datetime
from decimal import Decimal

from core.domain.result import Err, Ok
from modules.hr.domain.money import is_whole_amount
from modules.hr.domain.organisation import (
    DepartmentInput,
    GradeInput,
    PositionInput,
    validate_department,
    validate_grade,
    validate_position,
)

JAN_1 = datetime.date(2026, 1, 1)


def test_amounts_are_whole_non_negative_francs():
    assert is_whole_amount(Decimal("150000"))
    assert is_whole_amount(Decimal("0"))
    assert not is_whole_amount(Decimal("150000.5"))
    assert not is_whole_amount(Decimal("-1"))
    assert not is_whole_amount(Decimal("NaN"))
    assert not is_whole_amount(None)


def test_a_department_needs_a_code_and_a_name_and_is_trimmed():
    assert isinstance(validate_department(DepartmentInput(code=" ", name="Production")), Err)
    ok = validate_department(DepartmentInput(code=" PROD ", name=" Production ", manager_employee_id=""))
    assert ok == Ok(DepartmentInput(code="PROD", name="Production", manager_employee_id=None))


def test_a_position_budget_cannot_be_negative_but_can_be_absent():
    refused = validate_position(PositionInput(code="OP", title="Opérateur", headcount_budget=-1))
    assert isinstance(refused, Err) and refused.code == "INVALID_POSITION"
    assert validate_position(PositionInput(code="OP", title="Opérateur")).value.headcount_budget is None


def test_a_grade_minimum_is_whole_francs():
    grade = GradeInput(code="OS1", category="3", echelon="A", base_salary=Decimal("75000.5"), valid_from=JAN_1)
    assert validate_grade(grade).code == "INVALID_AMOUNT"


def test_a_grade_needs_every_field():
    assert validate_grade(GradeInput(code="OS1", category="", echelon="A", base_salary=Decimal("75000"), valid_from=JAN_1)).code == "INVALID_GRADE"
    assert validate_grade(GradeInput(code="OS1", category="3", echelon="A", base_salary=None, valid_from=JAN_1)).code == "INVALID_AMOUNT"
    assert validate_grade(GradeInput(code="OS1", category="3", echelon="A", base_salary=Decimal("1"), valid_from=None)).code == "INVALID_GRADE"
```

`backend/modules/hr/api/test_organisation_integration.py`:

```python
"""Departments, positions and grades against a real database (rolled back after each test)."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.hr.api.organisation_service import DepartmentService, GradeService, PositionService

TENANT = "hr-organisation-test"


@pytest.fixture
def actor(db):
    actor_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor_id, TENANT, f"{actor_id}@test.local"),
    )
    return actor_id


def _actions(db, entity_id: str) -> list[str]:
    rows = db.execute("SELECT action FROM core.audit_log WHERE entity_id = %s", (entity_id,)).fetchall()
    return sorted(row[0] for row in rows)


def test_a_duplicate_department_code_is_refused_and_the_transaction_stays_usable(db, actor):
    service = DepartmentService(db)
    assert isinstance(service.create_department(tenant_id=TENANT, actor_id=actor, code="PROD", name="Production"), Ok)
    refused = service.create_department(tenant_id=TENANT, actor_id=actor, code="PROD", name="Autre")
    assert isinstance(refused, Err) and refused.code == "DUPLICATE_CODE"
    assert [d["code"] for d in service.list_departments(TENANT)] == ["PROD"]


def test_a_department_edit_changes_only_what_it_names_and_is_audited(db, actor):
    service = DepartmentService(db)
    created = service.create_department(tenant_id=TENANT, actor_id=actor, code="PROD", name="Production").value
    updated = service.update_department(tenant_id=TENANT, actor_id=actor, department_id=created["id"], changes={"name": "Production pâtes"})
    assert (updated.value["code"], updated.value["name"]) == ("PROD", "Production pâtes")
    assert _actions(db, created["id"]) == ["department.created", "department.updated"]


def test_an_unknown_manager_or_department_is_refused(db, actor):
    service = DepartmentService(db)
    refused = service.create_department(tenant_id=TENANT, actor_id=actor, code="PROD", name="Production", manager_employee_id="nobody")
    assert isinstance(refused, Err) and refused.code == "NOT_FOUND"
    assert service.update_department(tenant_id=TENANT, actor_id=actor, department_id="nothing", changes={}).code == "NOT_FOUND"


def test_a_position_lists_its_department_and_headcount(db, actor):
    department = DepartmentService(db).create_department(tenant_id=TENANT, actor_id=actor, code="PROD", name="Production").value
    positions = PositionService(db)
    created = positions.create_position(
        tenant_id=TENANT, actor_id=actor, code="OP-EXT", title="Opérateur extrusion", department_id=department["id"], headcount_budget=12
    )
    assert isinstance(created, Ok)
    db.execute(
        "INSERT INTO hr.employees (id, tenant_id, employee_no, first_name, last_name, hire_date, position_id) "
        "VALUES (%s, %s, 'P-1', 'Awa', 'Traoré', '2024-01-01', %s)",
        (str(ULID()), TENANT, created.value["id"]),
    )
    listed = positions.list_positions(TENANT)
    assert [(p["code"], p["department_name"], p["headcount_budget"], p["headcount"]) for p in listed] == [
        ("OP-EXT", "Production", 12, 1)
    ]


def test_a_position_budget_can_be_cleared_and_a_taken_code_refused(db, actor):
    positions = PositionService(db)
    first = positions.create_position(tenant_id=TENANT, actor_id=actor, code="OP", title="Opérateur", headcount_budget=3).value
    second = positions.create_position(tenant_id=TENANT, actor_id=actor, code="MAG", title="Magasinier").value
    cleared = positions.update_position(tenant_id=TENANT, actor_id=actor, position_id=first["id"], changes={"headcount_budget": None})
    assert cleared.value["headcount_budget"] is None
    taken = positions.update_position(tenant_id=TENANT, actor_id=actor, position_id=second["id"], changes={"code": "OP"})
    assert isinstance(taken, Err) and taken.code == "DUPLICATE_CODE"


def test_a_grade_revision_is_a_new_row_but_the_same_date_twice_is_refused(db, actor):
    grades = GradeService(db)
    first = dict(
        tenant_id=TENANT, actor_id=actor, code="OS1", category="3", echelon="A",
        base_salary=Decimal("75000"), valid_from=datetime.date(2026, 1, 1),
    )
    assert isinstance(grades.create_grade(**first), Ok)
    assert isinstance(grades.create_grade(**{**first, "valid_from": datetime.date(2027, 1, 1), "base_salary": Decimal("80000")}), Ok)
    refused = grades.create_grade(**first)
    assert isinstance(refused, Err) and refused.code == "DUPLICATE_CODE"
    assert [(g["valid_from"], g["base_salary"]) for g in grades.list_grades(TENANT)] == [
        ("2027-01-01", Decimal("80000")),
        ("2026-01-01", Decimal("75000")),
    ]
```

`backend/modules/hr/api/test_organisation_routes_integration.py`:

```python
"""Organisation routes: reading, creating and editing need three different rights."""
from __future__ import annotations


def test_a_position_edit_needs_admin_positions(hr_api):
    hr_api.grant("hr.view_positions", "hr.manage_positions")
    created = hr_api.client.post("/hr/positions", json={"code": "OP", "title": "Opérateur"})
    assert created.status_code == 201
    position_id = created.json()["id"]
    assert hr_api.client.patch(f"/hr/positions/{position_id}", json={"title": "Opératrice"}).status_code == 403
    hr_api.grant("hr.admin_positions")
    edited = hr_api.client.patch(f"/hr/positions/{position_id}", json={"title": "Opératrice"})
    assert edited.status_code == 200 and edited.json()["title"] == "Opératrice"


def test_grades_share_the_position_rights(hr_api):
    hr_api.grant("hr.view_positions")
    assert hr_api.client.get("/hr/grades").status_code == 200
    body = {"code": "OS1", "category": "3", "echelon": "A", "base_salary": 75000, "valid_from": "2026-01-01"}
    assert hr_api.client.post("/hr/grades", json=body).status_code == 403
    hr_api.grant("hr.manage_positions")
    created = hr_api.client.post("/hr/grades", json=body)
    assert created.status_code == 201 and created.json()["base_salary"] == 75000


def test_a_duplicate_department_code_is_a_409_in_french_too(hr_api):
    hr_api.grant("hr.manage_departments")
    assert hr_api.client.post("/hr/departments", json={"code": "PROD", "name": "Production"}).status_code == 201
    refused = hr_api.client.post("/hr/departments", json={"code": "PROD", "name": "Production"})
    assert refused.status_code == 409
    assert refused.json()["detail"]["message_fr"] == "ce code de département existe déjà"


def test_a_department_edit_needs_admin_departments(hr_api):
    hr_api.grant("hr.manage_departments")
    department_id = hr_api.client.post("/hr/departments", json={"code": "PROD", "name": "Production"}).json()["id"]
    assert hr_api.client.patch(f"/hr/departments/{department_id}", json={"name": "Prod"}).status_code == 403
    hr_api.grant("hr.admin_departments")
    assert hr_api.client.patch(f"/hr/departments/{department_id}", json={"name": "Prod"}).json()["name"] == "Prod"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_organisation.py modules/hr/api/test_organisation_integration.py modules/hr/api/test_organisation_routes_integration.py -q`
Expected: FAIL — `No module named 'modules.hr.domain.money'` / `'modules.hr.api.organisation_service'`; the route tests get 404/405 for `/hr/positions`.

- [ ] **Step 3: Write the migration and classify the tables**

`backend/modules/hr/migrations/0003_hr_positions_grades.sql`:

```sql
-- The plant's organisation beyond departments: the positions people hold and the
-- collective-agreement grid (categorie / echelon) their pay is anchored to.
CREATE TABLE IF NOT EXISTS hr.positions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    department_id TEXT REFERENCES hr.departments (id),
    -- How many people the position is budgeted for; NULL until HR records one.
    headcount_budget INTEGER CONSTRAINT hr_positions_budget_check CHECK (headcount_budget IS NULL OR headcount_budget >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT hr_positions_code_key UNIQUE (tenant_id, code)
);

-- One row per grade and per revision of the grid: a new minimum from a later date is a new
-- row with the same code, so a contract signed under the old grid keeps pointing at its row.
CREATE TABLE IF NOT EXISTS hr.grades (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    category TEXT NOT NULL,
    echelon TEXT NOT NULL,
    -- Monthly minimum for the grade, in whole F CFA.
    base_salary NUMERIC(18,0) NOT NULL CONSTRAINT hr_grades_base_salary_check CHECK (base_salary >= 0),
    valid_from DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT hr_grades_code_valid_from_key UNIQUE (tenant_id, code, valid_from)
);

-- Where each person sits; the rest of the employee file comes in 0004.
ALTER TABLE hr.employees
    ADD COLUMN IF NOT EXISTS position_id TEXT REFERENCES hr.positions (id),
    ADD COLUMN IF NOT EXISTS grade_id TEXT REFERENCES hr.grades (id);

CREATE INDEX IF NOT EXISTS hr_positions_department_idx ON hr.positions (tenant_id, department_id);
CREATE INDEX IF NOT EXISTS hr_employees_position_idx ON hr.employees (tenant_id, position_id);
```

In `backend/scripts/reset_operational_data.py`, add `"hr.positions",` to `PURGE_TABLES` right after `"hr.payroll_runs",` (positions point at departments, which are purged) and add `"hr.grades",` to `KEPT_TABLES` right after `"core.users",` (the pay grid is configuration).

Apply it: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -c "from core.migrations.runner import apply_all_migrations; apply_all_migrations()"`
Expected: no output, exit 0.

- [ ] **Step 4: Write the domain rules**

`backend/modules/hr/domain/money.py`:

```python
"""XOF has no sub-unit: every amount the hr module stores is a whole, non-negative number of francs."""
from __future__ import annotations

from decimal import Decimal

from core.domain.result import Err


def is_whole_amount(value: Decimal | None) -> bool:
    return value is not None and value.is_finite() and value >= 0 and value == value.to_integral_value()


def invalid_amount(label_en: str, label_fr: str) -> Err:
    return Err(
        "INVALID_AMOUNT",
        f"{label_en} must be a whole, non-negative number of F CFA",
        f"{label_fr} doit être un nombre entier et positif de F CFA",
    )
```

`backend/modules/hr/domain/organisation.py`:

```python
"""Departments, positions and grades: shape rules, no database."""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal

from core.domain.result import Err, Ok, Result
from modules.hr.domain.money import invalid_amount, is_whole_amount


@dataclass(frozen=True)
class DepartmentInput:
    code: str
    name: str
    manager_employee_id: str | None = None


@dataclass(frozen=True)
class PositionInput:
    code: str
    title: str
    department_id: str | None = None
    headcount_budget: int | None = None


@dataclass(frozen=True)
class GradeInput:
    code: str
    category: str
    echelon: str
    base_salary: Decimal | None
    valid_from: datetime.date | None


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def validate_department(department: DepartmentInput) -> Result[DepartmentInput]:
    if _blank(department.code) or _blank(department.name):
        return Err("INVALID_DEPARTMENT", "department code and name are required", "le code et le nom du département sont obligatoires")
    return Ok(
        DepartmentInput(
            code=department.code.strip(),
            name=department.name.strip(),
            manager_employee_id=department.manager_employee_id or None,
        )
    )


def validate_position(position: PositionInput) -> Result[PositionInput]:
    if _blank(position.code) or _blank(position.title):
        return Err("INVALID_POSITION", "position code and title are required", "le code et l'intitulé du poste sont obligatoires")
    if position.headcount_budget is not None and position.headcount_budget < 0:
        return Err("INVALID_POSITION", "the headcount budget cannot be negative", "l'effectif budgété ne peut pas être négatif")
    return Ok(
        PositionInput(
            code=position.code.strip(),
            title=position.title.strip(),
            department_id=position.department_id or None,
            headcount_budget=position.headcount_budget,
        )
    )


def validate_grade(grade: GradeInput) -> Result[GradeInput]:
    if _blank(grade.code) or _blank(grade.category) or _blank(grade.echelon) or grade.valid_from is None:
        return Err(
            "INVALID_GRADE",
            "grade code, category, echelon and start date are required",
            "le code, la catégorie, l'échelon et la date de début de la grille sont obligatoires",
        )
    if not is_whole_amount(grade.base_salary):
        return invalid_amount("the grade minimum", "le minimum de la catégorie")
    return Ok(
        GradeInput(
            code=grade.code.strip(),
            category=grade.category.strip(),
            echelon=grade.echelon.strip(),
            base_salary=grade.base_salary,
            valid_from=grade.valid_from,
        )
    )
```

- [ ] **Step 5: Write the shared service helpers**

`backend/modules/hr/api/support.py`:

```python
"""Shared by the hr services: guarded writes, audit payloads and reference checks."""
from __future__ import annotations

import datetime
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from decimal import Decimal

import psycopg

from core.domain.result import Err


def execute_guarded(
    connection: psycopg.Connection, query: str, params: Sequence[object], refusals: Mapping[str, Err]
) -> Err | None:
    """Run one write inside a savepoint. A unique or exclusion constraint named in `refusals`
    becomes that refusal and leaves the transaction usable; any other failure is raised.

    The savepoint is plain SQL rather than connection.transaction(): on a connection with no
    transaction open yet, transaction() would begin one and commit it on exit, behind the
    router's back and past the test fixture's rollback."""
    connection.execute("SAVEPOINT hr_guarded_write")
    try:
        connection.execute(query, params)
    except (psycopg.errors.UniqueViolation, psycopg.errors.ExclusionViolation) as error:
        connection.execute("ROLLBACK TO SAVEPOINT hr_guarded_write")
        refusal = refusals.get(error.diag.constraint_name or "")
        if refusal is None:
            raise
        return refusal
    connection.execute("RELEASE SAVEPOINT hr_guarded_write")
    return None


def iso_dates(value):
    """Dates as ISO strings, recursively; everything else as it is (Decimals stay Decimals)."""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {key: iso_dates(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [iso_dates(item) for item in value]
    return value


def json_safe(value):
    """What the audit log's JSON can hold: dataclasses as dicts, dates as ISO, Decimals as strings."""
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def change_payload(before: Mapping[str, object], after: Mapping[str, object], sensitive: Iterable[str] = ()) -> dict:
    """What an edit changed, for the audit trail: the new value of each ordinary field, only the
    name of each sensitive one (the audit log is readable without hr.view_sensitive)."""
    hidden = set(sensitive)
    changed = [key for key in after if before.get(key) != after.get(key)]
    return {
        "changed": {key: json_safe(after[key]) for key in changed if key not in hidden},
        "sensitive_changed": [key for key in changed if key in hidden],
    }


def missing_reference(
    connection: psycopg.Connection, table: str, tenant_id: str, row_id: str | None, label_en: str, label_fr: str
) -> Err | None:
    """NOT_FOUND when `row_id` names no row of `table` in this tenant; None when it does or is None.
    `table` is always a literal from the calling service, never user input."""
    if row_id is None:
        return None
    found = connection.execute(f"SELECT 1 FROM {table} WHERE id = %s AND tenant_id = %s", (row_id, tenant_id)).fetchone()
    return None if found else Err("NOT_FOUND", f"{label_en} not found", f"{label_fr} introuvable")
```

- [ ] **Step 6: Write the organisation services**

`backend/modules/hr/api/organisation_service.py`:

```python
"""Departments, positions and grades: how the plant is organised and the pay grid it follows."""
from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import asdict, replace
from decimal import Decimal

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.support import change_payload, execute_guarded, json_safe, missing_reference
from modules.hr.domain.organisation import (
    DepartmentInput,
    GradeInput,
    PositionInput,
    validate_department,
    validate_grade,
    validate_position,
)

_DEPARTMENT_TAKEN = {
    "departments_tenant_id_code_key": Err("DUPLICATE_CODE", "department code already exists", "ce code de département existe déjà")
}
_POSITION_TAKEN = {"hr_positions_code_key": Err("DUPLICATE_CODE", "position code already exists", "ce code de poste existe déjà")}
_GRADE_TAKEN = {
    "hr_grades_code_valid_from_key": Err(
        "DUPLICATE_CODE", "this grade already has a row from that date", "cette catégorie a déjà une ligne à cette date"
    )
}

_DEPARTMENTS = """
    SELECT d.id, d.code, d.name, d.manager_employee_id, m.first_name || ' ' || m.last_name,
           COUNT(e.id) FILTER (WHERE e.status <> 'terminated')
    FROM hr.departments d
    LEFT JOIN hr.employees m ON m.id = d.manager_employee_id
    LEFT JOIN hr.employees e ON e.department_id = d.id AND e.tenant_id = d.tenant_id
    WHERE d.tenant_id = %s {extra}
    GROUP BY d.id, m.first_name, m.last_name
    ORDER BY d.name
"""
_POSITIONS = """
    SELECT p.id, p.code, p.title, p.department_id, d.name, p.headcount_budget,
           COUNT(e.id) FILTER (WHERE e.status <> 'terminated')
    FROM hr.positions p
    LEFT JOIN hr.departments d ON d.id = p.department_id
    LEFT JOIN hr.employees e ON e.position_id = p.id AND e.tenant_id = p.tenant_id
    WHERE p.tenant_id = %s {extra}
    GROUP BY p.id, d.name
    ORDER BY p.code
"""
_GRADES = "SELECT id, code, category, echelon, base_salary, valid_from FROM hr.grades WHERE tenant_id = %s {extra} ORDER BY code, valid_from DESC"


def _department(row) -> dict:
    return {"id": row[0], "code": row[1], "name": row[2], "manager_employee_id": row[3], "manager_name": row[4], "employee_count": row[5]}


def _position(row) -> dict:
    return {
        "id": row[0],
        "code": row[1],
        "title": row[2],
        "department_id": row[3],
        "department_name": row[4],
        "headcount_budget": row[5],
        "headcount": row[6],
    }


def _grade(row) -> dict:
    return {"id": row[0], "code": row[1], "category": row[2], "echelon": row[3], "base_salary": row[4], "valid_from": row[5].isoformat()}


class DepartmentService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_departments(self, tenant_id: str) -> list[dict]:
        rows = self.connection.execute(_DEPARTMENTS.format(extra=""), (tenant_id,)).fetchall()
        return [_department(row) for row in rows]

    def get_department(self, *, tenant_id: str, department_id: str) -> dict | None:
        row = self.connection.execute(_DEPARTMENTS.format(extra="AND d.id = %s"), (tenant_id, department_id)).fetchone()
        return None if row is None else _department(row)

    def create_department(
        self, *, tenant_id: str, actor_id: str, code: str, name: str, manager_employee_id: str | None = None
    ) -> Result[dict]:
        validated = validate_department(DepartmentInput(code=code, name=name, manager_employee_id=manager_employee_id))
        if isinstance(validated, Err):
            return validated
        department = validated.value
        refused = missing_reference(self.connection, "hr.employees", tenant_id, department.manager_employee_id, "manager", "responsable")
        if refused:
            return refused
        department_id = str(ULID())
        refused = execute_guarded(
            self.connection,
            "INSERT INTO hr.departments (id, tenant_id, code, name, manager_employee_id) VALUES (%s, %s, %s, %s, %s)",
            (department_id, tenant_id, department.code, department.name, department.manager_employee_id),
            _DEPARTMENT_TAKEN,
        )
        if refused:
            return refused
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="department.created",
            entity_type="department", entity_id=department_id, payload=json_safe(department),
        )
        return Ok(self.get_department(tenant_id=tenant_id, department_id=department_id))

    def update_department(self, *, tenant_id: str, actor_id: str, department_id: str, changes: Mapping[str, object]) -> Result[dict]:
        row = self.connection.execute(
            "SELECT code, name, manager_employee_id FROM hr.departments WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (department_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", "department not found", "département introuvable")
        current = DepartmentInput(*row)
        validated = validate_department(replace(current, **changes))
        if isinstance(validated, Err):
            return validated
        department = validated.value
        refused = missing_reference(self.connection, "hr.employees", tenant_id, department.manager_employee_id, "manager", "responsable")
        if refused:
            return refused
        refused = execute_guarded(
            self.connection,
            "UPDATE hr.departments SET code = %s, name = %s, manager_employee_id = %s WHERE id = %s AND tenant_id = %s",
            (department.code, department.name, department.manager_employee_id, department_id, tenant_id),
            _DEPARTMENT_TAKEN,
        )
        if refused:
            return refused
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="department.updated",
            entity_type="department", entity_id=department_id, payload=change_payload(asdict(current), asdict(department)),
        )
        return Ok(self.get_department(tenant_id=tenant_id, department_id=department_id))


class PositionService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_positions(self, tenant_id: str) -> list[dict]:
        rows = self.connection.execute(_POSITIONS.format(extra=""), (tenant_id,)).fetchall()
        return [_position(row) for row in rows]

    def get_position(self, *, tenant_id: str, position_id: str) -> dict | None:
        row = self.connection.execute(_POSITIONS.format(extra="AND p.id = %s"), (tenant_id, position_id)).fetchone()
        return None if row is None else _position(row)

    def create_position(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        code: str,
        title: str,
        department_id: str | None = None,
        headcount_budget: int | None = None,
    ) -> Result[dict]:
        validated = validate_position(PositionInput(code=code, title=title, department_id=department_id, headcount_budget=headcount_budget))
        if isinstance(validated, Err):
            return validated
        position = validated.value
        refused = missing_reference(self.connection, "hr.departments", tenant_id, position.department_id, "department", "département")
        if refused:
            return refused
        position_id = str(ULID())
        refused = execute_guarded(
            self.connection,
            "INSERT INTO hr.positions (id, tenant_id, code, title, department_id, headcount_budget) VALUES (%s, %s, %s, %s, %s, %s)",
            (position_id, tenant_id, position.code, position.title, position.department_id, position.headcount_budget),
            _POSITION_TAKEN,
        )
        if refused:
            return refused
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="position.created",
            entity_type="position", entity_id=position_id, payload=json_safe(position),
        )
        return Ok(self.get_position(tenant_id=tenant_id, position_id=position_id))

    def update_position(self, *, tenant_id: str, actor_id: str, position_id: str, changes: Mapping[str, object]) -> Result[dict]:
        row = self.connection.execute(
            "SELECT code, title, department_id, headcount_budget FROM hr.positions WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (position_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", "position not found", "poste introuvable")
        current = PositionInput(*row)
        validated = validate_position(replace(current, **changes))
        if isinstance(validated, Err):
            return validated
        position = validated.value
        refused = missing_reference(self.connection, "hr.departments", tenant_id, position.department_id, "department", "département")
        if refused:
            return refused
        refused = execute_guarded(
            self.connection,
            "UPDATE hr.positions SET code = %s, title = %s, department_id = %s, headcount_budget = %s WHERE id = %s AND tenant_id = %s",
            (position.code, position.title, position.department_id, position.headcount_budget, position_id, tenant_id),
            _POSITION_TAKEN,
        )
        if refused:
            return refused
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="position.updated",
            entity_type="position", entity_id=position_id, payload=change_payload(asdict(current), asdict(position)),
        )
        return Ok(self.get_position(tenant_id=tenant_id, position_id=position_id))


class GradeService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_grades(self, tenant_id: str) -> list[dict]:
        rows = self.connection.execute(_GRADES.format(extra=""), (tenant_id,)).fetchall()
        return [_grade(row) for row in rows]

    def get_grade(self, *, tenant_id: str, grade_id: str) -> dict | None:
        row = self.connection.execute(_GRADES.format(extra="AND id = %s"), (tenant_id, grade_id)).fetchone()
        return None if row is None else _grade(row)

    def create_grade(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        code: str,
        category: str,
        echelon: str,
        base_salary: Decimal,
        valid_from: datetime.date,
    ) -> Result[dict]:
        validated = validate_grade(GradeInput(code=code, category=category, echelon=echelon, base_salary=base_salary, valid_from=valid_from))
        if isinstance(validated, Err):
            return validated
        grade = validated.value
        grade_id = str(ULID())
        refused = execute_guarded(
            self.connection,
            "INSERT INTO hr.grades (id, tenant_id, code, category, echelon, base_salary, valid_from) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (grade_id, tenant_id, grade.code, grade.category, grade.echelon, grade.base_salary, grade.valid_from),
            _GRADE_TAKEN,
        )
        if refused:
            return refused
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="grade.created",
            entity_type="grade", entity_id=grade_id, payload=json_safe(grade),
        )
        return Ok(self.get_grade(tenant_id=tenant_id, grade_id=grade_id))

    def update_grade(self, *, tenant_id: str, actor_id: str, grade_id: str, changes: Mapping[str, object]) -> Result[dict]:
        row = self.connection.execute(
            "SELECT code, category, echelon, base_salary, valid_from FROM hr.grades WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (grade_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", "grade not found", "catégorie introuvable")
        current = GradeInput(*row)
        validated = validate_grade(replace(current, **changes))
        if isinstance(validated, Err):
            return validated
        grade = validated.value
        refused = execute_guarded(
            self.connection,
            "UPDATE hr.grades SET code = %s, category = %s, echelon = %s, base_salary = %s, valid_from = %s WHERE id = %s AND tenant_id = %s",
            (grade.code, grade.category, grade.echelon, grade.base_salary, grade.valid_from, grade_id, tenant_id),
            _GRADE_TAKEN,
        )
        if refused:
            return refused
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="grade.updated",
            entity_type="grade", entity_id=grade_id, payload=change_payload(asdict(current), asdict(grade)),
        )
        return Ok(self.get_grade(tenant_id=tenant_id, grade_id=grade_id))
```

In `backend/modules/hr/api/service.py`, delete the whole `class DepartmentService:` block and add, below the existing imports:

```python
# Re-exported: the dashboard route and later phases import it from here.
from modules.hr.api.organisation_service import DepartmentService  # noqa: F401
```

- [ ] **Step 7: Add the request bodies and routes**

Create `backend/modules/hr/api/schemas.py`:

```python
"""Request bodies of the hr routes. A PATCH body's unset fields mean "leave it as it is" (the
router passes model_dump(exclude_unset=True)); a field sent as null means "clear it"."""
from __future__ import annotations

import datetime
from decimal import Decimal

from pydantic import BaseModel


class DepartmentCreate(BaseModel):
    code: str
    name: str
    manager_employee_id: str | None = None


class DepartmentPatch(BaseModel):
    code: str | None = None
    name: str | None = None
    manager_employee_id: str | None = None


class PositionCreate(BaseModel):
    code: str
    title: str
    department_id: str | None = None
    headcount_budget: int | None = None


class PositionPatch(BaseModel):
    code: str | None = None
    title: str | None = None
    department_id: str | None = None
    headcount_budget: int | None = None


class GradeCreate(BaseModel):
    code: str
    category: str
    echelon: str
    base_salary: Decimal
    valid_from: datetime.date


class GradePatch(BaseModel):
    code: str | None = None
    category: str | None = None
    echelon: str | None = None
    base_salary: Decimal | None = None
    valid_from: datetime.date | None = None
```

In `backend/modules/hr/api/router.py`: delete the `class DepartmentBody(BaseModel):` model and the two legacy handlers `departments()` and `create_department()`; add to the imports:

```python
from modules.hr.api.organisation_service import GradeService, PositionService
from modules.hr.api.schemas import DepartmentCreate, DepartmentPatch, GradeCreate, GradePatch, PositionCreate, PositionPatch
```

and append at the end of the file:

```python
# ---- organisation: departments, positions, grades -------------------------------------------


@router.get("/departments")
def list_departments(tenant: TenantContext = Depends(require_permission("hr.view_departments"))):
    with get_connection() as connection:
        return DepartmentService(connection).list_departments(tenant.tenant_id)


@router.post("/departments", status_code=status.HTTP_201_CREATED)
def create_department(body: DepartmentCreate, tenant: TenantContext = Depends(require_permission("hr.manage_departments"))):
    with get_connection() as connection:
        result = DepartmentService(connection).create_department(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump())
        return respond(connection, result)


@router.patch("/departments/{department_id}")
def update_department(department_id: str, body: DepartmentPatch, tenant: TenantContext = Depends(require_permission("hr.admin_departments"))):
    with get_connection() as connection:
        result = DepartmentService(connection).update_department(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, department_id=department_id, changes=body.model_dump(exclude_unset=True)
        )
        return respond(connection, result)


@router.get("/positions")
def list_positions(tenant: TenantContext = Depends(require_permission("hr.view_positions"))):
    with get_connection() as connection:
        return PositionService(connection).list_positions(tenant.tenant_id)


@router.post("/positions", status_code=status.HTTP_201_CREATED)
def create_position(body: PositionCreate, tenant: TenantContext = Depends(require_permission("hr.manage_positions"))):
    with get_connection() as connection:
        result = PositionService(connection).create_position(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump())
        return respond(connection, result)


@router.patch("/positions/{position_id}")
def update_position(position_id: str, body: PositionPatch, tenant: TenantContext = Depends(require_permission("hr.admin_positions"))):
    with get_connection() as connection:
        result = PositionService(connection).update_position(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, position_id=position_id, changes=body.model_dump(exclude_unset=True)
        )
        return respond(connection, result)


@router.get("/grades")
def list_grades(tenant: TenantContext = Depends(require_permission("hr.view_positions"))):
    with get_connection() as connection:
        return GradeService(connection).list_grades(tenant.tenant_id)


@router.post("/grades", status_code=status.HTTP_201_CREATED)
def create_grade(body: GradeCreate, tenant: TenantContext = Depends(require_permission("hr.manage_positions"))):
    with get_connection() as connection:
        result = GradeService(connection).create_grade(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump())
        return respond(connection, result)


@router.patch("/grades/{grade_id}")
def update_grade(grade_id: str, body: GradePatch, tenant: TenantContext = Depends(require_permission("hr.admin_positions"))):
    with get_connection() as connection:
        result = GradeService(connection).update_grade(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, grade_id=grade_id, changes=body.model_dump(exclude_unset=True)
        )
        return respond(connection, result)
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr core/test_error_translations.py scripts/test_reset_operational_data_integration.py -q`
Expected: PASS (integration tests counted as passed).

- [ ] **Step 9: Commit**

```bash
git add backend/modules/hr/migrations/0003_hr_positions_grades.sql backend/modules/hr/domain/money.py backend/modules/hr/domain/organisation.py backend/modules/hr/domain/test_organisation.py backend/modules/hr/api/support.py backend/modules/hr/api/organisation_service.py backend/modules/hr/api/schemas.py backend/modules/hr/api/service.py backend/modules/hr/api/router.py backend/modules/hr/api/test_organisation_integration.py backend/modules/hr/api/test_organisation_routes_integration.py backend/scripts/reset_operational_data.py
git commit -m "feat(hr): positions, pay grid and editable departments

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The employee file — identity, social numbers, badge, linked user

**Files:**
- Create: `backend/modules/hr/migrations/0004_hr_employee_file.sql`
- Create: `backend/modules/hr/domain/employee.py`, `backend/modules/hr/domain/test_employee.py`
- Modify: `backend/modules/hr/domain/entities.py` (keep only the leave rules)
- Create: `backend/modules/hr/api/employee_service.py`
- Modify: `backend/modules/hr/api/service.py` (whole file: `LeaveService` + re-exports)
- Modify: `backend/modules/hr/api/schemas.py` (append `EmployeeCreate`, `EmployeePatch`)
- Modify: `backend/modules/hr/api/router.py` (replace the legacy employee routes)
- Test: `backend/modules/hr/api/test_employee_integration.py`, `backend/modules/hr/api/test_employee_routes_integration.py`

**Interfaces:**
- Consumes: `support.execute_guarded / iso_dates / change_payload / missing_reference`, `DepartmentService` (Task 2); `access.*`, `sensitive.*`, `respond`, `fail`, `hr_api` (Task 1).
- Produces: `modules.hr.domain.employee` — `EMPLOYEE_STATUSES`, `GENDERS`, `MARITAL_STATUSES`, `END_REASONS`, `TERMINATION_REASONS`, frozen dataclass `EmployeeFile(employee_no, first_name, last_name, hire_date, status="active", email, phone, department_id, job_title, user_id, gender, birth_date, birth_place, nationality, national_id, inps_no, amo_no, marital_status, address, emergency_contact, badge_no, position_id, grade_id, site, termination_date, termination_reason)` (every field after `status` defaults to `None`), `FIELDS` (all field names, in that order = column order), `EDITABLE_FIELDS` (`FIELDS` minus `employee_no`), `validate_employee_file(EmployeeFile) -> Result[EmployeeFile]` (trimmed, blank optional text → `None`).
- Produces: `EmployeeService(connection)` — `list_employees(tenant_id, status=None, *, today=None) -> list[dict]` (keys `id, employee_no, first_name, last_name, full_name, email, phone, department_id, department_name, job_title, hire_date, status, position_id, position_title, grade_id, grade_code, site, badge_no, user_id, termination_date, contract_type, contract_end_date`; never a sensitive field), `get_employee(*, tenant_id, employee_id) -> dict | None` (every `EmployeeFile` field, dates as ISO strings, plus `id, full_name, department_name, position_title, grade_code, user_email`), `get_by_user(*, tenant_id, user_id) -> dict | None` (same dict, unmasked: it is the caller's own file), `create_employee(*, tenant_id, actor_id, employee: EmployeeFile) -> Result[dict]`, `update_employee(*, tenant_id, actor_id, employee_id, changes: Mapping) -> Result[dict]`. Refusal codes: `INVALID_EMPLOYEE`, `INVALID_STATUS`, `INVALID_CHOICE`, `INVALID_DATES`, `INVALID_TERMINATION`, `DUPLICATE_EMPLOYEE_NO`, `BADGE_TAKEN`, `USER_ALREADY_LINKED`, `INVALID_TRANSITION`, `NOT_FOUND`.
- Produces: routes `GET /hr/employees`, `GET /hr/employees/{id}` (masked), `POST /hr/employees` (`hr.manage_employees`; NINA/INPS/AMO need `hr.view_sensitive`), `PATCH /hr/employees/{id}` (`hr.admin_employees`; mentioning a hidden field needs `hr.view_sensitive`).

- [ ] **Step 1: Write the failing tests**

`backend/modules/hr/domain/test_employee.py`:

```python
import datetime

from core.domain.result import Ok
from modules.hr.domain.employee import EmployeeFile, validate_employee_file

HIRED = datetime.date(2024, 3, 1)


def _file(**overrides) -> EmployeeFile:
    return EmployeeFile(**{"employee_no": "HRP-001", "first_name": "Awa", "last_name": "Traoré", "hire_date": HIRED, **overrides})


def test_blank_optional_text_is_stored_as_null_and_text_is_trimmed():
    result = validate_employee_file(_file(first_name="  Awa ", badge_no="  ", phone=" 76 00 00 00 "))
    assert isinstance(result, Ok)
    assert (result.value.first_name, result.value.badge_no, result.value.phone) == ("Awa", None, "76 00 00 00")


def test_names_number_and_hire_date_are_required():
    assert validate_employee_file(_file(last_name=" ")).code == "INVALID_EMPLOYEE"
    assert validate_employee_file(_file(first_name=None)).code == "INVALID_EMPLOYEE"
    assert validate_employee_file(_file(hire_date=None)).code == "INVALID_EMPLOYEE"


def test_closed_lists_are_closed():
    assert validate_employee_file(_file(status="retired")).code == "INVALID_STATUS"
    assert validate_employee_file(_file(marital_status="engaged")).code == "INVALID_CHOICE"
    assert validate_employee_file(_file(gender="x")).code == "INVALID_CHOICE"


def test_a_birth_date_on_or_after_hiring_is_refused():
    assert validate_employee_file(_file(birth_date=datetime.date(2025, 1, 1))).code == "INVALID_DATES"


def test_terminated_status_and_termination_fields_go_together():
    assert validate_employee_file(_file(status="terminated")).code == "INVALID_TERMINATION"
    left = _file(termination_date=datetime.date(2026, 1, 31), termination_reason="resignation")
    assert validate_employee_file(left).code == "INVALID_TERMINATION"
    complete = _file(status="terminated", termination_date=datetime.date(2026, 1, 31), termination_reason="resignation")
    assert isinstance(validate_employee_file(complete), Ok)


def test_amended_ends_a_contract_never_an_employment():
    assert validate_employee_file(
        _file(status="terminated", termination_date=datetime.date(2026, 1, 31), termination_reason="amended")
    ).code == "INVALID_TERMINATION"
```

`backend/modules/hr/api/test_employee_integration.py`:

```python
"""The employee file against a real database (rolled back after each test)."""
from __future__ import annotations

import datetime

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.hr.api.organisation_service import DepartmentService
from modules.hr.api.service import EmployeeService
from modules.hr.domain.employee import EmployeeFile

TENANT = "hr-employee-test"


@pytest.fixture
def actor(db):
    actor_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor_id, TENANT, f"{actor_id}@test.local"),
    )
    return actor_id


def _file(**overrides) -> EmployeeFile:
    return EmployeeFile(**{"employee_no": "E-001", "first_name": "Awa", "last_name": "Traoré", "hire_date": datetime.date(2024, 3, 1), **overrides})


def test_a_created_file_reads_back_with_its_names_resolved(db, actor):
    department = DepartmentService(db).create_department(tenant_id=TENANT, actor_id=actor, code="PROD", name="Production").value
    created = EmployeeService(db).create_employee(
        tenant_id=TENANT, actor_id=actor, employee=_file(department_id=department["id"], national_id="NINA-1", badge_no="B-1")
    )
    assert isinstance(created, Ok)
    record = created.value
    assert (record["full_name"], record["department_name"], record["national_id"], record["hire_date"]) == (
        "Awa Traoré", "Production", "NINA-1", "2024-03-01",
    )
    [row] = EmployeeService(db).list_employees(TENANT)
    assert (row["badge_no"], row["contract_type"]) == ("B-1", None)
    assert "national_id" not in row


def test_a_badge_is_given_to_one_employee_only(db, actor):
    service = EmployeeService(db)
    assert isinstance(service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(badge_no="B-1")), Ok)
    refused = service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(employee_no="E-002", badge_no="B-1"))
    assert isinstance(refused, Err) and refused.code == "BADGE_TAKEN"
    assert len(service.list_employees(TENANT)) == 1  # the savepoint left the transaction usable


def test_employees_without_a_badge_do_not_collide(db, actor):
    service = EmployeeService(db)
    assert isinstance(service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(badge_no=" ")), Ok)
    assert isinstance(service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(employee_no="E-002")), Ok)


def test_a_duplicate_employee_number_is_refused(db, actor):
    service = EmployeeService(db)
    service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file())
    assert service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file()).code == "DUPLICATE_EMPLOYEE_NO"


def test_a_user_account_links_to_one_employee_and_is_found_back(db, actor):
    service = EmployeeService(db)
    first = service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(user_id=actor, national_id="NINA-1")).value
    own = service.get_by_user(tenant_id=TENANT, user_id=actor)
    assert (own["id"], own["user_email"], own["national_id"]) == (first["id"], f"{actor}@test.local", "NINA-1")
    refused = service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(employee_no="E-002", user_id=actor))
    assert isinstance(refused, Err) and refused.code == "USER_ALREADY_LINKED"
    assert service.get_by_user(tenant_id=TENANT, user_id="someone-else") is None


def test_unknown_references_are_refused(db, actor):
    service = EmployeeService(db)
    assert service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(department_id="nowhere")).code == "NOT_FOUND"
    assert service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(user_id="nobody")).code == "NOT_FOUND"


def test_an_edit_leaves_unmentioned_fields_alone_and_audits_only_names_of_sensitive_ones(db, actor):
    service = EmployeeService(db)
    created = service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(phone="70 00 00 00")).value
    updated = service.update_employee(
        tenant_id=TENANT, actor_id=actor, employee_id=created["id"], changes={"national_id": "NINA-9", "site": "Usine"}
    )
    assert (updated.value["phone"], updated.value["national_id"], updated.value["site"]) == ("70 00 00 00", "NINA-9", "Usine")
    payload = db.execute(
        "SELECT payload FROM core.audit_log WHERE entity_id = %s AND action = 'employee.updated'", (created["id"],)
    ).fetchone()[0]
    assert payload == {"changed": {"site": "Usine"}, "sensitive_changed": ["national_id"]}


def test_an_edit_can_clear_a_field(db, actor):
    service = EmployeeService(db)
    created = service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(phone="70 00 00 00")).value
    cleared = service.update_employee(tenant_id=TENANT, actor_id=actor, employee_id=created["id"], changes={"phone": None})
    assert cleared.value["phone"] is None


def test_leaving_is_not_an_edit(db, actor):
    service = EmployeeService(db)
    created = service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file()).value
    refused = service.update_employee(
        tenant_id=TENANT, actor_id=actor, employee_id=created["id"],
        changes={"status": "terminated", "termination_date": datetime.date(2026, 9, 30), "termination_reason": "resignation"},
    )
    assert isinstance(refused, Err) and refused.code == "INVALID_TRANSITION"
    assert service.create_employee(tenant_id=TENANT, actor_id=actor, employee=_file(
        employee_no="E-002", status="terminated", termination_date=datetime.date(2026, 9, 30), termination_reason="resignation",
    )).code == "INVALID_STATUS"
```

`backend/modules/hr/api/test_employee_routes_integration.py`:

```python
"""The employee file over HTTP: hr.view_sensitive hides NINA / INPS / AMO and guards writing them."""
from __future__ import annotations


def _create(hr_api, **extra):
    body = {"employee_no": "R-001", "first_name": "Awa", "last_name": "Traoré", "hire_date": "2024-03-01", **extra}
    return hr_api.client.post("/hr/employees", json=body)


def _revoke_sensitive(hr_api) -> None:
    hr_api.db.execute(
        "DELETE FROM core.user_permissions WHERE user_id = %s AND permission = 'hr.view_sensitive'", (hr_api.user_id,)
    )


def test_the_social_numbers_are_hidden_from_a_reader_without_hr_view_sensitive(hr_api):
    hr_api.grant("hr.manage_employees", "hr.view_employees", "hr.view_sensitive")
    employee_id = _create(hr_api, national_id="NINA-123", inps_no="INPS-9").json()["id"]
    _revoke_sensitive(hr_api)
    shown = hr_api.client.get(f"/hr/employees/{employee_id}").json()
    assert (shown["national_id"], shown["inps_no"], shown["sensitive_hidden"]) == (None, None, True)
    assert shown["first_name"] == "Awa"


def test_a_reader_with_hr_view_sensitive_sees_them(hr_api):
    hr_api.grant("hr.manage_employees", "hr.view_employees", "hr.view_sensitive")
    employee_id = _create(hr_api, national_id="NINA-123").json()["id"]
    shown = hr_api.client.get(f"/hr/employees/{employee_id}").json()
    assert (shown["national_id"], shown["sensitive_hidden"]) == ("NINA-123", False)


def test_the_list_never_carries_the_sensitive_fields(hr_api):
    hr_api.grant("hr.manage_employees", "hr.view_employees", "hr.view_sensitive")
    _create(hr_api, national_id="NINA-123")
    [row] = hr_api.client.get("/hr/employees").json()
    assert "national_id" not in row and "inps_no" not in row and "amo_no" not in row


def test_setting_a_social_number_without_the_right_is_refused(hr_api):
    hr_api.grant("hr.manage_employees")
    refused = _create(hr_api, national_id="NINA-123")
    assert refused.status_code == 403 and "hr.view_sensitive" in refused.json()["detail"]["message"]
    assert _create(hr_api).status_code == 201  # the same file without it goes through


def test_an_edit_without_the_right_cannot_touch_hidden_fields_but_edits_the_rest(hr_api):
    hr_api.grant("hr.manage_employees", "hr.admin_employees", "hr.view_sensitive")
    employee_id = _create(hr_api, national_id="NINA-123").json()["id"]
    _revoke_sensitive(hr_api)
    assert hr_api.client.patch(f"/hr/employees/{employee_id}", json={"national_id": None}).status_code == 403
    edited = hr_api.client.patch(f"/hr/employees/{employee_id}", json={"phone": "76 00 00 00"})
    assert edited.status_code == 200
    assert (edited.json()["phone"], edited.json()["national_id"]) == ("76 00 00 00", None)
    stored = hr_api.db.execute("SELECT national_id FROM hr.employees WHERE id = %s", (employee_id,)).fetchone()[0]
    assert stored == "NINA-123"


def test_an_edit_needs_admin_employees(hr_api):
    hr_api.grant("hr.manage_employees")
    employee_id = _create(hr_api).json()["id"]
    assert hr_api.client.patch(f"/hr/employees/{employee_id}", json={"phone": "1"}).status_code == 403


def test_a_taken_badge_is_a_409_and_an_unknown_file_a_404(hr_api):
    hr_api.grant("hr.manage_employees", "hr.view_employees")
    assert _create(hr_api, badge_no="B-7").status_code == 201
    refused = _create(hr_api, employee_no="R-002", badge_no="B-7")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "BADGE_TAKEN"
    assert hr_api.client.get("/hr/employees/nobody").status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_employee.py modules/hr/api/test_employee_integration.py modules/hr/api/test_employee_routes_integration.py -q`
Expected: FAIL — `No module named 'modules.hr.domain.employee'`, and the route tests fail on the legacy body shape.

- [ ] **Step 3: Write the migration**

`backend/modules/hr/migrations/0004_hr_employee_file.sql`:

```sql
-- The full employee file: identity, social-security numbers, clock badge, site, the core
-- user the person signs in as (self-service), and how the employment ended.
ALTER TABLE hr.employees
    ADD COLUMN IF NOT EXISTS user_id TEXT REFERENCES core.users (id),
    ADD COLUMN IF NOT EXISTS gender TEXT,
    ADD COLUMN IF NOT EXISTS birth_date DATE,
    ADD COLUMN IF NOT EXISTS birth_place TEXT,
    ADD COLUMN IF NOT EXISTS nationality TEXT,
    ADD COLUMN IF NOT EXISTS national_id TEXT,
    ADD COLUMN IF NOT EXISTS inps_no TEXT,
    ADD COLUMN IF NOT EXISTS amo_no TEXT,
    ADD COLUMN IF NOT EXISTS marital_status TEXT,
    ADD COLUMN IF NOT EXISTS address TEXT,
    ADD COLUMN IF NOT EXISTS emergency_contact TEXT,
    ADD COLUMN IF NOT EXISTS badge_no TEXT,
    ADD COLUMN IF NOT EXISTS site TEXT,
    ADD COLUMN IF NOT EXISTS termination_date DATE,
    ADD COLUMN IF NOT EXISTS termination_reason TEXT;

ALTER TABLE hr.employees DROP CONSTRAINT IF EXISTS employees_status_check;
ALTER TABLE hr.employees ADD CONSTRAINT employees_status_check
    CHECK (status IN ('active', 'on_leave', 'inactive', 'terminated'));
ALTER TABLE hr.employees ADD CONSTRAINT hr_employees_gender_check
    CHECK (gender IS NULL OR gender IN ('male', 'female'));
ALTER TABLE hr.employees ADD CONSTRAINT hr_employees_marital_status_check
    CHECK (marital_status IS NULL OR marital_status IN ('single', 'married', 'divorced', 'widowed'));
ALTER TABLE hr.employees ADD CONSTRAINT hr_employees_termination_reason_check
    CHECK (termination_reason IS NULL OR termination_reason IN
           ('term_reached', 'resignation', 'dismissal', 'trial_termination', 'mutual_agreement', 'retirement', 'death', 'other'));
-- That a terminated employee has an exit date and reason (and only they do) is a domain rule
-- (modules/hr/domain/employee.py); later phases' tests insert exit dates directly.

-- A badge identifies one person at the clock; a sign-in belongs to one employee file.
CREATE UNIQUE INDEX IF NOT EXISTS hr_employees_badge_key ON hr.employees (tenant_id, badge_no) WHERE badge_no IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS hr_employees_user_key ON hr.employees (tenant_id, user_id) WHERE user_id IS NOT NULL;
```

Apply it with the Global Constraints command. Expected: no output, exit 0.

- [ ] **Step 4: Write the employee rules**

`backend/modules/hr/domain/employee.py`:

```python
"""The employee file: who the person is, how HR reaches them, where they sit in the plant and
how their employment ended. Pure rules, no database."""
from __future__ import annotations

import datetime
from dataclasses import dataclass, fields

from core.domain.result import Err, Ok, Result

EMPLOYEE_STATUSES = ("active", "on_leave", "inactive", "terminated")
GENDERS = ("male", "female")
MARITAL_STATUSES = ("single", "married", "divorced", "widowed")
# Why a contract or an employment ended. 'amended' only ever ends a contract: an avenant
# replaces it with a new one and the person stays employed.
END_REASONS = (
    "term_reached",
    "resignation",
    "dismissal",
    "trial_termination",
    "mutual_agreement",
    "retirement",
    "death",
    "amended",
    "other",
)
TERMINATION_REASONS = tuple(reason for reason in END_REASONS if reason != "amended")


@dataclass(frozen=True)
class EmployeeFile:
    employee_no: str
    first_name: str
    last_name: str
    hire_date: datetime.date
    status: str = "active"
    email: str | None = None
    phone: str | None = None
    department_id: str | None = None
    job_title: str | None = None
    user_id: str | None = None
    gender: str | None = None
    birth_date: datetime.date | None = None
    birth_place: str | None = None
    nationality: str | None = None
    national_id: str | None = None
    inps_no: str | None = None
    amo_no: str | None = None
    marital_status: str | None = None
    address: str | None = None
    emergency_contact: str | None = None
    badge_no: str | None = None
    position_id: str | None = None
    grade_id: str | None = None
    site: str | None = None
    termination_date: datetime.date | None = None
    termination_reason: str | None = None


# Field names in declaration order; they are also the column names in hr.employees.
FIELDS = tuple(field.name for field in fields(EmployeeFile))
EDITABLE_FIELDS = tuple(name for name in FIELDS if name != "employee_no")
_REQUIRED_TEXT = ("employee_no", "first_name", "last_name")


def _normalized(employee: EmployeeFile) -> EmployeeFile:
    """Trim every text field; an optional one left blank is stored as NULL, not ''."""
    values: dict[str, object] = {}
    for name in FIELDS:
        value = getattr(employee, name)
        if isinstance(value, str):
            value = value.strip()
            if value == "" and name not in _REQUIRED_TEXT:
                value = None
        values[name] = value
    return EmployeeFile(**values)


def validate_employee_file(employee: EmployeeFile) -> Result[EmployeeFile]:
    candidate = _normalized(employee)
    if not candidate.employee_no or not candidate.first_name or not candidate.last_name or candidate.hire_date is None:
        return Err(
            "INVALID_EMPLOYEE",
            "employee number, names and hire date are required",
            "le matricule, les noms et la date d'embauche sont obligatoires",
        )
    if candidate.status not in EMPLOYEE_STATUSES:
        return Err(
            "INVALID_STATUS",
            f"status must be one of {', '.join(EMPLOYEE_STATUSES)}",
            f"le statut doit être l'un de {', '.join(EMPLOYEE_STATUSES)}",
        )
    if candidate.gender is not None and candidate.gender not in GENDERS:
        return Err("INVALID_CHOICE", "unknown gender", "sexe inconnu")
    if candidate.marital_status is not None and candidate.marital_status not in MARITAL_STATUSES:
        return Err("INVALID_CHOICE", "unknown marital status", "situation matrimoniale inconnue")
    if candidate.birth_date is not None and candidate.birth_date >= candidate.hire_date:
        return Err("INVALID_DATES", "the birth date must precede the hire date", "la date de naissance doit précéder la date d'embauche")
    terminated = candidate.status == "terminated"
    if terminated != (candidate.termination_date is not None and candidate.termination_reason is not None):
        return Err(
            "INVALID_TERMINATION",
            "a person who left has an exit date and reason, and only they do",
            "une personne sortie a une date et un motif de sortie, et elle seule",
        )
    if candidate.termination_reason is not None and candidate.termination_reason not in TERMINATION_REASONS:
        return Err("INVALID_TERMINATION", "unknown exit reason", "motif de sortie inconnu")
    if candidate.termination_date is not None and candidate.termination_date < candidate.hire_date:
        return Err("INVALID_DATES", "the exit date cannot precede the hire date", "la date de sortie ne peut pas précéder la date d'embauche")
    return Ok(candidate)
```

Replace `backend/modules/hr/domain/entities.py` with (the employee rules now live in `employee.py`; nothing else imported them):

```python
from __future__ import annotations

from datetime import date

from core.domain.result import Err, Ok, Result

LEAVE_STATUSES = {"pending", "approved", "rejected", "cancelled"}


def validate_leave(*, start_date: date, end_date: date, status: str = "pending") -> Result[None]:
    if end_date < start_date:
        return Err(
            "INVALID_DATES", "leave end date cannot be before its start date", "la date de fin du congé ne peut pas précéder sa date de début"
        )
    if status not in LEAVE_STATUSES:
        return Err(
            "INVALID_STATUS", f"status must be one of {sorted(LEAVE_STATUSES)}", f"status doit être l'un de {sorted(LEAVE_STATUSES)}"
        )
    return Ok(None)
```

- [ ] **Step 5: Write the employee service**

`backend/modules/hr/api/employee_service.py`:

```python
"""The employee file: list, read, create and edit. Leaving closes contracts, so
terminate_employee (Task 7) works with ContractService."""
from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import asdict, replace

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.support import change_payload, execute_guarded, iso_dates, missing_reference
from modules.hr.domain.employee import EDITABLE_FIELDS, FIELDS, EmployeeFile, validate_employee_file
from modules.hr.domain.sensitive import EMPLOYEE_FIELDS

_UNIQUE_REFUSALS = {
    "employees_tenant_id_employee_no_key": Err("DUPLICATE_EMPLOYEE_NO", "employee number already exists", "ce matricule existe déjà"),
    "hr_employees_badge_key": Err(
        "BADGE_TAKEN", "this badge number is already given to another employee", "ce numéro de badge est déjà attribué à un autre employé"
    ),
    "hr_employees_user_key": Err(
        "USER_ALREADY_LINKED", "this user account is already linked to another employee", "ce compte utilisateur est déjà lié à un autre employé"
    ),
}
_NOT_FOUND = Err("NOT_FOUND", "employee not found", "employé introuvable")
_REFERENCES = (
    ("department_id", "hr.departments", "department", "département"),
    ("position_id", "hr.positions", "position", "poste"),
    ("grade_id", "hr.grades", "grade", "catégorie"),
)
_INSERT = f"INSERT INTO hr.employees (id, tenant_id, {', '.join(FIELDS)}) VALUES ({', '.join(['%s'] * (len(FIELDS) + 2))})"
_UPDATE = "UPDATE hr.employees SET " + ", ".join(f"{name} = %s" for name in EDITABLE_FIELDS) + " WHERE id = %s AND tenant_id = %s"
_FILE_COLUMNS = ", ".join(f"e.{name}" for name in FIELDS)
_SELECT_FILE = f"""
    SELECT e.id, {_FILE_COLUMNS}, d.name, p.title, g.code, u.email
    FROM hr.employees e
    LEFT JOIN hr.departments d ON d.id = e.department_id
    LEFT JOIN hr.positions p ON p.id = e.position_id
    LEFT JOIN hr.grades g ON g.id = e.grade_id
    LEFT JOIN core.users u ON u.id = e.user_id
    WHERE e.id = %s AND e.tenant_id = %s
"""


def _file_record(row) -> dict:
    count = len(FIELDS)
    employee = EmployeeFile(*row[1 : 1 + count])
    department_name, position_title, grade_code, user_email = row[1 + count :]
    return {
        "id": row[0],
        **iso_dates(asdict(employee)),
        "full_name": f"{employee.first_name} {employee.last_name}",
        "department_name": department_name,
        "position_title": position_title,
        "grade_code": grade_code,
        "user_email": user_email,
    }


class EmployeeService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_employees(self, tenant_id: str, status: str | None = None, *, today: datetime.date | None = None) -> list[dict]:
        """Every file of the tenant with its place and the contract in force on `today`.
        No sensitive field is selected here."""
        day = today or datetime.date.today()
        params: list[object] = [day, day, tenant_id]
        clause = "WHERE e.tenant_id = %s"
        if status:
            clause += " AND e.status = %s"
            params.append(status)
        rows = self.connection.execute(
            f"""
            SELECT e.id, e.employee_no, e.first_name, e.last_name, e.email, e.phone, e.department_id, d.name,
                   e.job_title, e.hire_date, e.status, e.position_id, p.title, e.grade_id, g.code, e.site,
                   e.badge_no, e.user_id, e.termination_date, c.contract_type, c.end_date
            FROM hr.employees e
            LEFT JOIN hr.departments d ON d.id = e.department_id
            LEFT JOIN hr.positions p ON p.id = e.position_id
            LEFT JOIN hr.grades g ON g.id = e.grade_id
            LEFT JOIN LATERAL (
                SELECT contract_type, end_date FROM hr.contracts
                WHERE employee_id = e.id AND tenant_id = e.tenant_id AND status <> 'draft'
                  AND start_date <= %s AND (end_date IS NULL OR end_date >= %s)
                ORDER BY start_date DESC
                LIMIT 1
            ) c ON TRUE
            {clause}
            ORDER BY e.last_name, e.first_name
            """,
            params,
        ).fetchall()
        return [
            {
                "id": r[0],
                "employee_no": r[1],
                "first_name": r[2],
                "last_name": r[3],
                "full_name": f"{r[2]} {r[3]}",
                "email": r[4],
                "phone": r[5],
                "department_id": r[6],
                "department_name": r[7],
                "job_title": r[8],
                "hire_date": r[9].isoformat(),
                "status": r[10],
                "position_id": r[11],
                "position_title": r[12],
                "grade_id": r[13],
                "grade_code": r[14],
                "site": r[15],
                "badge_no": r[16],
                "user_id": r[17],
                "termination_date": r[18].isoformat() if r[18] else None,
                "contract_type": r[19],
                "contract_end_date": r[20].isoformat() if r[20] else None,
            }
            for r in rows
        ]

    def get_employee(self, *, tenant_id: str, employee_id: str) -> dict | None:
        row = self.connection.execute(_SELECT_FILE, (employee_id, tenant_id)).fetchone()
        return None if row is None else _file_record(row)

    def get_by_user(self, *, tenant_id: str, user_id: str) -> dict | None:
        """The file of the employee who signs in as `user_id`, unmasked: it is their own."""
        row = self.connection.execute(
            "SELECT id FROM hr.employees WHERE tenant_id = %s AND user_id = %s", (tenant_id, user_id)
        ).fetchone()
        return None if row is None else self.get_employee(tenant_id=tenant_id, employee_id=row[0])

    def create_employee(self, *, tenant_id: str, actor_id: str, employee: EmployeeFile) -> Result[dict]:
        validated = validate_employee_file(employee)
        if isinstance(validated, Err):
            return validated
        candidate = validated.value
        if candidate.status == "terminated":
            return Err("INVALID_STATUS", "a new employee cannot start as having left", "un nouvel employé ne peut pas être créé déjà sorti")
        refused = self._missing_references(tenant_id, candidate)
        if refused:
            return refused
        employee_id = str(ULID())
        refused = execute_guarded(
            self.connection, _INSERT, (employee_id, tenant_id, *(getattr(candidate, name) for name in FIELDS)), _UNIQUE_REFUSALS
        )
        if refused:
            return refused
        record_audit(
            self.connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="employee.created",
            entity_type="employee",
            entity_id=employee_id,
            payload={
                "employee_no": candidate.employee_no,
                "first_name": candidate.first_name,
                "last_name": candidate.last_name,
                "hire_date": candidate.hire_date.isoformat(),
                "sensitive_set": [name for name in EMPLOYEE_FIELDS if getattr(candidate, name) is not None],
            },
        )
        return Ok(self.get_employee(tenant_id=tenant_id, employee_id=employee_id))

    def update_employee(self, *, tenant_id: str, actor_id: str, employee_id: str, changes: Mapping[str, object]) -> Result[dict]:
        """Edit in place (hr.admin_employees). Leaving is not an edit: it closes the contract too,
        so status 'terminated' is only reached through terminate_employee."""
        unknown = sorted(set(changes) - set(EDITABLE_FIELDS))
        if unknown:
            return Err(
                "INVALID_EMPLOYEE", f"these fields cannot be edited: {', '.join(unknown)}", f"ces champs ne sont pas modifiables : {', '.join(unknown)}"
            )
        current = self._locked(tenant_id, employee_id)
        if current is None:
            return _NOT_FOUND
        validated = validate_employee_file(replace(current, **changes))
        if isinstance(validated, Err):
            return validated
        candidate = validated.value
        if candidate.status == "terminated" and current.status != "terminated":
            return Err(
                "INVALID_TRANSITION",
                "an employee leaves through the exit action, which also closes the contract",
                "un employé sort par l'action de sortie, qui clôt aussi son contrat",
            )
        refused = self._missing_references(tenant_id, candidate)
        if refused:
            return refused
        refused = execute_guarded(
            self.connection, _UPDATE, (*(getattr(candidate, name) for name in EDITABLE_FIELDS), employee_id, tenant_id), _UNIQUE_REFUSALS
        )
        if refused:
            return refused
        record_audit(
            self.connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="employee.updated",
            entity_type="employee",
            entity_id=employee_id,
            payload=change_payload(asdict(current), asdict(candidate), EMPLOYEE_FIELDS),
        )
        return Ok(self.get_employee(tenant_id=tenant_id, employee_id=employee_id))

    def _locked(self, tenant_id: str, employee_id: str) -> EmployeeFile | None:
        row = self.connection.execute(
            f"SELECT {', '.join(FIELDS)} FROM hr.employees WHERE id = %s AND tenant_id = %s FOR UPDATE", (employee_id, tenant_id)
        ).fetchone()
        return None if row is None else EmployeeFile(*row)

    def _missing_references(self, tenant_id: str, employee: EmployeeFile) -> Err | None:
        for field_name, table, label_en, label_fr in _REFERENCES:
            refused = missing_reference(self.connection, table, tenant_id, getattr(employee, field_name), label_en, label_fr)
            if refused:
                return refused
        if employee.user_id is not None:
            found = self.connection.execute(
                "SELECT 1 FROM core.users WHERE id = %s AND tenant_id = %s", (employee.user_id, tenant_id)
            ).fetchone()
            if found is None:
                return Err("NOT_FOUND", "user account not found", "compte utilisateur introuvable")
        return None
```

Replace `backend/modules/hr/api/service.py` with (the `LeaveService` code is unchanged from today's file; the two re-exports keep `from modules.hr.api.service import EmployeeService, DepartmentService` working for the dashboard and for phase 5):

```python
from __future__ import annotations

import datetime

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.domain.entities import validate_leave

# Re-exported: the dashboard route and later phases (phase 5: EmployeeService.get_by_user)
# import these from here.
from modules.hr.api.employee_service import EmployeeService  # noqa: F401
from modules.hr.api.organisation_service import DepartmentService  # noqa: F401


class LeaveService:
    def __init__(self, connection: psycopg.Connection) -> None: self.connection = connection

    def list_requests(self, tenant_id: str, status: str | None = None) -> list[dict]:
        params: list[object] = [tenant_id]; clause = "WHERE l.tenant_id=%s"
        if status: clause += " AND l.status=%s"; params.append(status)
        rows = self.connection.execute(f"SELECT l.id,l.employee_id,e.first_name,e.last_name,l.leave_type,l.start_date,l.end_date,l.reason,l.status,l.reviewed_by FROM hr.leave_requests l JOIN hr.employees e ON e.id=l.employee_id {clause} ORDER BY l.start_date DESC", params).fetchall()
        return [{"id":r[0],"employee_id":r[1],"employee_name":f"{r[2]} {r[3]}","leave_type":r[4],"start_date":r[5].isoformat(),"end_date":r[6].isoformat(),"reason":r[7],"status":r[8],"reviewed_by":r[9]} for r in rows]

    def create_request(self, *, tenant_id: str, actor_id: str, employee_id: str, leave_type: str, start_date: datetime.date, end_date: datetime.date, reason: str | None) -> Result[dict]:
        validation = validate_leave(start_date=start_date, end_date=end_date)
        if isinstance(validation, Err): return validation
        if self.connection.execute("SELECT 1 FROM hr.employees WHERE id=%s AND tenant_id=%s", (employee_id, tenant_id)).fetchone() is None: return Err("NOT_FOUND", "employee not found", "employé introuvable")
        request_id = str(ULID()); self.connection.execute("INSERT INTO hr.leave_requests (id,tenant_id,employee_id,leave_type,start_date,end_date,reason) VALUES (%s,%s,%s,%s,%s,%s,%s)", (request_id,tenant_id,employee_id,leave_type,start_date,end_date,reason))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="leave_request.created", entity_type="leave_request", entity_id=request_id, payload={"employee_id":employee_id,"start_date":start_date.isoformat(),"end_date":end_date.isoformat()})
        return Ok({"id":request_id,"employee_id":employee_id,"leave_type":leave_type,"start_date":start_date.isoformat(),"end_date":end_date.isoformat(),"reason":reason,"status":"pending"})

    def review_request(self, *, tenant_id: str, actor_id: str, request_id: str, status: str) -> Result[dict]:
        if status not in {"approved", "rejected", "cancelled"}: return Err("INVALID_STATUS", "invalid leave decision", "décision de congé invalide")
        row = self.connection.execute("SELECT employee_id, leave_type, start_date, end_date, reason, status FROM hr.leave_requests WHERE id=%s AND tenant_id=%s FOR UPDATE", (request_id,tenant_id)).fetchone()
        if row is None: return Err("NOT_FOUND", "leave request not found", "demande de congé introuvable")
        if row[5] != "pending": return Err("INVALID_TRANSITION", "only pending leave can be reviewed", "seul un congé en attente peut être passé en revue")
        self.connection.execute("UPDATE hr.leave_requests SET status=%s, reviewed_by=%s WHERE id=%s AND tenant_id=%s", (status,actor_id,request_id,tenant_id))
        record_audit(self.connection, tenant_id=tenant_id, actor_id=actor_id, action="leave_request.status_changed", entity_type="leave_request", entity_id=request_id, payload={"from_status":"pending","to_status":status})
        return Ok({"id":request_id,"employee_id":row[0],"leave_type":row[1],"start_date":row[2].isoformat(),"end_date":row[3].isoformat(),"reason":row[4],"status":status,"reviewed_by":actor_id})
```

- [ ] **Step 6: Add the bodies and routes**

Append to `backend/modules/hr/api/schemas.py`:

```python
class EmployeeCreate(BaseModel):
    employee_no: str
    first_name: str
    last_name: str
    hire_date: datetime.date
    status: str = "active"
    email: str | None = None
    phone: str | None = None
    department_id: str | None = None
    job_title: str | None = None
    user_id: str | None = None
    gender: str | None = None
    birth_date: datetime.date | None = None
    birth_place: str | None = None
    nationality: str | None = None
    national_id: str | None = None
    inps_no: str | None = None
    amo_no: str | None = None
    marital_status: str | None = None
    address: str | None = None
    emergency_contact: str | None = None
    badge_no: str | None = None
    position_id: str | None = None
    grade_id: str | None = None
    site: str | None = None


class EmployeePatch(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    hire_date: datetime.date | None = None
    status: str | None = None
    email: str | None = None
    phone: str | None = None
    department_id: str | None = None
    job_title: str | None = None
    user_id: str | None = None
    gender: str | None = None
    birth_date: datetime.date | None = None
    birth_place: str | None = None
    nationality: str | None = None
    national_id: str | None = None
    inps_no: str | None = None
    amo_no: str | None = None
    marital_status: str | None = None
    address: str | None = None
    emergency_contact: str | None = None
    badge_no: str | None = None
    position_id: str | None = None
    grade_id: str | None = None
    site: str | None = None
    termination_date: datetime.date | None = None
    termination_reason: str | None = None
```

In `backend/modules/hr/api/router.py`: delete `class EmployeeBody(BaseModel):` and the three legacy handlers `employees()`, `create_employee()` and `update_employee()`. Extend the imports:

```python
from modules.hr.api.access import can_view_sensitive, require_sensitive_for
from modules.hr.api.schemas import EmployeeCreate, EmployeePatch
from modules.hr.domain.employee import EmployeeFile
from modules.hr.domain.sensitive import EMPLOYEE_FIELDS, filled, mask, written
```

(merge `EmployeeCreate, EmployeePatch` into the existing `from modules.hr.api.schemas import ...` line) and append at the end of the file:

```python
# ---- the employee file ------------------------------------------------------------------------

_EMPLOYEE_NOT_FOUND = Err("NOT_FOUND", "employee not found", "employé introuvable")


@router.get("/employees")
def list_employees(status_filter: str | None = None, tenant: TenantContext = Depends(require_permission("hr.view_employees"))):
    with get_connection() as connection:
        return EmployeeService(connection).list_employees(tenant.tenant_id, status_filter)


@router.get("/employees/{employee_id}")
def get_employee(employee_id: str, tenant: TenantContext = Depends(require_permission("hr.view_employees"))):
    with get_connection() as connection:
        record = EmployeeService(connection).get_employee(tenant_id=tenant.tenant_id, employee_id=employee_id)
        if record is None:
            fail(_EMPLOYEE_NOT_FOUND)
        return mask(record, EMPLOYEE_FIELDS, visible=can_view_sensitive(connection, tenant))


@router.post("/employees", status_code=status.HTTP_201_CREATED)
def create_employee(body: EmployeeCreate, tenant: TenantContext = Depends(require_permission("hr.manage_employees"))):
    data = body.model_dump()
    with get_connection() as connection:
        require_sensitive_for(connection, tenant, filled(data, EMPLOYEE_FIELDS))
        visible = can_view_sensitive(connection, tenant)
        result = EmployeeService(connection).create_employee(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, employee=EmployeeFile(**data)
        )
        return mask(respond(connection, result), EMPLOYEE_FIELDS, visible=visible)


@router.patch("/employees/{employee_id}")
def update_employee(employee_id: str, body: EmployeePatch, tenant: TenantContext = Depends(require_permission("hr.admin_employees"))):
    changes = body.model_dump(exclude_unset=True)
    with get_connection() as connection:
        require_sensitive_for(connection, tenant, written(changes, EMPLOYEE_FIELDS))
        visible = can_view_sensitive(connection, tenant)
        result = EmployeeService(connection).update_employee(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, employee_id=employee_id, changes=changes
        )
        return mask(respond(connection, result), EMPLOYEE_FIELDS, visible=visible)
```

The legacy `dashboard()` handler keeps calling `EmployeeService(connection).list_employees(tenant.tenant_id)` unchanged.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr core/test_error_translations.py -q`
Expected: PASS (integration tests counted as passed).

- [ ] **Step 8: Commit**

```bash
git add backend/modules/hr/migrations/0004_hr_employee_file.sql backend/modules/hr/domain/employee.py backend/modules/hr/domain/test_employee.py backend/modules/hr/domain/entities.py backend/modules/hr/api/employee_service.py backend/modules/hr/api/service.py backend/modules/hr/api/schemas.py backend/modules/hr/api/router.py backend/modules/hr/api/test_employee_integration.py backend/modules/hr/api/test_employee_routes_integration.py
git commit -m "feat(hr): full employee file with unique badge, linked user and masked social numbers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Family and payment — dependants and payment arrangements

**Files:**
- Create: `backend/modules/hr/migrations/0005_hr_dependants_payment_methods.sql`
- Create: `backend/modules/hr/domain/dependant.py`, `backend/modules/hr/domain/test_dependant.py`
- Create: `backend/modules/hr/domain/payment.py`, `backend/modules/hr/domain/test_payment.py`
- Create: `backend/modules/hr/api/dependant_service.py`, `backend/modules/hr/api/payment_method_service.py`
- Modify: `backend/modules/hr/api/schemas.py` (append), `backend/modules/hr/api/router.py` (append)
- Modify: `backend/scripts/reset_operational_data.py`
- Test: `backend/modules/hr/api/test_family_integration.py`, `backend/modules/hr/api/test_family_routes_integration.py`

**Interfaces:**
- Consumes: `support.*` (Task 2), `EmployeeService` (Task 3), `access.*`, `sensitive.*`, `respond`, `hr_api` (Task 1).
- Produces: `modules.hr.domain.dependant` — `DEPENDANT_KINDS`, `Dependant(kind, name, valid_from, birth_date=None, dependent_for_tax=False, valid_to=None)`, `validate_dependant(Dependant) -> Result[Dependant]`, `is_tax_dependant_on(Dependant, day) -> bool`, `count_tax_dependants(Iterable[Dependant], day) -> int`.
- Produces: `modules.hr.domain.payment` — `PAYMENT_METHODS`, `MOBILE_OPERATORS = ("orange_money", "moov_money")`, `PaymentMethod(method, share_percent: Decimal, is_primary=False, bank_name=None, account_no=None, mobile_operator=None, mobile_number=None)`, `validate_payment_set(Sequence[PaymentMethod]) -> Result[tuple[PaymentMethod, ...]]` (codes `PAYOUT_SPLIT_INVALID`, `INVALID_PAYMENT_METHOD`, `INVALID_CHOICE`), `set_in_force(starts, day) -> date | None`.
- Produces: `DependantService.list_dependants(*, tenant_id, employee_id, today=None)` (each dict: `id, employee_id, kind, name, valid_from, birth_date, dependent_for_tax, valid_to, counts_for_tax_today`), `create_dependant(*, tenant_id, actor_id, employee_id, dependant)`, `update_dependant(*, tenant_id, actor_id, dependant_id, changes)`; `PaymentMethodService.list_sets(*, tenant_id, employee_id, today=None) -> list[{valid_from, in_force, methods: [{id, method, bank_name, account_no, mobile_operator, mobile_number, share_percent, is_primary}]}]` (newest first), `set_exists(*, tenant_id, employee_id, valid_from) -> bool`, `replace_set(*, tenant_id, actor_id, employee_id, valid_from, methods) -> Result[list[dict]]` (empty `methods` removes the arrangement).
- Produces: routes `GET/POST /hr/employees/{id}/dependants`, `PATCH /hr/dependants/{id}` (`hr.admin_employees`); `GET /hr/employees/{id}/payment-methods` (masked), `PUT /hr/employees/{id}/payment-methods` (`hr.manage_employees` for a new start date, `hr.admin_employees` to replace an existing one, `hr.view_sensitive` when an account or phone number is set).

- [ ] **Step 1: Write the failing tests**

`backend/modules/hr/domain/test_dependant.py`:

```python
from datetime import date

from core.domain.result import Ok
from modules.hr.domain.dependant import Dependant, count_tax_dependants, validate_dependant


def test_a_dependant_needs_a_known_kind_and_a_name():
    assert validate_dependant(Dependant(kind="cousin", name="Issa", valid_from=date(2020, 1, 1))).code == "INVALID_CHOICE"
    assert validate_dependant(Dependant(kind="child", name=" ", valid_from=date(2020, 1, 1))).code == "INVALID_DEPENDANT"
    assert validate_dependant(Dependant(kind="child", name="Issa", valid_from=None)).code == "INVALID_DEPENDANT"


def test_the_name_is_trimmed():
    result = validate_dependant(Dependant(kind="child", name="  Issa ", valid_from=date(2020, 1, 1)))
    assert isinstance(result, Ok) and result.value.name == "Issa"


def test_validity_cannot_end_before_it_starts():
    refused = validate_dependant(Dependant(kind="child", name="Issa", valid_from=date(2020, 1, 1), valid_to=date(2019, 12, 31)))
    assert refused.code == "INVALID_DATES"


def test_a_dependant_cannot_count_before_being_born():
    refused = validate_dependant(Dependant(kind="child", name="Issa", birth_date=date(2021, 5, 1), valid_from=date(2021, 1, 1)))
    assert refused.code == "INVALID_DATES"


def test_the_tax_count_is_taken_on_the_given_day():
    spouse = Dependant(kind="spouse", name="Mariam", valid_from=date(2015, 6, 1), dependent_for_tax=True)
    child = Dependant(kind="child", name="Issa", birth_date=date(2019, 2, 1), valid_from=date(2019, 2, 1), dependent_for_tax=True, valid_to=date(2026, 9, 15))
    not_for_tax = Dependant(kind="child", name="Awa", valid_from=date(2010, 1, 1), dependent_for_tax=False)
    everyone = [spouse, child, not_for_tax]
    assert count_tax_dependants(everyone, date(2026, 9, 15)) == 2  # the last day of validity still counts
    assert count_tax_dependants(everyone, date(2026, 9, 30)) == 1
    assert count_tax_dependants(everyone, date(2015, 5, 31)) == 0
```

`backend/modules/hr/domain/test_payment.py`:

```python
from datetime import date
from decimal import Decimal

from core.domain.result import Ok
from modules.hr.domain.payment import PaymentMethod, set_in_force, validate_payment_set


def bank(share: str = "100", primary: bool = True) -> PaymentMethod:
    return PaymentMethod(method="bank", share_percent=Decimal(share), is_primary=primary, bank_name="BDM-SA", account_no="ML001 01001 000000000001 12")


def mobile(share: str, primary: bool = False) -> PaymentMethod:
    return PaymentMethod(method="mobile_money", share_percent=Decimal(share), is_primary=primary, mobile_operator="orange_money", mobile_number="76 00 00 00")


def test_one_bank_account_taking_everything_is_valid():
    assert isinstance(validate_payment_set([bank()]), Ok)


def test_a_split_must_add_up_to_exactly_one_hundred():
    assert isinstance(validate_payment_set([bank("70"), mobile("30")]), Ok)
    refused = validate_payment_set([bank("70"), mobile("20")])
    assert refused.code == "PAYOUT_SPLIT_INVALID" and "90" in refused.message


def test_a_share_has_at_most_two_decimals():
    """NUMERIC(5,2) would silently round 33.333 into a split that no longer adds up."""
    assert validate_payment_set([bank("33.333"), mobile("66.667")]).code == "PAYOUT_SPLIT_INVALID"
    cash = PaymentMethod(method="cash", share_percent=Decimal("33.34"))
    assert isinstance(validate_payment_set([bank("33.33"), mobile("33.33"), cash]), Ok)


def test_a_share_is_above_zero_and_at_most_one_hundred():
    assert validate_payment_set([bank("0"), mobile("100", primary=False)]).code == "PAYOUT_SPLIT_INVALID"
    assert validate_payment_set([bank("150"), mobile("-50")]).code == "PAYOUT_SPLIT_INVALID"


def test_exactly_one_method_is_primary():
    assert validate_payment_set([bank("50", primary=True), mobile("50", primary=True)]).code == "PAYOUT_SPLIT_INVALID"
    assert validate_payment_set([bank("50", primary=False), mobile("50")]).code == "PAYOUT_SPLIT_INVALID"


def test_a_bank_transfer_needs_the_account_and_mobile_money_a_known_operator_and_number():
    no_account = PaymentMethod(method="bank", share_percent=Decimal("100"), is_primary=True, bank_name="BDM-SA")
    assert validate_payment_set([no_account]).code == "INVALID_PAYMENT_METHOD"
    unknown_operator = PaymentMethod(method="mobile_money", share_percent=Decimal("100"), is_primary=True, mobile_operator="wave", mobile_number="1")
    assert validate_payment_set([unknown_operator]).code == "INVALID_PAYMENT_METHOD"
    assert validate_payment_set([PaymentMethod(method="cheque", share_percent=Decimal("100"), is_primary=True)]).code == "INVALID_CHOICE"


def test_cash_drops_details_that_do_not_apply():
    [cash] = validate_payment_set(
        [PaymentMethod(method="cash", share_percent=Decimal("100"), is_primary=True, bank_name="BDM-SA", account_no="x")]
    ).value
    assert (cash.bank_name, cash.account_no) == (None, None)


def test_an_empty_arrangement_is_refused():
    assert validate_payment_set([]).code == "PAYOUT_SPLIT_INVALID"


def test_the_arrangement_in_force_is_the_latest_started_on_or_before_the_day():
    starts = [date(2025, 1, 1), date(2026, 7, 1), date(2026, 10, 1)]
    assert set_in_force(starts, date(2026, 9, 30)) == date(2026, 7, 1)
    assert set_in_force(starts, date(2024, 12, 31)) is None
```

`backend/modules/hr/api/test_family_integration.py`:

```python
"""Dependants and payment arrangements against a real database (rolled back after each test)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.hr.api.dependant_service import DependantService
from modules.hr.api.payment_method_service import PaymentMethodService
from modules.hr.api.service import EmployeeService
from modules.hr.domain.dependant import Dependant
from modules.hr.domain.employee import EmployeeFile
from modules.hr.domain.payment import PaymentMethod

TENANT = "hr-family-test"


@pytest.fixture
def world(db):
    actor = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    employee = EmployeeService(db).create_employee(
        tenant_id=TENANT, actor_id=actor, employee=EmployeeFile(employee_no="F-001", first_name="Moussa", last_name="Keïta", hire_date=date(2015, 1, 5))
    ).value
    return SimpleNamespace(actor=actor, employee_id=employee["id"])


def bank(share: str = "100", primary: bool = True) -> PaymentMethod:
    return PaymentMethod(method="bank", share_percent=Decimal(share), is_primary=primary, bank_name="BDM-SA", account_no="ML-1")


def mobile(share: str = "100", primary: bool = False) -> PaymentMethod:
    return PaymentMethod(method="mobile_money", share_percent=Decimal(share), is_primary=primary, mobile_operator="orange_money", mobile_number="76 00 00 00")


def test_dependants_list_whether_they_count_for_tax_today(db, world):
    service = DependantService(db)
    service.create_dependant(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id,
        dependant=Dependant(kind="spouse", name="Mariam", valid_from=date(2015, 6, 1), dependent_for_tax=True),
    )
    service.create_dependant(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id,
        dependant=Dependant(kind="child", name="Issa", valid_from=date(2019, 2, 1), dependent_for_tax=True, valid_to=date(2020, 1, 1)),
    )
    listed = service.list_dependants(tenant_id=TENANT, employee_id=world.employee_id, today=date(2026, 9, 25))
    assert [(d["name"], d["counts_for_tax_today"]) for d in listed] == [("Mariam", True), ("Issa", False)]


def test_a_dependant_edit_is_validated_and_audited(db, world):
    service = DependantService(db)
    created = service.create_dependant(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id,
        dependant=Dependant(kind="child", name="Issa", valid_from=date(2019, 2, 1), dependent_for_tax=True),
    ).value
    refused = service.update_dependant(tenant_id=TENANT, actor_id=world.actor, dependant_id=created["id"], changes={"valid_to": date(2000, 1, 1)})
    assert isinstance(refused, Err) and refused.code == "INVALID_DATES"
    edited = service.update_dependant(tenant_id=TENANT, actor_id=world.actor, dependant_id=created["id"], changes={"dependent_for_tax": False})
    assert edited.value["dependent_for_tax"] is False
    actions = sorted(row[0] for row in db.execute("SELECT action FROM core.audit_log WHERE entity_id = %s", (created["id"],)).fetchall())
    assert actions == ["dependant.created", "dependant.updated"]


def test_a_dependant_of_an_unknown_employee_is_refused(db, world):
    refused = DependantService(db).create_dependant(
        tenant_id=TENANT, actor_id=world.actor, employee_id="nobody", dependant=Dependant(kind="child", name="Issa", valid_from=date(2019, 2, 1))
    )
    assert isinstance(refused, Err) and refused.code == "NOT_FOUND"


def test_an_arrangement_is_replaced_as_a_whole(db, world):
    service = PaymentMethodService(db)
    assert isinstance(service.replace_set(tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, valid_from=date(2025, 1, 1), methods=[bank()]), Ok)
    replaced = service.replace_set(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, valid_from=date(2025, 1, 1), methods=[bank("60"), mobile("40")]
    )
    [only] = replaced.value
    assert [(m["method"], m["share_percent"], m["is_primary"]) for m in only["methods"]] == [
        ("bank", Decimal("60.00"), True),
        ("mobile_money", Decimal("40.00"), False),
    ]


def test_a_later_arrangement_takes_over_on_its_date(db, world):
    service = PaymentMethodService(db)
    service.replace_set(tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, valid_from=date(2025, 1, 1), methods=[bank()])
    service.replace_set(tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, valid_from=date(2026, 10, 1), methods=[mobile(primary=True)])
    sets = service.list_sets(tenant_id=TENANT, employee_id=world.employee_id, today=date(2026, 9, 25))
    assert [(s["valid_from"], s["in_force"]) for s in sets] == [("2026-10-01", False), ("2025-01-01", True)]


def test_an_invalid_split_writes_nothing(db, world):
    service = PaymentMethodService(db)
    refused = service.replace_set(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, valid_from=date(2025, 1, 1), methods=[bank("70"), mobile("20")]
    )
    assert isinstance(refused, Err) and refused.code == "PAYOUT_SPLIT_INVALID"
    assert service.list_sets(tenant_id=TENANT, employee_id=world.employee_id) == []


def test_an_empty_list_removes_the_arrangement_and_the_audit_keeps_no_account_number(db, world):
    service = PaymentMethodService(db)
    service.replace_set(tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, valid_from=date(2025, 1, 1), methods=[bank()])
    assert service.replace_set(tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, valid_from=date(2025, 1, 1), methods=[]).value == []
    again = service.replace_set(tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, valid_from=date(2025, 1, 1), methods=[])
    assert isinstance(again, Err) and again.code == "NOT_FOUND"
    payloads = [row[0] for row in db.execute("SELECT payload FROM core.audit_log WHERE entity_id = %s", (world.employee_id,)).fetchall()]
    assert all("ML-1" not in str(payload) for payload in payloads)
```

`backend/modules/hr/api/test_family_routes_integration.py`:

```python
"""Dependants and payment arrangements over HTTP."""
from __future__ import annotations

BANK = {"method": "bank", "share_percent": 100, "is_primary": True, "bank_name": "BDM-SA", "account_no": "ML-1"}
CASH = {"method": "cash", "share_percent": 100, "is_primary": True}


def _employee(hr_api) -> str:
    hr_api.grant("hr.manage_employees", "hr.view_employees")
    body = {"employee_no": "R-001", "first_name": "Moussa", "last_name": "Keïta", "hire_date": "2015-01-05"}
    return hr_api.client.post("/hr/employees", json=body).json()["id"]


def test_bank_details_need_hr_view_sensitive_to_write_and_to_read(hr_api):
    employee_id = _employee(hr_api)
    url = f"/hr/employees/{employee_id}/payment-methods"
    body = {"valid_from": "2025-01-01", "methods": [BANK]}
    assert hr_api.client.put(url, json=body).status_code == 403
    hr_api.grant("hr.view_sensitive")
    saved = hr_api.client.put(url, json=body)
    assert saved.status_code == 200 and saved.json()[0]["methods"][0]["account_no"] == "ML-1"
    hr_api.db.execute("DELETE FROM core.user_permissions WHERE user_id = %s AND permission = 'hr.view_sensitive'", (hr_api.user_id,))
    method = hr_api.client.get(url).json()[0]["methods"][0]
    assert (method["account_no"], method["bank_name"], method["sensitive_hidden"]) == (None, "BDM-SA", True)


def test_a_cash_arrangement_needs_no_sensitive_right_but_replacing_one_needs_admin(hr_api):
    employee_id = _employee(hr_api)
    url = f"/hr/employees/{employee_id}/payment-methods"
    body = {"valid_from": "2025-01-01", "methods": [CASH]}
    assert hr_api.client.put(url, json=body).status_code == 200
    assert hr_api.client.put(url, json=body).status_code == 403
    hr_api.grant("hr.admin_employees")
    assert hr_api.client.put(url, json=body).status_code == 200


def test_a_bad_split_is_a_422_in_french_too(hr_api):
    employee_id = _employee(hr_api)
    body = {"valid_from": "2025-01-01", "methods": [{**CASH, "share_percent": 90}]}
    refused = hr_api.client.put(f"/hr/employees/{employee_id}/payment-methods", json=body)
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "PAYOUT_SPLIT_INVALID"
    assert refused.json()["detail"]["message_fr"] == "les parts totalisent 90 %, pas 100 %"


def test_dependants_are_added_with_manage_and_corrected_with_admin(hr_api):
    employee_id = _employee(hr_api)
    created = hr_api.client.post(
        f"/hr/employees/{employee_id}/dependants",
        json={"kind": "child", "name": "Issa", "valid_from": "2019-02-01", "dependent_for_tax": True},
    )
    assert created.status_code == 201
    assert hr_api.client.patch(f"/hr/dependants/{created.json()['id']}", json={"name": "Issa K."}).status_code == 403
    hr_api.grant("hr.admin_employees")
    assert hr_api.client.patch(f"/hr/dependants/{created.json()['id']}", json={"name": "Issa K."}).json()["name"] == "Issa K."
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_dependant.py modules/hr/domain/test_payment.py modules/hr/api/test_family_integration.py modules/hr/api/test_family_routes_integration.py -q`
Expected: FAIL — `No module named 'modules.hr.domain.dependant'` / `'modules.hr.domain.payment'`; routes answer 404.

- [ ] **Step 3: Write the migration and classify the tables**

`backend/modules/hr/migrations/0005_hr_dependants_payment_methods.sql`:

```sql
-- The people an employee supports (ITS family relief counts the tax dependants valid on the
-- last day of the pay period) and how their net pay reaches them.
CREATE TABLE IF NOT EXISTS hr.dependants (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL REFERENCES hr.employees (id),
    kind TEXT NOT NULL CONSTRAINT hr_dependants_kind_check CHECK (kind IN ('spouse', 'child')),
    name TEXT NOT NULL,
    birth_date DATE,
    dependent_for_tax BOOLEAN NOT NULL DEFAULT FALSE,
    valid_from DATE NOT NULL,
    valid_to DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT hr_dependants_validity_check CHECK (valid_to IS NULL OR valid_to >= valid_from)
);
CREATE INDEX IF NOT EXISTS hr_dependants_employee_idx ON hr.dependants (tenant_id, employee_id);

-- Payment methods come in arrangements: the arrangement in force on a date is the one with the
-- latest valid_from on or before it; its shares add up to 100 % and one method is primary.
CREATE TABLE IF NOT EXISTS hr.payment_methods (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL REFERENCES hr.employees (id),
    method TEXT NOT NULL CONSTRAINT hr_payment_methods_method_check CHECK (method IN ('bank', 'mobile_money', 'cash')),
    bank_name TEXT,
    account_no TEXT,
    mobile_operator TEXT CONSTRAINT hr_payment_methods_operator_check
        CHECK (mobile_operator IS NULL OR mobile_operator IN ('orange_money', 'moov_money')),
    mobile_number TEXT,
    share_percent NUMERIC(5,2) NOT NULL CONSTRAINT hr_payment_methods_share_check CHECK (share_percent > 0 AND share_percent <= 100),
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    valid_from DATE NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS hr_payment_methods_employee_idx ON hr.payment_methods (tenant_id, employee_id, valid_from);
CREATE UNIQUE INDEX IF NOT EXISTS hr_payment_methods_one_primary
    ON hr.payment_methods (tenant_id, employee_id, valid_from) WHERE is_primary;
```

In `backend/scripts/reset_operational_data.py`, add `"hr.dependants",` and `"hr.payment_methods",` to `PURGE_TABLES` right after `"hr.departments",`.

Apply it with the Global Constraints command. Expected: no output, exit 0.

- [ ] **Step 4: Write the domain rules**

`backend/modules/hr/domain/dependant.py`:

```python
"""The people an employee supports. ITS family relief (phase 3) counts the tax dependants valid
on the last day of the pay period. Pure rules, no database."""
from __future__ import annotations

import datetime
from collections.abc import Iterable
from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

DEPENDANT_KINDS = ("spouse", "child")


@dataclass(frozen=True)
class Dependant:
    kind: str
    name: str
    valid_from: datetime.date
    birth_date: datetime.date | None = None
    dependent_for_tax: bool = False
    valid_to: datetime.date | None = None


def validate_dependant(dependant: Dependant) -> Result[Dependant]:
    if dependant.kind not in DEPENDANT_KINDS:
        return Err("INVALID_CHOICE", "a dependant is a spouse or a child", "une personne à charge est un conjoint ou un enfant")
    name = (dependant.name or "").strip()
    if not name or dependant.valid_from is None:
        return Err("INVALID_DEPENDANT", "a dependant needs a name and a start date", "une personne à charge demande un nom et une date de début")
    if dependant.valid_to is not None and dependant.valid_to < dependant.valid_from:
        return Err("INVALID_DATES", "the validity cannot end before it starts", "la validité ne peut pas finir avant de commencer")
    if dependant.birth_date is not None and dependant.birth_date > dependant.valid_from:
        return Err("INVALID_DATES", "a dependant cannot count before being born", "une personne ne peut pas être à charge avant sa naissance")
    return Ok(
        Dependant(
            kind=dependant.kind,
            name=name,
            valid_from=dependant.valid_from,
            birth_date=dependant.birth_date,
            dependent_for_tax=dependant.dependent_for_tax,
            valid_to=dependant.valid_to,
        )
    )


def is_tax_dependant_on(dependant: Dependant, day: datetime.date) -> bool:
    return dependant.dependent_for_tax and dependant.valid_from <= day and (dependant.valid_to is None or dependant.valid_to >= day)


def count_tax_dependants(dependants: Iterable[Dependant], day: datetime.date) -> int:
    return sum(1 for dependant in dependants if is_tax_dependant_on(dependant, day))
```

`backend/modules/hr/domain/payment.py`:

```python
"""How net pay reaches an employee: one or more methods whose shares add up to 100 %.
Arrangements are dated: the one in force on a day is the latest that started on or before it.
Pure rules, no database."""
from __future__ import annotations

import datetime
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from core.domain.result import Err, Ok, Result

PAYMENT_METHODS = ("bank", "mobile_money", "cash")
MOBILE_OPERATORS = ("orange_money", "moov_money")
WHOLE = Decimal("100")
CENT = Decimal("0.01")


@dataclass(frozen=True)
class PaymentMethod:
    method: str
    share_percent: Decimal
    is_primary: bool = False
    bank_name: str | None = None
    account_no: str | None = None
    mobile_operator: str | None = None
    mobile_number: str | None = None


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalized(method: PaymentMethod) -> PaymentMethod:
    """Keep only the details that apply to the method: a cash line carries no account."""
    bank = method.method == "bank"
    mobile = method.method == "mobile_money"
    return PaymentMethod(
        method=method.method,
        share_percent=method.share_percent,
        is_primary=method.is_primary,
        bank_name=_text(method.bank_name) if bank else None,
        account_no=_text(method.account_no) if bank else None,
        mobile_operator=method.mobile_operator if mobile else None,
        mobile_number=_text(method.mobile_number) if mobile else None,
    )


def _split_refusal(message_en: str, message_fr: str) -> Err:
    return Err("PAYOUT_SPLIT_INVALID", message_en, message_fr)


def validate_payment_set(methods: Sequence[PaymentMethod]) -> Result[tuple[PaymentMethod, ...]]:
    if not methods:
        return _split_refusal("a payment arrangement needs at least one method", "un mode de paiement demande au moins une ligne")
    cleaned: list[PaymentMethod] = []
    for method in methods:
        if method.method not in PAYMENT_METHODS:
            return Err("INVALID_CHOICE", "a method is a bank transfer, mobile money or cash", "un mode est un virement, du mobile money ou des espèces")
        line = _normalized(method)
        if line.method == "bank" and (line.bank_name is None or line.account_no is None):
            return Err(
                "INVALID_PAYMENT_METHOD",
                "a bank transfer needs the bank and the account number (RIB)",
                "un virement demande la banque et le numéro de compte (RIB)",
            )
        if line.method == "mobile_money" and (line.mobile_operator not in MOBILE_OPERATORS or line.mobile_number is None):
            return Err("INVALID_PAYMENT_METHOD", "mobile money needs the operator and the number", "le mobile money demande l'opérateur et le numéro")
        share = line.share_percent
        # Checked before the database: NUMERIC(5,2) would round 33.333 silently.
        if share is None or not share.is_finite() or share <= 0 or share > WHOLE or share != share.quantize(CENT):
            return _split_refusal(
                "each share is above 0 %, at most 100 %, with at most two decimals",
                "chaque part est supérieure à 0 %, au plus 100 %, avec au plus deux décimales",
            )
        cleaned.append(line)
    total = sum((line.share_percent for line in cleaned), Decimal("0"))
    if total != WHOLE:
        return _split_refusal(f"the shares add up to {total} %, not 100 %", f"les parts totalisent {total} %, pas 100 %")
    if sum(1 for line in cleaned if line.is_primary) != 1:
        return _split_refusal("exactly one method is the primary one", "un seul mode doit être le principal")
    return Ok(tuple(cleaned))


def set_in_force(starts: Iterable[datetime.date], day: datetime.date) -> datetime.date | None:
    """The start date of the arrangement in force on `day`: the latest on or before it."""
    return max((start for start in starts if start <= day), default=None)
```

- [ ] **Step 5: Write the services**

`backend/modules/hr/api/dependant_service.py`:

```python
"""The people an employee supports: add, list, correct."""
from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import asdict, replace

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.support import change_payload, iso_dates, json_safe, missing_reference
from modules.hr.domain.dependant import Dependant, is_tax_dependant_on, validate_dependant

# Dependant's field order, which is also the column order used below.
_COLUMNS = ("kind", "name", "valid_from", "birth_date", "dependent_for_tax", "valid_to")
_SELECT = f"SELECT id, employee_id, {', '.join(_COLUMNS)} FROM hr.dependants"
_INSERT = f"INSERT INTO hr.dependants (id, tenant_id, employee_id, {', '.join(_COLUMNS)}) VALUES ({', '.join(['%s'] * (len(_COLUMNS) + 3))})"
_UPDATE = "UPDATE hr.dependants SET " + ", ".join(f"{name} = %s" for name in _COLUMNS) + " WHERE id = %s AND tenant_id = %s"


def _record(row, today: datetime.date) -> dict:
    dependant = Dependant(*row[2:])
    return {
        "id": row[0],
        "employee_id": row[1],
        **iso_dates(asdict(dependant)),
        "counts_for_tax_today": is_tax_dependant_on(dependant, today),
    }


class DependantService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_dependants(self, *, tenant_id: str, employee_id: str, today: datetime.date | None = None) -> list[dict]:
        day = today or datetime.date.today()
        rows = self.connection.execute(
            f"{_SELECT} WHERE tenant_id = %s AND employee_id = %s ORDER BY kind DESC, birth_date NULLS FIRST, name",
            (tenant_id, employee_id),
        ).fetchall()
        return [_record(row, day) for row in rows]

    def get_dependant(self, *, tenant_id: str, dependant_id: str) -> dict | None:
        row = self.connection.execute(f"{_SELECT} WHERE tenant_id = %s AND id = %s", (tenant_id, dependant_id)).fetchone()
        return None if row is None else _record(row, datetime.date.today())

    def create_dependant(self, *, tenant_id: str, actor_id: str, employee_id: str, dependant: Dependant) -> Result[dict]:
        refused = missing_reference(self.connection, "hr.employees", tenant_id, employee_id, "employee", "employé")
        if refused:
            return refused
        validated = validate_dependant(dependant)
        if isinstance(validated, Err):
            return validated
        clean = validated.value
        dependant_id = str(ULID())
        self.connection.execute(_INSERT, (dependant_id, tenant_id, employee_id, *(getattr(clean, name) for name in _COLUMNS)))
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="dependant.created",
            entity_type="dependant", entity_id=dependant_id, payload={"employee_id": employee_id, **json_safe(clean)},
        )
        return Ok(self.get_dependant(tenant_id=tenant_id, dependant_id=dependant_id))

    def update_dependant(self, *, tenant_id: str, actor_id: str, dependant_id: str, changes: Mapping[str, object]) -> Result[dict]:
        row = self.connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM hr.dependants WHERE id = %s AND tenant_id = %s FOR UPDATE", (dependant_id, tenant_id)
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", "dependant not found", "personne à charge introuvable")
        current = Dependant(*row)
        validated = validate_dependant(replace(current, **changes))
        if isinstance(validated, Err):
            return validated
        clean = validated.value
        self.connection.execute(_UPDATE, (*(getattr(clean, name) for name in _COLUMNS), dependant_id, tenant_id))
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="dependant.updated",
            entity_type="dependant", entity_id=dependant_id, payload=change_payload(asdict(current), asdict(clean)),
        )
        return Ok(self.get_dependant(tenant_id=tenant_id, dependant_id=dependant_id))
```

`backend/modules/hr/api/payment_method_service.py`:

```python
"""Payment arrangements: dated sets of methods, always written as a whole so their shares add up."""
from __future__ import annotations

import datetime
from collections.abc import Sequence

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.domain.payment import PaymentMethod, set_in_force, validate_payment_set


class PaymentMethodService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def list_sets(self, *, tenant_id: str, employee_id: str, today: datetime.date | None = None) -> list[dict]:
        """Every arrangement of the employee, newest first, flagging the one in force on `today`."""
        day = today or datetime.date.today()
        rows = self.connection.execute(
            """
            SELECT id, method, bank_name, account_no, mobile_operator, mobile_number, share_percent, is_primary, valid_from
            FROM hr.payment_methods
            WHERE tenant_id = %s AND employee_id = %s
            ORDER BY valid_from DESC, sort_order
            """,
            (tenant_id, employee_id),
        ).fetchall()
        in_force = set_in_force((row[8] for row in rows), day)
        sets: dict[datetime.date, dict] = {}
        for row in rows:
            entry = sets.setdefault(row[8], {"valid_from": row[8].isoformat(), "in_force": row[8] == in_force, "methods": []})
            entry["methods"].append(
                {
                    "id": row[0],
                    "method": row[1],
                    "bank_name": row[2],
                    "account_no": row[3],
                    "mobile_operator": row[4],
                    "mobile_number": row[5],
                    "share_percent": row[6],
                    "is_primary": row[7],
                }
            )
        return list(sets.values())

    def set_exists(self, *, tenant_id: str, employee_id: str, valid_from: datetime.date) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM hr.payment_methods WHERE tenant_id = %s AND employee_id = %s AND valid_from = %s LIMIT 1",
            (tenant_id, employee_id, valid_from),
        ).fetchone()
        return row is not None

    def replace_set(
        self, *, tenant_id: str, actor_id: str, employee_id: str, valid_from: datetime.date, methods: Sequence[PaymentMethod]
    ) -> Result[list[dict]]:
        """Write the arrangement starting on `valid_from` as a whole; an empty list removes it."""
        employee = self.connection.execute(
            "SELECT 1 FROM hr.employees WHERE id = %s AND tenant_id = %s FOR UPDATE", (employee_id, tenant_id)
        ).fetchone()
        if employee is None:
            return Err("NOT_FOUND", "employee not found", "employé introuvable")
        existed = self.set_exists(tenant_id=tenant_id, employee_id=employee_id, valid_from=valid_from)
        if not methods:
            if not existed:
                return Err("NOT_FOUND", "no payment arrangement starts on that date", "aucun mode de paiement ne commence à cette date")
            lines: tuple[PaymentMethod, ...] = ()
        else:
            validated = validate_payment_set(methods)
            if isinstance(validated, Err):
                return validated
            lines = validated.value
        self.connection.execute(
            "DELETE FROM hr.payment_methods WHERE tenant_id = %s AND employee_id = %s AND valid_from = %s", (tenant_id, employee_id, valid_from)
        )
        for order, line in enumerate(lines):
            self.connection.execute(
                """
                INSERT INTO hr.payment_methods (id, tenant_id, employee_id, method, bank_name, account_no, mobile_operator,
                                                mobile_number, share_percent, is_primary, valid_from, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(ULID()), tenant_id, employee_id, line.method, line.bank_name, line.account_no, line.mobile_operator,
                    line.mobile_number, line.share_percent, line.is_primary, valid_from, order,
                ),
            )
        action = "payment_methods.removed" if not lines else "payment_methods.replaced" if existed else "payment_methods.created"
        record_audit(
            self.connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            entity_type="employee",
            entity_id=employee_id,
            # Kinds and shares only: account and phone numbers stay out of the audit log.
            payload={
                "valid_from": valid_from.isoformat(),
                "methods": [{"method": line.method, "share_percent": str(line.share_percent), "is_primary": line.is_primary} for line in lines],
            },
        )
        return Ok(self.list_sets(tenant_id=tenant_id, employee_id=employee_id))
```

- [ ] **Step 6: Add the bodies and routes**

Append to `backend/modules/hr/api/schemas.py`:

```python
class DependantCreate(BaseModel):
    kind: str
    name: str
    valid_from: datetime.date
    birth_date: datetime.date | None = None
    dependent_for_tax: bool = False
    valid_to: datetime.date | None = None


class DependantPatch(BaseModel):
    kind: str | None = None
    name: str | None = None
    valid_from: datetime.date | None = None
    birth_date: datetime.date | None = None
    dependent_for_tax: bool = False  # never null: only sent when it changes
    valid_to: datetime.date | None = None


class PaymentMethodBody(BaseModel):
    method: str
    share_percent: Decimal
    is_primary: bool = False
    bank_name: str | None = None
    account_no: str | None = None
    mobile_operator: str | None = None
    mobile_number: str | None = None


class PaymentSetBody(BaseModel):
    valid_from: datetime.date
    methods: list[PaymentMethodBody]
```

In `backend/modules/hr/api/router.py`, extend the imports (merge into the existing `access`, `schemas` and `sensitive` import lines):

```python
from modules.hr.api.access import require
from modules.hr.api.dependant_service import DependantService
from modules.hr.api.payment_method_service import PaymentMethodService
from modules.hr.api.schemas import DependantCreate, DependantPatch, PaymentSetBody
from modules.hr.domain.dependant import Dependant
from modules.hr.domain.payment import PaymentMethod
from modules.hr.domain.sensitive import PAYMENT_FIELDS
```

and append at the end of the file:

```python
# ---- family and payment -----------------------------------------------------------------------


def _masked_sets(sets: list[dict], visible: bool) -> list[dict]:
    return [{**entry, "methods": [mask(method, PAYMENT_FIELDS, visible=visible) for method in entry["methods"]]} for entry in sets]


@router.get("/employees/{employee_id}/dependants")
def list_dependants(employee_id: str, tenant: TenantContext = Depends(require_permission("hr.view_employees"))):
    with get_connection() as connection:
        return DependantService(connection).list_dependants(tenant_id=tenant.tenant_id, employee_id=employee_id)


@router.post("/employees/{employee_id}/dependants", status_code=status.HTTP_201_CREATED)
def create_dependant(employee_id: str, body: DependantCreate, tenant: TenantContext = Depends(require_permission("hr.manage_employees"))):
    with get_connection() as connection:
        result = DependantService(connection).create_dependant(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, employee_id=employee_id, dependant=Dependant(**body.model_dump())
        )
        return respond(connection, result)


@router.patch("/dependants/{dependant_id}")
def update_dependant(dependant_id: str, body: DependantPatch, tenant: TenantContext = Depends(require_permission("hr.admin_employees"))):
    with get_connection() as connection:
        result = DependantService(connection).update_dependant(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, dependant_id=dependant_id, changes=body.model_dump(exclude_unset=True)
        )
        return respond(connection, result)


@router.get("/employees/{employee_id}/payment-methods")
def list_payment_methods(employee_id: str, tenant: TenantContext = Depends(require_permission("hr.view_employees"))):
    with get_connection() as connection:
        sets = PaymentMethodService(connection).list_sets(tenant_id=tenant.tenant_id, employee_id=employee_id)
        return _masked_sets(sets, can_view_sensitive(connection, tenant))


@router.put("/employees/{employee_id}/payment-methods")
def replace_payment_methods(employee_id: str, body: PaymentSetBody, tenant: TenantContext = Depends(require_permission("hr.manage_employees"))):
    """A new start date is a creation (hr.manage_employees); replacing or removing an existing
    arrangement is an edit (hr.admin_employees). Account and phone numbers need hr.view_sensitive."""
    methods = [method.model_dump() for method in body.methods]
    with get_connection() as connection:
        service = PaymentMethodService(connection)
        if service.set_exists(tenant_id=tenant.tenant_id, employee_id=employee_id, valid_from=body.valid_from):
            require(connection, tenant, "hr.admin_employees")
        require_sensitive_for(connection, tenant, [name for method in methods for name in filled(method, PAYMENT_FIELDS)])
        visible = can_view_sensitive(connection, tenant)
        result = service.replace_set(
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            employee_id=employee_id,
            valid_from=body.valid_from,
            methods=[PaymentMethod(**method) for method in methods],
        )
        return _masked_sets(respond(connection, result), visible)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr core/test_error_translations.py scripts/test_reset_operational_data_integration.py -q`
Expected: PASS (integration tests counted as passed).

- [ ] **Step 8: Commit**

```bash
git add backend/modules/hr/migrations/0005_hr_dependants_payment_methods.sql backend/modules/hr/domain/dependant.py backend/modules/hr/domain/test_dependant.py backend/modules/hr/domain/payment.py backend/modules/hr/domain/test_payment.py backend/modules/hr/api/dependant_service.py backend/modules/hr/api/payment_method_service.py backend/modules/hr/api/schemas.py backend/modules/hr/api/router.py backend/modules/hr/api/test_family_integration.py backend/modules/hr/api/test_family_routes_integration.py backend/scripts/reset_operational_data.py
git commit -m "feat(hr): dependants and dated payment arrangements with validated splits

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Contracts — types, terms, components, activate / end / amend

**Files:**
- Create: `backend/modules/hr/migrations/0006_hr_contract_terms.sql`
- Create: `backend/modules/hr/domain/contract.py`, `backend/modules/hr/domain/test_contract.py`
- Rewrite: `backend/modules/hr/api/contract_service.py`
- Modify: `backend/modules/hr/api/schemas.py` (append), `backend/modules/hr/api/router.py` (replace the legacy contract routes)
- Modify: `backend/scripts/reset_operational_data.py`, `backend/scripts/seed_dev.py:71-95, 131-144`
- Test: `backend/modules/hr/api/test_contract_integration.py`, `backend/modules/hr/api/test_contract_routes_integration.py`

**Interfaces:**
- Consumes: `support.*` (Task 2), `EmployeeService` (Task 3), `END_REASONS` (Task 3), `sensitive.*`, `access.*`, `respond`, `fail`, `hr_api` (Task 1).
- Produces: `modules.hr.domain.contract` — `CONTRACT_TYPES = ("cdi", "cdd", "apprentice", "daily", "intern")`, `PAY_FREQUENCIES = ("monthly", "daily")`, `CONTRACT_STATUSES = ("draft", "active", "expired", "terminated")`, `ContractComponent(component_code, amount: Decimal | None = None, rate: Decimal | None = None)`, `ContractTerms(employee_id, contract_type, start_date, base_salary, end_date=None, trial_end_date=None, weekly_hours=Decimal("40"), pay_frequency="monthly", position_id=None, grade_id=None, status="active", amends_contract_id=None, end_reason=None, components=())`, `COLUMNS` (stored column names in `ContractTerms` order, without `components`), `ContractPeriod(id, start_date, end_date, status)`, `validate_components(...)`, `validate_terms(ContractTerms) -> Result[ContractTerms]`, `overlapping(candidate, others) -> ContractPeriod | None` (drafts never count), `overlap_refusal(ContractPeriod) -> Err` (`CONTRACT_OVERLAP`), `end_status(end_reason) -> "expired" | "terminated"`.
- Produces: `ContractService(connection)` — `list_contracts(tenant_id, employee_id=None) -> list[dict]` and `get_contract(*, tenant_id, contract_id) -> dict | None` (keys: `id` + every `COLUMNS` name, dates ISO, `base_salary`/`weekly_hours` Decimal, `currency, employee_name, position_title, grade_code, components: [{component_code, amount, rate}]`), `create_contract(*, tenant_id, actor_id, terms) -> Result[dict]`, `update_contract(*, tenant_id, actor_id, contract_id, changes)`, `activate_contract(*, tenant_id, actor_id, contract_id)`, `end_contract(*, tenant_id, actor_id, contract_id, end_date, end_reason)`, `amend_contract(*, tenant_id, actor_id, contract_id, effective_date, changes) -> Result[dict]` (the new contract); private `_locked_terms`, `_close` used by Task 7.
- Produces: routes `GET /hr/contracts?employee_id=` and `GET /hr/contracts/{id}` (`hr.view_contracts`, masked), `POST /hr/contracts` (`hr.manage_contracts` + `hr.view_sensitive`), `PATCH /hr/contracts/{id}` (`hr.admin_contracts`; pay/components need `hr.view_sensitive`), `POST /hr/contracts/{id}/activate`, `POST /hr/contracts/{id}/end`, `POST /hr/contracts/{id}/amend` (`hr.manage_contracts`).
- Produces: table `hr.contract_components (id, tenant_id, contract_id, component_code, amount NUMERIC(18,0), rate NUMERIC(9,4) percent)`.

- [ ] **Step 1: Write the failing tests**

`backend/modules/hr/domain/test_contract.py`:

```python
import datetime
from decimal import Decimal

from core.domain.result import Ok
from modules.hr.domain.contract import (
    ContractComponent,
    ContractPeriod,
    ContractTerms,
    end_status,
    overlapping,
    validate_components,
    validate_terms,
)

D = datetime.date


def _terms(**overrides) -> ContractTerms:
    return ContractTerms(**{"employee_id": "e1", "contract_type": "cdd", "start_date": D(2026, 1, 1), "base_salary": Decimal("150000"), **overrides})


def test_valid_terms_come_back_with_their_components_cleaned():
    result = validate_terms(_terms(components=(ContractComponent(component_code=" transport ", amount=Decimal("15000")),)))
    assert isinstance(result, Ok)
    assert result.value.components == (ContractComponent(component_code="TRANSPORT", amount=Decimal("15000")),)


def test_an_unknown_contract_type_is_refused():
    assert validate_terms(_terms(contract_type="permanent")).code == "INVALID_CONTRACT_TYPE"


def test_pay_is_whole_francs():
    assert validate_terms(_terms(base_salary=Decimal("150000.50"))).code == "INVALID_AMOUNT"
    assert validate_terms(_terms(base_salary=None)).code == "INVALID_AMOUNT"


def test_weekly_hours_stay_within_a_week():
    assert validate_terms(_terms(weekly_hours=Decimal("0"))).code == "INVALID_CONTRACT"
    assert validate_terms(_terms(weekly_hours=Decimal("169"))).code == "INVALID_CONTRACT"
    assert validate_terms(_terms(weekly_hours=None)).code == "INVALID_CONTRACT"
    assert isinstance(validate_terms(_terms(weekly_hours=Decimal("48"))), Ok)


def test_dates_hold_together():
    assert validate_terms(_terms(start_date=None)).code == "INVALID_DATES"
    assert validate_terms(_terms(end_date=D(2025, 12, 31))).code == "INVALID_DATES"
    assert validate_terms(_terms(end_date=D(2026, 6, 30), trial_end_date=D(2026, 7, 1))).code == "INVALID_DATES"
    assert validate_terms(_terms(trial_end_date=D(2025, 12, 31))).code == "INVALID_DATES"


def test_an_end_reason_is_known_and_needs_an_end_date():
    assert validate_terms(_terms(end_reason="resignation")).code == "INVALID_END_REASON"
    assert validate_terms(_terms(end_date=D(2026, 6, 30), end_reason="bored")).code == "INVALID_END_REASON"


def test_a_component_has_an_amount_or_a_rate_never_both_or_neither():
    both = ContractComponent(component_code="HOUSING", amount=Decimal("1"), rate=Decimal("1"))
    neither = ContractComponent(component_code="HOUSING")
    assert validate_components([both]).code == "INVALID_COMPONENT"
    assert validate_components([neither]).code == "INVALID_COMPONENT"
    assert validate_components([ContractComponent(component_code="HOUSING", rate=Decimal("-1"))]).code == "INVALID_COMPONENT"
    assert validate_components([ContractComponent(component_code="9X", amount=Decimal("1"))]).code == "INVALID_COMPONENT"


def test_a_component_appears_once():
    twice = [ContractComponent(component_code="TRANSPORT", amount=Decimal("1")), ContractComponent(component_code="transport", amount=Decimal("2"))]
    assert validate_components(twice).code == "INVALID_COMPONENT"


def test_contracts_that_share_a_day_overlap():
    signed = ContractPeriod(id="a", start_date=D(2026, 1, 1), end_date=D(2026, 6, 30), status="active")
    assert overlapping(ContractPeriod(id="b", start_date=D(2026, 6, 30), end_date=None, status="active"), [signed]) == signed
    assert overlapping(ContractPeriod(id="b", start_date=D(2026, 7, 1), end_date=None, status="active"), [signed]) is None


def test_an_open_ended_contract_overlaps_everything_after_it():
    open_ended = ContractPeriod(id="a", start_date=D(2020, 1, 1), end_date=None, status="active")
    later = ContractPeriod(id="b", start_date=D(2030, 1, 1), end_date=D(2030, 2, 1), status="active")
    assert overlapping(later, [open_ended]) == open_ended


def test_drafts_never_conflict():
    signed = ContractPeriod(id="a", start_date=D(2026, 1, 1), end_date=None, status="active")
    draft = ContractPeriod(id="b", start_date=D(2026, 3, 1), end_date=None, status="draft")
    assert overlapping(draft, [signed]) is None
    assert overlapping(ContractPeriod(id="c", start_date=D(2026, 3, 1), end_date=None, status="active"), [draft]) is None


def test_a_contract_does_not_overlap_itself_and_ended_ones_keep_their_days():
    signed = ContractPeriod(id="a", start_date=D(2026, 1, 1), end_date=None, status="active")
    assert overlapping(signed, [signed]) is None
    ended = ContractPeriod(id="x", start_date=D(2025, 1, 1), end_date=D(2025, 12, 31), status="terminated")
    assert overlapping(ContractPeriod(id="b", start_date=D(2025, 6, 1), end_date=None, status="active"), [ended]) == ended


def test_a_term_or_an_amendment_expires_a_contract_anything_else_terminates_it():
    assert [end_status(reason) for reason in ("term_reached", "amended", "resignation", "dismissal")] == [
        "expired", "expired", "terminated", "terminated",
    ]
```

`backend/modules/hr/api/test_contract_integration.py`:

```python
"""Contracts against a real database (rolled back after each test)."""
from __future__ import annotations

import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.hr.api.contract_service import ContractService
from modules.hr.api.service import EmployeeService
from modules.hr.domain.contract import ContractComponent, ContractTerms
from modules.hr.domain.employee import EmployeeFile

TENANT = "hr-contract-test"
D = datetime.date


@pytest.fixture
def world(db):
    actor = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    employee = EmployeeService(db).create_employee(
        tenant_id=TENANT, actor_id=actor,
        employee=EmployeeFile(employee_no="C-001", first_name="Awa", last_name="Traoré", hire_date=D(2024, 1, 1)),
    ).value
    return SimpleNamespace(actor=actor, employee_id=employee["id"])


def _terms(world, **overrides) -> ContractTerms:
    return ContractTerms(
        **{"employee_id": world.employee_id, "contract_type": "cdi", "start_date": D(2024, 1, 1), "base_salary": Decimal("150000"), **overrides}
    )


def _create(db, world, **overrides):
    return ContractService(db).create_contract(tenant_id=TENANT, actor_id=world.actor, terms=_terms(world, **overrides))


def test_a_created_contract_reads_back_in_xof_with_its_components(db, world):
    created = _create(db, world, components=(ContractComponent(component_code="TRANSPORT", amount=Decimal("15000")),))
    assert isinstance(created, Ok)
    contract = created.value
    assert (contract["contract_type"], contract["base_salary"], contract["currency"], contract["weekly_hours"], contract["pay_frequency"]) == (
        "cdi", Decimal("150000"), "XOF", Decimal("40.00"), "monthly",
    )
    assert contract["components"] == [{"component_code": "TRANSPORT", "amount": Decimal("15000"), "rate": None}]
    # The legacy payroll screen still reads salary until phase 3 retires it.
    assert db.execute("SELECT salary FROM hr.contracts WHERE id = %s", (contract["id"],)).fetchone()[0] == Decimal("150000")


def test_a_second_signed_contract_on_the_same_days_is_refused_but_a_draft_is_not(db, world):
    assert isinstance(_create(db, world), Ok)
    refused = _create(db, world, start_date=D(2025, 1, 1))
    assert isinstance(refused, Err) and refused.code == "CONTRACT_OVERLAP" and "2024-01-01" in refused.message
    assert isinstance(_create(db, world, start_date=D(2025, 1, 1), status="draft"), Ok)


def test_a_new_contract_is_draft_or_active_and_amends_nothing(db, world):
    assert _create(db, world, status="expired").code == "INVALID_STATUS"
    assert _create(db, world, end_date=D(2024, 6, 30), end_reason="resignation").code == "INVALID_CONTRACT"


def test_activating_a_draft_checks_overlap(db, world):
    service = ContractService(db)
    assert isinstance(_create(db, world), Ok)
    draft = _create(db, world, start_date=D(2025, 1, 1), status="draft").value
    refused = service.activate_contract(tenant_id=TENANT, actor_id=world.actor, contract_id=draft["id"])
    assert isinstance(refused, Err) and refused.code == "CONTRACT_OVERLAP"


def test_activating_a_draft_that_fits_signs_it(db, world):
    draft = _create(db, world, status="draft").value
    activated = ContractService(db).activate_contract(tenant_id=TENANT, actor_id=world.actor, contract_id=draft["id"])
    assert activated.value["status"] == "active"
    again = ContractService(db).activate_contract(tenant_id=TENANT, actor_id=world.actor, contract_id=draft["id"])
    assert isinstance(again, Err) and again.code == "INVALID_TRANSITION"


def test_ending_early_terminates_and_cannot_run_past_the_agreed_end(db, world):
    service = ContractService(db)
    cdd = _create(db, world, contract_type="cdd", end_date=D(2024, 12, 31)).value
    late = service.end_contract(tenant_id=TENANT, actor_id=world.actor, contract_id=cdd["id"], end_date=D(2025, 1, 31), end_reason="resignation")
    assert isinstance(late, Err) and late.code == "INVALID_DATES"
    ended = service.end_contract(tenant_id=TENANT, actor_id=world.actor, contract_id=cdd["id"], end_date=D(2024, 6, 30), end_reason="resignation")
    assert (ended.value["status"], ended.value["end_date"], ended.value["end_reason"]) == ("terminated", "2024-06-30", "resignation")


def test_a_contract_that_reaches_its_term_expires(db, world):
    cdd = _create(db, world, contract_type="cdd", end_date=D(2024, 12, 31)).value
    ended = ContractService(db).end_contract(
        tenant_id=TENANT, actor_id=world.actor, contract_id=cdd["id"], end_date=D(2024, 12, 31), end_reason="term_reached"
    )
    assert ended.value["status"] == "expired"


def test_amended_is_not_a_reason_to_end_a_contract_by_hand(db, world):
    contract = _create(db, world).value
    refused = ContractService(db).end_contract(
        tenant_id=TENANT, actor_id=world.actor, contract_id=contract["id"], end_date=D(2024, 6, 30), end_reason="amended"
    )
    assert isinstance(refused, Err) and refused.code == "INVALID_END_REASON"


def test_an_amendment_closes_the_old_terms_and_carries_them_on(db, world):
    service = ContractService(db)
    old = _create(db, world, trial_end_date=D(2024, 3, 31), components=(ContractComponent(component_code="TRANSPORT", amount=Decimal("15000")),)).value
    new = service.amend_contract(
        tenant_id=TENANT, actor_id=world.actor, contract_id=old["id"], effective_date=D(2025, 1, 1), changes={"base_salary": Decimal("175000")}
    ).value
    assert (new["start_date"], new["base_salary"], new["amends_contract_id"], new["trial_end_date"], new["status"]) == (
        "2025-01-01", Decimal("175000"), old["id"], None, "active",
    )
    assert new["components"] == [{"component_code": "TRANSPORT", "amount": Decimal("15000"), "rate": None}]
    closed = service.get_contract(tenant_id=TENANT, contract_id=old["id"])
    assert (closed["end_date"], closed["end_reason"], closed["status"]) == ("2024-12-31", "amended", "expired")


def test_an_amendment_takes_effect_after_the_start_and_only_on_an_active_contract(db, world):
    service = ContractService(db)
    contract = _create(db, world).value
    same_day = service.amend_contract(tenant_id=TENANT, actor_id=world.actor, contract_id=contract["id"], effective_date=D(2024, 1, 1), changes={})
    assert isinstance(same_day, Err) and same_day.code == "INVALID_DATES"
    draft = _create(db, world, start_date=D(2030, 1, 1), status="draft").value
    not_signed = service.amend_contract(tenant_id=TENANT, actor_id=world.actor, contract_id=draft["id"], effective_date=D(2030, 6, 1), changes={})
    assert isinstance(not_signed, Err) and not_signed.code == "INVALID_TRANSITION"


def test_an_edit_can_replace_components_and_audits_pay_by_name_only(db, world):
    contract = _create(db, world).value
    edited = ContractService(db).update_contract(
        tenant_id=TENANT, actor_id=world.actor, contract_id=contract["id"],
        changes={"base_salary": Decimal("160000"), "components": [{"component_code": "HOUSING", "amount": Decimal("25000")}]},
    ).value
    assert edited["components"] == [{"component_code": "HOUSING", "amount": Decimal("25000"), "rate": None}]
    assert db.execute("SELECT salary FROM hr.contracts WHERE id = %s", (contract["id"],)).fetchone()[0] == Decimal("160000")
    payload = db.execute(
        "SELECT payload FROM core.audit_log WHERE entity_id = %s AND action = 'contract.updated'", (contract["id"],)
    ).fetchone()[0]
    assert payload == {"changed": {}, "sensitive_changed": ["base_salary", "components"]}


def test_the_employee_list_shows_the_contract_in_force_today(db, world):
    _create(db, world, contract_type="cdd", end_date=D(2026, 12, 31))
    [row] = EmployeeService(db).list_employees(TENANT, today=D(2026, 9, 25))
    assert (row["contract_type"], row["contract_end_date"]) == ("cdd", "2026-12-31")
    [later] = EmployeeService(db).list_employees(TENANT, today=D(2027, 1, 1))
    assert later["contract_type"] is None
```

`backend/modules/hr/api/test_contract_routes_integration.py`:

```python
"""Contracts over HTTP: pay and allowances are hidden without hr.view_sensitive and never written blind."""
from __future__ import annotations


def _employee(hr_api) -> str:
    hr_api.grant("hr.manage_employees")
    body = {"employee_no": "C-001", "first_name": "Awa", "last_name": "Traoré", "hire_date": "2024-01-01"}
    return hr_api.client.post("/hr/employees", json=body).json()["id"]


def _contract_body(employee_id: str, **extra) -> dict:
    return {
        "employee_id": employee_id,
        "contract_type": "cdi",
        "start_date": "2024-01-01",
        "base_salary": 150000,
        "components": [{"component_code": "TRANSPORT", "amount": 15000}],
        **extra,
    }


def _revoke_sensitive(hr_api) -> None:
    hr_api.db.execute("DELETE FROM core.user_permissions WHERE user_id = %s AND permission = 'hr.view_sensitive'", (hr_api.user_id,))


def test_creating_a_contract_needs_hr_view_sensitive(hr_api):
    employee_id = _employee(hr_api)
    hr_api.grant("hr.manage_contracts")
    assert hr_api.client.post("/hr/contracts", json=_contract_body(employee_id)).status_code == 403
    hr_api.grant("hr.view_sensitive")
    created = hr_api.client.post("/hr/contracts", json=_contract_body(employee_id))
    assert created.status_code == 201
    assert (created.json()["base_salary"], created.json()["currency"], created.json()["sensitive_hidden"]) == (150000, "XOF", False)


def test_pay_and_allowances_are_hidden_from_a_reader_without_the_right(hr_api):
    employee_id = _employee(hr_api)
    hr_api.grant("hr.manage_contracts", "hr.view_sensitive", "hr.view_contracts")
    hr_api.client.post("/hr/contracts", json=_contract_body(employee_id))
    _revoke_sensitive(hr_api)
    [contract] = hr_api.client.get(f"/hr/contracts?employee_id={employee_id}").json()
    assert contract["base_salary"] is None
    assert contract["components"] == [{"component_code": "TRANSPORT", "amount": None, "rate": None}]
    assert contract["sensitive_hidden"] is True


def test_an_overlapping_contract_is_a_409(hr_api):
    employee_id = _employee(hr_api)
    hr_api.grant("hr.manage_contracts", "hr.view_sensitive")
    hr_api.client.post("/hr/contracts", json=_contract_body(employee_id))
    refused = hr_api.client.post("/hr/contracts", json=_contract_body(employee_id, start_date="2026-01-01"))
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "CONTRACT_OVERLAP"


def test_an_admin_without_the_right_can_fix_hours_but_not_pay(hr_api):
    employee_id = _employee(hr_api)
    hr_api.grant("hr.manage_contracts", "hr.view_sensitive", "hr.admin_contracts")
    contract_id = hr_api.client.post("/hr/contracts", json=_contract_body(employee_id)).json()["id"]
    _revoke_sensitive(hr_api)
    assert hr_api.client.patch(f"/hr/contracts/{contract_id}", json={"base_salary": 1}).status_code == 403
    assert hr_api.client.patch(f"/hr/contracts/{contract_id}", json={"components": []}).status_code == 403
    edited = hr_api.client.patch(f"/hr/contracts/{contract_id}", json={"weekly_hours": 48})
    assert edited.status_code == 200 and edited.json()["weekly_hours"] == 48 and edited.json()["base_salary"] is None
    assert hr_api.db.execute("SELECT base_salary FROM hr.contracts WHERE id = %s", (contract_id,)).fetchone()[0] == 150000


def test_amending_and_ending_go_through_manage_contracts(hr_api):
    employee_id = _employee(hr_api)
    hr_api.grant("hr.manage_contracts", "hr.view_sensitive")
    contract_id = hr_api.client.post("/hr/contracts", json=_contract_body(employee_id)).json()["id"]
    amended = hr_api.client.post(f"/hr/contracts/{contract_id}/amend", json={"effective_date": "2025-01-01", "base_salary": 175000})
    assert amended.status_code == 201 and amended.json()["amends_contract_id"] == contract_id
    ended = hr_api.client.post(f"/hr/contracts/{amended.json()['id']}/end", json={"end_date": "2025-12-31", "end_reason": "resignation"})
    assert ended.status_code == 200 and ended.json()["status"] == "terminated"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_contract.py modules/hr/api/test_contract_integration.py modules/hr/api/test_contract_routes_integration.py -q`
Expected: FAIL — `No module named 'modules.hr.domain.contract'`.

- [ ] **Step 3: Write the migration, classify the table and fix the dev seed**

`backend/modules/hr/migrations/0006_hr_contract_terms.sql`:

```sql
-- Contracts carry the terms payroll pays from: type, trial period, hours, pay and how often it
-- is paid, position and grade, amendments, and why they ended. Money is whole F CFA (XOF).

-- The old screen typed the contract type freely ('permanent' by default). Map it onto the
-- closed list: a known value keeps its meaning, otherwise an end date means fixed-term.
UPDATE hr.contracts SET contract_type = CASE
    WHEN lower(contract_type) IN ('cdi', 'cdd', 'apprentice', 'daily', 'intern') THEN lower(contract_type)
    WHEN end_date IS NULL THEN 'cdi'
    ELSE 'cdd'
END;

ALTER TABLE hr.contracts
    ADD COLUMN IF NOT EXISTS trial_end_date DATE,
    ADD COLUMN IF NOT EXISTS weekly_hours NUMERIC(5,2) NOT NULL DEFAULT 40,
    ADD COLUMN IF NOT EXISTS base_salary NUMERIC(18,0) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS pay_frequency TEXT NOT NULL DEFAULT 'monthly',
    ADD COLUMN IF NOT EXISTS position_id TEXT REFERENCES hr.positions (id),
    ADD COLUMN IF NOT EXISTS grade_id TEXT REFERENCES hr.grades (id),
    ADD COLUMN IF NOT EXISTS amends_contract_id TEXT REFERENCES hr.contracts (id),
    ADD COLUMN IF NOT EXISTS end_reason TEXT;

-- base_salary takes over from salary. salary keeps being written (same value) for the legacy
-- payroll screen until phase 3 retires it; a later migration drops it.
UPDATE hr.contracts SET base_salary = ROUND(salary) WHERE base_salary = 0 AND salary > 0;
ALTER TABLE hr.contracts ALTER COLUMN currency SET DEFAULT 'XOF';

ALTER TABLE hr.contracts ADD CONSTRAINT hr_contracts_type_check
    CHECK (contract_type IN ('cdi', 'cdd', 'apprentice', 'daily', 'intern'));
ALTER TABLE hr.contracts ADD CONSTRAINT hr_contracts_pay_frequency_check
    CHECK (pay_frequency IN ('monthly', 'daily'));
ALTER TABLE hr.contracts ADD CONSTRAINT hr_contracts_amounts_check
    CHECK (base_salary >= 0 AND weekly_hours > 0 AND weekly_hours <= 168);
ALTER TABLE hr.contracts ADD CONSTRAINT hr_contracts_dates_check
    CHECK (end_date IS NULL OR end_date >= start_date);
ALTER TABLE hr.contracts ADD CONSTRAINT hr_contracts_end_reason_check
    CHECK (end_reason IS NULL OR end_reason IN
           ('term_reached', 'resignation', 'dismissal', 'trial_termination', 'mutual_agreement', 'retirement', 'death', 'amended', 'other'));

-- Fixed recurring allowances written on the contract (transport, housing...). The code is the
-- payroll component code (phase 3). The value is either a monthly amount in whole F CFA or a
-- rate in percent (10 = 10 %) of the base payroll applies it to.
CREATE TABLE IF NOT EXISTS hr.contract_components (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    contract_id TEXT NOT NULL REFERENCES hr.contracts (id),
    component_code TEXT NOT NULL,
    amount NUMERIC(18,0),
    rate NUMERIC(9,4),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT hr_contract_components_code_key UNIQUE (contract_id, component_code),
    CONSTRAINT hr_contract_components_value_check
        CHECK ((amount IS NULL) <> (rate IS NULL) AND COALESCE(amount, 0) >= 0 AND COALESCE(rate, 0) >= 0)
);
CREATE INDEX IF NOT EXISTS hr_contract_components_contract_idx ON hr.contract_components (tenant_id, contract_id);
```

In `backend/scripts/reset_operational_data.py`, add `"hr.contract_components",` to `PURGE_TABLES` right after `"hr.attendance_records",`.

In `backend/scripts/seed_dev.py` the demo contracts must use a type the new check accepts and XOF amounts:
- in `demo_employees`, replace the last value of the four tuples `1800`, `1650`, `1500`, `1200` with `650000`, `480000`, `420000`, `250000`;
- replace the contract insert with:

```python
            connection.execute(
                """
                INSERT INTO hr.contracts (id, tenant_id, employee_id, contract_type, start_date, base_salary, salary, currency, status)
                SELECT %s, %s, %s, 'cdi', %s, %s, %s, 'XOF', 'active'
                WHERE NOT EXISTS (SELECT 1 FROM hr.contracts WHERE tenant_id = %s AND employee_id = %s)
                """,
                (str(ULID()), DEMO_TENANT_ID, employee_id, hire_date, salary, salary, DEMO_TENANT_ID, employee_id),
            )
```

- in the legacy payroll block, replace `[("EMP-001", 1800), ("EMP-002", 1650), ("EMP-003", 1500), ("EMP-004", 1200)]` with `[("EMP-001", 650000), ("EMP-002", 480000), ("EMP-003", 420000), ("EMP-004", 250000)]`, `(150, 50, 180) if employee_no == "EMP-001" else (0, 25, 120)` with `(25000, 10000, 60000) if employee_no == "EMP-001" else (0, 5000, 30000)`, and the `'USD'` in the `hr.payroll_items` `VALUES` list with `'XOF'`.

Apply the migration with the Global Constraints command. Expected: no output, exit 0.

- [ ] **Step 4: Write the contract rules**

`backend/modules/hr/domain/contract.py`:

```python
"""Employment contracts: the terms payroll pays from, and the rule that a person has at most
one signed contract on any given day. Pure rules, no database."""
from __future__ import annotations

import datetime
import re
from collections.abc import Iterable
from dataclasses import dataclass, fields, replace
from decimal import Decimal

from core.domain.result import Err, Ok, Result
from modules.hr.domain.employee import END_REASONS
from modules.hr.domain.money import invalid_amount, is_whole_amount

CONTRACT_TYPES = ("cdi", "cdd", "apprentice", "daily", "intern")
PAY_FREQUENCIES = ("monthly", "daily")
CONTRACT_STATUSES = ("draft", "active", "expired", "terminated")
HOURS_IN_A_WEEK = Decimal("168")
_COMPONENT_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,31}$")


@dataclass(frozen=True)
class ContractComponent:
    component_code: str
    amount: Decimal | None = None
    rate: Decimal | None = None


@dataclass(frozen=True)
class ContractTerms:
    employee_id: str
    contract_type: str
    start_date: datetime.date
    base_salary: Decimal
    end_date: datetime.date | None = None
    trial_end_date: datetime.date | None = None
    weekly_hours: Decimal = Decimal("40")
    pay_frequency: str = "monthly"
    position_id: str | None = None
    grade_id: str | None = None
    status: str = "active"
    amends_contract_id: str | None = None
    end_reason: str | None = None
    components: tuple[ContractComponent, ...] = ()


# Stored columns of hr.contracts in ContractTerms order; components live in their own table.
COLUMNS = tuple(field.name for field in fields(ContractTerms) if field.name != "components")


@dataclass(frozen=True)
class ContractPeriod:
    id: str
    start_date: datetime.date
    end_date: datetime.date | None
    status: str


def validate_components(components: Iterable[ContractComponent]) -> Result[tuple[ContractComponent, ...]]:
    cleaned: list[ContractComponent] = []
    for component in components:
        code = (component.component_code or "").strip().upper()
        if not _COMPONENT_CODE.match(code):
            return Err(
                "INVALID_COMPONENT",
                f"'{component.component_code}' is not a component code (capitals, digits, underscores)",
                f"« {component.component_code} » n'est pas un code d'élément (majuscules, chiffres, tirets bas)",
            )
        if (component.amount is None) == (component.rate is None):
            return Err("INVALID_COMPONENT", f"{code}: give either an amount or a rate", f"{code} : indiquez soit un montant, soit un taux")
        if component.amount is not None and not is_whole_amount(component.amount):
            return invalid_amount(f"the amount of {code}", f"le montant de {code}")
        if component.rate is not None and (not component.rate.is_finite() or component.rate < 0):
            return Err("INVALID_COMPONENT", f"{code}: a rate cannot be negative", f"{code} : un taux ne peut pas être négatif")
        cleaned.append(ContractComponent(component_code=code, amount=component.amount, rate=component.rate))
    codes = [component.component_code for component in cleaned]
    if len(codes) != len(set(codes)):
        return Err("INVALID_COMPONENT", "an allowance appears twice on the contract", "une indemnité figure deux fois sur le contrat")
    return Ok(tuple(cleaned))


def validate_terms(terms: ContractTerms) -> Result[ContractTerms]:
    if terms.contract_type not in CONTRACT_TYPES:
        return Err(
            "INVALID_CONTRACT_TYPE",
            f"contract type must be one of {', '.join(CONTRACT_TYPES)}",
            f"le type de contrat doit être l'un de {', '.join(CONTRACT_TYPES)}",
        )
    if terms.pay_frequency not in PAY_FREQUENCIES:
        return Err("INVALID_CONTRACT", "pay frequency is monthly or daily", "la périodicité de paie est mensuelle ou journalière")
    if terms.status not in CONTRACT_STATUSES:
        return Err(
            "INVALID_STATUS",
            f"status must be one of {', '.join(CONTRACT_STATUSES)}",
            f"le statut doit être l'un de {', '.join(CONTRACT_STATUSES)}",
        )
    if terms.start_date is None:
        return Err("INVALID_DATES", "a contract needs a start date", "un contrat demande une date de début")
    if not is_whole_amount(terms.base_salary):
        return invalid_amount("the base salary", "le salaire de base")
    if terms.weekly_hours is None or not Decimal("0") < terms.weekly_hours <= HOURS_IN_A_WEEK:
        return Err("INVALID_CONTRACT", "weekly hours are above 0 and at most 168", "les heures hebdomadaires sont supérieures à 0 et au plus 168")
    if terms.end_date is not None and terms.end_date < terms.start_date:
        return Err("INVALID_DATES", "a contract cannot end before it starts", "un contrat ne peut pas finir avant de commencer")
    if terms.trial_end_date is not None and (
        terms.trial_end_date < terms.start_date or (terms.end_date is not None and terms.trial_end_date > terms.end_date)
    ):
        return Err("INVALID_DATES", "the trial period ends within the contract", "la période d'essai se termine pendant le contrat")
    if terms.end_reason is not None and terms.end_reason not in END_REASONS:
        return Err("INVALID_END_REASON", "unknown end reason", "motif de fin inconnu")
    if terms.end_reason is not None and terms.end_date is None:
        return Err("INVALID_END_REASON", "an end reason needs an end date", "un motif de fin demande une date de fin")
    components = validate_components(terms.components)
    if isinstance(components, Err):
        return components
    return Ok(replace(terms, components=components.value))


def overlapping(candidate: ContractPeriod, others: Iterable[ContractPeriod]) -> ContractPeriod | None:
    """The earliest signed contract of the same person sharing a day with `candidate`.
    A draft is not signed: it never conflicts, and nothing conflicts with it."""
    if candidate.status == "draft":
        return None
    clashes = [
        other
        for other in others
        if other.id != candidate.id
        and other.status != "draft"
        and other.start_date <= (candidate.end_date or datetime.date.max)
        and candidate.start_date <= (other.end_date or datetime.date.max)
    ]
    return min(clashes, key=lambda other: other.start_date, default=None)


def overlap_refusal(other: ContractPeriod) -> Err:
    start = other.start_date.isoformat()
    if other.end_date is None:
        span_en, span_fr = f"from {start}, open-ended", f"depuis le {start}, sans date de fin"
    else:
        end = other.end_date.isoformat()
        span_en, span_fr = f"from {start} to {end}", f"du {start} au {end}"
    return Err("CONTRACT_OVERLAP", f"the employee already has a signed contract {span_en}", f"l'employé a déjà un contrat signé {span_fr}")


def end_status(end_reason: str) -> str:
    """A contract that ran to its term, or that an amendment replaced, expired; any other end is a termination."""
    return "expired" if end_reason in ("term_reached", "amended") else "terminated"
```

- [ ] **Step 5: Rewrite the contract service**

Replace `backend/modules/hr/api/contract_service.py` with:

```python
"""Employment contracts: create, edit, activate, end and amend. The one-signed-contract-per-day
rule is checked here first (a readable refusal) and enforced again by the database
(hr_contracts_no_overlap, migration 0007)."""
from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.support import change_payload, execute_guarded, iso_dates, missing_reference
from modules.hr.domain.contract import (
    COLUMNS,
    ContractComponent,
    ContractPeriod,
    ContractTerms,
    end_status,
    overlap_refusal,
    overlapping,
    validate_terms,
)
from modules.hr.domain.employee import END_REASONS
from modules.hr.domain.sensitive import CONTRACT_WRITE_FIELDS

_NOT_FOUND = Err("NOT_FOUND", "contract not found", "contrat introuvable")
_OVERLAP_GUARD = {
    "hr_contracts_no_overlap": Err(
        "CONTRACT_OVERLAP", "the employee already has a signed contract on those days", "l'employé a déjà un contrat signé sur ces jours"
    )
}
# An edit may change everything but the person and the contract an amendment replaced.
_EDITABLE = {name for name in COLUMNS if name not in ("employee_id", "amends_contract_id")} | {"components"}
_AMENDABLE = {"contract_type", "end_date", "weekly_hours", "base_salary", "pay_frequency", "position_id", "grade_id", "components"}
_C_COLUMNS = ", ".join(f"c.{name}" for name in COLUMNS)
_SELECT = f"""
    SELECT c.id, {_C_COLUMNS}, c.currency, e.first_name || ' ' || e.last_name, p.title, g.code
    FROM hr.contracts c
    JOIN hr.employees e ON e.id = c.employee_id
    LEFT JOIN hr.positions p ON p.id = c.position_id
    LEFT JOIN hr.grades g ON g.id = c.grade_id
"""
# salary mirrors base_salary for the legacy payroll screen; every new contract is in XOF.
_INSERT = f"INSERT INTO hr.contracts (id, tenant_id, {', '.join(COLUMNS)}, salary, currency) VALUES ({', '.join(['%s'] * (len(COLUMNS) + 4))})"
_UPDATE = "UPDATE hr.contracts SET " + ", ".join(f"{name} = %s" for name in COLUMNS) + ", salary = %s WHERE id = %s AND tenant_id = %s"


def _components_of(values) -> tuple[ContractComponent, ...]:
    return tuple(value if isinstance(value, ContractComponent) else ContractComponent(**value) for value in (values or ()))


class ContractService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    # ---- reads ----------------------------------------------------------------------------------

    def list_contracts(self, tenant_id: str, employee_id: str | None = None) -> list[dict]:
        params: list[object] = [tenant_id]
        clause = "WHERE c.tenant_id = %s"
        if employee_id:
            clause += " AND c.employee_id = %s"
            params.append(employee_id)
        rows = self.connection.execute(f"{_SELECT} {clause} ORDER BY c.start_date DESC, c.created_at DESC", params).fetchall()
        return self._records(rows)

    def get_contract(self, *, tenant_id: str, contract_id: str) -> dict | None:
        rows = self.connection.execute(f"{_SELECT} WHERE c.tenant_id = %s AND c.id = %s", (tenant_id, contract_id)).fetchall()
        records = self._records(rows)
        return records[0] if records else None

    def _records(self, rows) -> list[dict]:
        components = self._components([row[0] for row in rows])
        count = len(COLUMNS)
        records: list[dict] = []
        for row in rows:
            terms = dict(zip(COLUMNS, row[1 : 1 + count]))
            currency, employee_name, position_title, grade_code = row[1 + count :]
            records.append(
                {
                    "id": row[0],
                    **iso_dates(terms),
                    "currency": currency,
                    "employee_name": employee_name,
                    "position_title": position_title,
                    "grade_code": grade_code,
                    "components": [
                        {"component_code": item.component_code, "amount": item.amount, "rate": item.rate} for item in components.get(row[0], ())
                    ],
                }
            )
        return records

    def _components(self, contract_ids: Sequence[str]) -> dict[str, tuple[ContractComponent, ...]]:
        if not contract_ids:
            return {}
        rows = self.connection.execute(
            "SELECT contract_id, component_code, amount, rate FROM hr.contract_components WHERE contract_id = ANY(%s) ORDER BY component_code",
            (list(contract_ids),),
        ).fetchall()
        found: dict[str, list[ContractComponent]] = {}
        for contract_id, code, amount, rate in rows:
            found.setdefault(contract_id, []).append(ContractComponent(component_code=code, amount=amount, rate=rate))
        return {contract_id: tuple(items) for contract_id, items in found.items()}

    def _locked_terms(self, tenant_id: str, contract_id: str) -> ContractTerms | None:
        row = self.connection.execute(
            f"SELECT {', '.join(COLUMNS)} FROM hr.contracts WHERE id = %s AND tenant_id = %s FOR UPDATE", (contract_id, tenant_id)
        ).fetchone()
        if row is None:
            return None
        return ContractTerms(*row, components=self._components([contract_id]).get(contract_id, ()))

    # ---- checks ---------------------------------------------------------------------------------

    def _check_employee(self, tenant_id: str, employee_id: str) -> Err | None:
        """The employee exists and has not left. Locking the row serialises two writes on the
        same person's contracts."""
        row = self.connection.execute(
            "SELECT status FROM hr.employees WHERE id = %s AND tenant_id = %s FOR UPDATE", (employee_id, tenant_id)
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", "employee not found", "employé introuvable")
        if row[0] == "terminated":
            return Err(
                "EMPLOYEE_TERMINATED",
                "this employee has left; a new contract needs a new hire",
                "cet employé est sorti ; un nouveau contrat demande une nouvelle embauche",
            )
        return None

    def _check_references(self, tenant_id: str, terms: ContractTerms) -> Err | None:
        return missing_reference(self.connection, "hr.positions", tenant_id, terms.position_id, "position", "poste") or missing_reference(
            self.connection, "hr.grades", tenant_id, terms.grade_id, "grade", "catégorie"
        )

    def _check_overlap(self, tenant_id: str, contract_id: str, terms: ContractTerms) -> Err | None:
        rows = self.connection.execute(
            "SELECT id, start_date, end_date, status FROM hr.contracts WHERE tenant_id = %s AND employee_id = %s",
            (tenant_id, terms.employee_id),
        ).fetchall()
        candidate = ContractPeriod(id=contract_id, start_date=terms.start_date, end_date=terms.end_date, status=terms.status)
        clash = overlapping(candidate, [ContractPeriod(*row) for row in rows])
        return None if clash is None else overlap_refusal(clash)

    # ---- writes ---------------------------------------------------------------------------------

    def _write_components(self, tenant_id: str, contract_id: str, components: Sequence[ContractComponent]) -> None:
        self.connection.execute("DELETE FROM hr.contract_components WHERE contract_id = %s AND tenant_id = %s", (contract_id, tenant_id))
        for component in components:
            self.connection.execute(
                "INSERT INTO hr.contract_components (id, tenant_id, contract_id, component_code, amount, rate) VALUES (%s, %s, %s, %s, %s, %s)",
                (str(ULID()), tenant_id, contract_id, component.component_code, component.amount, component.rate),
            )

    def _insert(self, *, tenant_id: str, actor_id: str, terms: ContractTerms) -> Result[str]:
        contract_id = str(ULID())
        refused = self._check_overlap(tenant_id, contract_id, terms)
        if refused:
            return refused
        refused = execute_guarded(
            self.connection,
            _INSERT,
            (contract_id, tenant_id, *(getattr(terms, name) for name in COLUMNS), terms.base_salary, "XOF"),
            _OVERLAP_GUARD,
        )
        if refused:
            return refused
        self._write_components(tenant_id, contract_id, terms.components)
        record_audit(
            self.connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="contract.created",
            entity_type="contract",
            entity_id=contract_id,
            payload={
                "employee_id": terms.employee_id,
                "contract_type": terms.contract_type,
                "start_date": terms.start_date.isoformat(),
                "end_date": terms.end_date.isoformat() if terms.end_date else None,
                "status": terms.status,
                "amends_contract_id": terms.amends_contract_id,
                "sensitive_set": [name for name in CONTRACT_WRITE_FIELDS if getattr(terms, name)],
            },
        )
        return Ok(contract_id)

    def _close(
        self, *, tenant_id: str, actor_id: str, contract_id: str, current: ContractTerms, end_date: datetime.date, end_reason: str
    ) -> None:
        to_status = end_status(end_reason)
        self.connection.execute(
            "UPDATE hr.contracts SET end_date = %s, end_reason = %s, status = %s WHERE id = %s AND tenant_id = %s",
            (end_date, end_reason, to_status, contract_id, tenant_id),
        )
        record_audit(
            self.connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="contract.ended",
            entity_type="contract",
            entity_id=contract_id,
            payload={
                "from_status": current.status,
                "to_status": to_status,
                "end_date": end_date.isoformat(),
                "end_reason": end_reason,
                "agreed_end_date": current.end_date.isoformat() if current.end_date else None,
            },
        )

    def create_contract(self, *, tenant_id: str, actor_id: str, terms: ContractTerms) -> Result[dict]:
        if terms.status not in ("draft", "active"):
            return Err("INVALID_STATUS", "a new contract is a draft or active", "un nouveau contrat est brouillon ou actif")
        if terms.end_reason is not None or terms.amends_contract_id is not None:
            return Err(
                "INVALID_CONTRACT",
                "a new contract has no end reason and amends nothing; use end or amend",
                "un nouveau contrat n'a ni motif de fin ni avenant ; utilisez la fin de contrat ou l'avenant",
            )
        validated = validate_terms(terms)
        if isinstance(validated, Err):
            return validated
        refused = self._check_employee(tenant_id, terms.employee_id) or self._check_references(tenant_id, validated.value)
        if refused:
            return refused
        inserted = self._insert(tenant_id=tenant_id, actor_id=actor_id, terms=validated.value)
        if isinstance(inserted, Err):
            return inserted
        return Ok(self.get_contract(tenant_id=tenant_id, contract_id=inserted.value))

    def update_contract(self, *, tenant_id: str, actor_id: str, contract_id: str, changes: Mapping[str, object]) -> Result[dict]:
        """Edit in place (hr.admin_contracts): any term, whatever the status."""
        unknown = sorted(set(changes) - _EDITABLE)
        if unknown:
            return Err("INVALID_CONTRACT", f"these fields cannot be edited: {', '.join(unknown)}", f"ces champs ne sont pas modifiables : {', '.join(unknown)}")
        current = self._locked_terms(tenant_id, contract_id)
        if current is None:
            return _NOT_FOUND
        updates = dict(changes)
        if "components" in updates:
            updates["components"] = _components_of(updates["components"])
        validated = validate_terms(replace(current, **updates))
        if isinstance(validated, Err):
            return validated
        candidate = validated.value
        refused = self._check_references(tenant_id, candidate) or self._check_overlap(tenant_id, contract_id, candidate)
        if refused:
            return refused
        refused = execute_guarded(
            self.connection,
            _UPDATE,
            (*(getattr(candidate, name) for name in COLUMNS), candidate.base_salary, contract_id, tenant_id),
            _OVERLAP_GUARD,
        )
        if refused:
            return refused
        if "components" in updates:
            self._write_components(tenant_id, contract_id, candidate.components)
        record_audit(
            self.connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="contract.updated",
            entity_type="contract",
            entity_id=contract_id,
            payload=change_payload(asdict(current), asdict(candidate), CONTRACT_WRITE_FIELDS),
        )
        return Ok(self.get_contract(tenant_id=tenant_id, contract_id=contract_id))

    def activate_contract(self, *, tenant_id: str, actor_id: str, contract_id: str) -> Result[dict]:
        current = self._locked_terms(tenant_id, contract_id)
        if current is None:
            return _NOT_FOUND
        if current.status != "draft":
            return Err("INVALID_TRANSITION", "only a draft contract can be activated", "seul un contrat brouillon peut être activé")
        refused = self._check_employee(tenant_id, current.employee_id) or self._check_overlap(
            tenant_id, contract_id, replace(current, status="active")
        )
        if refused:
            return refused
        refused = execute_guarded(
            self.connection, "UPDATE hr.contracts SET status = 'active' WHERE id = %s AND tenant_id = %s", (contract_id, tenant_id), _OVERLAP_GUARD
        )
        if refused:
            return refused
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="contract.activated",
            entity_type="contract", entity_id=contract_id, payload={"from_status": "draft", "to_status": "active"},
        )
        return Ok(self.get_contract(tenant_id=tenant_id, contract_id=contract_id))

    def end_contract(
        self, *, tenant_id: str, actor_id: str, contract_id: str, end_date: datetime.date, end_reason: str
    ) -> Result[dict]:
        current = self._locked_terms(tenant_id, contract_id)
        if current is None:
            return _NOT_FOUND
        if current.status != "active":
            return Err("INVALID_TRANSITION", "only an active contract can be ended", "seul un contrat actif peut prendre fin")
        if end_reason == "amended" or end_reason not in END_REASONS:
            return Err(
                "INVALID_END_REASON",
                "choose why the contract ends (an amendment ends it through the amendment itself)",
                "choisissez le motif de fin (un avenant y met fin de lui-même)",
            )
        if end_date < current.start_date:
            return Err("INVALID_DATES", "a contract cannot end before it starts", "un contrat ne peut pas finir avant de commencer")
        if current.end_date is not None and end_date > current.end_date:
            return Err(
                "INVALID_DATES",
                "a contract cannot end after its agreed end date; record an amendment to extend it",
                "un contrat ne peut pas finir après sa date de fin prévue ; faites un avenant pour le prolonger",
            )
        self._close(tenant_id=tenant_id, actor_id=actor_id, contract_id=contract_id, current=current, end_date=end_date, end_reason=end_reason)
        return Ok(self.get_contract(tenant_id=tenant_id, contract_id=contract_id))

    def amend_contract(
        self, *, tenant_id: str, actor_id: str, contract_id: str, effective_date: datetime.date, changes: Mapping[str, object]
    ) -> Result[dict]:
        """An avenant: the current terms end the day before `effective_date` and a new active
        contract carries them on from that day with `changes` applied. The trial period is not
        carried over; the allowances are, unless `changes` replaces them."""
        unknown = sorted(set(changes) - _AMENDABLE)
        if unknown:
            return Err("INVALID_CONTRACT", f"an amendment cannot change: {', '.join(unknown)}", f"un avenant ne peut pas modifier : {', '.join(unknown)}")
        current = self._locked_terms(tenant_id, contract_id)
        if current is None:
            return _NOT_FOUND
        if current.status != "active":
            return Err("INVALID_TRANSITION", "only an active contract can be amended", "seul un contrat actif peut faire l'objet d'un avenant")
        if effective_date <= current.start_date or (current.end_date is not None and effective_date > current.end_date):
            return Err(
                "INVALID_DATES",
                "an amendment takes effect after the contract starts and before it ends",
                "un avenant prend effet après le début du contrat et avant sa fin",
            )
        updates = dict(changes)
        if "components" in updates:
            updates["components"] = _components_of(updates["components"])
        validated = validate_terms(
            replace(current, start_date=effective_date, trial_end_date=None, status="active", amends_contract_id=contract_id, end_reason=None, **updates)
        )
        if isinstance(validated, Err):
            return validated
        refused = self._check_employee(tenant_id, current.employee_id) or self._check_references(tenant_id, validated.value)
        if refused:
            return refused
        self._close(
            tenant_id=tenant_id, actor_id=actor_id, contract_id=contract_id, current=current,
            end_date=effective_date - datetime.timedelta(days=1), end_reason="amended",
        )
        inserted = self._insert(tenant_id=tenant_id, actor_id=actor_id, terms=validated.value)
        if isinstance(inserted, Err):
            return inserted
        return Ok(self.get_contract(tenant_id=tenant_id, contract_id=inserted.value))
```

- [ ] **Step 6: Add the bodies and routes**

Append to `backend/modules/hr/api/schemas.py`:

```python
class ComponentBody(BaseModel):
    component_code: str
    amount: Decimal | None = None
    rate: Decimal | None = None  # percent: 10 means 10 %


class ContractCreate(BaseModel):
    employee_id: str
    contract_type: str
    start_date: datetime.date
    base_salary: Decimal
    end_date: datetime.date | None = None
    trial_end_date: datetime.date | None = None
    weekly_hours: Decimal = Decimal("40")
    pay_frequency: str = "monthly"
    position_id: str | None = None
    grade_id: str | None = None
    status: str = "active"
    components: list[ComponentBody] = []


class ContractPatch(BaseModel):
    contract_type: str | None = None
    start_date: datetime.date | None = None
    base_salary: Decimal | None = None
    end_date: datetime.date | None = None
    trial_end_date: datetime.date | None = None
    weekly_hours: Decimal | None = None
    pay_frequency: str | None = None
    position_id: str | None = None
    grade_id: str | None = None
    status: str | None = None
    end_reason: str | None = None
    components: list[ComponentBody] | None = None


class ContractAmend(BaseModel):
    effective_date: datetime.date
    contract_type: str | None = None
    end_date: datetime.date | None = None
    weekly_hours: Decimal | None = None
    base_salary: Decimal | None = None
    pay_frequency: str | None = None
    position_id: str | None = None
    grade_id: str | None = None
    components: list[ComponentBody] | None = None


class ContractEnd(BaseModel):
    end_date: datetime.date
    end_reason: str
```

In `backend/modules/hr/api/router.py`: delete `class ContractBody(BaseModel):` and the two legacy handlers `contracts()` and `create_contract()` (keep the `ContractService` import). Extend the imports (merge into the existing lines):

```python
from modules.hr.api.schemas import ContractAmend, ContractCreate, ContractEnd, ContractPatch
from modules.hr.domain.contract import ContractComponent, ContractTerms
from modules.hr.domain.sensitive import CONTRACT_WRITE_FIELDS, mask_contract
```

and append at the end of the file:

```python
# ---- contracts ------------------------------------------------------------------------------------

_CONTRACT_NOT_FOUND = Err("NOT_FOUND", "contract not found", "contrat introuvable")


def _terms_from(data: dict) -> ContractTerms:
    components = tuple(ContractComponent(**component) for component in data.pop("components"))
    return ContractTerms(**data, components=components)


@router.get("/contracts")
def list_contracts(employee_id: str | None = None, tenant: TenantContext = Depends(require_permission("hr.view_contracts"))):
    with get_connection() as connection:
        contracts = ContractService(connection).list_contracts(tenant.tenant_id, employee_id)
        visible = can_view_sensitive(connection, tenant)
        return [mask_contract(contract, visible=visible) for contract in contracts]


@router.get("/contracts/{contract_id}")
def get_contract(contract_id: str, tenant: TenantContext = Depends(require_permission("hr.view_contracts"))):
    with get_connection() as connection:
        contract = ContractService(connection).get_contract(tenant_id=tenant.tenant_id, contract_id=contract_id)
        if contract is None:
            fail(_CONTRACT_NOT_FOUND)
        return mask_contract(contract, visible=can_view_sensitive(connection, tenant))


@router.post("/contracts", status_code=status.HTTP_201_CREATED)
def create_contract(body: ContractCreate, tenant: TenantContext = Depends(require_permission("hr.manage_contracts"))):
    """A contract always sets pay, so creating one needs hr.view_sensitive."""
    data = body.model_dump()
    with get_connection() as connection:
        require_sensitive_for(connection, tenant, filled(data, CONTRACT_WRITE_FIELDS))
        visible = can_view_sensitive(connection, tenant)
        result = ContractService(connection).create_contract(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, terms=_terms_from(data))
        return mask_contract(respond(connection, result), visible=visible)


@router.patch("/contracts/{contract_id}")
def update_contract(contract_id: str, body: ContractPatch, tenant: TenantContext = Depends(require_permission("hr.admin_contracts"))):
    changes = body.model_dump(exclude_unset=True)
    with get_connection() as connection:
        require_sensitive_for(connection, tenant, written(changes, CONTRACT_WRITE_FIELDS))
        visible = can_view_sensitive(connection, tenant)
        result = ContractService(connection).update_contract(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, contract_id=contract_id, changes=changes
        )
        return mask_contract(respond(connection, result), visible=visible)


@router.post("/contracts/{contract_id}/activate")
def activate_contract(contract_id: str, tenant: TenantContext = Depends(require_permission("hr.manage_contracts"))):
    with get_connection() as connection:
        visible = can_view_sensitive(connection, tenant)
        result = ContractService(connection).activate_contract(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, contract_id=contract_id)
        return mask_contract(respond(connection, result), visible=visible)


@router.post("/contracts/{contract_id}/end")
def end_contract(contract_id: str, body: ContractEnd, tenant: TenantContext = Depends(require_permission("hr.manage_contracts"))):
    with get_connection() as connection:
        visible = can_view_sensitive(connection, tenant)
        result = ContractService(connection).end_contract(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, contract_id=contract_id, end_date=body.end_date, end_reason=body.end_reason
        )
        return mask_contract(respond(connection, result), visible=visible)


@router.post("/contracts/{contract_id}/amend", status_code=status.HTTP_201_CREATED)
def amend_contract(contract_id: str, body: ContractAmend, tenant: TenantContext = Depends(require_permission("hr.manage_contracts"))):
    changes = body.model_dump(exclude_unset=True, exclude={"effective_date"})
    with get_connection() as connection:
        require_sensitive_for(connection, tenant, written(changes, CONTRACT_WRITE_FIELDS))
        visible = can_view_sensitive(connection, tenant)
        result = ContractService(connection).amend_contract(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, contract_id=contract_id, effective_date=body.effective_date, changes=changes
        )
        return mask_contract(respond(connection, result), visible=visible)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr core/test_error_translations.py scripts/test_reset_operational_data_integration.py -q`
Expected: PASS (integration tests counted as passed).

Run the dev seed once to prove it still inserts: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m scripts.seed_dev`
Expected: exit 0 (rerunnable; it only adds what is missing).

- [ ] **Step 8: Commit**

```bash
git add backend/modules/hr/migrations/0006_hr_contract_terms.sql backend/modules/hr/domain/contract.py backend/modules/hr/domain/test_contract.py backend/modules/hr/api/contract_service.py backend/modules/hr/api/schemas.py backend/modules/hr/api/router.py backend/modules/hr/api/test_contract_integration.py backend/modules/hr/api/test_contract_routes_integration.py backend/scripts/reset_operational_data.py backend/scripts/seed_dev.py
git commit -m "feat(hr): typed contracts in XOF with allowances, amendments, activation and end

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The database guard — one signed contract per employee per day

**Files:**
- Create: `backend/modules/hr/migrations/0007_hr_contract_overlap_guard.sql`
- Test: `backend/modules/hr/api/test_contract_overlap_guard_integration.py`

**Interfaces:**
- Consumes: `hr.contracts` columns from Task 5; `ContractService._OVERLAP_GUARD` already maps the constraint name `hr_contracts_no_overlap` to `CONTRACT_OVERLAP`.
- Produces: extension `btree_gist`; constraint `hr_contracts_no_overlap EXCLUDE USING gist (tenant_id WITH =, employee_id WITH =, daterange(start_date, end_date, '[]') WITH &&) WHERE (status <> 'draft')`.

- [ ] **Step 1: Write the failing test**

`backend/modules/hr/api/test_contract_overlap_guard_integration.py`:

```python
"""0007 closes legacy overlaps before adding the exclusion constraint, so it runs on any database,
and from then on the database itself refuses a second signed contract on the same day."""
from __future__ import annotations

import datetime
from pathlib import Path

import psycopg
import pytest
from ulid import ULID

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "0007_hr_contract_overlap_guard.sql"
TENANT = "hr-overlap-guard-test"
D = datetime.date
UTC = datetime.timezone.utc


def _employee(db) -> str:
    employee_id = str(ULID())
    db.execute(
        "INSERT INTO hr.employees (id, tenant_id, employee_no, first_name, last_name, hire_date) VALUES (%s, %s, %s, 'Legacy', 'Row', '2020-01-01')",
        (employee_id, TENANT, employee_id[-8:]),
    )
    return employee_id


def _contract(db, employee_id, start, end=None, status="active", created=datetime.datetime(2020, 1, 1, tzinfo=UTC)) -> str:
    contract_id = str(ULID())
    db.execute(
        "INSERT INTO hr.contracts (id, tenant_id, employee_id, contract_type, start_date, end_date, status, created_at) "
        "VALUES (%s, %s, %s, 'cdi', %s, %s, %s, %s)",
        (contract_id, TENANT, employee_id, start, end, status, created),
    )
    return contract_id


def _row(db, contract_id):
    return db.execute("SELECT start_date, end_date, status, end_reason FROM hr.contracts WHERE id = %s", (contract_id,)).fetchone()


def test_the_database_refuses_a_second_signed_contract_on_the_same_day(db):
    employee_id = _employee(db)
    _contract(db, employee_id, D(2024, 1, 1))
    _contract(db, employee_id, D(2025, 1, 1), status="draft")  # drafts never count
    with pytest.raises(psycopg.errors.ExclusionViolation):
        _contract(db, employee_id, D(2025, 1, 1))


def test_the_migration_closes_legacy_overlaps_then_holds(db):
    db.execute("ALTER TABLE hr.contracts DROP CONSTRAINT hr_contracts_no_overlap")  # the state before 0007
    employee_id = _employee(db)
    first = _contract(db, employee_id, D(2020, 1, 1))                          # open-ended
    second = _contract(db, employee_id, D(2022, 1, 1), D(2024, 12, 31))        # starts inside the first
    twin_old = _contract(db, employee_id, D(2025, 1, 1), created=datetime.datetime(2025, 1, 1, tzinfo=UTC))
    twin_new = _contract(db, employee_id, D(2025, 1, 1), created=datetime.datetime(2025, 1, 2, tzinfo=UTC))
    draft = _contract(db, employee_id, D(2023, 1, 1), status="draft")

    db.execute(MIGRATION.read_text(encoding="utf-8"))

    assert _row(db, first) == (D(2020, 1, 1), D(2021, 12, 31), "active", "other")
    assert _row(db, second) == (D(2022, 1, 1), D(2024, 12, 31), "active", None)
    assert _row(db, twin_old)[2] == "draft"  # same start day: the older one goes back to draft
    assert _row(db, twin_new) == (D(2025, 1, 1), None, "active", None)
    assert _row(db, draft)[2] == "draft"
    with pytest.raises(psycopg.errors.ExclusionViolation):
        _contract(db, employee_id, D(2026, 1, 1))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest modules/hr/api/test_contract_overlap_guard_integration.py -q`
Expected: FAIL — no `ExclusionViolation` is raised, and the second test fails on the missing constraint / missing file.

- [ ] **Step 3: Write and apply the migration**

`backend/modules/hr/migrations/0007_hr_contract_overlap_guard.sql`:

```sql
-- An employee has at most one signed (non-draft) contract on any day. The domain checks it
-- first with a readable refusal; this constraint is the guard against a race.
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Nothing checked overlaps before. Close each signed contract the day before the same
-- employee's next one starts...
WITH ordered AS (
    SELECT id, start_date,
           LEAD(start_date) OVER (PARTITION BY tenant_id, employee_id ORDER BY start_date, created_at, id) AS next_start
    FROM hr.contracts
    WHERE status <> 'draft'
)
UPDATE hr.contracts c
SET end_date = o.next_start - 1,
    end_reason = COALESCE(c.end_reason, 'other')
FROM ordered o
WHERE c.id = o.id
  AND o.next_start > c.start_date
  AND (c.end_date IS NULL OR c.end_date >= o.next_start);

-- ...and when two start the same day, the older one goes back to draft (it cannot be shortened
-- to nothing).
WITH ordered AS (
    SELECT id, start_date,
           LEAD(start_date) OVER (PARTITION BY tenant_id, employee_id ORDER BY start_date, created_at, id) AS next_start
    FROM hr.contracts
    WHERE status <> 'draft'
)
UPDATE hr.contracts c
SET status = 'draft'
FROM ordered o
WHERE c.id = o.id
  AND o.next_start = c.start_date;

ALTER TABLE hr.contracts ADD CONSTRAINT hr_contracts_no_overlap
    EXCLUDE USING gist (tenant_id WITH =, employee_id WITH =, daterange(start_date, end_date, '[]') WITH &&)
    WHERE (status <> 'draft');
```

`btree_gist` is a trusted extension: the `erp` role (owner of the database) can create it on the dev box and on the server image. Apply with the Global Constraints command. Expected: no output, exit 0.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr -q`
Expected: PASS, including Task 5's contract tests (the domain check still answers first).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/hr/migrations/0007_hr_contract_overlap_guard.sql backend/modules/hr/api/test_contract_overlap_guard_integration.py
git commit -m "feat(hr): exclusion constraint for one signed contract per day, legacy overlaps closed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Terminating an employee

**Files:**
- Modify: `backend/modules/hr/domain/employee.py` (append `terminate`), `backend/modules/hr/domain/test_employee.py` (append)
- Modify: `backend/modules/hr/api/contract_service.py` (append `close_for_termination`)
- Modify: `backend/modules/hr/api/employee_service.py` (append `terminate_employee`)
- Modify: `backend/modules/hr/api/schemas.py`, `backend/modules/hr/api/router.py` (append)
- Test: `backend/modules/hr/api/test_termination_integration.py`

**Interfaces:**
- Consumes: `EmployeeFile`, `validate_employee_file` (Task 3); `ContractService._locked_terms`, `_close` (Task 5).
- Produces: `terminate(employee: EmployeeFile, *, termination_date, termination_reason) -> Result[EmployeeFile]` (`ALREADY_TERMINATED`, `INVALID_TERMINATION`, `INVALID_DATES`); `ContractService.close_for_termination(*, tenant_id, actor_id, employee_id, termination_date, termination_reason) -> Result[list[str]]` (`CONTRACT_AFTER_TERMINATION`); `EmployeeService.terminate_employee(*, tenant_id, actor_id, employee_id, termination_date, termination_reason) -> Result[dict]`; route `POST /hr/employees/{id}/terminate` (`hr.manage_employees`).
- The "final settlement" flag of the spec is the pair `termination_date` / `termination_reason`: `PayrollSnapshotService` (Task 9) returns them for the month the person leaves in, and phase 3 builds the settlement from them. No separate boolean.

- [ ] **Step 1: Write the failing tests**

Append to `backend/modules/hr/domain/test_employee.py`:

```python
from modules.hr.domain.employee import terminate  # noqa: E402


def test_terminating_sets_status_date_and_reason():
    result = terminate(_file(), termination_date=datetime.date(2026, 9, 30), termination_reason="resignation")
    assert isinstance(result, Ok)
    assert (result.value.status, result.value.termination_date, result.value.termination_reason) == (
        "terminated", datetime.date(2026, 9, 30), "resignation",
    )


def test_an_exit_needs_a_known_reason_and_cannot_precede_hiring():
    assert terminate(_file(), termination_date=datetime.date(2026, 9, 30), termination_reason="amended").code == "INVALID_TERMINATION"
    assert terminate(_file(), termination_date=datetime.date(2026, 9, 30), termination_reason="").code == "INVALID_TERMINATION"
    assert terminate(_file(), termination_date=datetime.date(2024, 2, 1), termination_reason="resignation").code == "INVALID_DATES"


def test_an_employee_leaves_only_once():
    left = terminate(_file(), termination_date=datetime.date(2026, 9, 30), termination_reason="resignation").value
    assert terminate(left, termination_date=datetime.date(2026, 10, 31), termination_reason="dismissal").code == "ALREADY_TERMINATED"
```

`backend/modules/hr/api/test_termination_integration.py`:

```python
"""Leaving: the exit closes the contract in force on that day and is recorded on the file."""
from __future__ import annotations

import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from ulid import ULID

from core.domain.result import Err, Ok
from modules.hr.api.contract_service import ContractService
from modules.hr.api.service import EmployeeService
from modules.hr.domain.contract import ContractTerms
from modules.hr.domain.employee import EmployeeFile

TENANT = "hr-termination-test"
D = datetime.date


@pytest.fixture
def world(db):
    actor = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    employee = EmployeeService(db).create_employee(
        tenant_id=TENANT, actor_id=actor,
        employee=EmployeeFile(employee_no="T-001", first_name="Seydou", last_name="Diarra", hire_date=D(2024, 1, 1)),
    ).value
    return SimpleNamespace(actor=actor, employee_id=employee["id"])


def _contract(db, world, **overrides) -> dict:
    terms = ContractTerms(
        **{"employee_id": world.employee_id, "contract_type": "cdi", "start_date": D(2024, 1, 1), "base_salary": Decimal("120000"), **overrides}
    )
    return ContractService(db).create_contract(tenant_id=TENANT, actor_id=world.actor, terms=terms).value


def _terminate(db, world, day=D(2026, 9, 30), reason="resignation"):
    return EmployeeService(db).terminate_employee(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, termination_date=day, termination_reason=reason
    )


def test_terminating_closes_the_contract_in_force_and_flags_the_file(db, world):
    contract = _contract(db, world)
    left = _terminate(db, world)
    assert isinstance(left, Ok)
    assert (left.value["status"], left.value["termination_date"], left.value["termination_reason"]) == ("terminated", "2026-09-30", "resignation")
    closed = ContractService(db).get_contract(tenant_id=TENANT, contract_id=contract["id"])
    assert (closed["end_date"], closed["end_reason"], closed["status"]) == ("2026-09-30", "resignation", "terminated")
    payload = db.execute(
        "SELECT payload FROM core.audit_log WHERE entity_id = %s AND action = 'employee.terminated'", (world.employee_id,)
    ).fetchone()[0]
    assert payload["closed_contract_ids"] == [contract["id"]]


def test_a_cdd_left_at_its_term_expires(db, world):
    cdd = _contract(db, world, contract_type="cdd", end_date=D(2026, 12, 31))
    _terminate(db, world, day=D(2026, 12, 31), reason="term_reached")
    assert ContractService(db).get_contract(tenant_id=TENANT, contract_id=cdd["id"])["status"] == "expired"


def test_a_signed_contract_starting_after_the_exit_blocks_it(db, world):
    _contract(db, world, start_date=D(2027, 1, 1))
    refused = _terminate(db, world)
    assert isinstance(refused, Err) and refused.code == "CONTRACT_AFTER_TERMINATION"
    assert EmployeeService(db).get_employee(tenant_id=TENANT, employee_id=world.employee_id)["status"] == "active"


def test_an_employee_leaves_once_and_gets_no_new_contract_after(db, world):
    _contract(db, world)
    assert isinstance(_terminate(db, world), Ok)
    assert _terminate(db, world).code == "ALREADY_TERMINATED"
    refused = ContractService(db).create_contract(
        tenant_id=TENANT, actor_id=world.actor,
        terms=ContractTerms(employee_id=world.employee_id, contract_type="cdi", start_date=D(2027, 1, 1), base_salary=Decimal("1")),
    )
    assert isinstance(refused, Err) and refused.code == "EMPLOYEE_TERMINATED"


def test_leaving_without_a_contract_still_records_the_exit(db, world):
    left = _terminate(db, world)
    assert left.value["status"] == "terminated"


def test_the_route_needs_manage_employees_and_answers_409_when_already_gone(hr_api):
    hr_api.grant("hr.manage_employees")
    body = {"employee_no": "T-9", "first_name": "Awa", "last_name": "Koné", "hire_date": "2024-01-01"}
    employee_id = hr_api.client.post("/hr/employees", json=body).json()["id"]
    exit_body = {"termination_date": "2026-09-30", "termination_reason": "resignation"}
    first = hr_api.client.post(f"/hr/employees/{employee_id}/terminate", json=exit_body)
    assert first.status_code == 200 and first.json()["status"] == "terminated"
    assert hr_api.client.post(f"/hr/employees/{employee_id}/terminate", json=exit_body).status_code == 409
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_employee.py modules/hr/api/test_termination_integration.py -q`
Expected: FAIL — `cannot import name 'terminate'`, `'EmployeeService' object has no attribute 'terminate_employee'`.

- [ ] **Step 3: Implement**

Append to `backend/modules/hr/domain/employee.py` (add `replace` to the `dataclasses` import):

```python
def terminate(employee: EmployeeFile, *, termination_date: datetime.date, termination_reason: str) -> Result[EmployeeFile]:
    """The file of someone who leaves on `termination_date` (the last day worked)."""
    if employee.status == "terminated":
        return Err("ALREADY_TERMINATED", "this employee has already left", "cet employé est déjà sorti")
    return validate_employee_file(
        replace(employee, status="terminated", termination_date=termination_date, termination_reason=termination_reason)
    )
```

Append to `ContractService` in `backend/modules/hr/api/contract_service.py`:

```python
    def close_for_termination(
        self, *, tenant_id: str, actor_id: str, employee_id: str, termination_date: datetime.date, termination_reason: str
    ) -> Result[list[str]]:
        """End every active contract in force on the exit day, on that day, for that reason.
        A signed contract starting after the exit is a contradiction the user must resolve first."""
        later = self.connection.execute(
            "SELECT start_date FROM hr.contracts WHERE tenant_id = %s AND employee_id = %s AND status <> 'draft' AND start_date > %s "
            "ORDER BY start_date LIMIT 1",
            (tenant_id, employee_id, termination_date),
        ).fetchone()
        if later is not None:
            day = later[0].isoformat()
            return Err(
                "CONTRACT_AFTER_TERMINATION",
                f"a signed contract starts on {day}, after the exit date",
                f"un contrat signé commence le {day}, après la date de sortie",
            )
        rows = self.connection.execute(
            "SELECT id FROM hr.contracts WHERE tenant_id = %s AND employee_id = %s AND status = 'active' "
            "AND start_date <= %s AND (end_date IS NULL OR end_date >= %s) ORDER BY start_date",
            (tenant_id, employee_id, termination_date, termination_date),
        ).fetchall()
        closed: list[str] = []
        for (contract_id,) in rows:
            current = self._locked_terms(tenant_id, contract_id)
            self._close(
                tenant_id=tenant_id, actor_id=actor_id, contract_id=contract_id, current=current,
                end_date=termination_date, end_reason=termination_reason,
            )
            closed.append(contract_id)
        return Ok(closed)
```

In `backend/modules/hr/api/employee_service.py`, add `from modules.hr.api.contract_service import ContractService`, extend the domain import with `terminate`, and append to `EmployeeService`:

```python
    def terminate_employee(
        self, *, tenant_id: str, actor_id: str, employee_id: str, termination_date: datetime.date, termination_reason: str
    ) -> Result[dict]:
        """Record the exit: the contract in force that day ends on it, and the file carries the date
        and reason the next payroll's final settlement is built from."""
        current = self._locked(tenant_id, employee_id)
        if current is None:
            return _NOT_FOUND
        left = terminate(current, termination_date=termination_date, termination_reason=termination_reason)
        if isinstance(left, Err):
            return left
        closed = ContractService(self.connection).close_for_termination(
            tenant_id=tenant_id, actor_id=actor_id, employee_id=employee_id,
            termination_date=termination_date, termination_reason=termination_reason,
        )
        if isinstance(closed, Err):
            return closed
        self.connection.execute(
            "UPDATE hr.employees SET status = 'terminated', termination_date = %s, termination_reason = %s WHERE id = %s AND tenant_id = %s",
            (termination_date, termination_reason, employee_id, tenant_id),
        )
        record_audit(
            self.connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="employee.terminated",
            entity_type="employee",
            entity_id=employee_id,
            payload={
                "from_status": current.status,
                "to_status": "terminated",
                "termination_date": termination_date.isoformat(),
                "termination_reason": termination_reason,
                "closed_contract_ids": closed.value,
            },
        )
        return Ok(self.get_employee(tenant_id=tenant_id, employee_id=employee_id))
```

Append to `backend/modules/hr/api/schemas.py`:

```python
class TerminationBody(BaseModel):
    termination_date: datetime.date
    termination_reason: str
```

In `router.py`, add `TerminationBody` to the schemas import and append:

```python
@router.post("/employees/{employee_id}/terminate")
def terminate_employee(employee_id: str, body: TerminationBody, tenant: TenantContext = Depends(require_permission("hr.manage_employees"))):
    with get_connection() as connection:
        visible = can_view_sensitive(connection, tenant)
        result = EmployeeService(connection).terminate_employee(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, employee_id=employee_id,
            termination_date=body.termination_date, termination_reason=body.termination_reason,
        )
        return mask(respond(connection, result), EMPLOYEE_FIELDS, visible=visible)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr core/test_error_translations.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/hr/domain/employee.py backend/modules/hr/domain/test_employee.py backend/modules/hr/api/contract_service.py backend/modules/hr/api/employee_service.py backend/modules/hr/api/schemas.py backend/modules/hr/api/router.py backend/modules/hr/api/test_termination_integration.py
git commit -m "feat(hr): terminate an employee, closing the contract in force on the exit day

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Documents, alert horizons and the expiry alerts

**Files:**
- Create: `backend/modules/hr/migrations/0008_hr_employee_documents.sql`, `backend/modules/hr/migrations/0009_hr_settings.sql`
- Create: `backend/modules/hr/domain/document.py`, `backend/modules/hr/domain/test_document.py`
- Create: `backend/modules/hr/domain/alerts.py`, `backend/modules/hr/domain/test_alerts.py`
- Create: `backend/modules/hr/api/document_service.py`, `backend/modules/hr/api/settings_service.py`, `backend/modules/hr/api/alert_service.py`
- Modify: `backend/modules/hr/api/schemas.py`, `backend/modules/hr/api/router.py` (append)
- Modify: `backend/scripts/reset_operational_data.py`
- Test: `backend/modules/hr/api/test_documents_alerts_integration.py`, `backend/modules/hr/api/test_documents_alerts_routes_integration.py`

**Interfaces:**
- Consumes: `support.*`, `ContractService`, `EmployeeService.terminate_employee`.
- Produces: `modules.hr.domain.document` — `DOCUMENT_KINDS = ("id_card", "passport", "work_permit", "medical_certificate", "driving_licence", "diploma", "criminal_record", "signed_contract", "other")`, `EmployeeDocument(kind, title=None, file_ref=None, issued_on=None, expires_on=None)`, `validate_document(...)`.
- Produces: `modules.hr.domain.alerts` — `HORIZON_KEYS = ("contract_expiry_horizon_days", "trial_end_horizon_days", "document_expiry_horizon_days")`, `validate_horizons(Mapping[str, int | None]) -> Result[dict]` (`INVALID_SETTING`), `window_end(today, days) -> date | None`, `expiry_state(expires_on, today, horizon_days) -> "expired" | "expiring" | "valid" | None`.
- Produces: `DocumentService.list_documents(*, tenant_id, employee_id, today=None)` (dicts `id, employee_id, kind, title, file_ref, issued_on, expires_on, state`), `create_document(*, tenant_id, actor_id, employee_id, document)`, `update_document(*, tenant_id, actor_id, document_id, changes)`; `HrSettingsService.get(tenant_id) -> dict` (the three keys, `None` when unset), `save(*, tenant_id, actor_id, contract_expiry_horizon_days, trial_end_horizon_days, document_expiry_horizon_days) -> Result[dict]`; `HrAlertService.expiry_alerts(*, tenant_id, today) -> {as_of, contract_expiry_horizon_days, trial_end_horizon_days, document_expiry_horizon_days, contracts_ending: [...], trials_ending: [...], documents_expiring: [...]}` — contract items `{contract_id, employee_id, employee_no, employee_name, contract_type, date}`, document items `{document_id, employee_id, employee_no, employee_name, kind, title, expires_on, state}`.
- Produces: routes `GET/POST /hr/employees/{id}/documents`, `PATCH /hr/documents/{id}` (`hr.admin_employees`), `GET /hr/settings` (`hr.view_employees`), `PUT /hr/settings` (`hr.admin_employees`), `GET /hr/alerts/expiries` (`hr.view_employees`).
- Produces: tables `hr.employee_documents`, `hr.settings (tenant_id PK, contract_expiry_horizon_days, trial_end_horizon_days, document_expiry_horizon_days, updated_by, updated_at)` — the names phase 5 (A5/A6) reads.

- [ ] **Step 1: Write the failing tests**

`backend/modules/hr/domain/test_document.py`:

```python
from datetime import date

from core.domain.result import Ok
from modules.hr.domain.document import EmployeeDocument, validate_document


def test_an_unknown_kind_is_refused_and_other_needs_a_title():
    assert validate_document(EmployeeDocument(kind="selfie")).code == "INVALID_CHOICE"
    assert validate_document(EmployeeDocument(kind="other")).code == "INVALID_DOCUMENT"
    assert isinstance(validate_document(EmployeeDocument(kind="other", title="Attestation")), Ok)


def test_a_document_cannot_expire_before_it_is_issued():
    refused = validate_document(EmployeeDocument(kind="passport", issued_on=date(2026, 1, 1), expires_on=date(2025, 1, 1)))
    assert refused.code == "INVALID_DATES"


def test_blank_text_becomes_null_and_text_is_trimmed():
    clean = validate_document(EmployeeDocument(kind="passport", title=" ", file_ref="  \\\\srv-rh\\dossiers\\p.pdf ")).value
    assert (clean.title, clean.file_ref) == (None, "\\\\srv-rh\\dossiers\\p.pdf")
```

`backend/modules/hr/domain/test_alerts.py`:

```python
from datetime import date

from core.domain.result import Ok
from modules.hr.domain.alerts import expiry_state, validate_horizons, window_end

TODAY = date(2026, 9, 25)


def test_no_horizon_means_no_window_and_the_window_includes_its_last_day():
    assert window_end(TODAY, None) is None
    assert window_end(TODAY, 30) == date(2026, 10, 25)


def test_a_horizon_is_a_positive_number_of_days_or_nothing():
    empty = {"contract_expiry_horizon_days": None, "trial_end_horizon_days": None, "document_expiry_horizon_days": None}
    assert isinstance(validate_horizons(empty), Ok)
    assert validate_horizons({**empty, "trial_end_horizon_days": 0}).code == "INVALID_SETTING"
    assert validate_horizons({**empty, "contract_expiry_horizon_days": -5}).code == "INVALID_SETTING"


def test_expiry_state_is_a_fact_when_past_and_a_judgement_only_inside_a_set_horizon():
    assert expiry_state(date(2026, 9, 24), TODAY, 30) == "expired"
    assert expiry_state(date(2026, 9, 24), TODAY, None) == "expired"
    assert expiry_state(date(2026, 9, 25), TODAY, 30) == "expiring"
    assert expiry_state(date(2026, 10, 25), TODAY, 30) == "expiring"
    assert expiry_state(date(2026, 10, 26), TODAY, 30) == "valid"
    assert expiry_state(date(2026, 10, 1), TODAY, None) == "valid"
    assert expiry_state(None, TODAY, 30) is None
```

`backend/modules/hr/api/test_documents_alerts_integration.py`:

```python
"""Documents, the alert horizons and the expiry alerts against a real database."""
from __future__ import annotations

import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from ulid import ULID

from core.domain.result import Err
from modules.hr.api.alert_service import HrAlertService
from modules.hr.api.contract_service import ContractService
from modules.hr.api.document_service import DocumentService
from modules.hr.api.service import EmployeeService
from modules.hr.api.settings_service import HrSettingsService
from modules.hr.domain.contract import ContractTerms
from modules.hr.domain.document import EmployeeDocument
from modules.hr.domain.employee import EmployeeFile

TENANT = "hr-alerts-test"
TODAY = datetime.date(2026, 9, 25)
D = datetime.date


@pytest.fixture
def world(db):
    actor = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    employee = EmployeeService(db).create_employee(
        tenant_id=TENANT, actor_id=actor,
        employee=EmployeeFile(employee_no="A-001", first_name="Hawa", last_name="Sangaré", hire_date=D(2024, 1, 1)),
    ).value
    return SimpleNamespace(actor=actor, employee_id=employee["id"])


def _horizons(db, world, contract=30, trial=15, document=30):
    return HrSettingsService(db).save(
        tenant_id=TENANT, actor_id=world.actor,
        contract_expiry_horizon_days=contract, trial_end_horizon_days=trial, document_expiry_horizon_days=document,
    )


def _contract(db, world, **overrides):
    terms = ContractTerms(**{"employee_id": world.employee_id, "contract_type": "cdd", "start_date": D(2026, 1, 1), "base_salary": Decimal("90000"), **overrides})
    return ContractService(db).create_contract(tenant_id=TENANT, actor_id=world.actor, terms=terms).value


def _alerts(db):
    return HrAlertService(db).expiry_alerts(tenant_id=TENANT, today=TODAY)


def test_settings_start_empty_and_nothing_is_listed_without_a_horizon(db, world):
    assert HrSettingsService(db).get(TENANT) == {
        "contract_expiry_horizon_days": None, "trial_end_horizon_days": None, "document_expiry_horizon_days": None,
    }
    _contract(db, world, end_date=D(2026, 10, 1))
    alerts = _alerts(db)
    assert (alerts["contract_expiry_horizon_days"], alerts["contracts_ending"]) == (None, [])


def test_saving_horizons_is_audited_and_validated(db, world):
    assert isinstance(_horizons(db, world, trial=0), Err)
    saved = _horizons(db, world, document=None).value
    assert saved == {"contract_expiry_horizon_days": 30, "trial_end_horizon_days": 15, "document_expiry_horizon_days": None}
    payload = db.execute("SELECT payload FROM core.audit_log WHERE entity_id = %s AND action = 'hr_settings.updated'", (TENANT,)).fetchone()[0]
    assert payload["changed"] == {"contract_expiry_horizon_days": 30, "trial_end_horizon_days": 15}


def test_a_cdd_ending_inside_the_horizon_is_listed_until_it_is_renewed(db, world):
    _horizons(db, world)
    _contract(db, world, end_date=D(2026, 10, 10))
    assert [(a["employee_no"], a["contract_type"], a["date"]) for a in _alerts(db)["contracts_ending"]] == [("A-001", "cdd", "2026-10-10")]
    _contract(db, world, start_date=D(2026, 10, 11), end_date=D(2027, 4, 10))
    assert _alerts(db)["contracts_ending"] == []


def test_a_trial_is_listed_only_inside_its_own_horizon(db, world):
    _horizons(db, world)
    _contract(db, world, contract_type="cdi", start_date=D(2026, 8, 1), trial_end_date=D(2026, 10, 5))
    assert [a["date"] for a in _alerts(db)["trials_ending"]] == ["2026-10-05"]


def test_a_trial_ending_after_the_horizon_is_not_listed(db, world):
    _horizons(db, world)
    _contract(db, world, contract_type="cdi", start_date=D(2026, 8, 1), trial_end_date=D(2026, 10, 20))
    assert _alerts(db)["trials_ending"] == []


def test_someone_who_left_raises_no_alert(db, world):
    _horizons(db, world)
    _contract(db, world, end_date=D(2026, 10, 10))
    DocumentService(db).create_document(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id,
        document=EmployeeDocument(kind="medical_certificate", expires_on=D(2026, 9, 1)),
    )
    EmployeeService(db).terminate_employee(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id, termination_date=D(2026, 9, 20), termination_reason="resignation"
    )
    alerts = _alerts(db)
    assert (alerts["contracts_ending"], alerts["documents_expiring"]) == ([], [])


def test_an_expired_document_is_listed_until_a_newer_one_of_the_same_kind_replaces_it(db, world):
    _horizons(db, world)
    documents = DocumentService(db)
    documents.create_document(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id,
        document=EmployeeDocument(kind="medical_certificate", expires_on=D(2026, 9, 1)),
    )
    assert [(a["kind"], a["state"]) for a in _alerts(db)["documents_expiring"]] == [("medical_certificate", "expired")]
    documents.create_document(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id,
        document=EmployeeDocument(kind="medical_certificate", issued_on=D(2026, 9, 20), expires_on=D(2027, 9, 20)),
    )
    assert _alerts(db)["documents_expiring"] == []


def test_the_document_list_carries_each_state_and_edits_are_audited(db, world):
    _horizons(db, world)
    documents = DocumentService(db)
    created = documents.create_document(
        tenant_id=TENANT, actor_id=world.actor, employee_id=world.employee_id,
        document=EmployeeDocument(kind="passport", expires_on=D(2026, 10, 10)),
    ).value
    assert created["state"] is not None
    [listed] = documents.list_documents(tenant_id=TENANT, employee_id=world.employee_id, today=TODAY)
    assert listed["state"] == "expiring"
    edited = documents.update_document(tenant_id=TENANT, actor_id=world.actor, document_id=created["id"], changes={"expires_on": D(2031, 1, 1)})
    assert edited.value["expires_on"] == "2031-01-01"
    actions = sorted(r[0] for r in db.execute("SELECT action FROM core.audit_log WHERE entity_id = %s", (created["id"],)).fetchall())
    assert actions == ["document.created", "document.updated"]
```

`backend/modules/hr/api/test_documents_alerts_routes_integration.py`:

```python
"""Documents, settings and alerts over HTTP."""
from __future__ import annotations


def test_settings_are_read_with_view_employees_and_saved_with_admin_employees(hr_api):
    hr_api.grant("hr.view_employees")
    assert hr_api.client.get("/hr/settings").json() == {
        "contract_expiry_horizon_days": None, "trial_end_horizon_days": None, "document_expiry_horizon_days": None,
    }
    body = {"contract_expiry_horizon_days": 30, "trial_end_horizon_days": 15, "document_expiry_horizon_days": None}
    assert hr_api.client.put("/hr/settings", json=body).status_code == 403
    hr_api.grant("hr.admin_employees")
    assert hr_api.client.put("/hr/settings", json=body).json()["trial_end_horizon_days"] == 15
    assert hr_api.client.get("/hr/alerts/expiries").json()["contracts_ending"] == []


def test_documents_are_added_with_manage_and_corrected_with_admin(hr_api):
    hr_api.grant("hr.manage_employees", "hr.view_employees")
    body = {"employee_no": "D-1", "first_name": "Rokia", "last_name": "Touré", "hire_date": "2024-01-01"}
    employee_id = hr_api.client.post("/hr/employees", json=body).json()["id"]
    created = hr_api.client.post(f"/hr/employees/{employee_id}/documents", json={"kind": "passport", "expires_on": "2030-01-01"})
    assert created.status_code == 201
    assert [d["kind"] for d in hr_api.client.get(f"/hr/employees/{employee_id}/documents").json()] == ["passport"]
    assert hr_api.client.patch(f"/hr/documents/{created.json()['id']}", json={"title": "Passeport"}).status_code == 403
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_document.py modules/hr/domain/test_alerts.py modules/hr/api/test_documents_alerts_integration.py modules/hr/api/test_documents_alerts_routes_integration.py -q`
Expected: FAIL — `No module named 'modules.hr.domain.document'` / `'modules.hr.domain.alerts'`.

- [ ] **Step 3: Write the migrations and classify the tables**

`backend/modules/hr/migrations/0008_hr_employee_documents.sql`:

```sql
-- An employee's papers and when they expire. The platform has no file storage yet: file_ref
-- says where the scan is kept (a path or a URL).
CREATE TABLE IF NOT EXISTS hr.employee_documents (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    employee_id TEXT NOT NULL REFERENCES hr.employees (id),
    kind TEXT NOT NULL CONSTRAINT hr_employee_documents_kind_check CHECK (kind IN (
        'id_card', 'passport', 'work_permit', 'medical_certificate', 'driving_licence',
        'diploma', 'criminal_record', 'signed_contract', 'other'
    )),
    title TEXT,
    file_ref TEXT,
    issued_on DATE,
    expires_on DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT hr_employee_documents_dates_check CHECK (issued_on IS NULL OR expires_on IS NULL OR expires_on >= issued_on)
);
CREATE INDEX IF NOT EXISTS hr_employee_documents_employee_idx ON hr.employee_documents (tenant_id, employee_id);
CREATE INDEX IF NOT EXISTS hr_employee_documents_expiry_idx ON hr.employee_documents (tenant_id, expires_on) WHERE expires_on IS NOT NULL;
```

`backend/modules/hr/migrations/0009_hr_settings.sql`:

```sql
-- How many days ahead HR is warned about contracts ending, trial periods ending and documents
-- expiring. Empty until HR sets them: an unset horizon switches that alert list off.
CREATE TABLE IF NOT EXISTS hr.settings (
    tenant_id TEXT PRIMARY KEY,
    contract_expiry_horizon_days INTEGER CONSTRAINT hr_settings_contract_days_check
        CHECK (contract_expiry_horizon_days IS NULL OR contract_expiry_horizon_days > 0),
    trial_end_horizon_days INTEGER CONSTRAINT hr_settings_trial_days_check
        CHECK (trial_end_horizon_days IS NULL OR trial_end_horizon_days > 0),
    document_expiry_horizon_days INTEGER CONSTRAINT hr_settings_document_days_check
        CHECK (document_expiry_horizon_days IS NULL OR document_expiry_horizon_days > 0),
    updated_by TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

In `backend/scripts/reset_operational_data.py`, add `"hr.employee_documents",` to `PURGE_TABLES` right after `"hr.employees",`, and `"hr.settings",` to `KEPT_TABLES` right after `"hr.grades",`.

Apply with the Global Constraints command. Expected: no output, exit 0.

- [ ] **Step 4: Write the domain rules**

`backend/modules/hr/domain/document.py`:

```python
"""An employee's papers. Pure rules, no database."""
from __future__ import annotations

import datetime
from dataclasses import dataclass

from core.domain.result import Err, Ok, Result

DOCUMENT_KINDS = (
    "id_card",
    "passport",
    "work_permit",
    "medical_certificate",
    "driving_licence",
    "diploma",
    "criminal_record",
    "signed_contract",
    "other",
)


@dataclass(frozen=True)
class EmployeeDocument:
    kind: str
    title: str | None = None
    file_ref: str | None = None
    issued_on: datetime.date | None = None
    expires_on: datetime.date | None = None


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def validate_document(document: EmployeeDocument) -> Result[EmployeeDocument]:
    if document.kind not in DOCUMENT_KINDS:
        return Err("INVALID_CHOICE", "unknown document kind", "type de document inconnu")
    title = _text(document.title)
    if document.kind == "other" and title is None:
        return Err("INVALID_DOCUMENT", "an 'other' document needs a title", "un document « autre » demande un intitulé")
    if document.issued_on is not None and document.expires_on is not None and document.expires_on < document.issued_on:
        return Err("INVALID_DATES", "a document cannot expire before it is issued", "un document ne peut pas expirer avant sa délivrance")
    return Ok(
        EmployeeDocument(
            kind=document.kind, title=title, file_ref=_text(document.file_ref), issued_on=document.issued_on, expires_on=document.expires_on
        )
    )
```

`backend/modules/hr/domain/alerts.py`:

```python
"""How far ahead HR is warned. Every horizon is a setting HR records (hr.settings); with none set,
nothing is judged "expiring". Pure rules, no database."""
from __future__ import annotations

import datetime
from collections.abc import Mapping

from core.domain.result import Err, Ok, Result

HORIZON_KEYS = ("contract_expiry_horizon_days", "trial_end_horizon_days", "document_expiry_horizon_days")


def validate_horizons(horizons: Mapping[str, int | None]) -> Result[dict]:
    clean: dict[str, int | None] = {}
    for key in HORIZON_KEYS:
        value = horizons.get(key)
        if value is not None and value <= 0:
            return Err(
                "INVALID_SETTING",
                "an alert horizon is a number of days above 0, or empty",
                "un horizon d'alerte est un nombre de jours supérieur à 0, ou vide",
            )
        clean[key] = value
    return Ok(clean)


def window_end(today: datetime.date, days: int | None) -> datetime.date | None:
    """The last day inside the horizon, or None when no horizon is set."""
    return None if days is None else today + datetime.timedelta(days=days)


def expiry_state(expires_on: datetime.date | None, today: datetime.date, horizon_days: int | None) -> str | None:
    """'expired' is a fact; 'expiring' needs a horizon HR has set; None when the paper never expires."""
    if expires_on is None:
        return None
    if expires_on < today:
        return "expired"
    end = window_end(today, horizon_days)
    if end is not None and expires_on <= end:
        return "expiring"
    return "valid"
```

- [ ] **Step 5: Write the services**

`backend/modules/hr/api/settings_service.py`:

```python
"""hr.settings: the alert horizons, one row per tenant, empty until HR sets them."""
from __future__ import annotations

import psycopg

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.support import change_payload
from modules.hr.domain.alerts import HORIZON_KEYS, validate_horizons


class HrSettingsService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def get(self, tenant_id: str) -> dict:
        row = self.connection.execute(f"SELECT {', '.join(HORIZON_KEYS)} FROM hr.settings WHERE tenant_id = %s", (tenant_id,)).fetchone()
        return dict(zip(HORIZON_KEYS, row or (None,) * len(HORIZON_KEYS)))

    def save(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        contract_expiry_horizon_days: int | None,
        trial_end_horizon_days: int | None,
        document_expiry_horizon_days: int | None,
    ) -> Result[dict]:
        validated = validate_horizons(
            {
                "contract_expiry_horizon_days": contract_expiry_horizon_days,
                "trial_end_horizon_days": trial_end_horizon_days,
                "document_expiry_horizon_days": document_expiry_horizon_days,
            }
        )
        if isinstance(validated, Err):
            return validated
        before = self.get(tenant_id)
        values = validated.value
        self.connection.execute(
            """
            INSERT INTO hr.settings (tenant_id, contract_expiry_horizon_days, trial_end_horizon_days, document_expiry_horizon_days, updated_by, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (tenant_id) DO UPDATE SET
                contract_expiry_horizon_days = EXCLUDED.contract_expiry_horizon_days,
                trial_end_horizon_days = EXCLUDED.trial_end_horizon_days,
                document_expiry_horizon_days = EXCLUDED.document_expiry_horizon_days,
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
            """,
            (tenant_id, *(values[key] for key in HORIZON_KEYS), actor_id),
        )
        after = self.get(tenant_id)
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="hr_settings.updated",
            entity_type="hr_settings", entity_id=tenant_id, payload=change_payload(before, after),
        )
        return Ok(after)
```

`backend/modules/hr/api/document_service.py`:

```python
"""An employee's papers: add, list with their expiry state, correct."""
from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import asdict, replace

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.hr.api.settings_service import HrSettingsService
from modules.hr.api.support import change_payload, iso_dates, json_safe, missing_reference
from modules.hr.domain.alerts import expiry_state
from modules.hr.domain.document import EmployeeDocument, validate_document

# EmployeeDocument's field order, which is also the column order used below.
_COLUMNS = ("kind", "title", "file_ref", "issued_on", "expires_on")
_SELECT = f"SELECT id, employee_id, {', '.join(_COLUMNS)} FROM hr.employee_documents"
_INSERT = f"INSERT INTO hr.employee_documents (id, tenant_id, employee_id, {', '.join(_COLUMNS)}) VALUES ({', '.join(['%s'] * (len(_COLUMNS) + 3))})"
_UPDATE = "UPDATE hr.employee_documents SET " + ", ".join(f"{name} = %s" for name in _COLUMNS) + " WHERE id = %s AND tenant_id = %s"


class DocumentService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def _record(self, row, today: datetime.date, horizon: int | None) -> dict:
        document = EmployeeDocument(*row[2:])
        return {"id": row[0], "employee_id": row[1], **iso_dates(asdict(document)), "state": expiry_state(document.expires_on, today, horizon)}

    def _horizon(self, tenant_id: str) -> int | None:
        return HrSettingsService(self.connection).get(tenant_id)["document_expiry_horizon_days"]

    def list_documents(self, *, tenant_id: str, employee_id: str, today: datetime.date | None = None) -> list[dict]:
        day = today or datetime.date.today()
        horizon = self._horizon(tenant_id)
        rows = self.connection.execute(
            f"{_SELECT} WHERE tenant_id = %s AND employee_id = %s ORDER BY expires_on NULLS LAST, kind", (tenant_id, employee_id)
        ).fetchall()
        return [self._record(row, day, horizon) for row in rows]

    def get_document(self, *, tenant_id: str, document_id: str) -> dict | None:
        row = self.connection.execute(f"{_SELECT} WHERE tenant_id = %s AND id = %s", (tenant_id, document_id)).fetchone()
        return None if row is None else self._record(row, datetime.date.today(), self._horizon(tenant_id))

    def create_document(self, *, tenant_id: str, actor_id: str, employee_id: str, document: EmployeeDocument) -> Result[dict]:
        refused = missing_reference(self.connection, "hr.employees", tenant_id, employee_id, "employee", "employé")
        if refused:
            return refused
        validated = validate_document(document)
        if isinstance(validated, Err):
            return validated
        clean = validated.value
        document_id = str(ULID())
        self.connection.execute(_INSERT, (document_id, tenant_id, employee_id, *(getattr(clean, name) for name in _COLUMNS)))
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="document.created",
            entity_type="document", entity_id=document_id, payload={"employee_id": employee_id, **json_safe(clean)},
        )
        return Ok(self.get_document(tenant_id=tenant_id, document_id=document_id))

    def update_document(self, *, tenant_id: str, actor_id: str, document_id: str, changes: Mapping[str, object]) -> Result[dict]:
        row = self.connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM hr.employee_documents WHERE id = %s AND tenant_id = %s FOR UPDATE", (document_id, tenant_id)
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", "document not found", "document introuvable")
        current = EmployeeDocument(*row)
        validated = validate_document(replace(current, **changes))
        if isinstance(validated, Err):
            return validated
        clean = validated.value
        self.connection.execute(_UPDATE, (*(getattr(clean, name) for name in _COLUMNS), document_id, tenant_id))
        record_audit(
            self.connection, tenant_id=tenant_id, actor_id=actor_id, action="document.updated",
            entity_type="document", entity_id=document_id, payload=change_payload(asdict(current), asdict(clean)),
        )
        return Ok(self.get_document(tenant_id=tenant_id, document_id=document_id))
```

`backend/modules/hr/api/alert_service.py`:

```python
"""What falls due inside the horizons HR set: contracts ending, trial periods ending, documents
to renew. People who left raise nothing; a contract already renewed and a paper already replaced
by a newer one of the same kind raise nothing either."""
from __future__ import annotations

import datetime

import psycopg

from modules.hr.api.settings_service import HrSettingsService
from modules.hr.domain.alerts import expiry_state, window_end

# A renewal is a signed contract of the same person starting after this one ends.
_NOT_RENEWED = """
    AND NOT EXISTS (
        SELECT 1 FROM hr.contracts n
        WHERE n.tenant_id = c.tenant_id AND n.employee_id = c.employee_id AND n.status <> 'draft' AND n.start_date > c.end_date
    )
"""


class HrAlertService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def expiry_alerts(self, *, tenant_id: str, today: datetime.date) -> dict:
        settings = HrSettingsService(self.connection).get(tenant_id)
        return {
            "as_of": today.isoformat(),
            **settings,
            "contracts_ending": self._contracts(tenant_id, "end_date", today, window_end(today, settings["contract_expiry_horizon_days"])),
            "trials_ending": self._contracts(tenant_id, "trial_end_date", today, window_end(today, settings["trial_end_horizon_days"])),
            "documents_expiring": self._documents(tenant_id, today, settings["document_expiry_horizon_days"]),
        }

    def _contracts(self, tenant_id: str, column: str, today: datetime.date, until: datetime.date | None) -> list[dict]:
        # `column` is one of the two literals above, never user input.
        if until is None:
            return []
        renewal = _NOT_RENEWED if column == "end_date" else ""
        rows = self.connection.execute(
            f"""
            SELECT c.id, c.employee_id, e.employee_no, e.first_name || ' ' || e.last_name, c.contract_type, c.{column}
            FROM hr.contracts c
            JOIN hr.employees e ON e.id = c.employee_id
            WHERE c.tenant_id = %s AND c.status = 'active' AND e.status <> 'terminated'
              AND c.{column} BETWEEN %s AND %s {renewal}
            ORDER BY c.{column}, e.employee_no
            """,
            (tenant_id, today, until),
        ).fetchall()
        return [
            {"contract_id": r[0], "employee_id": r[1], "employee_no": r[2], "employee_name": r[3], "contract_type": r[4], "date": r[5].isoformat()}
            for r in rows
        ]

    def _documents(self, tenant_id: str, today: datetime.date, days: int | None) -> list[dict]:
        until = window_end(today, days)
        if until is None:
            return []
        rows = self.connection.execute(
            """
            SELECT d.id, d.employee_id, e.employee_no, e.first_name || ' ' || e.last_name, d.kind, d.title, d.expires_on
            FROM hr.employee_documents d
            JOIN hr.employees e ON e.id = d.employee_id
            WHERE d.tenant_id = %s AND e.status <> 'terminated' AND d.expires_on IS NOT NULL AND d.expires_on <= %s
              AND (d.kind = 'other' OR NOT EXISTS (
                    SELECT 1 FROM hr.employee_documents n
                    WHERE n.tenant_id = d.tenant_id AND n.employee_id = d.employee_id AND n.kind = d.kind AND n.id <> d.id
                      AND (n.expires_on IS NULL OR n.expires_on > d.expires_on)))
            ORDER BY d.expires_on, e.employee_no
            """,
            (tenant_id, until),
        ).fetchall()
        return [
            {
                "document_id": r[0],
                "employee_id": r[1],
                "employee_no": r[2],
                "employee_name": r[3],
                "kind": r[4],
                "title": r[5],
                "expires_on": r[6].isoformat(),
                "state": expiry_state(r[6], today, days),
            }
            for r in rows
        ]
```

- [ ] **Step 6: Add the bodies and routes**

Append to `backend/modules/hr/api/schemas.py`:

```python
class DocumentCreate(BaseModel):
    kind: str
    title: str | None = None
    file_ref: str | None = None
    issued_on: datetime.date | None = None
    expires_on: datetime.date | None = None


class DocumentPatch(BaseModel):
    kind: str | None = None
    title: str | None = None
    file_ref: str | None = None
    issued_on: datetime.date | None = None
    expires_on: datetime.date | None = None


class SettingsBody(BaseModel):
    contract_expiry_horizon_days: int | None = None
    trial_end_horizon_days: int | None = None
    document_expiry_horizon_days: int | None = None
```

In `router.py`, extend the imports:

```python
from modules.hr.api.alert_service import HrAlertService
from modules.hr.api.document_service import DocumentService
from modules.hr.api.settings_service import HrSettingsService
from modules.hr.api.schemas import DocumentCreate, DocumentPatch, SettingsBody
from modules.hr.domain.document import EmployeeDocument
```

and append:

```python
# ---- documents, settings, alerts --------------------------------------------------------------


@router.get("/employees/{employee_id}/documents")
def list_documents(employee_id: str, tenant: TenantContext = Depends(require_permission("hr.view_employees"))):
    with get_connection() as connection:
        return DocumentService(connection).list_documents(tenant_id=tenant.tenant_id, employee_id=employee_id)


@router.post("/employees/{employee_id}/documents", status_code=status.HTTP_201_CREATED)
def create_document(employee_id: str, body: DocumentCreate, tenant: TenantContext = Depends(require_permission("hr.manage_employees"))):
    with get_connection() as connection:
        result = DocumentService(connection).create_document(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, employee_id=employee_id, document=EmployeeDocument(**body.model_dump())
        )
        return respond(connection, result)


@router.patch("/documents/{document_id}")
def update_document(document_id: str, body: DocumentPatch, tenant: TenantContext = Depends(require_permission("hr.admin_employees"))):
    with get_connection() as connection:
        result = DocumentService(connection).update_document(
            tenant_id=tenant.tenant_id, actor_id=tenant.user_id, document_id=document_id, changes=body.model_dump(exclude_unset=True)
        )
        return respond(connection, result)


@router.get("/settings")
def get_settings(tenant: TenantContext = Depends(require_permission("hr.view_employees"))):
    with get_connection() as connection:
        return HrSettingsService(connection).get(tenant.tenant_id)


@router.put("/settings")
def save_settings(body: SettingsBody, tenant: TenantContext = Depends(require_permission("hr.admin_employees"))):
    with get_connection() as connection:
        result = HrSettingsService(connection).save(tenant_id=tenant.tenant_id, actor_id=tenant.user_id, **body.model_dump())
        return respond(connection, result)


@router.get("/alerts/expiries")
def expiry_alerts(tenant: TenantContext = Depends(require_permission("hr.view_employees"))):
    with get_connection() as connection:
        return HrAlertService(connection).expiry_alerts(tenant_id=tenant.tenant_id, today=datetime.date.today())
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr core/test_error_translations.py scripts/test_reset_operational_data_integration.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/modules/hr/migrations/0008_hr_employee_documents.sql backend/modules/hr/migrations/0009_hr_settings.sql backend/modules/hr/domain/document.py backend/modules/hr/domain/test_document.py backend/modules/hr/domain/alerts.py backend/modules/hr/domain/test_alerts.py backend/modules/hr/api/document_service.py backend/modules/hr/api/settings_service.py backend/modules/hr/api/alert_service.py backend/modules/hr/api/schemas.py backend/modules/hr/api/router.py backend/modules/hr/api/test_documents_alerts_integration.py backend/modules/hr/api/test_documents_alerts_routes_integration.py backend/scripts/reset_operational_data.py
git commit -m "feat(hr): employee documents, alert horizons as settings, expiry alerts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: PayrollSnapshotService — the contract with phase 3

**Files:**
- Create: `backend/modules/hr/domain/snapshot.py`, `backend/modules/hr/domain/test_snapshot.py`
- Create: `backend/modules/hr/api/payroll_snapshot_service.py`
- Test: `backend/modules/hr/api/test_payroll_snapshot_integration.py`

**Interfaces:**
- Consumes: tables from Tasks 2–8; `count_tax_dependants`, `Dependant` (Task 4); `set_in_force` (Task 4).
- Produces (exactly the contract): `PayrollSnapshotService(connection).employees_for_period(*, tenant_id: str, period: datetime.date, employee_ids: list[str] | None = None) -> list[dict]`, ordered by `employee_no`. Each dict: `employee_id, employee_no, full_name, department_id, position_id, grade_id, hire_date (date), termination_date (date|None), termination_reason (str|None), inps_no (str|None), amo_no (str|None), tax_dependants (int), contract: {id, contract_type, base_salary: Decimal, weekly_hours: Decimal, pay_frequency, start_date (date), end_date (date|None), components: [{component_code, amount: Decimal|None, rate: Decimal|None}]}, payment_methods: [{method, bank_name, account_no, mobile_operator, mobile_number, share_percent: Decimal, is_primary}]`. `inps_no`/`amo_no` travel unmasked here — this is a server-side, module-to-module read, not the masked employee-file response Task 3 builds for HTTP callers — so payroll can print them on INPS/AMO declarations without payroll ever touching `hr.*` tables directly.
- Rules: "active contract on any day of the period" = a non-draft XOF contract whose `[start_date, end_date]` touches the month; when two touch it (amendment mid-month), the one that starts last is returned; `tax_dependants` and `payment_methods` are taken on the last day of the month; a `period` that is not the 1st of a month raises `ValueError` (a programming error, not a user refusal); unmasked (server-side consumer).

- [ ] **Step 1: Write the failing tests**

`backend/modules/hr/domain/test_snapshot.py`:

```python
from datetime import date

import pytest

from modules.hr.domain.snapshot import month_bounds, pick_contract


def test_month_bounds_know_month_lengths_and_leap_years():
    assert month_bounds(date(2026, 2, 1)) == (date(2026, 2, 1), date(2026, 2, 28))
    assert month_bounds(date(2028, 2, 1))[1] == date(2028, 2, 29)
    assert month_bounds(date(2026, 12, 1))[1] == date(2026, 12, 31)


def test_a_period_is_the_first_day_of_a_month():
    with pytest.raises(ValueError):
        month_bounds(date(2026, 2, 15))


def test_payroll_pays_from_the_latest_contract_that_touches_the_month():
    old = {"start_date": date(2025, 1, 1), "end_date": date(2026, 9, 14)}
    new = {"start_date": date(2026, 9, 15), "end_date": None}
    future = {"start_date": date(2026, 10, 1), "end_date": None}
    assert pick_contract([old, new, future], date(2026, 9, 1), date(2026, 9, 30)) is new
    assert pick_contract([old], date(2026, 10, 1), date(2026, 10, 31)) is None
```

`backend/modules/hr/api/test_payroll_snapshot_integration.py`:

```python
"""What payroll (phase 3) reads from hr for a month, against a real database."""
from __future__ import annotations

import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from ulid import ULID

from modules.hr.api.contract_service import ContractService
from modules.hr.api.dependant_service import DependantService
from modules.hr.api.organisation_service import DepartmentService
from modules.hr.api.payment_method_service import PaymentMethodService
from modules.hr.api.payroll_snapshot_service import PayrollSnapshotService
from modules.hr.api.service import EmployeeService
from modules.hr.domain.contract import ContractComponent, ContractTerms
from modules.hr.domain.dependant import Dependant
from modules.hr.domain.employee import EmployeeFile
from modules.hr.domain.payment import PaymentMethod

TENANT = "hr-snapshot-test"
SEPTEMBER = datetime.date(2026, 9, 1)
D = datetime.date


@pytest.fixture
def world(db):
    actor = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (actor, TENANT, f"{actor}@test.local"),
    )
    department = DepartmentService(db).create_department(tenant_id=TENANT, actor_id=actor, code="PROD", name="Production").value

    def employee(number: str, hired: datetime.date = D(2020, 1, 1)) -> str:
        return EmployeeService(db).create_employee(
            tenant_id=TENANT, actor_id=actor,
            employee=EmployeeFile(employee_no=number, first_name="Awa", last_name="Traoré", hire_date=hired, department_id=department["id"]),
        ).value["id"]

    def contract(employee_id: str, **overrides) -> dict:
        terms = ContractTerms(**{"employee_id": employee_id, "contract_type": "cdi", "start_date": D(2020, 1, 1), "base_salary": Decimal("250000"), **overrides})
        return ContractService(db).create_contract(tenant_id=TENANT, actor_id=actor, terms=terms).value

    return SimpleNamespace(actor=actor, department_id=department["id"], employee=employee, contract=contract)


def _snapshot(db, period=SEPTEMBER, employee_ids=None):
    return PayrollSnapshotService(db).employees_for_period(tenant_id=TENANT, period=period, employee_ids=employee_ids)


def test_an_employee_under_contract_during_the_month_comes_with_every_field(db, world):
    employee_id = world.employee("S-001")
    world.contract(
        employee_id,
        components=(
            ContractComponent(component_code="TRANSPORT", amount=Decimal("15000")),
            ContractComponent(component_code="HOUSING", rate=Decimal("10")),
        ),
    )
    dependants = DependantService(db)
    for dependant in (
        Dependant(kind="spouse", name="Mariam", valid_from=D(2015, 6, 1), dependent_for_tax=True),
        Dependant(kind="child", name="Issa", valid_from=D(2019, 2, 1), dependent_for_tax=True, valid_to=D(2026, 9, 15)),
        Dependant(kind="child", name="Awa", valid_from=D(2010, 1, 1), dependent_for_tax=False),
    ):
        dependants.create_dependant(tenant_id=TENANT, actor_id=world.actor, employee_id=employee_id, dependant=dependant)
    payments = PaymentMethodService(db)
    payments.replace_set(
        tenant_id=TENANT, actor_id=world.actor, employee_id=employee_id, valid_from=D(2025, 1, 1),
        methods=[PaymentMethod(method="bank", share_percent=Decimal("100"), is_primary=True, bank_name="BDM-SA", account_no="ML-1")],
    )
    payments.replace_set(
        tenant_id=TENANT, actor_id=world.actor, employee_id=employee_id, valid_from=D(2026, 10, 1),
        methods=[PaymentMethod(method="cash", share_percent=Decimal("100"), is_primary=True)],
    )

    [snapshot] = _snapshot(db)

    assert (snapshot["employee_id"], snapshot["employee_no"], snapshot["full_name"], snapshot["department_id"]) == (
        employee_id, "S-001", "Awa Traoré", world.department_id,
    )
    assert (snapshot["hire_date"], snapshot["termination_date"], snapshot["termination_reason"]) == (D(2020, 1, 1), None, None)
    assert snapshot["tax_dependants"] == 1  # Issa stopped counting on the 15th; the count is taken on the 30th
    contract = snapshot["contract"]
    assert (contract["contract_type"], contract["base_salary"], contract["weekly_hours"], contract["pay_frequency"]) == (
        "cdi", Decimal("250000"), Decimal("40.00"), "monthly",
    )
    assert (contract["start_date"], contract["end_date"]) == (D(2020, 1, 1), None)
    assert contract["components"] == [
        {"component_code": "HOUSING", "amount": None, "rate": Decimal("10.0000")},
        {"component_code": "TRANSPORT", "amount": Decimal("15000"), "rate": None},
    ]
    assert snapshot["payment_methods"] == [
        {"method": "bank", "bank_name": "BDM-SA", "account_no": "ML-1", "mobile_operator": None, "mobile_number": None,
         "share_percent": Decimal("100.00"), "is_primary": True}
    ]


def test_an_amendment_mid_month_gives_the_new_terms(db, world):
    employee_id = world.employee("S-001")
    old = world.contract(employee_id)
    new = ContractService(db).amend_contract(
        tenant_id=TENANT, actor_id=world.actor, contract_id=old["id"], effective_date=D(2026, 9, 15), changes={"base_salary": Decimal("300000")}
    ).value
    [snapshot] = _snapshot(db)
    assert (snapshot["contract"]["id"], snapshot["contract"]["base_salary"], snapshot["contract"]["start_date"]) == (
        new["id"], Decimal("300000"), D(2026, 9, 15),
    )


def test_someone_who_left_during_the_month_is_in_it_with_the_exit_and_not_after(db, world):
    employee_id = world.employee("S-001")
    world.contract(employee_id)
    EmployeeService(db).terminate_employee(
        tenant_id=TENANT, actor_id=world.actor, employee_id=employee_id, termination_date=D(2026, 9, 20), termination_reason="resignation"
    )
    [snapshot] = _snapshot(db)
    assert (snapshot["termination_date"], snapshot["termination_reason"], snapshot["contract"]["end_date"]) == (
        D(2026, 9, 20), "resignation", D(2026, 9, 20),
    )
    assert _snapshot(db, period=D(2026, 10, 1)) == []


def test_a_draft_contract_puts_nobody_on_the_payroll(db, world):
    employee_id = world.employee("S-001")
    world.contract(employee_id, status="draft")
    assert _snapshot(db) == []


def test_someone_hired_during_the_month_is_in_it_with_no_payment_method_yet(db, world):
    employee_id = world.employee("S-001", hired=D(2026, 9, 10))
    world.contract(employee_id, start_date=D(2026, 9, 10))
    [snapshot] = _snapshot(db)
    assert (snapshot["contract"]["start_date"], snapshot["payment_methods"], snapshot["tax_dependants"]) == (D(2026, 9, 10), [], 0)


def test_the_list_can_be_narrowed_to_some_employees(db, world):
    first, second = world.employee("S-001"), world.employee("S-002")
    world.contract(first)
    world.contract(second)
    assert [s["employee_no"] for s in _snapshot(db)] == ["S-001", "S-002"]
    assert [s["employee_id"] for s in _snapshot(db, employee_ids=[second])] == [second]


def test_a_period_must_be_the_first_of_the_month(db):
    with pytest.raises(ValueError):
        PayrollSnapshotService(db).employees_for_period(tenant_id=TENANT, period=D(2026, 9, 15))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/hr/domain/test_snapshot.py modules/hr/api/test_payroll_snapshot_integration.py -q`
Expected: FAIL — `No module named 'modules.hr.domain.snapshot'`.

- [ ] **Step 3: Implement**

`backend/modules/hr/domain/snapshot.py`:

```python
"""Which days a pay period covers and which contract payroll pays from. Pure rules, no database."""
from __future__ import annotations

import datetime
from collections.abc import Sequence


def month_bounds(period: datetime.date) -> tuple[datetime.date, datetime.date]:
    if period.day != 1:
        raise ValueError(f"a pay period is the first day of a month, not {period.isoformat()}")
    next_month = (period.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return period, next_month - datetime.timedelta(days=1)


def pick_contract(contracts: Sequence[dict], first: datetime.date, last: datetime.date) -> dict | None:
    """Of the contracts touching [first, last], the one that starts last (after an amendment in
    the month, the new terms)."""
    touching = [c for c in contracts if c["start_date"] <= last and (c["end_date"] is None or c["end_date"] >= first)]
    return max(touching, key=lambda c: c["start_date"], default=None)
```

`backend/modules/hr/api/payroll_snapshot_service.py`:

```python
"""What payroll (phase 3) reads from hr for one month. Server-side, so nothing is masked.
Contract with phase 3: docs/superpowers/plans/2026-09-25-hr-payroll-finance-interfaces.md."""
from __future__ import annotations

import datetime

import psycopg

from modules.hr.domain.dependant import Dependant, count_tax_dependants
from modules.hr.domain.payment import set_in_force
from modules.hr.domain.snapshot import month_bounds, pick_contract


class PayrollSnapshotService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self.connection = connection

    def employees_for_period(
        self, *, tenant_id: str, period: datetime.date, employee_ids: list[str] | None = None
    ) -> list[dict]:
        """Employees with an active contract on any day of the period."""
        first, last = month_bounds(period)
        params: list[object] = [tenant_id, last, first]
        narrow = ""
        if employee_ids is not None:
            narrow = " AND employee_id = ANY(%s)"
            params.append(list(employee_ids))
        rows = self.connection.execute(
            f"""
            SELECT id, employee_id, contract_type, base_salary, weekly_hours, pay_frequency, start_date, end_date
            FROM hr.contracts
            WHERE tenant_id = %s AND status <> 'draft' AND currency = 'XOF'
              AND start_date <= %s AND (end_date IS NULL OR end_date >= %s){narrow}
            """,
            params,
        ).fetchall()
        by_employee: dict[str, list[dict]] = {}
        for r in rows:
            by_employee.setdefault(r[1], []).append(
                {"id": r[0], "contract_type": r[2], "base_salary": r[3], "weekly_hours": r[4], "pay_frequency": r[5], "start_date": r[6], "end_date": r[7]}
            )
        chosen = {employee_id: pick_contract(contracts, first, last) for employee_id, contracts in by_employee.items()}
        if not chosen:
            return []
        ids = list(chosen)
        components = self._components([contract["id"] for contract in chosen.values()])
        dependants = self._dependants(tenant_id, ids)
        payments = self._payment_methods(tenant_id, ids, last)
        employees = self.connection.execute(
            """
            SELECT id, employee_no, first_name, last_name, department_id, position_id, grade_id, hire_date, termination_date, termination_reason, inps_no, amo_no
            FROM hr.employees WHERE tenant_id = %s AND id = ANY(%s) ORDER BY employee_no
            """,
            (tenant_id, ids),
        ).fetchall()
        return [
            {
                "employee_id": e[0],
                "employee_no": e[1],
                "full_name": f"{e[2]} {e[3]}",
                "department_id": e[4],
                "position_id": e[5],
                "grade_id": e[6],
                "hire_date": e[7],
                "termination_date": e[8],
                "termination_reason": e[9],
                "inps_no": e[10],
                "amo_no": e[11],
                "tax_dependants": count_tax_dependants(dependants.get(e[0], []), last),
                "contract": {**chosen[e[0]], "components": components.get(chosen[e[0]]["id"], [])},
                "payment_methods": payments.get(e[0], []),
            }
            for e in employees
        ]

    def _components(self, contract_ids: list[str]) -> dict[str, list[dict]]:
        rows = self.connection.execute(
            "SELECT contract_id, component_code, amount, rate FROM hr.contract_components WHERE contract_id = ANY(%s) ORDER BY component_code",
            (contract_ids,),
        ).fetchall()
        found: dict[str, list[dict]] = {}
        for contract_id, code, amount, rate in rows:
            found.setdefault(contract_id, []).append({"component_code": code, "amount": amount, "rate": rate})
        return found

    def _dependants(self, tenant_id: str, employee_ids: list[str]) -> dict[str, list[Dependant]]:
        rows = self.connection.execute(
            "SELECT employee_id, kind, name, valid_from, birth_date, dependent_for_tax, valid_to FROM hr.dependants "
            "WHERE tenant_id = %s AND employee_id = ANY(%s)",
            (tenant_id, employee_ids),
        ).fetchall()
        found: dict[str, list[Dependant]] = {}
        for row in rows:
            found.setdefault(row[0], []).append(Dependant(*row[1:]))
        return found

    def _payment_methods(self, tenant_id: str, employee_ids: list[str], last: datetime.date) -> dict[str, list[dict]]:
        """The arrangement in force on the last day of the month."""
        rows = self.connection.execute(
            """
            SELECT employee_id, valid_from, method, bank_name, account_no, mobile_operator, mobile_number, share_percent, is_primary
            FROM hr.payment_methods
            WHERE tenant_id = %s AND employee_id = ANY(%s) AND valid_from <= %s
            ORDER BY employee_id, sort_order
            """,
            (tenant_id, employee_ids, last),
        ).fetchall()
        starts: dict[str, list[datetime.date]] = {}
        for row in rows:
            starts.setdefault(row[0], []).append(row[1])
        in_force = {employee_id: set_in_force(days, last) for employee_id, days in starts.items()}
        found: dict[str, list[dict]] = {}
        for row in rows:
            if row[1] != in_force[row[0]]:
                continue
            found.setdefault(row[0], []).append(
                {
                    "method": row[2],
                    "bank_name": row[3],
                    "account_no": row[4],
                    "mobile_operator": row[5],
                    "mobile_number": row[6],
                    "share_percent": row[7],
                    "is_primary": row[8],
                }
            )
        return found
```

Contracts in another currency (only legacy demo rows can be) are not payable by the XOF payroll and are left out; the employee file shows their currency so HR can re-issue them.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/hr -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/hr/domain/snapshot.py backend/modules/hr/domain/test_snapshot.py backend/modules/hr/api/payroll_snapshot_service.py backend/modules/hr/api/test_payroll_snapshot_integration.py
git commit -m "feat(hr): PayrollSnapshotService, the month's employees, contracts, dependants and payment methods

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Frontend — API client, shared pieces, `/hr/employees` and the HR nav

**Files:**
- Rewrite: `frontend/src/features/hr/api.ts` (legacy leave/attendance/payroll exports kept)
- Create: `frontend/src/features/hr/employeeFormat.ts`, `employeeLabels.ts`, `HrTable.tsx`, `FormField.tsx`, `EmployeeFormDialog.tsx`, `ExpiryAlertsCard.tsx`, `EmployeesPage.tsx`
- Modify: `frontend/src/features/hr/HrPage.tsx:1-60` (legacy page keeps leave, attendance, payroll)
- Modify: `frontend/src/routes/router.tsx`, `frontend/src/routes/Sidebar.tsx`, `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: every backend route of Tasks 2–8.
- Produces (used by Tasks 11–14): from `api.ts` — `hrKeys`, the enum arrays/types (`EMPLOYEE_STATUSES`, `GENDERS`, `MARITAL_STATUSES`, `END_REASONS`, `TERMINATION_REASONS`, `CONTRACT_TYPES`, `CONTRACT_STATUSES`, `PAY_FREQUENCIES`, `PAYMENT_METHODS`, `MOBILE_OPERATORS`, `DEPENDANT_KINDS`, `DOCUMENT_KINDS`, `DocumentState`), the record types and every fetcher listed in the file; `employeeFormat.ts` — `formatXof`, `formatDate`, `todayIso`, `emptyToNull`; `employeeLabels.ts` — `*_LABEL` and `*_VARIANT` maps; `HrTable<Row>` (props below); `FormField`; `EmployeeFormDialog({ open, onOpenChange, employee, onSaved? })` (`employee === null` creates).
- `HrTable` props: `tableKey, columns: ColumnDef<Row>[], rows, rowKey, isLoading?, loadingVariant?: "loader" | "skeleton" (default "skeleton"), empty: { icon, title, description }, toolbar?, filtersActive?, onClearFilters?, onRowClick?`.

- [ ] **Step 1: Rewrite the API client**

`frontend/src/features/hr/api.ts`:

```ts
import { apiFetch } from "../../lib/api";

// ---------------------------------------------------------------------------
// Query keys: every hr read lives under ["hr", ...], so one prefix refreshes a
// file and all its tabs.
// ---------------------------------------------------------------------------
export const hrKeys = {
  employees: ["hr", "employees"] as const,
  employee: (id: string) => ["hr", "employees", id] as const,
  dependants: (id: string) => ["hr", "employees", id, "dependants"] as const,
  paymentSets: (id: string) => ["hr", "employees", id, "payment-methods"] as const,
  documents: (id: string) => ["hr", "employees", id, "documents"] as const,
  contracts: ["hr", "contracts"] as const,
  employeeContracts: (id: string) => ["hr", "contracts", id] as const,
  departments: ["hr", "departments"] as const,
  positions: ["hr", "positions"] as const,
  grades: ["hr", "grades"] as const,
  settings: ["hr", "settings"] as const,
  alerts: ["hr", "alerts"] as const,
  leave: ["hr", "leave"] as const,
  dashboard: ["hr", "dashboard"] as const,
};

// ---------------------------------------------------------------------------
// Closed lists (mirrors of backend/modules/hr/domain/*.py)
// ---------------------------------------------------------------------------
export const EMPLOYEE_STATUSES = ["active", "on_leave", "inactive", "terminated"] as const;
export type EmployeeStatus = (typeof EMPLOYEE_STATUSES)[number];
export const GENDERS = ["male", "female"] as const;
export type Gender = (typeof GENDERS)[number];
export const MARITAL_STATUSES = ["single", "married", "divorced", "widowed"] as const;
export type MaritalStatus = (typeof MARITAL_STATUSES)[number];
export const END_REASONS = [
  "term_reached",
  "resignation",
  "dismissal",
  "trial_termination",
  "mutual_agreement",
  "retirement",
  "death",
  "amended",
  "other",
] as const;
export type EndReason = (typeof END_REASONS)[number];
export type TerminationReason = Exclude<EndReason, "amended">;
export const TERMINATION_REASONS: TerminationReason[] = [
  "term_reached",
  "resignation",
  "dismissal",
  "trial_termination",
  "mutual_agreement",
  "retirement",
  "death",
  "other",
];
export const CONTRACT_TYPES = ["cdi", "cdd", "apprentice", "daily", "intern"] as const;
export type ContractType = (typeof CONTRACT_TYPES)[number];
export const CONTRACT_STATUSES = ["draft", "active", "expired", "terminated"] as const;
export type ContractStatus = (typeof CONTRACT_STATUSES)[number];
export const PAY_FREQUENCIES = ["monthly", "daily"] as const;
export type PayFrequency = (typeof PAY_FREQUENCIES)[number];
export const PAYMENT_METHODS = ["bank", "mobile_money", "cash"] as const;
export type PaymentMethodKind = (typeof PAYMENT_METHODS)[number];
export const MOBILE_OPERATORS = ["orange_money", "moov_money"] as const;
export type MobileOperator = (typeof MOBILE_OPERATORS)[number];
export const DEPENDANT_KINDS = ["spouse", "child"] as const;
export type DependantKind = (typeof DEPENDANT_KINDS)[number];
export const DOCUMENT_KINDS = [
  "id_card",
  "passport",
  "work_permit",
  "medical_certificate",
  "driving_licence",
  "diploma",
  "criminal_record",
  "signed_contract",
  "other",
] as const;
export type DocumentKind = (typeof DOCUMENT_KINDS)[number];
export type DocumentState = "expired" | "expiring" | "valid";

// ---------------------------------------------------------------------------
// Employee file
// ---------------------------------------------------------------------------
export interface EmployeeListItem {
  id: string;
  employee_no: string;
  first_name: string;
  last_name: string;
  full_name: string;
  email: string | null;
  phone: string | null;
  department_id: string | null;
  department_name: string | null;
  job_title: string | null;
  hire_date: string;
  status: EmployeeStatus;
  position_id: string | null;
  position_title: string | null;
  grade_id: string | null;
  grade_code: string | null;
  site: string | null;
  badge_no: string | null;
  user_id: string | null;
  termination_date: string | null;
  contract_type: ContractType | null;
  contract_end_date: string | null;
}
/** Kept for the legacy leave / attendance screens. */
export type Employee = EmployeeListItem;

export interface EmployeeInput {
  employee_no: string;
  first_name: string;
  last_name: string;
  hire_date: string;
  status: EmployeeStatus;
  email?: string | null;
  phone?: string | null;
  department_id?: string | null;
  job_title?: string | null;
  user_id?: string | null;
  gender?: Gender | null;
  birth_date?: string | null;
  birth_place?: string | null;
  nationality?: string | null;
  national_id?: string | null;
  inps_no?: string | null;
  amo_no?: string | null;
  marital_status?: MaritalStatus | null;
  address?: string | null;
  emergency_contact?: string | null;
  badge_no?: string | null;
  position_id?: string | null;
  grade_id?: string | null;
  site?: string | null;
}
export type EmployeeChanges = Partial<Omit<EmployeeInput, "employee_no">>;

export interface EmployeeRecord extends Required<EmployeeInput> {
  id: string;
  full_name: string;
  department_name: string | null;
  position_title: string | null;
  grade_code: string | null;
  user_email: string | null;
  termination_date: string | null;
  termination_reason: TerminationReason | null;
  /** True when the caller lacks hr.view_sensitive: national_id, inps_no, amo_no came back null. */
  sensitive_hidden: boolean;
}

export function listEmployees(token: string) {
  return apiFetch<EmployeeListItem[]>("/hr/employees", { token });
}
export function getEmployee(token: string, id: string) {
  return apiFetch<EmployeeRecord>(`/hr/employees/${id}`, { token });
}
export function createEmployee(token: string, input: EmployeeInput) {
  return apiFetch<EmployeeRecord>("/hr/employees", { method: "POST", token, body: input });
}
export function updateEmployee(token: string, id: string, changes: EmployeeChanges) {
  return apiFetch<EmployeeRecord>(`/hr/employees/${id}`, { method: "PATCH", token, body: changes });
}
export function terminateEmployee(token: string, id: string, input: { termination_date: string; termination_reason: TerminationReason }) {
  return apiFetch<EmployeeRecord>(`/hr/employees/${id}/terminate`, { method: "POST", token, body: input });
}

// ---- family ----
export interface Dependant {
  id: string;
  employee_id: string;
  kind: DependantKind;
  name: string;
  valid_from: string;
  birth_date: string | null;
  dependent_for_tax: boolean;
  valid_to: string | null;
  counts_for_tax_today: boolean;
}
export type DependantInput = Omit<Dependant, "id" | "employee_id" | "counts_for_tax_today">;
export function listDependants(token: string, employeeId: string) {
  return apiFetch<Dependant[]>(`/hr/employees/${employeeId}/dependants`, { token });
}
export function createDependant(token: string, employeeId: string, input: DependantInput) {
  return apiFetch<Dependant>(`/hr/employees/${employeeId}/dependants`, { method: "POST", token, body: input });
}
export function updateDependant(token: string, id: string, changes: Partial<DependantInput>) {
  return apiFetch<Dependant>(`/hr/dependants/${id}`, { method: "PATCH", token, body: changes });
}

// ---- payment ----
export interface PaymentMethod {
  id: string;
  method: PaymentMethodKind;
  bank_name: string | null;
  account_no: string | null;
  mobile_operator: MobileOperator | null;
  mobile_number: string | null;
  share_percent: number;
  is_primary: boolean;
  sensitive_hidden: boolean;
}
export interface PaymentSet {
  valid_from: string;
  in_force: boolean;
  methods: PaymentMethod[];
}
export type PaymentMethodInput = Omit<PaymentMethod, "id" | "sensitive_hidden">;
export function listPaymentSets(token: string, employeeId: string) {
  return apiFetch<PaymentSet[]>(`/hr/employees/${employeeId}/payment-methods`, { token });
}
export function replacePaymentSet(token: string, employeeId: string, input: { valid_from: string; methods: PaymentMethodInput[] }) {
  return apiFetch<PaymentSet[]>(`/hr/employees/${employeeId}/payment-methods`, { method: "PUT", token, body: input });
}

// ---- contracts ----
export interface ContractComponent {
  component_code: string;
  amount: number | null;
  rate: number | null;
}
export interface Contract {
  id: string;
  employee_id: string;
  employee_name: string;
  contract_type: ContractType;
  start_date: string;
  base_salary: number | null;
  end_date: string | null;
  trial_end_date: string | null;
  weekly_hours: number;
  pay_frequency: PayFrequency;
  position_id: string | null;
  position_title: string | null;
  grade_id: string | null;
  grade_code: string | null;
  status: ContractStatus;
  amends_contract_id: string | null;
  end_reason: EndReason | null;
  currency: string;
  components: ContractComponent[];
  sensitive_hidden: boolean;
}
export interface ContractInput {
  employee_id: string;
  contract_type: ContractType;
  start_date: string;
  base_salary: number;
  end_date?: string | null;
  trial_end_date?: string | null;
  weekly_hours?: number;
  pay_frequency?: PayFrequency;
  position_id?: string | null;
  grade_id?: string | null;
  status?: "draft" | "active";
  components?: ContractComponent[];
}
export type ContractChanges = Partial<Omit<ContractInput, "employee_id">>;
export function listContracts(token: string, employeeId: string) {
  return apiFetch<Contract[]>(`/hr/contracts?employee_id=${encodeURIComponent(employeeId)}`, { token });
}
export function createContract(token: string, input: ContractInput) {
  return apiFetch<Contract>("/hr/contracts", { method: "POST", token, body: input });
}
export function updateContract(token: string, id: string, changes: ContractChanges) {
  return apiFetch<Contract>(`/hr/contracts/${id}`, { method: "PATCH", token, body: changes });
}
export function activateContract(token: string, id: string) {
  return apiFetch<Contract>(`/hr/contracts/${id}/activate`, { method: "POST", token });
}
export function endContract(token: string, id: string, input: { end_date: string; end_reason: EndReason }) {
  return apiFetch<Contract>(`/hr/contracts/${id}/end`, { method: "POST", token, body: input });
}
export function amendContract(token: string, id: string, input: ContractChanges & { effective_date: string }) {
  return apiFetch<Contract>(`/hr/contracts/${id}/amend`, { method: "POST", token, body: input });
}

// ---- documents ----
export interface EmployeeDocument {
  id: string;
  employee_id: string;
  kind: DocumentKind;
  title: string | null;
  file_ref: string | null;
  issued_on: string | null;
  expires_on: string | null;
  state: DocumentState | null;
}
export type DocumentInput = Omit<EmployeeDocument, "id" | "employee_id" | "state">;
export function listDocuments(token: string, employeeId: string) {
  return apiFetch<EmployeeDocument[]>(`/hr/employees/${employeeId}/documents`, { token });
}
export function createDocument(token: string, employeeId: string, input: DocumentInput) {
  return apiFetch<EmployeeDocument>(`/hr/employees/${employeeId}/documents`, { method: "POST", token, body: input });
}
export function updateDocument(token: string, id: string, changes: Partial<DocumentInput>) {
  return apiFetch<EmployeeDocument>(`/hr/documents/${id}`, { method: "PATCH", token, body: changes });
}

// ---- organisation ----
export interface Department {
  id: string;
  code: string;
  name: string;
  manager_employee_id: string | null;
  manager_name: string | null;
  employee_count: number;
}
export type DepartmentInput = { code: string; name: string; manager_employee_id: string | null };
export function listDepartments(token: string) {
  return apiFetch<Department[]>("/hr/departments", { token });
}
export function createDepartment(token: string, input: DepartmentInput) {
  return apiFetch<Department>("/hr/departments", { method: "POST", token, body: input });
}
export function updateDepartment(token: string, id: string, changes: Partial<DepartmentInput>) {
  return apiFetch<Department>(`/hr/departments/${id}`, { method: "PATCH", token, body: changes });
}

export interface Position {
  id: string;
  code: string;
  title: string;
  department_id: string | null;
  department_name: string | null;
  headcount_budget: number | null;
  headcount: number;
}
export type PositionInput = { code: string; title: string; department_id: string | null; headcount_budget: number | null };
export function listPositions(token: string) {
  return apiFetch<Position[]>("/hr/positions", { token });
}
export function createPosition(token: string, input: PositionInput) {
  return apiFetch<Position>("/hr/positions", { method: "POST", token, body: input });
}
export function updatePosition(token: string, id: string, changes: Partial<PositionInput>) {
  return apiFetch<Position>(`/hr/positions/${id}`, { method: "PATCH", token, body: changes });
}

export interface Grade {
  id: string;
  code: string;
  category: string;
  echelon: string;
  base_salary: number;
  valid_from: string;
}
export type GradeInput = Omit<Grade, "id">;
export function listGrades(token: string) {
  return apiFetch<Grade[]>("/hr/grades", { token });
}
export function createGrade(token: string, input: GradeInput) {
  return apiFetch<Grade>("/hr/grades", { method: "POST", token, body: input });
}
export function updateGrade(token: string, id: string, changes: Partial<GradeInput>) {
  return apiFetch<Grade>(`/hr/grades/${id}`, { method: "PATCH", token, body: changes });
}

// ---- settings and alerts ----
export interface HrSettings {
  contract_expiry_horizon_days: number | null;
  trial_end_horizon_days: number | null;
  document_expiry_horizon_days: number | null;
}
export function getHrSettings(token: string) {
  return apiFetch<HrSettings>("/hr/settings", { token });
}
export function saveHrSettings(token: string, input: HrSettings) {
  return apiFetch<HrSettings>("/hr/settings", { method: "PUT", token, body: input });
}

export interface ContractAlert {
  contract_id: string;
  employee_id: string;
  employee_no: string;
  employee_name: string;
  contract_type: ContractType;
  date: string;
}
export interface DocumentAlert {
  document_id: string;
  employee_id: string;
  employee_no: string;
  employee_name: string;
  kind: DocumentKind;
  title: string | null;
  expires_on: string;
  state: DocumentState;
}
export interface ExpiryAlerts extends HrSettings {
  as_of: string;
  contracts_ending: ContractAlert[];
  trials_ending: ContractAlert[];
  documents_expiring: DocumentAlert[];
}
export function getExpiryAlerts(token: string) {
  return apiFetch<ExpiryAlerts>("/hr/alerts/expiries", { token });
}

// ---------------------------------------------------------------------------
// Legacy screens (leave, attendance, payroll) until phases 2 and 3 replace them
// ---------------------------------------------------------------------------
export interface LeaveRequest { id: string; employee_id: string; employee_name: string; leave_type: string; start_date: string; end_date: string; reason: string | null; status: "pending" | "approved" | "rejected" | "cancelled"; reviewed_by: string | null; }
export interface Attendance { id: string; employee_id: string; employee_name: string; attendance_date: string; status: string; hours_worked: number; note: string | null; }
export interface PayrollRun { id: string; period_month: string; status: string; }
export interface Payslip { id: string; payroll_run_id: string; period_month: string; employee_name: string; base_salary: number; bonuses: number; deductions: number; taxes: number; net_salary: number; currency: string; status: string; }
export function listLeaveRequests(token: string) { return apiFetch<LeaveRequest[]>("/hr/leave-requests", { token }); }
export function getHrDashboard(token: string) { return apiFetch<{ employee_count: number; active_employee_count: number; department_count: number; pending_leave_count: number; on_leave_count: number }>("/hr/dashboard", { token }); }
export function createLeaveRequest(token: string, input: { employee_id: string; leave_type: string; start_date: string; end_date: string; reason?: string }) { return apiFetch<LeaveRequest>("/hr/leave-requests", { method: "POST", token, body: input }); }
export function reviewLeaveRequest(token: string, id: string, status: "approved" | "rejected") { return apiFetch<LeaveRequest>(`/hr/leave-requests/${id}/review`, { method: "POST", token, body: { status } }); }
export function listAttendance(token: string) { return apiFetch<Attendance[]>("/hr/attendance", { token }); }
export function listPayrollRuns(token: string) { return apiFetch<PayrollRun[]>("/hr/payroll-runs", { token }); }
export function listPayslips(token: string, runId?: string) { return apiFetch<Payslip[]>(`/hr/payslips${runId ? `?run_id=${runId}` : ""}`, { token }); }
export function createPayrollRun(token: string, input: { period_month: string; bonuses: number; deductions: number; taxes: number }) { return apiFetch<PayrollRun>("/hr/payroll-runs", { method: "POST", token, body: input }); }
export function recordAttendance(token: string, input: { employee_id: string; attendance_date: string; status: string; hours_worked: number; note?: string }) { return apiFetch<Attendance>("/hr/attendance", { method: "POST", token, body: input }); }
export interface UpdatedPayslip { id: string; base_salary: number; bonuses: number; deductions: number; taxes: number; net_salary: number; currency: string; }
export function updatePayslip(token: string, payslipId: string, input: { bonuses?: number; deductions?: number; taxes?: number }) { return apiFetch<UpdatedPayslip>(`/hr/payslips/${payslipId}`, { method: "PATCH", token, body: input }); }
```

- [ ] **Step 2: Add the shared helpers and components**

`frontend/src/features/hr/employeeFormat.ts`:

```ts
import { currentLocale } from "../../lib/i18n";

/** Whole F CFA in the app's language ("150 000 F CFA"); "—" when the value is hidden or absent. */
export function formatXof(amount: number | null | undefined): string {
  if (amount == null) return "—";
  return new Intl.NumberFormat(currentLocale(), { style: "currency", currency: "XOF", maximumFractionDigits: 0 }).format(amount);
}

/** An ISO date (yyyy-mm-dd) in the app's language; "—" when absent. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(`${iso}T00:00:00`).toLocaleDateString(currentLocale());
}

/** Today as yyyy-mm-dd in the browser's time zone (toISOString would give UTC's date). */
export function todayIso(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

/** A form value for the API: trimmed, and blank means "no value". */
export function emptyToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}
```

`frontend/src/features/hr/employeeLabels.ts`:

```ts
import type { BadgeProps } from "../../components/ui/badge";
import type { TranslationKey } from "../../lib/i18n";
import type {
  ContractStatus,
  ContractType,
  DependantKind,
  DocumentKind,
  DocumentState,
  EmployeeStatus,
  EndReason,
  Gender,
  MaritalStatus,
  MobileOperator,
  PayFrequency,
  PaymentMethodKind,
} from "./api";

type Variant = NonNullable<BadgeProps["variant"]>;

export const EMPLOYEE_STATUS_LABEL: Record<EmployeeStatus, TranslationKey> = {
  active: "hr.employeeStatus.active",
  on_leave: "hr.employeeStatus.on_leave",
  inactive: "hr.employeeStatus.inactive",
  terminated: "hr.employeeStatus.terminated",
};
export const EMPLOYEE_STATUS_VARIANT: Record<EmployeeStatus, Variant> = {
  active: "success",
  on_leave: "warning",
  inactive: "default",
  terminated: "destructive",
};
export const GENDER_LABEL: Record<Gender, TranslationKey> = { male: "hr.gender.male", female: "hr.gender.female" };
export const MARITAL_LABEL: Record<MaritalStatus, TranslationKey> = {
  single: "hr.marital.single",
  married: "hr.marital.married",
  divorced: "hr.marital.divorced",
  widowed: "hr.marital.widowed",
};
export const END_REASON_LABEL: Record<EndReason, TranslationKey> = {
  term_reached: "hr.endReason.term_reached",
  resignation: "hr.endReason.resignation",
  dismissal: "hr.endReason.dismissal",
  trial_termination: "hr.endReason.trial_termination",
  mutual_agreement: "hr.endReason.mutual_agreement",
  retirement: "hr.endReason.retirement",
  death: "hr.endReason.death",
  amended: "hr.endReason.amended",
  other: "hr.endReason.other",
};
export const CONTRACT_TYPE_LABEL: Record<ContractType, TranslationKey> = {
  cdi: "hr.contractType.cdi",
  cdd: "hr.contractType.cdd",
  apprentice: "hr.contractType.apprentice",
  daily: "hr.contractType.daily",
  intern: "hr.contractType.intern",
};
export const CONTRACT_STATUS_LABEL: Record<ContractStatus, TranslationKey> = {
  draft: "hr.contractStatus.draft",
  active: "hr.contractStatus.active",
  expired: "hr.contractStatus.expired",
  terminated: "hr.contractStatus.terminated",
};
export const CONTRACT_STATUS_VARIANT: Record<ContractStatus, Variant> = {
  draft: "default",
  active: "success",
  expired: "outline",
  terminated: "destructive",
};
export const PAY_FREQUENCY_LABEL: Record<PayFrequency, TranslationKey> = { monthly: "hr.payFrequency.monthly", daily: "hr.payFrequency.daily" };
export const PAYMENT_METHOD_LABEL: Record<PaymentMethodKind, TranslationKey> = {
  bank: "hr.paymentMethod.bank",
  mobile_money: "hr.paymentMethod.mobile_money",
  cash: "hr.paymentMethod.cash",
};
export const OPERATOR_LABEL: Record<MobileOperator, TranslationKey> = { orange_money: "hr.operator.orange_money", moov_money: "hr.operator.moov_money" };
export const DEPENDANT_KIND_LABEL: Record<DependantKind, TranslationKey> = { spouse: "hr.dependantKind.spouse", child: "hr.dependantKind.child" };
export const DOCUMENT_KIND_LABEL: Record<DocumentKind, TranslationKey> = {
  id_card: "hr.documentKind.id_card",
  passport: "hr.documentKind.passport",
  work_permit: "hr.documentKind.work_permit",
  medical_certificate: "hr.documentKind.medical_certificate",
  driving_licence: "hr.documentKind.driving_licence",
  diploma: "hr.documentKind.diploma",
  criminal_record: "hr.documentKind.criminal_record",
  signed_contract: "hr.documentKind.signed_contract",
  other: "hr.documentKind.other",
};
export const DOCUMENT_STATE_LABEL: Record<DocumentState, TranslationKey> = {
  expired: "hr.documentState.expired",
  expiring: "hr.documentState.expiring",
  valid: "hr.documentState.valid",
};
export const DOCUMENT_STATE_VARIANT: Record<DocumentState, Variant> = { expired: "destructive", expiring: "warning", valid: "success" };
```

`frontend/src/features/hr/FormField.tsx`:

```tsx
import type { ReactNode } from "react";
import { Label } from "../../components/ui/label";

export function FormField({ id, label, hint, error, children }: { id: string; label: string; hint?: string; error?: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
```

`frontend/src/features/hr/HrTable.tsx`:

```tsx
import type { ReactNode } from "react";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { EmptyState } from "../../components/patterns/EmptyState";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import { ResizableTableHead, Table, TableBody, TableCell, TableHeader, TableRow } from "../../components/ui/table";
import { useI18n } from "../../lib/i18n";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { cn } from "../../lib/utils";

interface HrTableProps<Row> {
  tableKey: string;
  columns: ColumnDef<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  isLoading?: boolean;
  /** "loader" only for the one table that is the whole screen; tabs and sub-blocks use skeletons. */
  loadingVariant?: "loader" | "skeleton";
  empty: { icon: ReactNode; title: string; description: string };
  toolbar?: ReactNode;
  filtersActive?: boolean;
  onClearFilters?: () => void;
  onRowClick?: (row: Row) => void;
}

/** An hr list: columns as data (resizable, hideable, saved per user), a filter row, sortable headers. */
export function HrTable<Row>({
  tableKey,
  columns,
  rows,
  rowKey,
  isLoading = false,
  loadingVariant = "skeleton",
  empty,
  toolbar,
  filtersActive = false,
  onClearFilters,
  onRowClick,
}: HrTableProps<Row>) {
  const { t } = useI18n();
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns(tableKey, columns);
  const sorted = sortRows(rows);
  const hasFilterRow = columns.some((column) => column.filterCell);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        {toolbar}
        {filtersActive && onClearFilters && (
          <Button variant="ghost" size="sm" onClick={onClearFilters}>
            {t("common.clearFilters")}
          </Button>
        )}
        <div className="ml-auto">
          <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
        </div>
      </div>
      <Table colWidths={colWidths}>
        <TableHeader>
          <TableRow>
            {visibleColumns.map((column) => (
              <ResizableTableHead
                key={column.key}
                width={getWidth(column.key)}
                onResize={(width) => setWidth(column.key, width)}
                className={column.headerClassName}
                sortDirection={sortDirectionFor(column.key)}
                onSort={column.sortValue ? () => toggleSort(column.key) : undefined}
              >
                {column.header}
              </ResizableTableHead>
            ))}
          </TableRow>
          {hasFilterRow && <ColumnFilterRow cells={visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />}
        </TableHeader>
        <TableBody>
          {isLoading && loadingVariant === "loader" && <TableLoadingRow colSpan={visibleColumns.length} />}
          {isLoading &&
            loadingVariant === "skeleton" &&
            [0, 1, 2].map((index) => (
              <TableRow key={`skeleton-${index}`}>
                <TableCell colSpan={visibleColumns.length}>
                  <Skeleton className="h-6 w-full" />
                </TableCell>
              </TableRow>
            ))}
          {!isLoading && rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={visibleColumns.length} className="p-0">
                <EmptyState icon={empty.icon} title={empty.title} description={empty.description} />
              </TableCell>
            </TableRow>
          )}
          {!isLoading &&
            sorted.map((row) => (
              <TableRow key={rowKey(row)} className={cn(onRowClick && "cursor-pointer")} onClick={onRowClick ? () => onRowClick(row) : undefined}>
                {visibleColumns.map((column) => (
                  <TableCell key={column.key} className={column.cellClassName}>
                    {column.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
        </TableBody>
      </Table>
    </div>
  );
}
```

- [ ] **Step 3: Write the employee form dialog**

`frontend/src/features/hr/EmployeeFormDialog.tsx`. On edit it sends **only the fields the user changed** (React Hook Form `dirtyFields`), so a caller without `hr.view_sensitive` never sends the masked NINA/INPS/AMO back as empty; those inputs are disabled for them. The form resets when the dialog opens or the employee changes (`employee?.id`), never on a background refetch of the same employee (that would wipe what the user is typing):

```tsx
import { useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Lock } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { listUserDirectory, userDisplayName } from "../../lib/usersApi";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import {
  createEmployee,
  GENDERS,
  hrKeys,
  listDepartments,
  listGrades,
  listPositions,
  MARITAL_STATUSES,
  updateEmployee,
  type EmployeeChanges,
  type EmployeeInput,
  type EmployeeRecord,
} from "./api";
import { EMPLOYEE_STATUS_LABEL, GENDER_LABEL, MARITAL_LABEL } from "./employeeLabels";
import { emptyToNull, formatDate, todayIso } from "./employeeFormat";
import { FormField } from "./FormField";

const SENSITIVE_KEYS = ["national_id", "inps_no", "amo_no"] as const;
const EDITABLE_STATUSES = ["active", "on_leave", "inactive"] as const;
const USER_DIRECTORY_QUERY_KEY = ["core", "users", "directory"] as const;

function buildSchema(required: string) {
  return z.object({
    employee_no: z.string().trim().min(1, required),
    first_name: z.string().trim().min(1, required),
    last_name: z.string().trim().min(1, required),
    hire_date: z.string().min(1, required),
    // Optional: the select is disabled for a person who left, and React Hook Form submits a
    // disabled field as undefined. Text inputs that must not be typed in use readOnly instead.
    status: z.enum(["active", "on_leave", "inactive", "terminated"]).optional(),
    gender: z.string(),
    birth_date: z.string(),
    birth_place: z.string(),
    nationality: z.string(),
    marital_status: z.string(),
    national_id: z.string(),
    inps_no: z.string(),
    amo_no: z.string(),
    phone: z.string(),
    email: z.string(),
    address: z.string(),
    emergency_contact: z.string(),
    department_id: z.string(),
    position_id: z.string(),
    grade_id: z.string(),
    job_title: z.string(),
    site: z.string(),
    badge_no: z.string(),
    user_id: z.string(),
  });
}
type EmployeeForm = z.infer<ReturnType<typeof buildSchema>>;
type FormKey = keyof EmployeeForm;

function toForm(employee: EmployeeRecord | null): EmployeeForm {
  const text = (value: string | null | undefined) => value ?? "";
  return {
    employee_no: text(employee?.employee_no),
    first_name: text(employee?.first_name),
    last_name: text(employee?.last_name),
    hire_date: employee?.hire_date ?? todayIso(),
    status: employee?.status ?? "active",
    gender: text(employee?.gender),
    birth_date: text(employee?.birth_date),
    birth_place: text(employee?.birth_place),
    nationality: text(employee?.nationality),
    marital_status: text(employee?.marital_status),
    national_id: text(employee?.national_id),
    inps_no: text(employee?.inps_no),
    amo_no: text(employee?.amo_no),
    phone: text(employee?.phone),
    email: text(employee?.email),
    address: text(employee?.address),
    emergency_contact: text(employee?.emergency_contact),
    department_id: text(employee?.department_id),
    position_id: text(employee?.position_id),
    grade_id: text(employee?.grade_id),
    job_title: text(employee?.job_title),
    site: text(employee?.site),
    badge_no: text(employee?.badge_no),
    user_id: text(employee?.user_id),
  };
}

/** The API body for `keys`: required text trimmed, everything else blank → null. */
function toPayload(values: EmployeeForm, keys: FormKey[]): Record<string, string | null> {
  const payload: Record<string, string | null> = {};
  for (const key of keys) {
    const raw = values[key] ?? "";
    payload[key] = key === "employee_no" || key === "first_name" || key === "last_name" ? raw.trim() : emptyToNull(raw);
  }
  return payload;
}

interface EmployeeFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** null creates a new file. */
  employee: EmployeeRecord | null;
  onSaved?: (record: EmployeeRecord) => void;
}

export function EmployeeFormDialog({ open, onOpenChange, employee, onSaved }: EmployeeFormDialogProps) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canSeeSensitive = hasPermission("hr.view_sensitive");
  const schema = useMemo(() => buildSchema(t("common.required")), [t]);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, dirtyFields },
  } = useForm<EmployeeForm>({ resolver: zodResolver(schema), defaultValues: toForm(null) });

  useEffect(() => {
    if (open) reset(toForm(employee));
    // Reset on open and when another employee is shown, not when the same one is refetched.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, employee?.id]);

  const departments = useQuery({ queryKey: hrKeys.departments, queryFn: () => listDepartments(token), enabled: open && hasPermission("hr.view_departments") });
  const positions = useQuery({ queryKey: hrKeys.positions, queryFn: () => listPositions(token), enabled: open && hasPermission("hr.view_positions") });
  const grades = useQuery({ queryKey: hrKeys.grades, queryFn: () => listGrades(token), enabled: open && hasPermission("hr.view_positions") });
  const users = useQuery({ queryKey: USER_DIRECTORY_QUERY_KEY, queryFn: () => listUserDirectory(token), enabled: open });

  const mutation = useMutation({
    mutationFn: (values: EmployeeForm) => {
      if (!employee) {
        const keys = (Object.keys(values) as FormKey[]).filter(
          (key) => canSeeSensitive || !(SENSITIVE_KEYS as readonly string[]).includes(key),
        );
        return createEmployee(token, toPayload(values, keys) as unknown as EmployeeInput);
      }
      const keys = (Object.keys(dirtyFields) as FormKey[]).filter((key) => key !== "employee_no");
      return updateEmployee(token, employee.id, toPayload(values, keys) as unknown as EmployeeChanges);
    },
    onSuccess: (record) => {
      queryClient.invalidateQueries({ queryKey: hrKeys.employees });
      queryClient.invalidateQueries({ queryKey: hrKeys.alerts });
      toast.success(t(employee ? "hr.form.saved" : "hr.form.created"));
      onOpenChange(false);
      onSaved?.(record);
    },
    onError: (error) => toast.error(t("hr.form.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const terminated = employee?.status === "terminated";
  const sensitivePlaceholder = canSeeSensitive ? undefined : "••••";
  const sensitiveHint = canSeeSensitive ? undefined : t("hr.sensitive.readOnly");
  const sensitiveClass = canSeeSensitive ? undefined : "bg-muted";
  const grid = "grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>{t(employee ? "hr.form.editTitle" : "hr.form.createTitle")}</DialogTitle>
          <DialogDescription>{t(employee ? "hr.form.editDescription" : "hr.form.createDescription")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-5" onSubmit={handleSubmit((values) => mutation.mutate(values))}>
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">{t("hr.form.section.identity")}</h3>
            <div className={grid}>
              <FormField id="employee_no" label={t("hr.field.employeeNo")} error={errors.employee_no?.message}>
                <Input id="employee_no" readOnly={employee !== null} className={employee ? "bg-muted" : undefined} {...register("employee_no")} />
              </FormField>
              <FormField id="last_name" label={t("hr.field.lastName")} error={errors.last_name?.message}>
                <Input id="last_name" {...register("last_name")} />
              </FormField>
              <FormField id="first_name" label={t("hr.field.firstName")} error={errors.first_name?.message}>
                <Input id="first_name" {...register("first_name")} />
              </FormField>
              <FormField id="gender" label={t("hr.field.gender")}>
                <Select id="gender" {...register("gender")}>
                  <option value="">{t("hr.form.noneOption")}</option>
                  {GENDERS.map((value) => (
                    <option key={value} value={value}>
                      {t(GENDER_LABEL[value])}
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField id="birth_date" label={t("hr.field.birthDate")}>
                <Input id="birth_date" type="date" {...register("birth_date")} />
              </FormField>
              <FormField id="birth_place" label={t("hr.field.birthPlace")}>
                <Input id="birth_place" {...register("birth_place")} />
              </FormField>
              <FormField id="nationality" label={t("hr.field.nationality")}>
                <Input id="nationality" {...register("nationality")} />
              </FormField>
              <FormField id="marital_status" label={t("hr.field.maritalStatus")}>
                <Select id="marital_status" {...register("marital_status")}>
                  <option value="">{t("hr.form.noneOption")}</option>
                  {MARITAL_STATUSES.map((value) => (
                    <option key={value} value={value}>
                      {t(MARITAL_LABEL[value])}
                    </option>
                  ))}
                </Select>
              </FormField>
            </div>
          </section>

          <section className="space-y-2">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold">
              {t("hr.form.section.social")}
              {!canSeeSensitive && <Lock className="h-3.5 w-3.5 text-muted-foreground" aria-label={t("hr.sensitive.hidden")} />}
            </h3>
            <div className={grid}>
              <FormField id="national_id" label={t("hr.field.nationalId")} hint={sensitiveHint}>
                <Input id="national_id" readOnly={!canSeeSensitive} className={sensitiveClass} placeholder={sensitivePlaceholder} {...register("national_id")} />
              </FormField>
              <FormField id="inps_no" label={t("hr.field.inpsNo")}>
                <Input id="inps_no" readOnly={!canSeeSensitive} className={sensitiveClass} placeholder={sensitivePlaceholder} {...register("inps_no")} />
              </FormField>
              <FormField id="amo_no" label={t("hr.field.amoNo")}>
                <Input id="amo_no" readOnly={!canSeeSensitive} className={sensitiveClass} placeholder={sensitivePlaceholder} {...register("amo_no")} />
              </FormField>
            </div>
          </section>

          <section className="space-y-2">
            <h3 className="text-sm font-semibold">{t("hr.form.section.contact")}</h3>
            <div className={grid}>
              <FormField id="phone" label={t("hr.field.phone")}>
                <Input id="phone" {...register("phone")} />
              </FormField>
              <FormField id="email" label={t("hr.field.email")}>
                <Input id="email" type="email" {...register("email")} />
              </FormField>
              <FormField id="address" label={t("hr.field.address")}>
                <Input id="address" {...register("address")} />
              </FormField>
              <FormField id="emergency_contact" label={t("hr.field.emergencyContact")}>
                <Input id="emergency_contact" {...register("emergency_contact")} />
              </FormField>
            </div>
          </section>

          <section className="space-y-2">
            <h3 className="text-sm font-semibold">{t("hr.form.section.organisation")}</h3>
            <div className={grid}>
              <FormField id="hire_date" label={t("hr.field.hireDate")} error={errors.hire_date?.message}>
                <Input id="hire_date" type="date" {...register("hire_date")} />
              </FormField>
              <FormField id="status" label={t("hr.field.status")} hint={terminated ? t("hr.form.terminatedStatus") : undefined}>
                <Select id="status" disabled={terminated} {...register("status")}>
                  {(terminated ? (["terminated"] as const) : EDITABLE_STATUSES).map((value) => (
                    <option key={value} value={value}>
                      {t(EMPLOYEE_STATUS_LABEL[value])}
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField id="department_id" label={t("hr.field.department")}>
                <Select id="department_id" {...register("department_id")}>
                  <option value="">{t("hr.form.noneOption")}</option>
                  {(departments.data ?? []).map((department) => (
                    <option key={department.id} value={department.id}>
                      {department.name}
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField id="position_id" label={t("hr.field.position")}>
                <Select id="position_id" {...register("position_id")}>
                  <option value="">{t("hr.form.noneOption")}</option>
                  {(positions.data ?? []).map((position) => (
                    <option key={position.id} value={position.id}>
                      {position.code} — {position.title}
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField id="grade_id" label={t("hr.field.grade")}>
                <Select id="grade_id" {...register("grade_id")}>
                  <option value="">{t("hr.form.noneOption")}</option>
                  {(grades.data ?? []).map((grade) => (
                    <option key={grade.id} value={grade.id}>
                      {grade.code} — {grade.category} {grade.echelon} ({formatDate(grade.valid_from)})
                    </option>
                  ))}
                </Select>
              </FormField>
              <FormField id="job_title" label={t("hr.field.jobTitle")}>
                <Input id="job_title" {...register("job_title")} />
              </FormField>
              <FormField id="site" label={t("hr.field.site")}>
                <Input id="site" {...register("site")} />
              </FormField>
              <FormField id="badge_no" label={t("hr.field.badgeNo")}>
                <Input id="badge_no" {...register("badge_no")} />
              </FormField>
              <FormField id="user_id" label={t("hr.field.user")}>
                <Select id="user_id" {...register("user_id")}>
                  <option value="">{t("hr.form.noUser")}</option>
                  {(users.data ?? []).map((user) => (
                    <option key={user.id} value={user.id}>
                      {userDisplayName(user)}
                    </option>
                  ))}
                </Select>
              </FormField>
            </div>
          </section>

          <Button
            type="submit"
            className="w-full"
            disabled={mutation.isPending || (employee !== null && Object.keys(dirtyFields).length === 0)}
          >
            {mutation.isPending ? t("common.saving") : t(employee ? "hr.form.save" : "hr.form.create")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 4: Write the alerts card and the list page**

`frontend/src/features/hr/ExpiryAlertsCard.tsx`:

```tsx
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CalendarClock } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { Badge } from "../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Skeleton } from "../../components/ui/skeleton";
import { getExpiryAlerts, hrKeys, type ContractAlert, type DocumentAlert } from "./api";
import { CONTRACT_TYPE_LABEL, DOCUMENT_KIND_LABEL, DOCUMENT_STATE_LABEL, DOCUMENT_STATE_VARIANT } from "./employeeLabels";
import { formatDate } from "./employeeFormat";

/** Contracts, trial periods and documents falling due inside the horizons HR set (Organisation › Settings). */
export function ExpiryAlertsCard() {
  const { session } = useAuth();
  const { t } = useI18n();
  const { data, isLoading, isError } = useQuery({ queryKey: hrKeys.alerts, queryFn: () => getExpiryAlerts(session!.token) });

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <CalendarClock className="h-4 w-4 text-primary" />
          {t("hr.alerts.title")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className="grid gap-4 md:grid-cols-3">
            {[0, 1, 2].map((index) => (
              <Skeleton key={index} className="h-24 w-full" />
            ))}
          </div>
        )}
        {isError && <p className="text-sm text-destructive">{t("hr.alerts.error")}</p>}
        {data && (
          <div className="grid gap-4 md:grid-cols-3">
            <AlertColumn title={t("hr.alerts.contracts")} days={data.contract_expiry_horizon_days} empty={data.contracts_ending.length === 0}>
              {data.contracts_ending.map((item) => (
                <ContractLine key={item.contract_id} item={item} />
              ))}
            </AlertColumn>
            <AlertColumn title={t("hr.alerts.trials")} days={data.trial_end_horizon_days} empty={data.trials_ending.length === 0}>
              {data.trials_ending.map((item) => (
                <ContractLine key={item.contract_id} item={item} />
              ))}
            </AlertColumn>
            <AlertColumn title={t("hr.alerts.documents")} days={data.document_expiry_horizon_days} empty={data.documents_expiring.length === 0}>
              {data.documents_expiring.map((item) => (
                <DocumentLine key={item.document_id} item={item} />
              ))}
            </AlertColumn>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function AlertColumn({ title, days, empty, children }: { title: string; days: number | null; empty: boolean; children: ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-sm font-medium">{title}</p>
        {days !== null && (
          <span className="text-xs text-muted-foreground">
            {days} {t("hr.alerts.withinDays")}
          </span>
        )}
      </div>
      {days === null ? (
        <p className="text-xs text-muted-foreground">{t("hr.alerts.notConfigured")}</p>
      ) : empty ? (
        <p className="text-xs text-muted-foreground">{t("hr.alerts.none")}</p>
      ) : (
        <ul className="space-y-1">{children}</ul>
      )}
    </div>
  );
}

function ContractLine({ item }: { item: ContractAlert }) {
  const { t } = useI18n();
  return (
    <li className="flex items-center justify-between gap-2 text-sm">
      <Link to={`/hr/employees/${item.employee_id}?tab=contracts`} className="truncate hover:underline">
        {item.employee_name}
      </Link>
      <span className="shrink-0 text-xs text-muted-foreground">
        {t(CONTRACT_TYPE_LABEL[item.contract_type])} · {formatDate(item.date)}
      </span>
    </li>
  );
}

function DocumentLine({ item }: { item: DocumentAlert }) {
  const { t } = useI18n();
  return (
    <li className="flex items-center justify-between gap-2 text-sm">
      <Link to={`/hr/employees/${item.employee_id}?tab=documents`} className="truncate hover:underline">
        {item.employee_name} · {item.title ?? t(DOCUMENT_KIND_LABEL[item.kind])}
      </Link>
      <Badge variant={DOCUMENT_STATE_VARIANT[item.state]}>
        {t(DOCUMENT_STATE_LABEL[item.state])} · {formatDate(item.expires_on)}
      </Badge>
    </li>
  );
}
```

`frontend/src/features/hr/EmployeesPage.tsx`:

```tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Plus, UserCheck, UserRound, Users } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { useColumnFilters } from "../../lib/useColumnFilters";
import type { ColumnDef } from "../../lib/useTableColumns";
import type { FilterCell } from "../../components/patterns/ColumnFilterRow";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { StatCard } from "../../components/patterns/StatCard";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { EMPLOYEE_STATUSES, hrKeys, listEmployees, type EmployeeListItem, type EmployeeStatus } from "./api";
import { CONTRACT_TYPE_LABEL, EMPLOYEE_STATUS_LABEL, EMPLOYEE_STATUS_VARIANT } from "./employeeLabels";
import { formatDate } from "./employeeFormat";
import { HrTable } from "./HrTable";
import { EmployeeFormDialog } from "./EmployeeFormDialog";
import { ExpiryAlertsCard } from "./ExpiryAlertsCard";

type StatusFilter = "all" | EmployeeStatus;

export function EmployeesPage() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [status, setStatus] = useState<StatusFilter>("active");
  const [dialogOpen, setDialogOpen] = useState(false);
  const { data: employees = [], isLoading } = useQuery({ queryKey: hrKeys.employees, queryFn: () => listEmployees(session!.token) });

  const filters = useColumnFilters<EmployeeListItem>([
    { key: "employee_no", kind: "text", getValue: (row) => row.employee_no },
    { key: "name", kind: "text", getValue: (row) => row.full_name },
    { key: "department", kind: "text", getValue: (row) => row.department_name },
    { key: "position", kind: "text", getValue: (row) => row.position_title ?? row.job_title },
    { key: "grade", kind: "text", getValue: (row) => row.grade_code },
    { key: "site", kind: "text", getValue: (row) => row.site },
    { key: "badge", kind: "text", getValue: (row) => row.badge_no },
    { key: "phone", kind: "text", getValue: (row) => row.phone },
  ]);
  const text = (key: string, placeholder: string): FilterCell => ({
    type: "text",
    value: filters.text[key] ?? "",
    onChange: (value) => filters.setTextValue(key, value),
    placeholder,
  });
  const rows = filters.apply(status === "all" ? employees : employees.filter((row) => row.status === status));
  const count = (value: EmployeeStatus) => (isLoading ? null : employees.filter((row) => row.status === value).length);
  const statusOptions: { value: StatusFilter; label: string }[] = [
    { value: "all", label: t("common.all") },
    ...EMPLOYEE_STATUSES.map((value) => ({ value, label: t(EMPLOYEE_STATUS_LABEL[value]) })),
  ];

  const columns: ColumnDef<EmployeeListItem>[] = [
    { key: "employee_no", header: t("hr.field.employeeNo"), defaultWidth: 120, cell: (row) => <span className="font-medium">{row.employee_no}</span>, filterCell: text("employee_no", t("hr.field.employeeNo")), sortValue: (row) => row.employee_no },
    { key: "name", header: t("hr.field.fullName"), defaultWidth: 200, cell: (row) => row.full_name, filterCell: text("name", t("hr.field.fullName")), sortValue: (row) => `${row.last_name} ${row.first_name}` },
    { key: "department", header: t("hr.field.department"), defaultWidth: 160, cell: (row) => row.department_name ?? "—", filterCell: text("department", t("hr.field.department")), sortValue: (row) => row.department_name },
    { key: "position", header: t("hr.field.position"), defaultWidth: 190, cell: (row) => row.position_title ?? row.job_title ?? "—", filterCell: text("position", t("hr.field.position")), sortValue: (row) => row.position_title },
    { key: "grade", header: t("hr.field.grade"), defaultWidth: 110, cell: (row) => row.grade_code ?? "—", filterCell: text("grade", t("hr.field.grade")), sortValue: (row) => row.grade_code },
    {
      key: "contract",
      header: t("hr.field.contract"),
      defaultWidth: 170,
      cell: (row) =>
        row.contract_type
          ? `${t(CONTRACT_TYPE_LABEL[row.contract_type])}${row.contract_end_date ? ` · ${formatDate(row.contract_end_date)}` : ""}`
          : "—",
      sortValue: (row) => row.contract_type,
    },
    { key: "site", header: t("hr.field.site"), defaultWidth: 120, cell: (row) => row.site ?? "—", filterCell: text("site", t("hr.field.site")), sortValue: (row) => row.site },
    { key: "badge", header: t("hr.field.badgeNo"), defaultWidth: 110, cell: (row) => row.badge_no ?? "—", filterCell: text("badge", t("hr.field.badgeNo")), sortValue: (row) => row.badge_no },
    { key: "phone", header: t("hr.field.phone"), defaultWidth: 130, cell: (row) => row.phone ?? "—", filterCell: text("phone", t("hr.field.phone")) },
    { key: "hire_date", header: t("hr.field.hireDate"), defaultWidth: 120, cell: (row) => formatDate(row.hire_date), sortValue: (row) => row.hire_date },
    {
      key: "status",
      header: t("hr.field.status"),
      defaultWidth: 110,
      cell: (row) => (
        <Badge variant={EMPLOYEE_STATUS_VARIANT[row.status]} dot>
          {t(EMPLOYEE_STATUS_LABEL[row.status])}
        </Badge>
      ),
      sortValue: (row) => row.status,
    },
  ];

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25 }}
        className="flex flex-wrap items-start justify-between gap-3"
      >
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{t("hr.list.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("hr.list.subtitle")}</p>
        </div>
        {hasPermission("hr.manage_employees") && (
          <Button onClick={() => setDialogOpen(true)}>
            <Plus className="h-4 w-4" />
            {t("hr.list.new")}
          </Button>
        )}
      </motion.div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("hr.list.stat.active")} value={count("active")} icon={<UserCheck className="h-5 w-5" />} accent="success" />
        <StatCard label={t("hr.list.stat.onLeave")} value={count("on_leave")} icon={<Users className="h-5 w-5" />} accent="warning" />
        <StatCard label={t("hr.list.stat.left")} value={count("terminated")} icon={<UserRound className="h-5 w-5" />} />
      </div>

      <ExpiryAlertsCard />

      <Card>
        <CardContent className="pt-6">
          <HrTable
            tableKey="hr.employees.list"
            columns={columns}
            rows={rows}
            rowKey={(row) => row.id}
            isLoading={isLoading}
            loadingVariant="loader"
            empty={{ icon: <Users className="h-5 w-5" />, title: t("hr.list.empty.title"), description: t("hr.list.empty.description") }}
            toolbar={<FilterTabs value={status} onChange={setStatus} options={statusOptions} />}
            filtersActive={filters.isActive}
            onClearFilters={filters.reset}
            onRowClick={(row) => navigate(`/hr/employees/${row.id}`)}
          />
        </CardContent>
      </Card>

      <EmployeeFormDialog open={dialogOpen} onOpenChange={setDialogOpen} employee={null} onSaved={(record) => navigate(`/hr/employees/${record.id}`)} />
    </div>
  );
}
```

- [ ] **Step 5: Trim the legacy page, wire the route and the nav**

In `frontend/src/features/hr/HrPage.tsx`, replace everything from the top of the file down to and including the closing `}` of `export function HrPage()` (today lines 1–60) with the block below; leave `function Header` and everything after it unchanged. The employee file, departments and contracts moved to the new screens; the legacy page's contract form would now be refused (its `'permanent'`/USD body):

```tsx
import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, CalendarDays, Users } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { toast } from "sonner";
import { Button } from "../../components/ui/button";
import { Checkbox } from "../../components/ui/checkbox";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHeader, TableRow, ResizableTableHead } from "../../components/ui/table";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "../../components/ui/dialog";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { BulkActionBar } from "../../components/patterns/BulkActionBar";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { useSelection } from "../../lib/useSelection";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { createLeaveRequest, createPayrollRun, getHrDashboard, hrKeys, listAttendance, listEmployees, listLeaveRequests, listPayslips, recordAttendance, reviewLeaveRequest, updatePayslip, type LeaveRequest, type Payslip } from "./api";

// Employees, departments and contracts moved to /hr/employees and /hr/organisation (phase 1);
// leave, attendance and payroll stay here until phases 2 and 3 replace them.
const key = { employees: hrKeys.employees, leave: hrKeys.leave, attendance: ["hr", "attendance"], payslips: ["hr", "payslips"], dashboard: hrKeys.dashboard } as const;
type Tab = "leave" | "attendance" | "payroll";

export function HrPage() {
  const { session } = useAuth(); const { t } = useI18n(); const token = session!.token; const client = useQueryClient();
  const [tab, setTab] = useState<Tab>("leave");
  const [leave, setLeave] = useState({ employee_id: "", leave_type: "annual", start_date: "", end_date: "" });
  const [attendance, setAttendance] = useState({ employee_id: "", attendance_date: new Date().toISOString().slice(0, 10), status: "present", hours_worked: 8 });
  const [payroll, setPayroll] = useState({ period_month: `${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, "0")}-01`, bonuses: 0, deductions: 0, taxes: 0 });
  const dashboard = useQuery({ queryKey: key.dashboard, queryFn: () => getHrDashboard(token) }); const employees = useQuery({ queryKey: key.employees, queryFn: () => listEmployees(token) }); const leaves = useQuery({ queryKey: key.leave, queryFn: () => listLeaveRequests(token) }); const attendanceRows = useQuery({ queryKey: key.attendance, queryFn: () => listAttendance(token), enabled: tab === "attendance" }); const payslips = useQuery({ queryKey: key.payslips, queryFn: () => listPayslips(token), enabled: tab === "payroll" });
  const refresh = (keys: readonly unknown[]) => client.invalidateQueries({ queryKey: keys });
  const leaveMutation = useMutation({ mutationFn: () => createLeaveRequest(token, leave), onSuccess: () => { refresh(key.leave); refresh(key.dashboard); toast.success(t("hr.leave.created")); } });
  const attendanceMutation = useMutation({ mutationFn: () => recordAttendance(token, attendance), onSuccess: () => { refresh(key.attendance); toast.success(t("hr.attendance.created")); } });
  const payrollMutation = useMutation({ mutationFn: () => createPayrollRun(token, payroll), onSuccess: () => { refresh(key.payslips); refresh(key.dashboard); toast.success(t("hr.payroll.created")); } });
  const employeeOptions = <>{(employees.data ?? []).filter((item) => item.status !== "terminated").map((item) => <option key={item.id} value={item.id}>{item.first_name} {item.last_name}</option>)}</>;

  return <div className="space-y-6"><Header t={t} /><Metrics data={dashboard.data} t={t} /><nav className="flex flex-wrap gap-2 border-b pb-2">{(["leave", "attendance", "payroll"] as Tab[]).map((item) => <button key={item} className={`rounded-md px-3 py-2 text-sm ${tab === item ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"}`} onClick={() => setTab(item)}>{t(`hr.tab.${item}` as never)}</button>)}</nav>
    {tab === "leave" && <><InlineForm><Select value={leave.employee_id} onChange={(e) => setLeave({ ...leave, employee_id: e.target.value })}><option value="">{t("hr.employee.name")}</option>{employeeOptions}</Select><Input placeholder={t("hr.leave.type")} value={leave.leave_type} onChange={(e) => setLeave({ ...leave, leave_type: e.target.value })} /><Input type="date" value={leave.start_date} onChange={(e) => setLeave({ ...leave, start_date: e.target.value })} /><Input type="date" value={leave.end_date} onChange={(e) => setLeave({ ...leave, end_date: e.target.value })} /><Button disabled={!leave.employee_id} onClick={() => leaveMutation.mutate()}>{t("hr.leave.new")}</Button></InlineForm><LeaveTable requests={leaves.data ?? []} token={token} onRefresh={() => refresh(key.leave)} /></>}
    {tab === "attendance" && <><InlineForm><Select value={attendance.employee_id} onChange={(e) => setAttendance({ ...attendance, employee_id: e.target.value })}><option value="">{t("hr.employee.name")}</option>{employeeOptions}</Select><Input type="date" value={attendance.attendance_date} onChange={(e) => setAttendance({ ...attendance, attendance_date: e.target.value })} /><Input type="number" min="0" value={attendance.hours_worked} onChange={(e) => setAttendance({ ...attendance, hours_worked: Number(e.target.value) })} /><Button disabled={!attendance.employee_id} onClick={() => attendanceMutation.mutate()}>{t("hr.attendance.record")}</Button></InlineForm><SimpleTable tableKey="hr.attendance" headers={[t("hr.employee.name"), t("hr.attendance.date"), t("hr.attendance.status"), t("hr.attendance.hours")]} rows={(attendanceRows.data ?? []).map((item) => [item.employee_name, item.attendance_date, item.status, String(item.hours_worked)])} /></>}
    {tab === "payroll" && <><p className="flex items-center gap-1 text-xs text-muted-foreground">{t("hr.payroll.help")}<HelpTooltip text={t("hr.payroll.help.detail")} /></p><InlineForm><Input type="date" value={payroll.period_month} onChange={(e) => setPayroll({ ...payroll, period_month: e.target.value })} /><Input type="number" min="0" placeholder={t("hr.payroll.bonuses")} value={payroll.bonuses} onChange={(e) => setPayroll({ ...payroll, bonuses: Number(e.target.value) })} /><Input type="number" min="0" placeholder={t("hr.payroll.deductions")} value={payroll.deductions} onChange={(e) => setPayroll({ ...payroll, deductions: Number(e.target.value) })} /><Input type="number" min="0" placeholder={t("hr.payroll.taxes")} value={payroll.taxes} onChange={(e) => setPayroll({ ...payroll, taxes: Number(e.target.value) })} /><Button onClick={() => payrollMutation.mutate()}>{t("hr.payroll.calculate")}</Button></InlineForm><PayslipsTable payslips={payslips.data ?? []} token={token} onRefresh={() => refresh(key.payslips)} /></>}
  </div>;
}
```

In `frontend/src/routes/router.tsx`, add `import { EmployeesPage } from "../features/hr/EmployeesPage";` next to the `HrPage` import and add `{ path: "/hr/employees", element: <EmployeesPage /> },` right before `{ path: "/hr", element: <HrPage /> },`.

In `frontend/src/routes/Sidebar.tsx`, replace the HR group's items:

```tsx
  {
    labelKey: "nav.hr",
    items: [
      { to: "/hr/employees", labelKey: "nav.hrEmployees", icon: Users, permission: "hr.view_employees" },
      { to: "/hr", labelKey: "nav.hrLegacy", icon: BriefcaseBusiness, exact: true },
    ],
  },
```

(`exact: true` keeps the legacy entry from lighting up on every `/hr/...` page; `Users` and `BriefcaseBusiness` are already imported.)

- [ ] **Step 6: Add the strings**

In `frontend/src/lib/i18n.tsx`, insert into the `en` object, immediately before its closing `} as const;` (the one followed by `export type TranslationKey = keyof typeof en;`):

```ts
  "nav.hrEmployees": "Employees",
  "nav.hrLegacy": "Leave, attendance & payroll",
  "hr.employeeStatus.active": "Active",
  "hr.employeeStatus.on_leave": "On leave",
  "hr.employeeStatus.inactive": "Inactive",
  "hr.employeeStatus.terminated": "Left",
  "hr.gender.male": "Male",
  "hr.gender.female": "Female",
  "hr.marital.single": "Single",
  "hr.marital.married": "Married",
  "hr.marital.divorced": "Divorced",
  "hr.marital.widowed": "Widowed",
  "hr.endReason.term_reached": "Term reached",
  "hr.endReason.resignation": "Resignation",
  "hr.endReason.dismissal": "Dismissal",
  "hr.endReason.trial_termination": "Trial period ended",
  "hr.endReason.mutual_agreement": "Mutual agreement",
  "hr.endReason.retirement": "Retirement",
  "hr.endReason.death": "Death",
  "hr.endReason.amended": "Replaced by an amendment",
  "hr.endReason.other": "Other",
  "hr.contractType.cdi": "Permanent (CDI)",
  "hr.contractType.cdd": "Fixed-term (CDD)",
  "hr.contractType.apprentice": "Apprenticeship",
  "hr.contractType.daily": "Day labourer",
  "hr.contractType.intern": "Internship",
  "hr.contractStatus.draft": "Draft",
  "hr.contractStatus.active": "Active",
  "hr.contractStatus.expired": "Expired",
  "hr.contractStatus.terminated": "Terminated",
  "hr.payFrequency.monthly": "Monthly",
  "hr.payFrequency.daily": "Daily",
  "hr.paymentMethod.bank": "Bank transfer",
  "hr.paymentMethod.mobile_money": "Mobile money",
  "hr.paymentMethod.cash": "Cash",
  "hr.operator.orange_money": "Orange Money",
  "hr.operator.moov_money": "Moov Money",
  "hr.dependantKind.spouse": "Spouse",
  "hr.dependantKind.child": "Child",
  "hr.documentKind.id_card": "ID card (NINA)",
  "hr.documentKind.passport": "Passport",
  "hr.documentKind.work_permit": "Work permit",
  "hr.documentKind.medical_certificate": "Medical certificate",
  "hr.documentKind.driving_licence": "Driving licence",
  "hr.documentKind.diploma": "Diploma",
  "hr.documentKind.criminal_record": "Criminal record extract",
  "hr.documentKind.signed_contract": "Signed contract",
  "hr.documentKind.other": "Other",
  "hr.documentState.expired": "Expired",
  "hr.documentState.expiring": "Expiring soon",
  "hr.documentState.valid": "Valid",
  "hr.field.employeeNo": "Employee no.",
  "hr.field.firstName": "First name",
  "hr.field.lastName": "Last name",
  "hr.field.fullName": "Name",
  "hr.field.gender": "Gender",
  "hr.field.birthDate": "Birth date",
  "hr.field.birthPlace": "Birth place",
  "hr.field.nationality": "Nationality",
  "hr.field.maritalStatus": "Marital status",
  "hr.field.nationalId": "NINA (national id)",
  "hr.field.inpsNo": "INPS number",
  "hr.field.amoNo": "AMO number",
  "hr.field.phone": "Phone",
  "hr.field.email": "Email",
  "hr.field.address": "Address",
  "hr.field.emergencyContact": "Emergency contact",
  "hr.field.department": "Department",
  "hr.field.position": "Position",
  "hr.field.grade": "Grade",
  "hr.field.jobTitle": "Job title",
  "hr.field.site": "Site",
  "hr.field.badgeNo": "Badge no.",
  "hr.field.hireDate": "Hire date",
  "hr.field.status": "Status",
  "hr.field.user": "Sign-in account",
  "hr.field.contract": "Contract",
  "hr.field.terminationDate": "Exit date",
  "hr.field.terminationReason": "Exit reason",
  "hr.sensitive.hidden": "Hidden: needs the right to view sensitive HR data (hr.view_sensitive).",
  "hr.sensitive.readOnly": "You cannot set this without the right to view sensitive HR data.",
  "hr.form.noneOption": "— None —",
  "hr.form.noUser": "No sign-in account",
  "hr.form.createTitle": "New employee file",
  "hr.form.createDescription": "Identity, organisation and contact details. The contract, family and payment come next, in the file.",
  "hr.form.editTitle": "Edit the employee file",
  "hr.form.editDescription": "Only the fields you change are saved.",
  "hr.form.section.identity": "Identity",
  "hr.form.section.social": "Identity and social security numbers",
  "hr.form.section.contact": "Contact",
  "hr.form.section.organisation": "Place in the company",
  "hr.form.create": "Create the file",
  "hr.form.save": "Save changes",
  "hr.form.created": "Employee file created",
  "hr.form.saved": "Employee file saved",
  "hr.form.error": "The employee file could not be saved",
  "hr.form.terminatedStatus": "The status of a person who left changes only through the exit.",
  "hr.list.title": "Employees",
  "hr.list.subtitle": "The employee files: identity, contract, family, payment and documents.",
  "hr.list.new": "New employee",
  "hr.list.stat.active": "Active",
  "hr.list.stat.onLeave": "On leave",
  "hr.list.stat.left": "Left",
  "hr.list.empty.title": "No employee",
  "hr.list.empty.description": "Create an employee file, or change the filters.",
  "hr.alerts.title": "Coming up",
  "hr.alerts.contracts": "Contracts ending",
  "hr.alerts.trials": "Trial periods ending",
  "hr.alerts.documents": "Documents to renew",
  "hr.alerts.withinDays": "days ahead",
  "hr.alerts.notConfigured": "No horizon set. Set it in Organisation › Settings.",
  "hr.alerts.none": "Nothing in this window.",
  "hr.alerts.error": "The alerts could not be loaded.",
```

and into the `fr` object, immediately before its closing `};` (the one followed by `const dictionaries`):

```ts
  "nav.hrEmployees": "Employés",
  "nav.hrLegacy": "Congés, présence et paie",
  "hr.employeeStatus.active": "Actif",
  "hr.employeeStatus.on_leave": "En congé",
  "hr.employeeStatus.inactive": "Inactif",
  "hr.employeeStatus.terminated": "Sorti",
  "hr.gender.male": "Homme",
  "hr.gender.female": "Femme",
  "hr.marital.single": "Célibataire",
  "hr.marital.married": "Marié(e)",
  "hr.marital.divorced": "Divorcé(e)",
  "hr.marital.widowed": "Veuf / veuve",
  "hr.endReason.term_reached": "Arrivée à terme",
  "hr.endReason.resignation": "Démission",
  "hr.endReason.dismissal": "Licenciement",
  "hr.endReason.trial_termination": "Rupture de la période d'essai",
  "hr.endReason.mutual_agreement": "Rupture d'un commun accord",
  "hr.endReason.retirement": "Départ à la retraite",
  "hr.endReason.death": "Décès",
  "hr.endReason.amended": "Remplacé par un avenant",
  "hr.endReason.other": "Autre",
  "hr.contractType.cdi": "CDI",
  "hr.contractType.cdd": "CDD",
  "hr.contractType.apprentice": "Apprentissage",
  "hr.contractType.daily": "Journalier",
  "hr.contractType.intern": "Stage",
  "hr.contractStatus.draft": "Brouillon",
  "hr.contractStatus.active": "Actif",
  "hr.contractStatus.expired": "Échu",
  "hr.contractStatus.terminated": "Rompu",
  "hr.payFrequency.monthly": "Mensuel",
  "hr.payFrequency.daily": "Journalier",
  "hr.paymentMethod.bank": "Virement bancaire",
  "hr.paymentMethod.mobile_money": "Mobile money",
  "hr.paymentMethod.cash": "Espèces",
  "hr.operator.orange_money": "Orange Money",
  "hr.operator.moov_money": "Moov Money",
  "hr.dependantKind.spouse": "Conjoint(e)",
  "hr.dependantKind.child": "Enfant",
  "hr.documentKind.id_card": "Carte d'identité (NINA)",
  "hr.documentKind.passport": "Passeport",
  "hr.documentKind.work_permit": "Permis de travail",
  "hr.documentKind.medical_certificate": "Certificat médical",
  "hr.documentKind.driving_licence": "Permis de conduire",
  "hr.documentKind.diploma": "Diplôme",
  "hr.documentKind.criminal_record": "Extrait de casier judiciaire",
  "hr.documentKind.signed_contract": "Contrat signé",
  "hr.documentKind.other": "Autre",
  "hr.documentState.expired": "Expiré",
  "hr.documentState.expiring": "Expire bientôt",
  "hr.documentState.valid": "Valide",
  "hr.field.employeeNo": "Matricule",
  "hr.field.firstName": "Prénom",
  "hr.field.lastName": "Nom",
  "hr.field.fullName": "Nom",
  "hr.field.gender": "Sexe",
  "hr.field.birthDate": "Date de naissance",
  "hr.field.birthPlace": "Lieu de naissance",
  "hr.field.nationality": "Nationalité",
  "hr.field.maritalStatus": "Situation matrimoniale",
  "hr.field.nationalId": "NINA",
  "hr.field.inpsNo": "N° INPS",
  "hr.field.amoNo": "N° AMO",
  "hr.field.phone": "Téléphone",
  "hr.field.email": "E-mail",
  "hr.field.address": "Adresse",
  "hr.field.emergencyContact": "Personne à prévenir",
  "hr.field.department": "Département",
  "hr.field.position": "Poste",
  "hr.field.grade": "Catégorie",
  "hr.field.jobTitle": "Fonction",
  "hr.field.site": "Site",
  "hr.field.badgeNo": "N° de badge",
  "hr.field.hireDate": "Date d'embauche",
  "hr.field.status": "Statut",
  "hr.field.user": "Compte de connexion",
  "hr.field.contract": "Contrat",
  "hr.field.terminationDate": "Date de sortie",
  "hr.field.terminationReason": "Motif de sortie",
  "hr.sensitive.hidden": "Masqué : nécessite le droit de voir les données RH sensibles (hr.view_sensitive).",
  "hr.sensitive.readOnly": "Vous ne pouvez pas renseigner ce champ sans le droit de voir les données RH sensibles.",
  "hr.form.noneOption": "— Aucun —",
  "hr.form.noUser": "Aucun compte de connexion",
  "hr.form.createTitle": "Nouveau dossier employé",
  "hr.form.createDescription": "Identité, organisation et coordonnées. Le contrat, la famille et le paiement se saisissent ensuite dans le dossier.",
  "hr.form.editTitle": "Modifier le dossier employé",
  "hr.form.editDescription": "Seuls les champs modifiés sont enregistrés.",
  "hr.form.section.identity": "Identité",
  "hr.form.section.social": "Numéros d'identification et de sécurité sociale",
  "hr.form.section.contact": "Coordonnées",
  "hr.form.section.organisation": "Place dans l'entreprise",
  "hr.form.create": "Créer le dossier",
  "hr.form.save": "Enregistrer",
  "hr.form.created": "Dossier employé créé",
  "hr.form.saved": "Dossier employé enregistré",
  "hr.form.error": "Le dossier employé n'a pas pu être enregistré",
  "hr.form.terminatedStatus": "Le statut d'une personne sortie ne change que par la sortie.",
  "hr.list.title": "Employés",
  "hr.list.subtitle": "Les dossiers du personnel : identité, contrat, famille, paiement et documents.",
  "hr.list.new": "Nouvel employé",
  "hr.list.stat.active": "Actifs",
  "hr.list.stat.onLeave": "En congé",
  "hr.list.stat.left": "Sortis",
  "hr.list.empty.title": "Aucun employé",
  "hr.list.empty.description": "Créez un dossier employé ou modifiez les filtres.",
  "hr.alerts.title": "Échéances",
  "hr.alerts.contracts": "Contrats arrivant à terme",
  "hr.alerts.trials": "Fins de période d'essai",
  "hr.alerts.documents": "Documents à renouveler",
  "hr.alerts.withinDays": "jours à l'avance",
  "hr.alerts.notConfigured": "Aucun horizon défini. Réglez-le dans Organisation › Paramètres.",
  "hr.alerts.none": "Rien dans cette période.",
  "hr.alerts.error": "Les alertes n'ont pas pu être chargées.",
```

- [ ] **Step 7: Typecheck and look at it**

Run (from `frontend/`): `npx tsc -b --force`
Expected: exit 0, no errors (a missing `fr` key or an unused import fails here).

Browser check (servers usually running on 8000/5173; demo login `demo@sonalim-erp.local` / `demo1234`; re-run `python -m scripts.seed_dev` or Task 15's seed first so the admin role holds the new hr codes, then log in again): open `/hr/employees` — one branded loader, then the table; status tabs filter; each text filter narrows the rows; hide/resize a column and reload (it persists); "New employee" creates a file and lands on `/hr/employees/<id>` (that page is built in Task 11 — until then the route shows the error boundary). Switch the language: every label changes.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/hr/api.ts frontend/src/features/hr/employeeFormat.ts frontend/src/features/hr/employeeLabels.ts frontend/src/features/hr/HrTable.tsx frontend/src/features/hr/FormField.tsx frontend/src/features/hr/EmployeeFormDialog.tsx frontend/src/features/hr/ExpiryAlertsCard.tsx frontend/src/features/hr/EmployeesPage.tsx frontend/src/features/hr/HrPage.tsx frontend/src/routes/router.tsx frontend/src/routes/Sidebar.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(hr-ui): employees list with expiry alerts and the employee form

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Frontend — the employee file page: identity, family, exit, leave, payslips

**Files:**
- Create: `frontend/src/features/hr/Masked.tsx`
- Create: `frontend/src/features/hr/employee/EmployeeFilePage.tsx`, `IdentityTab.tsx`, `TerminateDialog.tsx`, `FamilyTab.tsx`, `LeaveTab.tsx`, `PayslipsTab.tsx`
- Modify: `frontend/src/routes/router.tsx`, `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: Task 10's `api.ts`, `employeeLabels.ts`, `employeeFormat.ts`, `HrTable`, `FormField`, `EmployeeFormDialog`.
- Produces: route `/hr/employees/:employeeId` with `?tab=` in `identity | family | contracts | payment | documents | leave | payslips`; `TABS` array and `TabBody` switch in `EmployeeFilePage.tsx` that Tasks 12–13 extend; `Masked` (lock + "••••").

- [ ] **Step 1: Write the page and its tabs**

`frontend/src/features/hr/Masked.tsx`:

```tsx
import { Lock } from "lucide-react";
import { useI18n } from "../../lib/i18n";

/** What a caller without hr.view_sensitive sees in place of a hidden value. */
export function Masked() {
  const { t } = useI18n();
  return (
    <span className="inline-flex items-center gap-1 text-muted-foreground" title={t("hr.sensitive.hidden")}>
      <Lock className="h-3.5 w-3.5" />
      ••••
    </span>
  );
}
```

`frontend/src/features/hr/employee/EmployeeFilePage.tsx`:

```tsx
import { useState, type ComponentType } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, Ban, CalendarDays, Pencil, Receipt, UserRound, Users } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { StickyTabBar } from "../../../components/patterns/StickyTabBar";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "../../../components/ui/tabs";
import { getEmployee, hrKeys, type EmployeeRecord } from "../api";
import { EMPLOYEE_STATUS_LABEL, EMPLOYEE_STATUS_VARIANT } from "../employeeLabels";
import { EmployeeFormDialog } from "../EmployeeFormDialog";
import { FamilyTab } from "./FamilyTab";
import { IdentityTab } from "./IdentityTab";
import { LeaveTab } from "./LeaveTab";
import { PayslipsTab } from "./PayslipsTab";
import { TerminateDialog } from "./TerminateDialog";

type TabValue = "identity" | "family" | "contracts" | "payment" | "documents" | "leave" | "payslips";

interface TabDef {
  value: TabValue;
  labelKey: TranslationKey;
  icon: ComponentType<{ className?: string }>;
  permission: string;
}

// In display order. Tasks 12 and 13 insert contracts, payment and documents after family.
const TABS: TabDef[] = [
  { value: "identity", labelKey: "hr.file.tab.identity", icon: UserRound, permission: "hr.view_employees" },
  { value: "family", labelKey: "hr.file.tab.family", icon: Users, permission: "hr.view_employees" },
  { value: "leave", labelKey: "hr.file.tab.leave", icon: CalendarDays, permission: "hr.view_leave" },
  { value: "payslips", labelKey: "hr.file.tab.payslips", icon: Receipt, permission: "hr.view_employees" },
];

function TabBody({ tab, employee }: { tab: TabValue; employee: EmployeeRecord }) {
  switch (tab) {
    case "identity":
      return <IdentityTab employee={employee} />;
    case "family":
      return <FamilyTab employee={employee} />;
    case "leave":
      return <LeaveTab employee={employee} />;
    case "payslips":
      return <PayslipsTab />;
    default:
      return null;
  }
}

export function EmployeeFilePage() {
  const { employeeId } = useParams();
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const [editOpen, setEditOpen] = useState(false);
  const [terminateOpen, setTerminateOpen] = useState(false);
  const { data: employee, isLoading, isError } = useQuery({
    queryKey: hrKeys.employee(employeeId!),
    queryFn: () => getEmployee(session!.token, employeeId!),
  });

  // The tab lives in the URL so an alert link can land straight on it.
  const tabs = TABS.filter((entry) => hasPermission(entry.permission));
  const requested = searchParams.get("tab");
  const tab: TabValue = tabs.find((entry) => entry.value === requested)?.value ?? "identity";
  const setTab = (value: TabValue) => setSearchParams({ tab: value }, { replace: true });

  if (isLoading) return <AppLoader label={t("hr.file.loading")} className="min-h-[220px]" />;
  if (isError || !employee) {
    return (
      <EmptyState
        icon={<UserRound className="h-5 w-5" />}
        title={t("hr.file.notFound.title")}
        description={t("hr.file.notFound.description")}
        action={
          <Button variant="outline" asChild>
            <Link to="/hr/employees">{t("hr.file.back")}</Link>
          </Button>
        }
      />
    );
  }

  return (
    <div className="space-y-6">
      <motion.div
        initial={{ opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25 }}
        className="flex flex-wrap items-start justify-between gap-3"
      >
        <div className="flex items-start gap-3">
          <Button variant="ghost" size="sm" asChild>
            <Link to="/hr/employees">
              <ArrowLeft className="h-4 w-4" />
              {t("hr.file.back")}
            </Link>
          </Button>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight">{employee.full_name}</h1>
              <Badge variant={EMPLOYEE_STATUS_VARIANT[employee.status]} dot>
                {t(EMPLOYEE_STATUS_LABEL[employee.status])}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              {[employee.employee_no, employee.position_title ?? employee.job_title, employee.department_name].filter(Boolean).join(" · ")}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          {hasPermission("hr.admin_employees") && (
            <Button variant="outline" onClick={() => setEditOpen(true)}>
              <Pencil className="h-4 w-4" />
              {t("hr.file.edit")}
            </Button>
          )}
          {hasPermission("hr.manage_employees") && employee.status !== "terminated" && (
            <Button variant="outline" onClick={() => setTerminateOpen(true)}>
              <Ban className="h-4 w-4" />
              {t("hr.terminate.action")}
            </Button>
          )}
        </div>
      </motion.div>

      <StickyTabBar>
        <Tabs value={tab} onValueChange={(value) => setTab(value as TabValue)}>
          <TabsList>
            {tabs.map((entry) => (
              <TabsTrigger key={entry.value} value={entry.value} active={tab === entry.value} layoutId="hr-employee-file-tab">
                <span className="flex items-center gap-1.5">
                  <entry.icon className="h-4 w-4" />
                  {t(entry.labelKey)}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </StickyTabBar>

      <AnimatePresence mode="wait">
        <motion.div key={tab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.2 }}>
          <TabBody tab={tab} employee={employee} />
        </motion.div>
      </AnimatePresence>

      <EmployeeFormDialog open={editOpen} onOpenChange={setEditOpen} employee={employee} />
      <TerminateDialog open={terminateOpen} onOpenChange={setTerminateOpen} employee={employee} />
    </div>
  );
}
```

`frontend/src/features/hr/employee/IdentityTab.tsx`:

```tsx
import type { ReactNode } from "react";
import { useI18n } from "../../../lib/i18n";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import type { EmployeeRecord } from "../api";
import { END_REASON_LABEL, GENDER_LABEL, MARITAL_LABEL } from "../employeeLabels";
import { formatDate } from "../employeeFormat";
import { Masked } from "../Masked";

export function IdentityTab({ employee }: { employee: EmployeeRecord }) {
  const { t } = useI18n();
  const hidden = (value: string | null): ReactNode => (employee.sensitive_hidden ? <Masked /> : value);
  const sections: { title: string; rows: [string, ReactNode][] }[] = [
    {
      title: t("hr.form.section.identity"),
      rows: [
        [t("hr.field.employeeNo"), employee.employee_no],
        [t("hr.field.lastName"), employee.last_name],
        [t("hr.field.firstName"), employee.first_name],
        [t("hr.field.gender"), employee.gender ? t(GENDER_LABEL[employee.gender]) : null],
        [t("hr.field.birthDate"), employee.birth_date ? formatDate(employee.birth_date) : null],
        [t("hr.field.birthPlace"), employee.birth_place],
        [t("hr.field.nationality"), employee.nationality],
        [t("hr.field.maritalStatus"), employee.marital_status ? t(MARITAL_LABEL[employee.marital_status]) : null],
      ],
    },
    {
      title: t("hr.form.section.social"),
      rows: [
        [t("hr.field.nationalId"), hidden(employee.national_id)],
        [t("hr.field.inpsNo"), hidden(employee.inps_no)],
        [t("hr.field.amoNo"), hidden(employee.amo_no)],
      ],
    },
    {
      title: t("hr.form.section.contact"),
      rows: [
        [t("hr.field.phone"), employee.phone],
        [t("hr.field.email"), employee.email],
        [t("hr.field.address"), employee.address],
        [t("hr.field.emergencyContact"), employee.emergency_contact],
      ],
    },
    {
      title: t("hr.form.section.organisation"),
      rows: [
        [t("hr.field.department"), employee.department_name],
        [t("hr.field.position"), employee.position_title],
        [t("hr.field.grade"), employee.grade_code],
        [t("hr.field.jobTitle"), employee.job_title],
        [t("hr.field.site"), employee.site],
        [t("hr.field.badgeNo"), employee.badge_no],
        [t("hr.field.hireDate"), formatDate(employee.hire_date)],
        [t("hr.field.user"), employee.user_email],
      ],
    },
  ];
  if (employee.status === "terminated") {
    sections.push({
      title: t("hr.file.exit"),
      rows: [
        [t("hr.field.terminationDate"), formatDate(employee.termination_date)],
        [t("hr.field.terminationReason"), employee.termination_reason ? t(END_REASON_LABEL[employee.termination_reason]) : null],
      ],
    });
  }

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {sections.map((section) => (
        <Card key={section.title}>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{section.title}</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-x-4 gap-y-2 text-sm">
              {section.rows.map(([label, value]) => (
                <div key={label} className="contents">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className="font-medium">{value ?? "—"}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
```

`frontend/src/features/hr/employee/TerminateDialog.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { hrKeys, terminateEmployee, TERMINATION_REASONS, type EmployeeRecord, type TerminationReason } from "../api";
import { END_REASON_LABEL } from "../employeeLabels";
import { todayIso } from "../employeeFormat";
import { FormField } from "../FormField";

export function TerminateDialog({ open, onOpenChange, employee }: { open: boolean; onOpenChange: (open: boolean) => void; employee: EmployeeRecord }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [day, setDay] = useState(todayIso());
  const [reason, setReason] = useState<TerminationReason>("resignation");
  const mutation = useMutation({
    mutationFn: () => terminateEmployee(session!.token, employee.id, { termination_date: day, termination_reason: reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.employees });
      queryClient.invalidateQueries({ queryKey: hrKeys.contracts });
      queryClient.invalidateQueries({ queryKey: hrKeys.alerts });
      toast.success(t("hr.terminate.done"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(t("hr.terminate.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("hr.terminate.title")}</DialogTitle>
          <DialogDescription>{t("hr.terminate.description")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <FormField id="termination-date" label={t("hr.field.terminationDate")}>
            <Input id="termination-date" type="date" required value={day} onChange={(event) => setDay(event.target.value)} />
          </FormField>
          <FormField id="termination-reason" label={t("hr.field.terminationReason")}>
            <Select id="termination-reason" value={reason} onChange={(event) => setReason(event.target.value as TerminationReason)}>
              {TERMINATION_REASONS.map((value) => (
                <option key={value} value={value}>
                  {t(END_REASON_LABEL[value])}
                </option>
              ))}
            </Select>
          </FormField>
          <Button type="submit" variant="destructive" className="w-full" disabled={mutation.isPending || !day}>
            {mutation.isPending ? t("common.saving") : t("hr.terminate.confirm")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

`frontend/src/features/hr/employee/FamilyTab.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Users } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Checkbox } from "../../../components/ui/checkbox";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import {
  createDependant,
  DEPENDANT_KINDS,
  hrKeys,
  listDependants,
  updateDependant,
  type Dependant,
  type DependantInput,
  type DependantKind,
  type EmployeeRecord,
} from "../api";
import { DEPENDANT_KIND_LABEL } from "../employeeLabels";
import { emptyToNull, formatDate, todayIso } from "../employeeFormat";
import { FormField } from "../FormField";
import { HrTable } from "../HrTable";

type KindFilter = "all" | DependantKind;

export function FamilyTab({ employee }: { employee: EmployeeRecord }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const [kind, setKind] = useState<KindFilter>("all");
  const [dialog, setDialog] = useState<{ open: boolean; dependant: Dependant | null }>({ open: false, dependant: null });
  const { data: dependants = [], isLoading } = useQuery({
    queryKey: hrKeys.dependants(employee.id),
    queryFn: () => listDependants(session!.token, employee.id),
  });
  const filters = useColumnFilters<Dependant>([{ key: "name", kind: "text", getValue: (row) => row.name }]);
  const rows = filters.apply(kind === "all" ? dependants : dependants.filter((row) => row.kind === kind));
  const kindOptions: { value: KindFilter; label: string }[] = [
    { value: "all", label: t("common.all") },
    ...DEPENDANT_KINDS.map((value) => ({ value, label: t(DEPENDANT_KIND_LABEL[value]) })),
  ];
  const canEdit = hasPermission("hr.admin_employees");

  const columns: ColumnDef<Dependant>[] = [
    {
      key: "name",
      header: t("hr.family.name"),
      defaultWidth: 200,
      cell: (row) => <span className="font-medium">{row.name}</span>,
      filterCell: { type: "text", value: filters.text.name ?? "", onChange: (value) => filters.setTextValue("name", value), placeholder: t("hr.family.name") },
      sortValue: (row) => row.name,
    },
    { key: "kind", header: t("hr.family.kind"), defaultWidth: 120, cell: (row) => t(DEPENDANT_KIND_LABEL[row.kind]), sortValue: (row) => row.kind },
    { key: "birth_date", header: t("hr.field.birthDate"), defaultWidth: 130, cell: (row) => formatDate(row.birth_date), sortValue: (row) => row.birth_date },
    { key: "tax", header: t("hr.family.forTax"), defaultWidth: 130, cell: (row) => t(row.dependent_for_tax ? "common.yes" : "common.no") },
    { key: "valid_from", header: t("hr.family.validFrom"), defaultWidth: 120, cell: (row) => formatDate(row.valid_from), sortValue: (row) => row.valid_from },
    { key: "valid_to", header: t("hr.family.validTo"), defaultWidth: 120, cell: (row) => formatDate(row.valid_to), sortValue: (row) => row.valid_to },
    {
      key: "today",
      header: t("hr.family.countsToday"),
      defaultWidth: 140,
      cell: (row) => <Badge variant={row.counts_for_tax_today ? "success" : "default"}>{t(row.counts_for_tax_today ? "common.yes" : "common.no")}</Badge>,
    },
    {
      key: "actions",
      header: "",
      defaultWidth: 100,
      alwaysVisible: true,
      cellClassName: "text-right",
      cell: (row) =>
        canEdit ? (
          <Button size="sm" variant="ghost" onClick={() => setDialog({ open: true, dependant: row })}>
            <Pencil className="h-3.5 w-3.5" />
            {t("common.edit")}
          </Button>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
        <div>
          <CardTitle className="text-base">{t("hr.family.title")}</CardTitle>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {t("hr.family.taxCount")}: {dependants.filter((row) => row.counts_for_tax_today).length} · {t("hr.family.forTaxHint")}
          </p>
        </div>
        {hasPermission("hr.manage_employees") && (
          <Button onClick={() => setDialog({ open: true, dependant: null })}>
            <Plus className="h-4 w-4" />
            {t("hr.family.add")}
          </Button>
        )}
      </CardHeader>
      <CardContent>
        <HrTable
          tableKey="hr.employee.dependants"
          columns={columns}
          rows={rows}
          rowKey={(row) => row.id}
          isLoading={isLoading}
          empty={{ icon: <Users className="h-5 w-5" />, title: t("hr.family.empty.title"), description: t("hr.family.empty.description") }}
          toolbar={<FilterTabs value={kind} onChange={setKind} options={kindOptions} />}
          filtersActive={filters.isActive}
          onClearFilters={filters.reset}
        />
      </CardContent>
      <DependantDialog
        employeeId={employee.id}
        open={dialog.open}
        dependant={dialog.dependant}
        onOpenChange={(open) => setDialog((current) => ({ ...current, open }))}
      />
    </Card>
  );
}

interface DependantForm {
  kind: DependantKind;
  name: string;
  birth_date: string;
  dependent_for_tax: boolean;
  valid_from: string;
  valid_to: string;
}

function toForm(dependant: Dependant | null): DependantForm {
  return {
    kind: dependant?.kind ?? "child",
    name: dependant?.name ?? "",
    birth_date: dependant?.birth_date ?? "",
    dependent_for_tax: dependant?.dependent_for_tax ?? false,
    valid_from: dependant?.valid_from ?? todayIso(),
    valid_to: dependant?.valid_to ?? "",
  };
}

function DependantDialog({
  employeeId,
  open,
  dependant,
  onOpenChange,
}: {
  employeeId: string;
  open: boolean;
  dependant: Dependant | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<DependantForm>(toForm(null));

  useEffect(() => {
    if (open) setForm(toForm(dependant));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, dependant?.id]);

  const mutation = useMutation({
    mutationFn: () => {
      const input: DependantInput = {
        kind: form.kind,
        name: form.name.trim(),
        birth_date: emptyToNull(form.birth_date),
        dependent_for_tax: form.dependent_for_tax,
        valid_from: form.valid_from,
        valid_to: emptyToNull(form.valid_to),
      };
      return dependant ? updateDependant(session!.token, dependant.id, input) : createDependant(session!.token, employeeId, input);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.dependants(employeeId) });
      toast.success(t("hr.family.saved"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(t("hr.family.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(dependant ? "hr.family.dialog.editTitle" : "hr.family.dialog.createTitle")}</DialogTitle>
          <DialogDescription>{t("hr.family.dialog.description")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <div className="grid grid-cols-2 gap-3">
            <FormField id="dependant-kind" label={t("hr.family.kind")}>
              <Select id="dependant-kind" value={form.kind} onChange={(event) => setForm({ ...form, kind: event.target.value as DependantKind })}>
                {DEPENDANT_KINDS.map((value) => (
                  <option key={value} value={value}>
                    {t(DEPENDANT_KIND_LABEL[value])}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField id="dependant-name" label={t("hr.family.name")}>
              <Input id="dependant-name" required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
            </FormField>
            <FormField id="dependant-birth" label={t("hr.field.birthDate")}>
              <Input id="dependant-birth" type="date" value={form.birth_date} onChange={(event) => setForm({ ...form, birth_date: event.target.value })} />
            </FormField>
            <FormField id="dependant-from" label={t("hr.family.validFrom")}>
              <Input id="dependant-from" type="date" required value={form.valid_from} onChange={(event) => setForm({ ...form, valid_from: event.target.value })} />
            </FormField>
            <FormField id="dependant-to" label={t("hr.family.validTo")}>
              <Input id="dependant-to" type="date" value={form.valid_to} onChange={(event) => setForm({ ...form, valid_to: event.target.value })} />
            </FormField>
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              id="dependant-tax"
              checked={form.dependent_for_tax}
              onCheckedChange={(checked) => setForm({ ...form, dependent_for_tax: checked === true })}
            />
            <Label htmlFor="dependant-tax">{t("hr.family.forTax")}</Label>
          </div>
          <p className="text-xs text-muted-foreground">{t("hr.family.forTaxHint")}</p>
          <Button type="submit" className="w-full" disabled={mutation.isPending || !form.name.trim() || !form.valid_from}>
            {mutation.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

`frontend/src/features/hr/employee/LeaveTab.tsx` (reads the current leave requests of this person; phase 2 replaces the leave screen and can repoint this tab):

```tsx
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent } from "../../../components/ui/card";
import { hrKeys, listLeaveRequests, type EmployeeRecord, type LeaveRequest } from "../api";
import { formatDate } from "../employeeFormat";
import { HrTable } from "../HrTable";

type LeaveStatus = LeaveRequest["status"];
const LEAVE_STATUSES: LeaveStatus[] = ["pending", "approved", "rejected", "cancelled"];
const LEAVE_STATUS_LABEL: Record<LeaveStatus, TranslationKey> = {
  pending: "hr.file.leave.status.pending",
  approved: "hr.file.leave.status.approved",
  rejected: "hr.file.leave.status.rejected",
  cancelled: "hr.file.leave.status.cancelled",
};

export function LeaveTab({ employee }: { employee: EmployeeRecord }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const [status, setStatus] = useState<"all" | LeaveStatus>("all");
  const { data = [], isLoading } = useQuery({ queryKey: hrKeys.leave, queryFn: () => listLeaveRequests(session!.token) });
  const mine = data.filter((row) => row.employee_id === employee.id);
  const filters = useColumnFilters<LeaveRequest>([
    { key: "type", kind: "text", getValue: (row) => row.leave_type },
    { key: "reason", kind: "text", getValue: (row) => row.reason },
  ]);
  const rows = filters.apply(status === "all" ? mine : mine.filter((row) => row.status === status));
  const statusOptions: { value: "all" | LeaveStatus; label: string }[] = [
    { value: "all", label: t("common.all") },
    ...LEAVE_STATUSES.map((value) => ({ value, label: t(LEAVE_STATUS_LABEL[value]) })),
  ];
  const columns: ColumnDef<LeaveRequest>[] = [
    {
      key: "type",
      header: t("hr.file.leave.type"),
      defaultWidth: 150,
      cell: (row) => row.leave_type,
      filterCell: { type: "text", value: filters.text.type ?? "", onChange: (value) => filters.setTextValue("type", value), placeholder: t("hr.file.leave.type") },
      sortValue: (row) => row.leave_type,
    },
    { key: "start", header: t("hr.file.leave.start"), defaultWidth: 120, cell: (row) => formatDate(row.start_date), sortValue: (row) => row.start_date },
    { key: "end", header: t("hr.file.leave.end"), defaultWidth: 120, cell: (row) => formatDate(row.end_date), sortValue: (row) => row.end_date },
    {
      key: "reason",
      header: t("hr.file.leave.reason"),
      defaultWidth: 240,
      cell: (row) => row.reason ?? "—",
      filterCell: { type: "text", value: filters.text.reason ?? "", onChange: (value) => filters.setTextValue("reason", value), placeholder: t("hr.file.leave.reason") },
    },
    { key: "status", header: t("hr.field.status"), defaultWidth: 120, cell: (row) => <Badge>{t(LEAVE_STATUS_LABEL[row.status])}</Badge>, sortValue: (row) => row.status },
  ];

  return (
    <Card>
      <CardContent className="space-y-3 pt-6">
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
          <span>{t("hr.file.leave.hint")}</span>
          <Button size="sm" variant="outline" asChild>
            <Link to="/hr">{t("hr.file.leave.open")}</Link>
          </Button>
        </div>
        <HrTable
          tableKey="hr.employee.leave"
          columns={columns}
          rows={rows}
          rowKey={(row) => row.id}
          isLoading={isLoading}
          empty={{ icon: <CalendarDays className="h-5 w-5" />, title: t("hr.file.leave.empty.title"), description: t("hr.file.leave.empty.description") }}
          toolbar={<FilterTabs value={status} onChange={setStatus} options={statusOptions} />}
          filtersActive={filters.isActive}
          onClearFilters={filters.reset}
        />
      </CardContent>
    </Card>
  );
}
```

`frontend/src/features/hr/employee/PayslipsTab.tsx` (payslips are produced by phase 3, which fills this tab):

```tsx
import { Receipt } from "lucide-react";
import { useI18n } from "../../../lib/i18n";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { Card, CardContent } from "../../../components/ui/card";

export function PayslipsTab() {
  const { t } = useI18n();
  return (
    <Card>
      <CardContent className="p-0">
        <EmptyState icon={<Receipt className="h-5 w-5" />} title={t("hr.file.payslips.title")} description={t("hr.file.payslips.description")} />
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Route and strings**

In `frontend/src/routes/router.tsx`, add `import { EmployeeFilePage } from "../features/hr/employee/EmployeeFilePage";` and `{ path: "/hr/employees/:employeeId", element: <EmployeeFilePage /> },` right after the `/hr/employees` route.

Add to `en` (before `} as const;`):

```ts
  "hr.file.loading": "Loading the employee file…",
  "hr.file.notFound.title": "Employee not found",
  "hr.file.notFound.description": "This file does not exist or you cannot see it.",
  "hr.file.back": "Employees",
  "hr.file.edit": "Edit the file",
  "hr.file.exit": "Exit",
  "hr.file.tab.identity": "Identity",
  "hr.file.tab.family": "Family",
  "hr.file.tab.contracts": "Contracts",
  "hr.file.tab.payment": "Payment",
  "hr.file.tab.documents": "Documents",
  "hr.file.tab.leave": "Leave",
  "hr.file.tab.payslips": "Payslips",
  "hr.terminate.action": "Record the exit",
  "hr.terminate.title": "Record the employee's exit",
  "hr.terminate.description": "The contract in force on that day ends on it, and the next payroll computes the final settlement. This cannot be undone from this screen.",
  "hr.terminate.confirm": "Record the exit",
  "hr.terminate.done": "Exit recorded",
  "hr.terminate.error": "The exit could not be recorded",
  "hr.family.title": "Dependants",
  "hr.family.taxCount": "Tax dependants today",
  "hr.family.add": "Add a dependant",
  "hr.family.name": "Name",
  "hr.family.kind": "Relationship",
  "hr.family.forTax": "Counts for tax",
  "hr.family.validFrom": "From",
  "hr.family.validTo": "Until",
  "hr.family.countsToday": "Counts today",
  "hr.family.forTaxHint": "Ticked dependants reduce the income tax (ITS) through family relief while they are valid.",
  "hr.family.empty.title": "No dependant",
  "hr.family.empty.description": "Add the spouse and children the employee supports.",
  "hr.family.dialog.createTitle": "Add a dependant",
  "hr.family.dialog.editTitle": "Edit the dependant",
  "hr.family.dialog.description": "The validity dates decide on which pay dates the person counts.",
  "hr.family.saved": "Dependant saved",
  "hr.family.error": "The dependant could not be saved",
  "hr.file.leave.hint": "Leave is requested and approved on the leave screen.",
  "hr.file.leave.open": "Open leave",
  "hr.file.leave.type": "Type",
  "hr.file.leave.start": "Start",
  "hr.file.leave.end": "End",
  "hr.file.leave.reason": "Reason",
  "hr.file.leave.status.pending": "Pending",
  "hr.file.leave.status.approved": "Approved",
  "hr.file.leave.status.rejected": "Rejected",
  "hr.file.leave.status.cancelled": "Cancelled",
  "hr.file.leave.empty.title": "No leave request",
  "hr.file.leave.empty.description": "This employee has not requested any leave.",
  "hr.file.payslips.title": "No payslip yet",
  "hr.file.payslips.description": "Payslips are produced by the payroll module and will be listed here.",
```

Add to `fr` (before its closing `};`):

```ts
  "hr.file.loading": "Chargement du dossier…",
  "hr.file.notFound.title": "Employé introuvable",
  "hr.file.notFound.description": "Ce dossier n'existe pas ou vous n'y avez pas accès.",
  "hr.file.back": "Employés",
  "hr.file.edit": "Modifier le dossier",
  "hr.file.exit": "Sortie",
  "hr.file.tab.identity": "Identité",
  "hr.file.tab.family": "Famille",
  "hr.file.tab.contracts": "Contrats",
  "hr.file.tab.payment": "Paiement",
  "hr.file.tab.documents": "Documents",
  "hr.file.tab.leave": "Congés",
  "hr.file.tab.payslips": "Bulletins",
  "hr.terminate.action": "Enregistrer la sortie",
  "hr.terminate.title": "Enregistrer la sortie de l'employé",
  "hr.terminate.description": "Le contrat en vigueur ce jour-là prend fin à cette date et la prochaine paie calcule le solde de tout compte. Cette action ne peut pas être annulée depuis cet écran.",
  "hr.terminate.confirm": "Enregistrer la sortie",
  "hr.terminate.done": "Sortie enregistrée",
  "hr.terminate.error": "La sortie n'a pas pu être enregistrée",
  "hr.family.title": "Personnes à charge",
  "hr.family.taxCount": "Personnes à charge fiscales aujourd'hui",
  "hr.family.add": "Ajouter une personne à charge",
  "hr.family.name": "Nom",
  "hr.family.kind": "Lien",
  "hr.family.forTax": "À charge fiscale",
  "hr.family.validFrom": "Du",
  "hr.family.validTo": "Au",
  "hr.family.countsToday": "Compte aujourd'hui",
  "hr.family.forTaxHint": "Les personnes cochées réduisent l'ITS (charges de famille) tant qu'elles sont valides.",
  "hr.family.empty.title": "Aucune personne à charge",
  "hr.family.empty.description": "Ajoutez le conjoint et les enfants à la charge de l'employé.",
  "hr.family.dialog.createTitle": "Ajouter une personne à charge",
  "hr.family.dialog.editTitle": "Modifier la personne à charge",
  "hr.family.dialog.description": "Les dates de validité déterminent à quelles paies la personne est comptée.",
  "hr.family.saved": "Personne à charge enregistrée",
  "hr.family.error": "La personne à charge n'a pas pu être enregistrée",
  "hr.file.leave.hint": "Les congés se demandent et s'approuvent dans l'écran des congés.",
  "hr.file.leave.open": "Ouvrir les congés",
  "hr.file.leave.type": "Type",
  "hr.file.leave.start": "Début",
  "hr.file.leave.end": "Fin",
  "hr.file.leave.reason": "Motif",
  "hr.file.leave.status.pending": "En attente",
  "hr.file.leave.status.approved": "Approuvé",
  "hr.file.leave.status.rejected": "Refusé",
  "hr.file.leave.status.cancelled": "Annulé",
  "hr.file.leave.empty.title": "Aucune demande de congé",
  "hr.file.leave.empty.description": "Cet employé n'a demandé aucun congé.",
  "hr.file.payslips.title": "Aucun bulletin pour l'instant",
  "hr.file.payslips.description": "Les bulletins sont produits par le module de paie et seront listés ici.",
```

- [ ] **Step 3: Typecheck and look at it**

Run (from `frontend/`): `npx tsc -b --force`
Expected: exit 0.

Browser check: open an employee from the list — one branded loader, then the header and tabs; `?tab=family` in the URL opens the family tab; add a child with "counts for tax" ticked and a past "until" date — "counts today" says No; edit it (with `hr.admin_employees`). Log in as a user without `hr.view_sensitive` (revoke it from a test user in Admin › Users): the identity tab shows the lock and "••••" for NINA/INPS/AMO; open "Edit the file", change only the phone, save — the NINA stored before is still there when a user with the right looks. Record an exit: the status badge turns "Left" and the exit section appears.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/hr/Masked.tsx frontend/src/features/hr/employee frontend/src/routes/router.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(hr-ui): employee file page with identity, family, exit, leave and payslips tabs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Frontend — the contracts tab (create, edit, activate, amend, end)

**Files:**
- Create: `frontend/src/features/hr/employee/ContractsTab.tsx`, `ContractFormDialog.tsx`, `EndContractDialog.tsx`
- Modify: `frontend/src/features/hr/employee/EmployeeFilePage.tsx` (tab entry + case), `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: `listContracts`, `createContract`, `updateContract`, `activateContract`, `amendContract`, `endContract`, `listGrades`, `listPositions`, `hrKeys`, labels, `HrTable`, `FormField`, `Masked` (Tasks 10–11); `RowActionsMenu` (`components/patterns/RowActionsMenu.tsx`).
- Produces: `ContractsTab({ employee })`; `ContractFormDialog({ open, onOpenChange, employeeId, mode: "create" | "edit" | "amend", contract })`; `EndContractDialog({ open, onOpenChange, contract })`.
- Rule: edit and amend send **only changed fields**; a caller without `hr.view_sensitive` cannot type pay or allowances (read-only), so the masked values are never sent back; creating needs the right (the button says why when it is missing).

- [ ] **Step 1: Write the dialogs and the tab**

`frontend/src/features/hr/employee/ContractFormDialog.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { Button } from "../../../components/ui/button";
import { Checkbox } from "../../../components/ui/checkbox";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import {
  amendContract,
  CONTRACT_TYPES,
  createContract,
  hrKeys,
  listGrades,
  listPositions,
  PAY_FREQUENCIES,
  updateContract,
  type Contract,
  type ContractChanges,
  type ContractComponent,
  type ContractType,
  type PayFrequency,
} from "../api";
import { CONTRACT_TYPE_LABEL, PAY_FREQUENCY_LABEL } from "../employeeLabels";
import { emptyToNull, formatXof, todayIso } from "../employeeFormat";
import { FormField } from "../FormField";

export type ContractDialogMode = "create" | "edit" | "amend";

interface ComponentRow {
  component_code: string;
  kind: "amount" | "rate";
  value: string;
}

interface ContractForm {
  contract_type: ContractType;
  start_date: string;
  end_date: string;
  trial_end_date: string;
  weekly_hours: string;
  base_salary: string;
  pay_frequency: PayFrequency;
  position_id: string;
  grade_id: string;
  draft: boolean;
  effective_date: string;
  components: ComponentRow[];
}

function toForm(contract: Contract | null): ContractForm {
  return {
    contract_type: contract?.contract_type ?? "cdi",
    start_date: contract?.start_date ?? todayIso(),
    end_date: contract?.end_date ?? "",
    trial_end_date: contract?.trial_end_date ?? "",
    // 40 h is the spec's default working week; HR changes it per contract.
    weekly_hours: contract ? String(contract.weekly_hours) : "40",
    base_salary: contract?.base_salary == null ? "" : String(contract.base_salary),
    pay_frequency: contract?.pay_frequency ?? "monthly",
    position_id: contract?.position_id ?? "",
    grade_id: contract?.grade_id ?? "",
    draft: contract?.status === "draft",
    effective_date: todayIso(),
    components: (contract?.components ?? []).map((component) => ({
      component_code: component.component_code,
      kind: component.rate !== null ? "rate" : "amount",
      value: String(component.rate ?? component.amount ?? ""),
    })),
  };
}

function toComponents(rows: ComponentRow[]): ContractComponent[] {
  return rows
    .filter((row) => row.component_code.trim() !== "")
    .map((row) => ({
      component_code: row.component_code.trim().toUpperCase(),
      amount: row.kind === "amount" ? Number(row.value) : null,
      rate: row.kind === "rate" ? Number(row.value) : null,
    }));
}

/** What the user changed; an amendment never carries the start or trial dates. */
function changes(initial: ContractForm, form: ContractForm, mode: "edit" | "amend"): ContractChanges {
  const out: ContractChanges = {};
  if (form.contract_type !== initial.contract_type) out.contract_type = form.contract_type;
  if (mode === "edit" && form.start_date !== initial.start_date) out.start_date = form.start_date;
  if (form.end_date !== initial.end_date) out.end_date = emptyToNull(form.end_date);
  if (mode === "edit" && form.trial_end_date !== initial.trial_end_date) out.trial_end_date = emptyToNull(form.trial_end_date);
  if (form.weekly_hours !== initial.weekly_hours) out.weekly_hours = Number(form.weekly_hours);
  if (form.base_salary !== initial.base_salary) out.base_salary = Number(form.base_salary);
  if (form.pay_frequency !== initial.pay_frequency) out.pay_frequency = form.pay_frequency;
  if (form.position_id !== initial.position_id) out.position_id = emptyToNull(form.position_id);
  if (form.grade_id !== initial.grade_id) out.grade_id = emptyToNull(form.grade_id);
  if (JSON.stringify(form.components) !== JSON.stringify(initial.components)) out.components = toComponents(form.components);
  return out;
}

export function ContractFormDialog({
  open,
  onOpenChange,
  employeeId,
  mode,
  contract,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  employeeId: string;
  mode: ContractDialogMode;
  contract: Contract | null;
}) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canSeeSensitive = hasPermission("hr.view_sensitive");
  const [initial, setInitial] = useState<ContractForm>(toForm(null));
  const [form, setForm] = useState<ContractForm>(toForm(null));

  useEffect(() => {
    if (!open) return;
    const start = toForm(mode === "create" ? null : contract);
    setInitial(start);
    setForm(start);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, mode, contract?.id]);

  const positions = useQuery({ queryKey: hrKeys.positions, queryFn: () => listPositions(token), enabled: open && hasPermission("hr.view_positions") });
  const grades = useQuery({ queryKey: hrKeys.grades, queryFn: () => listGrades(token), enabled: open && hasPermission("hr.view_positions") });
  const grade = (grades.data ?? []).find((entry) => entry.id === form.grade_id);

  const mutation = useMutation({
    mutationFn: () => {
      if (mode === "create") {
        return createContract(token, {
          employee_id: employeeId,
          contract_type: form.contract_type,
          start_date: form.start_date,
          base_salary: Number(form.base_salary),
          end_date: emptyToNull(form.end_date),
          trial_end_date: emptyToNull(form.trial_end_date),
          weekly_hours: Number(form.weekly_hours),
          pay_frequency: form.pay_frequency,
          position_id: emptyToNull(form.position_id),
          grade_id: emptyToNull(form.grade_id),
          status: form.draft ? "draft" : "active",
          components: toComponents(form.components),
        });
      }
      if (mode === "edit") return updateContract(token, contract!.id, changes(initial, form, "edit"));
      return amendContract(token, contract!.id, { effective_date: form.effective_date, ...changes(initial, form, "amend") });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.contracts });
      queryClient.invalidateQueries({ queryKey: hrKeys.employees });
      queryClient.invalidateQueries({ queryKey: hrKeys.alerts });
      toast.success(t(mode === "amend" ? "hr.contracts.amended" : "hr.contracts.saved"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(t("hr.contracts.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const set = (patch: Partial<ContractForm>) => setForm((current) => ({ ...current, ...patch }));
  const setRow = (index: number, patch: Partial<ComponentRow>) =>
    set({ components: form.components.map((row, i) => (i === index ? { ...row, ...patch } : row)) });
  const payLocked = !canSeeSensitive;
  const title = mode === "create" ? "hr.contracts.dialog.createTitle" : mode === "edit" ? "hr.contracts.dialog.editTitle" : "hr.contracts.dialog.amendTitle";
  const description =
    mode === "create" ? "hr.contracts.dialog.createDescription" : mode === "edit" ? "hr.contracts.dialog.editDescription" : "hr.contracts.dialog.amendDescription";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t(title)}</DialogTitle>
          <DialogDescription>{t(description)}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {mode === "amend" && (
              <FormField id="contract-effective" label={t("hr.contracts.field.effectiveDate")}>
                <Input id="contract-effective" type="date" required value={form.effective_date} onChange={(event) => set({ effective_date: event.target.value })} />
              </FormField>
            )}
            <FormField id="contract-type" label={t("hr.contracts.field.type")}>
              <Select id="contract-type" value={form.contract_type} onChange={(event) => set({ contract_type: event.target.value as ContractType })}>
                {CONTRACT_TYPES.map((value) => (
                  <option key={value} value={value}>
                    {t(CONTRACT_TYPE_LABEL[value])}
                  </option>
                ))}
              </Select>
            </FormField>
            {mode !== "amend" && (
              <FormField id="contract-start" label={t("hr.contracts.field.start")}>
                <Input id="contract-start" type="date" required value={form.start_date} onChange={(event) => set({ start_date: event.target.value })} />
              </FormField>
            )}
            <FormField id="contract-end" label={t("hr.contracts.field.end")}>
              <Input id="contract-end" type="date" value={form.end_date} onChange={(event) => set({ end_date: event.target.value })} />
            </FormField>
            {mode !== "amend" && (
              <FormField id="contract-trial" label={t("hr.contracts.field.trialEnd")}>
                <Input id="contract-trial" type="date" value={form.trial_end_date} onChange={(event) => set({ trial_end_date: event.target.value })} />
              </FormField>
            )}
            <FormField id="contract-hours" label={t("hr.contracts.field.hours")}>
              <Input id="contract-hours" type="number" min="1" max="168" step="0.5" required value={form.weekly_hours} onChange={(event) => set({ weekly_hours: event.target.value })} />
            </FormField>
            <FormField id="contract-frequency" label={t("hr.contracts.field.frequency")}>
              <Select id="contract-frequency" value={form.pay_frequency} onChange={(event) => set({ pay_frequency: event.target.value as PayFrequency })}>
                {PAY_FREQUENCIES.map((value) => (
                  <option key={value} value={value}>
                    {t(PAY_FREQUENCY_LABEL[value])}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField
              id="contract-pay"
              label={t("hr.contracts.field.pay")}
              hint={payLocked ? t("hr.sensitive.readOnly") : grade ? `${t("hr.contracts.gradeMinimum")}: ${formatXof(grade.base_salary)}` : undefined}
            >
              <Input
                id="contract-pay"
                type="number"
                min="0"
                step="1"
                required={mode === "create"}
                readOnly={payLocked}
                className={payLocked ? "bg-muted" : undefined}
                placeholder={payLocked ? "••••" : undefined}
                value={form.base_salary}
                onChange={(event) => set({ base_salary: event.target.value })}
              />
            </FormField>
            <FormField id="contract-position" label={t("hr.field.position")}>
              <Select id="contract-position" value={form.position_id} onChange={(event) => set({ position_id: event.target.value })}>
                <option value="">{t("hr.form.noneOption")}</option>
                {(positions.data ?? []).map((position) => (
                  <option key={position.id} value={position.id}>
                    {position.code} — {position.title}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField id="contract-grade" label={t("hr.field.grade")}>
              <Select id="contract-grade" value={form.grade_id} onChange={(event) => set({ grade_id: event.target.value })}>
                <option value="">{t("hr.form.noneOption")}</option>
                {(grades.data ?? []).map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.code} — {entry.category} {entry.echelon}
                  </option>
                ))}
              </Select>
            </FormField>
          </div>

          <div className="space-y-2">
            <p className="text-sm font-medium">{t("hr.contracts.field.components")}</p>
            {form.components.map((row, index) => (
              <div key={index} className="grid grid-cols-[1fr_8rem_1fr_auto] items-end gap-2">
                <Input
                  aria-label={t("hr.contracts.field.componentCode")}
                  placeholder="TRANSPORT"
                  readOnly={payLocked}
                  value={row.component_code}
                  onChange={(event) => setRow(index, { component_code: event.target.value.toUpperCase() })}
                />
                <Select disabled={payLocked} value={row.kind} onChange={(event) => setRow(index, { kind: event.target.value as ComponentRow["kind"] })}>
                  <option value="amount">{t("hr.contracts.kind.amount")}</option>
                  <option value="rate">{t("hr.contracts.kind.rate")}</option>
                </Select>
                <Input
                  aria-label={t(row.kind === "amount" ? "hr.contracts.field.componentAmount" : "hr.contracts.field.componentRate")}
                  placeholder={payLocked ? "••••" : t(row.kind === "amount" ? "hr.contracts.field.componentAmount" : "hr.contracts.field.componentRate")}
                  type="number"
                  min="0"
                  step={row.kind === "amount" ? "1" : "0.01"}
                  readOnly={payLocked}
                  value={row.value}
                  onChange={(event) => setRow(index, { value: event.target.value })}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={payLocked}
                  aria-label={t("hr.contracts.removeComponent")}
                  onClick={() => set({ components: form.components.filter((_, i) => i !== index) })}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={payLocked}
              onClick={() => set({ components: [...form.components, { component_code: "", kind: "amount", value: "" }] })}
            >
              <Plus className="h-3.5 w-3.5" />
              {t("hr.contracts.addComponent")}
            </Button>
          </div>

          {mode === "create" && (
            <div className="flex items-center gap-2">
              <Checkbox id="contract-draft" checked={form.draft} onCheckedChange={(checked) => set({ draft: checked === true })} />
              <Label htmlFor="contract-draft">{t("hr.contracts.field.statusDraft")}</Label>
            </div>
          )}

          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            {mutation.isPending
              ? t("common.saving")
              : t(mode === "create" ? "hr.contracts.create" : mode === "amend" ? "hr.contracts.saveAmendment" : "common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

(The component-kind `<Select>` is a controlled plain select, not a React Hook Form field, so `disabled` is fine there.)

`frontend/src/features/hr/employee/EndContractDialog.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { endContract, hrKeys, TERMINATION_REASONS, type Contract, type TerminationReason } from "../api";
import { END_REASON_LABEL } from "../employeeLabels";
import { todayIso } from "../employeeFormat";
import { FormField } from "../FormField";

export function EndContractDialog({ open, onOpenChange, contract }: { open: boolean; onOpenChange: (open: boolean) => void; contract: Contract | null }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [day, setDay] = useState(todayIso());
  const [reason, setReason] = useState<TerminationReason>("term_reached");

  useEffect(() => {
    if (open && contract) {
      setDay(contract.end_date ?? todayIso());
      setReason(contract.end_date ? "term_reached" : "resignation");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, contract?.id]);

  const mutation = useMutation({
    mutationFn: () => endContract(session!.token, contract!.id, { end_date: day, end_reason: reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.contracts });
      queryClient.invalidateQueries({ queryKey: hrKeys.employees });
      queryClient.invalidateQueries({ queryKey: hrKeys.alerts });
      toast.success(t("hr.contracts.ended"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(t("hr.contracts.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("hr.contracts.end.title")}</DialogTitle>
          <DialogDescription>{t("hr.contracts.end.description")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <FormField id="end-date" label={t("hr.contracts.end.date")}>
            <Input id="end-date" type="date" required value={day} onChange={(event) => setDay(event.target.value)} />
          </FormField>
          <FormField id="end-reason" label={t("hr.contracts.end.reason")}>
            <Select id="end-reason" value={reason} onChange={(event) => setReason(event.target.value as TerminationReason)}>
              {TERMINATION_REASONS.map((value) => (
                <option key={value} value={value}>
                  {t(END_REASON_LABEL[value])}
                </option>
              ))}
            </Select>
          </FormField>
          <Button type="submit" variant="destructive" className="w-full" disabled={mutation.isPending || !day}>
            {mutation.isPending ? t("common.saving") : t("hr.contracts.end.confirm")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

`frontend/src/features/hr/employee/ContractsTab.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, CheckCircle2, FileText, Pencil, Plus, Split } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { RowActionsMenu, type RowAction } from "../../../components/patterns/RowActionsMenu";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { activateContract, CONTRACT_STATUSES, hrKeys, listContracts, type Contract, type ContractStatus, type EmployeeRecord } from "../api";
import { CONTRACT_STATUS_LABEL, CONTRACT_STATUS_VARIANT, CONTRACT_TYPE_LABEL, END_REASON_LABEL, PAY_FREQUENCY_LABEL } from "../employeeLabels";
import { formatDate, formatXof } from "../employeeFormat";
import { HrTable } from "../HrTable";
import { Masked } from "../Masked";
import { ContractFormDialog, type ContractDialogMode } from "./ContractFormDialog";
import { EndContractDialog } from "./EndContractDialog";

type StatusFilter = "all" | ContractStatus;

export function ContractsTab({ employee }: { employee: EmployeeRecord }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<StatusFilter>("all");
  const [form, setForm] = useState<{ open: boolean; mode: ContractDialogMode; contract: Contract | null }>({ open: false, mode: "create", contract: null });
  const [ending, setEnding] = useState<Contract | null>(null);
  const { data: contracts = [], isLoading } = useQuery({
    queryKey: hrKeys.employeeContracts(employee.id),
    queryFn: () => listContracts(session!.token, employee.id),
  });
  const activate = useMutation({
    mutationFn: (contract: Contract) => activateContract(session!.token, contract.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.contracts });
      queryClient.invalidateQueries({ queryKey: hrKeys.employees });
      toast.success(t("hr.contracts.activated"));
    },
    onError: (error) => toast.error(t("hr.contracts.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const filters = useColumnFilters<Contract>([
    { key: "position", kind: "text", getValue: (row) => row.position_title },
    { key: "grade", kind: "text", getValue: (row) => row.grade_code },
    { key: "pay", kind: "range", getValue: (row) => row.base_salary },
    { key: "components", kind: "text", getValue: (row) => row.components.map((c) => c.component_code).join(" ") },
  ]);
  const rows = filters.apply(status === "all" ? contracts : contracts.filter((row) => row.status === status));
  const statusOptions: { value: StatusFilter; label: string }[] = [
    { value: "all", label: t("common.all") },
    ...CONTRACT_STATUSES.map((value) => ({ value, label: t(CONTRACT_STATUS_LABEL[value]) })),
  ];
  const canCreate = hasPermission("hr.manage_contracts") && hasPermission("hr.view_sensitive") && employee.status !== "terminated";

  const actionsFor = (row: Contract): RowAction[] => {
    const actions: RowAction[] = [];
    if (hasPermission("hr.admin_contracts")) {
      actions.push({ key: "edit", label: t("hr.contracts.action.edit"), icon: <Pencil className="h-3.5 w-3.5" />, onSelect: () => setForm({ open: true, mode: "edit", contract: row }) });
    }
    if (hasPermission("hr.manage_contracts") && row.status === "draft") {
      actions.push({ key: "activate", label: t("hr.contracts.action.activate"), icon: <CheckCircle2 className="h-3.5 w-3.5" />, onSelect: () => activate.mutate(row) });
    }
    if (hasPermission("hr.manage_contracts") && row.status === "active") {
      actions.push({ key: "amend", label: t("hr.contracts.action.amend"), icon: <Split className="h-3.5 w-3.5" />, onSelect: () => setForm({ open: true, mode: "amend", contract: row }) });
      actions.push({ key: "end", label: t("hr.contracts.action.end"), icon: <Ban className="h-3.5 w-3.5" />, tone: "destructive", onSelect: () => setEnding(row) });
    }
    return actions;
  };

  const columns: ColumnDef<Contract>[] = [
    { key: "type", header: t("hr.contracts.column.type"), defaultWidth: 150, cell: (row) => t(CONTRACT_TYPE_LABEL[row.contract_type]), sortValue: (row) => row.contract_type },
    { key: "start", header: t("hr.contracts.column.start"), defaultWidth: 115, cell: (row) => formatDate(row.start_date), sortValue: (row) => row.start_date },
    { key: "end", header: t("hr.contracts.column.end"), defaultWidth: 115, cell: (row) => formatDate(row.end_date), sortValue: (row) => row.end_date },
    { key: "trial", header: t("hr.contracts.column.trialEnd"), defaultWidth: 115, cell: (row) => formatDate(row.trial_end_date), sortValue: (row) => row.trial_end_date },
    { key: "hours", header: t("hr.contracts.column.hours"), defaultWidth: 110, cell: (row) => row.weekly_hours, sortValue: (row) => row.weekly_hours },
    {
      key: "pay",
      header: t("hr.contracts.column.pay"),
      defaultWidth: 170,
      cell: (row) =>
        row.sensitive_hidden ? (
          <Masked />
        ) : (
          <span className="tabular-nums">
            {formatXof(row.base_salary)} {t(row.pay_frequency === "daily" ? "hr.contracts.perDay" : "hr.contracts.perMonth")}
            {row.currency !== "XOF" && <span className="ml-1 text-xs text-destructive">{row.currency}</span>}
          </span>
        ),
      filterCell: {
        type: "range",
        min: filters.range.pay?.min ?? "",
        max: filters.range.pay?.max ?? "",
        onMinChange: (value) => filters.setRangeValue("pay", "min", value),
        onMaxChange: (value) => filters.setRangeValue("pay", "max", value),
      },
      sortValue: (row) => row.base_salary,
    },
    {
      key: "components",
      header: t("hr.contracts.column.components"),
      defaultWidth: 220,
      cell: (row) =>
        row.components.length === 0
          ? "—"
          : row.components.map((c) => (
              <span key={c.component_code} className="mr-2 whitespace-nowrap text-xs">
                {c.component_code}{" "}
                {row.sensitive_hidden ? "••••" : c.rate !== null ? `${c.rate} %` : formatXof(c.amount)}
              </span>
            )),
      filterCell: {
        type: "text",
        value: filters.text.components ?? "",
        onChange: (value) => filters.setTextValue("components", value),
        placeholder: t("hr.contracts.column.components"),
      },
    },
    {
      key: "position",
      header: t("hr.field.position"),
      defaultWidth: 160,
      cell: (row) => row.position_title ?? "—",
      filterCell: { type: "text", value: filters.text.position ?? "", onChange: (value) => filters.setTextValue("position", value), placeholder: t("hr.field.position") },
    },
    {
      key: "grade",
      header: t("hr.field.grade"),
      defaultWidth: 100,
      cell: (row) => row.grade_code ?? "—",
      filterCell: { type: "text", value: filters.text.grade ?? "", onChange: (value) => filters.setTextValue("grade", value), placeholder: t("hr.field.grade") },
    },
    {
      key: "status",
      header: t("hr.contracts.column.status"),
      defaultWidth: 110,
      cell: (row) => (
        <Badge variant={CONTRACT_STATUS_VARIANT[row.status]} dot>
          {t(CONTRACT_STATUS_LABEL[row.status])}
        </Badge>
      ),
      sortValue: (row) => row.status,
    },
    { key: "reason", header: t("hr.contracts.column.endReason"), defaultWidth: 170, cell: (row) => (row.end_reason ? t(END_REASON_LABEL[row.end_reason]) : "—") },
    { key: "frequency", header: t("hr.contracts.field.frequency"), defaultWidth: 110, cell: (row) => t(PAY_FREQUENCY_LABEL[row.pay_frequency]) },
    { key: "actions", header: "", defaultWidth: 70, alwaysVisible: true, cellClassName: "text-right", cell: (row) => <RowActionsMenu actions={actionsFor(row)} /> },
  ];

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
        <CardTitle className="text-base">{t("hr.contracts.title")}</CardTitle>
        {hasPermission("hr.manage_contracts") && (
          <div className="flex items-center gap-2">
            {!hasPermission("hr.view_sensitive") && <span className="text-xs text-muted-foreground">{t("hr.contracts.needsSensitive")}</span>}
            <Button disabled={!canCreate} onClick={() => setForm({ open: true, mode: "create", contract: null })}>
              <Plus className="h-4 w-4" />
              {t("hr.contracts.new")}
            </Button>
          </div>
        )}
      </CardHeader>
      <CardContent>
        <HrTable
          tableKey="hr.employee.contracts"
          columns={columns}
          rows={rows}
          rowKey={(row) => row.id}
          isLoading={isLoading}
          empty={{ icon: <FileText className="h-5 w-5" />, title: t("hr.contracts.empty.title"), description: t("hr.contracts.empty.description") }}
          toolbar={<FilterTabs value={status} onChange={setStatus} options={statusOptions} />}
          filtersActive={filters.isActive}
          onClearFilters={filters.reset}
        />
      </CardContent>
      <ContractFormDialog
        open={form.open}
        onOpenChange={(open) => setForm((current) => ({ ...current, open }))}
        employeeId={employee.id}
        mode={form.mode}
        contract={form.contract}
      />
      <EndContractDialog open={ending !== null} onOpenChange={(open) => !open && setEnding(null)} contract={ending} />
    </Card>
  );
}
```

`FileText` and `CheckCircle2` / `Split` are in the lucide set the app already uses.

- [ ] **Step 2: Wire the tab and add the strings**

In `EmployeeFilePage.tsx`: add `FileText` to the `lucide-react` import, `import { ContractsTab } from "./ContractsTab";`, insert into `TABS` right after the `family` entry:

```tsx
  { value: "contracts", labelKey: "hr.file.tab.contracts", icon: FileText, permission: "hr.view_contracts" },
```

and add to `TabBody`'s switch:

```tsx
    case "contracts":
      return <ContractsTab employee={employee} />;
```

Add to `en`:

```ts
  "hr.contracts.title": "Contract history",
  "hr.contracts.new": "New contract",
  "hr.contracts.needsSensitive": "A contract sets pay: creating one needs the right to view sensitive HR data.",
  "hr.contracts.column.type": "Type",
  "hr.contracts.column.start": "Start",
  "hr.contracts.column.end": "End",
  "hr.contracts.column.trialEnd": "Trial ends",
  "hr.contracts.column.hours": "Hours / week",
  "hr.contracts.column.pay": "Base pay",
  "hr.contracts.column.components": "Allowances",
  "hr.contracts.column.status": "Status",
  "hr.contracts.column.endReason": "End reason",
  "hr.contracts.perDay": "/ day",
  "hr.contracts.perMonth": "/ month",
  "hr.contracts.empty.title": "No contract",
  "hr.contracts.empty.description": "Create the employee's first contract.",
  "hr.contracts.action.edit": "Edit",
  "hr.contracts.action.activate": "Activate",
  "hr.contracts.action.amend": "Amendment",
  "hr.contracts.action.end": "End the contract",
  "hr.contracts.activated": "Contract activated",
  "hr.contracts.saved": "Contract saved",
  "hr.contracts.amended": "Amendment recorded",
  "hr.contracts.ended": "Contract ended",
  "hr.contracts.error": "The contract could not be saved",
  "hr.contracts.dialog.createTitle": "New contract",
  "hr.contracts.dialog.createDescription": "An employee has at most one signed contract on any day. A draft does not count until it is activated.",
  "hr.contracts.dialog.editTitle": "Edit the contract",
  "hr.contracts.dialog.editDescription": "Corrects the contract as recorded. To change the terms from a date, record an amendment instead.",
  "hr.contracts.dialog.amendTitle": "Amendment",
  "hr.contracts.dialog.amendDescription": "The current terms end the day before the effective date and the new ones apply from it. The trial period is not carried over.",
  "hr.contracts.field.type": "Contract type",
  "hr.contracts.field.start": "Start date",
  "hr.contracts.field.end": "End date",
  "hr.contracts.field.trialEnd": "Trial period ends",
  "hr.contracts.field.hours": "Weekly hours",
  "hr.contracts.field.pay": "Base salary (F CFA)",
  "hr.contracts.field.frequency": "Paid",
  "hr.contracts.field.statusDraft": "Save as draft (not signed yet)",
  "hr.contracts.field.effectiveDate": "Effective date",
  "hr.contracts.field.components": "Fixed allowances",
  "hr.contracts.field.componentCode": "Code",
  "hr.contracts.field.componentAmount": "Amount (F CFA)",
  "hr.contracts.field.componentRate": "Rate (%)",
  "hr.contracts.kind.amount": "Amount",
  "hr.contracts.kind.rate": "Rate",
  "hr.contracts.addComponent": "Add an allowance",
  "hr.contracts.removeComponent": "Remove",
  "hr.contracts.gradeMinimum": "Grade minimum",
  "hr.contracts.create": "Create the contract",
  "hr.contracts.saveAmendment": "Record the amendment",
  "hr.contracts.end.title": "End the contract",
  "hr.contracts.end.description": "The last day worked under this contract and why it ends.",
  "hr.contracts.end.date": "Last day",
  "hr.contracts.end.reason": "Reason",
  "hr.contracts.end.confirm": "End the contract",
```

Add to `fr`:

```ts
  "hr.contracts.title": "Historique des contrats",
  "hr.contracts.new": "Nouveau contrat",
  "hr.contracts.needsSensitive": "Un contrat fixe une rémunération : le créer demande le droit de voir les données RH sensibles.",
  "hr.contracts.column.type": "Type",
  "hr.contracts.column.start": "Début",
  "hr.contracts.column.end": "Fin",
  "hr.contracts.column.trialEnd": "Fin d'essai",
  "hr.contracts.column.hours": "Heures / semaine",
  "hr.contracts.column.pay": "Salaire de base",
  "hr.contracts.column.components": "Indemnités",
  "hr.contracts.column.status": "Statut",
  "hr.contracts.column.endReason": "Motif de fin",
  "hr.contracts.perDay": "/ jour",
  "hr.contracts.perMonth": "/ mois",
  "hr.contracts.empty.title": "Aucun contrat",
  "hr.contracts.empty.description": "Créez le premier contrat de l'employé.",
  "hr.contracts.action.edit": "Modifier",
  "hr.contracts.action.activate": "Activer",
  "hr.contracts.action.amend": "Avenant",
  "hr.contracts.action.end": "Mettre fin au contrat",
  "hr.contracts.activated": "Contrat activé",
  "hr.contracts.saved": "Contrat enregistré",
  "hr.contracts.amended": "Avenant enregistré",
  "hr.contracts.ended": "Fin de contrat enregistrée",
  "hr.contracts.error": "Le contrat n'a pas pu être enregistré",
  "hr.contracts.dialog.createTitle": "Nouveau contrat",
  "hr.contracts.dialog.createDescription": "Un employé a au plus un contrat signé chaque jour. Un brouillon ne compte pas tant qu'il n'est pas activé.",
  "hr.contracts.dialog.editTitle": "Modifier le contrat",
  "hr.contracts.dialog.editDescription": "Corrige le contrat tel qu'il a été saisi. Pour changer les conditions à partir d'une date, faites plutôt un avenant.",
  "hr.contracts.dialog.amendTitle": "Avenant",
  "hr.contracts.dialog.amendDescription": "Les conditions actuelles prennent fin la veille de la date d'effet et les nouvelles s'appliquent à partir de celle-ci. La période d'essai n'est pas reprise.",
  "hr.contracts.field.type": "Type de contrat",
  "hr.contracts.field.start": "Date de début",
  "hr.contracts.field.end": "Date de fin",
  "hr.contracts.field.trialEnd": "Fin de la période d'essai",
  "hr.contracts.field.hours": "Heures hebdomadaires",
  "hr.contracts.field.pay": "Salaire de base (F CFA)",
  "hr.contracts.field.frequency": "Payé",
  "hr.contracts.field.statusDraft": "Enregistrer en brouillon (pas encore signé)",
  "hr.contracts.field.effectiveDate": "Date d'effet",
  "hr.contracts.field.components": "Indemnités fixes",
  "hr.contracts.field.componentCode": "Code",
  "hr.contracts.field.componentAmount": "Montant (F CFA)",
  "hr.contracts.field.componentRate": "Taux (%)",
  "hr.contracts.kind.amount": "Montant",
  "hr.contracts.kind.rate": "Taux",
  "hr.contracts.addComponent": "Ajouter une indemnité",
  "hr.contracts.removeComponent": "Retirer",
  "hr.contracts.gradeMinimum": "Minimum de la catégorie",
  "hr.contracts.create": "Créer le contrat",
  "hr.contracts.saveAmendment": "Enregistrer l'avenant",
  "hr.contracts.end.title": "Mettre fin au contrat",
  "hr.contracts.end.description": "Le dernier jour travaillé sous ce contrat et le motif de la fin.",
  "hr.contracts.end.date": "Dernier jour",
  "hr.contracts.end.reason": "Motif",
  "hr.contracts.end.confirm": "Mettre fin au contrat",
```

- [ ] **Step 3: Typecheck and look at it**

Run (from `frontend/`): `npx tsc -b --force`
Expected: exit 0.

Browser check on an employee: create a CDI with a TRANSPORT allowance; creating a second signed contract on overlapping dates shows the French/English `CONTRACT_OVERLAP` toast; save one as draft, then "Activate"; record an amendment from next month with a new pay — the old row shows "Expired · Replaced by an amendment"; "End the contract" on a CDD. As a user without `hr.view_sensitive`: pay and allowances show the lock, "New contract" is disabled with its reason, and editing the weekly hours saves without touching the pay.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/hr/employee/ContractsTab.tsx frontend/src/features/hr/employee/ContractFormDialog.tsx frontend/src/features/hr/employee/EndContractDialog.tsx frontend/src/features/hr/employee/EmployeeFilePage.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(hr-ui): contracts tab with amendments, activation, end and masked pay

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Frontend — the payment and documents tabs

**Files:**
- Create: `frontend/src/features/hr/employee/PaymentTab.tsx`, `frontend/src/features/hr/employee/DocumentsTab.tsx`
- Modify: `frontend/src/features/hr/employee/EmployeeFilePage.tsx`, `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: `listPaymentSets`, `replacePaymentSet`, `listDocuments`, `createDocument`, `updateDocument`, `hrKeys`, labels, `HrTable`, `FormField`, `Masked`.
- Produces: `PaymentTab({ employee })`, `DocumentsTab({ employee })`.
- Payment arrangements are shown as dated cards (one to three lines each), not a list view, so they carry no filter row. An arrangement is always saved whole (`PUT`), with a live total that must reach 100 %; a caller without `hr.view_sensitive` can record cash only, and can only edit an arrangement that is cash-only (anything else would send its hidden numbers back empty).

- [ ] **Step 1: Write the tabs**

`frontend/src/features/hr/employee/PaymentTab.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2, Wallet } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { currentLocale, useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { Skeleton } from "../../../components/ui/skeleton";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import {
  hrKeys,
  listPaymentSets,
  MOBILE_OPERATORS,
  PAYMENT_METHODS,
  replacePaymentSet,
  type EmployeeRecord,
  type MobileOperator,
  type PaymentMethod,
  type PaymentMethodInput,
  type PaymentMethodKind,
  type PaymentSet,
} from "../api";
import { OPERATOR_LABEL, PAYMENT_METHOD_LABEL } from "../employeeLabels";
import { emptyToNull, formatDate, todayIso } from "../employeeFormat";
import { FormField } from "../FormField";
import { Masked } from "../Masked";

export function PaymentTab({ employee }: { employee: EmployeeRecord }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const canSeeSensitive = hasPermission("hr.view_sensitive");
  const [dialog, setDialog] = useState<{ open: boolean; set: PaymentSet | null }>({ open: false, set: null });
  const { data: sets = [], isLoading } = useQuery({
    queryKey: hrKeys.paymentSets(employee.id),
    queryFn: () => listPaymentSets(session!.token, employee.id),
  });

  const describe = (method: PaymentMethod) => {
    if (method.method === "cash") return t("hr.payment.cashHint");
    const number = method.sensitive_hidden ? <Masked /> : method.method === "bank" ? method.account_no : method.mobile_number;
    const label = method.method === "bank" ? method.bank_name : method.mobile_operator ? t(OPERATOR_LABEL[method.mobile_operator]) : null;
    return (
      <span className="inline-flex items-center gap-1.5">
        {label} · {number}
      </span>
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-3xl text-sm text-muted-foreground">{t("hr.payment.help")}</p>
        {hasPermission("hr.manage_employees") && (
          <Button onClick={() => setDialog({ open: true, set: null })}>
            <Plus className="h-4 w-4" />
            {t("hr.payment.new")}
          </Button>
        )}
      </div>
      {isLoading && <Skeleton className="h-32 w-full" />}
      {!isLoading && sets.length === 0 && (
        <Card>
          <CardContent className="p-0">
            <EmptyState icon={<Wallet className="h-5 w-5" />} title={t("hr.payment.empty.title")} description={t("hr.payment.empty.description")} />
          </CardContent>
        </Card>
      )}
      {sets.map((set) => (
        <Card key={set.valid_from}>
          <CardHeader className="flex-row items-center justify-between gap-3 pb-2">
            <CardTitle className="flex items-center gap-2 text-base">
              {t("hr.payment.from")} {formatDate(set.valid_from)}
              {set.in_force && <Badge variant="success">{t("hr.payment.inForce")}</Badge>}
            </CardTitle>
            {hasPermission("hr.admin_employees") && (canSeeSensitive || set.methods.every((method) => method.method === "cash")) && (
              <Button size="sm" variant="outline" onClick={() => setDialog({ open: true, set })}>
                <Pencil className="h-3.5 w-3.5" />
                {t("common.edit")}
              </Button>
            )}
          </CardHeader>
          <CardContent>
            <ul className="divide-y divide-border text-sm">
              {set.methods.map((method) => (
                <li key={method.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span className="flex items-center gap-2 font-medium">
                    {t(PAYMENT_METHOD_LABEL[method.method])}
                    {method.is_primary && <Badge variant="primary">{t("hr.payment.primary")}</Badge>}
                  </span>
                  <span className="text-muted-foreground">{describe(method)}</span>
                  <span className="tabular-nums">{method.share_percent.toLocaleString(currentLocale())} %</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ))}
      <PaymentSetDialog
        employeeId={employee.id}
        open={dialog.open}
        set={dialog.set}
        canSeeSensitive={canSeeSensitive}
        onOpenChange={(open) => setDialog((current) => ({ ...current, open }))}
      />
    </div>
  );
}

interface MethodRow {
  method: PaymentMethodKind;
  bank_name: string;
  account_no: string;
  mobile_operator: MobileOperator;
  mobile_number: string;
  share_percent: string;
  is_primary: boolean;
}

function blankRow(primary: boolean, canSeeSensitive: boolean): MethodRow {
  return {
    method: canSeeSensitive ? "bank" : "cash",
    bank_name: "",
    account_no: "",
    mobile_operator: "orange_money",
    mobile_number: "",
    share_percent: primary ? "100" : "",
    is_primary: primary,
  };
}

function fromMethod(method: PaymentMethod): MethodRow {
  return {
    method: method.method,
    bank_name: method.bank_name ?? "",
    account_no: method.account_no ?? "",
    mobile_operator: method.mobile_operator ?? "orange_money",
    mobile_number: method.mobile_number ?? "",
    share_percent: String(method.share_percent),
    is_primary: method.is_primary,
  };
}

function toInput(row: MethodRow): PaymentMethodInput {
  const bank = row.method === "bank";
  const mobile = row.method === "mobile_money";
  return {
    method: row.method,
    share_percent: Number(row.share_percent),
    is_primary: row.is_primary,
    bank_name: bank ? emptyToNull(row.bank_name) : null,
    account_no: bank ? emptyToNull(row.account_no) : null,
    mobile_operator: mobile ? row.mobile_operator : null,
    mobile_number: mobile ? emptyToNull(row.mobile_number) : null,
  };
}

function PaymentSetDialog({
  employeeId,
  open,
  set,
  canSeeSensitive,
  onOpenChange,
}: {
  employeeId: string;
  open: boolean;
  set: PaymentSet | null;
  canSeeSensitive: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [validFrom, setValidFrom] = useState(todayIso());
  const [rows, setRows] = useState<MethodRow[]>([blankRow(true, canSeeSensitive)]);

  useEffect(() => {
    if (!open) return;
    setValidFrom(set?.valid_from ?? todayIso());
    setRows(set ? set.methods.map(fromMethod) : [blankRow(true, canSeeSensitive)]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, set?.valid_from]);

  const total = rows.reduce((sum, row) => sum + (Number(row.share_percent) || 0), 0);
  const mutation = useMutation({
    mutationFn: (methods: PaymentMethodInput[]) => replacePaymentSet(session!.token, employeeId, { valid_from: validFrom, methods }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.paymentSets(employeeId) });
      toast.success(t("hr.payment.saved"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(t("hr.payment.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });
  const update = (index: number, patch: Partial<MethodRow>) =>
    setRows(rows.map((row, i) => (i === index ? { ...row, ...patch } : patch.is_primary ? { ...row, is_primary: false } : row)));
  const methodChoices: readonly PaymentMethodKind[] = canSeeSensitive ? PAYMENT_METHODS : ["cash"];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t(set ? "hr.payment.dialog.editTitle" : "hr.payment.dialog.createTitle")}</DialogTitle>
          <DialogDescription>{t("hr.payment.dialog.description")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate(rows.map(toInput));
          }}
        >
          <FormField id="payment-from" label={t("hr.payment.field.validFrom")}>
            <Input id="payment-from" type="date" required readOnly={set !== null} value={validFrom} onChange={(event) => setValidFrom(event.target.value)} />
          </FormField>
          {!canSeeSensitive && <p className="text-xs text-muted-foreground">{t("hr.payment.cashOnly")}</p>}
          {rows.map((row, index) => (
            <div key={index} className="grid grid-cols-1 items-end gap-2 rounded-lg border border-border p-3 sm:grid-cols-6">
              <FormField id={`method-${index}`} label={t("hr.payment.field.method")}>
                <Select id={`method-${index}`} value={row.method} onChange={(event) => update(index, { method: event.target.value as PaymentMethodKind })}>
                  {methodChoices.map((value) => (
                    <option key={value} value={value}>
                      {t(PAYMENT_METHOD_LABEL[value])}
                    </option>
                  ))}
                </Select>
              </FormField>
              {row.method === "bank" && (
                <>
                  <FormField id={`bank-${index}`} label={t("hr.payment.field.bankName")}>
                    <Input id={`bank-${index}`} required value={row.bank_name} onChange={(event) => update(index, { bank_name: event.target.value })} />
                  </FormField>
                  <div className="sm:col-span-2">
                    <FormField id={`account-${index}`} label={t("hr.payment.field.accountNo")}>
                      <Input id={`account-${index}`} required value={row.account_no} onChange={(event) => update(index, { account_no: event.target.value })} />
                    </FormField>
                  </div>
                </>
              )}
              {row.method === "mobile_money" && (
                <>
                  <FormField id={`operator-${index}`} label={t("hr.payment.field.operator")}>
                    <Select id={`operator-${index}`} value={row.mobile_operator} onChange={(event) => update(index, { mobile_operator: event.target.value as MobileOperator })}>
                      {MOBILE_OPERATORS.map((value) => (
                        <option key={value} value={value}>
                          {t(OPERATOR_LABEL[value])}
                        </option>
                      ))}
                    </Select>
                  </FormField>
                  <div className="sm:col-span-2">
                    <FormField id={`mobile-${index}`} label={t("hr.payment.field.mobileNumber")}>
                      <Input id={`mobile-${index}`} required value={row.mobile_number} onChange={(event) => update(index, { mobile_number: event.target.value })} />
                    </FormField>
                  </div>
                </>
              )}
              {row.method === "cash" && <div className="sm:col-span-3" />}
              <FormField id={`share-${index}`} label={t("hr.payment.field.share")}>
                <Input
                  id={`share-${index}`}
                  type="number"
                  min="0.01"
                  max="100"
                  step="0.01"
                  required
                  value={row.share_percent}
                  onChange={(event) => update(index, { share_percent: event.target.value })}
                />
              </FormField>
              <div className="flex items-center justify-between gap-2 sm:col-span-6">
                <label className="flex items-center gap-2 text-sm">
                  <input type="radio" name="primary-method" checked={row.is_primary} onChange={() => update(index, { is_primary: true })} />
                  {t("hr.payment.field.primary")}
                </label>
                {rows.length > 1 && (
                  <Button type="button" variant="ghost" size="sm" onClick={() => setRows(rows.filter((_, i) => i !== index))}>
                    <Trash2 className="h-3.5 w-3.5" />
                    {t("hr.payment.removeMethod")}
                  </Button>
                )}
              </div>
            </div>
          ))}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => setRows([...rows, blankRow(false, canSeeSensitive)])}>
              <Plus className="h-3.5 w-3.5" />
              {t("hr.payment.addMethod")}
            </Button>
            <span className={Math.abs(total - 100) < 0.005 ? "text-sm text-muted-foreground" : "text-sm font-medium text-destructive"}>
              {t("hr.payment.total")}: {total.toLocaleString(currentLocale())} / 100 %
            </span>
          </div>
          <div className="flex gap-2">
            {set && (
              <Button type="button" variant="outline" className="flex-1" disabled={mutation.isPending} onClick={() => mutation.mutate([])}>
                {t("hr.payment.removeSet")}
              </Button>
            )}
            <Button type="submit" className="flex-1" disabled={mutation.isPending}>
              {mutation.isPending ? t("common.saving") : t("common.save")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

The total line only colours what the server enforces (shares add up to 100 %); the server is still the judge (`PAYOUT_SPLIT_INVALID`).

`frontend/src/features/hr/employee/DocumentsTab.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileStack, Pencil, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import {
  createDocument,
  DOCUMENT_KINDS,
  hrKeys,
  listDocuments,
  updateDocument,
  type DocumentInput,
  type DocumentKind,
  type DocumentState,
  type EmployeeDocument,
  type EmployeeRecord,
} from "../api";
import { DOCUMENT_KIND_LABEL, DOCUMENT_STATE_LABEL, DOCUMENT_STATE_VARIANT } from "../employeeLabels";
import { emptyToNull, formatDate } from "../employeeFormat";
import { FormField } from "../FormField";
import { HrTable } from "../HrTable";

type StateFilter = "all" | DocumentState | "none";

export function DocumentsTab({ employee }: { employee: EmployeeRecord }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const [state, setState] = useState<StateFilter>("all");
  const [dialog, setDialog] = useState<{ open: boolean; document: EmployeeDocument | null }>({ open: false, document: null });
  const { data: documents = [], isLoading } = useQuery({
    queryKey: hrKeys.documents(employee.id),
    queryFn: () => listDocuments(session!.token, employee.id),
  });
  const filters = useColumnFilters<EmployeeDocument>([
    { key: "title", kind: "text", getValue: (row) => row.title },
    { key: "file", kind: "text", getValue: (row) => row.file_ref },
  ]);
  const byState = state === "all" ? documents : documents.filter((row) => (state === "none" ? row.state === null : row.state === state));
  const rows = filters.apply(byState);
  const stateOptions: { value: StateFilter; label: string }[] = [
    { value: "all", label: t("common.all") },
    { value: "expired", label: t(DOCUMENT_STATE_LABEL.expired) },
    { value: "expiring", label: t(DOCUMENT_STATE_LABEL.expiring) },
    { value: "valid", label: t(DOCUMENT_STATE_LABEL.valid) },
    { value: "none", label: t("hr.documents.noExpiry") },
  ];

  const columns: ColumnDef<EmployeeDocument>[] = [
    { key: "kind", header: t("hr.documents.column.kind"), defaultWidth: 180, cell: (row) => t(DOCUMENT_KIND_LABEL[row.kind]), sortValue: (row) => row.kind },
    {
      key: "title",
      header: t("hr.documents.column.title"),
      defaultWidth: 180,
      cell: (row) => row.title ?? "—",
      filterCell: { type: "text", value: filters.text.title ?? "", onChange: (value) => filters.setTextValue("title", value), placeholder: t("hr.documents.column.title") },
    },
    { key: "issued", header: t("hr.documents.column.issued"), defaultWidth: 120, cell: (row) => formatDate(row.issued_on), sortValue: (row) => row.issued_on },
    { key: "expires", header: t("hr.documents.column.expires"), defaultWidth: 120, cell: (row) => formatDate(row.expires_on), sortValue: (row) => row.expires_on },
    {
      key: "state",
      header: t("hr.documents.column.state"),
      defaultWidth: 130,
      cell: (row) => (row.state ? <Badge variant={DOCUMENT_STATE_VARIANT[row.state]}>{t(DOCUMENT_STATE_LABEL[row.state])}</Badge> : t("hr.documents.noExpiry")),
    },
    {
      key: "file",
      header: t("hr.documents.column.file"),
      defaultWidth: 220,
      cell: (row) =>
        !row.file_ref ? (
          "—"
        ) : /^https?:\/\//.test(row.file_ref) ? (
          <a href={row.file_ref} target="_blank" rel="noreferrer" className="text-primary hover:underline">
            {row.file_ref}
          </a>
        ) : (
          <span className="font-mono text-xs">{row.file_ref}</span>
        ),
      filterCell: { type: "text", value: filters.text.file ?? "", onChange: (value) => filters.setTextValue("file", value), placeholder: t("hr.documents.column.file") },
    },
    {
      key: "actions",
      header: "",
      defaultWidth: 100,
      alwaysVisible: true,
      cellClassName: "text-right",
      cell: (row) =>
        hasPermission("hr.admin_employees") ? (
          <Button size="sm" variant="ghost" onClick={() => setDialog({ open: true, document: row })}>
            <Pencil className="h-3.5 w-3.5" />
            {t("common.edit")}
          </Button>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
        <CardTitle className="text-base">{t("hr.file.tab.documents")}</CardTitle>
        {hasPermission("hr.manage_employees") && (
          <Button onClick={() => setDialog({ open: true, document: null })}>
            <Plus className="h-4 w-4" />
            {t("hr.documents.add")}
          </Button>
        )}
      </CardHeader>
      <CardContent>
        <HrTable
          tableKey="hr.employee.documents"
          columns={columns}
          rows={rows}
          rowKey={(row) => row.id}
          isLoading={isLoading}
          empty={{ icon: <FileStack className="h-5 w-5" />, title: t("hr.documents.empty.title"), description: t("hr.documents.empty.description") }}
          toolbar={<FilterTabs value={state} onChange={setState} options={stateOptions} />}
          filtersActive={filters.isActive}
          onClearFilters={filters.reset}
        />
      </CardContent>
      <DocumentDialog
        employeeId={employee.id}
        open={dialog.open}
        document={dialog.document}
        onOpenChange={(open) => setDialog((current) => ({ ...current, open }))}
      />
    </Card>
  );
}

interface DocumentForm {
  kind: DocumentKind;
  title: string;
  file_ref: string;
  issued_on: string;
  expires_on: string;
}

function toForm(document: EmployeeDocument | null): DocumentForm {
  return {
    kind: document?.kind ?? "id_card",
    title: document?.title ?? "",
    file_ref: document?.file_ref ?? "",
    issued_on: document?.issued_on ?? "",
    expires_on: document?.expires_on ?? "",
  };
}

function DocumentDialog({
  employeeId,
  open,
  document,
  onOpenChange,
}: {
  employeeId: string;
  open: boolean;
  document: EmployeeDocument | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<DocumentForm>(toForm(null));

  useEffect(() => {
    if (open) setForm(toForm(document));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, document?.id]);

  const mutation = useMutation({
    mutationFn: () => {
      const input: DocumentInput = {
        kind: form.kind,
        title: emptyToNull(form.title),
        file_ref: emptyToNull(form.file_ref),
        issued_on: emptyToNull(form.issued_on),
        expires_on: emptyToNull(form.expires_on),
      };
      return document ? updateDocument(session!.token, document.id, input) : createDocument(session!.token, employeeId, input);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.documents(employeeId) });
      queryClient.invalidateQueries({ queryKey: hrKeys.alerts });
      toast.success(t("hr.documents.saved"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(t("hr.documents.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(document ? "hr.documents.dialog.editTitle" : "hr.documents.dialog.createTitle")}</DialogTitle>
          <DialogDescription>{t("hr.documents.dialog.description")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <div className="grid grid-cols-2 gap-3">
            <FormField id="document-kind" label={t("hr.documents.column.kind")}>
              <Select id="document-kind" value={form.kind} onChange={(event) => setForm({ ...form, kind: event.target.value as DocumentKind })}>
                {DOCUMENT_KINDS.map((value) => (
                  <option key={value} value={value}>
                    {t(DOCUMENT_KIND_LABEL[value])}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField id="document-title" label={t("hr.documents.column.title")}>
              <Input id="document-title" required={form.kind === "other"} value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} />
            </FormField>
            <FormField id="document-issued" label={t("hr.documents.column.issued")}>
              <Input id="document-issued" type="date" value={form.issued_on} onChange={(event) => setForm({ ...form, issued_on: event.target.value })} />
            </FormField>
            <FormField id="document-expires" label={t("hr.documents.column.expires")}>
              <Input id="document-expires" type="date" value={form.expires_on} onChange={(event) => setForm({ ...form, expires_on: event.target.value })} />
            </FormField>
          </div>
          <FormField id="document-file" label={t("hr.documents.field.fileRef")}>
            <Input id="document-file" placeholder="\\srv-rh\dossiers\HRP-001\passeport.pdf" value={form.file_ref} onChange={(event) => setForm({ ...form, file_ref: event.target.value })} />
          </FormField>
          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            {mutation.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: Wire the tabs and add the strings**

In `EmployeeFilePage.tsx`: add `FileStack, Wallet` to the `lucide-react` import, import `PaymentTab` and `DocumentsTab`, insert into `TABS` right after the `contracts` entry:

```tsx
  { value: "payment", labelKey: "hr.file.tab.payment", icon: Wallet, permission: "hr.view_employees" },
  { value: "documents", labelKey: "hr.file.tab.documents", icon: FileStack, permission: "hr.view_employees" },
```

and add to the switch:

```tsx
    case "payment":
      return <PaymentTab employee={employee} />;
    case "documents":
      return <DocumentsTab employee={employee} />;
```

Add to `en`:

```ts
  "hr.payment.help": "Net pay is split between the methods in force on the last day of the month, by their shares (100 % in total). A new arrangement from a later date replaces the current one on that date.",
  "hr.payment.new": "New arrangement",
  "hr.payment.from": "From",
  "hr.payment.inForce": "In force",
  "hr.payment.primary": "Primary",
  "hr.payment.cashHint": "Paid at the cash desk",
  "hr.payment.empty.title": "No payment method",
  "hr.payment.empty.description": "Record how this employee is paid before the first payroll.",
  "hr.payment.dialog.createTitle": "New payment arrangement",
  "hr.payment.dialog.editTitle": "Edit the payment arrangement",
  "hr.payment.dialog.description": "The shares add up to 100 % and exactly one method is the primary one.",
  "hr.payment.field.validFrom": "Applies from",
  "hr.payment.field.method": "Method",
  "hr.payment.field.bankName": "Bank",
  "hr.payment.field.accountNo": "Account number (RIB)",
  "hr.payment.field.operator": "Operator",
  "hr.payment.field.mobileNumber": "Mobile number",
  "hr.payment.field.share": "Share (%)",
  "hr.payment.field.primary": "Primary",
  "hr.payment.addMethod": "Add a method",
  "hr.payment.removeMethod": "Remove",
  "hr.payment.total": "Total",
  "hr.payment.cashOnly": "Without the right to view sensitive HR data, only cash can be recorded.",
  "hr.payment.removeSet": "Remove this arrangement",
  "hr.payment.saved": "Payment arrangement saved",
  "hr.payment.error": "The payment arrangement could not be saved",
  "hr.documents.add": "Add a document",
  "hr.documents.column.kind": "Document",
  "hr.documents.column.title": "Title",
  "hr.documents.column.issued": "Issued",
  "hr.documents.column.expires": "Expires",
  "hr.documents.column.state": "State",
  "hr.documents.column.file": "File",
  "hr.documents.noExpiry": "No expiry",
  "hr.documents.empty.title": "No document",
  "hr.documents.empty.description": "Record the employee's papers and when they expire.",
  "hr.documents.dialog.createTitle": "Add a document",
  "hr.documents.dialog.editTitle": "Edit the document",
  "hr.documents.dialog.description": "There is no file storage yet: note where the scan is kept (a path or a link).",
  "hr.documents.field.fileRef": "Where the scan is kept",
  "hr.documents.saved": "Document saved",
  "hr.documents.error": "The document could not be saved",
```

Add to `fr`:

```ts
  "hr.payment.help": "Le net à payer est réparti entre les modes en vigueur le dernier jour du mois, selon leurs parts (100 % au total). Un nouveau mode à une date ultérieure remplace l'actuel à cette date.",
  "hr.payment.new": "Nouveau mode de paiement",
  "hr.payment.from": "À partir du",
  "hr.payment.inForce": "En vigueur",
  "hr.payment.primary": "Principal",
  "hr.payment.cashHint": "Payé en caisse",
  "hr.payment.empty.title": "Aucun mode de paiement",
  "hr.payment.empty.description": "Indiquez comment cet employé est payé avant la première paie.",
  "hr.payment.dialog.createTitle": "Nouveau mode de paiement",
  "hr.payment.dialog.editTitle": "Modifier le mode de paiement",
  "hr.payment.dialog.description": "Les parts totalisent 100 % et un seul mode est le principal.",
  "hr.payment.field.validFrom": "S'applique à partir du",
  "hr.payment.field.method": "Mode",
  "hr.payment.field.bankName": "Banque",
  "hr.payment.field.accountNo": "Numéro de compte (RIB)",
  "hr.payment.field.operator": "Opérateur",
  "hr.payment.field.mobileNumber": "Numéro de téléphone",
  "hr.payment.field.share": "Part (%)",
  "hr.payment.field.primary": "Principal",
  "hr.payment.addMethod": "Ajouter un mode",
  "hr.payment.removeMethod": "Retirer",
  "hr.payment.total": "Total",
  "hr.payment.cashOnly": "Sans le droit de voir les données RH sensibles, seules les espèces peuvent être saisies.",
  "hr.payment.removeSet": "Supprimer ce mode de paiement",
  "hr.payment.saved": "Mode de paiement enregistré",
  "hr.payment.error": "Le mode de paiement n'a pas pu être enregistré",
  "hr.documents.add": "Ajouter un document",
  "hr.documents.column.kind": "Document",
  "hr.documents.column.title": "Intitulé",
  "hr.documents.column.issued": "Délivré le",
  "hr.documents.column.expires": "Expire le",
  "hr.documents.column.state": "État",
  "hr.documents.column.file": "Fichier",
  "hr.documents.noExpiry": "Sans expiration",
  "hr.documents.empty.title": "Aucun document",
  "hr.documents.empty.description": "Enregistrez les pièces de l'employé et leur date d'expiration.",
  "hr.documents.dialog.createTitle": "Ajouter un document",
  "hr.documents.dialog.editTitle": "Modifier le document",
  "hr.documents.dialog.description": "Il n'y a pas encore de stockage de fichiers : indiquez où se trouve le scan (un chemin ou un lien).",
  "hr.documents.field.fileRef": "Emplacement du scan",
  "hr.documents.saved": "Document enregistré",
  "hr.documents.error": "Le document n'a pas pu être enregistré",
```

- [ ] **Step 3: Typecheck and look at it**

Run (from `frontend/`): `npx tsc -b --force`
Expected: exit 0.

Browser check: record a bank 70 % + Orange Money 30 % arrangement (total shows 100 %); try 70 + 20 — the server's French/English `PAYOUT_SPLIT_INVALID` toast appears; add a later arrangement and see "In force" stay on the current one. As a user without `hr.view_sensitive`: account and phone numbers show the lock; only cash is offered; "Edit" is hidden on a bank arrangement. Add a medical certificate expiring in 10 days with the document horizon set: it shows "Expiring soon" and appears in the list page's alerts; the state tabs filter it.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/hr/employee/PaymentTab.tsx frontend/src/features/hr/employee/DocumentsTab.tsx frontend/src/features/hr/employee/EmployeeFilePage.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(hr-ui): payment arrangements and documents tabs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Frontend — `/hr/organisation` (departments, positions, pay grid, settings)

**Files:**
- Create: `frontend/src/features/hr/organisation/OrganisationPage.tsx`, `DepartmentsTab.tsx`, `PositionsTab.tsx`, `GradesTab.tsx`, `HrSettingsTab.tsx`
- Modify: `frontend/src/routes/router.tsx`, `frontend/src/routes/Sidebar.tsx`, `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: `listDepartments/createDepartment/updateDepartment`, `listPositions/createPosition/updatePosition`, `listGrades/createGrade/updateGrade`, `getHrSettings/saveHrSettings`, `listEmployees`, `hrKeys`, `HrTable`, `FormField`, `formatXof`, `formatDate`, `emptyToNull`.
- Produces: route `/hr/organisation?tab=departments|positions|grades|settings`; nav entry "Organisation".
- Rights: tabs appear for `hr.view_departments` (departments), `hr.view_positions` (positions, grid), `hr.view_employees` (settings); create needs `hr.manage_*`, edit `hr.admin_*`, saving settings `hr.admin_employees`. Settings start empty and the form never pre-fills a number.

- [ ] **Step 1: Write the page and the tabs**

`frontend/src/features/hr/organisation/OrganisationPage.tsx`:

```tsx
import type { ComponentType } from "react";
import { useSearchParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Building2, Layers, Settings, Tag } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { StickyTabBar } from "../../../components/patterns/StickyTabBar";
import { Tabs, TabsList, TabsTrigger } from "../../../components/ui/tabs";
import { DepartmentsTab } from "./DepartmentsTab";
import { GradesTab } from "./GradesTab";
import { HrSettingsTab } from "./HrSettingsTab";
import { PositionsTab } from "./PositionsTab";

type TabValue = "departments" | "positions" | "grades" | "settings";
const TABS: { value: TabValue; labelKey: TranslationKey; icon: ComponentType<{ className?: string }>; permission: string; Component: ComponentType }[] = [
  { value: "departments", labelKey: "hr.org.tab.departments", icon: Building2, permission: "hr.view_departments", Component: DepartmentsTab },
  { value: "positions", labelKey: "hr.org.tab.positions", icon: Tag, permission: "hr.view_positions", Component: PositionsTab },
  { value: "grades", labelKey: "hr.org.tab.grades", icon: Layers, permission: "hr.view_positions", Component: GradesTab },
  { value: "settings", labelKey: "hr.org.tab.settings", icon: Settings, permission: "hr.view_employees", Component: HrSettingsTab },
];

export function OrganisationPage() {
  const { hasPermission } = useAuth();
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const tabs = TABS.filter((entry) => hasPermission(entry.permission));
  const active = tabs.find((entry) => entry.value === searchParams.get("tab")) ?? tabs[0];

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("hr.org.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("hr.org.subtitle")}</p>
      </motion.div>
      {!active ? (
        <EmptyState icon={<Building2 className="h-5 w-5" />} title={t("hr.org.noAccess.title")} description={t("hr.org.noAccess.description")} />
      ) : (
        <>
          <StickyTabBar>
            <Tabs value={active.value} onValueChange={(value) => setSearchParams({ tab: value }, { replace: true })}>
              <TabsList>
                {tabs.map((entry) => (
                  <TabsTrigger key={entry.value} value={entry.value} active={active.value === entry.value} layoutId="hr-organisation-tab">
                    <span className="flex items-center gap-1.5">
                      <entry.icon className="h-4 w-4" />
                      {t(entry.labelKey)}
                    </span>
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          </StickyTabBar>
          <AnimatePresence mode="wait">
            <motion.div key={active.value} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.2 }}>
              <active.Component />
            </motion.div>
          </AnimatePresence>
        </>
      )}
    </div>
  );
}
```

`frontend/src/features/hr/organisation/DepartmentsTab.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Pencil, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { createDepartment, hrKeys, listDepartments, listEmployees, updateDepartment, type Department, type DepartmentInput } from "../api";
import { FormField } from "../FormField";
import { HrTable } from "../HrTable";

export function DepartmentsTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const [dialog, setDialog] = useState<{ open: boolean; department: Department | null }>({ open: false, department: null });
  const { data: departments = [], isLoading } = useQuery({ queryKey: hrKeys.departments, queryFn: () => listDepartments(session!.token) });
  const filters = useColumnFilters<Department>([
    { key: "code", kind: "text", getValue: (row) => row.code },
    { key: "name", kind: "text", getValue: (row) => row.name },
    { key: "manager", kind: "text", getValue: (row) => row.manager_name },
    { key: "count", kind: "range", getValue: (row) => row.employee_count },
  ]);
  const text = (key: string, placeholder: string) => ({
    type: "text" as const,
    value: filters.text[key] ?? "",
    onChange: (value: string) => filters.setTextValue(key, value),
    placeholder,
  });
  const columns: ColumnDef<Department>[] = [
    { key: "code", header: t("hr.org.code"), defaultWidth: 120, cell: (row) => <span className="font-medium">{row.code}</span>, filterCell: text("code", t("hr.org.code")), sortValue: (row) => row.code },
    { key: "name", header: t("hr.org.name"), defaultWidth: 220, cell: (row) => row.name, filterCell: text("name", t("hr.org.name")), sortValue: (row) => row.name },
    { key: "manager", header: t("hr.org.manager"), defaultWidth: 200, cell: (row) => row.manager_name ?? "—", filterCell: text("manager", t("hr.org.manager")), sortValue: (row) => row.manager_name },
    {
      key: "count",
      header: t("hr.org.employees"),
      defaultWidth: 130,
      cell: (row) => row.employee_count,
      filterCell: {
        type: "range",
        min: filters.range.count?.min ?? "",
        max: filters.range.count?.max ?? "",
        onMinChange: (value) => filters.setRangeValue("count", "min", value),
        onMaxChange: (value) => filters.setRangeValue("count", "max", value),
      },
      sortValue: (row) => row.employee_count,
    },
    {
      key: "actions",
      header: "",
      defaultWidth: 100,
      alwaysVisible: true,
      cellClassName: "text-right",
      cell: (row) =>
        hasPermission("hr.admin_departments") ? (
          <Button size="sm" variant="ghost" onClick={() => setDialog({ open: true, department: row })}>
            <Pencil className="h-3.5 w-3.5" />
            {t("common.edit")}
          </Button>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3">
        <CardTitle className="text-base">{t("hr.org.tab.departments")}</CardTitle>
        {hasPermission("hr.manage_departments") && (
          <Button onClick={() => setDialog({ open: true, department: null })}>
            <Plus className="h-4 w-4" />
            {t("hr.org.department.new")}
          </Button>
        )}
      </CardHeader>
      <CardContent>
        <HrTable
          tableKey="hr.organisation.departments"
          columns={columns}
          rows={filters.apply(departments)}
          rowKey={(row) => row.id}
          isLoading={isLoading}
          loadingVariant="loader"
          empty={{ icon: <Building2 className="h-5 w-5" />, title: t("hr.org.department.empty.title"), description: t("hr.org.department.empty.description") }}
          filtersActive={filters.isActive}
          onClearFilters={filters.reset}
        />
      </CardContent>
      <DepartmentDialog open={dialog.open} department={dialog.department} onOpenChange={(open) => setDialog((current) => ({ ...current, open }))} />
    </Card>
  );
}

function DepartmentDialog({ open, department, onOpenChange }: { open: boolean; department: Department | null; onOpenChange: (open: boolean) => void }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ code: "", name: "", manager_employee_id: "" });
  const employees = useQuery({ queryKey: hrKeys.employees, queryFn: () => listEmployees(session!.token), enabled: open && hasPermission("hr.view_employees") });

  useEffect(() => {
    if (open) setForm({ code: department?.code ?? "", name: department?.name ?? "", manager_employee_id: department?.manager_employee_id ?? "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, department?.id]);

  const mutation = useMutation({
    mutationFn: () => {
      const input: DepartmentInput = { code: form.code.trim(), name: form.name.trim(), manager_employee_id: emptyOrNull(form.manager_employee_id) };
      return department ? updateDepartment(session!.token, department.id, input) : createDepartment(session!.token, input);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.departments });
      toast.success(t("hr.org.saved"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(t("hr.org.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(department ? "hr.org.department.editTitle" : "hr.org.department.createTitle")}</DialogTitle>
        </DialogHeader>
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
          <FormField id="department-code" label={t("hr.org.code")}>
            <Input id="department-code" required value={form.code} onChange={(event) => setForm({ ...form, code: event.target.value })} />
          </FormField>
          <FormField id="department-name" label={t("hr.org.name")}>
            <Input id="department-name" required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
          </FormField>
          <FormField id="department-manager" label={t("hr.org.manager")}>
            <Select id="department-manager" value={form.manager_employee_id} onChange={(event) => setForm({ ...form, manager_employee_id: event.target.value })}>
              <option value="">{t("hr.org.noManager")}</option>
              {(employees.data ?? []).filter((row) => row.status !== "terminated").map((row) => (
                <option key={row.id} value={row.id}>
                  {row.employee_no} — {row.full_name}
                </option>
              ))}
            </Select>
          </FormField>
          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            {mutation.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function emptyOrNull(value: string): string | null {
  return value === "" ? null : value;
}
```

`frontend/src/features/hr/organisation/PositionsTab.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Tag } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { createPosition, hrKeys, listDepartments, listPositions, updatePosition, type Position, type PositionInput } from "../api";
import { FormField } from "../FormField";
import { HrTable } from "../HrTable";

export function PositionsTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const [dialog, setDialog] = useState<{ open: boolean; position: Position | null }>({ open: false, position: null });
  const { data: positions = [], isLoading } = useQuery({ queryKey: hrKeys.positions, queryFn: () => listPositions(session!.token) });
  const filters = useColumnFilters<Position>([
    { key: "code", kind: "text", getValue: (row) => row.code },
    { key: "title", kind: "text", getValue: (row) => row.title },
    { key: "department", kind: "text", getValue: (row) => row.department_name },
    { key: "headcount", kind: "range", getValue: (row) => row.headcount },
  ]);
  const text = (key: string, placeholder: string) => ({
    type: "text" as const,
    value: filters.text[key] ?? "",
    onChange: (value: string) => filters.setTextValue(key, value),
    placeholder,
  });
  const columns: ColumnDef<Position>[] = [
    { key: "code", header: t("hr.org.code"), defaultWidth: 120, cell: (row) => <span className="font-medium">{row.code}</span>, filterCell: text("code", t("hr.org.code")), sortValue: (row) => row.code },
    { key: "title", header: t("hr.org.position.title"), defaultWidth: 240, cell: (row) => row.title, filterCell: text("title", t("hr.org.position.title")), sortValue: (row) => row.title },
    { key: "department", header: t("hr.field.department"), defaultWidth: 180, cell: (row) => row.department_name ?? "—", filterCell: text("department", t("hr.field.department")), sortValue: (row) => row.department_name },
    {
      key: "headcount",
      header: t("hr.org.position.headcount"),
      defaultWidth: 150,
      // The budget is a recorded figure; the cell states both numbers and judges nothing.
      cell: (row) => `${row.headcount}${row.headcount_budget !== null ? ` / ${row.headcount_budget}` : ""}`,
      filterCell: {
        type: "range",
        min: filters.range.headcount?.min ?? "",
        max: filters.range.headcount?.max ?? "",
        onMinChange: (value) => filters.setRangeValue("headcount", "min", value),
        onMaxChange: (value) => filters.setRangeValue("headcount", "max", value),
      },
      sortValue: (row) => row.headcount,
    },
    {
      key: "actions",
      header: "",
      defaultWidth: 100,
      alwaysVisible: true,
      cellClassName: "text-right",
      cell: (row) =>
        hasPermission("hr.admin_positions") ? (
          <Button size="sm" variant="ghost" onClick={() => setDialog({ open: true, position: row })}>
            <Pencil className="h-3.5 w-3.5" />
            {t("common.edit")}
          </Button>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3">
        <CardTitle className="text-base">{t("hr.org.tab.positions")}</CardTitle>
        {hasPermission("hr.manage_positions") && (
          <Button onClick={() => setDialog({ open: true, position: null })}>
            <Plus className="h-4 w-4" />
            {t("hr.org.position.new")}
          </Button>
        )}
      </CardHeader>
      <CardContent>
        <HrTable
          tableKey="hr.organisation.positions"
          columns={columns}
          rows={filters.apply(positions)}
          rowKey={(row) => row.id}
          isLoading={isLoading}
          loadingVariant="loader"
          empty={{ icon: <Tag className="h-5 w-5" />, title: t("hr.org.position.empty.title"), description: t("hr.org.position.empty.description") }}
          filtersActive={filters.isActive}
          onClearFilters={filters.reset}
        />
      </CardContent>
      <PositionDialog open={dialog.open} position={dialog.position} onOpenChange={(open) => setDialog((current) => ({ ...current, open }))} />
    </Card>
  );
}

function PositionDialog({ open, position, onOpenChange }: { open: boolean; position: Position | null; onOpenChange: (open: boolean) => void }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ code: "", title: "", department_id: "", headcount_budget: "" });
  const departments = useQuery({ queryKey: hrKeys.departments, queryFn: () => listDepartments(session!.token), enabled: open && hasPermission("hr.view_departments") });

  useEffect(() => {
    if (open)
      setForm({
        code: position?.code ?? "",
        title: position?.title ?? "",
        department_id: position?.department_id ?? "",
        headcount_budget: position?.headcount_budget == null ? "" : String(position.headcount_budget),
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, position?.id]);

  const mutation = useMutation({
    mutationFn: () => {
      const input: PositionInput = {
        code: form.code.trim(),
        title: form.title.trim(),
        department_id: form.department_id === "" ? null : form.department_id,
        headcount_budget: form.headcount_budget.trim() === "" ? null : Number(form.headcount_budget),
      };
      return position ? updatePosition(session!.token, position.id, input) : createPosition(session!.token, input);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.positions });
      toast.success(t("hr.org.saved"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(t("hr.org.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(position ? "hr.org.position.editTitle" : "hr.org.position.createTitle")}</DialogTitle>
        </DialogHeader>
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
          <div className="grid grid-cols-2 gap-3">
            <FormField id="position-code" label={t("hr.org.code")}>
              <Input id="position-code" required value={form.code} onChange={(event) => setForm({ ...form, code: event.target.value })} />
            </FormField>
            <FormField id="position-budget" label={t("hr.org.position.budget")}>
              <Input id="position-budget" type="number" min="0" step="1" value={form.headcount_budget} onChange={(event) => setForm({ ...form, headcount_budget: event.target.value })} />
            </FormField>
          </div>
          <FormField id="position-title" label={t("hr.org.position.title")}>
            <Input id="position-title" required value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} />
          </FormField>
          <FormField id="position-department" label={t("hr.field.department")}>
            <Select id="position-department" value={form.department_id} onChange={(event) => setForm({ ...form, department_id: event.target.value })}>
              <option value="">{t("hr.form.noneOption")}</option>
              {(departments.data ?? []).map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </Select>
          </FormField>
          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            {mutation.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

`frontend/src/features/hr/organisation/GradesTab.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Layers, Pencil, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { createGrade, hrKeys, listGrades, updateGrade, type Grade, type GradeInput } from "../api";
import { formatDate, formatXof, todayIso } from "../employeeFormat";
import { FormField } from "../FormField";
import { HrTable } from "../HrTable";

export function GradesTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const [dialog, setDialog] = useState<{ open: boolean; grade: Grade | null }>({ open: false, grade: null });
  const { data: grades = [], isLoading } = useQuery({ queryKey: hrKeys.grades, queryFn: () => listGrades(session!.token) });
  const filters = useColumnFilters<Grade>([
    { key: "code", kind: "text", getValue: (row) => row.code },
    { key: "category", kind: "text", getValue: (row) => row.category },
    { key: "echelon", kind: "text", getValue: (row) => row.echelon },
    { key: "minimum", kind: "range", getValue: (row) => row.base_salary },
  ]);
  const text = (key: string, placeholder: string) => ({
    type: "text" as const,
    value: filters.text[key] ?? "",
    onChange: (value: string) => filters.setTextValue(key, value),
    placeholder,
  });
  const columns: ColumnDef<Grade>[] = [
    { key: "code", header: t("hr.org.code"), defaultWidth: 110, cell: (row) => <span className="font-medium">{row.code}</span>, filterCell: text("code", t("hr.org.code")), sortValue: (row) => row.code },
    { key: "category", header: t("hr.org.grade.category"), defaultWidth: 200, cell: (row) => row.category, filterCell: text("category", t("hr.org.grade.category")), sortValue: (row) => row.category },
    { key: "echelon", header: t("hr.org.grade.echelon"), defaultWidth: 110, cell: (row) => row.echelon, filterCell: text("echelon", t("hr.org.grade.echelon")), sortValue: (row) => row.echelon },
    {
      key: "minimum",
      header: t("hr.org.grade.minimum"),
      defaultWidth: 180,
      cell: (row) => <span className="tabular-nums">{formatXof(row.base_salary)}</span>,
      filterCell: {
        type: "range",
        min: filters.range.minimum?.min ?? "",
        max: filters.range.minimum?.max ?? "",
        onMinChange: (value) => filters.setRangeValue("minimum", "min", value),
        onMaxChange: (value) => filters.setRangeValue("minimum", "max", value),
      },
      sortValue: (row) => row.base_salary,
    },
    { key: "valid_from", header: t("hr.org.grade.validFrom"), defaultWidth: 140, cell: (row) => formatDate(row.valid_from), sortValue: (row) => row.valid_from },
    {
      key: "actions",
      header: "",
      defaultWidth: 100,
      alwaysVisible: true,
      cellClassName: "text-right",
      cell: (row) =>
        hasPermission("hr.admin_positions") ? (
          <Button size="sm" variant="ghost" onClick={() => setDialog({ open: true, grade: row })}>
            <Pencil className="h-3.5 w-3.5" />
            {t("common.edit")}
          </Button>
        ) : null,
    },
  ];

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3">
        <CardTitle className="text-base">{t("hr.org.tab.grades")}</CardTitle>
        {hasPermission("hr.manage_positions") && (
          <Button onClick={() => setDialog({ open: true, grade: null })}>
            <Plus className="h-4 w-4" />
            {t("hr.org.grade.new")}
          </Button>
        )}
      </CardHeader>
      <CardContent>
        <HrTable
          tableKey="hr.organisation.grades"
          columns={columns}
          rows={filters.apply(grades)}
          rowKey={(row) => row.id}
          isLoading={isLoading}
          loadingVariant="loader"
          empty={{ icon: <Layers className="h-5 w-5" />, title: t("hr.org.grade.empty.title"), description: t("hr.org.grade.empty.description") }}
          filtersActive={filters.isActive}
          onClearFilters={filters.reset}
        />
      </CardContent>
      <GradeDialog open={dialog.open} grade={dialog.grade} onOpenChange={(open) => setDialog((current) => ({ ...current, open }))} />
    </Card>
  );
}

function GradeDialog({ open, grade, onOpenChange }: { open: boolean; grade: Grade | null; onOpenChange: (open: boolean) => void }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ code: "", category: "", echelon: "", base_salary: "", valid_from: todayIso() });

  useEffect(() => {
    if (open)
      setForm({
        code: grade?.code ?? "",
        category: grade?.category ?? "",
        echelon: grade?.echelon ?? "",
        base_salary: grade ? String(grade.base_salary) : "",
        valid_from: grade?.valid_from ?? todayIso(),
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, grade?.id]);

  const mutation = useMutation({
    mutationFn: () => {
      const input: GradeInput = {
        code: form.code.trim(),
        category: form.category.trim(),
        echelon: form.echelon.trim(),
        base_salary: Number(form.base_salary),
        valid_from: form.valid_from,
      };
      return grade ? updateGrade(session!.token, grade.id, input) : createGrade(session!.token, input);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.grades });
      toast.success(t("hr.org.saved"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(t("hr.org.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(grade ? "hr.org.grade.editTitle" : "hr.org.grade.createTitle")}</DialogTitle>
          <DialogDescription>{t("hr.org.grade.description")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
          <div className="grid grid-cols-2 gap-3">
            <FormField id="grade-code" label={t("hr.org.code")}>
              <Input id="grade-code" required value={form.code} onChange={(event) => setForm({ ...form, code: event.target.value })} />
            </FormField>
            <FormField id="grade-from" label={t("hr.org.grade.validFrom")}>
              <Input id="grade-from" type="date" required value={form.valid_from} onChange={(event) => setForm({ ...form, valid_from: event.target.value })} />
            </FormField>
            <FormField id="grade-category" label={t("hr.org.grade.category")}>
              <Input id="grade-category" required value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })} />
            </FormField>
            <FormField id="grade-echelon" label={t("hr.org.grade.echelon")}>
              <Input id="grade-echelon" required value={form.echelon} onChange={(event) => setForm({ ...form, echelon: event.target.value })} />
            </FormField>
          </div>
          <FormField id="grade-minimum" label={t("hr.org.grade.minimum")}>
            <Input id="grade-minimum" type="number" min="0" step="1" required value={form.base_salary} onChange={(event) => setForm({ ...form, base_salary: event.target.value })} />
          </FormField>
          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            {mutation.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

`frontend/src/features/hr/organisation/HrSettingsTab.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";
import { getHrSettings, hrKeys, saveHrSettings, type HrSettings } from "../api";
import { FormField } from "../FormField";

const FIELDS: { key: keyof HrSettings; labelKey: TranslationKey }[] = [
  { key: "contract_expiry_horizon_days", labelKey: "hr.settings.contractDays" },
  { key: "trial_end_horizon_days", labelKey: "hr.settings.trialDays" },
  { key: "document_expiry_horizon_days", labelKey: "hr.settings.documentDays" },
];

export function HrSettingsTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const canSave = hasPermission("hr.admin_employees");
  const { data, isLoading } = useQuery({ queryKey: hrKeys.settings, queryFn: () => getHrSettings(session!.token) });
  const [form, setForm] = useState<Record<keyof HrSettings, string>>({
    contract_expiry_horizon_days: "",
    trial_end_horizon_days: "",
    document_expiry_horizon_days: "",
  });

  useEffect(() => {
    if (!data) return;
    // Empty stays empty: an unset horizon is shown blank, never a suggested number.
    setForm({
      contract_expiry_horizon_days: data.contract_expiry_horizon_days == null ? "" : String(data.contract_expiry_horizon_days),
      trial_end_horizon_days: data.trial_end_horizon_days == null ? "" : String(data.trial_end_horizon_days),
      document_expiry_horizon_days: data.document_expiry_horizon_days == null ? "" : String(data.document_expiry_horizon_days),
    });
  }, [data]);

  const mutation = useMutation({
    mutationFn: () => {
      const value = (raw: string) => (raw.trim() === "" ? null : Number(raw));
      return saveHrSettings(session!.token, {
        contract_expiry_horizon_days: value(form.contract_expiry_horizon_days),
        trial_end_horizon_days: value(form.trial_end_horizon_days),
        document_expiry_horizon_days: value(form.document_expiry_horizon_days),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.settings });
      queryClient.invalidateQueries({ queryKey: hrKeys.alerts });
      queryClient.invalidateQueries({ queryKey: ["hr", "employees"] });
      toast.success(t("hr.settings.saved"));
    },
    onError: (error) => toast.error(t("hr.settings.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  if (isLoading) return <AppLoader className="min-h-[200px]" size={120} />;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("hr.settings.title")}</CardTitle>
        <p className="text-sm text-muted-foreground">{t("hr.settings.description")}</p>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); mutation.mutate(); }}>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {FIELDS.map((field) => (
              <FormField key={field.key} id={field.key} label={t(field.labelKey)}>
                <Input
                  id={field.key}
                  type="number"
                  min="1"
                  step="1"
                  readOnly={!canSave}
                  value={form[field.key]}
                  onChange={(event) => setForm({ ...form, [field.key]: event.target.value })}
                />
              </FormField>
            ))}
          </div>
          {canSave ? (
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? t("common.saving") : t("common.save")}
            </Button>
          ) : (
            <p className="text-xs text-muted-foreground">{t("hr.settings.readOnly")}</p>
          )}
        </form>
      </CardContent>
    </Card>
  );
}
```

(`["hr", "employees"]` is invalidated because the documents tab computes its states from the document horizon.)

- [ ] **Step 2: Route, nav and strings**

`router.tsx`: `import { OrganisationPage } from "../features/hr/organisation/OrganisationPage";` and `{ path: "/hr/organisation", element: <OrganisationPage /> },` after the `/hr/employees/:employeeId` route.

`Sidebar.tsx`: in the HR group, between the employees and legacy entries, add `{ to: "/hr/organisation", labelKey: "nav.hrOrganisation", icon: Building2 },` (`Building2` is already imported; the page itself shows only the tabs the user may read).

Add to `en`:

```ts
  "nav.hrOrganisation": "Organisation",
  "hr.org.title": "Organisation",
  "hr.org.subtitle": "Departments, positions, the pay grid and the HR settings.",
  "hr.org.tab.departments": "Departments",
  "hr.org.tab.positions": "Positions",
  "hr.org.tab.grades": "Pay grid",
  "hr.org.tab.settings": "Settings",
  "hr.org.noAccess.title": "Nothing to show",
  "hr.org.noAccess.description": "You have no right on the HR organisation.",
  "hr.org.code": "Code",
  "hr.org.name": "Name",
  "hr.org.manager": "Manager",
  "hr.org.employees": "Employees",
  "hr.org.noManager": "No manager",
  "hr.org.department.new": "New department",
  "hr.org.department.createTitle": "New department",
  "hr.org.department.editTitle": "Edit the department",
  "hr.org.department.empty.title": "No department",
  "hr.org.department.empty.description": "Create the company's departments.",
  "hr.org.position.new": "New position",
  "hr.org.position.title": "Title",
  "hr.org.position.headcount": "Headcount / budget",
  "hr.org.position.budget": "Budgeted headcount",
  "hr.org.position.createTitle": "New position",
  "hr.org.position.editTitle": "Edit the position",
  "hr.org.position.empty.title": "No position",
  "hr.org.position.empty.description": "Create the positions people hold.",
  "hr.org.grade.new": "New grade",
  "hr.org.grade.category": "Category",
  "hr.org.grade.echelon": "Echelon",
  "hr.org.grade.minimum": "Monthly minimum (F CFA)",
  "hr.org.grade.validFrom": "Valid from",
  "hr.org.grade.createTitle": "New grade",
  "hr.org.grade.editTitle": "Edit the grade",
  "hr.org.grade.description": "A revision of the collective agreement is a new row with the same code and a later date.",
  "hr.org.grade.empty.title": "No grade",
  "hr.org.grade.empty.description": "Record the collective-agreement grid.",
  "hr.org.saved": "Saved",
  "hr.org.error": "Could not save",
  "hr.settings.title": "Alert horizons",
  "hr.settings.description": "How many days ahead the employee list warns about contracts ending, trial periods ending and documents expiring. Leave a field empty to switch that list off.",
  "hr.settings.contractDays": "Contracts ending (days)",
  "hr.settings.trialDays": "Trial periods ending (days)",
  "hr.settings.documentDays": "Documents expiring (days)",
  "hr.settings.saved": "Settings saved",
  "hr.settings.error": "The settings could not be saved",
  "hr.settings.readOnly": "Only an HR administrator can change these.",
```

Add to `fr`:

```ts
  "nav.hrOrganisation": "Organisation",
  "hr.org.title": "Organisation",
  "hr.org.subtitle": "Départements, postes, grille salariale et paramètres RH.",
  "hr.org.tab.departments": "Départements",
  "hr.org.tab.positions": "Postes",
  "hr.org.tab.grades": "Grille salariale",
  "hr.org.tab.settings": "Paramètres",
  "hr.org.noAccess.title": "Rien à afficher",
  "hr.org.noAccess.description": "Vous n'avez aucun droit sur l'organisation RH.",
  "hr.org.code": "Code",
  "hr.org.name": "Nom",
  "hr.org.manager": "Responsable",
  "hr.org.employees": "Employés",
  "hr.org.noManager": "Aucun responsable",
  "hr.org.department.new": "Nouveau département",
  "hr.org.department.createTitle": "Nouveau département",
  "hr.org.department.editTitle": "Modifier le département",
  "hr.org.department.empty.title": "Aucun département",
  "hr.org.department.empty.description": "Créez les départements de l'entreprise.",
  "hr.org.position.new": "Nouveau poste",
  "hr.org.position.title": "Intitulé",
  "hr.org.position.headcount": "Effectif / budget",
  "hr.org.position.budget": "Effectif budgété",
  "hr.org.position.createTitle": "Nouveau poste",
  "hr.org.position.editTitle": "Modifier le poste",
  "hr.org.position.empty.title": "Aucun poste",
  "hr.org.position.empty.description": "Créez les postes occupés par le personnel.",
  "hr.org.grade.new": "Nouvelle catégorie",
  "hr.org.grade.category": "Catégorie",
  "hr.org.grade.echelon": "Échelon",
  "hr.org.grade.minimum": "Minimum mensuel (F CFA)",
  "hr.org.grade.validFrom": "Valable à partir du",
  "hr.org.grade.createTitle": "Nouvelle catégorie",
  "hr.org.grade.editTitle": "Modifier la catégorie",
  "hr.org.grade.description": "Une révision de la convention collective est une nouvelle ligne avec le même code et une date ultérieure.",
  "hr.org.grade.empty.title": "Aucune catégorie",
  "hr.org.grade.empty.description": "Saisissez la grille de la convention collective.",
  "hr.org.saved": "Enregistré",
  "hr.org.error": "Enregistrement impossible",
  "hr.settings.title": "Horizons d'alerte",
  "hr.settings.description": "Combien de jours à l'avance la liste des employés signale les fins de contrat, les fins de période d'essai et les documents qui expirent. Laissez un champ vide pour désactiver cette liste.",
  "hr.settings.contractDays": "Fins de contrat (jours)",
  "hr.settings.trialDays": "Fins de période d'essai (jours)",
  "hr.settings.documentDays": "Documents qui expirent (jours)",
  "hr.settings.saved": "Paramètres enregistrés",
  "hr.settings.error": "Les paramètres n'ont pas pu être enregistrés",
  "hr.settings.readOnly": "Seul un administrateur RH peut les modifier.",
```

- [ ] **Step 3: Typecheck and look at it**

Run (from `frontend/`): `npx tsc -b --force`
Expected: exit 0.

Browser check: `/hr/organisation` shows the tabs the user may read; create a department with a manager, a position with a budget ("0 / 3"), a grade; a duplicate code shows the `DUPLICATE_CODE` toast in the chosen language; the settings form starts empty, saving 30 / 15 / 30 makes the alerts card on `/hr/employees` list items, clearing a field switches its list off ("No horizon set").

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/hr/organisation frontend/src/routes/router.tsx frontend/src/routes/Sidebar.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(hr-ui): organisation page with departments, positions, pay grid and alert horizons

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Seed — 60 employees of a Malian pasta plant

**Files:**
- Create: `backend/scripts/seed_hr_payroll.py`
- Test: `backend/scripts/test_seed_hr_payroll.py` (plan shape, no DB), `backend/scripts/test_seed_hr_payroll_integration.py`

**Interfaces:**
- Consumes: every service of Tasks 2–8; `scripts.seed_common` (`TENANT = "demo"`, `actor_id`, `run`); `core.permissions_registry.ensure_default_roles`; `core.auth.hash_password`.
- Produces: `plans() -> list[Plan]` (deterministic, 60 entries, employee numbers `HRP-001`..`HRP-060`), `seed(conn, args) -> int`; runnable as `.venv/Scripts/python -m scripts.seed_hr_payroll [--dry-run]`, guarded by `if __name__ == "__main__":` (phase 5 assumption A11). Phases 2 and 3 extend this file (presence month, rule set, run).
- Idempotent: organisation rows are found by code, employees by employee number; an existing employee is skipped with everything under it. The alert horizons are written only while all three are empty.
- Every amount is demo data printed under a TO CONFIRM banner: grid minimums, allowances (`TRANSPORT`, `HOUSING`, the component codes phase 3 must seed), salaries. NINA/INPS/AMO numbers, phones and accounts are fake.

- [ ] **Step 1: Write the failing tests**

`backend/scripts/test_seed_hr_payroll.py`:

```python
"""The seed's plan is deterministic and every person in it is valid for the hr rules."""
from __future__ import annotations

import datetime

from scripts.seed_hr_payroll import TODAY, plans


def test_the_plan_is_sixty_distinct_people_and_the_same_every_run():
    first, second = plans(), plans()
    assert first == second
    assert len(first) == 60
    assert len({p.employee_no for p in first}) == 60
    assert len({p.badge_no for p in first}) == 60


def test_every_person_is_an_adult_when_hired_and_every_contract_holds_together():
    for plan in plans():
        assert plan.birth_date.replace(year=plan.birth_date.year + 18) <= plan.hire_date, plan.employee_no
        assert plan.contract_end is None or plan.contract_end >= plan.hire_date, plan.employee_no
        assert plan.trial_end is None or plan.hire_date <= plan.trial_end, plan.employee_no


def test_the_plan_exercises_the_alerts_amendments_and_exits():
    everyone = plans()
    horizon = TODAY + datetime.timedelta(days=30)
    assert sum(1 for p in everyone if p.contract_type == "cdd" and p.contract_end and TODAY <= p.contract_end <= horizon) >= 3
    assert sum(1 for p in everyone if p.trial_end and TODAY <= p.trial_end <= TODAY + datetime.timedelta(days=15)) >= 2
    assert {p.contract_type for p in everyone} == {"cdi", "cdd", "apprentice", "daily", "intern"}
    assert sum(1 for p in everyone if p.raise_from) == 5
    assert sum(1 for p in everyone if p.leaves_on) == 2
    assert {p.payment for p in everyone} == {"bank", "mobile", "cash", "split"}
```

`backend/scripts/test_seed_hr_payroll_integration.py`:

```python
"""The seed runs on the dev database (inside the rolled-back test transaction) and twice gives the same."""
from __future__ import annotations

import pytest

from scripts import seed_hr_payroll
from scripts.seed_common import ACTOR_EMAIL, TENANT


def _count(db) -> int:
    return db.execute("SELECT count(*) FROM hr.employees WHERE tenant_id = %s AND employee_no LIKE 'HRP-%%'", (TENANT,)).fetchone()[0]


def test_the_seed_creates_the_plant_once(db):
    if db.execute("SELECT 1 FROM core.users WHERE email = %s", (ACTOR_EMAIL,)).fetchone() is None:
        pytest.skip("the demo user is missing: run scripts.seed_dev first")
    seed_hr_payroll.seed(db, None)
    assert _count(db) == 60
    contracts = db.execute(
        "SELECT count(*) FROM hr.contracts c JOIN hr.employees e ON e.id = c.employee_id "
        "WHERE e.tenant_id = %s AND e.employee_no LIKE 'HRP-%%' AND c.status <> 'draft'",
        (TENANT,),
    ).fetchone()[0]
    assert contracts == 65  # 60 hires + 5 amendments
    seed_hr_payroll.seed(db, None)
    assert _count(db) == 60
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest scripts/test_seed_hr_payroll.py scripts/test_seed_hr_payroll_integration.py -q`
Expected: FAIL — `No module named 'scripts.seed_hr_payroll'`.

- [ ] **Step 3: Write the seed**

`backend/scripts/seed_hr_payroll.py`:

```python
"""Seeds the HR employee core for the demo tenant: departments, positions, the pay grid and 60
employees of a Malian pasta plant with contracts, amendments, dependants, payment methods,
documents, two exits and the alert horizons. Dev-only; idempotent (codes and employee numbers).

    .venv/Scripts/python -m scripts.seed_hr_payroll [--dry-run]

Every amount here (grid minimums, salaries, allowances) is DEMO data chosen for a realistic
spread, not the collective agreement: the client's HR and accountant replace them. The script
prints them under a TO CONFIRM banner. Phases 2 and 3 extend this file.
"""
from __future__ import annotations

import datetime
import random
from dataclasses import dataclass
from decimal import Decimal

from ulid import ULID

from core.auth import hash_password
from core.domain.result import Err
from core.permissions_registry import ensure_default_roles
from modules.hr.api.contract_service import ContractService
from modules.hr.api.dependant_service import DependantService
from modules.hr.api.document_service import DocumentService
from modules.hr.api.employee_service import EmployeeService
from modules.hr.api.organisation_service import DepartmentService, GradeService, PositionService
from modules.hr.api.payment_method_service import PaymentMethodService
from modules.hr.api.settings_service import HrSettingsService
from modules.hr.domain.contract import ContractComponent, ContractTerms
from modules.hr.domain.dependant import Dependant
from modules.hr.domain.document import EmployeeDocument
from modules.hr.domain.employee import EmployeeFile
from modules.hr.domain.payment import PaymentMethod
from scripts.seed_common import TENANT, actor_id, run

TODAY = datetime.date.today()
RNG_SEED = 20260925
GRID_FROM = datetime.date(2026, 1, 1)
RAISE_FROM = datetime.date(2026, 1, 1)
LAST_MONTH_END = TODAY.replace(day=1) - datetime.timedelta(days=1)
SELF_SERVICE_EMAIL = "employe.demo@sonalim-erp.local"
SELF_SERVICE_EMPLOYEE = "HRP-006"

DEPARTMENTS = [
    ("PROD", "Production"),
    ("CONDI", "Conditionnement"),
    ("MAINT", "Maintenance"),
    ("QUAL", "Qualité"),
    ("LOG", "Logistique et magasin"),
    ("ADM", "Administration et finance"),
    ("COM", "Commercial"),
]

# code, category, echelon, monthly minimum in F CFA (DEMO)
GRADES = [
    ("M1", "Manœuvre", "A", 45_000),
    ("M2", "Manœuvre", "B", 55_000),
    ("OS1", "Ouvrier spécialisé", "A", 70_000),
    ("OS2", "Ouvrier spécialisé", "B", 85_000),
    ("OQ1", "Ouvrier qualifié", "A", 110_000),
    ("AM1", "Agent de maîtrise", "A", 160_000),
    ("AM2", "Agent de maîtrise", "B", 210_000),
    ("CAD", "Cadre", "A", 380_000),
]

# code, title, department, grade, headcount budget, people seeded (sums to 60)
POSITIONS = [
    ("DIR-PROD", "Directeur de production", "PROD", "CAD", 1, 1),
    ("CHEF-EQ", "Chef d'équipe", "PROD", "AM1", 3, 3),
    ("OP-EXT", "Opérateur extrusion", "PROD", "OS2", 12, 12),
    ("OP-SECH", "Opérateur séchage", "PROD", "OS1", 4, 4),
    ("OP-COND", "Opérateur conditionnement", "CONDI", "OS1", 12, 11),
    ("CHEF-COND", "Chef de ligne conditionnement", "CONDI", "AM1", 1, 1),
    ("MANUT", "Manutentionnaire", "CONDI", "M2", 4, 2),
    ("MECA", "Mécanicien", "MAINT", "OQ1", 3, 3),
    ("ELEC", "Électricien", "MAINT", "OQ1", 2, 2),
    ("CHEF-MAINT", "Responsable maintenance", "MAINT", "AM2", 1, 1),
    ("LABO", "Technicien laboratoire", "QUAL", "OQ1", 3, 3),
    ("RESP-QUAL", "Responsable qualité", "QUAL", "AM2", 1, 1),
    ("MAG", "Magasinier", "LOG", "OS2", 2, 2),
    ("CARIST", "Cariste", "LOG", "OS1", 3, 3),
    ("CHAUF", "Chauffeur", "LOG", "OS1", 2, 2),
    ("COMPTA", "Comptable", "ADM", "AM2", 2, 2),
    ("ASS-RH", "Assistante RH", "ADM", "AM1", 1, 1),
    ("GARD", "Gardien", "ADM", "M1", 2, 2),
    ("COMM", "Commercial", "COM", "AM1", 3, 3),
    ("RESP-COM", "Responsable commercial", "COM", "CAD", 1, 1),
]

# Who gets which contract, by employee number (1-based, in POSITIONS order).
DAILY = {25, 30, 33, 34}             # two conditionnement operators and the two handlers
APPRENTICES = {37, 39}               # one mechanic, one electrician
INTERNS = {43, 53}                   # one lab technician, one accountant
CDD_ENDS_IN_DAYS = {7: 6, 12: 12, 19: 19, 23: 26, 28: 45, 46: 80, 49: 120, 57: 200}  # four inside a 30-day horizon
RECENT_HIRES_TRIAL_DAYS = {15: 4, 27: 11, 48: 25}                                       # two inside a 15-day horizon
RAISED = {2, 10, 18, 26, 36}         # CDI amended from RAISE_FROM with +10 000 F CFA
LEAVERS = {58: "resignation", 59: "dismissal"}

TRANSPORT = 15_000                   # DEMO allowance, every monthly contract
HOUSING = 50_000                     # DEMO allowance, grades below
HOUSING_GRADES = ("AM2", "CAD")

MALE = ["Moussa", "Mamadou", "Ibrahim", "Seydou", "Oumar", "Abdoulaye", "Boubacar", "Adama", "Souleymane", "Bakary",
        "Modibo", "Cheick", "Lassana", "Drissa", "Yacouba", "Sékou", "Amadou", "Issa", "Hamidou", "Siaka"]
FEMALE = ["Aminata", "Fatoumata", "Mariam", "Kadiatou", "Awa", "Oumou", "Hawa", "Assétou", "Djénéba", "Rokia",
          "Salimata", "Bintou", "Nana", "Korotoumou"]
LAST = ["Traoré", "Coulibaly", "Diarra", "Keïta", "Konaté", "Sangaré", "Diallo", "Touré", "Cissé", "Sidibé",
        "Dembélé", "Koné", "Sissoko", "Doumbia", "Maïga", "Kanté", "Camara", "Samaké", "Bagayoko", "Dicko"]
BANKS = ["BDM-SA", "BNDA", "Ecobank Mali", "Orabank Mali", "BOA Mali"]
PLACES = ["Bamako", "Ségou", "Sikasso", "Kayes", "Mopti", "Koulikoro", "Kati", "San"]


@dataclass(frozen=True)
class Plan:
    number: int
    employee_no: str
    badge_no: str
    first_name: str
    last_name: str
    gender: str
    birth_date: datetime.date
    birth_place: str
    married: bool
    children: tuple[datetime.date, ...]
    phone: str
    department: str
    position: str
    grade: str
    site: str
    contract_type: str
    pay_frequency: str
    hire_date: datetime.date
    contract_end: datetime.date | None
    trial_end: datetime.date | None
    base_salary: int
    payment: str  # bank / mobile / cash / split
    raise_from: datetime.date | None
    leaves_on: datetime.date | None


def _day(rng: random.Random, year: int) -> datetime.date:
    return datetime.date(year, rng.randint(1, 12), rng.randint(1, 28))


def plans() -> list[Plan]:
    """The same 60 people on every run (fixed random seed)."""
    rng = random.Random(RNG_SEED)
    result: list[Plan] = []
    number = 0
    for code, _title, department, grade, _budget, count in POSITIONS:
        minimum = next(m for g, _c, _e, m in GRADES if g == grade)
        for _ in range(count):
            number += 1
            female = rng.random() < (0.55 if department == "CONDI" else 0.2)
            age = rng.randint(22, 55)
            birth = _day(rng, TODAY.year - age)
            married = age >= 28 and rng.random() < 0.7
            contract_type, frequency, end, trial = "cdi", "monthly", None, None
            hire = _day(rng, rng.randint(max(2012, birth.year + 19), 2024))
            salary = minimum + rng.randint(0, 8) * 5_000
            if number in DAILY:
                contract_type, frequency = "daily", "daily"
                hire = _day(rng, rng.randint(max(2024, birth.year + 19), 2025))
                salary = 3_000 + rng.randint(0, 6) * 250  # F CFA per day (DEMO)
            elif number in APPRENTICES:
                contract_type, hire = "apprentice", TODAY - datetime.timedelta(days=200)
                end, salary = hire + datetime.timedelta(days=730), 50_000
            elif number in INTERNS:
                contract_type, hire = "intern", TODAY - datetime.timedelta(days=40)
                end, salary = hire + datetime.timedelta(days=182), 40_000
            elif number in CDD_ENDS_IN_DAYS:
                contract_type = "cdd"
                hire = TODAY - datetime.timedelta(days=rng.randint(200, 330))
                end = TODAY + datetime.timedelta(days=CDD_ENDS_IN_DAYS[number])
            elif number in RECENT_HIRES_TRIAL_DAYS:
                hire = TODAY - datetime.timedelta(days=45)
                trial = TODAY + datetime.timedelta(days=RECENT_HIRES_TRIAL_DAYS[number])
            children = tuple(
                _day(rng, rng.randint(max(birth.year + 22, 2000), min(TODAY.year - 1, birth.year + 45)))
                for _ in range(rng.choice([0, 1, 2, 2, 3, 3, 4]) if married else rng.choice([0, 0, 1]))
            ) if birth.year + 22 <= TODAY.year - 1 else ()
            if number in DAILY:
                payment = "cash" if number % 2 == 0 else "mobile"
            elif number % 10 == 0:
                payment = "cash"
            elif number % 10 in (3, 7):
                payment = "mobile"
            elif number % 10 == 5:
                payment = "split"
            else:
                payment = "bank"
            result.append(
                Plan(
                    number=number,
                    employee_no=f"HRP-{number:03d}",
                    badge_no=f"B{number:04d}",
                    first_name=rng.choice(FEMALE if female else MALE),
                    last_name=rng.choice(LAST),
                    gender="female" if female else "male",
                    birth_date=birth,
                    birth_place=rng.choice(PLACES),
                    married=married,
                    children=children,
                    phone=f"{rng.choice(['76', '77', '78', '79', '66', '65', '90', '91'])} {rng.randint(10, 99)} {rng.randint(10, 99)} {rng.randint(10, 99)}",
                    department=department,
                    position=code,
                    grade=grade,
                    site="Siège" if department in ("ADM", "COM") else "Usine",
                    contract_type=contract_type,
                    pay_frequency=frequency,
                    hire_date=hire,
                    contract_end=end,
                    trial_end=trial,
                    base_salary=salary,
                    payment=payment,
                    raise_from=RAISE_FROM if number in RAISED and hire < RAISE_FROM else None,
                    leaves_on=LAST_MONTH_END if number in LEAVERS and hire < LAST_MONTH_END else None,
                )
            )
    return result


def _ok(result):
    if isinstance(result, Err):
        raise RuntimeError(f"{result.code}: {result.message}")
    return result.value


def _fcfa(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " F CFA"


def _ensure_organisation(conn, actor: str) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    departments: dict[str, str] = {}
    for code, name in DEPARTMENTS:
        row = conn.execute("SELECT id FROM hr.departments WHERE tenant_id = %s AND code = %s", (TENANT, code)).fetchone()
        departments[code] = row[0] if row else _ok(DepartmentService(conn).create_department(tenant_id=TENANT, actor_id=actor, code=code, name=name))["id"]
    grades: dict[str, str] = {}
    for code, category, echelon, minimum in GRADES:
        row = conn.execute("SELECT id FROM hr.grades WHERE tenant_id = %s AND code = %s AND valid_from = %s", (TENANT, code, GRID_FROM)).fetchone()
        grades[code] = row[0] if row else _ok(
            GradeService(conn).create_grade(
                tenant_id=TENANT, actor_id=actor, code=code, category=category, echelon=echelon, base_salary=Decimal(minimum), valid_from=GRID_FROM
            )
        )["id"]
    positions: dict[str, str] = {}
    for code, title, department, _grade, budget, _count in POSITIONS:
        row = conn.execute("SELECT id FROM hr.positions WHERE tenant_id = %s AND code = %s", (TENANT, code)).fetchone()
        positions[code] = row[0] if row else _ok(
            PositionService(conn).create_position(
                tenant_id=TENANT, actor_id=actor, code=code, title=title, department_id=departments[department], headcount_budget=budget
            )
        )["id"]
    return departments, grades, positions


def _ensure_self_service_user(conn) -> str:
    conn.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash, full_name) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (email) DO NOTHING",
        (str(ULID()), TENANT, SELF_SERVICE_EMAIL, hash_password("demo1234"), "Employé démo"),
    )
    user_id = conn.execute("SELECT id FROM core.users WHERE email = %s", (SELF_SERVICE_EMAIL,)).fetchone()[0]
    conn.execute(
        "INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, 'hr.self_service') ON CONFLICT DO NOTHING", (user_id,)
    )
    return user_id


def _payment_methods(plan: Plan, rng: random.Random) -> list[PaymentMethod]:
    bank = PaymentMethod(
        method="bank", share_percent=Decimal("100"), is_primary=True, bank_name=rng.choice(BANKS),
        account_no=f"ML{rng.randint(10, 99)} {rng.randint(10000, 99999)} {rng.randint(10**11, 10**12 - 1)} {rng.randint(10, 99)}",
    )
    mobile = PaymentMethod(
        method="mobile_money", share_percent=Decimal("100"), is_primary=True,
        mobile_operator="orange_money" if plan.number % 3 else "moov_money", mobile_number=plan.phone,
    )
    if plan.payment == "cash":
        return [PaymentMethod(method="cash", share_percent=Decimal("100"), is_primary=True)]
    if plan.payment == "mobile":
        return [mobile]
    if plan.payment == "split":
        return [
            PaymentMethod(**{**bank.__dict__, "share_percent": Decimal("70")}),
            PaymentMethod(**{**mobile.__dict__, "share_percent": Decimal("30"), "is_primary": False}),
        ]
    return [bank]


def _create(conn, actor: str, plan: Plan, departments, grades, positions, self_service_user: str | None) -> None:
    rng = random.Random(f"{RNG_SEED}-{plan.employee_no}")
    employee = _ok(
        EmployeeService(conn).create_employee(
            tenant_id=TENANT,
            actor_id=actor,
            employee=EmployeeFile(
                employee_no=plan.employee_no, first_name=plan.first_name, last_name=plan.last_name, hire_date=plan.hire_date,
                phone=plan.phone, department_id=departments[plan.department], position_id=positions[plan.position],
                grade_id=grades[plan.grade], user_id=self_service_user, gender=plan.gender, birth_date=plan.birth_date,
                birth_place=plan.birth_place, nationality="Malienne", national_id=f"NINA-DEMO-{plan.number:04d}{rng.randint(1000, 9999)}",
                inps_no=f"INPS-DEMO-{rng.randint(100000, 999999)}", amo_no=f"AMO-DEMO-{rng.randint(100000, 999999)}",
                marital_status="married" if plan.married else "single", address=f"{plan.birth_place if plan.site == 'Siège' else 'Bamako'}",
                emergency_contact=f"{rng.choice(MALE + FEMALE)} {plan.last_name}", badge_no=plan.badge_no, site=plan.site,
            ),
        )
    )
    components: tuple[ContractComponent, ...] = ()
    if plan.pay_frequency == "monthly":
        components = (ContractComponent(component_code="TRANSPORT", amount=Decimal(TRANSPORT)),)
        if plan.grade in HOUSING_GRADES:
            components += (ContractComponent(component_code="HOUSING", amount=Decimal(HOUSING)),)
    contract = _ok(
        ContractService(conn).create_contract(
            tenant_id=TENANT,
            actor_id=actor,
            terms=ContractTerms(
                employee_id=employee["id"], contract_type=plan.contract_type, start_date=plan.hire_date,
                base_salary=Decimal(plan.base_salary), end_date=plan.contract_end, trial_end_date=plan.trial_end,
                pay_frequency=plan.pay_frequency, position_id=positions[plan.position], grade_id=grades[plan.grade],
                components=components,
            ),
        )
    )
    if plan.raise_from:
        _ok(
            ContractService(conn).amend_contract(
                tenant_id=TENANT, actor_id=actor, contract_id=contract["id"], effective_date=plan.raise_from,
                changes={"base_salary": Decimal(plan.base_salary + 10_000)},
            )
        )
    dependants = DependantService(conn)
    if plan.married:
        spouse_birth = plan.birth_date + datetime.timedelta(days=rng.randint(-1500, 1500))
        _ok(
            dependants.create_dependant(
                tenant_id=TENANT, actor_id=actor, employee_id=employee["id"],
                dependant=Dependant(
                    kind="spouse", name=f"{rng.choice(MALE if plan.gender == 'female' else FEMALE)} {rng.choice(LAST)}",
                    birth_date=spouse_birth, valid_from=max(spouse_birth, plan.birth_date).replace(year=max(spouse_birth, plan.birth_date).year + 25),
                    dependent_for_tax=plan.gender == "male",
                ),
            )
        )
    for child_birth in plan.children:
        _ok(
            dependants.create_dependant(
                tenant_id=TENANT, actor_id=actor, employee_id=employee["id"],
                dependant=Dependant(
                    kind="child", name=f"{rng.choice(MALE + FEMALE)} {plan.last_name}", birth_date=child_birth, valid_from=child_birth,
                    dependent_for_tax=True, valid_to=child_birth.replace(year=child_birth.year + 21) - datetime.timedelta(days=1),
                ),
            )
        )
    _ok(
        PaymentMethodService(conn).replace_set(
            tenant_id=TENANT, actor_id=actor, employee_id=employee["id"], valid_from=plan.hire_date, methods=_payment_methods(plan, rng)
        )
    )
    documents = DocumentService(conn)
    issued = plan.hire_date - datetime.timedelta(days=30)
    _ok(
        documents.create_document(
            tenant_id=TENANT, actor_id=actor, employee_id=employee["id"],
            document=EmployeeDocument(kind="id_card", issued_on=issued, expires_on=issued + datetime.timedelta(days=3650),
                                      file_ref=f"\\\\srv-rh\\dossiers\\{plan.employee_no}\\nina.pdf"),
        )
    )
    if plan.department in ("PROD", "CONDI", "QUAL"):
        medical = TODAY - datetime.timedelta(days=rng.randint(20, 420))  # some expired, some expiring (DEMO)
        _ok(
            documents.create_document(
                tenant_id=TENANT, actor_id=actor, employee_id=employee["id"],
                document=EmployeeDocument(kind="medical_certificate", issued_on=medical, expires_on=medical + datetime.timedelta(days=365)),
            )
        )
    if plan.position in ("CHAUF", "CARIST"):
        _ok(
            documents.create_document(
                tenant_id=TENANT, actor_id=actor, employee_id=employee["id"],
                document=EmployeeDocument(kind="driving_licence", issued_on=datetime.date(2020, 6, 1),
                                          expires_on=TODAY + datetime.timedelta(days=rng.choice([10, 200, 400, 700]))),
            )
        )
    if plan.leaves_on:
        _ok(
            EmployeeService(conn).terminate_employee(
                tenant_id=TENANT, actor_id=actor, employee_id=employee["id"], termination_date=plan.leaves_on,
                termination_reason=LEAVERS[plan.number],
            )
        )


def _print_to_confirm() -> None:
    print("\n=========== TO CONFIRM: demo values, not the collective agreement ===========")
    for code, category, echelon, minimum in GRADES:
        print(f"  grade {code:<4} {category} {echelon}: monthly minimum {_fcfa(minimum)} (from {GRID_FROM.isoformat()})")
    print(f"  allowance TRANSPORT: {_fcfa(TRANSPORT)} / month on every monthly contract")
    print(f"  allowance HOUSING:   {_fcfa(HOUSING)} / month for grades {', '.join(HOUSING_GRADES)}")
    print("  salaries: grade minimum + 0 to 40 000 F CFA; day labourers 3 000 to 4 500 F CFA / day;")
    print("            interns 40 000, apprentices 50 000; five raises of 10 000 from " + RAISE_FROM.isoformat())
    print("  alert horizons: contracts 30 days, trials 15 days (spec); documents 30 days (demo)")
    print("  NINA / INPS / AMO numbers, phones and bank accounts are fake.")
    print("=============================================================================")


def seed(conn, _args) -> int:
    actor = actor_id(conn)
    ensure_default_roles(conn, TENANT)  # the administrateur role picks up the new hr.* codes
    departments, grades, positions = _ensure_organisation(conn, actor)
    settings = HrSettingsService(conn)
    if all(value is None for value in settings.get(TENANT).values()):
        _ok(settings.save(tenant_id=TENANT, actor_id=actor, contract_expiry_horizon_days=30, trial_end_horizon_days=15, document_expiry_horizon_days=30))
    self_service_user = _ensure_self_service_user(conn)
    created = skipped = 0
    for plan in plans():
        if conn.execute("SELECT 1 FROM hr.employees WHERE tenant_id = %s AND employee_no = %s", (TENANT, plan.employee_no)).fetchone():
            skipped += 1
            continue
        linked = self_service_user if plan.employee_no == SELF_SERVICE_EMPLOYEE else None
        _create(conn, actor, plan, departments, grades, positions, linked)
        created += 1
    print(f"hr seed: {created} employee(s) created, {skipped} already there; {len(DEPARTMENTS)} departments, {len(POSITIONS)} positions, {len(GRADES)} grades")
    print(f"self-service login: {SELF_SERVICE_EMAIL} / demo1234 -> {SELF_SERVICE_EMPLOYEE}")
    _print_to_confirm()
    return 0


if __name__ == "__main__":
    raise SystemExit(run(__doc__, seed))
```

Notes for the implementer:
- `PaymentMethod(**{**bank.__dict__, ...})` copies a frozen dataclass with changed fields; `dataclasses.replace(bank, share_percent=Decimal("70"))` is equivalent and may be preferred.
- A spouse's `valid_from` is the later of the two birthdays plus 25 years (a stand-in wedding date), always after both births; if it lands after `TODAY` the spouse simply does not count yet, which is valid data.
- Children are only drawn when the parent is old enough (born at least 22 years before last year); `valid_to` is the day before their 21st birthday (demo modelling of "child dependant", to be confirmed with the accountant).

- [ ] **Step 4: Run the tests, then the seed**

Run: `.venv/Scripts/python -m pytest scripts/test_seed_hr_payroll.py scripts/test_seed_hr_payroll_integration.py -q`
Expected: PASS (the integration test counted as passed).

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m scripts.seed_hr_payroll`
Expected: `hr seed: 60 employee(s) created, 0 already there; ...` then the TO CONFIRM banner. Run it again: `0 employee(s) created, 60 already there`.

- [ ] **Step 5: Run the whole backend suite once**

Run: `.venv/Scripts/python -m pytest modules/hr core scripts -q`
Expected: PASS, with the hr integration tests counted as passed.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/seed_hr_payroll.py backend/scripts/test_seed_hr_payroll.py backend/scripts/test_seed_hr_payroll_integration.py
git commit -m "chore(hr): seed 60 employees of a Malian plant with contracts, family, payment and documents

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (done while writing)

**Spec coverage (Phase 1):**

| Spec item | Task |
|---|---|
| `hr.employees` gains user_id, gender, birth date/place, nationality, NINA, INPS, AMO, marital status, address, emergency contact, badge (unique), position, grade, site, termination date/reason; status `'terminated'` | 2 (position/grade), 3, 7 |
| `hr.dependants` + tax-dependant count on the pay date | 4, 9 |
| `hr.payment_methods` bank / mobile money / cash with shares, primary, valid_from | 4 |
| `hr.positions`, `hr.grades` | 2 |
| Contract types, trial end, weekly hours (40), base_salary, pay frequency, position, grade, amendments, end reason, XOF default, one active contract per date (domain + exclusion) | 5, 6 |
| `hr.contract_components` | 5 |
| `hr.employee_documents` with expiry (path/URL, no file storage exists) | 8 |
| Contract-expiry and trial-end alerts, horizons in `hr.settings` | 8, 10, 14 |
| Terminate: reason + date, closes the active contract, flags the final settlement (date/reason in the snapshot) | 7, 9 |
| Screens: Employees list, employee file with tabs identity/family/contracts/payment/documents/leave/payslips, Organisation | 10–14 |
| Permissions incl. `hr.view_sensitive`, `hr.self_service`, presence codes, positions codes | 1 |
| Hidden salary / national id / bank details without `hr.view_sensitive` | 1, 3, 4, 5, 10–13 |
| `PayrollSnapshotService`, `EmployeeService.get_by_user` per contract | 9, 3 |
| Errors `CONTRACT_OVERLAP`, `BADGE_TAKEN`, `PAYOUT_SPLIT_INVALID` (bilingual) | 3, 4, 5 |
| Seed ~60 Mali employees | 15 |

**Placeholder scan:** every code step carries the full code; the only "to confirm" items are client data (grid, allowances), printed by the seed as the spec requires.

**Type consistency:** `EmployeeFile` field order = `FIELDS` = column list; `ContractTerms` order = `COLUMNS`; `Dependant`/`EmployeeDocument` orders = their `_COLUMNS`; settings keys `contract_expiry_horizon_days / trial_end_horizon_days / document_expiry_horizon_days` are the same in migration 0009, `alerts.HORIZON_KEYS`, the services, the routes, `api.ts` and phase 5's A5; `hrKeys` names are the ones every frontend task uses; `ContractDialogMode` is exported from `ContractFormDialog.tsx` and imported by `ContractsTab.tsx`.

**Review Focus coverage:** masked-field edits → Task 1 `test_access_integration`, Task 3 `test_an_edit_without_the_right_cannot_touch_hidden_fields_but_edits_the_rest`, Task 4 `test_bank_details_need_hr_view_sensitive_to_write_and_to_read`, Task 5 `test_an_admin_without_the_right_can_fix_hours_but_not_pay`, dirty-fields-only dialogs in Tasks 10–12; legacy contracts → Task 6 `test_the_migration_closes_legacy_overlaps_then_holds` (+ the type mapping in 0006); three-decimal shares → Task 4 `test_a_share_has_at_most_two_decimals`; renewed CDD / replaced document / leaver → Task 8 alert tests; mid-month amendment / exit / draft → Task 9 snapshot tests.
