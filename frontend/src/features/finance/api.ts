import { apiFetch } from "../../lib/api";

export type InvoiceStatus = "draft" | "issued" | "partially_paid" | "paid";

export type InvoiceSource = "order" | "delivery_note" | "shipment" | null;

export interface Invoice {
  id: string;
  partner_id: string;
  /** What is due: the invoiced total less credit notes. */
  amount: number;
  currency: string;
  status: InvoiceStatus;
  amount_paid: number;
  number?: string | null;
  invoice_date?: string | null;
  total?: number;
  amount_credited?: number;
  remaining?: number;
  /** Paid above what is due once a credit note came in: owed back to the customer. */
  customer_credit?: number;
  source_type?: InvoiceSource;
  source_id?: string | null;
  source_number?: string | null;
  source_order_id?: string | null;
}

export interface BilledLine {
  product_id: string;
  quantity: number;
  unit_price: number;
  amount: number;
}

export interface CreditNote {
  id: string;
  number: string;
  invoice_id: string;
  invoice_number: string | null;
  partner_id: string;
  return_id: string;
  return_number: string | null;
  credit_date: string;
  amount: number;
  currency: string;
  lines: BilledLine[];
}

export interface InvoiceDetail extends Invoice {
  lines: BilledLine[];
  credit_notes: CreditNote[];
}

// Money comes back as JSON numbers or decimal strings depending on the route; the screens want numbers.
const MONEY_KEYS = ["amount", "amount_paid", "total", "amount_credited", "remaining", "customer_credit", "quantity", "unit_price"] as const;
function numbers<T extends object>(row: T): T {
  const copy = { ...row } as Record<string, unknown>;
  for (const key of MONEY_KEYS) if (copy[key] !== undefined && copy[key] !== null) copy[key] = Number(copy[key]);
  return copy as T;
}
function creditNoteNumbers(note: CreditNote): CreditNote {
  return { ...numbers(note), lines: note.lines.map(numbers) };
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

export async function listInvoices(token: string, params?: { orderId?: string }) {
  const suffix = params?.orderId ? `?order_id=${encodeURIComponent(params.orderId)}` : "";
  return (await apiFetch<Invoice[]>(`/finance/invoices${suffix}`, { token })).map(numbers);
}

export async function getInvoice(token: string, invoiceId: string) {
  const detail = await apiFetch<InvoiceDetail>(`/finance/invoices/${invoiceId}`, { token });
  return { ...numbers(detail), lines: detail.lines.map(numbers), credit_notes: detail.credit_notes.map(creditNoteNumbers) };
}

export async function listCreditNotes(token: string) {
  return (await apiFetch<CreditNote[]>("/finance/credit-notes", { token })).map(creditNoteNumbers);
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
