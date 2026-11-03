import { apiFetch } from "../../lib/api";

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
}

export interface DocumentInput {
  partner_id: string;
  doc_date: string;
  currency: string;
  reason: "full" | "advance";
  with_details: boolean;
  note?: string;
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
export const listOpenInvoices = (token: string, direction: Direction, partnerId: string) =>
  apiFetch<OpenInvoice[]>(`/treasury/open-invoices?direction=${direction}&partner_id=${partnerId}`, { token });
