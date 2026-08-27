import { apiFetch } from "../../lib/api";

export type PurchaseOrderStatus =
  | "draft"
  | "validated"
  | "approved"
  | "ordered"
  | "partially_received"
  | "fully_received"
  | "canceled"
  | "refused";

export interface PurchaseOrder {
  id: string;
  supplier_id: string | null;
  status: PurchaseOrderStatus;
  order_date: string | null;
  expected_date: string | null;
  currency_code: string;
  notes: string | null;
}

export interface PurchaseOrderLine {
  id: string;
  purchase_order_id: string;
  product_id: string;
  uom_id: string;
  quantity_ordered: number;
  quantity_received: number;
  status: "pending" | "partially_received" | "fully_received";
  unit_price: number;
  unit_price_currency: string;
}

export interface PurchaseOrderLineInput {
  product_id: string;
  uom_id: string;
  quantity_ordered: number;
  unit_price?: number;
  unit_price_currency?: string;
}

export interface CreatePurchaseOrderInput {
  lines: PurchaseOrderLineInput[];
  supplier_id?: string;
  currency_code?: string;
  order_date?: string;
  expected_date?: string;
  notes?: string;
}

export function listPurchaseOrders(token: string, status?: PurchaseOrderStatus) {
  const query = status ? `?status_filter=${status}` : "";
  return apiFetch<PurchaseOrder[]>(`/procurement/purchase-orders${query}`, { token });
}

export function createPurchaseOrder(token: string, input: CreatePurchaseOrderInput) {
  return apiFetch<PurchaseOrder>("/procurement/purchase-orders", { method: "POST", token, body: input });
}

export function listPurchaseOrderLines(token: string, orderId: string) {
  return apiFetch<PurchaseOrderLine[]>(`/procurement/purchase-orders/${orderId}/lines`, { token });
}

export interface UpdatePurchaseOrderInput {
  supplier_id?: string;
  order_date?: string;
  expected_date?: string;
  currency_code?: string;
  notes?: string;
}

// Gated by procurement.admin_purchase_orders — a distinct, elevated permission from the
// manage_purchase_orders used for create/transition actions above.
export function updatePurchaseOrder(token: string, orderId: string, input: UpdatePurchaseOrderInput) {
  return apiFetch<PurchaseOrder>(`/procurement/purchase-orders/${orderId}`, { method: "PATCH", token, body: input });
}

function transition(token: string, orderId: string, action: string) {
  return apiFetch<PurchaseOrder>(`/procurement/purchase-orders/${orderId}/${action}`, { method: "POST", token });
}

export const validatePurchaseOrder = (token: string, orderId: string) => transition(token, orderId, "validate");
export const approvePurchaseOrder = (token: string, orderId: string) => transition(token, orderId, "approve");
export const placePurchaseOrder = (token: string, orderId: string) => transition(token, orderId, "place-order");
export const refusePurchaseOrder = (token: string, orderId: string) => transition(token, orderId, "refuse");
export const cancelPurchaseOrder = (token: string, orderId: string) => transition(token, orderId, "cancel");

export interface CreateReceiptLineInput {
  purchase_order_line_id: string;
  quantity: number;
  lot_number?: string;
}

export interface CreateReceiptInput {
  location_id: string;
  lines: CreateReceiptLineInput[];
  invoice_number?: string;
  invoice_date?: string;
  origin_country?: string;
  carrier?: string;
  base_cost?: number;
  license_fee?: number;
  insurance_fee?: number;
  transit_fee?: number;
  transport_fee?: number;
  customs_duty?: number;
}

export interface PurchaseOrderReceipt {
  id: string;
  purchase_order_id: string;
  location_id: string;
  status: "draft" | "confirmed";
  invoice_number: string | null;
  invoice_date: string | null;
  origin_country: string | null;
  carrier: string | null;
  base_cost: number;
  license_fee: number;
  insurance_fee: number;
  transit_fee: number;
  transport_fee: number;
  customs_duty: number;
  total_cost: number;
  confirmed_at: string | null;
}

export function createPurchaseOrderReceipt(token: string, orderId: string, input: CreateReceiptInput) {
  return apiFetch<PurchaseOrderReceipt>(`/procurement/purchase-orders/${orderId}/receipts`, {
    method: "POST",
    token,
    body: input,
  });
}

export function confirmPurchaseOrderReceipt(token: string, receiptId: string) {
  return apiFetch<PurchaseOrder>(`/procurement/receipts/${receiptId}/confirm`, {
    method: "POST",
    token,
    body: { correlation_id: crypto.randomUUID() },
  });
}

export async function receiveAndConfirm(token: string, orderId: string, input: CreateReceiptInput) {
  const receipt = await createPurchaseOrderReceipt(token, orderId, input);
  return confirmPurchaseOrderReceipt(token, receipt.id);
}

export function listPurchaseOrderReceipts(token: string, orderId: string) {
  return apiFetch<PurchaseOrderReceipt[]>(`/procurement/purchase-orders/${orderId}/receipts`, { token });
}

export interface PurchaseOrderReceiptLine {
  id: string;
  purchase_order_receipt_id: string;
  purchase_order_line_id: string;
  quantity: number;
  lot_number: string | null;
  cost_per_unit: number;
}

export function listPurchaseOrderReceiptLines(token: string, receiptId: string) {
  return apiFetch<PurchaseOrderReceiptLine[]>(`/procurement/receipts/${receiptId}/lines`, { token });
}
