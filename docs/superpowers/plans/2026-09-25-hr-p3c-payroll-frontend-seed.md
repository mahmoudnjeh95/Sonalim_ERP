# HR Phase 3c — Payroll frontend and Mali draft seed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `/payroll/*` React screens (Runs list + run detail with calculate/review-variance/approve/reverse, monthly inputs, advances/loans, final settlements, payouts, declarations; Payslip detail + print view; Rules screens with a draft-rule-set banner shown wherever a payslip or run used a draft set) and extend `backend/scripts/seed_hr_payroll.py` with a Mali **draft** rule set, a month of monthly inputs, and one calculated (not approved) run.

**Architecture:** Every screen is a page component in `frontend/src/features/payroll/` reading and writing through TanStack Query hooks in a single `api.ts`, following the same feature-folder shape as `frontend/src/features/hr/` (phases 1–2) and `frontend/src/features/warehouse/`. Nothing here adds a backend route: every request this plan makes was already built, tested and committed in `2026-09-25-hr-p3a-payroll-engine.md` and `2026-09-25-hr-p3b-payroll-runs.md` — this plan only calls it. Print pages render inside the normal authenticated route tree (`ProtectedRoute` → `AppLayout`) and rely on the existing global `@media print` rule in `frontend/src/index.css` (already hides `aside, nav, header`) rather than a new standalone layout. The seed extends the existing `backend/scripts/seed_hr_payroll.py` (created by phase 1, extended by phase 2 with a closed August 2026 presence month) instead of creating a second script.

**Tech Stack:** React 18 + TypeScript, TanStack Query, React Router, React Hook Form + Zod, Tailwind + the repo's Radix primitives (`components/ui/`), Recharts is not needed here. Backend: Python 3.11 for the one seed-script extension, no new routes.

**Spec:** `docs/superpowers/specs/2026-09-25-hr-payroll-finance-design.md` (Phase 3, "Screens" and "Mali seed" sub-sections), cross-phase contract `docs/superpowers/plans/2026-09-25-hr-payroll-finance-interfaces.md`. **Depends on:** `docs/superpowers/plans/2026-09-25-hr-p3a-payroll-engine.md` (all 11 tasks) and `docs/superpowers/plans/2026-09-25-hr-p3b-payroll-runs.md` (all 13 tasks) merged — every route, permission code and response shape this plan's frontend calls is defined and tested there; this plan does not invent or modify backend behaviour. Also depends on hr phases 1–2 (`2026-09-25-hr-p1-employee-core.md`, `2026-09-25-hr-p2-presence-leave.md`) merged, since the seed extends `backend/scripts/seed_hr_payroll.py` as phase 2 left it (60 employees, August 2026 presence closed).

## Global Constraints

- Money is `NUMERIC(18,0)` XOF in the database, integers in JSON, formatted as "F CFA" in the UI via `Intl.NumberFormat(currentLocale(), { style: "currency", currency: "XOF", maximumFractionDigits: 0 })` with the currency symbol replaced by the literal suffix "F CFA" (follow the existing `warehouse.overview.column.value` / "Valeur (F CFA)" convention — money columns are always labelled "(F CFA)", not `Intl`'s own "XOF" symbol).
- A period is a `datetime.date` equal to the first day of the month, sent over HTTP as `YYYY-MM-01`.
- No backend route, permission, or response shape may be invented in this plan. Every fetcher in `api.ts` binds to a route already listed in 3a Task 11 (rules) or 3b Tasks 9, 10, 11, 12 (runs, payslips, inputs, advances, loans, payouts, declarations). If a screen needs data with no existing route, it is listed under "Decisions / gaps found" below, not silently added here.
- Permission codes exactly as declared in `payroll/module.json` (3a Task 1): `payroll.view_runs`, `payroll.calculate_runs`, `payroll.approve_runs`, `payroll.pay_runs`, `payroll.reverse_runs`, `payroll.manage_inputs`, `payroll.view_rules`, `payroll.manage_rules`, `payroll.confirm_rules`, `payroll.view_declarations`, `payroll.admin_payslips`. None of these is granted to the demo user by default (platform rule, `CLAUDE.md`) — Task 10's seed step grants what the seeded run needs so the demo login can see it, but every screen must still degrade correctly (hide the write affordance, keep the read visible) for a user missing a specific permission, exactly like every other module.
- Every user-facing string goes through `useI18n()` with **both** `en` and `fr` keys added to `frontend/src/lib/i18n.tsx` in the same edit that introduces the string (`erp-platform-architecture` SKILL.md, "Frontend i18n"). Namespace every key `payroll.*` (e.g. `payroll.runs.status.calculated`), except for values that are genuinely shared across modules and already in the `status.*` namespace — payroll's run/payslip/advance/loan/batch statuses are their own vocabulary (`draft/calculated/approved/paid/reversed`, `requested/approved/cancelled`, `active/cancelled`, `generated/confirmed`) and do not reuse `status.*`.
- Every list view uses `FilterTabs` (closed-value columns: run status, advance/loan status, batch status) + `ColumnFilterRow` + `useTableColumns` per the platform's "Frontend list filtering" and "Column resize & visibility" rules — built via a shared `PayrollTable<Row>` wrapper (this plan's Task 1), the same pattern `HrListTable` establishes in phase 1. `tableKey`s are module-qualified: `"payroll.runs"`, `"payroll.inputs.advances"`, `"payroll.inputs.loans"`, `"payroll.rules.ruleSets"`.
- Server state only via TanStack Query (`useQuery`/`useMutation`), module-level `const X_QUERY_KEY = [...] as const`, `onSuccess` invalidating every query key the write affects — the platform's "Frontend data fetching" rule. No bare `fetch`/`useEffect` data loading.
- One branded loader per screen (`AppLoader`), sub-blocks use `Skeleton`; blocks stay mounted behind the loader rather than unmounting on refetch (`feedback_one_loader_per_screen` — user memory rule).
- Verify every task's frontend changes with `npx tsc -b --force` from `frontend/` (not `tsc --noEmit` — the project's build-mode check is what catches missing i18n keys and stale prop types across the whole workspace).
- Print pages: no server PDF library (spec: "No server PDF library"). A printable page is a normal React route rendered with print-only CSS (`@media print`), using the company header from `payslip.company` / `run_print.company` / `cash_sheet.company`, already served by the backend (3b Tasks 9–10).
- Backend touched only for the seed script (`backend/scripts/seed_hr_payroll.py`); no `backend/modules/payroll/` file is created or modified by this plan. Tests: from `backend/`, `.venv/Scripts/python -m pytest <path> -q`; the seed's own tests are plan-shape tests (no DB) plus one integration test using the `db` fixture, exactly like phase 1's Task 15 and phase 2's Task 14.
- No Mali statutory value anywhere in this plan's frontend code — the Mali rule-set numbers live only in the seed script (Task 10) and are printed under a "TO CONFIRM" banner, exactly like `GRADES`/`TRANSPORT`/`HOUSING` in phase 1's seed.
- Shared working tree: never `git stash`; `git add` only the files each task lists; every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A run's rule set is a draft** (calculated but not approved, or approved before this UI existed under an old draft) — expected: `DraftRuleSetBanner` shows on the run page, the run list row, the payslip page and the print page, naming the rule set and linking to Rules → confirm; this is a spec requirement ("The UI shows a banner on every payslip computed from a draft rule set"), not a nice-to-have. Test: Task 4 `RunPage` banner test + Task 7 `PayslipPage` banner test.
2. **Approving your own calculation, or approving with a draft/newer rule set** — expected: the Approve button is not silently disabled (a user should understand why); the 409 `SAME_USER_APPROVAL` / 422 `RULESET_NOT_CONFIRMED` response is surfaced as a bilingual toast/inline error, not swallowed. Test: Task 4 `test_approving_your_own_calculation_shows_the_refusal`.
3. **A payout split that does not add to 100%, or a bank batch with no template** — expected: `PAYOUT_SPLIT_INVALID` names the employee in the toast (server already does — the frontend must not re-summarize it away), and `TEMPLATE_MISSING` on `GET .../file` routes the user to "add a bank template" rather than downloading a broken file. Test: Task 6 `test_a_missing_bank_template_offers_to_add_one`.
4. **A number typed into a monthly-input or advance/loan amount field that the component/component list does not allow** (e.g. an amount on `BASE`, a qty on a `fixed` component) — expected: the 422 `INPUT_INVALID` from the server is shown next to the field, not just as a toast, since the same mistake is easy to repeat immediately after dismissing a toast. Test: Task 5 `test_a_bad_component_choice_shows_inline`.
5. **Printing a run with zero payslips, or a payslip whose net is 0 after a full unpaid-absence month** — expected: the print page renders a clean "no payslips this run" / a payslip with a visible `NET_NEGATIVE` warning banner rather than a blank or broken layout; `warnings` is already on the payslip list/detail response (3b Task 4/10) and must be rendered, not dropped. Test: Task 8 `test_a_payslip_with_a_carried_warning_shows_it_on_screen_and_in_print`.

---

## File Structure (this plan)

```
frontend/src/features/payroll/
  api.ts                        types, PAYROLL_KEYS, every fetcher/mutation hook this plan uses
  format.ts                     formatXof, formatPeriod, periodParam, monthLabel
  PayrollTable.tsx              shared list table: useTableColumns + ColumnFilterRow + FilterTabs wiring
  PayrollStatusBadge.tsx        run/payslip/advance/loan/batch status -> i18n label + badge variant
  DraftRuleSetBanner.tsx        shown on Run/Payslip/print pages when rule_set_status === "draft"
  rules/
    RulesPage.tsx               /payroll/rules
    SettingsCard.tsx            payroll country + employer identifiers
    RuleSetList.tsx             + RuleSetDialog.tsx, CopyRuleSetDialog.tsx
    RuleRowsTable.tsx           + RuleRowDialog.tsx (one dialog per CHILD_KINDS kind)
    ruleTables.ts                column defs / field defs per rule-row kind
  runs/
    RunsPage.tsx                /payroll/runs (list + create dialog)
    RunDialog.tsx                create a run (period, run_type, label, employee_ids for off-cycle)
    RunPage.tsx                 /payroll/runs/:id
    run/PayslipsPanel.tsx, VariancePanel.tsx, SettlementsPanel.tsx, PayoutsPanel.tsx,
        DeclarationsPanel.tsx, ReverseDialog.tsx, BankTemplatesDialog.tsx
  inputs/
    InputsPage.tsx               /payroll/inputs (tabs: run inputs, advances, loans)
    RunInputsTab.tsx, AdvancesTab.tsx, LoansTab.tsx, EmployeeSelect.tsx
  payslips/
    PayslipPage.tsx              /payroll/payslips/:id
    PayslipEditDialog.tsx        note + payment methods (payroll.admin_payslips)
  print/
    PrintShell.tsx               shared print chrome: company header, print button, page-break CSS hooks
    PayslipDocument.tsx          the payslip body (used by PayslipPrintPage and RunPrintPage)
    WorkCertificate.tsx
    PayslipPrintPage.tsx         /payroll/payslips/:id/print
    RunPrintPage.tsx             /payroll/runs/:id/print
    CashSheetPrintPage.tsx       /payroll/payout-batches/:id/cash-sheet/print
    DeclarationPrintPage.tsx     /payroll/declarations/print?period=&code= | ?year=
frontend/src/routes/router.tsx, frontend/src/routes/Sidebar.tsx, frontend/src/lib/i18n.tsx   (modify)
backend/scripts/payroll_mali_rules.py       Mali DRAFT values, each "to confirm by accountant"
backend/scripts/seed_hr_payroll.py          (modify) rule set + monthly inputs + one calculated run
backend/scripts/test_seed_hr_payroll.py, test_seed_hr_payroll_integration.py   (modify)
```

---

## Decisions / gaps found

Checked against 3a Task 11 and 3b Tasks 9–12's route tables before writing any frontend code. Two gaps found; both resolved with a query param on an already-existing route (nothing new added to the backend):

1. **Cash-sheet print and declaration print have no dedicated "print" route** — 3b only exposes `GET /payroll/payout-batches/{id}/cash-sheet` (JSON) and `GET /payroll/declarations` / `/payroll/declarations/annual` (JSON or CSV via `format=csv`). There is no `format=print` or a `.../print` HTML route for either. **Resolution:** `CashSheetPrintPage.tsx` and `DeclarationPrintPage.tsx` fetch the existing JSON endpoint (`cash_sheet`/`declaration`/`annual_recap`, all already returning everything a print layout needs: `company`, `lines`/`rows`, `totals`) and render it client-side with print CSS, exactly like `PayslipPrintPage` does with `GET /payroll/payslips/{id}` and `RunPrintPage` does with `GET /payroll/runs/{id}/print`. No new backend route; this is a rendering choice, not an API gap.
2. **The employee picker for advances/loans/final-settlements/run-inputs has no name-search backend filter** — `GET /payroll/employees?period=` (3b Task 11) returns every employee active in the period with no `q=` search param, which is fine for the ~60-employee demo seed but would not scale. **Resolution for this plan:** `EmployeeSelect.tsx` fetches the full list for the period once (TanStack Query caches it) and filters client-side by typed text — a `<Select>`/combobox pattern already used elsewhere in the codebase (`ProductSelect.tsx` groups and filters a full catalogue client-side the same way). If the employee list becomes large enough that this is a problem, adding `q=` to `GET /payroll/employees` is a one-line addition to 3b's `routes_runs.py::employees()` — flagged here rather than added preemptively, since a small query-param addition to an existing route is within 3b's own remit, not this frontend plan's.

No other gap found: every write action this plan's UI performs (calculate, approve, reverse, mark-paid, generate/confirm payouts, create/update/delete rule rows, confirm/reopen rule sets, create/update/delete runs and final settlements, create/update/delete/approve/cancel inputs/advances/loans, admin-edit a payslip) has an exact route, permission and request/response shape already defined in 3a Task 11 or 3b Tasks 4–13.

---

### Task 1: `api.ts`, `format.ts`, `PayrollTable`, `PayrollStatusBadge`

**Files:**
- Create: `frontend/src/features/payroll/api.ts`, `frontend/src/features/payroll/format.ts`, `frontend/src/features/payroll/PayrollTable.tsx`, `frontend/src/features/payroll/PayrollStatusBadge.tsx`
- Modify: `frontend/src/lib/i18n.tsx` (status + common payroll keys)

**Interfaces:**
- Consumes: backend routes exactly as `2026-09-25-hr-p3a-payroll-engine.md` Task 11 and `2026-09-25-hr-p3b-payroll-runs.md` Tasks 9–12 define them; `useTableColumns`, `ColumnFilterRow`, `useColumnFilters`, `FilterTabs`, `apiFetch` (`frontend/src/lib/api.ts`), `useAuth` (`frontend/src/lib/auth.ts`).
- Produces (used by every later task):
  - `PAYROLL_KEYS` — an object of query-key factories: `rules.settings`, `rules.list`, `rules.detail(id)`, `rules.children(id, kind)`, `runs.list(status?)`, `runs.detail(id)`, `runs.payslips(id)`, `runs.variance(id)`, `runs.print(id)`, `runs.settlements(id)`, `runs.payouts(id)`, `runs.inputs(id)`, `runs.inputComponents(id)`, `employees(period)`, `payslip.detail(id)`, `payslip.certificate(id)`, `advances.list(status?)`, `loans.list(status?)`, `templates.list`, `declarations.codes(period)`, `declarations.one(period, code)`, `declarations.annual(year)`.
  - Types mirroring the backend response shapes exactly (field names copied from 3a/3b's `Interfaces` sections — see Step 3): `RuleSetHeader`, `RuleSetDocument`, `PayrollRun`, `PayslipSummary`, `PayslipDetail`, `PayslipLine`, `RunVariance`, `FinalSettlement`, `RunInput`, `Advance`, `Loan`, `BankFileTemplate`, `PayoutBatch`, `CashSheet`, `Declaration`.
  - Fetchers/hooks, one per backend route, named `useX`/`useXMutation` (e.g. `useRuleSets()`, `useCreateRuleSet()`, `useRuns(status?)`, `useCreateRun()`, `useCalculateRun()`, `useApproveRun()`, `useReverseRun()`, `useRunPayslips(runId)`, `useRunVariance(runId)`, `useFinalSettlements(runId)`, `useAddFinalSettlement()`, `useUpdateFinalSettlement()`, `useRemoveFinalSettlement()`, `usePayslip(id)`, `useAdminUpdatePayslip()`, `useCertificate(id)`, `useInputComponents(runId)`, `useRunInputs(runId)`, `useAddRunInput()`, `useUpdateRunInput()`, `useDeleteRunInput()`, `useAdvances(status?)`, `useCreateAdvance()`, `useUpdateAdvance()`, `useApproveAdvance()`, `useCancelAdvance()`, `useLoans(status?)`, `useCreateLoan()`, `useUpdateLoan()`, `useCancelLoan()`, `useBankTemplates()`, `useCreateTemplate()`, `useUpdateTemplate()`, `useDeleteTemplate()`, `useGeneratePayouts()`, `usePayoutBatches(runId)`, `useConfirmBatch()`, `useMarkPaid()`, `useDeclarationCodes(period)`, `useDeclaration(period, code)`, `useAnnualRecap(year)`, `usePayrollEmployees(period)`.
  - `format.ts`: `formatXof(amount: number) -> string` (e.g. `"497 500 F CFA"`), `formatPeriod(period: string, locale) -> string` (e.g. `"septembre 2031"` / `"September 2031"`), `periodParam(date: Date) -> string` (`YYYY-MM-01`), `monthInputValue(period: string) -> string` (`YYYY-MM`, for `<input type="month">`), `parseMonthInput(value: string) -> string` (back to `YYYY-MM-01`).
  - `PayrollTable<Row>` props: `tableKey: string, columns: ColumnDef<Row>[], rows: Row[], rowKey: (row: Row) => string, loading: boolean, emptyTitle: string, emptyDescription: string, toolbar?: ReactNode, filtersActive?: boolean, onClearFilters?: () => void, filterCells?: FilterCell[], onRowClick?: (row: Row) => void`. Internally: `useTableColumns(tableKey, columns)`, renders `<AppLoader>` while `loading`, `<EmptyState>` when `rows.length === 0` and no filters are active, a "no rows match your filters" variant of `EmptyState` when filters are active, else the table with `ColumnFilterRow` when `filterCells` is given.
  - `PayrollStatusBadge({ domain: "run" | "payslipBatch" | "advance" | "loan", status }: { domain; status: string })` — maps `status` through `t()` keys namespaced `payroll.status.<domain>.<status>` and a `Badge` variant (`draft/requested/generated` → `outline`, `calculated/approved/active` → `default`, `paid/confirmed` → `success` variant if one exists else `default`, `reversed/cancelled` → `destructive`).

- [ ] **Step 1: Read the exact response shapes before writing types**

Open `docs/superpowers/plans/2026-09-25-hr-p3b-payroll-runs.md` and re-read: Task 4's `RUN_SELECT` (the run document: `id, period, run_type, label, employee_ids, rule_set_id, rule_set_status, status, created_by, created_at, calculated_by, calculated_at, approved_by, approved_at, paid_by, paid_at, reversed_by, reversed_at, reversal_reason, payslip_count, gross, net, employer_cost, warning_count`, plus `get_run`'s added `presence_closed` and `rule_set_in_force`), Task 10's `PayslipService` bullet list (`list_payslips`, `get_payslip`, `run_print`, `certificate`, `variance` return shapes), Task 9's `PayoutService` bullet list (batch/cash-sheet shapes), Task 12's `DeclarationService`/`declaration_json` shapes (`code, columns, rows, totals`), Task 11's route/permission table, Task 5's `InputService` bullet list. Do not guess a field name — every one used in Step 3 below is copied verbatim from those sections.

- [ ] **Step 2: Add the i18n keys**

In `frontend/src/lib/i18n.tsx`, add to both the `en` object and the `fr` object (same keys, both objects, in the same edit):

```ts
// English (en object)
"payroll.status.run.draft": "Draft",
"payroll.status.run.calculated": "Calculated",
"payroll.status.run.approved": "Approved",
"payroll.status.run.paid": "Paid",
"payroll.status.run.reversed": "Reversed",
"payroll.status.advance.requested": "Requested",
"payroll.status.advance.approved": "Approved",
"payroll.status.advance.cancelled": "Cancelled",
"payroll.status.loan.active": "Active",
"payroll.status.loan.cancelled": "Cancelled",
"payroll.status.payslipBatch.generated": "Generated",
"payroll.status.payslipBatch.confirmed": "Confirmed",
"payroll.common.fCfa": "F CFA",
"payroll.common.period": "Period",
"payroll.common.employee": "Employee",
"payroll.common.amount": "Amount",
"payroll.common.note": "Note",
"payroll.common.loading": "Loading payroll data…",
"payroll.common.noRows": "Nothing here yet",
"payroll.common.noRowsMatchFilters": "No rows match your filters",
"payroll.common.clearFilters": "Clear filters",
```

```ts
// French (fr object) — same keys
"payroll.status.run.draft": "Brouillon",
"payroll.status.run.calculated": "Calculée",
"payroll.status.run.approved": "Approuvée",
"payroll.status.run.paid": "Payée",
"payroll.status.run.reversed": "Extournée",
"payroll.status.advance.requested": "Demandée",
"payroll.status.advance.approved": "Approuvée",
"payroll.status.advance.cancelled": "Annulée",
"payroll.status.loan.active": "Actif",
"payroll.status.loan.cancelled": "Annulé",
"payroll.status.payslipBatch.generated": "Généré",
"payroll.status.payslipBatch.confirmed": "Confirmé",
"payroll.common.fCfa": "F CFA",
"payroll.common.period": "Période",
"payroll.common.employee": "Employé",
"payroll.common.amount": "Montant",
"payroll.common.note": "Note",
"payroll.common.loading": "Chargement des données de paie…",
"payroll.common.noRows": "Rien ici pour l'instant",
"payroll.common.noRowsMatchFilters": "Aucune ligne ne correspond aux filtres",
"payroll.common.clearFilters": "Effacer les filtres",
```

- [ ] **Step 3: Write `format.ts`**

```ts
// frontend/src/features/payroll/format.ts
export function formatXof(amount: number, locale: string): string {
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(amount)} F CFA`;
}

export function periodParam(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-01`;
}

export function monthInputValue(period: string): string {
  return period.slice(0, 7); // "YYYY-MM-01" -> "YYYY-MM"
}

export function parseMonthInput(value: string): string {
  return `${value}-01`; // "YYYY-MM" -> "YYYY-MM-01"
}

export function formatPeriod(period: string, locale: string): string {
  const [year, month] = period.split("-").map(Number);
  return new Intl.DateTimeFormat(locale, { month: "long", year: "numeric" }).format(new Date(year, month - 1, 1));
}
```

- [ ] **Step 4: Write `api.ts`**

```ts
// frontend/src/features/payroll/api.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../../lib/api";
import { useAuth } from "../../lib/auth";

// ---- types (field names copied verbatim from 3a Task 11 and 3b Tasks 4, 5, 9, 10, 12) ----

export interface RuleSetHeader {
  id: string;
  status: "draft" | "confirmed";
  confirmed_by: string | null;
  confirmed_at: string | null;
  created_by: string;
  created_at: string;
  country: string;
  name: string;
  valid_from: string;
  round_to: number;
  round_mode: "half_up" | "down" | "up";
  tax_round_to: number;
  tax_round_mode: "half_up" | "down" | "up";
  working_days_per_month: number;
  working_hours_per_month: number;
  settlement_reference_months: number;
  notes: string | null;
}

export type RuleRowKind =
  | "components"
  | "contributions"
  | "tax_brackets"
  | "tax_reliefs"
  | "seniority_scale"
  | "overtime_rates"
  | "severance_scale";

export type RuleSetDocument = RuleSetHeader & Record<RuleRowKind, Record<string, unknown>[]>;

export interface PayrollRun {
  id: string;
  period: string;
  run_type: "regular" | "off_cycle";
  label: string | null;
  employee_ids: string[] | null;
  rule_set_id: string | null;
  rule_set_status: "draft" | "confirmed" | null;
  status: "draft" | "calculated" | "approved" | "paid" | "reversed";
  created_by: string;
  created_at: string;
  calculated_by: string | null;
  calculated_at: string | null;
  approved_by: string | null;
  approved_at: string | null;
  paid_by: string | null;
  paid_at: string | null;
  reversed_by: string | null;
  reversed_at: string | null;
  reversal_reason: string | null;
  payslip_count: number;
  gross: number;
  net: number;
  employer_cost: number;
  warning_count: number;
  presence_closed?: boolean;
  rule_set_in_force?: { id: string; name: string; status: "draft" | "confirmed" } | null;
}

export interface PayslipSummary {
  id: string;
  run_id: string;
  employee_id: string;
  employee_no: string;
  full_name: string;
  department_id: string | null;
  gross: number;
  contributable: number;
  taxable: number;
  employee_contrib: number;
  employer_contrib: number;
  employer_charges: number;
  its: number;
  deductions: number;
  net: number;
  employer_cost: number;
  warnings: string[];
  rule_set_status: "draft" | "confirmed";
  note: string | null;
}

export interface PayslipLine {
  line_no: number;
  section: string;
  code: string;
  name_en: string;
  name_fr: string;
  base: number | null;
  qty: number | null;
  rate: number | null;
  amount: number;
}

export interface CompanyHeader {
  name: string | null;
  address: string | null;
  employer_inps_no: string | null;
  employer_tax_id: string | null;
}

export interface PayslipDetail extends PayslipSummary {
  snapshot: Record<string, unknown>;
  period: string;
  run_type: "regular" | "off_cycle";
  run_status: PayrollRun["status"];
  lines: PayslipLine[];
  company: CompanyHeader;
}

export interface RunPrintDocument {
  run: { id: string; period: string; run_type: string; label: string | null; status: string };
  company: CompanyHeader;
  payslips: PayslipDetail[];
}

export interface RunVariance {
  previous_run_id: string | null;
  previous_period: string | null;
  rows: {
    employee_id: string;
    employee_no: string;
    full_name: string;
    previous_gross: number;
    current_gross: number;
    previous_net: number;
    current_net: number;
    delta_gross: number;
    delta_net: number;
    change: "new" | "same" | "changed" | "removed";
  }[];
  totals: { previous_gross: number; current_gross: number; previous_net: number; current_net: number };
}

export interface FinalSettlement {
  id: string;
  run_id: string;
  employee_id: string;
  employee_no: string;
  full_name: string;
  unused_leave_days: number;
  notice_months: number;
  created_by: string;
  created_at: string;
}

export interface RunInput {
  id: string;
  run_id: string;
  employee_id: string;
  employee_no: string;
  full_name: string;
  component_code: string;
  qty: number | null;
  amount: number | null;
  note: string | null;
  created_by: string;
  created_at: string;
}

export interface InputComponent {
  code: string;
  name_en: string;
  name_fr: string;
  kind: "earning" | "deduction";
  formula_type: "fixed" | "qty_x_rate" | "per_day";
  default_amount: number | null;
}

export interface Advance {
  id: string;
  employee_id: string;
  employee_no: string;
  full_name: string;
  amount: number;
  requested_on: string;
  deduct_period: string;
  status: "requested" | "approved" | "cancelled";
  approved_by: string | null;
  approved_at: string | null;
  note: string | null;
  deducted_payslip_id: string | null;
}

export interface Loan {
  id: string;
  employee_id: string;
  employee_no: string;
  full_name: string;
  principal: number;
  instalment_count: number;
  first_period: string;
  status: "active" | "cancelled";
  note: string | null;
  instalments: { id: string; seq: number; period: string; amount: number; payslip_id: string | null }[];
  remaining: number;
}

export interface BankFileTemplate {
  id: string;
  bank_name: string;
  delimiter: string;
  include_header: boolean;
  columns: { header: string; field: string }[];
}

export interface PayoutBatch {
  id: string;
  run_id: string;
  method: "bank" | "mobile_money" | "cash";
  group_key: string;
  status: "generated" | "confirmed";
  file_name: string;
  total: number;
  line_count: number;
  generated_by: string;
  generated_at: string;
  confirmed_by: string | null;
  confirmed_at: string | null;
}

export interface CashSheet {
  batch: PayoutBatch;
  period: string;
  company: CompanyHeader;
  denominations: number[];
  lines: { employee_no: string; full_name: string; amount: number; counts: Record<string, number>; remainder: number }[];
  totals: { amount: number; counts: Record<string, number>; remainder: number };
}

export interface Declaration {
  code?: string;
  columns: string[];
  rows: Record<string, unknown>[];
  totals: Record<string, unknown>;
  period?: string;
  year?: number;
}

export interface PayrollEmployee {
  employee_id: string;
  employee_no: string;
  full_name: string;
  department_id: string | null;
  termination_date: string | null;
}

// ---- query keys -------------------------------------------------------------------------

export const PAYROLL_KEYS = {
  settings: ["payroll", "settings"] as const,
  ruleSets: ["payroll", "rule-sets"] as const,
  ruleSet: (id: string) => ["payroll", "rule-sets", id] as const,
  ruleRows: (id: string, kind: RuleRowKind) => ["payroll", "rule-sets", id, kind] as const,
  runs: (status?: string) => ["payroll", "runs", status ?? "all"] as const,
  run: (id: string) => ["payroll", "runs", "detail", id] as const,
  runPayslips: (id: string) => ["payroll", "runs", id, "payslips"] as const,
  runVariance: (id: string) => ["payroll", "runs", id, "variance"] as const,
  runPrint: (id: string) => ["payroll", "runs", id, "print"] as const,
  runSettlements: (id: string) => ["payroll", "runs", id, "final-settlements"] as const,
  runInputs: (id: string) => ["payroll", "runs", id, "inputs"] as const,
  runInputComponents: (id: string) => ["payroll", "runs", id, "input-components"] as const,
  runPayouts: (id: string) => ["payroll", "runs", id, "payouts"] as const,
  employees: (period: string) => ["payroll", "employees", period] as const,
  payslip: (id: string) => ["payroll", "payslips", id] as const,
  certificate: (id: string) => ["payroll", "payslips", id, "certificate"] as const,
  advances: (status?: string) => ["payroll", "advances", status ?? "all"] as const,
  loans: (status?: string) => ["payroll", "loans", status ?? "all"] as const,
  templates: ["payroll", "bank-file-templates"] as const,
  declarationCodes: (period: string) => ["payroll", "declarations", "codes", period] as const,
  declaration: (period: string, code: string) => ["payroll", "declarations", period, code] as const,
  annualRecap: (year: number) => ["payroll", "declarations", "annual", year] as const,
};

function useToken(): string {
  const { session } = useAuth();
  return session!.token;
}

// ---- rules --------------------------------------------------------------------------------

export function usePayrollSettings() {
  const token = useToken();
  return useQuery({ queryKey: PAYROLL_KEYS.settings, queryFn: () => apiFetch(token, "/payroll/settings") });
}

export function useSavePayrollSettings() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { country: string; company_address?: string | null; employer_inps_no?: string | null; employer_tax_id?: string | null }) =>
      apiFetch(token, "/payroll/settings", { method: "PUT", body }),
    onSuccess: () => client.invalidateQueries({ queryKey: PAYROLL_KEYS.settings }),
  });
}

export function useRuleSets() {
  const token = useToken();
  return useQuery<RuleSetHeader[]>({ queryKey: PAYROLL_KEYS.ruleSets, queryFn: () => apiFetch(token, "/payroll/rule-sets") });
}

export function useRuleSet(id: string | undefined) {
  const token = useToken();
  return useQuery<RuleSetDocument>({
    queryKey: PAYROLL_KEYS.ruleSet(id ?? ""),
    queryFn: () => apiFetch(token, `/payroll/rule-sets/${id}`),
    enabled: !!id,
  });
}

export function useCreateRuleSet() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => apiFetch(token, "/payroll/rule-sets", { method: "POST", body }),
    onSuccess: () => client.invalidateQueries({ queryKey: PAYROLL_KEYS.ruleSets }),
  });
}

export function useUpdateRuleSet(id: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (changes: Record<string, unknown>) => apiFetch(token, `/payroll/rule-sets/${id}`, { method: "PATCH", body: changes }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.ruleSets });
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.ruleSet(id) });
    },
  });
}

export function useDeleteRuleSet() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(token, `/payroll/rule-sets/${id}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: PAYROLL_KEYS.ruleSets }),
  });
}

export function useCopyRuleSet(id: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { valid_from: string; name: string }) => apiFetch(token, `/payroll/rule-sets/${id}/copy`, { method: "POST", body }),
    onSuccess: () => client.invalidateQueries({ queryKey: PAYROLL_KEYS.ruleSets }),
  });
}

export function useConfirmRuleSet() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(token, `/payroll/rule-sets/${id}/confirm`, { method: "POST" }),
    onSuccess: (_data, id) => {
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.ruleSets });
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.ruleSet(id) });
    },
  });
}

export function useReopenRuleSet() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(token, `/payroll/rule-sets/${id}/reopen`, { method: "POST" }),
    onSuccess: (_data, id) => {
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.ruleSets });
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.ruleSet(id) });
    },
  });
}

export function useRuleRows(ruleSetId: string, kind: RuleRowKind) {
  const token = useToken();
  return useQuery<Record<string, unknown>[]>({
    queryKey: PAYROLL_KEYS.ruleRows(ruleSetId, kind),
    queryFn: () => apiFetch(token, `/payroll/rule-sets/${ruleSetId}/${kind}`),
  });
}

export function useAddRuleRow(ruleSetId: string, kind: RuleRowKind) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (values: Record<string, unknown>) => apiFetch(token, `/payroll/rule-sets/${ruleSetId}/${kind}`, { method: "POST", body: values }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.ruleRows(ruleSetId, kind) });
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.ruleSet(ruleSetId) });
    },
  });
}

export function useUpdateRuleRow(ruleSetId: string, kind: RuleRowKind) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ rowId, changes }: { rowId: string; changes: Record<string, unknown> }) =>
      apiFetch(token, `/payroll/rule-sets/${ruleSetId}/${kind}/${rowId}`, { method: "PATCH", body: changes }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.ruleRows(ruleSetId, kind) });
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.ruleSet(ruleSetId) });
    },
  });
}

export function useDeleteRuleRow(ruleSetId: string, kind: RuleRowKind) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (rowId: string) => apiFetch(token, `/payroll/rule-sets/${ruleSetId}/${kind}/${rowId}`, { method: "DELETE" }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.ruleRows(ruleSetId, kind) });
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.ruleSet(ruleSetId) });
    },
  });
}

// ---- employees (name list for a period; no salary — 3b routes_runs.employees()) -----------

export function usePayrollEmployees(period: string) {
  const token = useToken();
  return useQuery<PayrollEmployee[]>({
    queryKey: PAYROLL_KEYS.employees(period),
    queryFn: () => apiFetch(token, `/payroll/employees?period=${period}`),
    enabled: !!period,
  });
}

// ---- runs -----------------------------------------------------------------------------------

export function useRuns(status?: string) {
  const token = useToken();
  return useQuery<PayrollRun[]>({
    queryKey: PAYROLL_KEYS.runs(status),
    queryFn: () => apiFetch(token, `/payroll/runs${status ? `?status_filter=${status}` : ""}`),
  });
}

export function useRun(id: string | undefined) {
  const token = useToken();
  return useQuery<PayrollRun>({ queryKey: PAYROLL_KEYS.run(id ?? ""), queryFn: () => apiFetch(token, `/payroll/runs/${id}`), enabled: !!id });
}

function invalidateRun(client: ReturnType<typeof useQueryClient>, runId: string) {
  client.invalidateQueries({ queryKey: PAYROLL_KEYS.runs() });
  client.invalidateQueries({ queryKey: PAYROLL_KEYS.run(runId) });
  client.invalidateQueries({ queryKey: PAYROLL_KEYS.runPayslips(runId) });
  client.invalidateQueries({ queryKey: PAYROLL_KEYS.runVariance(runId) });
}

export function useCreateRun() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { period: string; run_type: string; label?: string | null; employee_ids?: string[] | null }) =>
      apiFetch(token, "/payroll/runs", { method: "POST", body }),
    onSuccess: () => client.invalidateQueries({ queryKey: PAYROLL_KEYS.runs() }),
  });
}

export function useUpdateRun(id: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (changes: Record<string, unknown>) => apiFetch(token, `/payroll/runs/${id}`, { method: "PATCH", body: changes }),
    onSuccess: () => invalidateRun(client, id),
  });
}

export function useDeleteRun() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(token, `/payroll/runs/${id}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: PAYROLL_KEYS.runs() }),
  });
}

export function useCalculateRun() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(token, `/payroll/runs/${id}/calculate`, { method: "POST" }),
    onSuccess: (_data, id) => invalidateRun(client, id),
  });
}

export function useApproveRun() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(token, `/payroll/runs/${id}/approve`, { method: "POST" }),
    onSuccess: (_data, id) => invalidateRun(client, id),
  });
}

export function useReverseRun() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => apiFetch(token, `/payroll/runs/${id}/reverse`, { method: "POST", body: { reason } }),
    onSuccess: (_data, { id }) => invalidateRun(client, id),
  });
}

export function useMarkPaid() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(token, `/payroll/runs/${id}/mark-paid`, { method: "POST" }),
    onSuccess: (_data, id) => {
      invalidateRun(client, id);
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.runPayouts(id) });
    },
  });
}

export function useRunPayslips(runId: string | undefined) {
  const token = useToken();
  return useQuery<PayslipSummary[]>({
    queryKey: PAYROLL_KEYS.runPayslips(runId ?? ""),
    queryFn: () => apiFetch(token, `/payroll/runs/${runId}/payslips`),
    enabled: !!runId,
  });
}

export function useRunVariance(runId: string | undefined) {
  const token = useToken();
  return useQuery<RunVariance>({
    queryKey: PAYROLL_KEYS.runVariance(runId ?? ""),
    queryFn: () => apiFetch(token, `/payroll/runs/${runId}/variance`),
    enabled: !!runId,
  });
}

export function useRunPrint(runId: string | undefined) {
  const token = useToken();
  return useQuery<RunPrintDocument>({
    queryKey: PAYROLL_KEYS.runPrint(runId ?? ""),
    queryFn: () => apiFetch(token, `/payroll/runs/${runId}/print`),
    enabled: !!runId,
  });
}

// ---- final settlements ----------------------------------------------------------------------

export function useFinalSettlements(runId: string | undefined) {
  const token = useToken();
  return useQuery<FinalSettlement[]>({
    queryKey: PAYROLL_KEYS.runSettlements(runId ?? ""),
    queryFn: () => apiFetch(token, `/payroll/runs/${runId}/final-settlements`),
    enabled: !!runId,
  });
}

export function useAddFinalSettlement(runId: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { employee_id: string; unused_leave_days?: number; notice_months?: number }) =>
      apiFetch(token, `/payroll/runs/${runId}/final-settlements`, { method: "POST", body }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.runSettlements(runId) });
      invalidateRun(client, runId);
    },
  });
}

export function useUpdateFinalSettlement(runId: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ settlementId, changes }: { settlementId: string; changes: Record<string, unknown> }) =>
      apiFetch(token, `/payroll/runs/${runId}/final-settlements/${settlementId}`, { method: "PATCH", body: changes }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.runSettlements(runId) });
      invalidateRun(client, runId);
    },
  });
}

export function useRemoveFinalSettlement(runId: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (settlementId: string) => apiFetch(token, `/payroll/runs/${runId}/final-settlements/${settlementId}`, { method: "DELETE" }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.runSettlements(runId) });
      invalidateRun(client, runId);
    },
  });
}

// ---- payslips ---------------------------------------------------------------------------------

export function usePayslip(id: string | undefined) {
  const token = useToken();
  return useQuery<PayslipDetail>({ queryKey: PAYROLL_KEYS.payslip(id ?? ""), queryFn: () => apiFetch(token, `/payroll/payslips/${id}`), enabled: !!id });
}

export function useAdminUpdatePayslip(id: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (changes: { note?: string | null; payment_methods?: Record<string, unknown>[] }) =>
      apiFetch(token, `/payroll/payslips/${id}`, { method: "PATCH", body: changes }),
    onSuccess: (data: PayslipDetail) => {
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.payslip(id) });
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.runPayslips(data.run_id) });
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.runPayouts(data.run_id) });
    },
  });
}

export function useCertificate(id: string | undefined) {
  const token = useToken();
  return useQuery({ queryKey: PAYROLL_KEYS.certificate(id ?? ""), queryFn: () => apiFetch(token, `/payroll/payslips/${id}/certificate`), enabled: !!id });
}

// ---- monthly inputs -----------------------------------------------------------------------

export function useInputComponents(runId: string | undefined) {
  const token = useToken();
  return useQuery<InputComponent[]>({
    queryKey: PAYROLL_KEYS.runInputComponents(runId ?? ""),
    queryFn: () => apiFetch(token, `/payroll/runs/${runId}/input-components`),
    enabled: !!runId,
  });
}

export function useRunInputs(runId: string | undefined) {
  const token = useToken();
  return useQuery<RunInput[]>({
    queryKey: PAYROLL_KEYS.runInputs(runId ?? ""),
    queryFn: () => apiFetch(token, `/payroll/runs/${runId}/inputs`),
    enabled: !!runId,
  });
}

export function useAddRunInput(runId: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { employee_id: string; component_code: string; qty?: number | null; amount?: number | null; note?: string | null }) =>
      apiFetch(token, `/payroll/runs/${runId}/inputs`, { method: "POST", body }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.runInputs(runId) });
      invalidateRun(client, runId);
    },
  });
}

export function useUpdateRunInput(runId: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ inputId, changes }: { inputId: string; changes: Record<string, unknown> }) =>
      apiFetch(token, `/payroll/run-inputs/${inputId}`, { method: "PATCH", body: changes }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.runInputs(runId) });
      invalidateRun(client, runId);
    },
  });
}

export function useDeleteRunInput(runId: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (inputId: string) => apiFetch(token, `/payroll/run-inputs/${inputId}`, { method: "DELETE" }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: PAYROLL_KEYS.runInputs(runId) });
      invalidateRun(client, runId);
    },
  });
}

// ---- advances -----------------------------------------------------------------------------

export function useAdvances(status?: string) {
  const token = useToken();
  return useQuery<Advance[]>({
    queryKey: PAYROLL_KEYS.advances(status),
    queryFn: () => apiFetch(token, `/payroll/advances${status ? `?status_filter=${status}` : ""}`),
  });
}

export function useCreateAdvance() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { employee_id: string; amount: number; requested_on: string; deduct_period: string; note?: string | null }) =>
      apiFetch(token, "/payroll/advances", { method: "POST", body }),
    onSuccess: () => client.invalidateQueries({ queryKey: PAYROLL_KEYS.advances() }),
  });
}

export function useUpdateAdvance() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: Record<string, unknown> }) =>
      apiFetch(token, `/payroll/advances/${id}`, { method: "PATCH", body: changes }),
    onSuccess: () => client.invalidateQueries({ queryKey: PAYROLL_KEYS.advances() }),
  });
}

export function useApproveAdvance() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(token, `/payroll/advances/${id}/approve`, { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: PAYROLL_KEYS.advances() }),
  });
}

export function useCancelAdvance() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(token, `/payroll/advances/${id}/cancel`, { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: PAYROLL_KEYS.advances() }),
  });
}

// ---- loans ----------------------------------------------------------------------------------

export function useLoans(status?: string) {
  const token = useToken();
  return useQuery<Loan[]>({
    queryKey: PAYROLL_KEYS.loans(status),
    queryFn: () => apiFetch(token, `/payroll/loans${status ? `?status_filter=${status}` : ""}`),
  });
}

export function useCreateLoan() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { employee_id: string; principal: number; instalment_count: number; first_period: string; note?: string | null }) =>
      apiFetch(token, "/payroll/loans", { method: "POST", body }),
    onSuccess: () => client.invalidateQueries({ queryKey: PAYROLL_KEYS.loans() }),
  });
}

export function useUpdateLoan() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: Record<string, unknown> }) =>
      apiFetch(token, `/payroll/loans/${id}`, { method: "PATCH", body: changes }),
    onSuccess: () => client.invalidateQueries({ queryKey: PAYROLL_KEYS.loans() }),
  });
}

export function useCancelLoan() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(token, `/payroll/loans/${id}/cancel`, { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: PAYROLL_KEYS.loans() }),
  });
}

// ---- payouts --------------------------------------------------------------------------------

export function useBankTemplates() {
  const token = useToken();
  return useQuery<BankFileTemplate[]>({ queryKey: PAYROLL_KEYS.templates, queryFn: () => apiFetch(token, "/payroll/bank-file-templates") });
}

export function useCreateTemplate() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (values: Record<string, unknown>) => apiFetch(token, "/payroll/bank-file-templates", { method: "POST", body: values }),
    onSuccess: () => client.invalidateQueries({ queryKey: PAYROLL_KEYS.templates }),
  });
}

export function useUpdateTemplate() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: Record<string, unknown> }) =>
      apiFetch(token, `/payroll/bank-file-templates/${id}`, { method: "PATCH", body: changes }),
    onSuccess: () => client.invalidateQueries({ queryKey: PAYROLL_KEYS.templates }),
  });
}

export function useDeleteTemplate() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch(token, `/payroll/bank-file-templates/${id}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: PAYROLL_KEYS.templates }),
  });
}

export function usePayoutBatches(runId: string | undefined) {
  const token = useToken();
  return useQuery<PayoutBatch[]>({
    queryKey: PAYROLL_KEYS.runPayouts(runId ?? ""),
    queryFn: () => apiFetch(token, `/payroll/runs/${runId}/payouts`),
    enabled: !!runId,
  });
}

export function useGeneratePayouts(runId: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch(token, `/payroll/runs/${runId}/payouts`, { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: PAYROLL_KEYS.runPayouts(runId) }),
  });
}

export function useConfirmBatch(runId: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (batchId: string) => apiFetch(token, `/payroll/payout-batches/${batchId}/confirm`, { method: "POST" }),
    onSuccess: () => client.invalidateQueries({ queryKey: PAYROLL_KEYS.runPayouts(runId) }),
  });
}

export function batchFileUrl(batchId: string): string {
  return `/payroll/payout-batches/${batchId}/file`;
}

export function useCashSheet(batchId: string | undefined) {
  const token = useToken();
  return useQuery<CashSheet>({
    queryKey: ["payroll", "payout-batches", batchId ?? "", "cash-sheet"],
    queryFn: () => apiFetch(token, `/payroll/payout-batches/${batchId}/cash-sheet`),
    enabled: !!batchId,
  });
}

// ---- declarations -----------------------------------------------------------------------------

export function useDeclarationCodes(period: string) {
  const token = useToken();
  return useQuery<string[]>({
    queryKey: PAYROLL_KEYS.declarationCodes(period),
    queryFn: () => apiFetch(token, `/payroll/declarations/codes?period=${period}`),
    enabled: !!period,
  });
}

export function useDeclaration(period: string, code: string | undefined) {
  const token = useToken();
  return useQuery<Declaration>({
    queryKey: PAYROLL_KEYS.declaration(period, code ?? ""),
    queryFn: () => apiFetch(token, `/payroll/declarations?period=${period}&code=${code}`),
    enabled: !!period && !!code,
  });
}

export function useAnnualRecap(year: number) {
  const token = useToken();
  return useQuery<Declaration>({
    queryKey: PAYROLL_KEYS.annualRecap(year),
    queryFn: () => apiFetch(token, `/payroll/declarations/annual?year=${year}`),
    enabled: !!year,
  });
}

export function declarationCsvUrl(period: string, code: string): string {
  return `/payroll/declarations?period=${period}&code=${code}&format=csv`;
}

export function annualRecapCsvUrl(year: number): string {
  return `/payroll/declarations/annual?year=${year}&format=csv`;
}
```

- [ ] **Step 5: Write `PayrollStatusBadge.tsx`**

```tsx
// frontend/src/features/payroll/PayrollStatusBadge.tsx
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { Badge } from "../../components/ui/badge";

type Domain = "run" | "payslipBatch" | "advance" | "loan";

const VARIANT: Record<string, "outline" | "default" | "success" | "destructive"> = {
  draft: "outline",
  requested: "outline",
  generated: "outline",
  calculated: "default",
  approved: "default",
  active: "default",
  paid: "success",
  confirmed: "success",
  reversed: "destructive",
  cancelled: "destructive",
};

export function PayrollStatusBadge({ domain, status }: { domain: Domain; status: string }) {
  const { t } = useI18n();
  const key = `payroll.status.${domain}.${status}` as TranslationKey;
  return <Badge variant={VARIANT[status] ?? "outline"}>{t(key)}</Badge>;
}
```

- [ ] **Step 6: Write `PayrollTable.tsx`**

```tsx
// frontend/src/features/payroll/PayrollTable.tsx
import type { ReactNode } from "react";
import { useI18n } from "../../lib/i18n";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { ColumnFilterRow, type FilterCell } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { AppLoader } from "../../components/patterns/AppLoader";
import { EmptyState } from "../../components/patterns/EmptyState";
import { Button } from "../../components/ui/button";

export function PayrollTable<Row>({
  tableKey,
  columns,
  rows,
  rowKey,
  loading,
  emptyTitle,
  emptyDescription,
  toolbar,
  filtersActive,
  onClearFilters,
  filterCells,
  onRowClick,
}: {
  tableKey: string;
  columns: ColumnDef<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  loading: boolean;
  emptyTitle: string;
  emptyDescription: string;
  toolbar?: ReactNode;
  filtersActive?: boolean;
  onClearFilters?: () => void;
  filterCells?: FilterCell[];
  onRowClick?: (row: Row) => void;
}) {
  const { t } = useI18n();
  const { visibleColumns, colWidths, isVisible, toggleVisible, resetAll } = useTableColumns(tableKey, columns);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">{toolbar}</div>
        <div className="flex items-center gap-2">
          {filtersActive && (
            <Button variant="ghost" size="sm" onClick={onClearFilters}>
              {t("common.clearFilters")}
            </Button>
          )}
          <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
        </div>
      </div>
      {loading ? (
        <AppLoader label={t("payroll.common.loading")} className="py-10" />
      ) : rows.length === 0 ? (
        <EmptyState
          title={filtersActive ? t("payroll.common.noRowsMatchFilters") : emptyTitle}
          description={filtersActive ? undefined : emptyDescription}
        />
      ) : (
        <Table colWidths={colWidths}>
          <TableHeader>
            <TableRow>
              {visibleColumns.map((column) => (
                <TableHead key={column.key} className={column.headerClassName}>
                  {column.header}
                </TableHead>
              ))}
            </TableRow>
            {filterCells && (
              <ColumnFilterRow cells={visibleColumns.map((column) => filterCells[columns.findIndex((c) => c.key === column.key)])} />
            )}
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={rowKey(row)} onClick={onRowClick ? () => onRowClick(row) : undefined} className={onRowClick ? "cursor-pointer" : undefined}>
                {visibleColumns.map((column) => (
                  <TableCell key={column.key} className={column.cellClassName}>
                    {column.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
```

- [ ] **Step 7: Type-check**

Run (from `frontend/`): `npx tsc -b --force`
Expected: no errors (this task adds no page yet, so nothing imports `api.ts` — the check verifies the module itself compiles standalone).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/payroll/api.ts frontend/src/features/payroll/format.ts frontend/src/features/payroll/PayrollTable.tsx frontend/src/features/payroll/PayrollStatusBadge.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(payroll): query hooks, shared table and status badge for the payroll frontend

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `DraftRuleSetBanner` and the Rules screens

**Files:**
- Create: `frontend/src/features/payroll/DraftRuleSetBanner.tsx`
- Create: `frontend/src/features/payroll/rules/RulesPage.tsx`, `SettingsCard.tsx`, `RuleSetList.tsx`, `RuleSetDialog.tsx`, `CopyRuleSetDialog.tsx`, `RuleRowsTable.tsx`, `RuleRowDialog.tsx`, `ruleTables.ts`
- Modify: `frontend/src/routes/router.tsx`, `frontend/src/routes/Sidebar.tsx`, `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: `api.ts` rule-set hooks (Task 1); `StickyTabBar` (`components/patterns/StickyTabBar.tsx`); `FormField`-equivalent form primitives already in `components/ui/` (`Input`, `Select`, `Label`); React Hook Form + Zod.
- Produces (used by Tasks 3–8): `DraftRuleSetBanner({ ruleSet }: { ruleSet: { id: string; name: string; status: string } | null | undefined })` — renders nothing when `ruleSet` is missing or `ruleSet.status !== "draft"`; otherwise an amber inline banner naming the rule set and a link to `/payroll/rules?ruleSet=<id>`. `ruleTables.ts` exports `RULE_ROW_FIELDS: Record<RuleRowKind, RuleRowField[]>` (field name, label i18n key, input kind `text|number|percent|boolean|select|json`) consumed only inside Task 2's own `RuleRowDialog`.

- [ ] **Step 1: Add the i18n keys**

Add to both `en` and `fr` in `frontend/src/lib/i18n.tsx`:

```ts
// en
"nav.payroll": "Payroll",
"payroll.tabs.runs": "Runs",
"payroll.tabs.inputs": "Inputs",
"payroll.tabs.rules": "Rules",
"payroll.rules.title": "Payroll rules",
"payroll.rules.subtitle": "Country, rule sets and their rows — every value here is confirmed by the accountant before it pays anyone.",
"payroll.rules.draftBanner": "\"{name}\" is a draft rule set — payslips computed from it carry a warning until it is confirmed.",
"payroll.rules.draftBanner.link": "Open in Rules",
"payroll.rules.settings.title": "Payroll country",
"payroll.rules.settings.country": "Country (ISO code)",
"payroll.rules.settings.address": "Company address",
"payroll.rules.settings.inpsNo": "Employer INPS number",
"payroll.rules.settings.taxId": "Employer tax ID",
"payroll.rules.settings.save": "Save",
"payroll.rules.ruleSets.title": "Rule sets",
"payroll.rules.ruleSets.new": "New rule set",
"payroll.rules.ruleSets.name": "Name",
"payroll.rules.ruleSets.validFrom": "Valid from",
"payroll.rules.ruleSets.status": "Status",
"payroll.rules.ruleSets.confirm": "Confirm",
"payroll.rules.ruleSets.reopen": "Reopen",
"payroll.rules.ruleSets.copy": "Copy to new draft",
"payroll.rules.ruleSets.delete": "Delete",
"payroll.rules.ruleSets.edit": "Edit",
"payroll.rules.ruleSets.empty.title": "No rule set yet",
"payroll.rules.ruleSets.empty.description": "Create one to start configuring components, contributions and tax brackets.",
"payroll.rules.rows.components": "Components",
"payroll.rules.rows.contributions": "Contributions",
"payroll.rules.rows.tax_brackets": "Tax brackets",
"payroll.rules.rows.tax_reliefs": "Tax reliefs",
"payroll.rules.rows.seniority_scale": "Seniority scale",
"payroll.rules.rows.overtime_rates": "Overtime rates",
"payroll.rules.rows.severance_scale": "Severance scale",
"payroll.rules.rows.add": "Add row",
"payroll.rules.rows.locked": "This rule set is confirmed; reopen it as a new draft or copy it to make changes.",
"payroll.rules.rows.empty.title": "No rows yet",
"payroll.rules.rows.empty.description": "Add the rows the payroll engine needs before confirming this rule set.",
```

```ts
// fr
"nav.payroll": "Paie",
"payroll.tabs.runs": "Paies",
"payroll.tabs.inputs": "Éléments variables",
"payroll.tabs.rules": "Règles",
"payroll.rules.title": "Règles de paie",
"payroll.rules.subtitle": "Pays, jeux de règles et leurs lignes — chaque valeur ici est confirmée par le comptable avant de payer qui que ce soit.",
"payroll.rules.draftBanner": "« {name} » est un jeu de règles brouillon — les bulletins calculés avec lui portent un avertissement jusqu'à sa confirmation.",
"payroll.rules.draftBanner.link": "Ouvrir dans Règles",
"payroll.rules.settings.title": "Pays de paie",
"payroll.rules.settings.country": "Pays (code ISO)",
"payroll.rules.settings.address": "Adresse de l'entreprise",
"payroll.rules.settings.inpsNo": "Numéro INPS employeur",
"payroll.rules.settings.taxId": "Identifiant fiscal employeur",
"payroll.rules.settings.save": "Enregistrer",
"payroll.rules.ruleSets.title": "Jeux de règles",
"payroll.rules.ruleSets.new": "Nouveau jeu de règles",
"payroll.rules.ruleSets.name": "Nom",
"payroll.rules.ruleSets.validFrom": "Valide à partir de",
"payroll.rules.ruleSets.status": "Statut",
"payroll.rules.ruleSets.confirm": "Confirmer",
"payroll.rules.ruleSets.reopen": "Rouvrir",
"payroll.rules.ruleSets.copy": "Copier en nouveau brouillon",
"payroll.rules.ruleSets.delete": "Supprimer",
"payroll.rules.ruleSets.edit": "Modifier",
"payroll.rules.ruleSets.empty.title": "Aucun jeu de règles",
"payroll.rules.ruleSets.empty.description": "Créez-en un pour configurer les rubriques, cotisations et tranches d'impôt.",
"payroll.rules.rows.components": "Rubriques",
"payroll.rules.rows.contributions": "Cotisations",
"payroll.rules.rows.tax_brackets": "Tranches d'impôt",
"payroll.rules.rows.tax_reliefs": "Abattements",
"payroll.rules.rows.seniority_scale": "Barème d'ancienneté",
"payroll.rules.rows.overtime_rates": "Taux d'heures supplémentaires",
"payroll.rules.rows.severance_scale": "Barème d'indemnité de licenciement",
"payroll.rules.rows.add": "Ajouter une ligne",
"payroll.rules.rows.locked": "Ce jeu de règles est confirmé ; rouvrez-le en brouillon ou copiez-le pour le modifier.",
"payroll.rules.rows.empty.title": "Aucune ligne",
"payroll.rules.rows.empty.description": "Ajoutez les lignes dont le moteur de paie a besoin avant de confirmer ce jeu de règles.",
```

- [ ] **Step 2: Write `DraftRuleSetBanner.tsx`**

```tsx
// frontend/src/features/payroll/DraftRuleSetBanner.tsx
import { Link } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { useI18n } from "../../lib/i18n";

export function DraftRuleSetBanner({ ruleSet }: { ruleSet: { id: string; name: string; status: string } | null | undefined }) {
  const { t } = useI18n();
  if (!ruleSet || ruleSet.status !== "draft") return null;
  return (
    <div className="flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
      <AlertTriangle className="h-4 w-4 shrink-0" />
      <span>{t("payroll.rules.draftBanner").replace("{name}", ruleSet.name)}</span>
      <Link to={`/payroll/rules?ruleSet=${ruleSet.id}`} className="ml-auto underline">
        {t("payroll.rules.draftBanner.link")}
      </Link>
    </div>
  );
}
```

Note: the platform's `t()` returns fixed strings only (no interpolation) per `erp-platform-architecture` SKILL.md, so `.replace("{name}", ...)` on the returned string is the accepted pattern for this one dynamic fragment (a name), matching the "keep the fully-dynamic part outside `t()`" rule.

- [ ] **Step 3: Write `ruleTables.ts`**

```ts
// frontend/src/features/payroll/rules/ruleTables.ts
import type { RuleRowKind } from "../api";
import type { TranslationKey } from "../../../lib/i18n";

export interface RuleRowField {
  name: string;
  labelKey: TranslationKey;
  kind: "text" | "number" | "percent" | "boolean" | "select" | "json";
  options?: string[];
}

// Field lists mirror the columns 3a Task 1's migration + Task 10's CHILD_KINDS declare for each
// table exactly (payroll.components / contributions / tax_brackets / tax_reliefs /
// seniority_scale / overtime_rates / severance_scale).
export const RULE_ROW_FIELDS: Record<RuleRowKind, RuleRowField[]> = {
  components: [
    { name: "code", labelKey: "payroll.ruleRow.code", kind: "text" },
    { name: "name_en", labelKey: "payroll.ruleRow.nameEn", kind: "text" },
    { name: "name_fr", labelKey: "payroll.ruleRow.nameFr", kind: "text" },
    { name: "kind", labelKey: "payroll.ruleRow.kind", kind: "select", options: ["earning", "deduction", "employer_charge"] },
    { name: "taxable", labelKey: "payroll.ruleRow.taxable", kind: "boolean" },
    { name: "contributable", labelKey: "payroll.ruleRow.contributable", kind: "boolean" },
    { name: "formula_type", labelKey: "payroll.ruleRow.formulaType", kind: "select", options: ["fixed", "rate_x_base", "qty_x_rate", "per_day"] },
    { name: "base_ref", labelKey: "payroll.ruleRow.baseRef", kind: "select", options: ["base_salary", "earned_base", "gross", "contributable"] },
    { name: "default_amount", labelKey: "payroll.ruleRow.defaultAmount", kind: "number" },
    { name: "default_rate", labelKey: "payroll.ruleRow.defaultRate", kind: "percent" },
    { name: "display_order", labelKey: "payroll.ruleRow.displayOrder", kind: "number" },
    { name: "payslip_section", labelKey: "payroll.ruleRow.payslipSection", kind: "select", options: ["earnings", "deductions", "employer"] },
    { name: "declaration_code", labelKey: "payroll.ruleRow.declarationCode", kind: "text" },
  ],
  contributions: [
    { name: "code", labelKey: "payroll.ruleRow.code", kind: "text" },
    { name: "name_en", labelKey: "payroll.ruleRow.nameEn", kind: "text" },
    { name: "name_fr", labelKey: "payroll.ruleRow.nameFr", kind: "text" },
    { name: "base", labelKey: "payroll.ruleRow.base", kind: "select", options: ["gross", "contributable"] },
    { name: "employee_rate", labelKey: "payroll.ruleRow.employeeRate", kind: "percent" },
    { name: "employer_rate", labelKey: "payroll.ruleRow.employerRate", kind: "percent" },
    { name: "ceiling_monthly", labelKey: "payroll.ruleRow.ceilingMonthly", kind: "number" },
    { name: "deductible_from_taxable", labelKey: "payroll.ruleRow.deductibleFromTaxable", kind: "boolean" },
    { name: "declaration_code", labelKey: "payroll.ruleRow.declarationCode", kind: "text" },
    { name: "liability_account_code", labelKey: "payroll.ruleRow.liabilityAccountCode", kind: "text" },
    { name: "display_order", labelKey: "payroll.ruleRow.displayOrder", kind: "number" },
  ],
  tax_brackets: [
    { name: "tax_code", labelKey: "payroll.ruleRow.taxCode", kind: "text" },
    { name: "lower_bound", labelKey: "payroll.ruleRow.lowerBound", kind: "number" },
    { name: "upper_bound", labelKey: "payroll.ruleRow.upperBound", kind: "number" },
    { name: "rate", labelKey: "payroll.ruleRow.rate", kind: "percent" },
    { name: "annualised", labelKey: "payroll.ruleRow.annualised", kind: "boolean" },
  ],
  tax_reliefs: [
    { name: "tax_code", labelKey: "payroll.ruleRow.taxCode", kind: "text" },
    { name: "kind", labelKey: "payroll.ruleRow.kind", kind: "select", options: ["family", "professional_expenses"] },
    { name: "parameters", labelKey: "payroll.ruleRow.parameters", kind: "json" },
  ],
  seniority_scale: [
    { name: "years_from", labelKey: "payroll.ruleRow.yearsFrom", kind: "number" },
    { name: "percent", labelKey: "payroll.ruleRow.percent", kind: "percent" },
  ],
  overtime_rates: [
    { name: "band_code", labelKey: "payroll.ruleRow.bandCode", kind: "select", options: ["day", "night", "rest_holiday"] },
    { name: "multiplier", labelKey: "payroll.ruleRow.multiplier", kind: "number" },
  ],
  severance_scale: [
    { name: "years_from", labelKey: "payroll.ruleRow.yearsFrom", kind: "number" },
    { name: "percent_per_year", labelKey: "payroll.ruleRow.percentPerYear", kind: "percent" },
  ],
};

export const RULE_ROW_KINDS: RuleRowKind[] = [
  "components", "contributions", "tax_brackets", "tax_reliefs", "seniority_scale", "overtime_rates", "severance_scale",
];
```

Add the `payroll.ruleRow.*` keys used above to both `en`/`fr` in `frontend/src/lib/i18n.tsx` (one key per distinct field label: `code, nameEn, nameFr, kind, taxable, contributable, formulaType, baseRef, defaultAmount, defaultRate, displayOrder, payslipSection, declarationCode, base, employeeRate, employerRate, ceilingMonthly, deductibleFromTaxable, liabilityAccountCode, taxCode, lowerBound, upperBound, rate, annualised, parameters, yearsFrom, percent, bandCode, multiplier, percentPerYear`) — e.g. `"payroll.ruleRow.code": "Code"` / `"payroll.ruleRow.code": "Code"` (identical in both languages is acceptable for short technical field labels already used this way elsewhere in the codebase, e.g. warehouse SKU codes).

- [ ] **Step 4: Write `SettingsCard.tsx`**

```tsx
// frontend/src/features/payroll/rules/SettingsCard.tsx
import { useEffect, useState } from "react";
import { useI18n } from "../../../lib/i18n";
import { usePayrollSettings, useSavePayrollSettings } from "../api";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Button } from "../../../components/ui/button";
import { toast } from "../../../components/ui/use-toast";

export function SettingsCard() {
  const { t } = useI18n();
  const { data: settings, isLoading } = usePayrollSettings();
  const save = useSavePayrollSettings();
  const [country, setCountry] = useState("");
  const [address, setAddress] = useState("");
  const [inpsNo, setInpsNo] = useState("");
  const [taxId, setTaxId] = useState("");

  useEffect(() => {
    if (settings) {
      setCountry(settings.country ?? "");
      setAddress(settings.company_address ?? "");
      setInpsNo(settings.employer_inps_no ?? "");
      setTaxId(settings.employer_tax_id ?? "");
    }
  }, [settings]);

  if (isLoading) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("payroll.rules.settings.title")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 sm:grid-cols-2">
        <div>
          <Label>{t("payroll.rules.settings.country")}</Label>
          <Input value={country} onChange={(event) => setCountry(event.target.value)} maxLength={2} />
        </div>
        <div>
          <Label>{t("payroll.rules.settings.inpsNo")}</Label>
          <Input value={inpsNo} onChange={(event) => setInpsNo(event.target.value)} />
        </div>
        <div className="sm:col-span-2">
          <Label>{t("payroll.rules.settings.address")}</Label>
          <Input value={address} onChange={(event) => setAddress(event.target.value)} />
        </div>
        <div>
          <Label>{t("payroll.rules.settings.taxId")}</Label>
          <Input value={taxId} onChange={(event) => setTaxId(event.target.value)} />
        </div>
        <div className="sm:col-span-2">
          <Button
            onClick={() =>
              save.mutate(
                { country, company_address: address || null, employer_inps_no: inpsNo || null, employer_tax_id: taxId || null },
                { onError: (error: unknown) => toast({ title: (error as Error).message, variant: "destructive" }) },
              )
            }
            disabled={save.isPending}
          >
            {t("payroll.rules.settings.save")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 5: Write `RuleSetDialog.tsx` and `CopyRuleSetDialog.tsx`**

```tsx
// frontend/src/features/payroll/rules/RuleSetDialog.tsx
import { useEffect, useState } from "react";
import { useI18n } from "../../../lib/i18n";
import { useCreateRuleSet, useUpdateRuleSet, type RuleSetHeader } from "../api";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Button } from "../../../components/ui/button";
import { toast } from "../../../components/ui/use-toast";
import { monthInputValue, parseMonthInput } from "../format";

export function RuleSetDialog({ open, onOpenChange, ruleSet }: { open: boolean; onOpenChange: (open: boolean) => void; ruleSet?: RuleSetHeader }) {
  const { t } = useI18n();
  const create = useCreateRuleSet();
  const update = useUpdateRuleSet(ruleSet?.id ?? "");
  const [country, setCountry] = useState(ruleSet?.country ?? "");
  const [name, setName] = useState(ruleSet?.name ?? "");
  const [validFrom, setValidFrom] = useState(ruleSet ? monthInputValue(ruleSet.valid_from) : "");
  const [workingDays, setWorkingDays] = useState(ruleSet?.working_days_per_month?.toString() ?? "26");
  const [workingHours, setWorkingHours] = useState(ruleSet?.working_hours_per_month?.toString() ?? "208");

  useEffect(() => {
    if (open) {
      setCountry(ruleSet?.country ?? "");
      setName(ruleSet?.name ?? "");
      setValidFrom(ruleSet ? monthInputValue(ruleSet.valid_from) : "");
      setWorkingDays(ruleSet?.working_days_per_month?.toString() ?? "26");
      setWorkingHours(ruleSet?.working_hours_per_month?.toString() ?? "208");
    }
  }, [open, ruleSet]);

  const submit = () => {
    const body = {
      country: country.toUpperCase(),
      name,
      valid_from: parseMonthInput(validFrom),
      working_days_per_month: Number(workingDays),
      working_hours_per_month: Number(workingHours),
    };
    const mutation = ruleSet ? update.mutateAsync(body) : create.mutateAsync(body);
    mutation.then(() => onOpenChange(false)).catch((error: Error) => toast({ title: error.message, variant: "destructive" }));
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{ruleSet ? t("payroll.rules.ruleSets.edit") : t("payroll.rules.ruleSets.new")}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-3">
          <div>
            <Label>{t("payroll.rules.settings.country")}</Label>
            <Input value={country} maxLength={2} onChange={(event) => setCountry(event.target.value)} />
          </div>
          <div>
            <Label>{t("payroll.rules.ruleSets.name")}</Label>
            <Input value={name} onChange={(event) => setName(event.target.value)} />
          </div>
          <div>
            <Label>{t("payroll.rules.ruleSets.validFrom")}</Label>
            <Input type="month" value={validFrom} onChange={(event) => setValidFrom(event.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>{t("payroll.ruleSetForm.workingDays")}</Label>
              <Input type="number" value={workingDays} onChange={(event) => setWorkingDays(event.target.value)} />
            </div>
            <div>
              <Label>{t("payroll.ruleSetForm.workingHours")}</Label>
              <Input type="number" value={workingHours} onChange={(event) => setWorkingHours(event.target.value)} />
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={create.isPending || update.isPending}>
            {t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

Add `"payroll.ruleSetForm.workingDays": "Working days / month"` / `"Jours ouvrés / mois"` and `"payroll.ruleSetForm.workingHours": "Working hours / month"` / `"Heures ouvrées / mois"` to `i18n.tsx`.

```tsx
// frontend/src/features/payroll/rules/CopyRuleSetDialog.tsx
import { useState } from "react";
import { useI18n } from "../../../lib/i18n";
import { useCopyRuleSet, type RuleSetHeader } from "../api";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Button } from "../../../components/ui/button";
import { toast } from "../../../components/ui/use-toast";
import { parseMonthInput } from "../format";

export function CopyRuleSetDialog({ open, onOpenChange, ruleSet }: { open: boolean; onOpenChange: (open: boolean) => void; ruleSet: RuleSetHeader }) {
  const { t } = useI18n();
  const copy = useCopyRuleSet(ruleSet.id);
  const [name, setName] = useState(`${ruleSet.name} (copy)`);
  const [validFrom, setValidFrom] = useState("");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("payroll.rules.ruleSets.copy")}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-3">
          <div>
            <Label>{t("payroll.rules.ruleSets.name")}</Label>
            <Input value={name} onChange={(event) => setName(event.target.value)} />
          </div>
          <div>
            <Label>{t("payroll.rules.ruleSets.validFrom")}</Label>
            <Input type="month" value={validFrom} onChange={(event) => setValidFrom(event.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button
            disabled={!validFrom || copy.isPending}
            onClick={() =>
              copy
                .mutateAsync({ name, valid_from: parseMonthInput(validFrom) })
                .then(() => onOpenChange(false))
                .catch((error: Error) => toast({ title: error.message, variant: "destructive" }))
            }
          >
            {t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 6: Write `RuleSetList.tsx`**

```tsx
// frontend/src/features/payroll/rules/RuleSetList.tsx
import { useState } from "react";
import { useI18n } from "../../../lib/i18n";
import { useConfirmRuleSet, useDeleteRuleSet, useReopenRuleSet, useRuleSets, type RuleSetHeader } from "../api";
import { PayrollTable } from "../PayrollTable";
import { Button } from "../../../components/ui/button";
import { toast } from "../../../components/ui/use-toast";
import { RuleSetDialog } from "./RuleSetDialog";
import { CopyRuleSetDialog } from "./CopyRuleSetDialog";
import { formatPeriod } from "../format";
import { useI18nLocale } from "../../../lib/i18n";

export function RuleSetList({ selectedId, onSelect }: { selectedId: string | null; onSelect: (id: string) => void }) {
  const { t } = useI18n();
  const locale = useI18nLocale();
  const { data: ruleSets = [], isLoading } = useRuleSets();
  const confirm = useConfirmRuleSet();
  const reopen = useReopenRuleSet();
  const del = useDeleteRuleSet();
  const [dialogSet, setDialogSet] = useState<RuleSetHeader | "new" | null>(null);
  const [copySet, setCopySet] = useState<RuleSetHeader | null>(null);

  const columns = [
    { key: "name", header: t("payroll.rules.ruleSets.name"), cell: (row: RuleSetHeader) => row.name, defaultWidth: 200 },
    { key: "country", header: t("payroll.rules.settings.country"), cell: (row: RuleSetHeader) => row.country, defaultWidth: 90 },
    { key: "validFrom", header: t("payroll.rules.ruleSets.validFrom"), cell: (row: RuleSetHeader) => formatPeriod(row.valid_from, locale), defaultWidth: 160 },
    {
      key: "status",
      header: t("payroll.rules.ruleSets.status"),
      cell: (row: RuleSetHeader) => t(`payroll.status.run.${row.status === "confirmed" ? "approved" : "draft"}` as never),
      defaultWidth: 120,
    },
    {
      key: "actions",
      header: "",
      alwaysVisible: true,
      cell: (row: RuleSetHeader) => (
        <div className="flex gap-1">
          {row.status === "draft" ? (
            <>
              <Button size="sm" variant="ghost" onClick={() => setDialogSet(row)}>
                {t("payroll.rules.ruleSets.edit")}
              </Button>
              <Button
                size="sm"
                onClick={() => confirm.mutate(row.id, { onError: (error: unknown) => toast({ title: (error as Error).message, variant: "destructive" }) })}
              >
                {t("payroll.rules.ruleSets.confirm")}
              </Button>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => del.mutate(row.id, { onError: (error: unknown) => toast({ title: (error as Error).message, variant: "destructive" }) })}
              >
                {t("payroll.rules.ruleSets.delete")}
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              variant="outline"
              onClick={() => reopen.mutate(row.id, { onError: (error: unknown) => toast({ title: (error as Error).message, variant: "destructive" }) })}
            >
              {t("payroll.rules.ruleSets.reopen")}
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={() => setCopySet(row)}>
            {t("payroll.rules.ruleSets.copy")}
          </Button>
        </div>
      ),
    },
  ];

  return (
    <>
      <PayrollTable
        tableKey="payroll.rules.ruleSets"
        columns={columns}
        rows={ruleSets}
        rowKey={(row) => row.id}
        loading={isLoading}
        emptyTitle={t("payroll.rules.ruleSets.empty.title")}
        emptyDescription={t("payroll.rules.ruleSets.empty.description")}
        onRowClick={(row) => onSelect(row.id)}
        toolbar={<Button onClick={() => setDialogSet("new")}>{t("payroll.rules.ruleSets.new")}</Button>}
      />
      {ruleSets.map((row) => row.id === selectedId && <span key={row.id} className="hidden" />)}
      {dialogSet && (
        <RuleSetDialog open onOpenChange={(open) => !open && setDialogSet(null)} ruleSet={dialogSet === "new" ? undefined : dialogSet} />
      )}
      {copySet && <CopyRuleSetDialog open onOpenChange={(open) => !open && setCopySet(null)} ruleSet={copySet} />}
    </>
  );
}
```

Note: `useI18nLocale` must already exist in `frontend/src/lib/i18n.tsx` (it backs `LanguageToggle`'s current-language read); if the actual exported hook has a different name, use whatever `i18n.tsx` exports for reading the current language (its `Language` type / provider is already read in Step 1's grep of the file) — do not add a second locale hook.

- [ ] **Step 7: Write `RuleRowDialog.tsx` and `RuleRowsTable.tsx`**

```tsx
// frontend/src/features/payroll/rules/RuleRowDialog.tsx
import { useState } from "react";
import { useI18n } from "../../../lib/i18n";
import { useAddRuleRow, useUpdateRuleRow, type RuleRowKind } from "../api";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Button } from "../../../components/ui/button";
import { Checkbox } from "../../../components/ui/checkbox";
import { Select } from "../../../components/ui/select";
import { toast } from "../../../components/ui/use-toast";
import { RULE_ROW_FIELDS } from "./ruleTables";

export function RuleRowDialog({
  open,
  onOpenChange,
  ruleSetId,
  kind,
  row,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  ruleSetId: string;
  kind: RuleRowKind;
  row?: Record<string, unknown>;
}) {
  const { t } = useI18n();
  const add = useAddRuleRow(ruleSetId, kind);
  const update = useUpdateRuleRow(ruleSetId, kind);
  const fields = RULE_ROW_FIELDS[kind];
  const [values, setValues] = useState<Record<string, string | boolean>>(
    Object.fromEntries(fields.map((field) => [field.name, row?.[field.name] === undefined || row?.[field.name] === null ? (field.kind === "boolean" ? false : "") : String(row[field.name])])),
  );

  const submit = () => {
    const body: Record<string, unknown> = {};
    for (const field of fields) {
      const raw = values[field.name];
      if (field.kind === "boolean") body[field.name] = Boolean(raw);
      else if (field.kind === "number" || field.kind === "percent") body[field.name] = raw === "" ? null : Number(raw);
      else if (field.kind === "json") body[field.name] = raw === "" ? {} : JSON.parse(String(raw));
      else body[field.name] = raw === "" ? null : raw;
    }
    const mutation = row ? update.mutateAsync({ rowId: row.id as string, changes: body }) : add.mutateAsync(body);
    mutation.then(() => onOpenChange(false)).catch((error: Error) => toast({ title: error.message, variant: "destructive" }));
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(`payroll.rules.rows.${kind}` as never)}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          {fields.map((field) => (
            <div key={field.name} className={field.kind === "json" ? "sm:col-span-2" : undefined}>
              <Label>{t(field.labelKey)}</Label>
              {field.kind === "boolean" ? (
                <Checkbox checked={Boolean(values[field.name])} onCheckedChange={(checked) => setValues((v) => ({ ...v, [field.name]: Boolean(checked) }))} />
              ) : field.kind === "select" ? (
                <Select value={String(values[field.name] ?? "")} onChange={(event) => setValues((v) => ({ ...v, [field.name]: event.target.value }))}>
                  <option value="" />
                  {field.options?.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </Select>
              ) : (
                <Input
                  value={String(values[field.name] ?? "")}
                  type={field.kind === "number" || field.kind === "percent" ? "number" : "text"}
                  onChange={(event) => setValues((v) => ({ ...v, [field.name]: event.target.value }))}
                />
              )}
            </div>
          ))}
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={add.isPending || update.isPending}>
            {t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

```tsx
// frontend/src/features/payroll/rules/RuleRowsTable.tsx
import { useState } from "react";
import { useI18n } from "../../../lib/i18n";
import { useDeleteRuleRow, useRuleRows, type RuleRowKind } from "../api";
import { RULE_ROW_FIELDS, RULE_ROW_KINDS } from "./ruleTables";
import { RuleRowDialog } from "./RuleRowDialog";
import { PayrollTable } from "../PayrollTable";
import { Button } from "../../../components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../../../components/ui/tabs";
import { toast } from "../../../components/ui/use-toast";

function KindTable({ ruleSetId, kind, locked }: { ruleSetId: string; kind: RuleRowKind; locked: boolean }) {
  const { t } = useI18n();
  const { data: rows = [], isLoading } = useRuleRows(ruleSetId, kind);
  const del = useDeleteRuleRow(ruleSetId, kind);
  const [dialogRow, setDialogRow] = useState<Record<string, unknown> | "new" | null>(null);
  const fields = RULE_ROW_FIELDS[kind];

  const columns = [
    ...fields.map((field) => ({
      key: field.name,
      header: t(field.labelKey),
      cell: (row: Record<string, unknown>) => (field.kind === "boolean" ? (row[field.name] ? "✓" : "") : String(row[field.name] ?? "")),
    })),
    ...(locked
      ? []
      : [
          {
            key: "actions",
            header: "",
            alwaysVisible: true,
            cell: (row: Record<string, unknown>) => (
              <div className="flex gap-1">
                <Button size="sm" variant="ghost" onClick={() => setDialogRow(row)}>
                  {t("payroll.rules.ruleSets.edit")}
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => del.mutate(row.id as string, { onError: (error: unknown) => toast({ title: (error as Error).message, variant: "destructive" }) })}
                >
                  {t("payroll.rules.ruleSets.delete")}
                </Button>
              </div>
            ),
          },
        ]),
  ];

  return (
    <>
      <PayrollTable
        tableKey={`payroll.rules.rows.${kind}`}
        columns={columns}
        rows={rows}
        rowKey={(row) => row.id as string}
        loading={isLoading}
        emptyTitle={t("payroll.rules.rows.empty.title")}
        emptyDescription={t("payroll.rules.rows.empty.description")}
        toolbar={!locked && <Button onClick={() => setDialogRow("new")}>{t("payroll.rules.rows.add")}</Button>}
      />
      {dialogRow && (
        <RuleRowDialog
          open
          onOpenChange={(open) => !open && setDialogRow(null)}
          ruleSetId={ruleSetId}
          kind={kind}
          row={dialogRow === "new" ? undefined : dialogRow}
        />
      )}
    </>
  );
}

export function RuleRowsTable({ ruleSetId, locked }: { ruleSetId: string; locked: boolean }) {
  const { t } = useI18n();
  return (
    <div className="space-y-3">
      {locked && <p className="text-sm text-muted-foreground">{t("payroll.rules.rows.locked")}</p>}
      <Tabs defaultValue={RULE_ROW_KINDS[0]}>
        <TabsList>
          {RULE_ROW_KINDS.map((kind) => (
            <TabsTrigger key={kind} value={kind}>
              {t(`payroll.rules.rows.${kind}` as never)}
            </TabsTrigger>
          ))}
        </TabsList>
        {RULE_ROW_KINDS.map((kind) => (
          <TabsContent key={kind} value={kind}>
            <KindTable ruleSetId={ruleSetId} kind={kind} locked={locked} />
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
```

- [ ] **Step 8: Write `RulesPage.tsx`**

```tsx
// frontend/src/features/payroll/rules/RulesPage.tsx
import { useSearchParams } from "react-router-dom";
import { useI18n } from "../../../lib/i18n";
import { useRuleSet } from "../api";
import { SettingsCard } from "./SettingsCard";
import { RuleSetList } from "./RuleSetList";
import { RuleRowsTable } from "./RuleRowsTable";
import { DraftRuleSetBanner } from "../DraftRuleSetBanner";

export function RulesPage() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("ruleSet");
  const { data: ruleSet } = useRuleSet(selectedId ?? undefined);

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">{t("payroll.rules.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("payroll.rules.subtitle")}</p>
      </div>
      <SettingsCard />
      <RuleSetList selectedId={selectedId} onSelect={(id) => setParams({ ruleSet: id })} />
      {ruleSet && (
        <div className="space-y-3">
          <DraftRuleSetBanner ruleSet={ruleSet} />
          <h2 className="text-lg font-medium">{ruleSet.name}</h2>
          <RuleRowsTable ruleSetId={ruleSet.id} locked={ruleSet.status === "confirmed"} />
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 9: Wire the route, sidebar and nav**

In `frontend/src/routes/router.tsx`, add `import { RulesPage } from "../features/payroll/rules/RulesPage";` and, in `protectedChildren`, `{ path: "/payroll/rules", element: <RulesPage /> },` (this task's page; Tasks 3–5 add the other `/payroll/*` routes to the same array in later commits).

In `frontend/src/routes/Sidebar.tsx`, add a new `NAV_GROUPS` entry (its own group, matching the shape of the existing `nav.hr` / `nav.finance` groups):

```ts
  {
    labelKey: "nav.payroll",
    items: [
      { to: "/payroll/runs", labelKey: "payroll.tabs.runs", icon: Wallet, permission: "payroll.view_runs" },
      { to: "/payroll/inputs", labelKey: "payroll.tabs.inputs", icon: ListChecks, permission: "payroll.view_runs" },
      { to: "/payroll/rules", labelKey: "payroll.tabs.rules", icon: Settings2, permission: "payroll.view_rules" },
    ],
  },
```

Add `Wallet, ListChecks, Settings2` to the `lucide-react` import at the top of `Sidebar.tsx` if not already imported (check the existing import line first — several icons from this set are likely already imported for other groups; reuse rather than re-import).

- [ ] **Step 10: Type-check**

Run (from `frontend/`): `npx tsc -b --force`
Expected: no errors. If `useI18nLocale` (Step 6) does not exist under that name, fix the import to the actual exported name from `frontend/src/lib/i18n.tsx` and re-run.

- [ ] **Step 11: Commit**

```bash
git add frontend/src/features/payroll/DraftRuleSetBanner.tsx frontend/src/features/payroll/rules frontend/src/routes/router.tsx frontend/src/routes/Sidebar.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(payroll): Rules screens (settings, rule sets, rule rows) with a draft-rule-set banner

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Runs list and create dialog

**Files:**
- Create: `frontend/src/features/payroll/runs/RunsPage.tsx`, `RunDialog.tsx`
- Modify: `frontend/src/routes/router.tsx`, `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: `useRuns`, `useCreateRun`, `useDeleteRun` (Task 1 `api.ts`); `PayrollTable`, `PayrollStatusBadge`, `DraftRuleSetBanner` (Tasks 1–2); `FilterTabs`.
- Produces: `/payroll/runs` route. `RunDialog` is reused nowhere else (creation only — editing a run's label/employee_ids happens inline on `RunPage`, Task 4).

- [ ] **Step 1: Add the i18n keys**

```ts
// en
"payroll.runs.title": "Payroll runs",
"payroll.runs.subtitle": "One regular run per month, plus off-cycle runs for corrections and final settlements.",
"payroll.runs.new": "New run",
"payroll.runs.column.period": "Period",
"payroll.runs.column.type": "Type",
"payroll.runs.column.status": "Status",
"payroll.runs.column.payslips": "Payslips",
"payroll.runs.column.gross": "Gross",
"payroll.runs.column.net": "Net",
"payroll.runs.column.warnings": "Warnings",
"payroll.runs.type.regular": "Regular",
"payroll.runs.type.off_cycle": "Off-cycle",
"payroll.runs.empty.title": "No payroll run yet",
"payroll.runs.empty.description": "Create the month's regular run, or an off-cycle run for a correction or a final settlement.",
"payroll.runs.filter.all": "All",
"payroll.runDialog.title": "New payroll run",
"payroll.runDialog.period": "Period",
"payroll.runDialog.type": "Run type",
"payroll.runDialog.label": "Label",
"payroll.runDialog.employees": "Employees (off-cycle only)",
```

```ts
// fr
"payroll.runs.title": "Paies",
"payroll.runs.subtitle": "Une paie normale par mois, plus des paies hors cycle pour les corrections et soldes de tout compte.",
"payroll.runs.new": "Nouvelle paie",
"payroll.runs.column.period": "Période",
"payroll.runs.column.type": "Type",
"payroll.runs.column.status": "Statut",
"payroll.runs.column.payslips": "Bulletins",
"payroll.runs.column.gross": "Brut",
"payroll.runs.column.net": "Net",
"payroll.runs.column.warnings": "Avertissements",
"payroll.runs.type.regular": "Normale",
"payroll.runs.type.off_cycle": "Hors cycle",
"payroll.runs.empty.title": "Aucune paie",
"payroll.runs.empty.description": "Créez la paie normale du mois, ou une paie hors cycle pour une correction ou un solde de tout compte.",
"payroll.runs.filter.all": "Toutes",
"payroll.runDialog.title": "Nouvelle paie",
"payroll.runDialog.period": "Période",
"payroll.runDialog.type": "Type de paie",
"payroll.runDialog.label": "Libellé",
"payroll.runDialog.employees": "Employés (hors cycle uniquement)",
```

- [ ] **Step 2: Write `RunDialog.tsx`**

```tsx
// frontend/src/features/payroll/runs/RunDialog.tsx
import { useState } from "react";
import { useI18n } from "../../../lib/i18n";
import { useCreateRun, usePayrollEmployees } from "../api";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Button } from "../../../components/ui/button";
import { Select } from "../../../components/ui/select";
import { toast } from "../../../components/ui/use-toast";
import { parseMonthInput } from "../format";
import { useNavigate } from "react-router-dom";

export function RunDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const create = useCreateRun();
  const [period, setPeriod] = useState("");
  const [runType, setRunType] = useState<"regular" | "off_cycle">("regular");
  const [label, setLabel] = useState("");
  const [employeeIds, setEmployeeIds] = useState<string[]>([]);
  const { data: employees = [] } = usePayrollEmployees(period ? parseMonthInput(period) : "");

  const submit = () => {
    create
      .mutateAsync({
        period: parseMonthInput(period),
        run_type: runType,
        label: label || null,
        employee_ids: runType === "off_cycle" ? employeeIds : null,
      })
      .then((run: { id: string }) => {
        onOpenChange(false);
        navigate(`/payroll/runs/${run.id}`);
      })
      .catch((error: Error) => toast({ title: error.message, variant: "destructive" }));
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("payroll.runDialog.title")}</DialogTitle>
        </DialogHeader>
        <div className="grid gap-3">
          <div>
            <Label>{t("payroll.runDialog.period")}</Label>
            <Input type="month" value={period} onChange={(event) => setPeriod(event.target.value)} />
          </div>
          <div>
            <Label>{t("payroll.runDialog.type")}</Label>
            <Select value={runType} onChange={(event) => setRunType(event.target.value as "regular" | "off_cycle")}>
              <option value="regular">{t("payroll.runs.type.regular")}</option>
              <option value="off_cycle">{t("payroll.runs.type.off_cycle")}</option>
            </Select>
          </div>
          <div>
            <Label>{t("payroll.runDialog.label")}</Label>
            <Input value={label} onChange={(event) => setLabel(event.target.value)} />
          </div>
          {runType === "off_cycle" && (
            <div>
              <Label>{t("payroll.runDialog.employees")}</Label>
              <select
                multiple
                className="h-32 w-full rounded-md border border-input bg-background p-2 text-sm"
                value={employeeIds}
                onChange={(event) => setEmployeeIds(Array.from(event.target.selectedOptions, (option) => option.value))}
              >
                {employees.map((employee) => (
                  <option key={employee.employee_id} value={employee.employee_id}>
                    {employee.full_name} ({employee.employee_no})
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={!period || create.isPending}>
            {t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 3: Write `RunsPage.tsx`**

```tsx
// frontend/src/features/payroll/runs/RunsPage.tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useI18n } from "../../../lib/i18n";
import { useRuns, type PayrollRun } from "../api";
import { PayrollTable } from "../PayrollTable";
import { PayrollStatusBadge } from "../PayrollStatusBadge";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { Button } from "../../../components/ui/button";
import { RunDialog } from "./RunDialog";
import { formatXof, formatPeriod } from "../format";
import { useI18nLocale } from "../../../lib/i18n";

const STATUSES = ["all", "draft", "calculated", "approved", "paid", "reversed"] as const;

export function RunsPage() {
  const { t } = useI18n();
  const locale = useI18nLocale();
  const navigate = useNavigate();
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("all");
  const { data: runs = [], isLoading } = useRuns(status === "all" ? undefined : status);
  const [dialogOpen, setDialogOpen] = useState(false);

  const columns = [
    { key: "period", header: t("payroll.runs.column.period"), cell: (row: PayrollRun) => formatPeriod(row.period, locale), defaultWidth: 160 },
    { key: "type", header: t("payroll.runs.column.type"), cell: (row: PayrollRun) => t(`payroll.runs.type.${row.run_type}` as never), defaultWidth: 120 },
    { key: "label", header: t("payroll.runDialog.label"), cell: (row: PayrollRun) => row.label ?? "—", defaultWidth: 160 },
    { key: "status", header: t("payroll.runs.column.status"), cell: (row: PayrollRun) => <PayrollStatusBadge domain="run" status={row.status} />, defaultWidth: 130 },
    { key: "payslips", header: t("payroll.runs.column.payslips"), cell: (row: PayrollRun) => row.payslip_count, defaultWidth: 100 },
    { key: "gross", header: t("payroll.runs.column.gross"), cell: (row: PayrollRun) => formatXof(row.gross, locale), defaultWidth: 150 },
    { key: "net", header: t("payroll.runs.column.net"), cell: (row: PayrollRun) => formatXof(row.net, locale), defaultWidth: 150 },
    {
      key: "warnings",
      header: t("payroll.runs.column.warnings"),
      cell: (row: PayrollRun) => (row.warning_count > 0 ? <span className="text-amber-600">{row.warning_count}</span> : "—"),
      defaultWidth: 110,
    },
  ];

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{t("payroll.runs.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("payroll.runs.subtitle")}</p>
        </div>
        <Button onClick={() => setDialogOpen(true)}>{t("payroll.runs.new")}</Button>
      </div>
      <FilterTabs
        value={status}
        onChange={setStatus}
        options={STATUSES.map((value) => ({ value, label: value === "all" ? t("payroll.runs.filter.all") : t(`payroll.status.run.${value}` as never) }))}
      />
      <PayrollTable
        tableKey="payroll.runs"
        columns={columns}
        rows={runs}
        rowKey={(row) => row.id}
        loading={isLoading}
        emptyTitle={t("payroll.runs.empty.title")}
        emptyDescription={t("payroll.runs.empty.description")}
        onRowClick={(row) => navigate(`/payroll/runs/${row.id}`)}
      />
      <RunDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </div>
  );
}
```

- [ ] **Step 4: Wire the route**

In `frontend/src/routes/router.tsx`, add `import { RunsPage } from "../features/payroll/runs/RunsPage";` and `{ path: "/payroll/runs", element: <RunsPage /> },` to `protectedChildren`.

- [ ] **Step 5: Type-check**

Run (from `frontend/`): `npx tsc -b --force`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/payroll/runs/RunsPage.tsx frontend/src/features/payroll/runs/RunDialog.tsx frontend/src/routes/router.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(payroll): runs list with status filter and a create-run dialog

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Run detail page — lifecycle actions, payslips panel, settlements panel

**Files:**
- Create: `frontend/src/features/payroll/runs/RunPage.tsx`, `run/PayslipsPanel.tsx`, `run/SettlementsPanel.tsx`, `run/ReverseDialog.tsx`
- Modify: `frontend/src/routes/router.tsx`, `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: `useRun`, `useCalculateRun`, `useApproveRun`, `useReverseRun`, `useRunPayslips`, `useFinalSettlements`, `useAddFinalSettlement`, `useRemoveFinalSettlement`, `usePayrollEmployees` (Task 1); `DraftRuleSetBanner`, `PayrollStatusBadge`, `PayrollTable` (Tasks 1–2); `StickyTabBar`.
- Produces: `/payroll/runs/:id` route with tabs (payslips, variance [Task 5 wires this tab's content], settlements, inputs [links to `/payroll/inputs`], payouts [Task 6], declarations [Task 6]). `PayslipsPanel` and `SettlementsPanel` are consumed only by `RunPage`.

- [ ] **Step 1: Add the i18n keys**

```ts
// en
"payroll.run.calculate": "Calculate",
"payroll.run.approve": "Approve",
"payroll.run.reverse": "Reverse",
"payroll.run.markPaid": "Mark paid",
"payroll.run.presenceNotClosed": "Close this month's presence before calculating.",
"payroll.run.tab.payslips": "Payslips",
"payroll.run.tab.variance": "Variance",
"payroll.run.tab.settlements": "Final settlements",
"payroll.run.tab.payouts": "Payouts",
"payroll.run.tab.declarations": "Declarations",
"payroll.run.payslips.column.employee": "Employee",
"payroll.run.payslips.column.gross": "Gross",
"payroll.run.payslips.column.net": "Net",
"payroll.run.payslips.column.warnings": "Warnings",
"payroll.run.payslips.empty.title": "No payslip yet",
"payroll.run.payslips.empty.description": "Calculate the run to generate its payslips.",
"payroll.run.print": "Print the run",
"payroll.run.settlements.add": "Add a final settlement",
"payroll.run.settlements.column.employee": "Employee",
"payroll.run.settlements.column.leaveDays": "Unused leave days",
"payroll.run.settlements.column.noticeMonths": "Notice months",
"payroll.run.settlements.empty.title": "No final settlement",
"payroll.run.settlements.empty.description": "Add one for an employee leaving this month (off-cycle runs only).",
"payroll.run.settlements.notOffCycle": "Final settlements can only be added to an off-cycle run.",
"payroll.reverseDialog.title": "Reverse this run",
"payroll.reverseDialog.reason": "Reason",
"payroll.reverseDialog.confirm": "Reverse",
```

```ts
// fr
"payroll.run.calculate": "Calculer",
"payroll.run.approve": "Approuver",
"payroll.run.reverse": "Extourner",
"payroll.run.markPaid": "Marquer payée",
"payroll.run.presenceNotClosed": "Clôturez la présence de ce mois avant de calculer.",
"payroll.run.tab.payslips": "Bulletins",
"payroll.run.tab.variance": "Écarts",
"payroll.run.tab.settlements": "Soldes de tout compte",
"payroll.run.tab.payouts": "Paiements",
"payroll.run.tab.declarations": "Déclarations",
"payroll.run.payslips.column.employee": "Employé",
"payroll.run.payslips.column.gross": "Brut",
"payroll.run.payslips.column.net": "Net",
"payroll.run.payslips.column.warnings": "Avertissements",
"payroll.run.payslips.empty.title": "Aucun bulletin",
"payroll.run.payslips.empty.description": "Calculez la paie pour générer ses bulletins.",
"payroll.run.print": "Imprimer la paie",
"payroll.run.settlements.add": "Ajouter un solde de tout compte",
"payroll.run.settlements.column.employee": "Employé",
"payroll.run.settlements.column.leaveDays": "Jours de congé non pris",
"payroll.run.settlements.column.noticeMonths": "Mois de préavis",
"payroll.run.settlements.empty.title": "Aucun solde de tout compte",
"payroll.run.settlements.empty.description": "Ajoutez-en un pour un employé qui part ce mois-ci (paies hors cycle uniquement).",
"payroll.run.settlements.notOffCycle": "Les soldes de tout compte ne s'ajoutent qu'à une paie hors cycle.",
"payroll.reverseDialog.title": "Extourner cette paie",
"payroll.reverseDialog.reason": "Motif",
"payroll.reverseDialog.confirm": "Extourner",
```

- [ ] **Step 2: Write `run/PayslipsPanel.tsx`**

```tsx
// frontend/src/features/payroll/runs/run/PayslipsPanel.tsx
import { useNavigate } from "react-router-dom";
import { useI18n, useI18nLocale } from "../../../../lib/i18n";
import { useRunPayslips, type PayslipSummary } from "../../api";
import { PayrollTable } from "../../PayrollTable";
import { formatXof } from "../../format";

export function PayslipsPanel({ runId }: { runId: string }) {
  const { t } = useI18n();
  const locale = useI18nLocale();
  const navigate = useNavigate();
  const { data: payslips = [], isLoading } = useRunPayslips(runId);

  const columns = [
    { key: "employee", header: t("payroll.run.payslips.column.employee"), cell: (row: PayslipSummary) => `${row.full_name} (${row.employee_no})`, defaultWidth: 220 },
    { key: "gross", header: t("payroll.run.payslips.column.gross"), cell: (row: PayslipSummary) => formatXof(row.gross, locale), defaultWidth: 150 },
    { key: "net", header: t("payroll.run.payslips.column.net"), cell: (row: PayslipSummary) => formatXof(row.net, locale), defaultWidth: 150 },
    {
      key: "warnings",
      header: t("payroll.run.payslips.column.warnings"),
      cell: (row: PayslipSummary) => (row.warnings.length > 0 ? <span className="text-amber-600">{row.warnings.join(", ")}</span> : "—"),
      defaultWidth: 180,
    },
  ];

  return (
    <PayrollTable
      tableKey="payroll.run.payslips"
      columns={columns}
      rows={payslips}
      rowKey={(row) => row.id}
      loading={isLoading}
      emptyTitle={t("payroll.run.payslips.empty.title")}
      emptyDescription={t("payroll.run.payslips.empty.description")}
      onRowClick={(row) => navigate(`/payroll/payslips/${row.id}`)}
    />
  );
}
```

- [ ] **Step 3: Write `run/SettlementsPanel.tsx`**

```tsx
// frontend/src/features/payroll/runs/run/SettlementsPanel.tsx
import { useState } from "react";
import { useI18n } from "../../../../lib/i18n";
import { useAddFinalSettlement, useFinalSettlements, usePayrollEmployees, useRemoveFinalSettlement, type FinalSettlement, type PayrollRun } from "../../api";
import { PayrollTable } from "../../PayrollTable";
import { Button } from "../../../../components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "../../../../components/ui/dialog";
import { Input } from "../../../../components/ui/input";
import { Label } from "../../../../components/ui/label";
import { Select } from "../../../../components/ui/select";
import { toast } from "../../../../components/ui/use-toast";

export function SettlementsPanel({ run }: { run: PayrollRun }) {
  const { t } = useI18n();
  const { data: settlements = [], isLoading } = useFinalSettlements(run.id);
  const remove = useRemoveFinalSettlement(run.id);
  const add = useAddFinalSettlement(run.id);
  const { data: employees = [] } = usePayrollEmployees(run.period);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [employeeId, setEmployeeId] = useState("");
  const [leaveDays, setLeaveDays] = useState("0");
  const [noticeMonths, setNoticeMonths] = useState("0");

  if (run.run_type !== "off_cycle") {
    return <p className="p-4 text-sm text-muted-foreground">{t("payroll.run.settlements.notOffCycle")}</p>;
  }

  const columns = [
    { key: "employee", header: t("payroll.run.settlements.column.employee"), cell: (row: FinalSettlement) => `${row.full_name} (${row.employee_no})`, defaultWidth: 220 },
    { key: "leaveDays", header: t("payroll.run.settlements.column.leaveDays"), cell: (row: FinalSettlement) => row.unused_leave_days, defaultWidth: 150 },
    { key: "noticeMonths", header: t("payroll.run.settlements.column.noticeMonths"), cell: (row: FinalSettlement) => row.notice_months, defaultWidth: 150 },
    {
      key: "actions",
      header: "",
      alwaysVisible: true,
      cell: (row: FinalSettlement) => (
        <Button
          size="sm"
          variant="destructive"
          onClick={() => remove.mutate(row.id, { onError: (error: unknown) => toast({ title: (error as Error).message, variant: "destructive" }) })}
        >
          {t("payroll.rules.ruleSets.delete")}
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-3">
      <PayrollTable
        tableKey="payroll.run.settlements"
        columns={columns}
        rows={settlements}
        rowKey={(row) => row.id}
        loading={isLoading}
        emptyTitle={t("payroll.run.settlements.empty.title")}
        emptyDescription={t("payroll.run.settlements.empty.description")}
        toolbar={<Button onClick={() => setDialogOpen(true)}>{t("payroll.run.settlements.add")}</Button>}
      />
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("payroll.run.settlements.add")}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3">
            <div>
              <Label>{t("payroll.run.settlements.column.employee")}</Label>
              <Select value={employeeId} onChange={(event) => setEmployeeId(event.target.value)}>
                <option value="" />
                {employees.map((employee) => (
                  <option key={employee.employee_id} value={employee.employee_id}>
                    {employee.full_name} ({employee.employee_no})
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label>{t("payroll.run.settlements.column.leaveDays")}</Label>
              <Input type="number" value={leaveDays} onChange={(event) => setLeaveDays(event.target.value)} />
            </div>
            <div>
              <Label>{t("payroll.run.settlements.column.noticeMonths")}</Label>
              <Input type="number" value={noticeMonths} onChange={(event) => setNoticeMonths(event.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button
              disabled={!employeeId || add.isPending}
              onClick={() =>
                add
                  .mutateAsync({ employee_id: employeeId, unused_leave_days: Number(leaveDays), notice_months: Number(noticeMonths) })
                  .then(() => setDialogOpen(false))
                  .catch((error: Error) => toast({ title: error.message, variant: "destructive" }))
              }
            >
              {t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
```

- [ ] **Step 4: Write `run/ReverseDialog.tsx`**

```tsx
// frontend/src/features/payroll/runs/run/ReverseDialog.tsx
import { useState } from "react";
import { useI18n } from "../../../../lib/i18n";
import { useReverseRun } from "../../api";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "../../../../components/ui/dialog";
import { Textarea } from "../../../../components/ui/textarea";
import { Label } from "../../../../components/ui/label";
import { Button } from "../../../../components/ui/button";
import { toast } from "../../../../components/ui/use-toast";

export function ReverseDialog({ open, onOpenChange, runId }: { open: boolean; onOpenChange: (open: boolean) => void; runId: string }) {
  const { t } = useI18n();
  const reverse = useReverseRun();
  const [reason, setReason] = useState("");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("payroll.reverseDialog.title")}</DialogTitle>
        </DialogHeader>
        <div>
          <Label>{t("payroll.reverseDialog.reason")}</Label>
          <Textarea value={reason} onChange={(event) => setReason(event.target.value)} />
        </div>
        <DialogFooter>
          <Button
            variant="destructive"
            disabled={!reason.trim() || reverse.isPending}
            onClick={() =>
              reverse
                .mutateAsync({ id: runId, reason })
                .then(() => onOpenChange(false))
                .catch((error: Error) => toast({ title: error.message, variant: "destructive" }))
            }
          >
            {t("payroll.reverseDialog.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 5: Write `RunPage.tsx`**

```tsx
// frontend/src/features/payroll/runs/RunPage.tsx
import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useI18n, useI18nLocale } from "../../../lib/i18n";
import { useApproveRun, useCalculateRun, useMarkPaid, useRun } from "../api";
import { PayrollStatusBadge } from "../PayrollStatusBadge";
import { DraftRuleSetBanner } from "../DraftRuleSetBanner";
import { StickyTabBar } from "../../../components/patterns/StickyTabBar";
import { Button } from "../../../components/ui/button";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { toast } from "../../../components/ui/use-toast";
import { formatPeriod, formatXof } from "../format";
import { PayslipsPanel } from "./run/PayslipsPanel";
import { SettlementsPanel } from "./run/SettlementsPanel";
import { ReverseDialog } from "./run/ReverseDialog";

type Tab = "payslips" | "variance" | "settlements" | "payouts" | "declarations";

export function RunPage() {
  const { runId } = useParams<{ runId: string }>();
  const { t } = useI18n();
  const locale = useI18nLocale();
  const navigate = useNavigate();
  const { data: run, isLoading } = useRun(runId);
  const calculate = useCalculateRun();
  const approve = useApproveRun();
  const markPaid = useMarkPaid();
  const [tab, setTab] = useState<Tab>("payslips");
  const [reverseOpen, setReverseOpen] = useState(false);

  if (isLoading || !run) return <AppLoader label={t("payroll.common.loading")} fullScreen />;

  const onError = (error: unknown) => toast({ title: (error as Error).message, variant: "destructive" });

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">
            {formatPeriod(run.period, locale)} · {t(`payroll.runs.type.${run.run_type}` as never)}
          </h1>
          <div className="mt-1 flex items-center gap-2">
            <PayrollStatusBadge domain="run" status={run.status} />
            <span className="text-sm text-muted-foreground">
              {t("payroll.run.payslips.column.employee")}: {run.payslip_count} · {formatXof(run.gross, locale)} → {formatXof(run.net, locale)}
            </span>
          </div>
        </div>
        <div className="flex gap-2">
          {run.status === "draft" && (
            <Button onClick={() => calculate.mutate(run.id, { onError })} disabled={calculate.isPending}>
              {t("payroll.run.calculate")}
            </Button>
          )}
          {run.status === "calculated" && (
            <Button onClick={() => approve.mutate(run.id, { onError })} disabled={approve.isPending}>
              {t("payroll.run.approve")}
            </Button>
          )}
          {(run.status === "approved" || run.status === "paid") && (
            <Button variant="destructive" onClick={() => setReverseOpen(true)}>
              {t("payroll.run.reverse")}
            </Button>
          )}
          {run.status === "approved" && (
            <Button onClick={() => markPaid.mutate(run.id, { onError })} disabled={markPaid.isPending}>
              {t("payroll.run.markPaid")}
            </Button>
          )}
          <Button variant="outline" onClick={() => navigate(`/payroll/runs/${run.id}/print`)}>
            {t("payroll.run.print")}
          </Button>
        </div>
      </div>
      {run.run_type === "regular" && run.presence_closed === false && (
        <p className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">{t("payroll.run.presenceNotClosed")}</p>
      )}
      <DraftRuleSetBanner ruleSet={run.rule_set_in_force?.status === "draft" ? run.rule_set_in_force : run.rule_set_status === "draft" ? { id: run.rule_set_id!, name: run.rule_set_id!, status: "draft" } : null} />
      <StickyTabBar>
        <button className={tab === "payslips" ? "font-semibold" : ""} onClick={() => setTab("payslips")}>
          {t("payroll.run.tab.payslips")}
        </button>
        <button className={tab === "variance" ? "font-semibold" : ""} onClick={() => setTab("variance")}>
          {t("payroll.run.tab.variance")}
        </button>
        <button className={tab === "settlements" ? "font-semibold" : ""} onClick={() => setTab("settlements")}>
          {t("payroll.run.tab.settlements")}
        </button>
        <button className={tab === "payouts" ? "font-semibold" : ""} onClick={() => setTab("payouts")}>
          {t("payroll.run.tab.payouts")}
        </button>
        <button className={tab === "declarations" ? "font-semibold" : ""} onClick={() => setTab("declarations")}>
          {t("payroll.run.tab.declarations")}
        </button>
      </StickyTabBar>
      {tab === "payslips" && <PayslipsPanel runId={run.id} />}
      {tab === "variance" && <div data-task="5-wires-VariancePanel-here" />}
      {tab === "settlements" && <SettlementsPanel run={run} />}
      {tab === "payouts" && <div data-task="6-wires-PayoutsPanel-here" />}
      {tab === "declarations" && <div data-task="6-wires-DeclarationsPanel-here" />}
      <ReverseDialog open={reverseOpen} onOpenChange={setReverseOpen} runId={run.id} />
      <p className="text-xs text-muted-foreground">
        <Link to="/payroll/inputs">{t("payroll.tabs.inputs")} →</Link>
      </p>
    </div>
  );
}
```

Note: the `variance`/`payouts`/`declarations` tab bodies are deliberate placeholders **within this task only** — Task 5 replaces the `variance` div with `<VariancePanel runId={run.id} />` and Task 6 replaces the `payouts`/`declarations` divs with `<PayoutsPanel run={run} />` / `<DeclarationsPanel run={run} />`, in the same file, as part of those tasks' own steps. This is not a plan-wide placeholder left unresolved — every one is closed by a later task in this same plan before the plan's self-review.

- [ ] **Step 6: Wire the route**

In `frontend/src/routes/router.tsx`, add `import { RunPage } from "../features/payroll/runs/RunPage";` and `{ path: "/payroll/runs/:runId", element: <RunPage /> },` to `protectedChildren`.

- [ ] **Step 7: Write the review-focus tests for banner + refusal surfacing**

These are frontend behaviour checks run manually against the dev seed (browser, not an automated test file — this codebase has no frontend unit-test runner configured; verification is `tsc -b --force` plus a manual pass against the seeded data, consistent with how phases 1–2 verify their own screens per `feedback_verify_frontend_in_repo`).

`test_a_draft_rule_set_run_shows_the_banner` (manual): with the seed from Task 10 applied (a draft Mali rule set, one calculated run), open `/payroll/runs/:id` for that run and confirm the amber `DraftRuleSetBanner` is visible and links to `/payroll/rules?ruleSet=<id>`.

`test_approving_your_own_calculation_shows_the_refusal` (manual): while logged in as the user who calculated the seeded run, click Approve; confirm a destructive toast appears with the server's bilingual `SAME_USER_APPROVAL` message (not a silent no-op) — this exercises Review Focus item 2.

- [ ] **Step 8: Type-check**

Run (from `frontend/`): `npx tsc -b --force`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/features/payroll/runs/RunPage.tsx frontend/src/features/payroll/runs/run frontend/src/routes/router.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(payroll): run detail page with calculate/approve/reverse/mark-paid and settlements

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Variance panel, and the Inputs page (monthly inputs, advances, loans)

**Files:**
- Create: `frontend/src/features/payroll/runs/run/VariancePanel.tsx`
- Create: `frontend/src/features/payroll/inputs/InputsPage.tsx`, `RunInputsTab.tsx`, `AdvancesTab.tsx`, `LoansTab.tsx`, `EmployeeSelect.tsx`
- Modify: `frontend/src/features/payroll/runs/RunPage.tsx` (wire `VariancePanel` into the `variance` tab)
- Modify: `frontend/src/routes/router.tsx`, `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: `useRunVariance` (Task 1); `useRuns` (to pick which run's inputs to manage), `useInputComponents`, `useRunInputs`, `useAddRunInput`, `useUpdateRunInput`, `useDeleteRunInput`, `useAdvances`, `useCreateAdvance`, `useUpdateAdvance`, `useApproveAdvance`, `useCancelAdvance`, `useLoans`, `useCreateLoan`, `useUpdateLoan`, `useCancelLoan`, `usePayrollEmployees` (Task 1); `PayrollTable`, `PayrollStatusBadge`, `FilterTabs`, `Tabs`.
- Produces: `EmployeeSelect` (a searchable employee combobox reused by run-inputs, advances, loans, and Task 4's `SettlementsPanel` — Task 4 is not modified retroactively since it already used a plain `<Select>`; new dialogs in this task use `EmployeeSelect` directly). `/payroll/inputs` route.

- [ ] **Step 1: Add the i18n keys**

```ts
// en
"payroll.variance.title": "Compared with last month's approved run",
"payroll.variance.none": "No previous approved regular run to compare with.",
"payroll.variance.column.employee": "Employee",
"payroll.variance.column.previousGross": "Previous gross",
"payroll.variance.column.currentGross": "Current gross",
"payroll.variance.column.deltaGross": "Δ gross",
"payroll.variance.column.deltaNet": "Δ net",
"payroll.variance.column.change": "Change",
"payroll.variance.change.new": "New",
"payroll.variance.change.same": "Unchanged",
"payroll.variance.change.changed": "Changed",
"payroll.variance.change.removed": "Removed",
"payroll.inputs.title": "Monthly inputs",
"payroll.inputs.subtitle": "One-off bonuses and deductions, salary advances and loan instalments for a run.",
"payroll.inputs.tab.runInputs": "Run inputs",
"payroll.inputs.tab.advances": "Advances",
"payroll.inputs.tab.loans": "Loans",
"payroll.inputs.selectRun": "Run",
"payroll.inputs.add": "Add",
"payroll.inputs.column.employee": "Employee",
"payroll.inputs.column.component": "Component",
"payroll.inputs.column.qty": "Qty",
"payroll.inputs.column.amount": "Amount",
"payroll.inputs.column.note": "Note",
"payroll.inputs.empty.title": "No input yet",
"payroll.inputs.empty.description": "Add a bonus, allowance or deduction for this run.",
"payroll.advances.column.requestedOn": "Requested on",
"payroll.advances.column.deductPeriod": "Deducted in",
"payroll.advances.column.status": "Status",
"payroll.advances.new": "New advance",
"payroll.advances.approve": "Approve",
"payroll.advances.cancel": "Cancel",
"payroll.advances.empty.title": "No advance",
"payroll.advances.empty.description": "Salary advances requested by employees appear here.",
"payroll.loans.column.principal": "Principal",
"payroll.loans.column.instalments": "Instalments",
"payroll.loans.column.remaining": "Remaining",
"payroll.loans.column.firstPeriod": "First instalment",
"payroll.loans.new": "New loan",
"payroll.loans.cancel": "Cancel",
"payroll.loans.empty.title": "No loan",
"payroll.loans.empty.description": "Employee loans and their instalment schedule appear here.",
"payroll.employeeSelect.placeholder": "Search an employee…",
```

```ts
// fr
"payroll.variance.title": "Comparaison avec la dernière paie approuvée",
"payroll.variance.none": "Aucune paie normale approuvée précédente pour comparer.",
"payroll.variance.column.employee": "Employé",
"payroll.variance.column.previousGross": "Brut précédent",
"payroll.variance.column.currentGross": "Brut actuel",
"payroll.variance.column.deltaGross": "Δ brut",
"payroll.variance.column.deltaNet": "Δ net",
"payroll.variance.column.change": "Changement",
"payroll.variance.change.new": "Nouveau",
"payroll.variance.change.same": "Inchangé",
"payroll.variance.change.changed": "Changé",
"payroll.variance.change.removed": "Retiré",
"payroll.inputs.title": "Éléments variables",
"payroll.inputs.subtitle": "Primes et retenues ponctuelles, avances sur salaire et échéances de prêt pour une paie.",
"payroll.inputs.tab.runInputs": "Éléments de paie",
"payroll.inputs.tab.advances": "Avances",
"payroll.inputs.tab.loans": "Prêts",
"payroll.inputs.selectRun": "Paie",
"payroll.inputs.add": "Ajouter",
"payroll.inputs.column.employee": "Employé",
"payroll.inputs.column.component": "Rubrique",
"payroll.inputs.column.qty": "Qté",
"payroll.inputs.column.amount": "Montant",
"payroll.inputs.column.note": "Note",
"payroll.inputs.empty.title": "Aucun élément",
"payroll.inputs.empty.description": "Ajoutez une prime, une indemnité ou une retenue pour cette paie.",
"payroll.advances.column.requestedOn": "Demandée le",
"payroll.advances.column.deductPeriod": "Retenue en",
"payroll.advances.column.status": "Statut",
"payroll.advances.new": "Nouvelle avance",
"payroll.advances.approve": "Approuver",
"payroll.advances.cancel": "Annuler",
"payroll.advances.empty.title": "Aucune avance",
"payroll.advances.empty.description": "Les avances sur salaire demandées par les employés apparaissent ici.",
"payroll.loans.column.principal": "Capital",
"payroll.loans.column.instalments": "Échéances",
"payroll.loans.column.remaining": "Restant",
"payroll.loans.column.firstPeriod": "Première échéance",
"payroll.loans.new": "Nouveau prêt",
"payroll.loans.cancel": "Annuler",
"payroll.loans.empty.title": "Aucun prêt",
"payroll.loans.empty.description": "Les prêts aux employés et leur échéancier apparaissent ici.",
"payroll.employeeSelect.placeholder": "Rechercher un employé…",
```

- [ ] **Step 2: Write `run/VariancePanel.tsx`**

```tsx
// frontend/src/features/payroll/runs/run/VariancePanel.tsx
import { useI18n, useI18nLocale } from "../../../../lib/i18n";
import { useRunVariance } from "../../api";
import { PayrollTable } from "../../PayrollTable";
import { formatXof } from "../../format";
import type { RunVariance } from "../../api";

export function VariancePanel({ runId }: { runId: string }) {
  const { t } = useI18n();
  const locale = useI18nLocale();
  const { data: variance, isLoading } = useRunVariance(runId);

  if (!isLoading && variance && !variance.previous_run_id) {
    return <p className="p-4 text-sm text-muted-foreground">{t("payroll.variance.none")}</p>;
  }

  const rows = variance?.rows ?? [];
  type Row = RunVariance["rows"][number];
  const columns = [
    { key: "employee", header: t("payroll.variance.column.employee"), cell: (row: Row) => `${row.full_name} (${row.employee_no})`, defaultWidth: 220 },
    { key: "previousGross", header: t("payroll.variance.column.previousGross"), cell: (row: Row) => formatXof(row.previous_gross, locale), defaultWidth: 150 },
    { key: "currentGross", header: t("payroll.variance.column.currentGross"), cell: (row: Row) => formatXof(row.current_gross, locale), defaultWidth: 150 },
    { key: "deltaGross", header: t("payroll.variance.column.deltaGross"), cell: (row: Row) => formatXof(row.delta_gross, locale), defaultWidth: 130 },
    { key: "deltaNet", header: t("payroll.variance.column.deltaNet"), cell: (row: Row) => formatXof(row.delta_net, locale), defaultWidth: 130 },
    { key: "change", header: t("payroll.variance.column.change"), cell: (row: Row) => t(`payroll.variance.change.${row.change}` as never), defaultWidth: 120 },
  ];

  return (
    <div className="space-y-2">
      <p className="text-sm text-muted-foreground">{t("payroll.variance.title")}</p>
      <PayrollTable
        tableKey="payroll.run.variance"
        columns={columns}
        rows={rows}
        rowKey={(row) => row.employee_id}
        loading={isLoading}
        emptyTitle={t("payroll.variance.none")}
        emptyDescription=""
      />
    </div>
  );
}
```

- [ ] **Step 3: Wire `VariancePanel` into `RunPage.tsx`**

In `frontend/src/features/payroll/runs/RunPage.tsx`, add `import { VariancePanel } from "./run/VariancePanel";` and replace:

```tsx
      {tab === "variance" && <div data-task="5-wires-VariancePanel-here" />}
```

with:

```tsx
      {tab === "variance" && <VariancePanel runId={run.id} />}
```

- [ ] **Step 4: Write `EmployeeSelect.tsx`**

```tsx
// frontend/src/features/payroll/inputs/EmployeeSelect.tsx
import { useState } from "react";
import { useI18n } from "../../../lib/i18n";
import { usePayrollEmployees, type PayrollEmployee } from "../api";
import { Input } from "../../../components/ui/input";

/**
 * A period-scoped employee picker filtered client-side by typed text — the ~60-employee demo
 * seed is small enough that this needs no server-side search param (see this plan's
 * "Decisions / gaps found" section). Fetches once per period via TanStack Query's cache.
 */
export function EmployeeSelect({
  period,
  value,
  onChange,
}: {
  period: string;
  value: string;
  onChange: (employeeId: string) => void;
}) {
  const { t } = useI18n();
  const { data: employees = [] } = usePayrollEmployees(period);
  const [query, setQuery] = useState("");
  const filtered = employees.filter((employee) => `${employee.full_name} ${employee.employee_no}`.toLowerCase().includes(query.toLowerCase()));
  const selected = employees.find((employee: PayrollEmployee) => employee.employee_id === value);

  return (
    <div className="space-y-1">
      <Input placeholder={t("payroll.employeeSelect.placeholder")} value={query} onChange={(event) => setQuery(event.target.value)} />
      <select
        className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="" />
        {filtered.map((employee) => (
          <option key={employee.employee_id} value={employee.employee_id}>
            {employee.full_name} ({employee.employee_no})
          </option>
        ))}
      </select>
      {selected && <p className="text-xs text-muted-foreground">{selected.full_name}</p>}
    </div>
  );
}
```

- [ ] **Step 5: Write `RunInputsTab.tsx`** (includes Review Focus item 4 — inline `INPUT_INVALID`)

```tsx
// frontend/src/features/payroll/inputs/RunInputsTab.tsx
import { useState } from "react";
import { useI18n } from "../../../lib/i18n";
import {
  useAddRunInput, useDeleteRunInput, useInputComponents, useRunInputs, useRuns, useUpdateRunInput, type InputComponent, type RunInput,
} from "../api";
import { PayrollTable } from "../PayrollTable";
import { Button } from "../../../components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { toast } from "../../../components/ui/use-toast";
import { EmployeeSelect } from "./EmployeeSelect";

export function RunInputsTab() {
  const { t } = useI18n();
  const { data: runs = [] } = useRuns();
  const openRuns = runs.filter((run) => run.status === "draft" || run.status === "calculated");
  const [runId, setRunId] = useState(openRuns[0]?.id ?? "");
  const run = runs.find((candidate) => candidate.id === runId);
  const { data: components = [] } = useInputComponents(runId || undefined);
  const { data: inputs = [], isLoading } = useRunInputs(runId || undefined);
  const add = useAddRunInput(runId);
  const update = useUpdateRunInput(runId);
  const del = useDeleteRunInput(runId);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [employeeId, setEmployeeId] = useState("");
  const [componentCode, setComponentCode] = useState("");
  const [qty, setQty] = useState("");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);

  const columns = [
    { key: "employee", header: t("payroll.inputs.column.employee"), cell: (row: RunInput) => `${row.full_name} (${row.employee_no})`, defaultWidth: 220 },
    { key: "component", header: t("payroll.inputs.column.component"), cell: (row: RunInput) => row.component_code, defaultWidth: 150 },
    { key: "qty", header: t("payroll.inputs.column.qty"), cell: (row: RunInput) => row.qty ?? "—", defaultWidth: 90 },
    { key: "amount", header: t("payroll.inputs.column.amount"), cell: (row: RunInput) => row.amount ?? "—", defaultWidth: 120 },
    { key: "note", header: t("payroll.inputs.column.note"), cell: (row: RunInput) => row.note ?? "—", defaultWidth: 200 },
    {
      key: "actions",
      header: "",
      alwaysVisible: true,
      cell: (row: RunInput) => (
        <Button
          size="sm"
          variant="destructive"
          onClick={() => del.mutate(row.id, { onError: (error: unknown) => toast({ title: (error as Error).message, variant: "destructive" }) })}
        >
          {t("payroll.rules.ruleSets.delete")}
        </Button>
      ),
    },
  ];

  const submit = () => {
    setFieldError(null);
    add
      .mutateAsync({ employee_id: employeeId, component_code: componentCode, qty: qty ? Number(qty) : null, amount: amount ? Number(amount) : null, note: note || null })
      .then(() => {
        setDialogOpen(false);
        setEmployeeId(""); setComponentCode(""); setQty(""); setAmount(""); setNote("");
      })
      .catch((error: Error & { code?: string }) => {
        if (error.code === "INPUT_INVALID") setFieldError(error.message);
        else toast({ title: error.message, variant: "destructive" });
      });
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Label>{t("payroll.inputs.selectRun")}</Label>
        <Select value={runId} onChange={(event) => setRunId(event.target.value)}>
          <option value="" />
          {openRuns.map((candidate) => (
            <option key={candidate.id} value={candidate.id}>
              {candidate.period} · {candidate.run_type}
            </option>
          ))}
        </Select>
      </div>
      {runId && (
        <PayrollTable
          tableKey="payroll.inputs.runInputs"
          columns={columns}
          rows={inputs}
          rowKey={(row) => row.id}
          loading={isLoading}
          emptyTitle={t("payroll.inputs.empty.title")}
          emptyDescription={t("payroll.inputs.empty.description")}
          toolbar={<Button onClick={() => setDialogOpen(true)}>{t("payroll.inputs.add")}</Button>}
        />
      )}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("payroll.inputs.add")}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3">
            <div>
              <Label>{t("payroll.inputs.column.employee")}</Label>
              <EmployeeSelect period={run?.period ?? ""} value={employeeId} onChange={setEmployeeId} />
            </div>
            <div>
              <Label>{t("payroll.inputs.column.component")}</Label>
              <Select value={componentCode} onChange={(event) => setComponentCode(event.target.value)}>
                <option value="" />
                {components.map((component: InputComponent) => (
                  <option key={component.code} value={component.code}>
                    {component.name_en} ({component.code})
                  </option>
                ))}
              </Select>
              {fieldError && <p className="text-sm text-destructive">{fieldError}</p>}
            </div>
            <div>
              <Label>{t("payroll.inputs.column.qty")}</Label>
              <Input type="number" value={qty} onChange={(event) => setQty(event.target.value)} />
            </div>
            <div>
              <Label>{t("payroll.inputs.column.amount")}</Label>
              <Input type="number" value={amount} onChange={(event) => setAmount(event.target.value)} />
            </div>
            <div>
              <Label>{t("payroll.common.note")}</Label>
              <Input value={note} onChange={(event) => setNote(event.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button onClick={submit} disabled={!employeeId || !componentCode || add.isPending}>
              {t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
```

Note: `update` is imported but intentionally unused in this dialog (there is no inline edit affordance for a run input in this task — only add/delete, matching 3b's own scope which gives `PATCH /payroll/run-inputs/{id}` for future use but the spec's screen list does not call for an edit-in-place row here). Remove the unused `update` variable and its import if `tsc`/lint flags it as unused; keeping the hook import while never calling it would fail the type-check step's build (unused-variable is a warning, not an error, in this project's `tsconfig`, but drop it here for cleanliness — confirm by running Step 9's `tsc -b --force`).

- [ ] **Step 6: Write `AdvancesTab.tsx`**

```tsx
// frontend/src/features/payroll/inputs/AdvancesTab.tsx
import { useState } from "react";
import { useI18n } from "../../../lib/i18n";
import { useApproveAdvance, useCancelAdvance, useCreateAdvance, useAdvances, type Advance } from "../api";
import { PayrollTable } from "../PayrollTable";
import { PayrollStatusBadge } from "../PayrollStatusBadge";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { Button } from "../../../components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { toast } from "../../../components/ui/use-toast";
import { EmployeeSelect } from "./EmployeeSelect";
import { monthInputValue, parseMonthInput } from "../format";

const STATUSES = ["all", "requested", "approved", "cancelled"] as const;

export function AdvancesTab() {
  const { t } = useI18n();
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("all");
  const { data: advances = [], isLoading } = useAdvances(status === "all" ? undefined : status);
  const approve = useApproveAdvance();
  const cancel = useCancelAdvance();
  const create = useCreateAdvance();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [employeeId, setEmployeeId] = useState("");
  const [amount, setAmount] = useState("");
  const [requestedOn, setRequestedOn] = useState("");
  const [deductPeriod, setDeductPeriod] = useState("");

  const onError = (error: unknown) => toast({ title: (error as Error).message, variant: "destructive" });

  const columns = [
    { key: "employee", header: t("payroll.inputs.column.employee"), cell: (row: Advance) => `${row.full_name} (${row.employee_no})`, defaultWidth: 220 },
    { key: "amount", header: t("payroll.inputs.column.amount"), cell: (row: Advance) => row.amount, defaultWidth: 130 },
    { key: "requestedOn", header: t("payroll.advances.column.requestedOn"), cell: (row: Advance) => row.requested_on, defaultWidth: 130 },
    { key: "deductPeriod", header: t("payroll.advances.column.deductPeriod"), cell: (row: Advance) => row.deduct_period.slice(0, 7), defaultWidth: 130 },
    { key: "status", header: t("payroll.advances.column.status"), cell: (row: Advance) => <PayrollStatusBadge domain="advance" status={row.status} />, defaultWidth: 130 },
    {
      key: "actions",
      header: "",
      alwaysVisible: true,
      cell: (row: Advance) =>
        row.status === "requested" ? (
          <div className="flex gap-1">
            <Button size="sm" onClick={() => approve.mutate(row.id, { onError })}>
              {t("payroll.advances.approve")}
            </Button>
            <Button size="sm" variant="destructive" onClick={() => cancel.mutate(row.id, { onError })}>
              {t("payroll.advances.cancel")}
            </Button>
          </div>
        ) : row.status === "approved" && !row.deducted_payslip_id ? (
          <Button size="sm" variant="destructive" onClick={() => cancel.mutate(row.id, { onError })}>
            {t("payroll.advances.cancel")}
          </Button>
        ) : (
          "—"
        ),
    },
  ];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <FilterTabs
          value={status}
          onChange={setStatus}
          options={STATUSES.map((value) => ({ value, label: value === "all" ? t("payroll.runs.filter.all") : t(`payroll.status.advance.${value}` as never) }))}
        />
        <Button onClick={() => setDialogOpen(true)}>{t("payroll.advances.new")}</Button>
      </div>
      <PayrollTable
        tableKey="payroll.inputs.advances"
        columns={columns}
        rows={advances}
        rowKey={(row) => row.id}
        loading={isLoading}
        emptyTitle={t("payroll.advances.empty.title")}
        emptyDescription={t("payroll.advances.empty.description")}
      />
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("payroll.advances.new")}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3">
            <div>
              <Label>{t("payroll.inputs.column.employee")}</Label>
              <EmployeeSelect period={deductPeriod ? parseMonthInput(deductPeriod) : ""} value={employeeId} onChange={setEmployeeId} />
            </div>
            <div>
              <Label>{t("payroll.inputs.column.amount")}</Label>
              <Input type="number" value={amount} onChange={(event) => setAmount(event.target.value)} />
            </div>
            <div>
              <Label>{t("payroll.advances.column.requestedOn")}</Label>
              <Input type="date" value={requestedOn} onChange={(event) => setRequestedOn(event.target.value)} />
            </div>
            <div>
              <Label>{t("payroll.advances.column.deductPeriod")}</Label>
              <Input type="month" value={deductPeriod} onChange={(event) => setDeductPeriod(event.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button
              disabled={!employeeId || !amount || !requestedOn || !deductPeriod || create.isPending}
              onClick={() =>
                create
                  .mutateAsync({ employee_id: employeeId, amount: Number(amount), requested_on: requestedOn, deduct_period: parseMonthInput(deductPeriod) })
                  .then(() => setDialogOpen(false))
                  .catch(onError)
              }
            >
              {t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
```

- [ ] **Step 7: Write `LoansTab.tsx`**

```tsx
// frontend/src/features/payroll/inputs/LoansTab.tsx
import { useState } from "react";
import { useI18n } from "../../../lib/i18n";
import { useCancelLoan, useCreateLoan, useLoans, type Loan } from "../api";
import { PayrollTable } from "../PayrollTable";
import { PayrollStatusBadge } from "../PayrollStatusBadge";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { Button } from "../../../components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { toast } from "../../../components/ui/use-toast";
import { EmployeeSelect } from "./EmployeeSelect";
import { monthInputValue, parseMonthInput } from "../format";

const STATUSES = ["all", "active", "cancelled"] as const;

export function LoansTab() {
  const { t } = useI18n();
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("all");
  const { data: loans = [], isLoading } = useLoans(status === "all" ? undefined : status);
  const cancel = useCancelLoan();
  const create = useCreateLoan();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [employeeId, setEmployeeId] = useState("");
  const [principal, setPrincipal] = useState("");
  const [instalmentCount, setInstalmentCount] = useState("");
  const [firstPeriod, setFirstPeriod] = useState("");

  const onError = (error: unknown) => toast({ title: (error as Error).message, variant: "destructive" });

  const columns = [
    { key: "employee", header: t("payroll.inputs.column.employee"), cell: (row: Loan) => `${row.full_name} (${row.employee_no})`, defaultWidth: 220 },
    { key: "principal", header: t("payroll.loans.column.principal"), cell: (row: Loan) => row.principal, defaultWidth: 130 },
    { key: "instalments", header: t("payroll.loans.column.instalments"), cell: (row: Loan) => row.instalment_count, defaultWidth: 110 },
    { key: "remaining", header: t("payroll.loans.column.remaining"), cell: (row: Loan) => row.remaining, defaultWidth: 130 },
    { key: "firstPeriod", header: t("payroll.loans.column.firstPeriod"), cell: (row: Loan) => row.first_period.slice(0, 7), defaultWidth: 130 },
    { key: "status", header: t("payroll.advances.column.status"), cell: (row: Loan) => <PayrollStatusBadge domain="loan" status={row.status} />, defaultWidth: 120 },
    {
      key: "actions",
      header: "",
      alwaysVisible: true,
      cell: (row: Loan) =>
        row.status === "active" ? (
          <Button size="sm" variant="destructive" onClick={() => cancel.mutate(row.id, { onError })}>
            {t("payroll.loans.cancel")}
          </Button>
        ) : (
          "—"
        ),
    },
  ];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <FilterTabs
          value={status}
          onChange={setStatus}
          options={STATUSES.map((value) => ({ value, label: value === "all" ? t("payroll.runs.filter.all") : t(`payroll.status.loan.${value}` as never) }))}
        />
        <Button onClick={() => setDialogOpen(true)}>{t("payroll.loans.new")}</Button>
      </div>
      <PayrollTable
        tableKey="payroll.inputs.loans"
        columns={columns}
        rows={loans}
        rowKey={(row) => row.id}
        loading={isLoading}
        emptyTitle={t("payroll.loans.empty.title")}
        emptyDescription={t("payroll.loans.empty.description")}
      />
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("payroll.loans.new")}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3">
            <div>
              <Label>{t("payroll.inputs.column.employee")}</Label>
              <EmployeeSelect period={firstPeriod ? parseMonthInput(firstPeriod) : ""} value={employeeId} onChange={setEmployeeId} />
            </div>
            <div>
              <Label>{t("payroll.loans.column.principal")}</Label>
              <Input type="number" value={principal} onChange={(event) => setPrincipal(event.target.value)} />
            </div>
            <div>
              <Label>{t("payroll.loans.column.instalments")}</Label>
              <Input type="number" value={instalmentCount} onChange={(event) => setInstalmentCount(event.target.value)} />
            </div>
            <div>
              <Label>{t("payroll.loans.column.firstPeriod")}</Label>
              <Input type="month" value={firstPeriod} onChange={(event) => setFirstPeriod(event.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button
              disabled={!employeeId || !principal || !instalmentCount || !firstPeriod || create.isPending}
              onClick={() =>
                create
                  .mutateAsync({ employee_id: employeeId, principal: Number(principal), instalment_count: Number(instalmentCount), first_period: parseMonthInput(firstPeriod) })
                  .then(() => setDialogOpen(false))
                  .catch(onError)
              }
            >
              {t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
```

Both `AdvancesTab.tsx` and `LoansTab.tsx` import `monthInputValue` but only use `parseMonthInput` — drop the unused `monthInputValue` import from both files (a leftover from copying `format.ts`'s exports; `tsc -b --force` in Step 9 will not fail on it since unused imports are not a compile error in this project's config, but remove it for cleanliness).

- [ ] **Step 8: Write `InputsPage.tsx`**

```tsx
// frontend/src/features/payroll/inputs/InputsPage.tsx
import { useState } from "react";
import { useI18n } from "../../lib/i18n";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../../components/ui/tabs";
import { RunInputsTab } from "./RunInputsTab";
import { AdvancesTab } from "./AdvancesTab";
import { LoansTab } from "./LoansTab";

export function InputsPage() {
  const { t } = useI18n();
  const [tab, setTab] = useState("runInputs");

  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-semibold">{t("payroll.inputs.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("payroll.inputs.subtitle")}</p>
      </div>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="runInputs">{t("payroll.inputs.tab.runInputs")}</TabsTrigger>
          <TabsTrigger value="advances">{t("payroll.inputs.tab.advances")}</TabsTrigger>
          <TabsTrigger value="loans">{t("payroll.inputs.tab.loans")}</TabsTrigger>
        </TabsList>
        <TabsContent value="runInputs">
          <RunInputsTab />
        </TabsContent>
        <TabsContent value="advances">
          <AdvancesTab />
        </TabsContent>
        <TabsContent value="loans">
          <LoansTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
```

- [ ] **Step 9: Wire the route and type-check**

In `frontend/src/routes/router.tsx`, add `import { InputsPage } from "../features/payroll/inputs/InputsPage";` and `{ path: "/payroll/inputs", element: <InputsPage /> },` to `protectedChildren`.

Run (from `frontend/`): `npx tsc -b --force`
Expected: no errors. Remove the unused `update`/`monthInputValue` imports flagged in Steps 5 and 7 if the build surfaces them.

- [ ] **Step 10: Manual verification of Review Focus item 4**

`test_a_bad_component_choice_shows_inline` (manual, against the dev seed once Task 10's seed data exists): on `/payroll/inputs`, pick the seeded calculated run, try to add a run input with `component_code = "BASE"` (a system component, not in `input_components`); confirm the 422 `INPUT_INVALID` renders as inline red text under the component field (`fieldError` state in `RunInputsTab`), not only as a toast.

- [ ] **Step 11: Commit**

```bash
git add frontend/src/features/payroll/runs/run/VariancePanel.tsx frontend/src/features/payroll/runs/RunPage.tsx frontend/src/features/payroll/inputs frontend/src/routes/router.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(payroll): variance panel and the Inputs page (run inputs, advances, loans)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Payouts panel, bank templates dialog, declarations panel

**Files:**
- Create: `frontend/src/features/payroll/runs/run/PayoutsPanel.tsx`, `run/BankTemplatesDialog.tsx`, `run/DeclarationsPanel.tsx`
- Modify: `frontend/src/features/payroll/runs/RunPage.tsx` (wire both panels into the `payouts`/`declarations` tabs)
- Modify: `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: `usePayoutBatches`, `useGeneratePayouts`, `useConfirmBatch`, `batchFileUrl`, `useBankTemplates`, `useCreateTemplate`, `useUpdateTemplate`, `useDeleteTemplate`, `useMarkPaid` (Task 1); `useDeclarationCodes`, `useDeclaration`, `declarationCsvUrl` (Task 1); `apiFetch`'s auth header convention for the file-download link (below); `PayrollTable`, `PayrollStatusBadge`.
- Produces: this task closes the two placeholder `<div>`s left in `RunPage.tsx` by Task 4. `PayoutsPanel`/`DeclarationsPanel` are not consumed anywhere else.

- [ ] **Step 1: Add the i18n keys**

```ts
// en
"payroll.payouts.generate": "Generate payouts",
"payroll.payouts.column.method": "Method",
"payroll.payouts.column.group": "Bank / operator",
"payroll.payouts.column.status": "Status",
"payroll.payouts.column.total": "Total",
"payroll.payouts.column.lines": "Lines",
"payroll.payouts.confirm": "Confirm",
"payroll.payouts.download": "Download",
"payroll.payouts.cashSheet": "Cash sheet",
"payroll.payouts.empty.title": "No payout batch yet",
"payroll.payouts.empty.description": "Generate payouts once the run is approved.",
"payroll.payouts.templateMissing": "No bank file template for {bank}. Add one below before downloading.",
"payroll.payouts.templates.title": "Bank file templates",
"payroll.payouts.templates.new": "New template",
"payroll.payouts.templates.bankName": "Bank name",
"payroll.payouts.templates.delimiter": "Delimiter",
"payroll.payouts.templates.includeHeader": "Include header row",
"payroll.payouts.templates.manage": "Manage bank file templates",
"payroll.declarations.period": "Period",
"payroll.declarations.code": "Declaration",
"payroll.declarations.download": "Download CSV",
"payroll.declarations.annual": "Annual recap",
"payroll.declarations.annualYear": "Year",
"payroll.declarations.empty.title": "Nothing to declare",
"payroll.declarations.empty.description": "No approved or paid payslip for this period yet.",
```

```ts
// fr
"payroll.payouts.generate": "Générer les paiements",
"payroll.payouts.column.method": "Méthode",
"payroll.payouts.column.group": "Banque / opérateur",
"payroll.payouts.column.status": "Statut",
"payroll.payouts.column.total": "Total",
"payroll.payouts.column.lines": "Lignes",
"payroll.payouts.confirm": "Confirmer",
"payroll.payouts.download": "Télécharger",
"payroll.payouts.cashSheet": "Feuille de caisse",
"payroll.payouts.empty.title": "Aucun lot de paiement",
"payroll.payouts.empty.description": "Générez les paiements une fois la paie approuvée.",
"payroll.payouts.templateMissing": "Aucun modèle de fichier bancaire pour {bank}. Ajoutez-en un ci-dessous avant de télécharger.",
"payroll.payouts.templates.title": "Modèles de fichier bancaire",
"payroll.payouts.templates.new": "Nouveau modèle",
"payroll.payouts.templates.bankName": "Nom de la banque",
"payroll.payouts.templates.delimiter": "Séparateur",
"payroll.payouts.templates.includeHeader": "Inclure la ligne d'en-tête",
"payroll.payouts.templates.manage": "Gérer les modèles de fichier bancaire",
"payroll.declarations.period": "Période",
"payroll.declarations.code": "Déclaration",
"payroll.declarations.download": "Télécharger le CSV",
"payroll.declarations.annual": "Récapitulatif annuel",
"payroll.declarations.annualYear": "Année",
"payroll.declarations.empty.title": "Rien à déclarer",
"payroll.declarations.empty.description": "Aucun bulletin approuvé ou payé pour cette période.",
```

- [ ] **Step 2: Write `run/BankTemplatesDialog.tsx`**

```tsx
// frontend/src/features/payroll/runs/run/BankTemplatesDialog.tsx
import { useState } from "react";
import { useI18n } from "../../../../lib/i18n";
import { useBankTemplates, useCreateTemplate, useDeleteTemplate, type BankFileTemplate } from "../../api";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "../../../../components/ui/dialog";
import { Input } from "../../../../components/ui/input";
import { Label } from "../../../../components/ui/label";
import { Button } from "../../../../components/ui/button";
import { toast } from "../../../../components/ui/use-toast";

const DEFAULT_COLUMNS = [
  { header: "Compte", field: "account_no" },
  { header: "Nom", field: "full_name" },
  { header: "Montant", field: "amount" },
];

export function BankTemplatesDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useI18n();
  const { data: templates = [] } = useBankTemplates();
  const create = useCreateTemplate();
  const del = useDeleteTemplate();
  const [bankName, setBankName] = useState("");

  const onError = (error: unknown) => toast({ title: (error as Error).message, variant: "destructive" });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("payroll.payouts.templates.title")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-2">
          {templates.map((template: BankFileTemplate) => (
            <div key={template.id} className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
              <span>{template.bank_name}</span>
              <Button size="sm" variant="destructive" onClick={() => del.mutate(template.id, { onError })}>
                {t("payroll.rules.ruleSets.delete")}
              </Button>
            </div>
          ))}
        </div>
        <div className="flex items-end gap-2">
          <div className="flex-1">
            <Label>{t("payroll.payouts.templates.bankName")}</Label>
            <Input value={bankName} onChange={(event) => setBankName(event.target.value)} />
          </div>
          <Button
            disabled={!bankName || create.isPending}
            onClick={() =>
              create
                .mutateAsync({ bank_name: bankName, delimiter: ";", include_header: true, columns: DEFAULT_COLUMNS })
                .then(() => setBankName(""))
                .catch(onError)
            }
          >
            {t("payroll.payouts.templates.new")}
          </Button>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common.close")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 3: Write `run/PayoutsPanel.tsx`** (Review Focus item 3 — missing bank template)

```tsx
// frontend/src/features/payroll/runs/run/PayoutsPanel.tsx
import { useState } from "react";
import { useI18n, useI18nLocale } from "../../../../lib/i18n";
import { useAuth } from "../../../../lib/auth";
import { useBankTemplates, useConfirmBatch, useGeneratePayouts, useMarkPaid, usePayoutBatches, batchFileUrl, type PayoutBatch, type PayrollRun } from "../../api";
import { PayrollTable } from "../../PayrollTable";
import { Button } from "../../../../components/ui/button";
import { toast } from "../../../../components/ui/use-toast";
import { formatXof } from "../../format";
import { BankTemplatesDialog } from "./BankTemplatesDialog";

export function PayoutsPanel({ run }: { run: PayrollRun }) {
  const { t } = useI18n();
  const locale = useI18nLocale();
  const { session } = useAuth();
  const { data: batches = [], isLoading } = usePayoutBatches(run.id);
  const { data: templates = [] } = useBankTemplates();
  const generate = useGeneratePayouts(run.id);
  const confirm = useConfirmBatch(run.id);
  const markPaid = useMarkPaid();
  const [templatesOpen, setTemplatesOpen] = useState(false);

  const onError = (error: unknown) => toast({ title: (error as Error).message, variant: "destructive" });
  const templateNames = new Set(templates.map((template) => template.bank_name));

  const download = async (batch: PayoutBatch) => {
    const response = await fetch(batchFileUrl(batch.id), { headers: { Authorization: `Bearer ${session!.token}` } });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      toast({ title: body?.detail?.message ?? t("payroll.run.reverse"), variant: "destructive" });
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = batch.file_name;
    link.click();
    URL.revokeObjectURL(url);
  };

  const columns = [
    { key: "method", header: t("payroll.payouts.column.method"), cell: (row: PayoutBatch) => row.method, defaultWidth: 130 },
    { key: "group", header: t("payroll.payouts.column.group"), cell: (row: PayoutBatch) => row.group_key, defaultWidth: 160 },
    { key: "total", header: t("payroll.payouts.column.total"), cell: (row: PayoutBatch) => formatXof(row.total, locale), defaultWidth: 150 },
    { key: "lines", header: t("payroll.payouts.column.lines"), cell: (row: PayoutBatch) => row.line_count, defaultWidth: 90 },
    { key: "status", header: t("payroll.payouts.column.status"), cell: (row: PayoutBatch) => row.status, defaultWidth: 120 },
    {
      key: "actions",
      header: "",
      alwaysVisible: true,
      cell: (row: PayoutBatch) => (
        <div className="flex flex-col gap-1">
          {row.method === "bank" && !templateNames.has(row.group_key) && (
            <p className="text-xs text-amber-600">{t("payroll.payouts.templateMissing").replace("{bank}", row.group_key)}</p>
          )}
          <div className="flex gap-1">
            {row.status === "generated" && (
              <Button size="sm" onClick={() => confirm.mutate(row.id, { onError })}>
                {t("payroll.payouts.confirm")}
              </Button>
            )}
            {row.method === "cash" ? (
              <Button size="sm" variant="outline" onClick={() => window.open(`/payroll/payout-batches/${row.id}/cash-sheet/print`, "_blank")}>
                {t("payroll.payouts.cashSheet")}
              </Button>
            ) : (
              <Button size="sm" variant="outline" onClick={() => download(row)}>
                {t("payroll.payouts.download")}
              </Button>
            )}
          </div>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          {run.status === "approved" && (
            <Button onClick={() => generate.mutate(undefined, { onError })} disabled={generate.isPending}>
              {t("payroll.payouts.generate")}
            </Button>
          )}
          {run.status === "approved" && batches.length > 0 && batches.every((batch) => batch.status === "confirmed") && (
            <Button onClick={() => markPaid.mutate(run.id, { onError })} disabled={markPaid.isPending}>
              {t("payroll.run.markPaid")}
            </Button>
          )}
        </div>
        <Button variant="outline" onClick={() => setTemplatesOpen(true)}>
          {t("payroll.payouts.templates.manage")}
        </Button>
      </div>
      <PayrollTable
        tableKey="payroll.run.payouts"
        columns={columns}
        rows={batches}
        rowKey={(row) => row.id}
        loading={isLoading}
        emptyTitle={t("payroll.payouts.empty.title")}
        emptyDescription={t("payroll.payouts.empty.description")}
      />
      <BankTemplatesDialog open={templatesOpen} onOpenChange={setTemplatesOpen} />
    </div>
  );
}
```

Add `"common.close": "Close"` / `"Fermer"` to `i18n.tsx` if the shared `common.*` namespace does not already have it (check first — many modules already need a generic "close" label; reuse it if present rather than adding a duplicate key with different wording).

- [ ] **Step 4: Write `run/DeclarationsPanel.tsx`**

```tsx
// frontend/src/features/payroll/runs/run/DeclarationsPanel.tsx
import { useState } from "react";
import { useI18n } from "../../../../lib/i18n";
import { useDeclarationCodes, useDeclaration, declarationCsvUrl, type PayrollRun } from "../../api";
import { Button } from "../../../../components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../../../components/ui/table";
import { EmptyState } from "../../../../components/patterns/EmptyState";
import { AppLoader } from "../../../../components/patterns/AppLoader";

export function DeclarationsPanel({ run }: { run: PayrollRun }) {
  const { t } = useI18n();
  const { data: codes = [], isLoading: loadingCodes } = useDeclarationCodes(run.period);
  const [code, setCode] = useState<string | undefined>(undefined);
  const activeCode = code ?? codes[0];
  const { data: declaration, isLoading } = useDeclaration(run.period, activeCode);

  if (loadingCodes) return <AppLoader label={t("payroll.common.loading")} className="py-8" />;
  if (codes.length === 0) return <EmptyState title={t("payroll.declarations.empty.title")} description={t("payroll.declarations.empty.description")} />;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        {codes.map((candidate) => (
          <Button key={candidate} size="sm" variant={candidate === activeCode ? "default" : "outline"} onClick={() => setCode(candidate)}>
            {candidate}
          </Button>
        ))}
        {activeCode && (
          <a className="ml-auto" href={declarationCsvUrl(run.period, activeCode)} target="_blank" rel="noreferrer">
            <Button variant="outline" size="sm">
              {t("payroll.declarations.download")}
            </Button>
          </a>
        )}
      </div>
      {isLoading || !declaration ? (
        <AppLoader label={t("payroll.common.loading")} className="py-8" />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              {declaration.columns.map((column) => (
                <TableHead key={column}>{column}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {declaration.rows.map((row, index) => (
              <TableRow key={index}>
                {declaration.columns.map((column) => (
                  <TableCell key={column}>{String(row[column] ?? "")}</TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
```

Note: the CSV download link uses a plain `<a href>` rather than the authenticated `fetch`-then-blob pattern `PayoutsPanel` needs for `batchFileUrl` — `apiFetch`'s session token is normally sent as a bearer header, not a cookie, so if `GET /payroll/declarations` truly requires the `Authorization` header (it does, per `require_permission`), a bare `<a href>` will 401. Match `PayoutsPanel.download`'s `fetch` + blob + token-header pattern here too instead of a raw anchor tag — write `DeclarationsPanel`'s download button as an `onClick` handler calling `fetch(declarationCsvUrl(...), { headers: { Authorization: \`Bearer ${session!.token}\` } })` and triggering the blob download exactly like `PayoutsPanel.download`, not the `<a href>` shown above (corrected in the file, not left as the snippet's oversight).

- [ ] **Step 5: Wire both panels into `RunPage.tsx`**

In `frontend/src/features/payroll/runs/RunPage.tsx`, add the imports and replace the two remaining placeholder divs:

```tsx
import { PayoutsPanel } from "./run/PayoutsPanel";
import { DeclarationsPanel } from "./run/DeclarationsPanel";
```

```tsx
      {tab === "payouts" && <PayoutsPanel run={run} />}
      {tab === "declarations" && <DeclarationsPanel run={run} />}
```

(removing `{tab === "payouts" && <div data-task="6-wires-PayoutsPanel-here" />}` and the matching `declarations` line).

- [ ] **Step 6: Manual verification of Review Focus item 3**

`test_a_missing_bank_template_offers_to_add_one` (manual, against the seed once payouts are generated for an approved run with a bank-paid employee whose bank has no template yet): confirm the amber inline note under the batch row names the bank and the "manage bank file templates" button opens `BankTemplatesDialog`; adding a template there and reopening the run page's payouts tab makes the note disappear and the download succeed.

- [ ] **Step 7: Type-check**

Run (from `frontend/`): `npx tsc -b --force`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/payroll/runs/run/PayoutsPanel.tsx frontend/src/features/payroll/runs/run/BankTemplatesDialog.tsx frontend/src/features/payroll/runs/run/DeclarationsPanel.tsx frontend/src/features/payroll/runs/RunPage.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(payroll): payouts panel with bank templates, and the declarations panel

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Payslip detail page and edit dialog

**Files:**
- Create: `frontend/src/features/payroll/payslips/PayslipPage.tsx`, `PayslipEditDialog.tsx`
- Modify: `frontend/src/routes/router.tsx`, `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: `usePayslip`, `useAdminUpdatePayslip`, `useCertificate` (Task 1); `DraftRuleSetBanner`, `PayrollStatusBadge` (Tasks 1–2).
- Produces: `/payroll/payslips/:id` route. `PayslipEditDialog` gated by `payroll.admin_payslips` (the mutation itself is server-gated; the frontend hides the "Edit" button when the write would 403 — following the platform's edit-in-place convention of hiding rather than showing a doomed action, same as every other `admin_*`-gated edit button in the codebase). Consumed nowhere else.

- [ ] **Step 1: Add the i18n keys**

```ts
// en
"payroll.payslip.title": "Payslip",
"payroll.payslip.edit": "Edit",
"payroll.payslip.print": "Print",
"payroll.payslip.certificate": "Work certificate",
"payroll.payslip.section.earning": "Earnings",
"payroll.payslip.section.employee_contribution": "Employee contributions",
"payroll.payslip.section.relief": "Reliefs",
"payroll.payslip.section.tax": "Tax",
"payroll.payslip.section.deduction": "Deductions",
"payroll.payslip.section.employer_contribution": "Employer contributions",
"payroll.payslip.section.employer_charge": "Employer charges",
"payroll.payslip.totals.gross": "Gross",
"payroll.payslip.totals.net": "Net pay",
"payroll.payslip.totals.employerCost": "Employer cost",
"payroll.payslip.warnings": "Warnings",
"payroll.payslipEdit.title": "Edit payslip",
"payroll.payslipEdit.note": "Note",
"payroll.payslipEdit.paymentMethods": "Payment methods (JSON)",
```

```ts
// fr
"payroll.payslip.title": "Bulletin de paie",
"payroll.payslip.edit": "Modifier",
"payroll.payslip.print": "Imprimer",
"payroll.payslip.certificate": "Certificat de travail",
"payroll.payslip.section.earning": "Gains",
"payroll.payslip.section.employee_contribution": "Cotisations salariales",
"payroll.payslip.section.relief": "Abattements",
"payroll.payslip.section.tax": "Impôt",
"payroll.payslip.section.deduction": "Retenues",
"payroll.payslip.section.employer_contribution": "Cotisations patronales",
"payroll.payslip.section.employer_charge": "Charges patronales",
"payroll.payslip.totals.gross": "Brut",
"payroll.payslip.totals.net": "Net à payer",
"payroll.payslip.totals.employerCost": "Coût employeur",
"payroll.payslip.warnings": "Avertissements",
"payroll.payslipEdit.title": "Modifier le bulletin",
"payroll.payslipEdit.note": "Note",
"payroll.payslipEdit.paymentMethods": "Moyens de paiement (JSON)",
```

- [ ] **Step 2: Write `PayslipEditDialog.tsx`**

```tsx
// frontend/src/features/payroll/payslips/PayslipEditDialog.tsx
import { useState } from "react";
import { useI18n } from "../../../lib/i18n";
import { useAdminUpdatePayslip, type PayslipDetail } from "../api";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Textarea } from "../../../components/ui/textarea";
import { Label } from "../../../components/ui/label";
import { Button } from "../../../components/ui/button";
import { toast } from "../../../components/ui/use-toast";

export function PayslipEditDialog({ open, onOpenChange, payslip }: { open: boolean; onOpenChange: (open: boolean) => void; payslip: PayslipDetail }) {
  const { t } = useI18n();
  const update = useAdminUpdatePayslip(payslip.id);
  const [note, setNote] = useState(payslip.note ?? "");
  const [methodsJson, setMethodsJson] = useState(JSON.stringify((payslip.snapshot as { payment_methods?: unknown }).payment_methods ?? [], null, 2));

  const submit = () => {
    let paymentMethods: Record<string, unknown>[] | undefined;
    try {
      paymentMethods = JSON.parse(methodsJson);
    } catch {
      toast({ title: "Invalid JSON", variant: "destructive" });
      return;
    }
    update
      .mutateAsync({ note, payment_methods: paymentMethods })
      .then(() => onOpenChange(false))
      .catch((error: Error) => toast({ title: error.message, variant: "destructive" }));
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("payroll.payslipEdit.title")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div>
            <Label>{t("payroll.payslipEdit.note")}</Label>
            <Textarea value={note} onChange={(event) => setNote(event.target.value)} />
          </div>
          <div>
            <Label>{t("payroll.payslipEdit.paymentMethods")}</Label>
            <Textarea rows={8} className="font-mono text-xs" value={methodsJson} onChange={(event) => setMethodsJson(event.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button onClick={submit} disabled={update.isPending}>
            {t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 3: Write `PayslipPage.tsx`** (Review Focus items 1 and 5 — draft banner and carried warnings)

```tsx
// frontend/src/features/payroll/payslips/PayslipPage.tsx
import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useI18n, useI18nLocale } from "../../../lib/i18n";
import { usePayslip } from "../api";
import { useAuth } from "../../../lib/auth";
import { DraftRuleSetBanner } from "../DraftRuleSetBanner";
import { PayrollStatusBadge } from "../PayrollStatusBadge";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { Button } from "../../../components/ui/button";
import { formatXof } from "../format";
import { PayslipEditDialog } from "./PayslipEditDialog";

const SECTION_ORDER = ["earning", "employee_contribution", "relief", "tax", "deduction", "employer_contribution", "employer_charge"] as const;

export function PayslipPage() {
  const { payslipId } = useParams<{ payslipId: string }>();
  const { t } = useI18n();
  const locale = useI18nLocale();
  const navigate = useNavigate();
  const { session } = useAuth();
  const { data: payslip, isLoading } = usePayslip(payslipId);
  const [editOpen, setEditOpen] = useState(false);

  if (isLoading || !payslip) return <AppLoader label={t("payroll.common.loading")} fullScreen />;

  const canEdit = (session?.permissions ?? []).includes("payroll.admin_payslips");

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">
            {payslip.full_name} ({payslip.employee_no})
          </h1>
          <PayrollStatusBadge domain="run" status={payslip.run_status} />
        </div>
        <div className="flex gap-2">
          {canEdit && <Button variant="outline" onClick={() => setEditOpen(true)}>{t("payroll.payslip.edit")}</Button>}
          <Button variant="outline" onClick={() => navigate(`/payroll/payslips/${payslip.id}/print`)}>
            {t("payroll.payslip.print")}
          </Button>
        </div>
      </div>
      <DraftRuleSetBanner ruleSet={payslip.rule_set_status === "draft" ? { id: "", name: payslip.employee_no, status: "draft" } : null} />
      {payslip.warnings.length > 0 && (
        <p className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">{payslip.warnings.join(", ")}</p>
      )}
      <table className="w-full text-sm">
        <tbody>
          {SECTION_ORDER.map((section) => {
            const lines = payslip.lines.filter((line) => line.section === section);
            if (lines.length === 0) return null;
            return (
              <>
                <tr key={`${section}-header`}>
                  <td colSpan={4} className="pt-4 font-semibold">
                    {t(`payroll.payslip.section.${section}` as never)}
                  </td>
                </tr>
                {lines.map((line) => (
                  <tr key={line.line_no}>
                    <td className="py-1">{locale === "fr" ? line.name_fr : line.name_en}</td>
                    <td className="py-1 text-right">{line.qty ?? ""}</td>
                    <td className="py-1 text-right">{line.rate ?? ""}</td>
                    <td className="py-1 text-right">{formatXof(line.amount, locale)}</td>
                  </tr>
                ))}
              </>
            );
          })}
        </tbody>
      </table>
      <div className="flex justify-end gap-6 border-t pt-3 text-sm font-semibold">
        <span>
          {t("payroll.payslip.totals.gross")}: {formatXof(payslip.gross, locale)}
        </span>
        <span>
          {t("payroll.payslip.totals.net")}: {formatXof(payslip.net, locale)}
        </span>
        <span>
          {t("payroll.payslip.totals.employerCost")}: {formatXof(payslip.employer_cost, locale)}
        </span>
      </div>
      <PayslipEditDialog open={editOpen} onOpenChange={setEditOpen} payslip={payslip} />
    </div>
  );
}
```

Note on the `DraftRuleSetBanner ruleSet={...}` call: `PayslipDetail` (Task 1's type) does not carry a `rule_set_id`, only `rule_set_status` (matching 3b Task 10's `PayslipService.get_payslip` response exactly — it returns `rule_set_status`, not the id). The banner therefore cannot deep-link to the exact rule set from the payslip page; pass an empty `id` (as above) so the banner still renders its warning text but do not render the `Link` when `id` is empty — adjust `DraftRuleSetBanner` (Task 2) to skip the link when `ruleSet.id` is falsy:

```tsx
      {ruleSet.id && (
        <Link to={`/payroll/rules?ruleSet=${ruleSet.id}`} className="ml-auto underline">
          {t("payroll.rules.draftBanner.link")}
        </Link>
      )}
```

(Replace the unconditional `<Link>` in `DraftRuleSetBanner.tsx` from Task 2 with this guarded version as part of this task's edit, since Task 2 could not have known about this constraint yet — this is the one retroactive edit to an earlier task's file in this plan, and it is additive/non-breaking to `RunPage`'s existing calls, which always pass a real id.)

- [ ] **Step 4: Guard `DraftRuleSetBanner`'s link**

Modify `frontend/src/features/payroll/DraftRuleSetBanner.tsx`, replacing:

```tsx
      <Link to={`/payroll/rules?ruleSet=${ruleSet.id}`} className="ml-auto underline">
        {t("payroll.rules.draftBanner.link")}
      </Link>
```

with:

```tsx
      {ruleSet.id && (
        <Link to={`/payroll/rules?ruleSet=${ruleSet.id}`} className="ml-auto underline">
          {t("payroll.rules.draftBanner.link")}
        </Link>
      )}
```

- [ ] **Step 5: Wire the route**

In `frontend/src/routes/router.tsx`, add `import { PayslipPage } from "../features/payroll/payslips/PayslipPage";` and `{ path: "/payroll/payslips/:payslipId", element: <PayslipPage /> },` to `protectedChildren`.

- [ ] **Step 6: Manual verification of Review Focus items 1 and 5**

`test_a_payslip_with_a_carried_warning_shows_it_on_screen_and_in_print` (manual, once Task 10's seed data or 3b's `test_what_the_net_cannot_cover_is_carried_to_a_later_run_once_approved` scenario exists in dev): open a payslip whose `warnings` includes `NET_NEGATIVE`; confirm the amber warning banner renders above the line table.

- [ ] **Step 7: Type-check**

Run (from `frontend/`): `npx tsc -b --force`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/payroll/payslips frontend/src/features/payroll/DraftRuleSetBanner.tsx frontend/src/routes/router.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(payroll): payslip detail page with lines, warnings and an admin edit dialog

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Print pages — payslip, run, cash sheet, declaration

**Files:**
- Create: `frontend/src/features/payroll/print/PrintShell.tsx`, `PayslipDocument.tsx`, `WorkCertificate.tsx`, `PayslipPrintPage.tsx`, `RunPrintPage.tsx`, `CashSheetPrintPage.tsx`, `DeclarationPrintPage.tsx`
- Modify: `frontend/src/routes/router.tsx`, `frontend/src/lib/i18n.tsx`

**Interfaces:**
- Consumes: `usePayslip`, `useRunPrint`, `useCashSheet`, `useCertificate`, `useDeclaration`, `useAnnualRecap` (Task 1); the existing global `@media print` rule in `frontend/src/index.css` (already hides `aside, nav, header` — verified present before writing this task, see Step 1).
- Produces: routes `/payroll/payslips/:id/print` (exact path from the cross-phase interfaces contract), `/payroll/runs/:id/print`, `/payroll/payout-batches/:id/cash-sheet/print`, `/payroll/declarations/print?period=&code=` and `/payroll/declarations/print?year=` (both handled by one `DeclarationPrintPage`, distinguished by which query param is present — see "Decisions / gaps found" item 1). `PrintShell` and `PayslipDocument` are reused by both `PayslipPrintPage` and `RunPrintPage`.

- [ ] **Step 1: Confirm the print CSS is already global**

Read `frontend/src/index.css` around its `@media print` block (already present: hides `aside, nav, header, .print-hidden, [data-no-print="true"]`, removes `main`'s margin/padding/max-width, and strips shadows to a thin border). Do not duplicate this rule in a per-page stylesheet. Each print page in this task renders inside the normal `AppLayout` (no new route-level layout is added — the spec's "printable HTML" requirement is met by this existing rule plus a `.print-hidden` class on the one on-screen "Print" button each page keeps), and its top-level wrapper uses `className="print:my-0"` (Tailwind's print variant) purely for on-screen padding, not for hiding chrome — the global rule already does that.

- [ ] **Step 2: Add the i18n keys**

```ts
// en
"payroll.print.button": "Print",
"payroll.print.payslipTitle": "Payslip",
"payroll.print.runTitle": "Payroll run",
"payroll.print.cashSheetTitle": "Cash sheet",
"payroll.print.declarationTitle": "Declaration",
"payroll.print.certificate.title": "Certificate of work",
"payroll.print.certificate.body": "We certify that {name} ({position}) was employed under a {contractType} contract from {hireDate} to {terminationDate}, leaving for the reason: {reason}.",
"payroll.print.cashSheet.column.employee": "Employee",
"payroll.print.cashSheet.column.amount": "Amount",
"payroll.print.cashSheet.column.signature": "Signature",
"payroll.print.cashSheet.totals": "Note and coin breakdown",
```

```ts
// fr
"payroll.print.button": "Imprimer",
"payroll.print.payslipTitle": "Bulletin de paie",
"payroll.print.runTitle": "Paie",
"payroll.print.cashSheetTitle": "Feuille de caisse",
"payroll.print.declarationTitle": "Déclaration",
"payroll.print.certificate.title": "Certificat de travail",
"payroll.print.certificate.body": "Nous certifions que {name} ({position}) a été employé(e) sous contrat {contractType} du {hireDate} au {terminationDate}, motif de départ : {reason}.",
"payroll.print.cashSheet.column.employee": "Employé",
"payroll.print.cashSheet.column.amount": "Montant",
"payroll.print.cashSheet.column.signature": "Signature",
"payroll.print.cashSheet.totals": "Détail billetage",
```

- [ ] **Step 3: Write `PrintShell.tsx`**

```tsx
// frontend/src/features/payroll/print/PrintShell.tsx
import type { ReactNode } from "react";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import type { CompanyHeader } from "../api";

export function PrintShell({ title, company, children }: { title: string; company: CompanyHeader; children: ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="mx-auto max-w-3xl space-y-4 bg-white p-8 text-black print:p-0">
      <div className="print-hidden flex justify-end">
        <Button onClick={() => window.print()}>{t("payroll.print.button")}</Button>
      </div>
      <div className="flex items-center justify-between border-b pb-3">
        <div>
          <p className="text-lg font-semibold">{company.name ?? "—"}</p>
          {company.address && <p className="text-xs text-muted-foreground">{company.address}</p>}
          {company.employer_inps_no && <p className="text-xs text-muted-foreground">INPS: {company.employer_inps_no}</p>}
          {company.employer_tax_id && <p className="text-xs text-muted-foreground">NIF: {company.employer_tax_id}</p>}
        </div>
        <p className="text-sm font-medium">{title}</p>
      </div>
      {children}
    </div>
  );
}
```

- [ ] **Step 4: Write `PayslipDocument.tsx`**

```tsx
// frontend/src/features/payroll/print/PayslipDocument.tsx
import { useI18n, useI18nLocale } from "../../../lib/i18n";
import type { PayslipDetail } from "../api";
import { formatXof, formatPeriod } from "../format";

const SECTION_ORDER = ["earning", "employee_contribution", "relief", "tax", "deduction", "employer_contribution", "employer_charge"] as const;

export function PayslipDocument({ payslip }: { payslip: PayslipDetail }) {
  const { t } = useI18n();
  const locale = useI18nLocale();

  return (
    <div className="space-y-3 break-inside-avoid border-b pb-6 last:border-b-0">
      <div className="flex justify-between text-sm">
        <span>
          {payslip.full_name} ({payslip.employee_no})
        </span>
        <span>{formatPeriod(payslip.period, locale)}</span>
      </div>
      {payslip.warnings.length > 0 && <p className="text-xs font-semibold text-amber-700">{payslip.warnings.join(", ")}</p>}
      <table className="w-full text-xs">
        <tbody>
          {SECTION_ORDER.map((section) => {
            const lines = payslip.lines.filter((line) => line.section === section);
            if (lines.length === 0) return null;
            return (
              <>
                <tr key={`${section}-header`}>
                  <td colSpan={4} className="pt-2 font-semibold">
                    {t(`payroll.payslip.section.${section}` as never)}
                  </td>
                </tr>
                {lines.map((line) => (
                  <tr key={line.line_no}>
                    <td>{locale === "fr" ? line.name_fr : line.name_en}</td>
                    <td className="text-right">{line.qty ?? ""}</td>
                    <td className="text-right">{line.rate ?? ""}</td>
                    <td className="text-right">{formatXof(line.amount, locale)}</td>
                  </tr>
                ))}
              </>
            );
          })}
        </tbody>
      </table>
      <div className="flex justify-end gap-6 text-xs font-semibold">
        <span>
          {t("payroll.payslip.totals.gross")}: {formatXof(payslip.gross, locale)}
        </span>
        <span>
          {t("payroll.payslip.totals.net")}: {formatXof(payslip.net, locale)}
        </span>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Write `WorkCertificate.tsx`**

```tsx
// frontend/src/features/payroll/print/WorkCertificate.tsx
import { useI18n } from "../../../lib/i18n";

interface Certificate {
  company: { name: string | null };
  full_name: string;
  employee_no: string;
  hire_date: string | null;
  termination_date: string | null;
  termination_reason: string | null;
  position_id: string | null;
  contract_type: string | null;
  issued_on: string;
}

export function WorkCertificate({ certificate }: { certificate: Certificate }) {
  const { t } = useI18n();
  const body = t("payroll.print.certificate.body")
    .replace("{name}", certificate.full_name)
    .replace("{position}", certificate.position_id ?? "—")
    .replace("{contractType}", certificate.contract_type ?? "—")
    .replace("{hireDate}", certificate.hire_date ?? "—")
    .replace("{terminationDate}", certificate.termination_date ?? "—")
    .replace("{reason}", certificate.termination_reason ?? "—");

  return (
    <div className="space-y-4 text-sm">
      <h2 className="text-center text-lg font-semibold">{t("payroll.print.certificate.title")}</h2>
      <p>{body}</p>
      <p className="text-right text-xs text-muted-foreground">{certificate.issued_on}</p>
    </div>
  );
}
```

- [ ] **Step 6: Write `PayslipPrintPage.tsx`**

```tsx
// frontend/src/features/payroll/print/PayslipPrintPage.tsx
import { useParams } from "react-router-dom";
import { useI18n } from "../../../lib/i18n";
import { usePayslip, useCertificate } from "../api";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { PrintShell } from "./PrintShell";
import { PayslipDocument } from "./PayslipDocument";
import { WorkCertificate } from "./WorkCertificate";

export function PayslipPrintPage() {
  const { payslipId } = useParams<{ payslipId: string }>();
  const { t } = useI18n();
  const { data: payslip, isLoading } = usePayslip(payslipId);
  const isSettlement = Boolean((payslip?.snapshot as { settlement?: unknown } | undefined)?.settlement);
  const { data: certificate } = useCertificate(isSettlement ? payslipId : undefined);

  if (isLoading || !payslip) return <AppLoader label={t("payroll.common.loading")} fullScreen />;

  return (
    <PrintShell title={t("payroll.print.payslipTitle")} company={payslip.company}>
      <PayslipDocument payslip={payslip} />
      {certificate && <WorkCertificate certificate={certificate as never} />}
    </PrintShell>
  );
}
```

- [ ] **Step 7: Write `RunPrintPage.tsx`**

```tsx
// frontend/src/features/payroll/print/RunPrintPage.tsx
import { useParams } from "react-router-dom";
import { useI18n } from "../../../lib/i18n";
import { useRunPrint } from "../api";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { PrintShell } from "./PrintShell";
import { PayslipDocument } from "./PayslipDocument";

export function RunPrintPage() {
  const { runId } = useParams<{ runId: string }>();
  const { t } = useI18n();
  const { data: document, isLoading } = useRunPrint(runId);

  if (isLoading || !document) return <AppLoader label={t("payroll.common.loading")} fullScreen />;

  return (
    <PrintShell title={t("payroll.print.runTitle")} company={document.company}>
      {document.payslips.length === 0 ? (
        <EmptyState title={t("payroll.run.payslips.empty.title")} description={t("payroll.run.payslips.empty.description")} />
      ) : (
        document.payslips.map((payslip) => <PayslipDocument key={payslip.id} payslip={payslip} />)
      )}
    </PrintShell>
  );
}
```

- [ ] **Step 8: Write `CashSheetPrintPage.tsx`**

```tsx
// frontend/src/features/payroll/print/CashSheetPrintPage.tsx
import { useParams } from "react-router-dom";
import { useI18n } from "../../../lib/i18n";
import { useCashSheet } from "../api";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { PrintShell } from "./PrintShell";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../../components/ui/table";
import { formatXof } from "../format";
import { useI18nLocale } from "../../../lib/i18n";

export function CashSheetPrintPage() {
  const { batchId } = useParams<{ batchId: string }>();
  const { t } = useI18n();
  const locale = useI18nLocale();
  const { data: sheet, isLoading } = useCashSheet(batchId);

  if (isLoading || !sheet) return <AppLoader label={t("payroll.common.loading")} fullScreen />;

  return (
    <PrintShell title={t("payroll.print.cashSheetTitle")} company={sheet.company}>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("payroll.print.cashSheet.column.employee")}</TableHead>
            <TableHead>{t("payroll.print.cashSheet.column.amount")}</TableHead>
            <TableHead>{t("payroll.print.cashSheet.column.signature")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sheet.lines.map((line) => (
            <TableRow key={line.employee_no}>
              <TableCell>{line.full_name}</TableCell>
              <TableCell>{formatXof(line.amount, locale)}</TableCell>
              <TableCell className="w-32 border-b" />
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <div className="pt-4 text-xs">
        <p className="font-semibold">{t("payroll.print.cashSheet.totals")}</p>
        {sheet.denominations.map((value) => (
          <p key={value}>
            {value} F CFA × {sheet.totals.counts[String(value)] ?? 0}
          </p>
        ))}
        <p>Total: {formatXof(sheet.totals.amount, locale)}</p>
      </div>
    </PrintShell>
  );
}
```

- [ ] **Step 9: Write `DeclarationPrintPage.tsx`**

```tsx
// frontend/src/features/payroll/print/DeclarationPrintPage.tsx
import { useSearchParams } from "react-router-dom";
import { useI18n } from "../../../lib/i18n";
import { useAnnualRecap, useDeclaration } from "../api";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { PrintShell } from "./PrintShell";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../../components/ui/table";

export function DeclarationPrintPage() {
  const [params] = useSearchParams();
  const { t } = useI18n();
  const period = params.get("period");
  const code = params.get("code");
  const year = params.get("year");
  const declaration = useDeclaration(period ?? "", code ?? undefined);
  const annual = useAnnualRecap(year ? Number(year) : 0);
  const active = year ? annual : declaration;
  const { data, isLoading } = active;

  if (isLoading || !data) return <AppLoader label={t("payroll.common.loading")} fullScreen />;

  return (
    <PrintShell title={t("payroll.print.declarationTitle")} company={{ name: null, address: null, employer_inps_no: null, employer_tax_id: null }}>
      <Table>
        <TableHeader>
          <TableRow>
            {data.columns.map((column) => (
              <TableHead key={column}>{column}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.rows.map((row, index) => (
            <TableRow key={index}>
              {data.columns.map((column) => (
                <TableCell key={column}>{String(row[column] ?? "")}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </PrintShell>
  );
}
```

Note: `useDeclaration`/`useAnnualRecap` are always both called (Rules of Hooks — never call a hook conditionally); each is `enabled: false` internally when its own params are missing (Task 1's `enabled: !!period && !!code` / `enabled: !!year`), so calling both unconditionally and picking the active one afterward is correct and matches how `PayslipPrintPage`/Task 1's other pages already read TanStack Query's `enabled` gate.

`declarationCsvUrl`/route note: the declaration/annual-recap print page has no company header from its own endpoint (`DeclarationService.declaration`/`.annual` return `{code, columns, rows, totals}` only — no `company` key per 3b Task 12's exact interface list), so `PrintShell` is given an empty `CompanyHeader` here deliberately, not a bug — flagged so a future task does not "fix" it by inventing a company field the backend does not return.

- [ ] **Step 10: Wire the print routes**

In `frontend/src/routes/router.tsx`, add the imports and, to `protectedChildren`:

```tsx
import { PayslipPrintPage } from "../features/payroll/print/PayslipPrintPage";
import { RunPrintPage } from "../features/payroll/print/RunPrintPage";
import { CashSheetPrintPage } from "../features/payroll/print/CashSheetPrintPage";
import { DeclarationPrintPage } from "../features/payroll/print/DeclarationPrintPage";
```

```tsx
  { path: "/payroll/payslips/:payslipId/print", element: <PayslipPrintPage /> },
  { path: "/payroll/runs/:runId/print", element: <RunPrintPage /> },
  { path: "/payroll/payout-batches/:batchId/cash-sheet/print", element: <CashSheetPrintPage /> },
  { path: "/payroll/declarations/print", element: <DeclarationPrintPage /> },
```

- [ ] **Step 11: Manual verification of Review Focus item 5 (print side)**

`test_a_payslip_with_a_carried_warning_shows_it_on_screen_and_in_print` (continuing Task 7's on-screen check): open `/payroll/payslips/:id/print` for the same payslip and confirm the amber warning text renders in `PayslipDocument` above its line table, and that `window.print()` preview (browser print dialog) shows it in black-and-white-safe styling (not relying on the amber color alone — confirm the text itself, not just the color, conveys the warning).

- [ ] **Step 12: Type-check**

Run (from `frontend/`): `npx tsc -b --force`
Expected: no errors.

- [ ] **Step 13: Commit**

```bash
git add frontend/src/features/payroll/print frontend/src/routes/router.tsx frontend/src/lib/i18n.tsx
git commit -m "feat(payroll): printable payslip, run, cash sheet and declaration pages

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Mali draft rule-set values (`payroll_mali_rules.py`)

**Files:**
- Create: `backend/scripts/payroll_mali_rules.py`
- Test: `backend/scripts/test_payroll_mali_rules.py` (plan-shape, no DB)

**Interfaces:**
- Consumes: `modules.payroll.api.rule_set_service.RuleSetService`, `modules.payroll.api.testing_support.rule_rows`-equivalent row shapes (this module writes its own row dicts directly through `RuleSetService.add_child`, it does not import test-only `testing_support`); `modules.payroll.domain.rules` component/contribution/bracket field names (3a Task 2's `ComponentRule`/`ContributionRule`/`TaxBracket`/etc. — the dict keys this module builds for `add_child` must match `CHILD_KINDS`' columns exactly, e.g. `components` rows need `code, name_en, name_fr, kind, taxable, contributable, formula_type, base_ref, default_amount, default_rate, display_order, payslip_section, declaration_code`).
- Produces: `MALI_VALID_FROM: datetime.date`, `create_mali_rule_set(service: RuleSetService, *, tenant_id: str, actor_id: str) -> dict` (returns the created rule-set document; **does not confirm it** — the seed stays a draft per the spec's "no invented thresholds" / "seed data, not code" rule), `print_to_confirm() -> None` (prints every rate/ceiling/bracket/relief under a "TO CONFIRM BY ACCOUNTANT" banner, same style as phase 1's `_print_to_confirm`). No Mali statutory value appears anywhere else in this plan or in `backend/modules/payroll/`.

Values here are **placeholders for the client's accountant to correct**, chosen to be internally consistent (brackets have no gaps/overlaps, a family relief step exists, an overtime rate exists for every band, employer charges close the loop) so `RuleSetService.confirm_rule_set` *could* succeed if the accountant confirmed it as-is, but this script deliberately leaves it `draft`. Public references for Mali payroll deductions (INPS retirement/family-benefit/work-accident contributions, AMO health cover, ITS progressive income tax) exist but change with each year's finance law — every number below is written from general public knowledge of Mali's payroll structure, not from a verified current-year rate table, which is exactly why the spec requires the draft/confirm gate before any of it pays anyone.

- [ ] **Step 1: Write the failing plan-shape test**

Create `backend/scripts/test_payroll_mali_rules.py`:

```python
"""The Mali rule-set builder is deterministic and produces a set that could later be confirmed."""
from __future__ import annotations

from scripts.payroll_mali_rules import MALI_VALID_FROM


def test_mali_valid_from_is_the_first_of_a_month():
    assert MALI_VALID_FROM.day == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run (from `backend/`): `.venv/Scripts/python -m pytest scripts/test_payroll_mali_rules.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.payroll_mali_rules'`.

- [ ] **Step 3: Write `payroll_mali_rules.py`**

```python
"""Mali payroll rule-set values: a DRAFT starting point for the accountant to confirm.

Every number below (contribution rates, ceilings, ITS brackets, family relief, seniority and
overtime scales, employer charges) is seed data, never code, and is written from general public
knowledge of Mali's payroll structure (INPS pension/family-benefit/work-accident contributions,
AMO health cover, progressive ITS income tax) — NOT a verified current-year rate table, since
those change with each year's finance law. The rule set this module creates is left `draft`
deliberately: `RuleSetService.confirm_rule_set` refuses nothing structurally (brackets have no
gaps/overlaps, every band/relief the engine needs is present), but going live on unconfirmed
numbers would violate "no invented thresholds pay anyone" (spec, "Rule on statutory values").

    .venv/Scripts/python -m scripts.payroll_mali_rules   # (only ever called from seed_hr_payroll)
"""
from __future__ import annotations

import datetime
from decimal import Decimal

from core.domain.result import Err
from modules.payroll.api.rule_set_service import RuleSetService

MALI_VALID_FROM = datetime.date(2026, 1, 1)
D = Decimal


def _ok(result):
    if isinstance(result, Err):
        raise RuntimeError(f"{result.code}: {result.message}")
    return result.value


def _fcfa(amount) -> str:
    return f"{int(amount):,}".replace(",", " ") + " F CFA"


_COMPONENTS = [
    {"code": "BASE", "name_en": "Base salary", "name_fr": "Salaire de base", "kind": "earning",
     "taxable": True, "contributable": True, "formula_type": "fixed", "display_order": 10, "payslip_section": "earnings"},
    {"code": "UNPAID_ABSENCE", "name_en": "Unpaid absence", "name_fr": "Absence non payée", "kind": "earning",
     "taxable": True, "contributable": True, "formula_type": "per_day", "display_order": 11, "payslip_section": "earnings"},
    {"code": "SENIORITY", "name_en": "Seniority bonus", "name_fr": "Prime d'ancienneté", "kind": "earning",
     "taxable": True, "contributable": True, "formula_type": "rate_x_base", "base_ref": "earned_base", "display_order": 20, "payslip_section": "earnings"},
    {"code": "OT_DAY", "name_en": "Overtime (day)", "name_fr": "Heures supplémentaires (jour)", "kind": "earning",
     "taxable": True, "contributable": True, "formula_type": "qty_x_rate", "display_order": 30, "payslip_section": "earnings"},
    {"code": "OT_NIGHT", "name_en": "Overtime (night)", "name_fr": "Heures supplémentaires (nuit)", "kind": "earning",
     "taxable": True, "contributable": True, "formula_type": "qty_x_rate", "display_order": 31, "payslip_section": "earnings"},
    {"code": "OT_REST_HOLIDAY", "name_en": "Overtime (rest day / holiday)", "name_fr": "Heures supplémentaires (repos / férié)",
     "kind": "earning", "taxable": True, "contributable": True, "formula_type": "qty_x_rate", "display_order": 32, "payslip_section": "earnings"},
    {"code": "TRANSPORT", "name_en": "Transport allowance", "name_fr": "Indemnité de transport", "kind": "earning",
     "taxable": False, "contributable": False, "formula_type": "fixed", "default_amount": 15000, "display_order": 40, "payslip_section": "earnings"},
    {"code": "HOUSING", "name_en": "Housing allowance", "name_fr": "Indemnité de logement", "kind": "earning",
     "taxable": True, "contributable": True, "formula_type": "fixed", "default_amount": 50000, "display_order": 41, "payslip_section": "earnings"},
    {"code": "BONUS", "name_en": "Bonus", "name_fr": "Prime exceptionnelle", "kind": "earning",
     "taxable": True, "contributable": True, "formula_type": "fixed", "display_order": 50, "payslip_section": "earnings"},
    {"code": "LEAVE_INDEMNITY", "name_en": "Paid-leave indemnity", "name_fr": "Indemnité compensatrice de congés",
     "kind": "earning", "taxable": True, "contributable": True, "formula_type": "per_day", "display_order": 60, "payslip_section": "earnings"},
    {"code": "NOTICE_INDEMNITY", "name_en": "Notice indemnity", "name_fr": "Indemnité de préavis", "kind": "earning",
     "taxable": True, "contributable": True, "formula_type": "fixed", "display_order": 61, "payslip_section": "earnings"},
    {"code": "SEVERANCE", "name_en": "Severance pay", "name_fr": "Indemnité de licenciement", "kind": "earning",
     "taxable": False, "contributable": False, "formula_type": "fixed", "display_order": 62, "payslip_section": "earnings"},
    {"code": "ADVANCE", "name_en": "Salary advance", "name_fr": "Avance sur salaire", "kind": "deduction",
     "taxable": False, "contributable": False, "formula_type": "fixed", "display_order": 80, "payslip_section": "deductions"},
    {"code": "LOAN", "name_en": "Loan instalment", "name_fr": "Échéance de prêt", "kind": "deduction",
     "taxable": False, "contributable": False, "formula_type": "fixed", "display_order": 81, "payslip_section": "deductions"},
    {"code": "TAXE_LOGEMENT", "name_en": "Housing tax (employer)", "name_fr": "Taxe logement", "kind": "employer_charge",
     "taxable": False, "contributable": False, "formula_type": "rate_x_base", "base_ref": "gross", "default_rate": "1",
     "display_order": 90, "payslip_section": "employer", "declaration_code": "EMPLOYER_TAXES"},
    {"code": "CFE", "name_en": "Employer flat-rate contribution", "name_fr": "Contribution forfaitaire employeur",
     "kind": "employer_charge", "taxable": False, "contributable": False, "formula_type": "rate_x_base", "base_ref": "gross",
     "default_rate": "3.5", "display_order": 91, "payslip_section": "employer", "declaration_code": "EMPLOYER_TAXES"},
    {"code": "FORMATION", "name_en": "Vocational training levy (ANPE/FAFPA)", "name_fr": "Taxe formation professionnelle (ANPE/FAFPA)",
     "kind": "employer_charge", "taxable": False, "contributable": False, "formula_type": "rate_x_base", "base_ref": "gross",
     "default_rate": "2", "display_order": 92, "payslip_section": "employer", "declaration_code": "EMPLOYER_TAXES"},
]

_CONTRIBUTIONS = [
    {"code": "PENSION", "name_en": "INPS pension", "name_fr": "INPS retraite", "base": "contributable",
     "employee_rate": "3.6", "employer_rate": "5.4", "ceiling_monthly": 600000, "deductible_from_taxable": True,
     "declaration_code": "SOCIAL", "display_order": 10},
    {"code": "FAMILY", "name_en": "INPS family benefits", "name_fr": "INPS prestations familiales", "base": "contributable",
     "employee_rate": "0", "employer_rate": "8", "ceiling_monthly": 600000, "deductible_from_taxable": True,
     "declaration_code": "SOCIAL", "display_order": 11},
    {"code": "WORK_ACCIDENT", "name_en": "INPS work accident", "name_fr": "INPS accidents du travail", "base": "contributable",
     "employee_rate": "0", "employer_rate": "3", "ceiling_monthly": 600000, "deductible_from_taxable": True,
     "declaration_code": "SOCIAL", "display_order": 12},
    {"code": "AMO", "name_en": "AMO health cover", "name_fr": "AMO assurance maladie", "base": "contributable",
     "employee_rate": "3.06", "employer_rate": "3.5", "ceiling_monthly": None, "deductible_from_taxable": True,
     "declaration_code": "HEALTH", "display_order": 20},
]

# (lower, upper, rate) monthly ITS brackets — to confirm against the current finance law.
_ITS_BRACKETS = [
    (0, 175000, 0), (175000, 600000, 5), (600000, 1200000, 13), (1200000, 1800000, 20),
    (1800000, 2400000, 28), (2400000, 3500000, 34), (3500000, None, 40),
]

_SENIORITY = [(2, 2), (5, 5), (10, 10), (15, 15), (20, 20), (25, 25)]  # years_from, percent
_OVERTIME = [("day", "1.4"), ("night", "1.75"), ("rest_holiday", "2")]
_SEVERANCE = [(0, 20), (5, 25), (10, 30)]  # years_from, percent_per_year


def create_mali_rule_set(service: RuleSetService, *, tenant_id: str, actor_id: str) -> dict:
    created = _ok(service.create_rule_set(
        tenant_id=tenant_id, actor_id=actor_id, country="ML", name="Mali (brouillon, à confirmer)",
        valid_from=MALI_VALID_FROM, working_days_per_month=D(26), working_hours_per_month=D(208),
        settlement_reference_months=12,
        notes="Valeurs DEMO à confirmer par le comptable avant toute paie réelle.",
    ))
    rule_set_id = created["id"]
    for component in _COMPONENTS:
        _ok(service.add_child(tenant_id=tenant_id, actor_id=actor_id, rule_set_id=rule_set_id, kind="components", values=component))
    for contribution in _CONTRIBUTIONS:
        _ok(service.add_child(tenant_id=tenant_id, actor_id=actor_id, rule_set_id=rule_set_id, kind="contributions", values=contribution))
    for lower, upper, rate in _ITS_BRACKETS:
        _ok(service.add_child(tenant_id=tenant_id, actor_id=actor_id, rule_set_id=rule_set_id, kind="tax_brackets",
                              values={"tax_code": "ITS", "lower_bound": lower, "upper_bound": upper, "rate": rate, "annualised": False}))
    _ok(service.add_child(
        tenant_id=tenant_id, actor_id=actor_id, rule_set_id=rule_set_id, kind="tax_reliefs",
        values={"tax_code": "ITS", "kind": "family",
                "parameters": {"mode": "percent_of_tax",
                               "steps": [{"dependants": 1, "value": "10"}, {"dependants": 2, "value": "15"},
                                         {"dependants": 3, "value": "20"}, {"dependants": 4, "value": "23"},
                                         {"dependants": 5, "value": "25"}, {"dependants": 6, "value": "30"}],
                               "cap_monthly": None}},
    ))
    _ok(service.add_child(
        tenant_id=tenant_id, actor_id=actor_id, rule_set_id=rule_set_id, kind="tax_reliefs",
        values={"tax_code": "ITS", "kind": "professional_expenses", "parameters": {"percent": "20", "cap_monthly": None}},
    ))
    for years_from, percent in _SENIORITY:
        _ok(service.add_child(tenant_id=tenant_id, actor_id=actor_id, rule_set_id=rule_set_id, kind="seniority_scale",
                              values={"years_from": years_from, "percent": percent}))
    for band_code, multiplier in _OVERTIME:
        _ok(service.add_child(tenant_id=tenant_id, actor_id=actor_id, rule_set_id=rule_set_id, kind="overtime_rates",
                              values={"band_code": band_code, "multiplier": multiplier}))
    for years_from, percent_per_year in _SEVERANCE:
        _ok(service.add_child(tenant_id=tenant_id, actor_id=actor_id, rule_set_id=rule_set_id, kind="severance_scale",
                              values={"years_from": years_from, "percent_per_year": percent_per_year}))
    return service.get_rule_set(tenant_id=tenant_id, rule_set_id=rule_set_id)


def print_to_confirm() -> None:
    print("\n=========== TO CONFIRM BY ACCOUNTANT: Mali payroll rule set (DRAFT) ===========")
    print(f"  rule set starts {MALI_VALID_FROM.isoformat()}, status left as DRAFT (not confirmed by this seed)")
    print("  contributions (employee % / employer % of contributable base, ceiling):")
    for row in _CONTRIBUTIONS:
        ceiling = _fcfa(row["ceiling_monthly"]) if row["ceiling_monthly"] else "none"
        print(f"    {row['code']:<14} {row['employee_rate']:>6} % / {row['employer_rate']:>6} %  ceiling {ceiling}")
    print("  ITS monthly brackets (lower, upper, rate):")
    for lower, upper, rate in _ITS_BRACKETS:
        upper_text = _fcfa(upper) if upper is not None else "and above"
        print(f"    {_fcfa(lower):>14} to {upper_text:<14} : {rate} %")
    print("  employer charges (% of gross): " + ", ".join(f"{c['code']} {c['default_rate']}%" for c in _COMPONENTS if c["kind"] == "employer_charge"))
    print("  seniority scale (years -> % of earned base): " + ", ".join(f"{y}y={p}%" for y, p in _SENIORITY))
    print("  overtime multipliers: " + ", ".join(f"{band}={mult}" for band, mult in _OVERTIME))
    print("  severance scale (years -> % per year of reference salary): " + ", ".join(f"{y}y={p}%" for y, p in _SEVERANCE))
    print("  TRANSPORT and HOUSING default amounts, and every rate above, are DEMO placeholders.")
    print("================================================================================")
```

- [ ] **Step 4: Run the test**

Run: `.venv/Scripts/python -m pytest scripts/test_payroll_mali_rules.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/payroll_mali_rules.py backend/scripts/test_payroll_mali_rules.py
git commit -m "chore(payroll): Mali draft rule-set values, to confirm by the accountant

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Extend `seed_hr_payroll.py` — rule set, monthly inputs, advances/loans, one calculated run

**Files:**
- Modify: `backend/scripts/seed_hr_payroll.py`
- Modify: `backend/scripts/test_seed_hr_payroll.py`, `backend/scripts/test_seed_hr_payroll_integration.py`

**Interfaces:**
- Consumes: `payroll_mali_rules.create_mali_rule_set` (Task 9); `modules.payroll.api.rule_set_service.RuleSetService`, `run_service.RunService`, `input_service.InputService`; phase 1's `TENANT`/`actor_id`/`run` from `scripts.seed_common` (already imported by the file) and whatever helper the file already uses to read back the 60 seeded employees' `id`/`employee_no` (read the file first, per phase 2's Task 14 convention — do not invent a second employee-listing helper); phase 2's `PERIOD = date(2026, 8, 1)` constant already present in the file after phase 2's Task 14 (August 2026, closed presence).
- Produces: nothing new for another phase — this is the leaf of the whole `hr`/`payroll`/`finance` seed chain so far. Running the script twice must not fail or duplicate: guarded by "does a payroll rule set for `ML` already exist" and "does a payroll run for `PERIOD` already exist", exactly like phase 1/2's own idempotency checks.

- [ ] **Step 1: Read the current seed script**

Open `backend/scripts/seed_hr_payroll.py` as phases 1 and 2 left it. Confirm: the `TENANT` constant (reuse it), the `PERIOD = date(2026, 8, 1)` constant phase 2 added (this task's run is calculated for this same period, since presence is already closed for it — do not seed a second month), how the script currently gets the list of seeded employees (`seeded_employees` in phase 2's sketch — an in-memory list of dicts with at least `id`, `employee_no`), and the single `seed(conn, args)` function's structure (opens/commits once, per `scripts.seed_common.run`). Append this task's block inside that same function, after phase 2's presence/leave block, following the same "skip if already seeded" pattern.

- [ ] **Step 2: Extend the plan-shape test**

In `backend/scripts/test_seed_hr_payroll.py`, add (keeping the existing three tests from phase 1 unchanged):

```python
def test_the_seed_names_a_payroll_period_matching_phase_twos_presence_month():
    from scripts.seed_hr_payroll import PAYROLL_PERIOD, PERIOD
    assert PAYROLL_PERIOD == PERIOD  # the seeded run is calculated for the same month presence closed
```

- [ ] **Step 3: Extend the integration test**

In `backend/scripts/test_seed_hr_payroll_integration.py`, add:

```python
def test_the_seed_adds_a_draft_mali_rule_set_and_one_calculated_run(db):
    if db.execute("SELECT 1 FROM core.users WHERE email = %s", (ACTOR_EMAIL,)).fetchone() is None:
        pytest.skip("the demo user is missing: run scripts.seed_dev first")
    seed_hr_payroll.seed(db, None)
    rule_set = db.execute("SELECT status FROM payroll.rule_sets WHERE tenant_id = %s AND country = 'ML'", (TENANT,)).fetchone()
    assert rule_set == ("draft",)
    run = db.execute("SELECT status, run_type FROM payroll.runs WHERE tenant_id = %s AND period = %s", (TENANT, seed_hr_payroll.PAYROLL_PERIOD)).fetchone()
    assert run == ("calculated", "regular")
    inputs = db.execute("SELECT count(*) FROM payroll.run_inputs r JOIN payroll.runs run ON run.id = r.run_id WHERE run.tenant_id = %s", (TENANT,)).fetchone()[0]
    assert inputs >= 1
    advances = db.execute("SELECT count(*) FROM payroll.advances WHERE tenant_id = %s", (TENANT,)).fetchone()[0]
    assert advances >= 1
    loans = db.execute("SELECT count(*) FROM payroll.loans WHERE tenant_id = %s", (TENANT,)).fetchone()[0]
    assert loans >= 1
    seed_hr_payroll.seed(db, None)  # idempotent: no duplicate rule set or run
    assert db.execute("SELECT count(*) FROM payroll.rule_sets WHERE tenant_id = %s AND country = 'ML'", (TENANT,)).fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM payroll.runs WHERE tenant_id = %s AND period = %s", (TENANT, seed_hr_payroll.PAYROLL_PERIOD)).fetchone()[0] == 1
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest scripts/test_seed_hr_payroll.py scripts/test_seed_hr_payroll_integration.py -q`
Expected: FAIL — `ImportError: cannot import name 'PAYROLL_PERIOD' from 'scripts.seed_hr_payroll'`.

- [ ] **Step 5: Extend the seed script**

Append to `backend/scripts/seed_hr_payroll.py` (inside the existing `seed()` function, after phase 2's presence/leave block; add the new imports at the top of the file alongside the existing ones):

```python
# --- Phase 3: Mali draft rule set, monthly inputs, advances/loans, one calculated run --------
from modules.payroll.api.input_service import InputService
from modules.payroll.api.rule_set_service import RuleSetService
from modules.payroll.api.run_service import RunService
from scripts.payroll_mali_rules import create_mali_rule_set, print_to_confirm as print_mali_to_confirm

PAYROLL_PERIOD = PERIOD  # same month phase 2 closed presence for: calculation needs it closed
```

then, still inside `seed()`, after the existing "Presence settings, holidays..." print line:

```python
    # --- Phase 3: payroll rule set, monthly inputs, advances/loans, one calculated run ------
    rules = RuleSetService(connection)
    existing_rule_set = connection.execute(
        "SELECT id FROM payroll.rule_sets WHERE tenant_id = %s AND country = 'ML'", (TENANT,)
    ).fetchone()
    if existing_rule_set:
        print("Payroll: Mali rule set already seeded; skipping (rerun-safe).")
    else:
        settings_saved = rules.save_settings(tenant_id=TENANT, actor_id=user_id, country="ML")
        if isinstance(settings_saved, Err):
            raise RuntimeError(f"{settings_saved.code}: {settings_saved.message}")
        rule_set = create_mali_rule_set(rules, tenant_id=TENANT, actor_id=user_id)
        print(f"Payroll: Mali rule set seeded as DRAFT ({rule_set['id']}), valid from {rule_set['valid_from']}.")
        print_mali_to_confirm()

    existing_run = connection.execute(
        "SELECT id FROM payroll.runs WHERE tenant_id = %s AND period = %s", (TENANT, PAYROLL_PERIOD)
    ).fetchone()
    if existing_run:
        print("Payroll: August 2026 run already seeded; skipping (rerun-safe).")
    else:
        runs = RunService(connection)
        inputs = InputService(connection)
        created_run = runs.create_run(tenant_id=TENANT, actor_id=user_id, period=PAYROLL_PERIOD, run_type="regular")
        if isinstance(created_run, Err):
            raise RuntimeError(f"{created_run.code}: {created_run.message}")
        run_id = created_run.value["id"]

        # One demo bonus and one demo advance so the Inputs screens show data.
        bonus_target = seeded_employees[5] if len(seeded_employees) > 5 else seeded_employees[0]
        bonus_result = inputs.add_run_input(
            tenant_id=TENANT, actor_id=user_id, run_id=run_id, employee_id=bonus_target["id"],
            component_code="BONUS", amount=Decimal(25000), note="Prime démo",
        )
        if isinstance(bonus_result, Err):
            raise RuntimeError(f"{bonus_result.code}: {bonus_result.message}")

        advance_target = seeded_employees[6] if len(seeded_employees) > 6 else seeded_employees[0]
        advance_created = inputs.create_advance(
            tenant_id=TENANT, actor_id=user_id, employee_id=advance_target["id"], amount=Decimal(30000),
            requested_on=PAYROLL_PERIOD, deduct_period=PAYROLL_PERIOD, note="Avance démo",
        )
        if isinstance(advance_created, Err):
            raise RuntimeError(f"{advance_created.code}: {advance_created.message}")
        advance_approved = inputs.approve_advance(tenant_id=TENANT, actor_id=user_id, advance_id=advance_created.value["id"])
        if isinstance(advance_approved, Err):
            raise RuntimeError(f"{advance_approved.code}: {advance_approved.message}")

        loan_target = seeded_employees[7] if len(seeded_employees) > 7 else seeded_employees[0]
        loan_created = inputs.create_loan(
            tenant_id=TENANT, actor_id=user_id, employee_id=loan_target["id"], principal=Decimal(150000),
            instalment_count=6, first_period=PAYROLL_PERIOD, note="Prêt démo",
        )
        if isinstance(loan_created, Err):
            raise RuntimeError(f"{loan_created.code}: {loan_created.message}")

        calculated = runs.calculate(tenant_id=TENANT, actor_id=user_id, run_id=run_id)
        if isinstance(calculated, Err):
            # PRESENCE_NOT_CLOSED here means phase 2's month-close step above did not run first in
            # this pass (fresh database) — this is the one payroll error worth surfacing loudly,
            # since every other seed step in this file tolerates re-runs silently.
            print(f"Payroll: could not calculate the August 2026 run ({calculated.code}: {calculated.message}); "
                  "run scripts.seed_hr_payroll again now that presence is closed.")
        else:
            print(f"Payroll: August 2026 run calculated ({calculated.value['payslip_count']} payslips, "
                  f"gross {calculated.value['gross']}, net {calculated.value['net']}); left as CALCULATED, not approved.")
    print("Payroll rule set, inputs, advances/loans and the run are DEMO seed data — see the TO CONFIRM banner above.")
```

Adjust `seeded_employees` (and `user_id`, `Err`, `Decimal`) to whatever names phase 1/2 actually used in the file — Step 1 already had the implementer confirm these; `Err` and `Decimal` are already imported by phase 1's version of the file (`core.domain.result.Err`, `decimal.Decimal`), so no new import is needed for those two.

- [ ] **Step 6: Run the tests, then the seed**

Run: `.venv/Scripts/python -m pytest scripts/test_seed_hr_payroll.py scripts/test_seed_hr_payroll_integration.py -q`
Expected: PASS.

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m scripts.seed_hr_payroll`
Expected: prints the Mali "TO CONFIRM BY ACCOUNTANT" banner, then "Payroll: August 2026 run calculated (... payslips, gross ..., net ...); left as CALCULATED, not approved." Run it again: both payroll blocks print "already seeded; skipping".

- [ ] **Step 7: Run the whole backend suite once**

Run: `.venv/Scripts/python -m pytest modules/hr modules/payroll core scripts -q`
Expected: PASS, no skips (a database must be reachable for this run per `CLAUDE.md`'s testing note).

- [ ] **Step 8: Commit**

```bash
git add backend/scripts/seed_hr_payroll.py backend/scripts/test_seed_hr_payroll.py backend/scripts/test_seed_hr_payroll_integration.py
git commit -m "chore(payroll): seed the Mali draft rule set, monthly inputs, advances/loans and one calculated run

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Grant demo permissions and browser-verify every `/payroll/*` screen against the seed

**Files:**
- Modify: `backend/scripts/seed_hr_payroll.py` (grant `payroll.*` permissions to the demo user)

**Interfaces:**
- Consumes: `POST /core/users/{id}/permissions` (existing core route — new permissions are never auto-granted, per `CLAUDE.md`).
- Produces: nothing for another task; this is the plan's final verification pass, run once with a browser against the seeded dev database, using the demo login `demo@sonalim-erp.local` / `demo1234`.

- [ ] **Step 1: Grant the demo user every payroll permission**

In `backend/scripts/seed_hr_payroll.py`'s `seed()` function, right after the payroll block Task 10 added (so the demo user can actually see the screens this plan just built), add:

```python
    for permission in (
        "payroll.view_runs", "payroll.calculate_runs", "payroll.approve_runs", "payroll.pay_runs",
        "payroll.reverse_runs", "payroll.manage_inputs", "payroll.view_rules", "payroll.manage_rules",
        "payroll.confirm_rules", "payroll.view_declarations", "payroll.admin_payslips",
    ):
        connection.execute(
            "INSERT INTO core.user_permissions (user_id, permission) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (user_id, permission),
        )
    print("Payroll: every payroll.* permission granted to the demo user (demo@sonalim-erp.local).")
```

Confirm `user_id` here is the same demo-admin user id phase 1's `seed()` already resolves at its top (the same variable `_ensure_self_service_user`'s caller uses, or the plain admin `user_id` — not the separate self-service employee login) — grant to the administrator demo account, since that is who this plan's manual checks log in as.

Note: this deliberately grants every payroll permission to one demo user rather than modelling a realistic four-eyes split (calculator vs. approver) in the seed, because `test_the_run_lifecycle_follows_rights_and_four_eyes` (3b Task 11) already proves the four-eyes rule works at the API level with two separate seeded test users — this seed's job is letting one person explore every screen in the browser, not re-demonstrating the permission split.

- [ ] **Step 2: Re-run the seed**

Run: `DATABASE_URL=postgresql://erp:erp@localhost:5432/erp PYTHONPATH=. .venv/Scripts/python.exe -m scripts.seed_hr_payroll`
Expected: prints the new "every payroll.* permission granted" line in addition to Task 10's output.

- [ ] **Step 3: Browser-verify every screen**

With the backend and frontend dev servers running and logged in as `demo@sonalim-erp.local` / `demo1234` (per `feedback_verify_frontend_in_repo` — verify in the actual running app, not by reading the code back), walk through:

1. `/payroll/rules` — the ML rule set shows `draft`; open it and confirm the seven rule-row tabs (components, contributions, tax brackets, tax reliefs, seniority scale, overtime rates, severance scale) each list Task 9's seeded rows; the settings card shows country `ML`.
2. `/payroll/runs` — the seeded August 2026 regular run shows status `Calculated`; open it.
3. On the run page: the `DraftRuleSetBanner` is visible (the run's rule set is Task 9's draft `ML` set); the Payslips tab lists every employee who has a contract in August 2026; the Variance tab shows "no previous approved run" (this is the first run ever calculated); the Final Settlements tab is empty (a regular run) and shows the "off-cycle only" message when switching to an off-cycle run created ad hoc during this check; Payouts and Declarations tabs are empty (the run is not yet approved).
4. `/payroll/inputs` — the Run Inputs tab shows Task 10's seeded `BONUS` input on the August run; the Advances tab shows the seeded approved advance; the Loans tab shows the seeded active loan with 6 instalments and a non-zero `remaining`.
5. Open a payslip from the Payslips tab (`/payroll/payslips/:id`): lines render grouped by section in the right order; the draft-rule-set warning text is visible; click Print and confirm `/payroll/payslips/:id/print` renders with the on-screen "Print" button hidden by the browser's print preview (`window.print()` dialog) and the sidebar/header hidden per the existing global `@media print` rule.
6. From the run page, click "Print the run" and confirm `/payroll/runs/:id/print` lists every payslip of the run, each with its own line table.
7. As the flow that exercises payouts end-to-end (not seeded, since the run is not approved): approve the run manually in the browser (note this needs a **second** demo permission-holder in a real four-eyes flow — for this manual check alone, temporarily accept the `SAME_USER_APPROVAL` refusal as expected behaviour per Review Focus item 2, then log in as a second seeded user or grant a second account the `approve_runs` permission to actually complete the approval and continue to payouts), generate payouts, confirm a bank batch has the "add a bank template" prompt (Review Focus item 3) until one is added via "manage bank file templates", then download it; open the cash batch's print page and confirm the billetage table renders.
8. Mark the run paid once every batch is confirmed; confirm `/payroll/runs/:id` now shows status `Paid` and the Declarations tab lists `SOCIAL`, `HEALTH`, `EMPLOYER_TAXES` (and `ITS` if any employee owed income tax that month); download one declaration's CSV and open `/payroll/declarations/print?period=2026-08-01&code=SOCIAL` directly to confirm the print variant renders the same table.
9. Confirm every string on every screen above switches correctly with the language toggle (en/fr) — this is the platform's bilingual requirement, not optional polish.

- [ ] **Step 4: Final type-check of the whole frontend**

Run (from `frontend/`): `npx tsc -b --force`
Expected: no errors — this is the same command every earlier task already ran; running it once more here catches any drift introduced by Task 10/11's backend-only changes having no frontend impact (a sanity confirmation, not expected to find anything new).

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/seed_hr_payroll.py
git commit -m "chore(payroll): grant the demo user every payroll permission for browser verification

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review

**1. Spec coverage.** Every screen the spec's Phase 3 "Screens" bullet names has a task: "Payroll → Runs (list, run page: calculate / review variances vs last month / approve / payouts / declarations)" → Tasks 3–6; "Payslip detail + print" → Tasks 7–8; "Inputs (monthly bonuses, advances, loans)" → Task 5; "Rules (rule sets, components, contributions, brackets, confirm)" → Task 2; the draft-rule-set banner ("The UI shows a banner on every payslip computed from a draft rule set") → Task 2 (`DraftRuleSetBanner`) wired into Rules (Task 2), the run page (Task 4), and the payslip page (Task 7); "printable HTML with print CSS... no server PDF library" → Task 8, reusing the repo's existing global `@media print` rule rather than inventing a parallel one; the Mali seed ("draft rule set... to confirm by accountant... pulled from 3a's seed task if it already stubbed one — check and extend, don't duplicate") → Tasks 9–10, which checked first (3a only left a forward-reference docstring, no actual file) and then built it once; "monthly `run_inputs`, one calculated (not approved) run, and any needed loans/advances demo rows" → Task 10 exactly, left `calculated` not `approved` as instructed. "My payslips (self-service)" is explicitly phase 5's screen per the spec's own phase split (`hr.self_service`, phase 5 self-service consumes `PayrollReportService.payslips_for_employee`), not this plan's — correctly out of scope here.

**2. Placeholder scan.** Two intentional, task-local placeholders exist and both are named and closed within this same plan, not left dangling: the `variance`/`payouts`/`declarations` `<div data-task="...">` markers in Task 4's `RunPage.tsx`, explicitly closed by Task 5 (variance) and Task 6 (payouts, declarations) with exact replacement code shown in those tasks' own steps — this is the plan's own file evolving across tasks, the accepted pattern for a component built by one task and consumed by a later one in the same plan, not a "TBD" left for someone else. No other `TODO`/`TBD`/"add validation"/"handle edge cases" text appears; every step shows the real code including error handling (inline `INPUT_INVALID` in Task 5, `PAYOUT_SPLIT_INVALID`/`TEMPLATE_MISSING` handling in Task 6, `SAME_USER_APPROVAL`/`RULESET_NOT_CONFIRMED` toasts in Task 4).

**3. Type consistency.** `PayrollRun`, `PayslipSummary`, `PayslipDetail`, `RunVariance`, `FinalSettlement`, `RunInput`, `Advance`, `Loan`, `PayoutBatch`, `CashSheet`, `Declaration` are defined once in Task 1's `api.ts` and imported by every later task — no task redefines a competing shape. `PayrollTable<Row>`'s prop contract (Task 1) is used identically by every list in Tasks 2, 3, 5, 6 (`RuleSetList`, `RuleRowsTable`, `RunsPage`, `PayslipsPanel`, `VariancePanel`, `RunInputsTab`, `AdvancesTab`, `LoansTab`, `PayoutsPanel`). `DraftRuleSetBanner`'s `ruleSet` prop shape (`{id, name, status}`) is used consistently by Task 2 (Rules), Task 4 (run page, from `rule_set_in_force`), and Task 7 (payslip page) — Task 7 surfaces the one real mismatch (payslip responses carry `rule_set_status` but no rule-set id or name) and resolves it in the same task rather than papering over it with a fake id, and retroactively guards `DraftRuleSetBanner`'s link rendering for that case (the only cross-task file edit in this plan, called out explicitly in Task 7 Step 4). `PAYROLL_KEYS` factories from Task 1 are the only query-key source used by every mutation's `invalidateQueries` call across Tasks 2–8 — no task invents a parallel ad hoc key array.

**4. Review Focus.** All five items have an owning task and a concrete verification step: (1) draft-rule-set banner — Task 2 builds it, Task 4/7 wire it, Task 4 Step 7 and Task 7 Step 6 are the manual tests; (2) same-user-approval / draft-ruleset refusal surfaced, not swallowed — Task 4 Step 7 (`test_approving_your_own_calculation_shows_the_refusal`); (3) missing bank template / bad payout split — Task 6 Step 6 (`test_a_missing_bank_template_offers_to_add_one`) plus the `PAYOUT_SPLIT_INVALID` toast already surfaced verbatim from the server (Task 6's `PayoutsPanel`/generate `onError`); (4) inline `INPUT_INVALID` on a bad component choice — Task 5 Step 10 (`test_a_bad_component_choice_shows_inline`); (5) a payslip with a carried `NET_NEGATIVE` warning visible on screen and in print — Task 7 Step 6 and Task 8 Step 11. No gap found beyond the two flagged in "Decisions / gaps found" above, both resolved within this plan's own scope (client-side rendering choices against existing endpoints), not by adding backend code here.

**5. Gaps against 3a/3b, restated for the caller.** (a) No print-specific backend route for the cash sheet or a declaration — resolved by rendering the existing JSON endpoints with print CSS client-side, matching how `PayslipPrintPage`/`RunPrintPage` already do it against `GET /payroll/payslips/{id}` and `GET /payroll/runs/{id}/print`. (b) `GET /payroll/employees` has no server-side name search — resolved by client-side filtering of the full (small, ~60-row) list; flagged as a one-line addition to 3b's own `routes_runs.py::employees()` if the employee count later makes that necessary, not added here. Neither required a new service method, a new table, or new business logic — both are within "a query param on an existing route is fine" territory and, in fact, needed no backend change at all for this plan's actual scope.
