import { apiFetch } from "../../lib/api";

export type SalesOrderStatus = "draft" | "confirmed" | "shipped";

export interface OrderLine {
  product_id: string;
  quantity: number;
  unit_price: number;
  /** % off this line; 0 on orders from before discounts existed */
  discount_rate?: number;
  /** left out on a new line: the tenant's default rate (sales settings) */
  vat_rate?: number | null;
  price_list_id?: string | null;
}

export interface OrderTotals {
  gross: number;
  discount: number;
  excl_tax: number;
  vat: number;
  incl_tax: number;
}

export interface SalesOrder {
  id: string;
  partner_id: string;
  location_id: string;
  status: SalesOrderStatus;
  /** VAT included, whole francs */
  total_amount: number;
  totals: OrderTotals;
  discount_rate: number;
  quote_id: string | null;
  requested_ship_date: string | null;
  opportunity_id: string | null;
  lines: OrderLine[];
}

export interface CreateOrderInput {
  partner_id: string;
  location_id: string;
  lines: OrderLine[];
  requested_ship_date?: string;
  discount_rate?: number;
}

export interface UpdateOrderInput {
  partner_id?: string;
  location_id?: string;
  lines?: OrderLine[];
  requested_ship_date?: string;
  discount_rate?: number;
}

export function listOrders(token: string) {
  return apiFetch<SalesOrder[]>("/sales/orders", { token });
}

export function createOrder(token: string, input: CreateOrderInput) {
  return apiFetch<SalesOrder>("/sales/orders", { method: "POST", token, body: input });
}

export function updateOrder(token: string, orderId: string, input: UpdateOrderInput) {
  return apiFetch<SalesOrder>(`/sales/orders/${orderId}`, { method: "PATCH", token, body: input });
}

export function confirmOrder(token: string, orderId: string, overrideCredit = false) {
  return apiFetch<SalesOrder>(`/sales/orders/${orderId}/confirm`, {
    method: "POST",
    token,
    body: { correlation_id: crypto.randomUUID(), override_credit: overrideCredit },
  });
}

/** Drafts a warehouse issue voucher from this order (customer and lines prefilled). */
export function createIssueVoucherFromOrder(token: string, orderId: string, sourceLocationId: string) {
  return apiFetch<{ id: string }>(`/warehouse/vouchers/from-order/${orderId}`, {
    method: "POST",
    token,
    body: { source_location_id: sourceLocationId },
  });
}
