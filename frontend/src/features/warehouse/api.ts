import { apiFetch } from "../../lib/api";

export interface Location {
  id: string;
  code: string;
  name: string;
  // Stock in a blocked location exists and stays on the books, but is excluded
  // from available quantity so no module can promise it. Quarantine is the case
  // this was built for.
  is_blocked: boolean;
  blocked_reason: string | null;
}

export interface CreateLocationInput {
  code: string;
  name: string;
  is_blocked?: boolean;
  blocked_reason?: string;
}

export interface UpdateLocationInput {
  code?: string;
  name?: string;
}

export function listLocations(token: string) {
  return apiFetch<Location[]>("/warehouse/locations", { token });
}

export function createLocation(token: string, input: CreateLocationInput) {
  return apiFetch<Location>("/warehouse/locations", { method: "POST", token, body: input });
}

export function updateLocation(token: string, locationId: string, input: UpdateLocationInput) {
  return apiFetch<Location>(`/warehouse/locations/${locationId}`, { method: "PATCH", token, body: input });
}

export interface StockItem {
  location_id: string;
  product_id: string;
  quantity_on_hand: number;
  quantity_reserved: number;
  quantity_in_production: number;
  quantity_available: number;
}

export interface ReserveStockInput {
  product_id: string;
  location_id: string;
  quantity: number;
  reference: string;
}

export function listStock(token: string) {
  return apiFetch<StockItem[]>("/warehouse/stock", { token });
}

export function reserveStock(token: string, input: ReserveStockInput) {
  return apiFetch<{ location_id: string; product_id: string; quantity_on_hand: number; quantity_reserved: number }>(
    "/warehouse/stock/reserve",
    { method: "POST", token, body: { ...input, correlation_id: crypto.randomUUID() } },
  );
}

export interface IssueStockInput {
  product_id: string;
  location_id: string;
  quantity: number;
  reference: string;
}

export function issueStock(token: string, input: IssueStockInput) {
  return apiFetch<{ location_id: string; product_id: string; quantity_on_hand: number; quantity_reserved: number }>(
    "/warehouse/stock/issue",
    { method: "POST", token, body: input },
  );
}

export interface AdjustStockInput {
  product_id: string;
  location_id: string;
  delta: number;
  reason: string;
}

export function adjustStock(token: string, input: AdjustStockInput) {
  return apiFetch<{ location_id: string; product_id: string; quantity_on_hand: number; quantity_reserved: number }>(
    "/warehouse/stock/adjust",
    { method: "POST", token, body: input },
  );
}

export interface TransferStockInput {
  product_id: string;
  from_location_id: string;
  to_location_id: string;
  quantity: number;
  reference: string;
}

export function transferStock(token: string, input: TransferStockInput) {
  return apiFetch<{
    from: { location_id: string; quantity_on_hand: number };
    to: { location_id: string; quantity_on_hand: number };
    product_id: string;
    quantity: number;
  }>("/warehouse/stock/transfer", { method: "POST", token, body: { ...input, correlation_id: crypto.randomUUID() } });
}

export interface AdminSetStockInput {
  quantity_on_hand: number;
  quantity_reserved: number;
  quantity_in_production: number;
}

export function adminSetStock(token: string, locationId: string, productId: string, input: AdminSetStockInput) {
  return apiFetch<StockItem>(`/warehouse/stock-items/${locationId}/${productId}`, {
    method: "PUT",
    token,
    body: input,
  });
}

export function deleteStockItem(token: string, locationId: string, productId: string) {
  return apiFetch<void>(`/warehouse/stock-items/${locationId}/${productId}`, { method: "DELETE", token });
}

export type StockMoveType =
  | "reservation"
  | "reservation_released"
  | "receipt"
  | "issue"
  | "adjustment"
  | "production"
  | "send_to_production"
  | "production_consumption"
  | "transfer_out"
  | "transfer_in"
  | "admin_correction";

export interface StockMove {
  id: string;
  location_id: string;
  product_id: string;
  quantity: number;
  move_type: StockMoveType;
  reference: string;
  actor_id: string | null;
  reason: string | null;
  created_at: string;
}

export function listStockMoves(
  token: string,
  params: { location_id?: string; product_id?: string; move_type?: StockMoveType; limit?: number } = {},
) {
  const query = new URLSearchParams();
  if (params.location_id) query.set("location_id", params.location_id);
  if (params.product_id) query.set("product_id", params.product_id);
  if (params.move_type) query.set("move_type", params.move_type);
  if (params.limit) query.set("limit", String(params.limit));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<StockMove[]>(`/warehouse/stock/moves${suffix}`, { token });
}

// --- Audit log (core.audit_log, ISO 9001 traceability) --------------------

export interface AuditLogEntry {
  id: string;
  actor_id: string;
  actor_email: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  occurred_at: string;
  payload: Record<string, unknown>;
}

export function listAuditLog(token: string, params: { entity_type?: string; entity_id?: string; limit?: number } = {}) {
  const query = new URLSearchParams();
  if (params.entity_type) query.set("entity_type", params.entity_type);
  if (params.entity_id) query.set("entity_id", params.entity_id);
  if (params.limit) query.set("limit", String(params.limit));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<AuditLogEntry[]>(`/core/audit-log${suffix}`, { token });
}

export type LotSerialTracking = "none" | "lot" | "serial";
export type ExpiryDatePolicy = "none" | "sell_by" | "eat_by";

export interface Product {
  id: string;
  sku: string;
  name: string;
  uom_id: string;
  net_weight_grams: number | null;
  /**
   * Phase 9, decision 20. Null means the product has no carton line at all —
   * a 4.54 kg sac is its own selling unit — not that nobody filled it in.
   */
  packets_per_carton: number | null;
  parent_product_id: string | null;
  is_sellable: boolean;
  is_purchasable: boolean;
  lot_serial_tracking: LotSerialTracking;
  expiry_date_policy: ExpiryDatePolicy;
  description: string | null;
  default_location_id: string | null;
  stock_alert_threshold: number | null;
  internal_note: string | null;
  selling_price: number;
  min_selling_price: number | null;
  purchase_price: number;
  tax_rate: number;
  accounting_code_sale: string | null;
  accounting_code_sale_export: string | null;
  accounting_code_purchase: string | null;
  accounting_code_purchase_import: string | null;
}

export function listProducts(token: string) {
  return apiFetch<Product[]>("/core/products", { token });
}

export interface SuggestedVendor {
  partner_id: string;
  name: string;
  kind: "customer" | "supplier" | "both";
  industry: string | null;
  phone: string | null;
  email: string | null;
  is_preferred: boolean;
  lead_time_days: number | null;
  min_order_qty: number | null;
}

export function listSuggestedVendors(token: string, productId: string) {
  return apiFetch<SuggestedVendor[]>(`/core/products/${productId}/suggested-vendors`, { token });
}

export interface UnitOfMeasure {
  id: string;
  code: string;
  name: string;
  category: string;
  ratio_to_base: number;
  /** How the unit prints next to a quantity ("pièce", "kg", "t"). `code` stays the key. */
  symbol: string;
  /** Whether a quantity in this unit must be a whole number (a carton, a pièce). */
  is_integer_only: boolean;
}

export function listUoms(token: string) {
  return apiFetch<UnitOfMeasure[]>("/core/uoms", { token });
}

// --- Confirmed goods receipts (procurement module) ------------------------
// Flat per-line view of every confirmed purchase-order receipt line, used for the
// landed-cost analysis below. Lives here (not a procurement feature folder yet) because
// this tab is the only current consumer -- see AnalysisTab.tsx.

export interface ReceiptLineDetail {
  product_id: string;
  uom_id: string;
  quantity: number;
  invoice_date: string | null;
  total_cost: number;
}

export function listConfirmedReceiptLineDetails(token: string) {
  return apiFetch<ReceiptLineDetail[]>("/procurement/receipt-lines", { token });
}

