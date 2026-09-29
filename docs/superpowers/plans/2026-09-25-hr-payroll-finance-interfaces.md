# HR / Payroll / Finance — cross-phase interface contract

Spec: `docs/superpowers/specs/2026-09-25-hr-payroll-finance-design.md`.
Five plans (phase 1..5) are written in parallel; every plan MUST use exactly these names and
shapes where phases meet. Anything not listed here is private to its phase.

## Plan files

- Phase 1: `docs/superpowers/plans/2026-09-25-hr-p1-employee-core.md`
- Phase 2: `docs/superpowers/plans/2026-09-25-hr-p2-presence-leave.md`
- Phase 3: `docs/superpowers/plans/2026-09-25-hr-p3-payroll.md`
- Phase 4: `docs/superpowers/plans/2026-09-25-hr-p4-finance-ledger.md`
- Phase 5: `docs/superpowers/plans/2026-09-25-hr-p5-analytics-self-service.md`

Order of execution: 1 → 2 → 3 → 4 → 5. A later plan may assume every earlier plan is merged.

## Migration numbers

- `hr`: phase 1 uses `0003_*`..`0009_*`, phase 2 uses `0010_*`..`0019_*`, phase 5 uses `0020_*`+.
- `payroll` (new module, `backend/modules/payroll/`): phase 3 uses `0001_*`+.
- `finance`: phase 4 uses `0002_*`+.
- Phase 3 adds `"payroll"` to `MODULE_ORDER` in `backend/core/migrations/runner.py` right after
  `"hr"` and registers its migrations dir the same way the others are; it also includes the
  payroll router in `backend/app/main.py`.

## Money and dates

- Money columns `NUMERIC(18,0)`, XOF; Python side uses `decimal.Decimal`, never float.
- A "period" is a `datetime.date` equal to the first day of the month.

## Phase 1 → Phase 3 (hr api, `backend/modules/hr/api/payroll_snapshot_service.py`)

```python
class PayrollSnapshotService:
    def __init__(self, connection: psycopg.Connection) -> None: ...
    def employees_for_period(self, *, tenant_id: str, period: datetime.date,
                             employee_ids: list[str] | None = None) -> list[dict]:
        """Employees with an active contract on any day of the period."""
```
Each dict:
```
employee_id, employee_no, full_name, department_id, position_id, grade_id,
hire_date (date), termination_date (date|None), termination_reason (str|None),
inps_no (str|None), amo_no (str|None),
tax_dependants (int, dependants with dependent_for_tax valid on the last day of the period),
contract: {id, contract_type, base_salary: Decimal, weekly_hours: Decimal,
           pay_frequency: 'monthly'|'daily', start_date, end_date|None,
           components: [{component_code: str, amount: Decimal|None, rate: Decimal|None}]},
payment_methods: [{method: 'bank'|'mobile_money'|'cash', bank_name, account_no,
                   mobile_operator, mobile_number, share_percent: Decimal, is_primary: bool}]
```

Phase 1 also owns `hr.employees.user_id` and
`EmployeeService.get_by_user(*, tenant_id, user_id) -> dict | None` (used by phase 5).

## Phase 2 → Phase 3 (hr api, `backend/modules/hr/api/presence_service.py`)

```python
class PresenceService:
    def month_summary(self, *, tenant_id: str, period: datetime.date,
                      employee_ids: list[str] | None = None) -> list[dict]: ...
    def is_month_closed(self, *, tenant_id: str, period: datetime.date) -> bool: ...
```
`month_summary` dict: `employee_id, scheduled_days, worked_days, unpaid_absence_days,
paid_leave_days, sick_days, holiday_days, holidays_worked_days, ot_minutes_day,
ot_minutes_night, ot_minutes_rest_holiday, night_minutes, late_minutes` (all int).
Overtime bands stored in presence: `day`, `night`, `rest_holiday` — phase 3 maps them to
rate multipliers through `payroll.overtime_rates.band_code` with the same three codes.
Event published by phase 2 on close: `hr.presence_month.closed` payload `{period}`.

## Phase 3 → Phase 4 (payroll api, `backend/modules/payroll/api/posting_service.py`)

```python
class PayrollPostingService:
    def posting_lines(self, *, tenant_id: str, run_id: str) -> list[dict]: ...
    def payment_lines(self, *, tenant_id: str, run_id: str) -> list[dict]: ...
```
`posting_lines` dict: `source_kind` in `'earning'|'deduction'|'employee_contribution'|
'employer_contribution'|'employer_charge'|'tax'|'net'`, `code` (component/contribution/tax code,
`'NET'` for net), `amount: Decimal` (positive), `employee_id`.
`payment_lines` dict: `method` in `'bank'|'mobile_money'|'cash'`, `amount: Decimal`,
`employee_id`.

Events (payload thin, add to `backend/events/CATALOG.md`):
- `payroll.run.approved` `{run_id, period, run_type}`
- `payroll.run.paid` `{run_id, period}`
- `payroll.run.reversed` `{run_id, period}`

Phase 4 posting-rule keys = `(source='payroll', source_kind, code)`, with a fallback row where
`code='*'` for each source_kind.

## Phase 4 publishes

`finance.journal_entry.posted` `{entry_id, journal_code, source_module, source_id}`.
Phase 4 exposes `LedgerQueryService.entries_for_source(*, tenant_id, source_module, source_id)
-> list[dict]` so the payroll run page can show "posted / not posted".

## Phase 5 consumes

- `PayrollSnapshotService`, `PresenceService.month_summary`, `EmployeeService.get_by_user`.
- `payroll/api/report_service.py` (created in phase 3):
  `PayrollReportService.cost_by_department(*, tenant_id, period_from, period_to) -> list[dict]`
  dict: `period, department_id, headcount, gross, employer_cost` and
  `PayrollReportService.payslips_for_employee(*, tenant_id, employee_id) -> list[dict]`.

## Permission codes

Exactly as listed in the spec section "Permissions". Phase 5 adds only `hr.self_service` usage
(declared in phase 1's `module.json` change).

## Frontend

- Feature folders: `frontend/src/features/hr/` (phases 1, 2, 5), `frontend/src/features/payroll/`
  (phase 3), `frontend/src/features/finance/` (phase 4).
- Routes: `/hr/employees`, `/hr/employees/:id`, `/hr/organisation`, `/hr/presence`,
  `/hr/presence/imports`, `/hr/leave`, `/hr/schedules`, `/hr/dashboard`, `/me`;
  `/payroll/runs`, `/payroll/runs/:id`, `/payroll/payslips/:id`, `/payroll/payslips/:id/print`,
  `/payroll/inputs`, `/payroll/rules`; `/finance/accounts`, `/finance/entries`,
  `/finance/trial-balance`, `/finance/ledger`, `/finance/periods`, `/finance/posting-rules`.
