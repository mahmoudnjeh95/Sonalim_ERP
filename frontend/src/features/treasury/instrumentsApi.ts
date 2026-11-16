import { apiFetch } from "../../lib/api";

export interface Instrument {
  id: string;
  direction: "in" | "out";
  method: "cash" | "cheque" | "draft" | "transfer" | "mobile_money";
  number: string;
  bank_name: string;
  due_date: string;
  amount: string;
  currency: string;
  status: "pending" | "collected" | "unpaid" | "cancelled";
  document_id: string;
  document_number: string;
  account_id: string | null;
  partner_id: string;
  rejection_fee: string | null;
  rejection_fee_account_id: string | null;
  issue_date: string | null;
  branch_name: string | null;
  deposit_date: string | null;
  slip_reference: string | null;
  account_name: string | null;
}

export interface InstrumentAlert extends Instrument {
  days_overdue: number;
}

export interface CashJournalRow {
  date: string;
  account_id: string;
  account_name: string;
  label: string;
  source_type: string;
  document_number: string | null;
  direction: "in" | "out" | null;
  partner_name: string | null;
  money_in: string;
  money_out: string;
  balance: string;
}

export interface CashJournal {
  year: number;
  opening_balance: string;
  closing_balance: string;
  rows: CashJournalRow[];
}

export const listInstruments = (token: string, params?: { status?: string; direction?: string }) => {
  const query = new URLSearchParams();
  if (params?.status) query.set("status_filter", params.status);
  if (params?.direction) query.set("direction", params.direction);
  return apiFetch<Instrument[]>(`/treasury/instruments${query.toString() ? `?${query}` : ""}`, { token });
};

export const postDepositSlip = (
  token: string,
  body: { account_id?: string; slip_date: string; items: { instrument_id: string; outcome: "collected" | "unpaid" }[] },
) => apiFetch<{ id?: string; number?: string; slips?: { id: string; number: string }[] }>("/treasury/deposit-slips", { method: "POST", token, body });

export const markUnpaid = (token: string, id: string, fee?: { rejection_fee: number; rejection_fee_account_id: string }) =>
  apiFetch<Instrument>(`/treasury/instruments/${id}/unpaid`, { method: "POST", token, body: fee ?? {} });

export const listAlerts = (token: string) => apiFetch<InstrumentAlert[]>("/treasury/alerts", { token });

export const getCashJournal = (token: string, year: number, accountId?: string) => {
  const query = new URLSearchParams({ year: String(year) });
  if (accountId) query.set("account_id", accountId);
  return apiFetch<CashJournal>(`/treasury/journals/cash?${query}`, { token });
};
