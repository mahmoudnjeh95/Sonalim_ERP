import { apiFetch } from "../../lib/api";

// --- Products & units of measure -----------------------------------------

export interface Product {
  id: string;
  sku: string;
  name: string;
  uom_id: string;
  net_weight_grams: number | null;
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
export type PackagingFormat = "packet" | "carton";

export interface ProductClassification {
  product_id: string;
  category: ProductCategory;
  is_regrind: boolean;
  packaging_format: PackagingFormat | null;
  is_water: boolean;
}

export interface SetClassificationInput {
  product_id: string;
  category: ProductCategory;
  is_regrind: boolean;
  packaging_format?: PackagingFormat;
  is_water?: boolean;
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

export type WorkOrderStatus = "draft" | "in_progress" | "completed";

export interface WorkOrder {
  id: string;
  reference: string;
  product_id: string;
  quantity: number;
  status: WorkOrderStatus;
  work_center_id: string | null;
  recipe_id: string | null;
  packaging_bom_id: string | null;
  actual_output_quantity: number | null;
}

export interface PouredInputInput {
  productId: string;
  quantity: number;
}

export interface CreateWorkOrderInput {
  product_id: string;
  quantity: number;
  work_center_id?: string;
  recipe_id?: string;
  pouredInputs?: PouredInputInput[];
  pouredInputsLocationId?: string;
}

export interface UpdateWorkOrderInput {
  quantity?: number;
  work_center_id?: string;
  recipe_id?: string;
  packaging_bom_id?: string;
}

export function listWorkOrders(token: string) {
  return apiFetch<WorkOrder[]>("/production/work-orders", { token });
}

export function createWorkOrder(token: string, input: CreateWorkOrderInput) {
  return apiFetch<WorkOrder>("/production/work-orders", {
    method: "POST",
    token,
    body: {
      product_id: input.product_id,
      quantity: input.quantity,
      work_center_id: input.work_center_id,
      recipe_id: input.recipe_id,
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

export interface MaterialUsedInput {
  product_id: string;
  quantity: number;
}

export interface ScrapEntryInput {
  scrapType: ScrapType;
  productId: string;
  quantity: number;
}

export interface CompleteWorkOrderInput {
  correlationId: string;
  locationId: string;
  actualOutputQuantity?: number;
  materialsUsed?: MaterialUsedInput[];
  materialsLocationId?: string;
  scrapEntries?: ScrapEntryInput[];
}

export function completeWorkOrder(token: string, workOrderId: string, input: CompleteWorkOrderInput) {
  return apiFetch<WorkOrder>(`/production/work-orders/${workOrderId}/complete`, {
    method: "POST",
    token,
    body: {
      correlation_id: input.correlationId,
      location_id: input.locationId,
      actual_output_quantity: input.actualOutputQuantity,
      materials_used: input.materialsUsed ?? [],
      materials_location_id: input.materialsLocationId,
      scrap_entries: (input.scrapEntries ?? []).map((e) => ({
        scrap_type: e.scrapType,
        product_id: e.productId,
        quantity: e.quantity,
      })),
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

export type MachineStatus = "operational" | "down" | "maintenance";

export interface Machine {
  id: string;
  work_center_id: string;
  code: string;
  name: string;
  status: MachineStatus;
}

export interface CreateMachineInput {
  work_center_id: string;
  code: string;
  name: string;
}

export interface UpdateMachineInput {
  work_center_id?: string;
  code?: string;
  name?: string;
}

export function listMachines(token: string) {
  return apiFetch<Machine[]>("/production/machines", { token });
}

export function createMachine(token: string, input: CreateMachineInput) {
  return apiFetch<Machine>("/production/machines", { method: "POST", token, body: input });
}

export function updateMachine(token: string, machineId: string, input: UpdateMachineInput) {
  return apiFetch<Machine>(`/production/machines/${machineId}`, { method: "PATCH", token, body: input });
}

export function setMachineStatus(token: string, machineId: string, status: MachineStatus) {
  return apiFetch<Machine>(`/production/machines/${machineId}/status`, { method: "POST", token, body: { status } });
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

export type ScrapType = "filling_dosing" | "cutting";

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
}

export interface RecordScrapInput {
  scrap_type: ScrapType;
  product_id: string;
  quantity: number;
  work_order_id?: string;
  work_center_id?: string;
  source_note?: string;
}

export interface RegrindBatch {
  work_order: WorkOrder;
  scrap_record_ids: string[];
  input_quantity_total: number;
  loss_quantity: number;
}

export interface RegrindBatchSummary {
  work_order_id: string;
  output_product_id: string;
  output_quantity: number;
  status: WorkOrderStatus;
  work_center_id: string | null;
  input_quantity_total: number;
  loss_quantity: number;
  created_at: string;
}

export interface CreateRegrindBatchInput {
  scrap_record_ids: string[];
  output_product_id: string;
  output_quantity: number;
  work_center_id?: string;
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

export function listRegrindBatches(token: string) {
  return apiFetch<RegrindBatchSummary[]>("/production/regrind-batches", { token });
}

// --- Daily resource consumption (electricity, fuel, ...) -------------------

export interface ResourceType {
  id: string;
  code: string;
  name: string;
  unit: string;
}

export interface CreateResourceTypeInput {
  code: string;
  name: string;
  unit: string;
}

export interface UpdateResourceTypeInput {
  code?: string;
  name?: string;
  unit?: string;
}

export interface DailyConsumption {
  id: string;
  consumption_date: string;
  resource_type_id: string;
  quantity: number;
  note: string | null;
}

export interface RecordDailyConsumptionInput {
  consumption_date: string;
  resource_type_id: string;
  quantity: number;
  note?: string;
}

export function listResourceTypes(token: string) {
  return apiFetch<ResourceType[]>("/production/resource-types", { token });
}

export function createResourceType(token: string, input: CreateResourceTypeInput) {
  return apiFetch<ResourceType>("/production/resource-types", { method: "POST", token, body: input });
}

export function updateResourceType(token: string, resourceTypeId: string, input: UpdateResourceTypeInput) {
  return apiFetch<ResourceType>(`/production/resource-types/${resourceTypeId}`, { method: "PATCH", token, body: input });
}

export function listDailyConsumption(token: string, params: { date_from?: string; date_to?: string } = {}) {
  const query = new URLSearchParams();
  if (params.date_from) query.set("date_from", params.date_from);
  if (params.date_to) query.set("date_to", params.date_to);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch<DailyConsumption[]>(`/production/daily-consumption${suffix}`, { token });
}

export function recordDailyConsumption(token: string, input: RecordDailyConsumptionInput) {
  return apiFetch<DailyConsumption>("/production/daily-consumption", { method: "POST", token, body: input });
}

// --- Rendement (yield) ------------------------------------------------------

export interface WorkOrderYield {
  work_order_id: string;
  actual_output_quantity: number;
  rebroyat_quantity: number;
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

export function getWorkOrderYield(token: string, workOrderId: string) {
  return apiFetch<WorkOrderYield>(`/production/work-orders/${workOrderId}/yield`, { token });
}

export function getRecipeYieldSummary(token: string, recipeId: string) {
  return apiFetch<RecipeYieldSummary>(`/production/recipes/${recipeId}/yield-summary`, { token });
}

// --- Per-OF utility consumption (fuel, scotch, film, ...) -------------------

export interface WorkOrderConsumptionEntry {
  id: string;
  work_order_id: string;
  resource_type_id: string;
  quantity: number;
  note: string | null;
}

export interface RecordWorkOrderConsumptionInput {
  resource_type_id: string;
  quantity: number;
  note?: string;
}

export function listWorkOrderConsumption(token: string, workOrderId: string) {
  return apiFetch<WorkOrderConsumptionEntry[]>(`/production/work-orders/${workOrderId}/consumption`, { token });
}

export function recordWorkOrderConsumption(token: string, workOrderId: string, input: RecordWorkOrderConsumptionInput) {
  return apiFetch<WorkOrderConsumptionEntry>(`/production/work-orders/${workOrderId}/consumption`, {
    method: "POST",
    token,
    body: input,
  });
}
