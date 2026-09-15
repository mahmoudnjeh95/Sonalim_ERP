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
  currency_code: string | null;
  notes: string | null;
  is_import: boolean;
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
  is_import?: boolean;
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
  is_import?: boolean;
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
  currency_code: string;
  lines: CreateReceiptLineInput[];
  invoice_number?: string;
  invoice_date?: string;
  origin_country?: string;
  carrier?: string;
  transport_company_name?: string;
  driver_name?: string;
  base_cost?: number;
  license_fee?: number;
  insurance_fee?: number;
  transit_fee?: number;
  transport_fee?: number;
  customs_duty?: number;
  handling_fee?: number;
}

export interface PurchaseOrderReceipt {
  id: string;
  purchase_order_id: string;
  location_id: string;
  status: "draft" | "confirmed";
  currency_code: string;
  invoice_number: string | null;
  invoice_date: string | null;
  origin_country: string | null;
  carrier: string | null;
  transport_company_name: string | null;
  driver_name: string | null;
  base_cost: number;
  license_fee: number;
  insurance_fee: number;
  transit_fee: number;
  transport_fee: number;
  customs_duty: number;
  handling_fee: number;
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

/** Resolves a stock move's `purchase_order_receipt:{id}` reference back to its order. */
export function getPurchaseOrderReceipt(token: string, receiptId: string) {
  return apiFetch<PurchaseOrderReceipt>(`/procurement/receipts/${receiptId}`, { token });
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

export interface LastPrice {
  product_id: string;
  unit_price: number;
  unit_price_currency: string;
  order_date: string | null;
}

export function listLastPrices(token: string, supplierId: string, productIds: string[]) {
  if (productIds.length === 0) return Promise.resolve<LastPrice[]>([]);
  const params = new URLSearchParams({ supplier_id: supplierId });
  productIds.forEach((productId) => params.append("product_ids", productId));
  return apiFetch<LastPrice[]>(`/procurement/last-prices?${params.toString()}`, { token });
}

/** Every recorded order price for one product, oldest to newest, converted to
 * CFA at the rate in effect on each order's own date -- the trend behind the
 * single latest figure listLastPrices returns. */
export interface PriceHistoryPoint {
  order_id: string;
  supplier_id: string | null;
  order_date: string | null;
  quantity_ordered: number;
  unit_price: number;
  unit_price_currency: string;
  /** Null only when no exchange rate exists to convert unit_price_currency as of order_date. */
  unit_price_cfa: number | null;
}

export function listPriceHistory(token: string, productId: string, supplierId?: string) {
  const params = new URLSearchParams({ product_id: productId });
  if (supplierId) params.set("supplier_id", supplierId);
  return apiFetch<PriceHistoryPoint[]>(`/procurement/price-history?${params.toString()}`, { token });
}

/** Ranks every supplier ever ordered from by how often they held the lowest
 * recorded price across products -- the aggregate view behind price
 * history's per-product best-supplier highlight. */
export interface SupplierLeaderboardEntry {
  supplier_id: string;
  products_supplied: number;
  total_orders: number;
  best_price_count: number;
}

export function listSupplierLeaderboard(token: string) {
  return apiFetch<SupplierLeaderboardEntry[]>("/procurement/supplier-leaderboard", { token });
}
