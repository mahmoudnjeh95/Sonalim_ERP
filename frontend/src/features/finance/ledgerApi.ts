import type { QueryClient } from "@tanstack/react-query";
import { apiFetch } from "../../lib/api";

export const ACCOUNT_TYPES = ["asset", "liability", "equity", "income", "expense"] as const;
export type AccountType = (typeof ACCOUNT_TYPES)[number];

export interface LedgerAccount {
  code: string;
  name: string;
  class_no: number;
  account_type: AccountType;
  is_postable: boolean;
  parent_code: string | null;
}

export interface AccountInput {
  code: string;
  name: string;
  account_type: AccountType;
  is_postable: boolean;
  parent_code: string | null;
}

export interface AccountPatch {
  name?: string;
  account_type?: AccountType;
  is_postable?: boolean;
  /** "" removes the parent. */
  parent_code?: string;
}

export interface Journal {
  code: string;
  name: string;
  journal_type: string;
}

export type PeriodStatus = "open" | "closed";

export interface AccountingPeriod {
  period: string;
  year: number;
  status: PeriodStatus;
  closed_by: string | null;
  closed_at: string | null;
}

export const RULE_SOURCES = ["payroll", "invoice", "purchase_invoice"] as const;
export type RuleSource = (typeof RULE_SOURCES)[number];
export const RULE_KINDS: Record<RuleSource, readonly string[]> = {
  payroll: ["earning", "deduction", "employee_contribution", "employer_contribution", "employer_charge", "tax", "net", "payment"],
  invoice: ["issued", "paid"],
  purchase_invoice: ["validated", "vat"],
};
export type RuleStatus = "to_confirm" | "confirmed";

export interface PostingRule {
  id: string;
  source: RuleSource;
  source_kind: string;
  code: string;
  debit_account_code: string | null;
  credit_account_code: string | null;
  journal_code: string | null;
  status: RuleStatus;
  confirmed_by: string | null;
  confirmed_at: string | null;
  updated_at: string;
}

export interface PostingRuleInput {
  source: RuleSource;
  source_kind: string;
  code: string;
  debit_account_code: string | null;
  credit_account_code: string | null;
  journal_code: string | null;
}

/** Every field optional; "" clears it. */
export interface PostingRulePatch {
  debit_account_code?: string;
  credit_account_code?: string;
  journal_code?: string;
}

export type EntryStatus = "draft" | "posted" | "reversed";

export interface JournalEntry {
  id: string;
  number: string | null;
  journal_code: string;
  entry_date: string;
  period: string;
  label: string;
  reference: string | null;
  status: EntryStatus;
  source_module: string | null;
  source_id: string | null;
  source_kind: string | null;
  reversal_of: string | null;
  created_by: string;
  created_at: string;
  posted_by: string | null;
  posted_at: string | null;
  total_debit: number;
  total_credit: number;
}

export interface JournalLine {
  line_no: number;
  account_code: string;
  account_name: string;
  debit: number;
  credit: number;
  label: string | null;
  partner_id: string | null;
  partner_name: string | null;
  employee_ref: string | null;
}

export interface JournalEntryDetail extends JournalEntry {
  lines: JournalLine[];
}

export interface EntryLineInput {
  account_code: string;
  debit: number;
  credit: number;
  label?: string | null;
  partner_id?: string | null;
}

export interface EntryInput {
  journal_code: string;
  entry_date: string;
  label: string;
  reference?: string | null;
  lines: EntryLineInput[];
}

export interface EntryFilters {
  date_from: string;
  date_to: string;
  journal_code?: string;
}

export type FailureStatus = "open" | "resolved" | "cancelled";

export interface PostingFailure {
  id: string;
  source_module: string;
  source_id: string;
  source_kind: string;
  event_id: string;
  event_type: string;
  error_code: string;
  error_message: string;
  error_message_fr: string | null;
  status: FailureStatus;
  failed_at: string;
  resolved_at: string | null;
}

export interface SourcePostings {
  entries: JournalEntry[];
  failures: PostingFailure[];
}

export interface TrialBalanceAmounts {
  opening_debit: number;
  opening_credit: number;
  period_debit: number;
  period_credit: number;
  closing_debit: number;
  closing_credit: number;
}

export interface TrialBalanceRow extends TrialBalanceAmounts {
  account_code: string;
  account_name: string;
  class_no: number;
}

export interface TrialBalance {
  rows: TrialBalanceRow[];
  totals: TrialBalanceAmounts;
}

export interface GeneralLedgerLine {
  entry_id: string;
  number: string;
  journal_code: string;
  entry_date: string;
  label: string;
  reference: string | null;
  debit: number;
  credit: number;
  balance: number;
}

export interface GeneralLedger {
  account: LedgerAccount;
  opening_balance: number;
  lines: GeneralLedgerLine[];
  total_debit: number;
  total_credit: number;
  closing_balance: number;
}

export interface AccountBalance {
  account_code: string;
  account_name: string;
  debit: number;
  credit: number;
  owed: number;
}

export const LEDGER_KEYS = {
  accounts: ["finance", "ledger", "accounts"] as const,
  journals: ["finance", "ledger", "journals"] as const,
  periods: ["finance", "ledger", "periods"] as const,
  rules: ["finance", "ledger", "posting-rules"] as const,
  entries: ["finance", "ledger", "entries"] as const,
  entryList: (filters: EntryFilters) => ["finance", "ledger", "entries", "list", filters] as const,
  entry: (id: string) => ["finance", "ledger", "entries", "detail", id] as const,
  failures: ["finance", "ledger", "posting-failures"] as const,
  reports: ["finance", "ledger", "reports"] as const,
  trialBalance: (from: string, to: string) => ["finance", "ledger", "reports", "trial-balance", from, to] as const,
  generalLedger: (code: string, from: string, to: string) =>
    ["finance", "ledger", "reports", "general-ledger", code, from, to] as const,
  balances: (asOf: string) => ["finance", "ledger", "reports", "balances", asOf] as const,
  sources: ["finance", "ledger", "sources"] as const,
  source: (module: string, id: string) => ["finance", "ledger", "sources", module, id] as const,
};

/** After anything that posts, reverses or deletes: every read that could show it. */
export function invalidateLedgerData(queryClient: QueryClient) {
  for (const queryKey of [LEDGER_KEYS.entries, LEDGER_KEYS.reports, LEDGER_KEYS.sources, LEDGER_KEYS.failures]) {
    void queryClient.invalidateQueries({ queryKey });
  }
}

function query(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) search.set(key, value);
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function setupLedger(token: string) {
  return apiFetch<{ accounts: number; journals: number; posting_rules: number }>("/finance/setup", { method: "POST", token });
}

export function listAccounts(token: string) {
  return apiFetch<LedgerAccount[]>("/finance/accounts", { token });
}

export function createAccount(token: string, input: AccountInput) {
  return apiFetch<LedgerAccount>("/finance/accounts", { method: "POST", token, body: input });
}

export function updateAccount(token: string, code: string, patch: AccountPatch) {
  return apiFetch<LedgerAccount>(`/finance/accounts/${encodeURIComponent(code)}`, { method: "PATCH", token, body: patch });
}

export function listJournals(token: string) {
  return apiFetch<Journal[]>("/finance/journals", { token });
}

export function listPeriods(token: string) {
  return apiFetch<AccountingPeriod[]>("/finance/periods", { token });
}

export function openFiscalYear(token: string, year: number) {
  return apiFetch<{ id: string; year: number }>("/finance/fiscal-years", { method: "POST", token, body: { year } });
}

export function closePeriod(token: string, period: string) {
  return apiFetch<AccountingPeriod>(`/finance/periods/${period}/close`, { method: "POST", token });
}

export function reopenPeriod(token: string, period: string) {
  return apiFetch<AccountingPeriod>(`/finance/periods/${period}/reopen`, { method: "POST", token });
}

export function listPostingRules(token: string) {
  return apiFetch<PostingRule[]>("/finance/posting-rules", { token });
}

export function createPostingRule(token: string, input: PostingRuleInput) {
  return apiFetch<PostingRule>("/finance/posting-rules", { method: "POST", token, body: input });
}

export function updatePostingRule(token: string, id: string, patch: PostingRulePatch) {
  return apiFetch<PostingRule>(`/finance/posting-rules/${id}`, { method: "PATCH", token, body: patch });
}

export function confirmPostingRule(token: string, id: string) {
  return apiFetch<PostingRule>(`/finance/posting-rules/${id}/confirm`, { method: "POST", token });
}

export function listEntries(token: string, filters: EntryFilters) {
  const search = query({ date_from: filters.date_from, date_to: filters.date_to, journal_code: filters.journal_code });
  return apiFetch<JournalEntry[]>(`/finance/entries${search}`, { token });
}

export function getEntry(token: string, id: string) {
  return apiFetch<JournalEntryDetail>(`/finance/entries/${id}`, { token });
}

export function createEntry(token: string, input: EntryInput) {
  return apiFetch<JournalEntryDetail>("/finance/entries", { method: "POST", token, body: input });
}

export function updateEntry(token: string, id: string, input: EntryInput) {
  return apiFetch<JournalEntryDetail>(`/finance/entries/${id}`, { method: "PATCH", token, body: input });
}

export function deleteEntry(token: string, id: string) {
  return apiFetch<{ id: string }>(`/finance/entries/${id}`, { method: "DELETE", token });
}

export function postEntry(token: string, id: string) {
  return apiFetch<JournalEntry>(`/finance/entries/${id}/post`, {
    method: "POST",
    token,
    body: { correlation_id: crypto.randomUUID() },
  });
}

export function reverseEntry(token: string, id: string, entryDate: string) {
  return apiFetch<JournalEntry>(`/finance/entries/${id}/reverse`, {
    method: "POST",
    token,
    body: { entry_date: entryDate, correlation_id: crypto.randomUUID() },
  });
}

export function listPostingFailures(token: string) {
  return apiFetch<PostingFailure[]>("/finance/posting-failures?status=open", { token });
}

export function retryPostingFailure(token: string, id: string) {
  return apiFetch<{ entries: JournalEntry[] }>(`/finance/posting-failures/${id}/retry`, { method: "POST", token });
}

export function getSourcePostings(token: string, module: string, id: string) {
  return apiFetch<SourcePostings>(`/finance/ledger/sources/${encodeURIComponent(module)}/${encodeURIComponent(id)}`, { token });
}

export function getTrialBalance(token: string, from: string, to: string) {
  return apiFetch<TrialBalance>(`/finance/reports/trial-balance${query({ date_from: from, date_to: to })}`, { token });
}

export function getGeneralLedger(token: string, accountCode: string, from: string, to: string) {
  const search = query({ account_code: accountCode, date_from: from, date_to: to });
  return apiFetch<GeneralLedger>(`/finance/reports/general-ledger${search}`, { token });
}

export function getBalances(token: string, asOf: string) {
  return apiFetch<AccountBalance[]>(`/finance/reports/balances${query({ as_of: asOf, prefixes: "42,43,44" })}`, { token });
}
