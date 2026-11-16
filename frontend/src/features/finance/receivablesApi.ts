import { apiErrorFromResponse, apiFetch, networkError } from "../../lib/api";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface Installment {
  percent: string | number;
  days: number;
  end_of_month: boolean;
  day_of_month: number | null;
}

export interface PaymentTerm {
  id: string;
  code: string;
  name_fr: string;
  name_en: string;
  installments: Installment[];
  active: boolean;
}

export interface PartnerTerms {
  customer: PaymentTerm | null;
  supplier: PaymentTerm | null;
}

export interface DunningLevel {
  level: number;
  days_after_due: number;
  name_fr: string;
  name_en: string;
  letter_fr: string;
  letter_en: string;
  blocks_orders: boolean;
}

export interface OpenInvoice {
  id: string;
  partner_id: string;
  number: string | null;
  invoice_date: string;
  due_date: string | null;
  total: string;
  paid: string;
  remaining: string;
  overdue: string;
  oldest_due: string | null;
  days_overdue: number;
  next_due: string | null;
  bucket: BucketKey;
  status: string;
}

export const BUCKETS = ["not_due", "1_30", "31_60", "61_90", "over_90"] as const;
export type BucketKey = (typeof BUCKETS)[number];

export interface Position {
  partner_id: string;
  credit_limit: string | null;
  open_invoices: string;
  uninvoiced_deliveries: string;
  undelivered_orders: string;
  exposure: string;
  available: string | null;
  overdue: string;
  max_days_overdue: number;
  buckets: Record<BucketKey, string>;
  dunning_level: DunningLevel | null;
  blocked: boolean;
  customer_term: PaymentTerm | null;
  supplier_term: PaymentTerm | null;
}

export interface CreditReason {
  code: string;
  message: string;
  message_fr: string;
}

export interface CreditPreview {
  exposure: string;
  credit_limit: string | null;
  available: string | null;
  overdue: string;
  max_days_overdue: number;
  dunning_level: DunningLevel | null;
  order_amount: string;
  warnings: CreditReason[];
  blocking: CreditReason[];
  can_override: boolean;
}

export type ActionKind = "letter" | "call" | "email" | "promise" | "note";

export interface DunningAction {
  id: string;
  partner_id: string;
  kind: ActionKind;
  level: number | null;
  note: string | null;
  invoice_ids: string[];
  amount_due: string | null;
  promise_date: string | null;
  promise_amount: string | null;
  promise_status: "open" | "kept" | "broken" | null;
  created_by: string;
  created_at: string;
}

export interface WorklistRow {
  partner_id: string;
  partner_name: string | null;
  overdue: string;
  remaining: string;
  days_overdue: number;
  since: string;
  invoices: OpenInvoice[];
  level_reached: DunningLevel | null;
  level_sent: number | null;
  next_level: DunningLevel | null;
  open_promise: DunningAction | null;
  broken_promise: DunningAction | null;
  last_action: DunningAction | null;
  to_chase: boolean;
  blocked: boolean;
}

export type AgingRow = {
  partner_id: string;
  partner_name: string | null;
  credit_limit: string | null;
  remaining: string;
  overdue: string;
  max_days_overdue: number;
  invoices: number;
} & Record<`bucket_${BucketKey}`, string>;

export interface StatementLine {
  date: string;
  kind: "invoice" | "credit_note" | "payment" | "payment_reversed";
  reference: string;
  due_date: string | null;
  against?: string | null;
  debit: string;
  credit: string;
  balance: string;
}

export interface Statement {
  partner_id: string;
  partner_name: string | null;
  opening_balance: string;
  closing_balance: string;
  lines: StatementLine[];
  position: Position;
  open_invoices: OpenInvoice[];
  dunning_history: DunningAction[];
}

export interface ReceivablesSettings {
  block_overdue_days: number | null;
  warn_ratio: string;
  company_name: string | null;
  company_address: string | null;
  company_phone: string | null;
  signatory: string | null;
  signatory_title: string | null;
  company_email: string | null;
  company_tax_id: string | null;
  company_rccm: string | null;
  chase_from: string | null;
}

export interface Letter {
  date: string;
  company: ReceivablesSettings;
  partner: { id: string; name: string; email: string | null; phone: string | null };
  level: DunningLevel;
  invoices: OpenInvoice[];
  overdue: string;
  remaining: string;
}

export const listPaymentTerms = (token: string, includeInactive = false) =>
  apiFetch<PaymentTerm[]>(`/finance/payment-terms${includeInactive ? "?include_inactive=true" : ""}`, { token });
export const createPaymentTerm = (token: string, body: { code: string; name_fr: string; name_en: string; installments: Installment[] }) =>
  apiFetch<PaymentTerm>("/finance/payment-terms", { method: "POST", token, body });
export const updatePaymentTerm = (token: string, id: string, body: Partial<Pick<PaymentTerm, "name_fr" | "name_en" | "installments" | "active">>) =>
  apiFetch<PaymentTerm>(`/finance/payment-terms/${id}`, { method: "PATCH", token, body });
export const getPartnerTerms = (token: string, partnerId: string) =>
  apiFetch<PartnerTerms>(`/finance/partners/${partnerId}/payment-terms`, { token });
export const setPartnerTerm = (token: string, partnerId: string, side: "customer" | "supplier", termId: string | null) =>
  apiFetch<PartnerTerms>(`/finance/partners/${partnerId}/payment-terms`, { method: "PUT", token, body: { side, term_id: termId } });

export const getCreditPreview = (token: string, partnerId: string, orderAmount: number) =>
  apiFetch<CreditPreview>(`/finance/customers/${partnerId}/credit-check?order_amount=${orderAmount}`, { token });
export const setCreditLimit = (token: string, partnerId: string, creditLimit: number | null, note?: string) =>
  apiFetch<Position>(`/finance/customers/${partnerId}/credit-limit`, { method: "PUT", token, body: { credit_limit: creditLimit, note } });
export const getStatement = (token: string, partnerId: string, dateFrom?: string, dateTo?: string) => {
  const query = new URLSearchParams();
  if (dateFrom) query.set("date_from", dateFrom);
  if (dateTo) query.set("date_to", dateTo);
  return apiFetch<Statement>(`/finance/customers/${partnerId}/statement${query.toString() ? `?${query}` : ""}`, { token });
};
export const getAging = (token: string) => apiFetch<AgingRow[]>("/finance/receivables/aging", { token });
export const getReceivablesSettings = (token: string) => apiFetch<ReceivablesSettings>("/finance/receivables/settings", { token });
export const saveReceivablesSettings = (token: string, body: Partial<ReceivablesSettings>) =>
  apiFetch<ReceivablesSettings>("/finance/receivables/settings", { method: "PUT", token, body });

export const getWorklist = (token: string) => apiFetch<WorklistRow[]>("/finance/dunning", { token });
export const getDunningLevels = (token: string) => apiFetch<DunningLevel[]>("/finance/dunning/levels", { token });
export const saveDunningLevels = (token: string, levels: Omit<DunningLevel, "level">[]) =>
  apiFetch<DunningLevel[]>("/finance/dunning/levels", { method: "PUT", token, body: { levels } });
export const recordDunningAction = (
  token: string,
  body: { partner_id: string; kind: ActionKind; level?: number | null; note?: string; promise_date?: string; promise_amount?: number },
) => apiFetch<DunningAction>("/finance/dunning/actions", { method: "POST", token, body });
export const setPromiseStatus = (token: string, actionId: string, status: "kept" | "broken") =>
  apiFetch<DunningAction>(`/finance/dunning/actions/${actionId}/promise`, { method: "PATCH", token, body: { status } });
export const runDunning = (token: string) =>
  apiFetch<{ promises_kept: number; promises_broken: number; levels_announced: number }>("/finance/dunning/run", { method: "POST", token });
export const getLetter = (token: string, partnerId: string, level?: number) =>
  apiFetch<Letter>(`/finance/dunning/letter/${partnerId}${level ? `?level=${level}` : ""}`, { token });

export async function downloadReceivables(
  token: string,
  path: "aging" | { statement: string },
  format: "csv" | "xlsx",
  lang: string,
): Promise<Blob> {
  const url = path === "aging" ? "/finance/receivables/aging" : `/finance/customers/${path.statement}/statement`;
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${url}?format=${format}&lang=${lang}`, { headers: { Authorization: `Bearer ${token}` } });
  } catch {
    throw networkError();
  }
  if (!response.ok) throw await apiErrorFromResponse(response);
  return response.blob();
}

export const RECEIVABLES_QUERY_KEY = ["finance", "receivables"] as const;
