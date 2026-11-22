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
  /** null on a free line (a service, a fee, a lump sum) */
  product_id: string | null;
  description?: string | null;
  quantity: number;
  /** excluding tax, after the order's discounts */
  unit_price: number;
  /** excluding tax */
  amount: number;
  vat_rate?: number;
  /** the order's price before discounts, and the combined discount, when the line came from an order */
  list_price?: number | null;
  discount_rate?: number;
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
  amount_excl_tax?: number;
  vat_amount?: number;
  lines: BilledLine[];
}

export interface InvoiceDetail extends Invoice {
  amount_excl_tax?: number;
  vat_amount?: number;
  lines: BilledLine[];
  credit_notes: CreditNote[];
}

// Money comes back as JSON numbers or decimal strings depending on the route; the screens want numbers.
const MONEY_KEYS = [
  "amount", "amount_paid", "total", "amount_credited", "remaining", "customer_credit", "quantity", "unit_price",
  "amount_excl_tax", "vat_amount", "vat_rate", "list_price", "discount_rate",
] as const;
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

/** A line as typed on an invoice: a product or a description, a list price, a discount and a tax code. */
export interface InvoiceLineInput {
  product_id?: string | null;
  description?: string | null;
  quantity: number;
  unit_price: number;
  discount_rate: number;
  tax_code: string;
}

export interface InvoiceWithLinesInput {
  partner_id: string;
  invoice_date?: string | null;
  lines: InvoiceLineInput[];
}

export async function createInvoiceWithLines(token: string, input: InvoiceWithLinesInput) {
  const detail = await apiFetch<InvoiceDetail>("/finance/invoices", { method: "POST", token, body: input });
  return { ...numbers(detail), lines: detail.lines.map(numbers), credit_notes: [] };
}

export async function replaceInvoiceLines(token: string, invoiceId: string, input: Omit<InvoiceWithLinesInput, "partner_id">) {
  const detail = await apiFetch<InvoiceDetail>(`/finance/invoices/${invoiceId}/lines`, { method: "PUT", token, body: input });
  return { ...numbers(detail), lines: detail.lines.map(numbers), credit_notes: [] };
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
