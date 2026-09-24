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
  /** Set when this movement came from a production report -- the work order it belongs to. */
  of_id: string | null;
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

export type LotSerialTracking = "none" | "lot" | "serial";
export type ExpiryDatePolicy = "none" | "sell_by" | "eat_by";

export interface Product {
  id: string;
  sku: string;
  name: string;
  product_type: "PL" | "PC";
  product_family: string | null;
  uom_id: string;
  net_weight_grams: number | null;
  empty_packaging_weight_grams: number | null;
  sachets_per_package: number | null;
  /**
   * Phase 9, decision 20. Null means the product has no carton line at all —
   * a 4.54 kg sac is its own selling unit — not that nobody filled it in.
   */
  packets_per_carton: number | null;
  carton_weight_grams: number | null;
  cartons_per_pallet: number | null;
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
  tag_ids: string[];
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
  receipt_id: string;
  product_id: string;
  uom_id: string;
  quantity: number;
  invoice_date: string | null;
  total_cost: number;
  currency_code: string;
  // total_cost converted to base_currency (XOF) as of invoice_date -- use this, not
  // total_cost, whenever summing/averaging across rows: receipts can be in different
  // currencies (local CFA vs. imported EUR/TRY) and total_cost alone isn't comparable.
  total_cost_base: number;
  base_currency: string;
  origin_country: string | null;
  is_import: boolean;
  // "Majoration" alert: this row's cost/unit vs. this product+unit's average cost across
  // every OTHER confirmed receipt. baseline/deviation are null when there's no other
  // receipt yet to compare against (nothing flagged in that case).
  cost_per_unit_base: number;
  baseline_avg_cost_per_unit: number | null;
  cost_deviation_pct: number | null;
  is_cost_anomaly: boolean;
}

export function listConfirmedReceiptLineDetails(token: string) {
  return apiFetch<ReceiptLineDetail[]>("/procurement/receipt-lines", { token });
}

export interface CostSummaryRow {
  product_id: string;
  uom_id: string;
  origin_country: string | null;
  is_import: boolean;
  total_quantity: number;
  // Both already converted to base_currency (XOF) -- safe to compare/sort across rows
  // regardless of which currency each underlying receipt was priced in.
  average_cost_per_unit: number;
  best_cost_per_unit: number;
  receipt_count: number;
  base_currency: string;
}

export function getCostSummary(token: string) {
  return apiFetch<CostSummaryRow[]>("/procurement/cost-summary", { token });
}


// --- Lots -------------------------------------------------------------------

export interface Lot {
  id: string;
  product_id: string;
  lot_number: string;
  status: string;
  /** Null until someone enters it: production files a finished-goods lot with its number only. */
  expiry_date: string | null;
  produced_at: string | null;
  source_type: string | null;
  source_id: string | null;
}

/** The lots a validated packing report registers, which is where quality's DLC queue comes from. */
export const FINISHED_GOODS_LOT_SOURCE = "production.conditionnement_report";
export const SET_LOT_EXPIRY_PERMISSION = "warehouse.set_lot_expiry";
export const LOTS_QUERY_KEY = ["warehouse", "lots"] as const;

export function listLots(token: string, params: { sourceType?: string; withoutExpiry?: boolean } = {}) {
  const query = new URLSearchParams();
  if (params.sourceType) query.set("source_type", params.sourceType);
  if (params.withoutExpiry) query.set("without_expiry", "true");
  const suffix = query.size > 0 ? `?${query}` : "";
  return apiFetch<Lot[]>(`/warehouse/lots${suffix}`, { token });
}

export function setLotExpiry(token: string, lotId: string, expiryDate: string) {
  return apiFetch<Lot>(`/warehouse/lots/${lotId}/expiry`, {
    method: "PATCH",
    token,
    body: { expiry_date: expiryDate },
  });
}
