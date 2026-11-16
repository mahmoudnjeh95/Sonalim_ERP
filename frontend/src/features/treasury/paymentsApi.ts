import { apiErrorFromResponse, apiFetch } from "../../lib/api";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export type PaymentMethod = "cash" | "cheque" | "draft" | "transfer" | "mobile_money";
export type Direction = "in" | "out";

export interface PaymentInput {
  method: PaymentMethod;
  amount: number;
  account_id?: string;
  number?: string;
  bank_name?: string;
  due_date?: string;
  reference?: string;
  issue_date?: string;
  branch_name?: string;
  deposit_date?: string;
  slip_reference?: string;
  denominations?: Record<string, number>;
}

export interface DocumentInput {
  partner_id: string;
  doc_date: string;
  currency: string;
  reason: "full" | "advance";
  with_details: boolean;
  note?: string;
  withheld_amount?: number;
  payments: PaymentInput[];
  allocations: { invoice_id: string; amount: number }[];
}

export interface PaymentDocument {
  id: string;
  number: string;
  partner_id: string;
  doc_date: string;
  reason: "full" | "advance";
  currency: string;
  total: string;
  unallocated: string;
  status: "posted" | "cancelled";
  withheld_amount: string;
}

export interface PaymentDocumentDetail extends PaymentDocument {
  with_details: boolean;
  note: string | null;
  allocations: { invoice_id: string; amount: string }[];
  payments: { id: string; method: PaymentMethod; amount: string; account_id: string | null; reference: string | null; denominations: Record<string, number> | null }[];
  instruments: {
    id: string;
    method: PaymentMethod;
    number: string;
    bank_name: string;
    branch_name: string | null;
    issue_date: string | null;
    due_date: string;
    deposit_date: string | null;
    slip_reference: string | null;
    amount: string;
    status: string;
  }[];
}

export interface DocumentAttachment {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
}

export interface OpenInvoice {
  id: string;
  number?: string | null;
  supplier_invoice_number?: string;
  partner_id: string;
  amount: string;
  remaining: string;
  currency: string;
  status: string;
}

const path = (direction: Direction) => (direction === "in" ? "receipts" : "disbursements");

export const listDocuments = (token: string, direction: Direction) =>
  apiFetch<PaymentDocument[]>(`/treasury/${path(direction)}`, { token });
export const createDocument = (token: string, direction: Direction, body: DocumentInput) =>
  apiFetch<PaymentDocument>(`/treasury/${path(direction)}`, { method: "POST", token, body });
export const cancelDocument = (token: string, direction: Direction, id: string) =>
  apiFetch<PaymentDocument>(`/treasury/${path(direction)}/${id}/cancel`, { method: "POST", token });
export const getDocument = (token: string, direction: Direction, id: string) =>
  apiFetch<PaymentDocumentDetail>(`/treasury/${path(direction)}/${id}`, { token });
export const listAttachments = (token: string, direction: Direction, id: string) =>
  apiFetch<DocumentAttachment[]>(`/treasury/${path(direction)}/${id}/attachments`, { token });
export const addAttachment = (token: string, direction: Direction, id: string, body: { filename: string; content_type?: string; content_base64: string }) =>
  apiFetch<DocumentAttachment>(`/treasury/${path(direction)}/${id}/attachments`, { method: "POST", token, body });
export const deleteAttachment = (token: string, direction: Direction, id: string, attachmentId: string) =>
  apiFetch<void>(`/treasury/${path(direction)}/${id}/attachments/${attachmentId}`, { method: "DELETE", token });
export async function downloadAttachment(token: string, direction: Direction, id: string, attachmentId: string): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/treasury/${path(direction)}/${id}/attachments/${attachmentId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw await apiErrorFromResponse(response);
  return response.blob();
}
export const listOpenInvoices = (token: string, direction: Direction, partnerId: string) =>
  apiFetch<OpenInvoice[]>(`/treasury/open-invoices?direction=${direction}&partner_id=${partnerId}`, { token });
