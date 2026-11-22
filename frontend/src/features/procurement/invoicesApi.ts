import { BASE_URL, apiErrorFromResponse, apiFetch, networkError } from "../../lib/api";

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
  /** What is due: the total including tax less validated credit notes. */
  amount: string;
  amount_paid: string;
  remaining: string;
  /** What the supplier owes back when a credit note brought the amount due below what was paid. */
  supplier_credit: string;
  status: PurchaseInvoiceStatus;
  note: string | null;
  total_gross: string;
  total_discount: string;
  total_excl_tax: string;
  total_vat: string;
  total_incl_tax: string;
  credited_amount: string;
}

export interface PurchaseInvoiceLine {
  id: string;
  line_no: number;
  product_id: string | null;
  description: string;
  quantity: string;
  uom_id: string | null;
  unit_price: string;
  discount_rate: string;
  vat_rate: string;
  purchase_order_line_id: string | null;
  receipt_id: string | null;
  total_excl_tax: string;
  total_vat: string;
  total_incl_tax: string;
}

export interface MatchWarning {
  code: "QUANTITY_OVER_RECEIVED" | "PRICE_DIFFERS_FROM_ORDER";
  line: string;
  purchase_order_line_id: string;
  invoiced?: string;
  receivable?: string;
  unit_price?: string;
  order_unit_price?: string;
}

export interface CreditNoteLine {
  id: string;
  line_no: number;
  invoice_line_id: string;
  description: string;
  quantity: string;
  unit_price: string;
  discount_rate: string;
  vat_rate: string;
  total_excl_tax: string;
  total_vat: string;
  total_incl_tax: string;
}

export interface CreditNote {
  id: string;
  number: string | null;
  invoice_id: string;
  partner_id: string;
  note_date: string;
  reason: string;
  status: "draft" | "validated" | "cancelled";
  total_excl_tax: string;
  total_vat: string;
  total_incl_tax: string;
  lines: CreditNoteLine[];
}

export interface PurchaseInvoiceDetail extends PurchaseInvoice {
  lines: PurchaseInvoiceLine[];
  receipt_ids: string[];
  warnings: MatchWarning[];
  credit_notes: CreditNote[];
}

export interface InvoiceLineInput {
  product_id?: string | null;
  description?: string;
  quantity: number;
  unit_price: number;
  discount_rate?: number;
  vat_rate?: number | null;
  uom_id?: string | null;
  purchase_order_line_id?: string | null;
  receipt_id?: string | null;
}

export interface PurchaseInvoiceInput {
  partner_id: string;
  supplier_invoice_number: string;
  invoice_date: string;
  due_date?: string | null;
  note?: string | null;
  lines: InvoiceLineInput[];
}

export interface InvoiceableReceipt {
  receipt_id: string;
  purchase_order_id: string;
  supplier_id: string;
  confirmed_at: string | null;
  supplier_document: string | null;
  lines: {
    receipt_line_id: string;
    purchase_order_line_id: string;
    product_id: string;
    product_name: string;
    received: string;
    to_invoice: string;
    order_unit_price: string | null;
  }[];
}

export interface Attachment {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at?: string;
}

export interface InvoiceActivity {
  documents: { document_id: string; number: string; doc_date: string; status: string; amount: string; reversed: string; methods: string[] }[];
  payment_orders: { id: string; number: string; order_date: string; due_date: string; method: string; employee_email: string }[];
}

export interface InvoiceFilters {
  status?: PurchaseInvoiceStatus;
  overdue?: boolean;
  partner_id?: string;
  date_from?: string;
  date_to?: string;
}

function filterQuery(filters: InvoiceFilters) {
  const query = new URLSearchParams();
  if (filters.status) query.set("status_filter", filters.status);
  if (filters.overdue) query.set("overdue", "true");
  if (filters.partner_id) query.set("partner_id", filters.partner_id);
  if (filters.date_from) query.set("date_from", filters.date_from);
  if (filters.date_to) query.set("date_to", filters.date_to);
  return query;
}

const BASE = "/procurement/purchase-invoices";

export function listPurchaseInvoices(token: string, filters: InvoiceFilters = {}) {
  const query = filterQuery(filters).toString();
  return apiFetch<PurchaseInvoice[]>(`${BASE}${query ? `?${query}` : ""}`, { token });
}

export const getPurchaseInvoice = (token: string, id: string) => apiFetch<PurchaseInvoiceDetail>(`${BASE}/${id}`, { token });

export const createPurchaseInvoice = (token: string, input: PurchaseInvoiceInput) =>
  apiFetch<PurchaseInvoiceDetail>(BASE, { method: "POST", token, body: input });

export const updatePurchaseInvoice = (token: string, id: string, input: Partial<PurchaseInvoiceInput>) =>
  apiFetch<PurchaseInvoiceDetail>(`${BASE}/${id}`, { method: "PATCH", token, body: input });

export const validatePurchaseInvoice = (token: string, id: string) =>
  apiFetch<PurchaseInvoiceDetail>(`${BASE}/${id}/validate`, { method: "POST", token });

export const cancelPurchaseInvoice = (token: string, id: string) =>
  apiFetch<PurchaseInvoiceDetail>(`${BASE}/${id}/cancel`, { method: "POST", token });

export const listInvoiceableReceipts = (token: string, partnerId?: string) =>
  apiFetch<InvoiceableReceipt[]>(`${BASE}/invoiceable-receipts${partnerId ? `?partner_id=${partnerId}` : ""}`, { token });

export const createFromReceipts = (
  token: string,
  input: { receipt_ids: string[]; supplier_invoice_number: string; invoice_date: string; due_date?: string | null },
) => apiFetch<PurchaseInvoiceDetail>(`${BASE}/from-receipts`, { method: "POST", token, body: input });

export const getInvoiceSettings = (token: string) => apiFetch<{ default_vat_rate: string }>(`${BASE}/settings`, { token });

export const setDefaultVatRate = (token: string, rate: number) =>
  apiFetch<{ default_vat_rate: string }>(`${BASE}/settings`, { method: "PUT", token, body: { default_vat_rate: rate } });

export const listInvoiceAttachments = (token: string, id: string) => apiFetch<Attachment[]>(`${BASE}/${id}/attachments`, { token });

export const addInvoiceAttachment = (token: string, id: string, body: { filename: string; content_type?: string; content_base64: string }) =>
  apiFetch<Attachment>(`${BASE}/${id}/attachments`, { method: "POST", token, body });

export const deleteInvoiceAttachment = (token: string, id: string, attachmentId: string) =>
  apiFetch<void>(`${BASE}/${id}/attachments/${attachmentId}`, { method: "DELETE", token });

async function download(token: string, path: string): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  } catch {
    throw networkError();
  }
  if (!response.ok) throw await apiErrorFromResponse(response);
  return response.blob();
}

export const downloadInvoiceAttachment = (token: string, id: string, attachmentId: string) =>
  download(token, `${BASE}/${id}/attachments/${attachmentId}`);

export function exportPurchaseInvoices(token: string, format: "csv" | "xlsx", lang: string, filters: InvoiceFilters) {
  const query = filterQuery(filters);
  query.set("fmt", format);
  query.set("lang", lang);
  return download(token, `${BASE}/export?${query}`);
}

export const getInvoiceActivity = (token: string, invoiceId: string) =>
  apiFetch<InvoiceActivity>(`/treasury/invoice-activity?direction=out&invoice_id=${invoiceId}`, { token });

export interface CreditNoteInput {
  invoice_id: string;
  note_date: string;
  reason: string;
  lines: { invoice_line_id: string; quantity: number; unit_price?: number | null }[];
}

export const createCreditNote = (token: string, input: CreditNoteInput) =>
  apiFetch<CreditNote>("/procurement/purchase-credit-notes", { method: "POST", token, body: input });

export const validateCreditNote = (token: string, id: string) =>
  apiFetch<CreditNote>(`/procurement/purchase-credit-notes/${id}/validate`, { method: "POST", token });

export const cancelCreditNote = (token: string, id: string) =>
  apiFetch<CreditNote>(`/procurement/purchase-credit-notes/${id}/cancel`, { method: "POST", token });

// ---- payables: what we owe suppliers ------------------------------------------------------------------

export interface PayablesAgingRow {
  partner_id: string;
  partner_name: string | null;
  remaining: string;
  overdue: string;
  invoices: number;
  max_days_overdue: number;
  bucket_not_due: string;
  bucket_1_30: string;
  bucket_31_60: string;
  bucket_61_90: string;
  bucket_over_90: string;
}

export interface SupplierStatementLine {
  date: string;
  kind: "invoice" | "credit_note" | "payment" | "payment_reversed";
  reference: string;
  due_date: string | null;
  against?: string;
  debit: string;
  credit: string;
  balance: string;
}

export interface SupplierStatement {
  partner_id: string;
  partner_name: string | null;
  opening_balance: string;
  closing_balance: string;
  remaining: string;
  overdue: string;
  lines: SupplierStatementLine[];
}

export const PAYABLES_KEY = ["procurement", "payables"] as const;
export const getPayablesAging = (token: string) => apiFetch<PayablesAgingRow[]>(`${BASE}/payables/aging`, { token });
export const getSupplierStatement = (token: string, partnerId: string) =>
  apiFetch<SupplierStatement>(`${BASE}/payables/statement/${partnerId}`, { token });
export const exportPayablesAging = (token: string, format: "csv" | "xlsx", lang: string) =>
  download(token, `${BASE}/payables/aging?format=${format}&lang=${lang}`);
