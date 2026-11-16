import { apiFetch } from "../../lib/api";

export type QuoteStatus = "draft" | "sent" | "accepted" | "refused" | "expired" | "superseded";

export interface QuoteLine {
  id: string;
  line_no: number;
  product_id: string;
  sku: string;
  product_name: string;
  quantity: string;
  unit_price: string;
  discount_rate: string;
  vat_rate: string;
  price_list_id: string | null;
  net_amount: string;
}

export interface QuoteTotals {
  gross: string;
  discount: string;
  excl_tax: string;
  vat: string;
  incl_tax: string;
}

export interface Quote {
  id: string;
  number: string;
  revision: number;
  display_number: string;
  previous_id: string | null;
  partner_id: string;
  partner_name: string | null;
  opportunity_id: string | null;
  location_id: string | null;
  quote_date: string;
  valid_until: string;
  status: QuoteStatus;
  discount_rate: string;
  note: string | null;
  refusal_reason: string | null;
  order_id: string | null;
  created_at: string;
  lines: QuoteLine[];
  totals: QuoteTotals;
}

export interface QuoteLineInput {
  product_id: string;
  quantity: number;
  unit_price?: number | null;
  discount_rate?: number | null;
  vat_rate?: number | null;
  price_list_id?: string | null;
}

export interface QuoteInput {
  partner_id: string;
  lines: QuoteLineInput[];
  quote_date?: string | null;
  valid_until?: string | null;
  discount_rate?: number | null;
  opportunity_id?: string | null;
  location_id?: string | null;
  note?: string | null;
}

export interface QuoteStats {
  counts: Partial<Record<QuoteStatus, number>>;
  conversion_rate: string | null;
  accepted_value: string;
  open_value: string;
}

export const QUOTES_QUERY_KEY = ["sales", "quotes"] as const;

export const listQuotes = (token: string) => apiFetch<Quote[]>("/sales/quotes", { token });
export const getQuoteStats = (token: string) => apiFetch<QuoteStats>("/sales/quotes/stats", { token });
export const getQuote = (token: string, id: string) => apiFetch<Quote>(`/sales/quotes/${id}`, { token });
export const createQuote = (token: string, body: QuoteInput) => apiFetch<Quote>("/sales/quotes", { method: "POST", token, body });
export const updateQuote = (token: string, id: string, body: Partial<QuoteInput>) =>
  apiFetch<Quote>(`/sales/quotes/${id}`, { method: "PATCH", token, body });
export const sendQuote = (token: string, id: string) => apiFetch<Quote>(`/sales/quotes/${id}/send`, { method: "POST", token });
export const acceptQuote = (token: string, id: string) => apiFetch<Quote>(`/sales/quotes/${id}/accept`, { method: "POST", token });
export const refuseQuote = (token: string, id: string, reason: string | null) =>
  apiFetch<Quote>(`/sales/quotes/${id}/refuse`, { method: "POST", token, body: { reason } });
export const reviseQuote = (token: string, id: string) => apiFetch<Quote>(`/sales/quotes/${id}/revise`, { method: "POST", token });
export const convertQuote = (token: string, id: string, body: { location_id?: string | null; requested_ship_date?: string | null }) =>
  apiFetch<{ quote: Quote; order_id: string }>(`/sales/quotes/${id}/convert`, { method: "POST", token, body });
