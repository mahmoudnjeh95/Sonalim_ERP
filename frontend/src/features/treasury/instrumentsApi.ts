import { apiFetch } from "../../lib/api";

export interface Instrument {
  id: string;
  direction: "in" | "out";
  method: "cheque" | "draft";
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
}

export interface InstrumentAlert extends Instrument {
  days_overdue: number;
}

export interface CashJournal {
  opening_balance: string;
  closing_balance: string;
  rows: { date: string; label: string; money_in: string; money_out: string; balance: string }[];
}

export const listInstruments = (token: string, params?: { status?: string; direction?: string }) => {
  const query = new URLSearchParams();
  if (params?.status) query.set("status_filter", params.status);
  if (params?.direction) query.set("direction", params.direction);
  return apiFetch<Instrument[]>(`/treasury/instruments${query.toString() ? `?${query}` : ""}`, { token });
};

export const postDepositSlip = (
  token: string,
  body: { account_id: string; slip_date: string; items: { instrument_id: string; outcome: "collected" | "unpaid" }[] },
) => apiFetch<{ id: string; number: string }>("/treasury/deposit-slips", { method: "POST", token, body });

export const markUnpaid = (token: string, id: string) =>
  apiFetch<Instrument>(`/treasury/instruments/${id}/unpaid`, { method: "POST", token });

export const listAlerts = (token: string) => apiFetch<InstrumentAlert[]>("/treasury/alerts", { token });

export const getCashJournal = (token: string, accountId: string, dateFrom?: string, dateTo?: string) => {
  const query = new URLSearchParams({ account_id: accountId });
  if (dateFrom) query.set("date_from", dateFrom);
  if (dateTo) query.set("date_to", dateTo);
  return apiFetch<CashJournal>(`/treasury/journals/cash?${query}`, { token });
};
