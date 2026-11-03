import { apiFetch } from "../../lib/api";

export type AccountKind = "bank" | "cash" | "mobile_money";

export interface Branch {
  id: string;
  bank_id: string;
  name: string;
  city: string | null;
  address: string | null;
  phone: string | null;
}

export interface Bank {
  id: string;
  name: string;
  code: string | null;
  swift: string | null;
  country: string | null;
  is_active: boolean;
  branches: Branch[];
}

export interface TreasuryAccount {
  id: string;
  kind: AccountKind;
  name: string;
  currency: string;
  account_number: string | null;
  iban: string | null;
  branch_id: string | null;
  operator: string | null;
  phone: string | null;
  opening_balance: string;
  balance: string;
  allow_overdraft: boolean;
  ledger_account_code: string | null;
  is_active: boolean;
}

export interface AccountInput {
  kind: AccountKind;
  name: string;
  currency: string;
  account_number?: string;
  iban?: string;
  branch_id?: string;
  operator?: string;
  phone?: string;
  opening_balance?: number;
  allow_overdraft?: boolean;
  ledger_account_code?: string;
}

export interface AccountMovement {
  id: string;
  amount: string;
  balance_after: string;
  source_type: string;
  source_id: string | null;
  occurred_on: string;
  note: string | null;
}

export interface AlertRule {
  direction: "in" | "out";
  method: "cheque" | "draft";
  offset_days: number;
  is_default: boolean;
}

export interface TreasurySettings {
  cash_payment_limit: number | null;
  prior_year_invoice_cutoff: string | null;
}

export const listBanks = (token: string) => apiFetch<Bank[]>("/treasury/banks", { token });
export const createBank = (token: string, body: { name: string; code?: string; swift?: string; country?: string }) =>
  apiFetch<Bank>("/treasury/banks", { method: "POST", token, body });
export const addBranch = (token: string, bankId: string, body: { name: string; city?: string; address?: string; phone?: string }) =>
  apiFetch<Branch>(`/treasury/banks/${bankId}/branches`, { method: "POST", token, body });

export const listAccounts = (token: string, includeInactive = false) =>
  apiFetch<TreasuryAccount[]>(`/treasury/accounts${includeInactive ? "?include_inactive=true" : ""}`, { token });
export const createAccount = (token: string, body: AccountInput) =>
  apiFetch<TreasuryAccount>("/treasury/accounts", { method: "POST", token, body });
export const updateAccount = (token: string, id: string, body: Partial<Omit<AccountInput, "kind">> & { is_active?: boolean }) =>
  apiFetch<TreasuryAccount>(`/treasury/accounts/${id}`, { method: "PATCH", token, body });
export const listMovements = (token: string, id: string) => apiFetch<AccountMovement[]>(`/treasury/accounts/${id}/movements`, { token });

export const getSettings = (token: string) => apiFetch<TreasurySettings>("/treasury/settings", { token });
export const putSetting = (token: string, key: keyof TreasurySettings, value: unknown) =>
  apiFetch<TreasurySettings>(`/treasury/settings/${key}`, { method: "PUT", token, body: { value } });
export const listAlertRules = (token: string) => apiFetch<AlertRule[]>("/treasury/alert-rules", { token });
export const putAlertRule = (token: string, direction: string, method: string, offset_days: number) =>
  apiFetch<AlertRule[]>(`/treasury/alert-rules/${direction}/${method}`, { method: "PUT", token, body: { offset_days } });
