import { apiFetch } from "../../lib/api";

export type InvoiceStatus = "draft" | "issued" | "paid";

export interface Invoice {
  id: string;
  partner_id: string;
  amount: number;
  currency: string;
  status: InvoiceStatus;
}

export interface CreateInvoiceInput {
  partner_id: string;
  amount: number;
  currency: string;
}

export interface UpdateInvoiceInput {
  partner_id?: string;
  amount?: number;
  currency?: string;
}

export function listInvoices(token: string) {
  return apiFetch<Invoice[]>("/finance/invoices", { token });
}

export function createInvoice(token: string, input: CreateInvoiceInput) {
  return apiFetch<Invoice>("/finance/invoices", { method: "POST", token, body: input });
}

export function updateInvoice(token: string, invoiceId: string, input: UpdateInvoiceInput) {
  return apiFetch<Invoice>(`/finance/invoices/${invoiceId}`, { method: "PATCH", token, body: input });
}

export function issueInvoice(token: string, invoiceId: string) {
  return apiFetch<Invoice>(`/finance/invoices/${invoiceId}/issue`, {
    method: "POST",
    token,
    body: { correlation_id: crypto.randomUUID() },
  });
}

export function payInvoice(token: string, invoiceId: string) {
  return apiFetch<Invoice>(`/finance/invoices/${invoiceId}/pay`, {
    method: "POST",
    token,
    body: { correlation_id: crypto.randomUUID() },
  });
}
