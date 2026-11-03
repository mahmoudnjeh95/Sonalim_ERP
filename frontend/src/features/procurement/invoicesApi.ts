import { apiFetch } from "../../lib/api";

export type PurchaseInvoiceStatus = "draft" | "validated" | "partially_paid" | "paid" | "cancelled";

export interface PurchaseInvoice {
  id: string;
  number: string | null;
  partner_id: string;
  supplier_invoice_number: string;
  purchase_order_id: string | null;
  invoice_date: string;
  due_date: string | null;
  currency: string;
  amount: string;
  amount_paid: string;
  remaining: string;
  status: PurchaseInvoiceStatus;
  note: string | null;
}

export interface CreatePurchaseInvoiceInput {
  partner_id: string;
  supplier_invoice_number: string;
  invoice_date: string;
  amount: number;
  currency: string;
  due_date?: string;
  purchase_order_id?: string;
  note?: string;
}

export function listPurchaseInvoices(token: string, params?: { status?: PurchaseInvoiceStatus; overdue?: boolean }) {
  const query = new URLSearchParams();
  if (params?.status) query.set("status_filter", params.status);
  if (params?.overdue) query.set("overdue", "true");
  const suffix = query.toString() ? `?${query}` : "";
  return apiFetch<PurchaseInvoice[]>(`/procurement/purchase-invoices${suffix}`, { token });
}

export function createPurchaseInvoice(token: string, input: CreatePurchaseInvoiceInput) {
  return apiFetch<PurchaseInvoice>("/procurement/purchase-invoices", { method: "POST", token, body: input });
}

export function validatePurchaseInvoice(token: string, id: string) {
  return apiFetch<PurchaseInvoice>(`/procurement/purchase-invoices/${id}/validate`, { method: "POST", token });
}

export function cancelPurchaseInvoice(token: string, id: string) {
  return apiFetch<PurchaseInvoice>(`/procurement/purchase-invoices/${id}/cancel`, { method: "POST", token });
}
