import { apiFetch, ApiError } from "../../lib/api";

// --- Products & units of measure -----------------------------------------

export interface Product {
  id: string;
  sku: string;
  name: string;
  uom_id: string;
  net_weight_grams: number | null;
  packets_per_carton: number | null;
  product_type: "PL" | "PC";
  // Free-text; for a packaging product it marks a PC/PL-specific variant,
  // null meaning it's generic and fits either (see the packaging-tag fix
  // script for how this is populated).
  product_family: string | null;
  is_sellable: boolean;
  tag_ids: string[];
}

export interface CreateProductInput {
  sku: string;
  name: string;
  uom_id: string;
  net_weight_grams?: number;
}

export interface UpdateProductInput {
  sku?: string;
  name?: string;
  uom_id?: string;
  net_weight_grams?: number;
  packets_per_carton?: number;
}

export interface UnitOfMeasure {
  id: string;
  code: string;
  name: string;
  category: string;
  ratio_to_base: number;
}

export function listProducts(token: string) {
  return apiFetch<Product[]>("/core/products", { token });
}

export function createProduct(token: string, input: CreateProductInput) {
  return apiFetch<Product>("/core/products", { method: "POST", token, body: input });
}

export function updateProduct(token: string, productId: string, input: UpdateProductInput) {
  return apiFetch<Product>(`/core/products/${productId}`, { method: "PATCH", token, body: input });
}

export function listUoms(token: string) {
  return apiFetch<UnitOfMeasure[]>("/core/uoms", { token });
}

// --- Product classification ---------------------------------------------

export type ProductCategory = "raw_material" | "semi_finished" | "packaging_component" | "finished_good";
export type PackagingFormat = "packet" | "carton" | "sac";
export type PackagingKind = "film" | "carton" | "bobine" | "scotch" | "ruban";

export interface ProductClassification {
  product_id: string;
  category: ProductCategory;
  is_regrind: boolean;
  packaging_format: PackagingFormat | null;
  is_water: boolean;
  packaging_kind: PackagingKind | null;
}

export interface SetClassificationInput {
  product_id: string;
  category: ProductCategory;
  is_regrind: boolean;
  packaging_format?: PackagingFormat;
  is_water?: boolean;
  packaging_kind?: PackagingKind;
}

export function listClassifications(token: string) {
  return apiFetch<ProductClassification[]>("/production/product-classifications", { token });
}

export function setClassification(token: string, input: SetClassificationInput) {
  return apiFetch<ProductClassification>("/production/product-classifications", {
    method: "POST",
    token,
    body: input,
  });
}

// --- Packaging BOMs --------------------------------------------------------

export type PackagingBomStatus = "draft" | "active" | "archived";

export interface PackagingBomLine {
  component_product_id: string;
  quantity_per_unit: number;
}

export interface PackagingBom {
  id: string;
  target_product_id: string;
  version: number;
  status: PackagingBomStatus;
  lines: PackagingBomLine[];
}

export interface CreatePackagingBomInput {
  target_product_id: string;
  lines: PackagingBomLine[];
}

export interface UpdatePackagingBomInput {
  target_product_id?: string;
  lines?: PackagingBomLine[];
}

export function listPackagingBoms(token: string) {
  return apiFetch<PackagingBom[]>("/production/packaging-boms", { token });
}

export function createPackagingBom(token: string, input: CreatePackagingBomInput) {
  return apiFetch<PackagingBom>("/production/packaging-boms", { method: "POST", token, body: input });
}

export function updatePackagingBom(token: string, bomId: string, input: UpdatePackagingBomInput) {
  return apiFetch<PackagingBom>(`/production/packaging-boms/${bomId}`, { method: "PATCH", token, body: input });
}

export function activatePackagingBom(token: string, bomId: string) {
  return apiFetch<PackagingBom>(`/production/packaging-boms/${bomId}/activate`, { method: "POST", token });
}

export function archivePackagingBom(token: string, bomId: string) {
  return apiFetch<PackagingBom>(`/production/packaging-boms/${bomId}/archive`, { method: "POST", token });
}

// --- Work orders -------------------------------------------------------

export type WorkOrderStatus = "planned" | "ongoing" | "suspended" | "closed" | "cancelled";

export interface WorkOrder {
  id: string;
  reference: string;
  // Null until Conditionnement names one, with the order's first packaging report.
  product_id: string | null;
  planned_quantity: number | null;
  status: WorkOrderStatus;
  work_center_id: string | null;
  // Who is responsible for this OF. Optional — unlike work_center_id, never
  // required to create or run one.
  supervisor_id: string | null;
  recipe_id: string | null;
  packaging_bom_id: string | null;
  start_date: string | null;
  product_type: string | null;
  notes: string | null;
  created_by: string | null;
  closed_at: string | null;
  closed_by: string | null;
  // An OFR — the order a rebroyat run is built on. Tracked in Rebuts et
  // rebroyat, never reported on.
  is_regrind: boolean;
}

export interface PouredInputInput {
  productId: string;
  quantity: number;
}

export interface CreateWorkOrderInput {
  work_center_id: string;
  product_id?: string;
  planned_quantity?: number;
  supervisor_id?: string;
  recipe_id?: string;
  start_date?: string;
  product_type?: string;
  notes?: string;
  pouredInputs?: PouredInputInput[];
  pouredInputsLocationId?: string;
}

export interface UpdateWorkOrderInput {
  product_id?: string;
  planned_quantity?: number;
  work_center_id?: string;
  supervisor_id?: string;
  recipe_id?: string;
  packaging_bom_id?: string;
  start_date?: string;
  product_type?: string;
  notes?: string;
}

export function listWorkOrders(token: string) {
  return apiFetch<WorkOrder[]>("/production/work-orders", { token });
}

// A user with the Production role — who can be named an OF's supervisor.
// Never a raw id in the UI: full_name is what's shown when a user has one on
// file (set via Admin > Users), falling back to email otherwise.
export interface SupervisorOption {
  id: string;
  email: string;
  full_name: string | null;
}

export function supervisorLabel(supervisor: SupervisorOption): string {
  return supervisor.full_name || supervisor.email;
}

export function listSupervisorOptions(token: string) {
  return apiFetch<SupervisorOption[]>("/production/work-orders/supervisors", { token });
}

export function createWorkOrder(token: string, input: CreateWorkOrderInput) {
  return apiFetch<WorkOrder>("/production/work-orders", {
    method: "POST",
    token,
    body: {
      product_id: input.product_id,
      planned_quantity: input.planned_quantity,
      work_center_id: input.work_center_id,
      supervisor_id: input.supervisor_id,
      recipe_id: input.recipe_id,
      start_date: input.start_date,
      product_type: input.product_type,
      notes: input.notes,
      poured_inputs: (input.pouredInputs ?? []).map((i) => ({ product_id: i.productId, quantity: i.quantity })),
      poured_inputs_location_id: input.pouredInputsLocationId,
    },
  });
}

export interface WorkOrderInputLine {
  id: string;
  product_id: string;
  quantity: number;
  location_id: string;
  recipe_line_id: string | null;
}

export function listWorkOrderInputs(token: string, workOrderId: string) {
  return apiFetch<WorkOrderInputLine[]>(`/production/work-orders/${workOrderId}/inputs`, { token });
}

export function updateWorkOrder(token: string, workOrderId: string, input: UpdateWorkOrderInput) {
  return apiFetch<WorkOrder>(`/production/work-orders/${workOrderId}`, { method: "PATCH", token, body: input });
}

export function startWorkOrder(token: string, workOrderId: string) {
  return apiFetch<{ id: string; status: WorkOrderStatus }>(`/production/work-orders/${workOrderId}/start`, {
    method: "POST",
    token,
  });
}

export function suspendWorkOrder(token: string, workOrderId: string, reason?: string) {
  return apiFetch<WorkOrder>(`/production/work-orders/${workOrderId}/suspend`, {
    method: "POST",
    token,
    body: { reason },
  });
}

export function resumeWorkOrder(token: string, workOrderId: string) {
  return apiFetch<WorkOrder>(`/production/work-orders/${workOrderId}/resume`, { method: "POST", token });
}

export function cancelWorkOrder(token: string, workOrderId: string, reason?: string) {
  return apiFetch<WorkOrder>(`/production/work-orders/${workOrderId}/cancel`, {
    method: "POST",
    token,
    body: { reason },
  });
}

// What still stands between an OF and closure. Blockers are unfinished production
// work; warnings are worth showing but never hold an order open — quality
// follow-up in particular outlives production by design.
export interface PreCloseFinding {
  code: string;
  count: number;
  message: string;
}

export interface PreCloseCheck {
  of_id: string;
  reference: string;
  status: WorkOrderStatus;
  can_close: boolean;
  blockers: PreCloseFinding[];
  warnings: PreCloseFinding[];
  validated_report_count: number;
}

export function getPreCloseCheck(token: string, workOrderId: string) {
  return apiFetch<PreCloseCheck>(`/production/work-orders/${workOrderId}/pre-close-check`, { token });
}

// Closing an OF is archival: it moves no stock and deletes nothing. What was
// produced and consumed is posted by validating the OF's reports, not here.
// `force` closes over unfinished reports and requires a reason, which is audited.
export function closeWorkOrder(
  token: string,
  workOrderId: string,
  correlationId: string,
  options: { force?: boolean; forceReason?: string; closedAt?: string } = {},
) {
  return apiFetch<WorkOrder>(`/production/work-orders/${workOrderId}/close`, {
    method: "POST",
    token,
    body: {
      correlation_id: correlationId,
      force: options.force,
      force_reason: options.forceReason,
      closed_at: options.closedAt,
    },
  });
}

// --- Work centers & machines --------------------------------------------

export interface WorkCenter {
  id: string;
  code: string;
  name: string;
  hourly_rate: number;
  is_blocked: boolean;
  blocked_reason: string | null;
}

export interface CreateWorkCenterInput {
  code: string;
  name: string;
  hourly_rate?: number;
}

export interface UpdateWorkCenterInput {
  code?: string;
  name?: string;
  hourly_rate?: number;
}

export function listWorkCenters(token: string) {
  return apiFetch<WorkCenter[]>("/production/work-centers", { token });
}

export function createWorkCenter(token: string, input: CreateWorkCenterInput) {
  return apiFetch<WorkCenter>("/production/work-centers", { method: "POST", token, body: input });
}

export function updateWorkCenter(token: string, workCenterId: string, input: UpdateWorkCenterInput) {
  return apiFetch<WorkCenter>(`/production/work-centers/${workCenterId}`, { method: "PATCH", token, body: input });
}

export function blockWorkCenter(token: string, workCenterId: string, reason: string) {
  return apiFetch<WorkCenter>(`/production/work-centers/${workCenterId}/block`, {
    method: "POST",
    token,
    body: { reason },
  });
}

export function unblockWorkCenter(token: string, workCenterId: string) {
  return apiFetch<WorkCenter>(`/production/work-centers/${workCenterId}/unblock`, { method: "POST", token });
}

// A line like Line_1_PL can carry more than one machine running at once (see
// the Maintenance module's Equipment tab, where they're added). This is a
// thin pass-through so a report's machine field, or resolving a report's
// equipment_id to a name, never needs maintenance.view_equipment.
export interface Machine {
  id: string;
  code: string;
  name: string;
  status: "operational" | "down" | "maintenance";
}

export function listMachines(token: string, workCenterId?: string) {
  const query = workCenterId ? `?work_center_id=${encodeURIComponent(workCenterId)}` : "";
  return apiFetch<Machine[]>(`/production/machines${query}`, { token });
}

// --- Molds ----------------------------------------------------------------

export type MoldType = "PC" | "PL";

export interface Mold {
  id: string;
  code: string;
  name: string;
  type: MoldType;
}

export interface CreateMoldInput {
  code: string;
  name: string;
  type: MoldType;
}

export interface UpdateMoldInput {
  code?: string;
  name?: string;
  type?: MoldType;
}

export function listMolds(token: string) {
  return apiFetch<Mold[]>("/production/molds", { token });
}

export function createMold(token: string, input: CreateMoldInput) {
  return apiFetch<Mold>("/production/molds", { method: "POST", token, body: input });
}

export function updateMold(token: string, moldId: string, input: UpdateMoldInput) {
  return apiFetch<Mold>(`/production/molds/${moldId}`, { method: "PATCH", token, body: input });
}

// --- Recipes -------------------------------------------------------------

export type RecipeStatus = "draft" | "trial" | "active" | "archived";

export interface RecipeLine {
  component_product_id: string;
  default_percentage: number;
  min_percentage: number;
  max_percentage: number;
  is_hard_limit: boolean;
}

export interface Recipe {
  id: string;
  target_product_id: string;
  version: number;
  status: RecipeStatus;
  target_moisture_percentage: number | null;
  origin: string;
  ai_confidence: number | null;
  previous_recipe_id: string | null;
  lines: RecipeLine[];
}

export interface CreateRecipeInput {
  target_product_id: string;
  target_moisture_percentage?: number;
  lines: RecipeLine[];
}

export function listRecipes(token: string) {
  return apiFetch<Recipe[]>("/production/recipes", { token });
}

export function createRecipe(token: string, input: CreateRecipeInput) {
  return apiFetch<Recipe>("/production/recipes", { method: "POST", token, body: input });
}

export function promoteRecipeToTrial(token: string, recipeId: string) {
  return apiFetch<Recipe>(`/production/recipes/${recipeId}/promote-to-trial`, { method: "POST", token });
}

export function rejectRecipe(token: string, recipeId: string) {
  return apiFetch<Recipe>(`/production/recipes/${recipeId}/reject`, { method: "POST", token });
}

export function activateRecipe(token: string, recipeId: string) {
  return apiFetch<Recipe>(`/production/recipes/${recipeId}/activate`, { method: "POST", token });
}

export function archiveRecipe(token: string, recipeId: string) {
  return apiFetch<Recipe>(`/production/recipes/${recipeId}/archive`, { method: "POST", token });
}

// --- Scrap & regrind -------------------------------------------------------

// "cutting" and "filling_dosing" are the two a person picks in the "Enregistrer
// un rebut" dialog. "daily_report" and "non_conformity" never come from that
// dialog -- they're written by the backend itself (a validated daily report's
// own rebroyat figure, or a QC disposition sending a rejected packet back to
// regrind) and only ever appear when reading scrap records back.
export type ScrapType = "filling_dosing" | "cutting" | "daily_report" | "non_conformity";

export interface ScrapRecord {
  id: string;
  work_order_id: string | null;
  operation_step_id: string | null;
  scrap_type: ScrapType;
  product_id: string;
  quantity: number;
  is_reground: boolean;
  work_center_id: string | null;
  source_note: string | null;
  // The OFR that consumed this scrap; null while it is still available.
  regrind_work_order_id: string | null;
}

export interface RecordScrapInput {
  scrap_type: ScrapType;
  product_id: string;
  quantity: number;
  work_order_id?: string;
  work_center_id?: string;
  source_note?: string;
}

// The rebroyat-specific workflow shown in the UI: new (just opened, nobody
// responsible yet) -> assigned (a responsable handed it to a team) -> finished
// (the team weighed the real output and it is back in stock). Layered on top
// of the OF's own status rather than replacing it — see regrind_stage() on
// the backend.
export type RegrindStage = "new" | "assigned" | "finished" | "suspended" | "cancelled";

// One scrap input a regrind batch was built from -- work_order_id is the
// *production* OF the scrap came off of (cutting/filling waste), not the
// regrind batch itself. This is what lets a raw-material stock line trace a
// receipt back to "ground from OF-X's cutting scrap".
export interface RegrindScrapInput {
  id: string;
  work_order_id: string | null;
  product_id: string;
  scrap_type: ScrapType;
  quantity: number;
}

export interface RegrindBatch {
  work_order: WorkOrder;
  scrap_record_ids: string[];
  scrap_inputs: RegrindScrapInput[];
  input_quantity_total: number;
  actual_output_quantity: number | null;
  loss_quantity: number | null;
  stage: RegrindStage;
  assigned_team: string | null;
  assigned_by: string | null;
  assigned_at: string | null;
}

export interface RegrindBatchSummary {
  work_order_id: string;
  output_product_id: string;
  output_quantity: number;
  actual_output_quantity: number | null;
  status: WorkOrderStatus;
  stage: RegrindStage;
  assigned_team: string | null;
  work_center_id: string | null;
  input_quantity_total: number;
  // null until the batch is finished and a real weight has been entered — an
  // écart can only be measured once that happens.
  loss_quantity: number | null;
  created_at: string;
}

export interface CreateRegrindBatchInput {
  scrap_record_ids: string[];
  output_quantity: number;
  work_center_id?: string;
}

export function assignRegrindBatch(token: string, workOrderId: string, team: string) {
  return apiFetch<RegrindBatch>(`/production/regrind-batches/${workOrderId}/assign`, {
    method: "POST",
    token,
    body: { team },
  });
}

export function listScrapRecords(token: string, isReground?: boolean) {
  const query = isReground === undefined ? "" : `?is_reground=${isReground}`;
  return apiFetch<ScrapRecord[]>(`/production/scrap-records${query}`, { token });
}

export function recordScrap(token: string, input: RecordScrapInput) {
  return apiFetch<ScrapRecord>("/production/scrap-records", { method: "POST", token, body: input });
}

export function createRegrindBatch(token: string, input: CreateRegrindBatchInput) {
  return apiFetch<RegrindBatch>("/production/regrind-batches", { method: "POST", token, body: input });
}

export interface CompletedRegrindBatch {
  work_order: WorkOrder;
  input_quantity_total: number;
  output_quantity: number;
  loss_quantity: number;
}

export interface CompleteRegrindBatchInput {
  correlationId: string;
  locationId: string;
  actualOutputQuantity?: number;
}

// Rebroyat is the one production output that still becomes stock on its own work
// order: a regrind batch has no report behind it, only the scrap it was built from.
export function completeRegrindBatch(token: string, workOrderId: string, input: CompleteRegrindBatchInput) {
  return apiFetch<CompletedRegrindBatch>(`/production/regrind-batches/${workOrderId}/complete`, {
    method: "POST",
    token,
    body: {
      correlation_id: input.correlationId,
      location_id: input.locationId,
      actual_output_quantity: input.actualOutputQuantity,
    },
  });
}

export function listRegrindBatches(token: string) {
  return apiFetch<RegrindBatchSummary[]>("/production/regrind-batches", { token });
}

export function getRegrindBatch(token: string, workOrderId: string) {
  return apiFetch<RegrindBatch>(`/production/regrind-batches/${workOrderId}`, { token });
}

// --- Rendement (yield) ------------------------------------------------------

export interface WorkOrderYield {
  work_order_id: string;
  // Every term is summed from the OF's validated reports — nothing is cached on
  // the order any more, so a yield always matches the reports behind it.
  produced_quantity: number;
  rebroyat_quantity: number;
  // Semoule plus any rebroyat poured back in — the material the line was given.
  semoule_quantity_total: number;
  yield_ratio: number;
}

export interface RecipeYieldSummary {
  recipe_id: string;
  work_order_count: number;
  average_yield_ratio: number | null;
}

export function listWorkOrderYields(token: string) {
  return apiFetch<WorkOrderYield[]>("/production/work-orders/yields", { token });
}

/** What the OF list needs per order, from one light read: official figures from validated shifts, pending ones apart. */
export interface WorkOrderOverview {
  of_id: string;
  /** Products of the validated packing reports (earliest first), else the order's own; empty until either exists. */
  products: string[];
  /** Tonnes packed in validated shifts. */
  produced_quantity: number;
  /** produced / planned; null when the order has no planned quantity. */
  completion_ratio: number | null;
  /** Null until a shift is validated. */
  yield_ratio: number | null;
  shifts: { validated: number; submitted: number; in_progress: number; returned: number };
  last_shift_date: string | null;
  /** Tonnes on shifts handed in or still being typed; never part of the official figure. */
  pending_quantity: number;
  live: boolean;
}

export const WORK_ORDER_OVERVIEW_QUERY_KEY = ["production", "work-orders", "overview"] as const;

export function getWorkOrdersOverview(token: string, params: { date: string; at: string }) {
  return apiFetch<WorkOrderOverview[]>(`/production/work-orders/overview?date=${params.date}&at=${params.at}`, { token });
}

// --- Team performance --------------------------------------------------------
//
// Output, time and waste from validated reports, bucketed by team and by
// calendar period. Team is whatever Production Settings has configured — new
// teams show up on their own, there is nothing to register here.

export type PerformanceGrain = "day" | "week" | "month" | "year";

export interface TeamPerformanceRow {
  team: string | null;
  period: string;
  report_count: number;
  semolina_quantity: number;
  regrind_input_quantity: number;
  material_input_quantity: number;
  produced_quantity: number;
  production_minutes: number;
  downtime_minutes: number;
  waste_by_product: { product_id: string; quantity: number }[];
  /**
   * Semoule-side déchet only (daily report categories), by stage — where it
   * came from. Always raw kilos (the form's own basis), never each stage's
   * own item unit: `finished_product_conditioning` is usually logged against
   * a finished-good item stocked in kg while the other five stages use bulk
   * semoule stocked in tonnes, so converting each to its own unit would make
   * stages look wildly different sizes once stacked/compared side by side.
   */
  daily_waste_by_category: Partial<Record<WasteCategory, number>>;
  /** What the team declared as rebroyat over the same reports — recovered, not lost. */
  regrind_quantity: number;
  /** daily_waste_by_category summed, minus regrind_quantity: semoule genuinely lost. */
  net_semoule_waste: number;
}

export function listTeamPerformance(
  token: string,
  params: { grain: PerformanceGrain; date_from?: string; date_to?: string },
) {
  const query = new URLSearchParams({ grain: params.grain });
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  return apiFetch<TeamPerformanceRow[]>(`/production/reports/team-performance?${query.toString()}`, { token });
}

// --- Machine performance ------------------------------------------------
//
// Same shape as team performance, grouped by machine instead of by team — a
// line like Line_1_PL can run more than one machine at once, so productivity
// has to be checkable per machine, not just per line. Rows are keyed by
// equipment_id, an opaque reference into the Maintenance module: resolve it
// to a code/name via listMachines or the Equipment tab's own list.

export interface MachinePerformanceRow {
  equipment_id: string;
  period: string;
  report_count: number;
  material_input_quantity: number;
  produced_quantity: number;
  production_minutes: number;
  downtime_minutes: number;
}

export function listMachinePerformance(
  token: string,
  params: { grain: PerformanceGrain; date_from?: string; date_to?: string },
) {
  const query = new URLSearchParams({ grain: params.grain });
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  return apiFetch<MachinePerformanceRow[]>(`/production/reports/machine-performance?${query.toString()}`, { token });
}

export interface DowntimeReasonRow {
  reason: string;
  minutes: number;
  report_count: number;
}

export function listDowntimeReasons(token: string, params: { date_from?: string; date_to?: string } = {}) {
  const query = new URLSearchParams();
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<DowntimeReasonRow[]>(`/production/reports/downtime-reasons${suffix}`, { token });
}

// --- Consumption by supplier ---------------------------------------------
//
// Film/carton/scotch/ruban (from conditionnement reports) and gasoil/fuel
// (from daily reports), grouped by category/month/PC-PL/fournisseur — the
// report that replaces the plant's hand-built monthly spreadsheets. Ids
// (product_id/supplier_id) are resolved to names client-side, same as every
// other screen in this app.

export type ConsumptionCategory = "film" | "carton" | "scotch" | "ruban" | "gasoil" | "fuel";

export interface ConsumptionRow {
  category: ConsumptionCategory;
  month: string;
  pc_pl: string | null;
  product_id: string | null;
  supplier_id: string | null;
  quantity: number;
  unit_price: number | null;
  unit_price_currency: string | null;
  cost: number | null;
  /** False when no procurement order history exists for this supplier+product to cost it from. */
  priced: boolean;
}

function consumptionQuery(params: { date_from?: string; date_to?: string; category?: ConsumptionCategory }) {
  const query = new URLSearchParams();
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  if (params.category) query.set("category", params.category);
  return query;
}

export function listConsumptionBySupplier(
  token: string,
  params: { date_from?: string; date_to?: string; category?: ConsumptionCategory } = {},
) {
  const query = consumptionQuery(params);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<ConsumptionRow[]>(`/production/reports/consumption-by-supplier${suffix}`, { token });
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

/** Downloads the same data as an .xlsx workbook laid out like the original
 * spreadsheets — bypasses apiFetch since that always parses JSON. */
export async function exportConsumptionBySupplier(
  token: string,
  params: { date_from?: string; date_to?: string; category?: ConsumptionCategory } = {},
): Promise<Blob> {
  const query = consumptionQuery(params);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  const response = await fetch(`${API_BASE_URL}/production/reports/consumption-by-supplier/export${suffix}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new ApiError(response.status, "EXPORT_FAILED", response.statusText);
  }
  return response.blob();
}

export type ProductionRecapPeriod = "day" | "week" | "month";

/** The full plant recap workbook (produit fini, consommations, coûts
 * unitaires, achats, charges and coût de production) for one day, ISO week
 * or calendar month anchored on `date` — see daily_recap_export.py. */
export async function exportProductionRecap(
  token: string,
  params: { date: string; period: ProductionRecapPeriod },
): Promise<Blob> {
  const query = new URLSearchParams({ date: params.date, period: params.period });
  const response = await fetch(`${API_BASE_URL}/production/reports/daily-recap/export?${query.toString()}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new ApiError(response.status, "EXPORT_FAILED", response.statusText);
  }
  return response.blob();
}

// --- Production recap analytics (always-on charts/tables) ----------------
//
// The JSON twin of the recap export above, for the dashboard that renders
// inline instead of downloading -- see production_analytics_service.py.
// Fixed charges (Salaire, Amortissement, Impôts, ...) are deliberately
// absent here: they only exist once someone types them into the exported
// workbook, so "variable_cost"/"cost_per_tonne" below means MP + emballage
// only, never the export's full charges-included figure.

export interface ProductionCostBreakdownEntry {
  category: string;
  cost: number;
}

export interface ProductionPeriodPoint {
  date_from: string;
  date_to: string;
  label: string;
  tonnage: number;
  mp_cost: number | null;
  packaging_cost: number | null;
  /** null when mp_cost or packaging_cost is null (a row this period has no price yet) --
   * never coerced to 0, since that would understate the true cost. */
  variable_cost: number | null;
  cost_per_tonne: number | null;
  cartons: number;
  packets: number;
  cost_breakdown: ProductionCostBreakdownEntry[];
}

export interface ProductionCostAnomaly {
  receipt_id: string;
  product_id: string | null;
  supplier_id: string | null;
  invoice_date: string | null;
  quantity: number;
  cost_per_unit_base: number;
  baseline_avg_cost_per_unit: number | null;
  cost_deviation_pct: number | null;
  is_cost_anomaly: boolean;
}

export interface ProductionAnalytics {
  period: ProductionRecapPeriod;
  period_phrase: string;
  date_from: string;
  date_to: string;
  current: ProductionPeriodPoint;
  trend: ProductionPeriodPoint[];
  anomalies: ProductionCostAnomaly[];
}

export function getProductionAnalytics(token: string, params: { date: string; period: ProductionRecapPeriod }) {
  const query = new URLSearchParams({ date: params.date, period: params.period });
  return apiFetch<ProductionAnalytics>(`/production/reports/daily-recap/analytics?${query.toString()}`, { token });
}

/** Full granularity (reason x team x machine) -- a caller re-aggregates by
 * whichever dimension it needs, rather than one endpoint per slice. */
export interface DowntimeBreakdownRow {
  reason: string;
  team: string | null;
  equipment_id: string | null;
  minutes: number;
  report_count: number;
}

export function listDowntimeBreakdown(token: string, params: { date_from?: string; date_to?: string } = {}) {
  const query = new URLSearchParams();
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<DowntimeBreakdownRow[]>(`/production/reports/downtime-breakdown${suffix}`, { token });
}

// --- Recipe correlation ------------------------------------------------------
//
// Each shift's water dosage and flow rate against its own OF's yield —
// deliberately coarse (Phase 6's yield is per-OF, not per-shift), and sparse
// until the plant has filed a few weeks of shifts with these figures recorded.

export interface RecipeCorrelationRow {
  report_id: string;
  of_id: string;
  product_id: string;
  report_date: string;
  team: string | null;
  water_percentage: number | null;
  semolina_flow_rate: number | null;
  yield_ratio: number;
  /** The OF's recipe's own water line, when it has one classified is_water. Null means no target to check against, not that the dosage is fine. */
  water_target_min: number | null;
  water_target_max: number | null;
  water_target_default: number | null;
}

export function listRecipeCorrelation(token: string) {
  return apiFetch<RecipeCorrelationRow[]>("/production/work-orders/recipe-correlation", { token });
}

export interface RecipeCorrelationInsight {
  available: boolean;
  text: string | null;
}

/** Generated on demand (never on page load) -- each call is a real Groq request against the free tier's quota. */
export function getRecipeCorrelationInsight(token: string, locale: string) {
  return apiFetch<RecipeCorrelationInsight>(
    `/production/work-orders/recipe-correlation/insight?locale=${encodeURIComponent(locale)}`,
    { token },
  );
}

export function getWorkOrderYield(token: string, workOrderId: string) {
  return apiFetch<WorkOrderYield>(`/production/work-orders/${workOrderId}/yield`, { token });
}

// --- IA assistant ------------------------------------------------------------
//
// A per-user chat grounded in this tenant's own production stats via
// server-side Groq function-calling -- the assistant only ever states a
// number after fetching it through a whitelisted, already-aggregated tool, and
// only once at least 10 shifts/reports back it (see MIN_ROWS_FOR_TOOL_RESULT in
// ia_assistant_service.py). Conversations are private: nobody else, including
// an admin, can list or read another user's.

export interface IaAssistantConversation {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface IaAssistantMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export function listIaAssistantConversations(token: string) {
  return apiFetch<IaAssistantConversation[]>("/production/ia-assistant/conversations", { token });
}

export function createIaAssistantConversation(token: string) {
  return apiFetch<IaAssistantConversation>("/production/ia-assistant/conversations", { method: "POST", token });
}

export function deleteIaAssistantConversation(token: string, conversationId: string) {
  return apiFetch<void>(`/production/ia-assistant/conversations/${conversationId}`, { method: "DELETE", token });
}

export function listIaAssistantMessages(token: string, conversationId: string) {
  return apiFetch<IaAssistantMessage[]>(`/production/ia-assistant/conversations/${conversationId}/messages`, { token });
}

/** The assistant's one reply -- the user's own message is echoed back into the
 * message list by a refetch, not returned here, since the backend only persists
 * the pair once it actually has an answer (see send_message's docstring). */
export function sendIaAssistantMessage(token: string, conversationId: string, content: string, locale: string) {
  return apiFetch<IaAssistantMessage>(`/production/ia-assistant/conversations/${conversationId}/messages`, {
    method: "POST",
    token,
    body: { content, locale },
  });
}

// --- OF consolidation -------------------------------------------------------
//
// What an OF produced and consumed, summed live from its validated reports.
// Available while the order is still running: it simply reflects the shifts
// validated so far.

export interface OfConsolidation {
  of_id: string;
  reference: string;
  product_id: string;
  /** Every product the order's validated packing reports cover, earliest first; the order's own before its first one. */
  product_ids: string[];
  status: string;
  work_center_id: string | null;
  start_date: string | null;
  closed_at: string | null;
  /** Tonnes, per decision 19. Null for a mold-created OF whose quantity is not yet assigned. */
  planned_quantity: number | null;
  /** Tonnes: the packing reports' summed tonnage (decision 17). */
  produced_quantity: number;
  /** What the line counted into stock, in the product's own unit. */
  packets_counted: number;
  completion_ratio: number | null;
  // Produced against what was actually poured in — semoule plus rebroyat
  // recycled back into the mix — rather than against the schedule.
  material_input_quantity: number;
  transformation_ratio: number | null;
  // The product ids say which unit each total is in. Null when the validated
  // reports named different products, in which case no unit is true of the sum.
  raw_material: {
    semolina_quantity: number;
    semolina_product_id: string | null;
    /** Per quality, sorted largest first. Null semolina_product_id above just means more than one was poured. */
    semolina_by_product: { product_id: string; quantity: number }[];
    regrind_input_quantity: number;
    regrind_input_product_id: string | null;
    dough_quantity: number;
  };
  packaging: {
    film_quantity: number;
    film_product_id: string | null;
    carton_quantity: number;
    /** Part of carton_quantity above that held no product — see ConditionnementReportDetail.waste_carton_quantity. */
    waste_carton_quantity: number;
    carton_product_id: string | null;
    scotch_quantity: number;
    scotch_product_id: string | null;
    ruban_quantity: number;
    ruban_product_id: string | null;
  };
  utilities: { water_quantity: number; fuel_quantity: number; electricity_quantity: number };
  waste: {
    /** Per stage, the way the plant's own form is laid out. */
    by_category: Partial<Record<WasteCategory, number>>;
    /** Per item — the only grouping a unit can be attached to. */
    by_product: { product_id: string; quantity: number }[];
    /**
     * Quantity on lines that never said what was lost, from reports written
     * before waste named its item. Shown rather than hidden so it gets fixed.
     */
    unattributed_quantity: number;
    /** Not waste: recovered material that opens its own regrind OF. */
    regrind: { quantity: number; product_id: string | null };
    /**
     * The semoule genuinely lost: daily-report déchet (raw_material through
     * finished_product_conditioning — never conditionnement's product/packaging,
     * which isn't semoule any more) net of the rebroyat declared over the same
     * reports. The figure the plant tracks to minimise.
     */
    net_semoule_waste: number;
  };
  time: { production_minutes: number; downtime_minutes: number };
  quality: {
    validated_report_count: number;
    conforming_cartons: number;
    non_conforming_cartons: number;
    conformity_rate: number | null;
    /**
     * Validated reports that logged a defect but never got a case raised
     * against it -- nothing pulls that carton off the market until someone
     * does, so the screen needs to flag it rather than let it hide inside a
     * conformity percentage that already counts it as lost.
     */
    pending_nc_reports: { report_id: string; report_date: string; non_conforming_cartons: number }[];
  };
  report_counts: { daily: number; conditionnement: number; quality: number };
}

export function getWorkOrderConsolidation(token: string, workOrderId: string) {
  return apiFetch<OfConsolidation>(`/production/work-orders/${workOrderId}/consolidation`, { token });
}

/** A running OF's consolidation, plus the teams that filed the validated reports behind it. */
export interface ActiveOfConsolidation extends OfConsolidation {
  teams: string[];
}

// Under the per-OF key's prefix so anything that refreshes one order's figures
// refreshes the cockpit's batch too.
export const ACTIVE_CONSOLIDATIONS_QUERY_KEY = ["production", "of-consolidation", "active"] as const;

/** Every ongoing or suspended OF in one request, instead of two requests per order. */
export function listActiveConsolidations(token: string) {
  return apiFetch<ActiveOfConsolidation[]>(`/production/work-orders/active-consolidations`, { token });
}

// What was poured into an OF, against the recipe it follows.
//
// Advisory only. Nothing in the report or validation flow reads this — the plant's
// rule is warn, never block — so a finding here never prevents anything.
export interface RecipeFinding {
  code: "BELOW_MINIMUM" | "ABOVE_MAXIMUM" | "COMPONENT_NOT_POURED" | "NOT_IN_RECIPE" | "NEGATIVE_QUANTITY";
  component_product_id: string | null;
  severity: "hard" | "soft";
  actual_percentage: number | null;
  min_percentage: number | null;
  max_percentage: number | null;
}

export interface RecipeCheck {
  of_id: string;
  reference: string;
  recipe_id: string | null;
  /** False means there was no formula to check against, not that it passed. */
  has_recipe: boolean;
  mix: { product_id: string; quantity: number }[];
  mix_total: number;
  findings: RecipeFinding[];
  has_findings: boolean;
  hard_finding_count: number;
}

export function getWorkOrderRecipeCheck(token: string, workOrderId: string) {
  return apiFetch<RecipeCheck>(`/production/work-orders/${workOrderId}/recipe-check`, { token });
}

/** Same recipe-check finding, aggregated across every recipe-linked OF in
 * range -- how often a recipe trips a finding in practice, not one OF at a
 * time. `top_finding_component_id` is null only when a recipe had no
 * findings at all in range. */
export interface RecipeDriftRow {
  recipe_id: string;
  of_count: number;
  hard_finding_of_count: number;
  soft_finding_of_count: number;
  top_finding_code: RecipeFinding["code"] | null;
  top_finding_component_id: string | null;
  top_finding_count: number;
}

export function listRecipeDrift(token: string, params: { date_from?: string; date_to?: string } = {}) {
  const query = new URLSearchParams();
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<RecipeDriftRow[]>(`/production/recipes/drift-summary${suffix}`, { token });
}

export function getRecipeYieldSummary(token: string, recipeId: string) {
  return apiFetch<RecipeYieldSummary>(`/production/recipes/${recipeId}/yield-summary`, { token });
}

// --- Production reports -----------------------------------------------------
//
// A report is the team's claim about a shift until a supervisor validates it.
// Approving and correcting are separate rights on purpose: validate accepts the
// figures, correct changes what the team entered, and the originals are kept as
// a revision either way.

export type ReportStatus = "draft" | "submitted" | "validated" | "rejected";
export type ReportType = "daily" | "conditionnement";

export interface ProductionReport {
  id: string;
  of_id: string;
  report_type: ReportType;
  report_date: string;
  status: ReportStatus;
  revision: number;
  team: string | null;
  work_center_id: string | null;
  // Which machine within work_center_id ran this shift — a line can carry
  // more than one at once. Optional while a draft, required to submit.
  equipment_id: string | null;
  shift: string | null;
  created_by: string | null;
  submitted_at: string | null;
  validated_by: string | null;
  validated_at: string | null;
  rejection_reason: string | null;
}

/**
 * Where in the process material was lost: either one of the built-ins below or
 * the id of a kind the plant added itself (see `WasteType`). The backend refuses
 * a line filed under a kind the report does not have, so a daily report never
 * carries a packing stage.
 *
 * A string, not a union, because the plant's own ids are not known at compile
 * time. Use `useWasteTypes().label(category)` to show one — never the raw value.
 */
export type WasteCategory = string;

/**
 * The built-in kinds, by the report they are entered on. `raw_material`, `press`,
 * `pouring`, `cross`, `kneading` and `finished_product_conditioning` belong to
 * the daily report, `product` and `packaging` to the packing report. Their names
 * are translated; a plant's own kinds carry the name its administrator typed.
 */
export const BUILT_IN_WASTE_CATEGORIES = {
  daily: ["raw_material", "press", "pouring", "cross", "kneading", "finished_product_conditioning"],
  conditionnement: ["product", "packaging"],
} as const satisfies Record<ReportType, readonly string[]>;

/** A déchet kind a plant defined for itself, entered on one report. */
export interface WasteType {
  /** What a line stores as its category. */
  id: string;
  name: string;
  report_type: ReportType;
  sort_order: number;
  /** A retired kind is no longer offered on a new line but still explains old ones. */
  is_active: boolean;
}

export function listWasteTypes(token: string) {
  return apiFetch<WasteType[]>("/production/waste-types", { token });
}

export function createWasteType(token: string, input: { name: string; report_type: ReportType; sort_order?: number }) {
  return apiFetch<WasteType>("/production/waste-types", { method: "POST", token, body: input });
}

export function updateWasteType(
  token: string,
  wasteTypeId: string,
  input: { name?: string; sort_order?: number; is_active?: boolean },
) {
  return apiFetch<WasteType>(`/production/waste-types/${wasteTypeId}`, { method: "PATCH", token, body: input });
}

export type DaySheetSection = "material" | "production" | "waste" | "packing" | "energy";

/** One row of the day sheet. The fixed rows are named by `key`; the ones that exist once per product or déchet kind carry `ref`/`name`. */
export interface DaySheetRow {
  section: DaySheetSection;
  key: string;
  /** A product id, or a déchet category, for the rows that exist once per item. */
  ref: string | null;
  name: string | null;
  unit: string | null;
  /** A shift with no report is absent, which is not the same as 0. */
  by_column: Record<string, number>;
  total: number | null;
}

export interface DaySheetColumn {
  /** The shift as filed (empty for reports filed with none) on a day sheet; the product's id on the month recap. */
  key: string;
  /** The recap's column title, the product's name. */
  name?: string | null;
  teams: string[];
  lots: string[];
  reports: Record<ReportType, { validated: number; pending: number }>;
}

export interface DaySheet {
  date: string;
  work_center: { id: string; code: string; name: string };
  include_pending: boolean;
  columns: DaySheetColumn[];
  rows: DaySheetRow[];
  ofs: { id: string; reference: string | null; product_name: string | null }[];
}

/** The same rows as a day sheet, added up over a month, with a column per product. */
export interface MonthRecap {
  month: string;
  work_center: { id: string; code: string; name: string };
  columns: DaySheetColumn[];
  rows: DaySheetRow[];
}

export function getDaySheet(token: string, params: { date: string; workCenterId: string; includePending: boolean }) {
  const query = new URLSearchParams({
    date: params.date,
    work_center_id: params.workCenterId,
    include_pending: String(params.includePending),
  });
  return apiFetch<DaySheet>(`/production/day-sheet?${query}`, { token });
}

/** The lot a packing report is most likely to carry, and the earlier lot it is counted on from. */
export interface LotSuggestion {
  lot_number: string | null;
  based_on: { lot_number: string; report_date: string } | null;
}

export function getLotSuggestion(token: string, params: { workCenterId: string; reportDate: string }) {
  const query = new URLSearchParams({ work_center_id: params.workCenterId, report_date: params.reportDate });
  return apiFetch<LotSuggestion>(`/production/lot-suggestion?${query}`, { token });
}

export function getMonthRecap(token: string, params: { month: string; workCenterId: string }) {
  const query = new URLSearchParams({ month: params.month, work_center_id: params.workCenterId });
  return apiFetch<MonthRecap>(`/production/month-recap?${query}`, { token });
}

export interface WasteLine {
  category: WasteCategory;
  /**
   * The item lost. Optional while a draft is being typed, required to submit —
   * without it the quantity has no unit and no one can read it.
   */
  product_id: string | null;
  quantity: number;
  note: string | null;
}

export interface SemolinaLine {
  /** The quality poured. Optional while a draft is being typed, required to submit. */
  product_id: string | null;
  quantity: number;
  /** Its own store — unlike rebroyat, different qualities are routinely kept in different silos. */
  location_id: string | null;
}

export interface DowntimeLine {
  /** The stated cause. Optional while a draft is being typed, required to submit if minutes > 0. */
  motif: string | null;
  /** What kind of intervention this was (préventive, corrective, ...). */
  downtime_type: string | null;
  /** Which system it hit (pneumatique, électrique, ...). */
  classification: string | null;
  minutes: number;
  note: string | null;
}

export interface DailyReportDetail {
  dough_quantity: number;
  // Recorded for yield and consolidation; it posts no stock.
  finished_product_quantity: number;
  regrind_quantity: number;
  water_quantity: number;
  // Water dosed as a percentage of the semoule poured — the operator's real
  // input; water_quantity is derived from it and kept in sync by the form.
  water_percentage: number;
  fuel_quantity: number;
  // Which fournisseur this shift's fioul came from — informational only, since
  // fuel is never posted to stock and more than one supplier can deliver it.
  fuel_supplier_id: string | null;
  // Gasoil (diesel) — a separate fuel from fuel_quantity (fioul). Derived from
  // gasoil_flow_rate x generator_hours, the same way water_quantity is derived
  // from water_percentage.
  gasoil_quantity: number;
  gasoil_supplier_id: string | null;
  // Groupe électrogène consumption rate (L/h) and hours run this shift — the
  // operator's real inputs; gasoil_quantity is their product.
  gasoil_flow_rate: number;
  generator_hours: number;
  electricity_quantity: number;
  // Débit de semoule, tonnes/hour. Recorded for future recipe statistics only.
  semolina_flow_rate: number;
  start_time: string | null;
  end_time: string | null;
  production_minutes: number;
  // Arrêts, one line per stoppage — a shift may stop more than once, for more
  // than one reason.
  downtime_lines: DowntimeLine[];
  // Semoule poured this shift, one line per quality. Required before the report
  // can be submitted if a line's quantity is above zero.
  semolina_lines: SemolinaLine[];
  // Rebroyat's own store — kept separate from the semoule lines' locations.
  raw_material_location_id: string | null;
  // Rebroyat poured back into the mix — deducted from stock like semolina.
  regrind_input_quantity: number;
  regrind_input_product_id: string | null;
  // What this shift's rebroyat *is*: the item its scrap record and regrind OF
  // are opened against, and what gives the figure a unit.
  regrind_product_id: string | null;
  // Which mold this shift ran — named per report, not on the OF.
  mold_id: string | null;
  // Déchets. Records what was lost; moves no stock, because the material left
  // stock when it was poured or consumed.
  waste_lines: WasteLine[];
}

export interface ConditionnementReportDetail {
  /**
   * Phase 9, decision 17: the tonnage off the scale, in tonnes. Feeds yield and
   * consolidation; moves no stock on its own.
   */
  finished_product_quantity: number;
  /**
   * What the line tallied, in the product's own unit. Decision 18: this is what
   * validation posts into the finished-goods store — never the packet count
   * derived from the tonnage, or stock would always be the estimate and the
   * écart could never appear in it.
   */
  packets_counted: number;
  film_quantity: number;
  carton_quantity: number;
  /**
   * Part of carton_quantity that held no sellable product — empty or damaged
   * cartons the line still built and counted, but never filled. Subtracted
   * from carton_quantity wherever that count feeds finished-goods stock or
   * the packaging écart, so it is never read back as unaccounted product.
   */
  waste_carton_quantity: number;
  /** @deprecated superseded by scotch_quantity/ruban_quantity */
  tape_quantity: number;
  scotch_quantity: number;
  ruban_quantity: number;
  machine_speed: number | null;
  production_minutes: number;
  downtime_minutes: number;
  downtime_reason: string | null;
  downtime_note: string | null;
  lot_number: string | null;
  dlc_date: string | null;
  film_product_id: string | null;
  carton_product_id: string | null;
  /** @deprecated superseded by scotch_product_id/ruban_product_id */
  tape_product_id: string | null;
  scotch_product_id: string | null;
  ruban_product_id: string | null;
  // Which fournisseur each packaging item came from — informational only, since
  // more than one supplier can deliver film, carton, scotch or ruban.
  film_supplier_id: string | null;
  carton_supplier_id: string | null;
  /** @deprecated superseded by scotch_supplier_id/ruban_supplier_id */
  tape_supplier_id: string | null;
  scotch_supplier_id: string | null;
  ruban_supplier_id: string | null;
  packaging_location_id: string | null;
  // The finished product itself is the OF's product and is not restated here.
  finished_goods_location_id: string | null;
  // The daily report whose output this run packaged. Optional -- a team may
  // file conditionnement before that day's daily report exists, or package
  // previously stored product with no same-shift daily report at all. Powers
  // qc's inspection hint (packets/cartons/regrind) rather than gating stock.
  daily_report_id: string | null;
  waste_lines: WasteLine[];
}

export interface ProductionReportWithDetail extends ProductionReport {
  detail: DailyReportDetail | ConditionnementReportDetail | null;
}

export interface CreateDailyReportInput {
  of_id: string;
  report_date: string;
  team?: string;
  work_center_id?: string;
  equipment_id?: string;
  shift?: string;
  detail?: Partial<DailyReportDetail>;
}

export function listReports(
  token: string,
  params: { of_id?: string; status?: ReportStatus; report_type?: ReportType } = {},
) {
  const query = new URLSearchParams();
  if (params.of_id) query.set("of_id", params.of_id);
  if (params.status) query.set("status", params.status);
  if (params.report_type) query.set("report_type", params.report_type);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<ProductionReport[]>(`/production/reports${suffix}`, { token });
}

export function getReport(token: string, reportId: string) {
  return apiFetch<ProductionReportWithDetail>(`/production/reports/${reportId}`, { token });
}

export function createDailyReport(token: string, input: CreateDailyReportInput) {
  return apiFetch<ProductionReportWithDetail>("/production/reports/daily", { method: "POST", token, body: input });
}

export function updateDailyReport(token: string, reportId: string, detail: Partial<DailyReportDetail>) {
  return apiFetch<ProductionReportWithDetail>(`/production/reports/daily/${reportId}`, {
    method: "PATCH",
    token,
    body: { detail },
  });
}

export interface CreateConditionnementReportInput {
  of_id: string;
  report_date: string;
  team?: string;
  work_center_id?: string;
  equipment_id?: string;
  shift?: string;
  // Only required when the order has no product yet — its first packaging
  // report is what names one.
  product_id?: string;
  detail?: Partial<ConditionnementReportDetail>;
}

export function createConditionnementReport(token: string, input: CreateConditionnementReportInput) {
  return apiFetch<ProductionReportWithDetail>("/production/reports/conditionnement", {
    method: "POST",
    token,
    body: input,
  });
}

export function updateConditionnementReport(
  token: string,
  reportId: string,
  detail: Partial<ConditionnementReportDetail>,
) {
  return apiFetch<ProductionReportWithDetail>(`/production/reports/conditionnement/${reportId}`, {
    method: "PATCH",
    token,
    body: { detail },
  });
}

export function correctConditionnementReport(
  token: string,
  reportId: string,
  detail: Partial<ConditionnementReportDetail>,
  reason: string,
) {
  return apiFetch<ProductionReportWithDetail>(`/production/reports/conditionnement/${reportId}/correct`, {
    method: "PATCH",
    token,
    body: { detail, reason },
  });
}

// submit / validate / reject / revise are shared by both report types — the
// header machinery does not care which detail table the figures live in.
export function submitReport(token: string, reportId: string) {
  return apiFetch<ProductionReport>(`/production/reports/${reportId}/submit`, { method: "POST", token });
}

// Needs production.admin_reports — the right to change the team's figures, which
// is deliberately not the same as the right to approve them.
export function correctDailyReport(
  token: string,
  reportId: string,
  detail: Partial<DailyReportDetail>,
  reason: string,
) {
  return apiFetch<ProductionReportWithDetail>(`/production/reports/daily/${reportId}/correct`, {
    method: "PATCH",
    token,
    body: { detail, reason },
  });
}

// Validation is what posts stock. A report that consumes more than the stock
// figure holds still posts — that is deliberate — but needs a comment explaining
// why, or the call is refused with SHORTFALL_COMMENT_REQUIRED.
export function validateReport(
  token: string,
  reportId: string,
  options: { correlationId?: string; shortfallComment?: string; regrindWorkCenterId?: string } = {},
) {
  return apiFetch<ProductionReport>(`/production/reports/${reportId}/validate`, {
    method: "POST",
    token,
    body: {
      correlation_id: options.correlationId,
      shortfall_comment: options.shortfallComment,
      regrind_work_center_id: options.regrindWorkCenterId,
    },
  });
}

// --- Regrind defaults -------------------------------------------------------
//
// Which product the regrind of a given input yields. Without one configured, a
// daily report carrying rebroyat cannot be validated.

export interface RegrindDefault {
  input_product_id: string | null;
  output_product_id: string;
}

export function listRegrindDefaults(token: string) {
  return apiFetch<RegrindDefault[]>("/production/regrind-defaults", { token });
}

export function setRegrindDefault(token: string, outputProductId: string, inputProductId?: string) {
  return apiFetch<RegrindDefault>("/production/regrind-defaults", {
    method: "PUT",
    token,
    body: { output_product_id: outputProductId, input_product_id: inputProductId },
  });
}

export function rejectReport(token: string, reportId: string, reason: string) {
  return apiFetch<ProductionReport>(`/production/reports/${reportId}/reject`, {
    method: "POST",
    token,
    body: { reason },
  });
}

// A validated report has moved stock, so deleting it reverses those movements
// first. Needs production.admin_reports, and a reason that lands in the audit log.
// `force` pushes past a REGRIND_ALREADY_COMPLETED refusal: it also reverses the
// regrind order's stock receipt and removes the order along with the report.
export function deleteReport(token: string, reportId: string, reason: string, force = false) {
  return apiFetch<{ deleted: string }>(`/production/reports/${reportId}`, {
    method: "DELETE",
    token,
    body: { reason, force },
  });
}

// Correcting an already-validated report: the old movements are reversed and the
// new ones posted, so inventory always matches the figures that justify it.
export function correctValidatedDailyReport(
  token: string,
  reportId: string,
  detail: Partial<DailyReportDetail>,
  reason: string,
  force = false,
) {
  return apiFetch<ProductionReportWithDetail>(`/production/reports/daily/${reportId}/correct-validated`, {
    method: "PATCH",
    token,
    body: { detail, reason, force },
  });
}

export function correctValidatedConditionnementReport(
  token: string,
  reportId: string,
  detail: Partial<ConditionnementReportDetail>,
  reason: string,
) {
  return apiFetch<ProductionReportWithDetail>(
    `/production/reports/conditionnement/${reportId}/correct-validated`,
    { method: "PATCH", token, body: { detail, reason } },
  );
}

export function reviseReport(token: string, reportId: string) {
  return apiFetch<ProductionReport>(`/production/reports/${reportId}/revise`, { method: "POST", token });
}

// --- Packaging reconciliation (Phase 9) --------------------------------------

/**
 * One écart. Every term it was computed from travels with the answer, because a
 * variance nobody can decompose is a variance nobody will act on: "−412 packets"
 * needs the net weight beside it before anyone can tell a lost pallet from a
 * mistyped tonnage.
 *
 * `null` figures are honest gaps, not zeroes — without a net weight there is no
 * way to turn a weight into a count, and `missing` says which parameter is absent.
 */
export interface PackagingVariance {
  /**
   * How the product is sold (`sac` counts sacs, not packets, and has no carton
   * tier). `null`/absent when the product is unclassified — per-report rows
   * inside a product summary omit it.
   */
  packaging_format?: PackagingFormat | null;
  /**
   * Decision 25: no longer entered on the packing report. Comes from the OF's
   * own daily reports at OF/product scope, and is always `null` for a single
   * report — it has no natural share of an OF's tonnage to compare against.
   */
  tonnage: number | null;
  net_weight_grams: number | null;
  packets_per_carton: number | null;
  expected_packets: number | null;
  expected_cartons: number | null;
  counted_packets: number;
  counted_cartons: number;
  /** What quality has taken off the market and not given back (decision 21). */
  rejected_packets: number;
  /** The part of that still awaiting a disposition — shown so an open case does not read as a loss. */
  undecided_packets: number;
  good_packets: number;
  /**
   * Cartons the line counted that never held product — empty or damaged,
   * still swept into `counted_cartons`. Distinct from `rejected_packets`: a
   * rejected packet was real product in a real carton the line still built;
   * a waste carton was never real product at all.
   */
  waste_cartons: number;
  good_cartons: number;
  /** actual − expected, so short reads negative. */
  packet_variance: number | null;
  packet_variance_ratio: number | null;
  /** Judged against `good_cartons` (counted less `waste_cartons`), never the raw physical tally. */
  carton_variance: number | null;
  carton_variance_ratio: number | null;
  /**
   * The machine's own tally against what the floor physically boxed:
   * `counted_packets - (good_cartons * packets_per_carton)`. Independent of
   * the weight-based figures above — this catches an HMI miscount or a carton
   * closed short even when the scale is right. `null` for a product with no
   * carton tier (a sac counted directly).
   */
  machine_carton_variance: number | null;
  machine_carton_variance_ratio: number | null;
  tolerance_percent: number | null;
  within_tolerance: boolean | null;
  missing: string[];
}

export interface ReportPackagingVariance extends PackagingVariance {
  scope: "report";
  report_id: string;
  of_id: string;
  of_reference: string;
  product_id: string;
  report_date: string;
  report_status: ReportStatus;
  /** False while the report is unvalidated: the figure moves if the product is edited. */
  parameters_frozen: boolean;
}

export interface WorkOrderPackagingVariance extends PackagingVariance {
  scope: "work_order";
  of_id: string;
  of_reference: string;
  product_id: string;
  report_count: number;
  /** True when the OF's reports were frozen against different parameters. */
  parameters_varied: boolean;
  quality_available: boolean;
}

/** An order whose validated packing reports cover several products: one breakdown per product, no order-wide figure. */
export interface MultiProductOrderVariance {
  scope: "work_order";
  multi_product: true;
  of_id: string;
  of_reference: string;
  products: ProductPackagingVariance[];
}

export interface ProductPackagingVariance extends PackagingVariance {
  scope: "product";
  product_id: string;
  of_count: number;
  report_count: number;
  quality_available: boolean;
  /** Per-report rows, each with its own date. Gross: quality attaches to an OF, not a date. */
  reports: (PackagingVariance & {
    report_id: string;
    of_id: string;
    of_reference: string;
    report_date: string;
  })[];
}

/** Écart de conditionnement — the scale against the counter, no quality adjustment. */
export function getReportPackagingVariance(token: string, reportId: string) {
  return apiFetch<ReportPackagingVariance>(`/production/reports/${reportId}/packaging-variance`, { token });
}

/** Écart net — the same, less what quality pulled. */
export function getWorkOrderPackagingVariance(token: string, workOrderId: string) {
  return apiFetch<WorkOrderPackagingVariance | MultiProductOrderVariance>(
    `/production/work-orders/${workOrderId}/packaging-variance`,
    { token },
  );
}

export function listPackagingVariance(token: string, params: { date_from?: string; date_to?: string } = {}) {
  const query = new URLSearchParams();
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<ProductPackagingVariance[]>(`/production/packaging-variance${suffix}`, { token });
}

export interface PackagingTolerance {
  /** Null is the tenant-wide default row. */
  product_id: string | null;
  tolerance_percent: number;
}

export function listPackagingTolerances(token: string) {
  return apiFetch<PackagingTolerance[]>("/production/packaging-tolerances", { token });
}

export function setPackagingTolerance(token: string, input: PackagingTolerance) {
  return apiFetch<PackagingTolerance>("/production/packaging-tolerances", {
    method: "PUT",
    token,
    body: input,
  });
}

// --- Validator edit --------------------------------------------------------

export function saveValidatorEditSection(token: string, shiftReportId: string, sectionKey: string, payload: Record<string, unknown>, reason?: string) {
  return apiFetch(`/production/shift-reports/${shiftReportId}/sections/${sectionKey}/validator-edit`, {
    method: "PUT",
    token,
    body: { payload, reason },
  });
}
