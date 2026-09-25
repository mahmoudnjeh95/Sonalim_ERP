# HR, Payroll and Finance ledger — design

Date: 2026-09-25
Status: approved in conversation, awaiting spec review

## Goal

Give the plant (Mali, F CFA / XOF) a complete people-to-ledger chain: a full employee file,
daily presence captured by supervisors and by the clock device, a monthly payroll computed from
configurable Mali rules, payouts by bank file / mobile money / cash, and the payroll and sales
invoices posted to a SYSCOHADA general ledger.

## What the client decided (2026-09-25)

- Legislation: **configurable, multi-country rule tables**; the deployment is **Mali**.
- Presence capture: **supervisor bulk entry** and **clock-device CSV import**. Not from
  production shift reports, not employee self check-in.
- Payment: **bank transfer file**, **mobile money** (Orange Money / Moov Money), **cash**.
- Payroll **posts to a SYSCOHADA ledger**, which does not exist yet and is built here.
- Split: three bounded contexts (`hr`, new `payroll`, `finance`), approach A.

## Rule on statutory values (no invented numbers)

Every rate, ceiling, bracket, relief and account number named below is **seed data, not code**,
and the Mali seed is written from public references that must be checked by the client's
accountant. A rule set carries `status in ('draft', 'confirmed')` and `confirmed_by/at`.
A payroll run may be *calculated* on a draft rule set (for testing and comparison), but
**approval is refused** (`RULESET_NOT_CONFIRMED`) until the rule set in force for the period is
confirmed. The UI shows a banner on every payslip computed from a draft rule set.

## Current state (measured)

- `hr` has employees, departments, contracts (`salary`, `currency` default `'USD'`), leave
  requests, one-row-per-day attendance, and a "payroll run" that copies contract salary and applies
  flat hand-typed bonuses/deductions/taxes. No rules, no payslip lines, no balances.
- `finance` has one table, `finance.invoices`, created by a consumer of `sales.order.confirmed`.
- No `payroll` module; `MODULE_ORDER` = core, warehouse, production, crm, sales, finance, hr, …

The old `hr.payroll_runs` / `hr.payroll_items` / `hr.attendance_records` stay in place (not
dropped: backward-compatible migrations). New code stops writing them; the old endpoints are
removed from the router once the new screens ship, and a later migration drops them.

## Architecture

```
hr  ──(api: EmployeeService, PresenceService, LeaveService)──►  payroll
payroll ──event payroll.run.approved / payroll.run.paid──►  finance (consumer posts entries)
sales/finance invoices ──finance.invoice.issued/paid──►  finance posting (same module)
```

- `payroll` depends on `core`, `hr`. `finance` optionally depends on `payroll` (it calls
  `PayrollPostingService.posting_lines(run_id)` from its consumer to get the lines to post).
- `MODULE_ORDER` gains `payroll` after `hr`.
- New events (in `backend/events/CATALOG.md`): `hr.presence_month.closed`,
  `payroll.run.approved`, `payroll.run.paid`, `payroll.run.reversed`,
  `finance.journal_entry.posted`. Thin payloads (ids, period).
- Money is `NUMERIC(18,0)` in XOF (no sub-unit). Rounding of every computed line is a rule-set
  setting (`round_to` = 1 by default, `round_mode` = half_up); the ITS may round down to a
  multiple of 10 or 100 if the accountant says so — this is also data.
- Every mutation calls `record_audit()`; every entity with create has edit behind
  `<module>.admin_<entity>`; every list uses FilterTabs + ColumnFilterRow + useTableColumns;
  every string is bilingual; every error is `Err(code, message, message_fr)`.

---

## Phase 1 — Employee core (`hr`)

### Data

- `hr.employees` gains: `user_id` (nullable, link to `core.users` for self-service), `gender`,
  `birth_date`, `birth_place`, `nationality`, `national_id` (NINA), `inps_no`, `amo_no`,
  `marital_status` (single/married/divorced/widowed), `address`, `emergency_contact`,
  `badge_no` (clock device, unique per tenant), `position_id`, `grade_id`, `site`,
  `termination_date`, `termination_reason`. `status` gains `'terminated'`.
- `hr.dependants` (employee_id, kind spouse/child, name, birth_date, dependent_for_tax bool,
  valid_from/valid_to). The number of tax dependants on the pay date feeds ITS family relief.
- `hr.payment_methods` (employee_id, method bank/mobile_money/cash, bank_name, account_no/RIB,
  mobile_operator, mobile_number, share_percent, is_primary, valid_from). Net pay splits by
  share; one method per employee is the common case.
- `hr.positions` (code, title, department_id, headcount_budget) and `hr.grades`
  (collective-agreement category/échelon, `base_salary` min for the grade, valid_from).
- `hr.contracts` gains: `contract_type` in (cdi, cdd, apprentice, daily, intern),
  `trial_end_date`, `weekly_hours` (default 40), `base_salary`, `pay_frequency`
  (monthly/daily), `position_id`, `grade_id`, `amends_contract_id`, `end_reason`. Currency
  default becomes `'XOF'`. At most one active contract per employee on any date (enforced in
  domain + exclusion constraint on daterange).
- `hr.contract_components` (contract_id, component_code, amount or rate): fixed recurring
  allowances written on the contract (transport, housing, seniority is computed, see phase 3).
- `hr.employee_documents` (employee_id, kind, file ref, expires_on) — uses existing file
  storage if present, else stores a path/URL only; expiry feeds the dashboard alert list.

### Behaviour

- Contract expiry and trial-end alerts: list of CDD ending in the next 30 days and trials ending
  in the next 15 days (horizons are settings in `hr.settings`, not constants).
- Terminating an employee requires an end reason and date; it closes the active contract and
  flags the employee for a final settlement in the next payroll run.

### Screens

HR → Employees (list + full-page employee file with tabs: identity, family, contract history,
payment, documents, leave, payslips), Organisation (departments, positions, grades).

## Phase 2 — Time & presence (`hr`)

### Data

- `hr.work_schedules` (code, name, per weekday start/end/break minutes, `is_night`) and
  `hr.schedule_assignments` (employee_id, schedule_id, valid_from/to). Plant rotations
  07-15 / 15-23 / 23-07 are three schedules; a rotation pattern is an ordered list of schedules
  per week (`hr.rotation_patterns`).
- `hr.public_holidays` (date, name, paid bool) per country, seeded for Mali per year.
- `hr.clock_punches` (employee_id, badge_no, punched_at, direction in/out/unknown, source
  import_batch_id). `hr.clock_imports` (file name, uploaded_by, row counts, status
  staged/committed/discarded) and `hr.clock_import_rows` (raw row, parsed values, error code).
- `hr.presence_days` replaces `attendance_records`: (employee_id, date, status in
  present/absent/late/leave/holiday/rest/sick/mission/suspended, `scheduled_minutes`,
  `worked_minutes`, `late_minutes`, `ot_minutes_day`, `ot_minutes_night`,
  `ot_minutes_rest_holiday`, `source` in manual/clock/leave/holiday, `justified` bool,
  `note`, `locked` bool). Unique (tenant, employee, date).
- `hr.presence_months` (period, status open/closed, closed_by/at).
- Leave: `hr.leave_types` (code, paid bool, accrual_days_per_month, max_carry_over,
  counts_calendar_or_working_days, requires_document), `hr.leave_balances` (employee, type,
  year, accrued, taken, adjusted), `hr.leave_requests` gains `leave_type_id`, `days`,
  `half_day`. Approval deducts the balance and writes `leave` presence days.

### Behaviour

- **Supervisor bulk grid:** one team (department or schedule) × one day; defaults each row to
  `present` with scheduled minutes, supervisor marks exceptions (absent/late + minutes/sick…),
  saves in one request. A range variant (team × week) for catch-up.
- **Clock import:** CSV upload with a column mapping saved per device profile
  (`hr.clock_profiles`: delimiter, date format, badge column, timestamp column, direction
  column). Rows go to staging; unknown badge, unparsable time, duplicate punch are shown as
  errors; commit writes punches, then the pairing engine (pure domain) turns punches into
  worked intervals per schedule day (night shift 23-07 belongs to the day it starts), computes
  worked/late/overtime minutes, and upserts `presence_days` with `source='clock'` unless the
  day was already set manually (manual wins; conflicts listed).
- **Overtime bands:** split by the rule set of phase 3 (day overtime tiers, night, rest
  day/holiday). Presence only stores minutes by band; rates live in payroll.
- **Month close:** refuses while any working day of an active employee has no presence row
  (`PRESENCE_INCOMPLETE`, lists them) or leave requests are pending; locks the rows and
  publishes `hr.presence_month.closed`. Reopening needs `hr.admin_presence` and is audited;
  it is refused if a payroll run for that month is approved.
- `PresenceService.month_summary(employee_ids, period)` is the payroll's only input from
  presence: days worked, absences unjustified (unpaid days), paid leave days, overtime minutes by
  band, night minutes, holidays worked.

### Screens

HR → Presence (daily grid, monthly calendar per employee, clock imports with staging review,
month close), Leave (requests, approvals, balances), Schedules & holidays.

## Phase 3 — Payroll (`payroll`, new module)

### Rule tables (per country, effective-dated)

- `payroll.rule_sets` (country, valid_from, status draft/confirmed, confirmed_by/at,
  `round_to`, `round_mode`, `working_days_per_month`, `working_hours_per_month`).
- `payroll.components` (code, name_en, name_fr, kind earning/deduction/employer_charge,
  `taxable` bool, `contributable` bool, formula type fixed / rate_x_base / qty_x_rate /
  per_day, base reference, display order, payslip section). Examples seeded: base salary,
  seniority bonus, overtime bands, transport, housing, bonus, advance repayment, loan
  instalment, unpaid absence.
- `payroll.contributions` (rule_set, code, name, base in gross/contributable,
  `employee_rate`, `employer_rate`, `ceiling_monthly` nullable, liability account code).
- `payroll.tax_brackets` (rule_set, tax code e.g. ITS, lower, upper, rate, annualised bool),
  `payroll.tax_reliefs` (rule_set, kind family/professional_expenses, parameters as json:
  percentage, cap, relief per dependant, max dependants).
- `payroll.seniority_scale` (years_from, percent of base), `payroll.overtime_rates`
  (band code, multiplier).

**Mali seed (all `draft`, to be confirmed):** INPS employee pension, employer pension, family
allowances, maternity, work accident (rate by risk class), AMO employee and employer, ITS
progressive brackets with family-charge relief, employer taxes (taxe logement, contribution
forfaitaire employeur, ANPE/formation contributions) as `employer_charge` components. The seed
script prints every value it wrote so the accountant can tick them.

### Engine (`payroll/domain/engine.py`, pure, no DB)

Input: employee snapshot (contract salary, components, dependants, seniority years), presence
month summary, rule set, one-off inputs for the month (bonus, advance, manual adjustments).
Output: ordered payslip lines with base, rate, amount, employee/employer side, plus totals.

1. Earnings: prorated base (hire/exit mid-month and unpaid absence days by
   `working_days_per_month`), seniority, fixed allowances, overtime (minutes × hourly rate ×
   band multiplier), bonuses → **gross**.
2. Contributable base = sum of contributable earnings, capped per contribution.
3. Employee and employer contributions.
4. Taxable = taxable earnings − deductible employee contributions − professional relief;
   ITS from brackets (annualised if the rule says so, then /12) − family relief.
5. Deductions: advances, loan instalments, other → **net to pay**, never negative
   (`NET_NEGATIVE` → the line that overflows is carried to next month and reported).
6. Employer cost = gross + employer contributions + employer charges.

Every step is a function tested alone; golden tests use payslips hand-computed from the
confirmed Mali rules (placeholders until the accountant provides three real payslips).

### Runs and payslips

- `payroll.runs` (period, rule_set_id, status draft → calculated → approved → paid, or
  reversed; calculated_by, approved_by, paid_at). One regular run per period; an
  **off-cycle** run type exists for final settlements and corrections.
- `payroll.run_inputs` (run, employee, component, qty/amount): the one-off monthly inputs.
- `payroll.payslips` (run, employee, snapshot json of the inputs used, gross, contributable,
  taxable, employee_contrib, employer_contrib, its, deductions, net, employer_cost) and
  `payroll.payslip_lines`.
- Calculate: requires the presence month closed (`PRESENCE_NOT_CLOSED`); recomputes all
  payslips of the run; idempotent. Approve: requires `payroll.approve_runs`, a user different
  from the one who calculated (`SAME_USER_APPROVAL`), a confirmed rule set; locks the run and
  publishes `payroll.run.approved`. Mark paid: after payouts are generated and confirmed,
  publishes `payroll.run.paid`. Reverse: only an approved/paid run, creates a mirror entry via
  `payroll.run.reversed`.
- `payroll.advances` and `payroll.loans` (+ `payroll.loan_instalments`): approved advances are
  deducted in the chosen month; loans generate instalments consumed by runs.
- **Final settlement:** off-cycle payslip with prorated salary, unused paid-leave indemnity,
  notice indemnity, severance (formula components from the rule set), certificate of work
  (printable).
- **Payslip:** printable HTML route (`/payroll/payslips/:id/print`) with print CSS, bilingual
  labels, company header; “Download all” opens a print view of the whole run. No server PDF
  library.

### Payouts

- `payroll.payout_batches` (run, method, status generated/confirmed, file ref) and
  `payroll.payout_lines` (employee, method details snapshot, amount).
- Bank: CSV with configurable column template per bank (`payroll.bank_file_templates`).
- Mobile money: CSV (operator, number, name, amount) per operator.
- Cash: printable sheet with signature column and a note/coin breakdown (billetage) total.

### Declarations

Monthly reports from payslips: INPS (per employee contributable base and contributions),
AMO, ITS withheld, employer taxes. Exported as CSV + printable page. Annual per-employee
recap (gross, contributions, ITS) for the yearly declaration.

### Screens

Payroll → Runs (list, run page: calculate / review variances vs last month / approve / payouts
/ declarations), Payslip detail + print, Inputs (monthly bonuses, advances, loans), Rules
(rule sets, components, contributions, brackets, confirm), My payslips (self-service, any user
whose `user_id` is linked to an employee sees only their own).

## Phase 4 — Finance ledger (`finance`)

### Data

- `finance.accounts` (code, name, class 1–9, type asset/liability/equity/income/expense,
  `is_postable`, parent_code). SYSCOHADA revised chart seeded (classes and the accounts the
  plant uses).
- `finance.journals` (code PAIE, VTE, ACH, BNQ, CAI, OD, name, type).
- `finance.fiscal_years` and `finance.periods` (month, status open/closed).
- `finance.journal_entries` (journal, date, period, reference, source_module, source_id,
  status draft/posted/reversed, reversal_of) and `finance.journal_lines` (account, debit, credit,
  partner_id nullable, employee_ref nullable, label). Posted entries are immutable; balance
  check `sum(debit) = sum(credit)` in domain and a deferred constraint trigger.
- `finance.posting_rules` (source e.g. payroll, key e.g. component/contribution code, debit
  account, credit account). Default payroll mapping (to be confirmed): earnings → 661/663,
  employer contributions → 664, employer taxes → 641, net pay → 422, INPS → 431, AMO → 433,
  ITS → 447, advances → 421, payment → 521 (bank) / 571 (cash) / a configured 5xx for mobile
  money. Invoices: 411 / 70x / 443 (VAT rate from existing invoice data if any; none added
  here).

### Behaviour

- Consumer `payroll.run.approved` → one PAIE entry per run, lines aggregated by account
  (per-employee detail on 422 optional via `employee_ref`). `payroll.run.paid` → BNQ/CAI
  entries clearing 422. `payroll.run.reversed` → reversal entry. `finance.invoice.issued/paid`
  → VTE / BNQ entries. All consumers idempotent on `event_id` and on (source_module,
  source_id, kind).
- Posting into a closed period is refused (`PERIOD_CLOSED`); the consumer dead-letters and
  the run page shows “not posted” with the reason.
- Manual OD entries (draft → posted) behind `finance.manage_entries`.
- Reports: trial balance (period range), general ledger per account, journal listing, account
  balance for 42x/43x/44x (what is owed to staff, INPS, the State).
- Period close / reopen (`finance.admin_periods`).

### Screens

Finance → Chart of accounts, Journals & entries, Trial balance, General ledger, Periods,
Posting rules; existing Invoices page stays.

## Phase 5 — HR analytics & self-service

- HR dashboard: headcount by department/contract type, hires/exits of the month, absence rate
  (unjustified absence days / scheduled days), overtime hours by band, payroll cost (gross and
  employer cost) by department, month-on-month variance, contract/trial/document expiry list.
  Every figure comes from a recorded field listed above; no targets invented.
- Self-service (`hr.self_service`, granted per user): my file (read), my payslips, my leave
  balance and leave request.

## Permissions (declared in `module.json`)

- `hr`: existing codes + `hr.view_presence`, `hr.manage_presence`, `hr.import_clock`,
  `hr.close_presence`, `hr.admin_presence`, `hr.view_positions`, `hr.manage_positions`,
  `hr.admin_positions`, `hr.view_sensitive` (salary, national id, bank details hidden without
  it), `hr.self_service`. Existing `*_attendance` codes are kept and mapped to presence.
- `payroll`: `view_runs`, `calculate_runs`, `approve_runs`, `pay_runs`, `reverse_runs`,
  `manage_inputs`, `view_rules`, `manage_rules`, `confirm_rules`, `view_declarations`,
  `admin_payslips`.
- `finance`: existing + `view_ledger`, `manage_entries`, `admin_entries`, `manage_accounts`,
  `admin_accounts`, `admin_periods`, `manage_posting_rules`.

## Errors (typed codes, bilingual)

`CONTRACT_OVERLAP`, `BADGE_TAKEN`, `PRESENCE_INCOMPLETE`, `PRESENCE_MONTH_CLOSED`,
`PRESENCE_NOT_CLOSED`, `LEAVE_BALANCE_INSUFFICIENT`, `RULESET_NOT_CONFIRMED`,
`RULESET_MISSING`, `SAME_USER_APPROVAL`, `RUN_LOCKED`, `NET_NEGATIVE`, `PAYOUT_SPLIT_INVALID`,
`ENTRY_UNBALANCED`, `PERIOD_CLOSED`, `ACCOUNT_NOT_POSTABLE`, `POSTING_RULE_MISSING`.

## Testing

- Domain (no DB): pairing engine (day/night shift, missing out-punch, duplicates), leave
  accrual and balance, every payroll engine step, proration, rounding, net-negative carry,
  balanced-entry builder, posting-rule mapping.
- Integration (`db` fixture): contract overlap, presence close, run calculate → approve →
  event → PAIE entry balanced, paid → 422 cleared, reversal, idempotent consumers (same event
  twice → one entry), closed period refused.
- Frontend: `tsc -b --force` + browser check of each screen with the demo seed.
- Seed: `scripts/seed_hr_payroll.py` — ~60 employees across departments and shifts, one month
  of presence (with a clock CSV sample), Mali draft rule set, one calculated run.

## Delivery order

Each phase is its own implementation plan and merges on its own:
1 Employee core → 2 Presence & leave → 3 Payroll (engine, runs, payouts, declarations) →
4 Finance ledger + posting → 5 Analytics & self-service. Phase 4's ledger tables can be built
in parallel with phase 3; the posting consumers wait for phase 3's events.

## Out of scope

Recruitment/ATS, training management, performance reviews, expense claims, biometric device
live integration (CSV import only), bank API payouts, multi-currency payroll, VAT returns,
fixed assets, supplier invoices/AP (the ledger is ready for them later).
