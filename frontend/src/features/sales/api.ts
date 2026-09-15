import { apiFetch } from "../../lib/api";

export type SalesOrderStatus = "draft" | "confirmed";

export interface OrderLine {
  product_id: string;
  quantity: number;
  unit_price: number;
}

export interface SalesOrder {
  id: string;
  partner_id: string;
  location_id: string;
  status: SalesOrderStatus;
  total_amount: number;
  requested_ship_date: string | null;
  opportunity_id: string | null;
  lines: OrderLine[];
}

export interface CreateOrderInput {
  partner_id: string;
  location_id: string;
  lines: OrderLine[];
  requested_ship_date?: string;
}

export interface UpdateOrderInput {
  partner_id?: string;
  location_id?: string;
  lines?: OrderLine[];
  requested_ship_date?: string;
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

export function confirmOrder(token: string, orderId: string) {
  return apiFetch<SalesOrder>(`/sales/orders/${orderId}/confirm`, {
    method: "POST",
    token,
    body: { correlation_id: crypto.randomUUID() },
  });
}
