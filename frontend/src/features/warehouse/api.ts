import { apiErrorFromResponse, apiFetch, networkError, BASE_URL } from "../../lib/api";

export type LocationType = "zone" | "aisle" | "rack" | "bin";

export interface Location {
  id: string;
  code: string;
  name: string;
  site_id: string;
  location_type: LocationType;
  parent_location_id: string | null;
  sequence: number | null;
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
  // Optional hold expiry (ISO instant); the worker releases it once lapsed.
  // Omitted for a reservation meant to last until released by hand.
  expires_at?: string;
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
  | "admin_correction"
  | "shipment"
  | "reservation_expired";

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
  params: {
    location_id?: string;
    product_id?: string;
    move_type?: StockMoveType;
    /** Inclusive calendar-day bounds (YYYY-MM-DD). */
    date_from?: string;
    date_to?: string;
    limit?: number;
  } = {},
) {
  const query = new URLSearchParams();
  if (params.location_id) query.set("location_id", params.location_id);
  if (params.product_id) query.set("product_id", params.product_id);
  if (params.move_type) query.set("move_type", params.move_type);
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
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


// --- KPI overview -----------------------------------------------------------

export type CoverageStatus = "out" | "critical" | "warning" | "ok" | "idle";

/** One product's stock KPIs. Quantities are in the product's own unit -- never sum them across rows. */
export interface OverviewProductRow {
  product_id: string;
  sku: string;
  name: string;
  uom_id: string;
  on_hand: number;
  blocked_on_hand: number;
  reserved: number;
  in_production: number;
  /** Standard (purchase) cost per unit, null when the catalog has none. */
  unit_cost: number | null;
  /** on_hand x unit_cost, null when there is no cost -- not 0. */
  value: number | null;
  stock_alert_threshold: number | null;
  avg_daily_consumption: number;
  /** Null when nothing was consumed in the window (status "idle"). */
  days_of_cover: number | null;
  coverage_status: CoverageStatus;
  last_move_at: string | null;
  idle_days: number | null;
  is_dormant: boolean;
  period_inbound: number;
  period_outbound: number;
  period_consumed: number;
  /** Signed sum of manual adjustments and admin corrections in the period. */
  period_corrections: number;
  period_corrections_count: number;
  period_move_count: number;
}

export interface OverviewCorrection {
  id: string;
  product_id: string;
  location_id: string;
  quantity: number;
  move_type: StockMoveType;
  reason: string | null;
  reference: string;
  actor_id: string | null;
  created_at: string;
}

export interface OverviewExpiringLot {
  lot_id: string;
  product_id: string;
  lot_number: string;
  expiry_date: string;
  /** Negative once the lot is past its DLC. */
  days_until_expiry: number;
  quantity_on_hand: number;
}

export interface WarehouseOverview {
  period: { from: string; to: string; consumption_window_days: number; dormant_after_days: number; expiry_horizon_days: number };
  summary: {
    products_in_stock: number;
    stock_value: number;
    valued_products: number;
    unvalued_products: number;
    below_threshold: number;
    out_of_stock: number;
    negative_stock: number;
    blocked_products: number;
    coverage_critical: number;
    coverage_warning: number;
    dormant_count: number;
    movements_count: number;
    corrections_count: number;
    lots_expired: number;
    lots_expiring_soon: number;
  };
  flow_by_uom: { uom_id: string; inbound: number; outbound: number; consumed: number; corrections: number }[];
  moves_by_type: { move_type: StockMoveType; count: number }[];
  daily: { day: string; uom_id: string; inbound: number; outbound: number }[];
  products: OverviewProductRow[];
  corrections: OverviewCorrection[];
  expiring_lots: OverviewExpiringLot[];
}

export function getWarehouseOverview(
  token: string,
  params: { date_from?: string; date_to?: string; consumption_window_days?: number; dormant_after_days?: number } = {},
) {
  const query = new URLSearchParams();
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  if (params.consumption_window_days) query.set("consumption_window_days", String(params.consumption_window_days));
  if (params.dormant_after_days) query.set("dormant_after_days", String(params.dormant_after_days));
  const suffix = query.size > 0 ? `?${query}` : "";
  return apiFetch<WarehouseOverview>(`/warehouse/analytics/overview${suffix}`, { token });
}

/** The stock table as an .xlsx workbook (per location, then per product; FIFO
 * value columns only with warehouse.view_valuation) -- bypasses apiFetch,
 * which always parses JSON. */
export async function exportStock(token: string, siteId?: string): Promise<Blob> {
  const suffix = siteId ? `?${new URLSearchParams({ site_id: siteId })}` : "";
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}/warehouse/stock/export${suffix}`, { headers: { Authorization: `Bearer ${token}` } });
  } catch {
    throw networkError();
  }
  if (!response.ok) {
    throw await apiErrorFromResponse(response);
  }
  return response.blob();
}
