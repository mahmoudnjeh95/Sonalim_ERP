import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiErrorFromResponse, apiFetch, networkError, BASE_URL } from "../../lib/api";
import { useAuth } from "../../lib/auth";

// Every type below mirrors what backend/modules/payroll/api/*_service.py returns (money and
// counts arrive as integers, rates as floats, dates as ISO strings — rows.jsonable).

// ---------------------------------------------------------------------------
// Closed lists (mirrors of backend/modules/payroll/domain/*.py)
// ---------------------------------------------------------------------------
export const RUN_STATUSES = ["draft", "calculated", "approved", "paid", "reversed"] as const;
export type RunStatus = (typeof RUN_STATUSES)[number];
export const RUN_TYPES = ["regular", "off_cycle"] as const;
export type RunType = (typeof RUN_TYPES)[number];
export type RuleSetStatus = "draft" | "confirmed";
export const ADVANCE_STATUSES = ["requested", "approved", "cancelled"] as const;
export type AdvanceStatus = (typeof ADVANCE_STATUSES)[number];
export const LOAN_STATUSES = ["active", "cancelled"] as const;
export type LoanStatus = (typeof LOAN_STATUSES)[number];
export const BATCH_STATUSES = ["generated", "confirmed"] as const;
export type BatchStatus = (typeof BATCH_STATUSES)[number];
export const PAYOUT_METHODS = ["bank", "mobile_money", "cash"] as const;
export type PayoutMethod = (typeof PAYOUT_METHODS)[number];
export const ROUND_MODES = ["half_up", "down", "up"] as const;
export type RoundMode = (typeof ROUND_MODES)[number];
export const DAILY_REST_DAY_PAY_MODES = ["overtime_only", "day_rate_and_overtime"] as const;
export type DailyRestDayPay = (typeof DAILY_REST_DAY_PAY_MODES)[number];
/** What a bank file template column can print (domain/payouts.py BANK_TEMPLATE_FIELDS). */
export const BANK_TEMPLATE_FIELDS = ["employee_no", "full_name", "bank_name", "account_no", "amount", "period", "reference"] as const;
export type BankTemplateField = (typeof BANK_TEMPLATE_FIELDS)[number];

// ---------------------------------------------------------------------------
// Rules (routes_rules.py, rule_set_service.py)
// ---------------------------------------------------------------------------
export interface PayrollSettings {
  tenant_id: string;
  country: string;
  company_address: string | null;
  employer_inps_no: string | null;
  employer_tax_id: string | null;
}

export interface PayrollSettingsInput {
  country: string;
  company_address?: string | null;
  employer_inps_no?: string | null;
  employer_tax_id?: string | null;
}

export interface RuleSetHeader {
  id: string;
  status: RuleSetStatus;
  confirmed_by: string | null;
  confirmed_at: string | null;
  created_by: string;
  created_at: string;
  country: string;
  name: string;
  valid_from: string;
  round_to: number;
  round_mode: RoundMode;
  tax_round_to: number;
  tax_round_mode: RoundMode;
  working_days_per_month: number;
  working_hours_per_month: number;
  settlement_reference_months: number;
  daily_rest_day_pay: DailyRestDayPay;
  notes: string | null;
}

export interface RuleSetInput {
  country: string;
  name: string;
  valid_from: string;
  working_days_per_month: number;
  working_hours_per_month: number;
  round_to?: number;
  round_mode?: RoundMode;
  tax_round_to?: number;
  tax_round_mode?: RoundMode;
  settlement_reference_months?: number;
  daily_rest_day_pay?: DailyRestDayPay;
  notes?: string | null;
}

/** The rule tables of a rule set, as `GET/POST /payroll/rule-sets/{id}/{kind}` name them (CHILD_KINDS). */
export const RULE_ROW_KINDS = [
  "components",
  "contributions",
  "tax_brackets",
  "tax_reliefs",
  "seniority_scale",
  "overtime_rates",
  "severance_scale",
] as const;
export type RuleRowKind = (typeof RULE_ROW_KINDS)[number];

/** One row of a rule table: `id` plus that kind's columns (rule_set_service.CHILD_KINDS). */
export type RuleRow = { id: string } & Record<string, unknown>;

export type RuleSetDocument = RuleSetHeader & Record<RuleRowKind, RuleRow[]>;

// ---------------------------------------------------------------------------
// Runs, payslips, final settlements (routes_runs.py, run_service.py, payslip_service.py)
// ---------------------------------------------------------------------------
export interface PayrollEmployee {
  employee_id: string;
  employee_no: string;
  full_name: string;
  department_id: string | null;
  termination_date: string | null;
}

export interface RuleSetRef {
  id: string;
  name: string;
  status: RuleSetStatus;
}

export interface PayrollRun {
  id: string;
  period: string;
  run_type: RunType;
  label: string | null;
  employee_ids: string[] | null;
  /** Set by calculate; back to null when the run returns to draft. */
  rule_set_id: string | null;
  rule_set_status: RuleSetStatus | null;
  status: RunStatus;
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
  /** Payslips carrying at least one warning. */
  warning_count: number;
  /** GET /payroll/runs/{id} only: the month's presence is closed (null on an off-cycle run). */
  presence_closed?: boolean | null;
  /** GET /payroll/runs/{id} only: the rule set that applies to the period today (null when none). */
  rule_set_in_force?: RuleSetRef | null;
}

export interface PayrollRunInput {
  period: string;
  run_type: RunType;
  label?: string | null;
  employee_ids?: string[] | null;
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
  /** Codes such as "NET_NEGATIVE". */
  warnings: string[];
  /** The rule set's status when this payslip was calculated. */
  rule_set_status: RuleSetStatus;
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

/** The employer block printed on payslips, cash sheets (company.company_header). */
export interface CompanyHeader {
  name: string | null;
  address: string | null;
  employer_inps_no: string | null;
  employer_tax_id: string | null;
}

export interface PayslipDetail extends PayslipSummary {
  /** What the payslip was computed from: employee, presence, inputs, settlement, payment_methods, rule_set. */
  snapshot: Record<string, unknown>;
  period: string;
  run_type: RunType;
  run_status: RunStatus;
  lines: PayslipLine[];
  company: CompanyHeader;
}

export interface PayslipAdminChanges {
  note?: string | null;
  payment_methods?: Record<string, unknown>[];
}

export interface RunPrintDocument {
  run: { id: string; period: string; run_type: RunType; label: string | null; status: RunStatus };
  company: CompanyHeader;
  payslips: PayslipDetail[];
}

/** GET /payroll/payslips/{id}/certificate — only for a final-settlement payslip (404 otherwise). */
export interface WorkCertificateData {
  company: CompanyHeader;
  full_name: string;
  employee_no: string;
  hire_date: string | null;
  termination_date: string | null;
  termination_reason: string | null;
  position_id: string | null;
  contract_type: string | null;
  issued_on: string;
}

export interface VarianceRow {
  employee_id: string;
  employee_no: string;
  full_name: string;
  /** null when the employee was not on the previous run ("new") or is not on this one ("left"). */
  previous_gross: number | null;
  current_gross: number | null;
  previous_net: number | null;
  current_net: number | null;
  delta_gross: number;
  delta_net: number;
  change: "new" | "left" | "same" | "changed";
}

export interface RunVariance {
  /** The previous month's approved/paid regular run; null when there is none to compare with. */
  previous_run_id: string | null;
  previous_period: string;
  rows: VarianceRow[];
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

export interface FinalSettlementInput {
  employee_id: string;
  unused_leave_days?: number;
  notice_months?: number;
}

// ---------------------------------------------------------------------------
// Monthly inputs, advances, loans (routes_inputs.py, input_service.py)
// ---------------------------------------------------------------------------
export interface InputComponent {
  code: string;
  name_en: string;
  name_fr: string;
  kind: "earning" | "deduction";
  formula_type: "fixed" | "qty_x_rate" | "per_day";
  default_amount: number | null;
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

export interface RunInputInput {
  employee_id: string;
  component_code: string;
  qty?: number | null;
  amount?: number | null;
  note?: string | null;
}

export interface RunInputChanges {
  component_code?: string;
  qty?: number | null;
  amount?: number | null;
  note?: string | null;
}

export interface Advance {
  id: string;
  employee_id: string;
  employee_no: string;
  full_name: string;
  amount: number;
  requested_on: string;
  deduct_period: string;
  status: AdvanceStatus;
  approved_by: string | null;
  approved_at: string | null;
  note: string | null;
  deducted_payslip_id: string | null;
  created_by: string;
  created_at: string;
  /** The run whose payslip took it, when one did. */
  deducted_run_id: string | null;
  deducted_period: string | null;
  deducted_run_status: RunStatus | null;
}

export interface AdvanceInput {
  employee_id: string;
  amount: number;
  requested_on: string;
  deduct_period: string;
  note?: string | null;
}

export interface AdvanceChanges {
  amount?: number;
  requested_on?: string;
  deduct_period?: string;
  note?: string | null;
}

export interface LoanInstalment {
  id: string;
  loan_id: string;
  seq: number;
  period: string;
  amount: number;
  /** The run whose payslip took this instalment, when one did. */
  run_id: string | null;
  run_status: RunStatus | null;
  /** Taken by an approved or paid run. */
  deducted: boolean;
}

export interface Loan {
  id: string;
  employee_id: string;
  employee_no: string;
  full_name: string;
  principal: number;
  instalment_count: number;
  first_period: string;
  status: LoanStatus;
  note: string | null;
  created_by: string;
  created_at: string;
  instalments: LoanInstalment[];
  /** Instalments not yet deducted by an approved/paid run; 0 once cancelled. */
  remaining: number;
}

export interface LoanInput {
  employee_id: string;
  principal: number;
  instalment_count: number;
  first_period: string;
  note?: string | null;
}

export interface LoanChanges {
  principal?: number;
  instalment_count?: number;
  first_period?: string;
  note?: string | null;
}

// ---------------------------------------------------------------------------
// Payouts (routes_payouts.py, payout_service.py)
// ---------------------------------------------------------------------------
export interface BankTemplateColumn {
  header: string;
  /** One of BANK_TEMPLATE_FIELDS. */
  field: string;
}

export interface BankFileTemplate {
  id: string;
  bank_name: string;
  delimiter: string;
  include_header: boolean;
  columns: BankTemplateColumn[];
}

export interface BankFileTemplateInput {
  bank_name: string;
  delimiter?: string;
  include_header?: boolean;
  columns: BankTemplateColumn[];
}

export interface PayoutBatch {
  id: string;
  run_id: string;
  method: PayoutMethod;
  /** The bank name, the mobile operator, or "CASH". */
  group_key: string;
  status: BatchStatus;
  file_name: string;
  total: number;
  line_count: number;
  generated_by: string;
  generated_at: string;
  confirmed_by: string | null;
  confirmed_at: string | null;
}

export interface CashSheetLine {
  employee_no: string;
  full_name: string;
  amount: number;
  /** Notes/coins per denomination, keyed by the denomination as a string. */
  counts: Record<string, number>;
  remainder: number;
}

export interface CashSheet {
  batch: PayoutBatch;
  period: string;
  company: CompanyHeader;
  denominations: number[];
  lines: CashSheetLine[];
  totals: { amount: number; counts: Record<string, number>; remainder: number };
}

// ---------------------------------------------------------------------------
// Declarations (routes_declarations.py, declaration_service.py)
// ---------------------------------------------------------------------------
export interface Declaration {
  /** The declaration code, or "ANNUAL" for the annual recap. */
  code: string;
  columns: string[];
  rows: Record<string, string | number | null>[];
  totals: Record<string, number>;
  /** Monthly declaration only. */
  period?: string;
  /** Annual recap only. */
  year?: number;
}

// ---------------------------------------------------------------------------
// Query keys: every payroll read lives under ["payroll", ...]. A parent key is a prefix of its
// children, so invalidating runs.detail(id) also refreshes that run's payslips, inputs, payouts.
// ---------------------------------------------------------------------------
export const PAYROLL_KEYS = {
  all: ["payroll"] as const,
  rules: {
    all: ["payroll", "rules"] as const,
    settings: ["payroll", "rules", "settings"] as const,
    list: ["payroll", "rules", "rule-sets", "list"] as const,
    detail: (id: string) => ["payroll", "rules", "rule-sets", id] as const,
    children: (id: string, kind: RuleRowKind) => ["payroll", "rules", "rule-sets", id, kind] as const,
  },
  runs: {
    all: ["payroll", "runs"] as const,
    lists: ["payroll", "runs", "list"] as const,
    list: (status?: string) => ["payroll", "runs", "list", status ?? "all"] as const,
    detail: (id: string) => ["payroll", "runs", id] as const,
    payslips: (id: string) => ["payroll", "runs", id, "payslips"] as const,
    variance: (id: string) => ["payroll", "runs", id, "variance"] as const,
    print: (id: string) => ["payroll", "runs", id, "print"] as const,
    settlements: (id: string) => ["payroll", "runs", id, "final-settlements"] as const,
    payouts: (id: string) => ["payroll", "runs", id, "payouts"] as const,
    inputs: (id: string) => ["payroll", "runs", id, "inputs"] as const,
    inputComponents: (id: string) => ["payroll", "runs", id, "input-components"] as const,
  },
  employees: (period: string) => ["payroll", "employees", period] as const,
  payslip: {
    all: ["payroll", "payslips"] as const,
    detail: (id: string) => ["payroll", "payslips", id] as const,
    certificate: (id: string) => ["payroll", "payslips", id, "certificate"] as const,
  },
  advances: {
    all: ["payroll", "advances"] as const,
    list: (status?: string) => ["payroll", "advances", status ?? "all"] as const,
  },
  loans: {
    all: ["payroll", "loans"] as const,
    list: (status?: string) => ["payroll", "loans", status ?? "all"] as const,
  },
  templates: {
    list: ["payroll", "bank-file-templates"] as const,
  },
  payouts: {
    all: ["payroll", "payout-batches"] as const,
    cashSheet: (batchId: string) => ["payroll", "payout-batches", batchId, "cash-sheet"] as const,
  },
  declarations: {
    all: ["payroll", "declarations"] as const,
    codes: (period: string) => ["payroll", "declarations", "codes", period] as const,
    one: (period: string, code: string) => ["payroll", "declarations", "one", period, code] as const,
    annual: (year: number) => ["payroll", "declarations", "annual", year] as const,
  },
};

type QueryClient = ReturnType<typeof useQueryClient>;

function useToken(): string {
  const { session } = useAuth();
  return session?.token ?? "";
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** Rule changes move which rule set is in force, its status on runs, and the components runs accept. */
function invalidateRules(client: QueryClient) {
  void client.invalidateQueries({ queryKey: PAYROLL_KEYS.rules.all });
  void client.invalidateQueries({ queryKey: PAYROLL_KEYS.runs.all });
}

/**
 * A run's lifecycle (and every input to it) reaches beyond the run: a calculated run that loses
 * an input goes back to draft and drops its payslips and payouts, releasing the advances and loan
 * instalments they took; approving or reversing changes what declarations count. Refresh every
 * read that shows any of it.
 */
function invalidateRunData(client: QueryClient) {
  for (const queryKey of [
    PAYROLL_KEYS.runs.all,
    PAYROLL_KEYS.payslip.all,
    PAYROLL_KEYS.advances.all,
    PAYROLL_KEYS.loans.all,
    PAYROLL_KEYS.payouts.all,
    PAYROLL_KEYS.declarations.all,
  ]) {
    void client.invalidateQueries({ queryKey });
  }
}

// ---------------------------------------------------------------------------
// Rules
// ---------------------------------------------------------------------------
export function usePayrollSettings() {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.rules.settings,
    // null until the payroll country is first saved
    queryFn: () => apiFetch<PayrollSettings | null>("/payroll/settings", { token }),
  });
}

export function useSavePayrollSettings() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: PayrollSettingsInput) => apiFetch<PayrollSettings>("/payroll/settings", { method: "PUT", token, body }),
    onSuccess: () => invalidateRules(client),
  });
}

export function useRuleSets() {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.rules.list,
    queryFn: () => apiFetch<RuleSetHeader[]>("/payroll/rule-sets", { token }),
  });
}

export function useRuleSet(id: string | undefined) {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.rules.detail(id ?? ""),
    queryFn: () => apiFetch<RuleSetDocument>(`/payroll/rule-sets/${id}`, { token }),
    enabled: !!id,
  });
}

export function useCreateRuleSet() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: RuleSetInput) => apiFetch<RuleSetDocument>("/payroll/rule-sets", { method: "POST", token, body }),
    onSuccess: () => invalidateRules(client),
  });
}

export function useUpdateRuleSet(id: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (changes: Partial<RuleSetInput>) =>
      apiFetch<RuleSetDocument>(`/payroll/rule-sets/${id}`, { method: "PATCH", token, body: changes }),
    onSuccess: () => invalidateRules(client),
  });
}

export function useDeleteRuleSet() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<{ id: string }>(`/payroll/rule-sets/${id}`, { method: "DELETE", token }),
    onSuccess: () => invalidateRules(client),
  });
}

/** Copies a rule set (any status) into a new draft starting at `valid_from`. */
export function useCopyRuleSet(id: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { valid_from: string; name: string }) =>
      apiFetch<RuleSetDocument>(`/payroll/rule-sets/${id}/copy`, { method: "POST", token, body }),
    onSuccess: () => invalidateRules(client),
  });
}

export function useConfirmRuleSet() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<RuleSetDocument>(`/payroll/rule-sets/${id}/confirm`, { method: "POST", token }),
    onSuccess: () => invalidateRules(client),
  });
}

export function useReopenRuleSet() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<RuleSetDocument>(`/payroll/rule-sets/${id}/reopen`, { method: "POST", token }),
    onSuccess: () => invalidateRules(client),
  });
}

export function useRuleRows(ruleSetId: string, kind: RuleRowKind) {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.rules.children(ruleSetId, kind),
    queryFn: () => apiFetch<RuleRow[]>(`/payroll/rule-sets/${ruleSetId}/${kind}`, { token }),
    enabled: !!ruleSetId,
  });
}

export function useAddRuleRow(ruleSetId: string, kind: RuleRowKind) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (values: Record<string, unknown>) =>
      apiFetch<RuleRow>(`/payroll/rule-sets/${ruleSetId}/${kind}`, { method: "POST", token, body: values }),
    onSuccess: () => invalidateRules(client),
  });
}

export function useUpdateRuleRow(ruleSetId: string, kind: RuleRowKind) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ rowId, changes }: { rowId: string; changes: Record<string, unknown> }) =>
      apiFetch<RuleRow>(`/payroll/rule-sets/${ruleSetId}/${kind}/${rowId}`, { method: "PATCH", token, body: changes }),
    onSuccess: () => invalidateRules(client),
  });
}

export function useDeleteRuleRow(ruleSetId: string, kind: RuleRowKind) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (rowId: string) =>
      apiFetch<{ id: string }>(`/payroll/rule-sets/${ruleSetId}/${kind}/${rowId}`, { method: "DELETE", token }),
    onSuccess: () => invalidateRules(client),
  });
}

// ---------------------------------------------------------------------------
// Employees: who can be on a payslip that month — names only, no salary (payroll.view_runs)
// ---------------------------------------------------------------------------
export function usePayrollEmployees(period: string) {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.employees(period),
    queryFn: () => apiFetch<PayrollEmployee[]>(`/payroll/employees${query({ period })}`, { token }),
    enabled: !!period,
  });
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------
export function useRuns(status?: string) {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.runs.list(status),
    queryFn: () => apiFetch<PayrollRun[]>(`/payroll/runs${query({ status_filter: status })}`, { token }),
  });
}

export function useRun(id: string | undefined) {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.runs.detail(id ?? ""),
    queryFn: () => apiFetch<PayrollRun>(`/payroll/runs/${id}`, { token }),
    enabled: !!id,
  });
}

export function useCreateRun() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: PayrollRunInput) => apiFetch<PayrollRun>("/payroll/runs", { method: "POST", token, body }),
    onSuccess: () => void client.invalidateQueries({ queryKey: PAYROLL_KEYS.runs.lists }),
  });
}

/** Label and, on an off-cycle run, the employee list (changing it sends a calculated run back to draft). */
export function useUpdateRun(id: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (changes: { label?: string | null; employee_ids?: string[] | null }) =>
      apiFetch<PayrollRun>(`/payroll/runs/${id}`, { method: "PATCH", token, body: changes }),
    onSuccess: () => invalidateRunData(client),
  });
}

export function useDeleteRun() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<{ id: string }>(`/payroll/runs/${id}`, { method: "DELETE", token }),
    onSuccess: () => invalidateRunData(client),
  });
}

export function useCalculateRun() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<PayrollRun>(`/payroll/runs/${id}/calculate`, { method: "POST", token }),
    onSuccess: () => invalidateRunData(client),
  });
}

/** Refused with 409 SAME_USER_APPROVAL (own calculation) or RULESET_NOT_CONFIRMED (draft/newer rule set). */
export function useApproveRun() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<PayrollRun>(`/payroll/runs/${id}/approve`, { method: "POST", token }),
    onSuccess: () => invalidateRunData(client),
  });
}

export function useReverseRun() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      apiFetch<PayrollRun>(`/payroll/runs/${id}/reverse`, { method: "POST", token, body: { reason } }),
    onSuccess: () => invalidateRunData(client),
  });
}

/** POST /payroll/runs/{id}/mark-paid (payroll.pay_runs) — refused with PAYOUT_INCOMPLETE until every batch is confirmed. */
export function useMarkPaid() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<PayrollRun>(`/payroll/runs/${id}/mark-paid`, { method: "POST", token }),
    onSuccess: () => invalidateRunData(client),
  });
}

export function useRunPayslips(runId: string | undefined) {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.runs.payslips(runId ?? ""),
    queryFn: () => apiFetch<PayslipSummary[]>(`/payroll/runs/${runId}/payslips`, { token }),
    enabled: !!runId,
  });
}

export function useRunVariance(runId: string | undefined) {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.runs.variance(runId ?? ""),
    queryFn: () => apiFetch<RunVariance>(`/payroll/runs/${runId}/variance`, { token }),
    enabled: !!runId,
  });
}

export function useRunPrint(runId: string | undefined) {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.runs.print(runId ?? ""),
    queryFn: () => apiFetch<RunPrintDocument>(`/payroll/runs/${runId}/print`, { token }),
    enabled: !!runId,
  });
}

// ---------------------------------------------------------------------------
// Final settlements (off-cycle runs only)
// ---------------------------------------------------------------------------
export function useFinalSettlements(runId: string | undefined) {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.runs.settlements(runId ?? ""),
    queryFn: () => apiFetch<FinalSettlement[]>(`/payroll/runs/${runId}/final-settlements`, { token }),
    enabled: !!runId,
  });
}

export function useAddFinalSettlement(runId: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: FinalSettlementInput) =>
      apiFetch<FinalSettlement>(`/payroll/runs/${runId}/final-settlements`, { method: "POST", token, body }),
    onSuccess: () => invalidateRunData(client),
  });
}

export function useUpdateFinalSettlement(runId: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ settlementId, changes }: { settlementId: string; changes: { unused_leave_days?: number; notice_months?: number } }) =>
      apiFetch<FinalSettlement>(`/payroll/runs/${runId}/final-settlements/${settlementId}`, { method: "PATCH", token, body: changes }),
    onSuccess: () => invalidateRunData(client),
  });
}

export function useRemoveFinalSettlement(runId: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (settlementId: string) =>
      apiFetch<{ id: string }>(`/payroll/runs/${runId}/final-settlements/${settlementId}`, { method: "DELETE", token }),
    onSuccess: () => invalidateRunData(client),
  });
}

// ---------------------------------------------------------------------------
// Payslips
// ---------------------------------------------------------------------------
export function usePayslip(id: string | undefined) {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.payslip.detail(id ?? ""),
    queryFn: () => apiFetch<PayslipDetail>(`/payroll/payslips/${id}`, { token }),
    enabled: !!id,
  });
}

/** Note and payment details only (payroll.admin_payslips); new payment details drop the run's payout batches. */
export function useAdminUpdatePayslip(id: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (changes: PayslipAdminChanges) => apiFetch<PayslipDetail>(`/payroll/payslips/${id}`, { method: "PATCH", token, body: changes }),
    onSuccess: () => invalidateRunData(client),
  });
}

export function useCertificate(id: string | undefined) {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.payslip.certificate(id ?? ""),
    queryFn: () => apiFetch<WorkCertificateData>(`/payroll/payslips/${id}/certificate`, { token }),
    enabled: !!id,
  });
}

// ---------------------------------------------------------------------------
// Monthly inputs (one-off amounts on a run; payroll.manage_inputs to write)
// ---------------------------------------------------------------------------
/** The components a monthly input may use, from the rule set in force for the run's period. */
export function useInputComponents(runId: string | undefined) {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.runs.inputComponents(runId ?? ""),
    queryFn: () => apiFetch<InputComponent[]>(`/payroll/runs/${runId}/input-components`, { token }),
    enabled: !!runId,
  });
}

export function useRunInputs(runId: string | undefined) {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.runs.inputs(runId ?? ""),
    queryFn: () => apiFetch<RunInput[]>(`/payroll/runs/${runId}/inputs`, { token }),
    enabled: !!runId,
  });
}

export function useAddRunInput(runId: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: RunInputInput) => apiFetch<RunInput>(`/payroll/runs/${runId}/inputs`, { method: "POST", token, body }),
    onSuccess: () => invalidateRunData(client),
  });
}

/** PATCH /payroll/run-inputs/{inputId}; `runId` only scopes nothing server-side — kept for callers' symmetry. */
export function useUpdateRunInput(runId: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ inputId, changes }: { inputId: string; changes: RunInputChanges }) =>
      apiFetch<RunInput>(`/payroll/run-inputs/${inputId}`, { method: "PATCH", token, body: changes }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: PAYROLL_KEYS.runs.inputs(runId) });
      invalidateRunData(client);
    },
  });
}

export function useDeleteRunInput(runId: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (inputId: string) => apiFetch<{ id: string }>(`/payroll/run-inputs/${inputId}`, { method: "DELETE", token }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: PAYROLL_KEYS.runs.inputs(runId) });
      invalidateRunData(client);
    },
  });
}

// ---------------------------------------------------------------------------
// Advances
// ---------------------------------------------------------------------------
export function useAdvances(status?: string) {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.advances.list(status),
    queryFn: () => apiFetch<Advance[]>(`/payroll/advances${query({ status_filter: status })}`, { token }),
  });
}

export function useCreateAdvance() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: AdvanceInput) => apiFetch<Advance>("/payroll/advances", { method: "POST", token, body }),
    onSuccess: () => invalidateRunData(client),
  });
}

export function useUpdateAdvance() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: AdvanceChanges }) =>
      apiFetch<Advance>(`/payroll/advances/${id}`, { method: "PATCH", token, body: changes }),
    onSuccess: () => invalidateRunData(client),
  });
}

export function useApproveAdvance() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<Advance>(`/payroll/advances/${id}/approve`, { method: "POST", token }),
    onSuccess: () => invalidateRunData(client),
  });
}

export function useCancelAdvance() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<Advance>(`/payroll/advances/${id}/cancel`, { method: "POST", token }),
    onSuccess: () => invalidateRunData(client),
  });
}

// ---------------------------------------------------------------------------
// Loans
// ---------------------------------------------------------------------------
export function useLoans(status?: string) {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.loans.list(status),
    queryFn: () => apiFetch<Loan[]>(`/payroll/loans${query({ status_filter: status })}`, { token }),
  });
}

export function useCreateLoan() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: LoanInput) => apiFetch<Loan>("/payroll/loans", { method: "POST", token, body }),
    onSuccess: () => invalidateRunData(client),
  });
}

export function useUpdateLoan() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: LoanChanges }) =>
      apiFetch<Loan>(`/payroll/loans/${id}`, { method: "PATCH", token, body: changes }),
    onSuccess: () => invalidateRunData(client),
  });
}

export function useCancelLoan() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<Loan>(`/payroll/loans/${id}/cancel`, { method: "POST", token }),
    onSuccess: () => invalidateRunData(client),
  });
}

// ---------------------------------------------------------------------------
// Payouts: bank file templates, batches, cash sheets
// ---------------------------------------------------------------------------
export function useBankTemplates() {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.templates.list,
    queryFn: () => apiFetch<BankFileTemplate[]>("/payroll/bank-file-templates", { token }),
  });
}

export function useCreateTemplate() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (values: BankFileTemplateInput) =>
      apiFetch<BankFileTemplate>("/payroll/bank-file-templates", { method: "POST", token, body: values }),
    onSuccess: () => void client.invalidateQueries({ queryKey: PAYROLL_KEYS.templates.list }),
  });
}

export function useUpdateTemplate() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: Partial<BankFileTemplateInput> }) =>
      apiFetch<BankFileTemplate>(`/payroll/bank-file-templates/${id}`, { method: "PATCH", token, body: changes }),
    onSuccess: () => void client.invalidateQueries({ queryKey: PAYROLL_KEYS.templates.list }),
  });
}

export function useDeleteTemplate() {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<{ id: string }>(`/payroll/bank-file-templates/${id}`, { method: "DELETE", token }),
    onSuccess: () => void client.invalidateQueries({ queryKey: PAYROLL_KEYS.templates.list }),
  });
}

export function usePayoutBatches(runId: string | undefined) {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.runs.payouts(runId ?? ""),
    queryFn: () => apiFetch<PayoutBatch[]>(`/payroll/runs/${runId}/payouts`, { token }),
    enabled: !!runId,
  });
}

/** (Re)generates every batch of an approved run; refused once a batch is confirmed. */
export function useGeneratePayouts(runId: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<PayoutBatch[]>(`/payroll/runs/${runId}/payouts`, { method: "POST", token }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: PAYROLL_KEYS.runs.payouts(runId) });
      void client.invalidateQueries({ queryKey: PAYROLL_KEYS.payouts.all });
    },
  });
}

export function useConfirmBatch(runId: string) {
  const token = useToken();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (batchId: string) => apiFetch<PayoutBatch>(`/payroll/payout-batches/${batchId}/confirm`, { method: "POST", token }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: PAYROLL_KEYS.runs.payouts(runId) });
      void client.invalidateQueries({ queryKey: PAYROLL_KEYS.payouts.all });
    },
  });
}

export function useCashSheet(batchId: string | undefined) {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.payouts.cashSheet(batchId ?? ""),
    queryFn: () => apiFetch<CashSheet>(`/payroll/payout-batches/${batchId}/cash-sheet`, { token }),
    enabled: !!batchId,
  });
}

// ---------------------------------------------------------------------------
// Declarations (payroll.view_declarations): approved and paid runs only
// ---------------------------------------------------------------------------
export function useDeclarationCodes(period: string) {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.declarations.codes(period),
    queryFn: () => apiFetch<string[]>(`/payroll/declarations/codes${query({ period })}`, { token }),
    enabled: !!period,
  });
}

export function useDeclaration(period: string, code: string | undefined) {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.declarations.one(period, code ?? ""),
    queryFn: () => apiFetch<Declaration>(`/payroll/declarations${query({ period, code })}`, { token }),
    enabled: !!period && !!code,
  });
}

export function useAnnualRecap(year: number) {
  const token = useToken();
  return useQuery({
    queryKey: PAYROLL_KEYS.declarations.annual(year),
    queryFn: () => apiFetch<Declaration>(`/payroll/declarations/annual${query({ year })}`, { token }),
    enabled: year > 0,
  });
}

// ---------------------------------------------------------------------------
// File downloads (CSV). These bypass apiFetch, which always parses JSON; the URLs are absolute
// (API origin), since the API does not share the SPA's origin. The route needs the bearer token,
// so a bare <a href> would 401: fetch it with fetchPayrollFile, then save the blob.
// ---------------------------------------------------------------------------

/** A bank or mobile-money batch file (payroll.pay_runs). A bank batch with no template for its bank is refused with TEMPLATE_MISSING; a cash batch with PAYOUT_INVALID. */
export function batchFileUrl(batchId: string): string {
  return `${BASE_URL}/payroll/payout-batches/${batchId}/file`;
}

export function declarationCsvUrl(period: string, code: string): string {
  return `${BASE_URL}/payroll/declarations${query({ period, code, format: "csv" })}`;
}

export function annualRecapCsvUrl(year: number): string {
  return `${BASE_URL}/payroll/declarations/annual${query({ year, format: "csv" })}`;
}

/** GETs one of the URLs above with the session token; a refusal throws the same bilingual ApiError as apiFetch (its `code` tells TEMPLATE_MISSING apart). */
export async function fetchPayrollFile(token: string, url: string): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  } catch {
    throw networkError();
  }
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event("auth:unauthorized"));
    throw await apiErrorFromResponse(response);
  }
  return response.blob();
}
