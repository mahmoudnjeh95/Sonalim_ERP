import { apiErrorFromResponse, apiFetch, networkError } from "../../lib/api";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface PreviewLine {
  row: number;
  line_date: string;
  label: string;
  debit: string;
  credit: string;
  balance: string | null;
}

export interface ImportResult {
  errors: { row: number; message: string; message_fr: string }[];
  warnings: { row: number; message: string; message_fr: string }[];
  new_lines: PreviewLine[];
  duplicate_lines: PreviewLine[];
  committed: boolean;
}

export interface StatementLine {
  id: string;
  line_date: string;
  label: string;
  debit: string;
  credit: string;
  balance: string | null;
  partner_id: string | null;
  matched_payment_id: string | null;
}

export interface Suggestions {
  suggestions: Record<string, string>;
  payments: { id: string; direction: "in" | "out"; amount: string; date: string; document_number: string }[];
}

export interface StatementSummary {
  account_balance: string;
  statement_balance: string | null;
  difference: string | null;
  lines: number;
  matched: number;
  unmatched: number;
}

export interface PartnerPosition {
  partner_id: string;
  currency: string;
  invoiced: string;
  paid: string;
  remaining: string;
  count: number;
  "bucket_0-30": string;
  "bucket_31-60": string;
  "bucket_61-90": string;
  "bucket_90+": string;
}

export const importStatement = (token: string, body: { account_id: string; filename: string; content_base64: string; commit: boolean }) =>
  apiFetch<ImportResult>("/treasury/statements/import", { method: "POST", token, body });
export const listStatementLines = (token: string, accountId: string) =>
  apiFetch<StatementLine[]>(`/treasury/statements/lines?account_id=${accountId}`, { token });
export const getSuggestions = (token: string, accountId: string) =>
  apiFetch<Suggestions>(`/treasury/statements/suggestions?account_id=${accountId}`, { token });
export const getStatementSummary = (token: string, accountId: string) =>
  apiFetch<StatementSummary>(`/treasury/statements/summary?account_id=${accountId}`, { token });
export const setLinePartner = (token: string, lineId: string, partnerId: string | null) =>
  apiFetch<StatementLine>(`/treasury/statements/lines/${lineId}/partner`, { method: "PATCH", token, body: { partner_id: partnerId } });
export const matchLine = (token: string, lineId: string, paymentId: string | null) =>
  apiFetch<StatementLine>(`/treasury/statements/lines/${lineId}/match`, { method: "PATCH", token, body: { payment_id: paymentId } });

export interface ReportInvoice {
  invoice_id: string;
  number: string | null;
  invoice_date: string;
  amount: string;
  paid: string;
  remaining: string;
  status: string;
}

export interface ReportPartnerGroup {
  partner_id: string;
  partner_name: string | null;
  documents: { document_id: string; number: string; net_to_pay: string; withheld: string; invoices: ReportInvoice[] }[];
  without_document: ReportInvoice[];
}

export const getInvoiceReport = (token: string, kind: "sales" | "purchase") =>
  apiFetch<{ partners: PartnerPosition[]; groups: ReportPartnerGroup[] }>(`/treasury/reports/${kind === "sales" ? "sales-invoices" : "purchase-invoices"}`, { token });

export async function downloadInvoiceReport(token: string, kind: "sales" | "purchase", format: "csv" | "xlsx", lang: string): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE_URL}/treasury/reports/${kind === "sales" ? "sales-invoices" : "purchase-invoices"}?format=${format}&lang=${lang}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
  } catch {
    throw networkError();
  }
  if (!response.ok) throw await apiErrorFromResponse(response);
  return response.blob();
}

/** The file as base64 (the upload endpoint takes JSON; the platform has no multipart support). */
export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}
