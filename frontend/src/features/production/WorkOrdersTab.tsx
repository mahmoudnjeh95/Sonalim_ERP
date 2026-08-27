import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useFieldArray, useForm, type UseFormReturn } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, ClipboardList, PlayCircle, Plus, Pencil, Timer, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { Skeleton } from "../../components/ui/skeleton";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "../../components/ui/dialog";
import {
  completeWorkOrder,
  createWorkOrder,
  listClassifications,
  listPackagingBoms,
  listProducts,
  listRecipes,
  listResourceTypes,
  listWorkCenters,
  listWorkOrderInputs,
  listWorkOrderYields,
  listWorkOrders,
  listRegrindBatches,
  recordWorkOrderConsumption,
  startWorkOrder,
  updateWorkOrder,
  type CompleteWorkOrderInput,
  type PackagingBom,
  type Product,
  type Recipe,
  type RecordWorkOrderConsumptionInput,
  type ResourceType,
  type UpdateWorkOrderInput,
  type WorkCenter,
  type WorkOrder,
  type WorkOrderStatus,
} from "./api";
import { listLocations, type Location } from "../warehouse/api";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { cn } from "../../lib/utils";

const pouredInputSchema = z.object({
  product_id: z.string().min(1, "Required"),
  quantity: z.coerce.number().positive("Must be > 0"),
});
const newOrderSchema = z
  .object({
    product_id: z.string().min(1, "Required"),
    quantity: z.coerce.number().positive("Must be > 0"),
    work_center_id: z.string().optional(),
    recipe_id: z.string().optional(),
    poured_inputs: z.array(pouredInputSchema).default([]),
    poured_inputs_location_id: z.string().optional(),
  })
  .refine((data) => data.poured_inputs.length === 0 || !!data.poured_inputs_location_id, {
    message: "Required when raw materials are poured",
    path: ["poured_inputs_location_id"],
  });
type NewOrderForm = z.infer<typeof newOrderSchema>;

const editOrderSchema = z.object({
  quantity: z.coerce.number().positive("Must be > 0"),
  work_center_id: z.string().optional(),
  recipe_id: z.string().optional(),
  packaging_bom_id: z.string().optional(),
});
type EditOrderForm = z.infer<typeof editOrderSchema>;

const materialUsedSchema = z.object({
  product_id: z.string().min(1, "Required"),
  quantity: z.coerce.number().positive("Must be > 0"),
});
const consumptionEntrySchema = z.object({
  resource_type_id: z.string().min(1, "Required"),
  quantity: z.coerce.number().min(0),
  note: z.string().optional(),
});
const completeSchema = z.object({
  location_id: z.string().min(1, "Required"),
  actual_output_quantity: z.coerce.number().positive("Must be > 0"),
  materials_location_id: z.string().optional(),
  materials: z.array(materialUsedSchema),
  versement_quantity: z.coerce.number().min(0).optional(),
  versement_product_id: z.string().optional(),
  decoupe_quantity: z.coerce.number().min(0).optional(),
  decoupe_product_id: z.string().optional(),
  consumption: z.array(consumptionEntrySchema).default([]),
});
type CompleteForm = z.infer<typeof completeSchema>;

const PROGRESS: Record<WorkOrderStatus, number> = { draft: 8, in_progress: 55, completed: 100 };
const QUERY_KEY = ["production", "work-orders"] as const;
const WORK_CENTERS_QUERY_KEY = ["production", "work-centers"] as const;
const RECIPES_QUERY_KEY = ["production", "recipes"] as const;
const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const CLASSIFICATIONS_QUERY_KEY = ["production", "product-classifications"] as const;
const PACKAGING_BOMS_QUERY_KEY = ["production", "packaging-boms"] as const;
const YIELDS_QUERY_KEY = ["production", "work-order-yields"] as const;
const RESOURCE_TYPES_QUERY_KEY = ["production", "resource-types"] as const;
const REGRIND_BATCHES_QUERY_KEY = ["production", "regrind-batches"] as const;
type StatusFilter = "all" | WorkOrderStatus;

export function WorkOrdersTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [completingId, setCompletingId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [productManual, setProductManual] = useState(false);

  const { data: orders = [], isLoading } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => listWorkOrders(token),
  });
  const { data: workCenters = [] } = useQuery({ queryKey: WORK_CENTERS_QUERY_KEY, queryFn: () => listWorkCenters(token) });
  const { data: recipes = [] } = useQuery({ queryKey: RECIPES_QUERY_KEY, queryFn: () => listRecipes(token) });
  const { data: locations = [] } = useQuery({ queryKey: LOCATIONS_QUERY_KEY, queryFn: () => listLocations(token) });
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: classifications = [] } = useQuery({ queryKey: CLASSIFICATIONS_QUERY_KEY, queryFn: () => listClassifications(token) });
  const { data: packagingBoms = [] } = useQuery({ queryKey: PACKAGING_BOMS_QUERY_KEY, queryFn: () => listPackagingBoms(token) });
  const { data: workOrderYields = [] } = useQuery({ queryKey: YIELDS_QUERY_KEY, queryFn: () => listWorkOrderYields(token) });
  const { data: resourceTypes = [] } = useQuery({ queryKey: RESOURCE_TYPES_QUERY_KEY, queryFn: () => listResourceTypes(token) });
  const { data: regrindBatches = [] } = useQuery({ queryKey: REGRIND_BATCHES_QUERY_KEY, queryFn: () => listRegrindBatches(token) });
  const regrindWorkOrderIds = new Set(regrindBatches.map((b) => b.work_order_id));
  const yieldByWorkOrderId = new Map(workOrderYields.map((y) => [y.work_order_id, y.yield_ratio]));
  const activeRecipes = recipes.filter((r) => r.status === "active");
  // Classifications key products by sku (production.product_classifications is
  // independent of core.products), but the pickers below submit product.id since
  // that's what warehouse stock operations (issue/receive) require — so match
  // classification.product_id against product.sku, not product.id.
  const finishedGoodIds = new Set(classifications.filter((c) => c.category === "finished_good").map((c) => c.product_id));
  const rawMaterialIds = new Set(classifications.filter((c) => c.category === "raw_material").map((c) => c.product_id));
  const finishedGoodProducts = products.filter((p) => finishedGoodIds.has(p.sku));
  const rawMaterialProducts = products.filter((p) => rawMaterialIds.has(p.sku));

  const {
    register,
    control,
    handleSubmit,
    watch,
    setValue,
    reset,
    formState: { errors },
  } = useForm<NewOrderForm>({
    resolver: zodResolver(newOrderSchema),
    defaultValues: { product_id: "", quantity: undefined, work_center_id: "", recipe_id: "", poured_inputs: [], poured_inputs_location_id: "" },
  });
  const { fields: pouredInputFields, append: appendPouredInput, remove: removePouredInput, replace: replacePouredInputs } = useFieldArray({
    control,
    name: "poured_inputs",
  });
  const selectedRecipeId = watch("recipe_id");
  const selectedRecipe = selectedRecipeId ? recipes.find((r) => r.id === selectedRecipeId) : undefined;

  function onRecipeChange(recipeId: string) {
    setValue("recipe_id", recipeId);
    const recipe = recipeId ? recipes.find((r) => r.id === recipeId) : undefined;
    if (!recipe) return;
    // Pre-seed one poured-input line per recipe component (matched by sku, same
    // convention as the classification lookups above) so the operator only has to
    // type real tonnage rather than adding every line by hand.
    replacePouredInputs(
      recipe.lines.map((line) => {
        const product = products.find((p) => p.id === line.component_product_id);
        return { product_id: product?.id ?? line.component_product_id, quantity: 0 };
      }),
    );
  }

  const createMutation = useMutation({
    mutationFn: (input: NewOrderForm) =>
      createWorkOrder(token, {
        ...input,
        work_center_id: input.work_center_id || undefined,
        recipe_id: input.recipe_id || undefined,
        pouredInputs: input.poured_inputs.filter((i) => i.product_id && i.quantity > 0).map((i) => ({ productId: i.product_id, quantity: i.quantity })),
        pouredInputsLocationId: input.poured_inputs_location_id || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock"] });
      setDialogOpen(false);
      setProductManual(false);
      reset({ product_id: "", quantity: undefined, work_center_id: "", recipe_id: "", poured_inputs: [], poured_inputs_location_id: "" });
      toast.success(t("production.workOrders.created"));
    },
    onError: (error) => {
      toast.error(t("production.workOrders.createError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const startMutation = useMutation({
    mutationFn: (id: string) => startWorkOrder(token, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      toast.success(t("production.workOrders.started"));
    },
    onError: (error) => {
      toast.error(t("production.workOrders.startError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const editForm = useForm<EditOrderForm>({ resolver: zodResolver(editOrderSchema) });

  const updateMutation = useMutation({
    mutationFn: ({ id, input }: { id: string; input: UpdateWorkOrderInput }) => updateWorkOrder(token, id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setEditingId(null);
      editForm.reset();
      toast.success(t("production.workOrders.updated"));
    },
    onError: (error) => {
      toast.error(t("production.workOrders.updateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  function openEditDialog(order: WorkOrder | null) {
    if (!order) {
      setEditingId(null);
      return;
    }
    setEditingId(order.id);
    editForm.reset({
      quantity: order.quantity,
      work_center_id: order.work_center_id ?? "",
      recipe_id: order.recipe_id ?? "",
      packaging_bom_id: order.packaging_bom_id ?? "",
    });
  }

  function submitEdit(order: WorkOrder, input: EditOrderForm) {
    updateMutation.mutate({
      id: order.id,
      input: {
        quantity: input.quantity,
        work_center_id: input.work_center_id || undefined,
        recipe_id: input.recipe_id || undefined,
        packaging_bom_id: input.packaging_bom_id || undefined,
      },
    });
  }

  const completeForm = useForm<CompleteForm>({
    resolver: zodResolver(completeSchema),
    defaultValues: {
      location_id: "",
      actual_output_quantity: undefined,
      materials_location_id: "",
      materials: [],
      versement_quantity: 0,
      versement_product_id: "",
      decoupe_quantity: 0,
      decoupe_product_id: "",
      consumption: [],
    },
  });

  function resetCompleteForm() {
    completeForm.reset({
      location_id: "",
      actual_output_quantity: undefined,
      materials_location_id: "",
      materials: [],
      versement_quantity: 0,
      versement_product_id: "",
      decoupe_quantity: 0,
      decoupe_product_id: "",
      consumption: [],
    });
  }

  const completeMutation = useMutation({
    mutationFn: async ({
      id,
      input,
      consumptionEntries,
    }: {
      id: string;
      input: CompleteWorkOrderInput;
      consumptionEntries: RecordWorkOrderConsumptionInput[];
    }) => {
      const result = await completeWorkOrder(token, id, input);
      for (const entry of consumptionEntries) {
        await recordWorkOrderConsumption(token, id, entry);
      }
      return result;
    },
    onSuccess: (_result, { id }) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock"] });
      queryClient.invalidateQueries({ queryKey: ["production", "scrap-records"] });
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock", "moves"] });
      queryClient.invalidateQueries({ queryKey: YIELDS_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["production", "work-order-inputs", id] });
      queryClient.invalidateQueries({ queryKey: ["production", "work-order-consumption", id] });
      queryClient.invalidateQueries({ queryKey: ["production", "recipe-yield-summary"] });
      setCompletingId(null);
      resetCompleteForm();
      toast.success(t("production.workOrders.completedToast"));
    },
    onError: (error) => {
      toast.error(t("production.workOrders.completeError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  function openCompleteDialog(order: WorkOrder | null) {
    if (!order) {
      setCompletingId(null);
      return;
    }
    setCompletingId(order.id);
    resetCompleteForm();
  }

  const nonRegrindOrders = orders.filter((o) => !regrindWorkOrderIds.has(o.id));
  const inProgressCount = nonRegrindOrders.filter((o) => o.status === "in_progress").length;
  const completedCount = nonRegrindOrders.filter((o) => o.status === "completed").length;
  const statusFilteredOrders = statusFilter === "all" ? nonRegrindOrders : nonRegrindOrders.filter((o) => o.status === statusFilter);

  const columnFilterFields: FilterField<WorkOrder>[] = [
    { key: "reference", kind: "text", getValue: (o) => o.reference },
    { key: "product_id", kind: "text", getValue: (o) => products.find((p) => p.id === o.product_id)?.name ?? o.product_id },
    { key: "quantity", kind: "range", getValue: (o) => o.quantity },
    { key: "work_center", kind: "text", getValue: (o) => workCenters.find((wc) => wc.id === o.work_center_id)?.code ?? o.work_center_id },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredOrders = columnFilters.apply(statusFilteredOrders);

  const productName = (productId: string) => products.find((p) => p.id === productId)?.name ?? productId;

  const columns: ColumnDef<WorkOrder>[] = [
    {
      key: "reference",
      header: t("production.workOrders.column.reference"),
      defaultWidth: 140,
      cell: (order) => <span className="font-medium">{order.reference}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.reference ?? "",
        onChange: (v) => columnFilters.setTextValue("reference", v),
        placeholder: t("production.workOrders.column.reference"),
      },
    },
    {
      key: "product",
      header: t("production.workOrders.column.product"),
      defaultWidth: 200,
      cell: (order) => <span className="font-medium">{productName(order.product_id)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.product_id ?? "",
        onChange: (v) => columnFilters.setTextValue("product_id", v),
        placeholder: t("production.workOrders.column.product"),
      },
    },
    {
      key: "quantity",
      header: t("production.workOrders.column.quantity"),
      defaultWidth: 140,
      cell: (order) => <span className="tabular-nums text-muted-foreground">{order.quantity}</span>,
      filterCell: {
        type: "range",
        min: columnFilters.range.quantity?.min ?? "",
        max: columnFilters.range.quantity?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("quantity", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("quantity", "max", v),
      },
    },
    {
      key: "work_center",
      header: t("production.workOrders.column.workCenter"),
      defaultWidth: 160,
      cell: (order) => (
        <span className="text-muted-foreground">{workCenters.find((wc) => wc.id === order.work_center_id)?.code ?? "—"}</span>
      ),
      filterCell: {
        type: "text",
        value: columnFilters.text.work_center ?? "",
        onChange: (v) => columnFilters.setTextValue("work_center", v),
        placeholder: t("production.workOrders.column.workCenter"),
      },
    },
    {
      key: "progress",
      header: t("production.workOrders.column.progress"),
      defaultWidth: 160,
      cell: (order) => (
        <div className="h-1.5 w-28 overflow-hidden rounded-full bg-muted">
          <motion.div
            className={cn(
              "h-full rounded-full",
              order.status === "completed" ? "bg-success" : order.status === "in_progress" ? "bg-warning" : "bg-border",
            )}
            initial={{ width: 0 }}
            animate={{ width: `${PROGRESS[order.status]}%` }}
            transition={{ duration: 0.5, ease: "easeOut" }}
          />
        </div>
      ),
    },
    { key: "status", header: t("production.workOrders.column.status"), defaultWidth: 140, cell: (order) => <StatusBadge status={order.status} /> },
    {
      key: "yield",
      header: t("production.workOrders.column.yield"),
      defaultWidth: 140,
      cell: (order) => {
        const ratio = yieldByWorkOrderId.get(order.id) ?? null;
        return (
          <span className="tabular-nums text-muted-foreground">
            {ratio !== null ? `${(ratio * 100).toFixed(1)}%` : t("production.workOrders.yieldNotAvailable")}
          </span>
        );
      },
    },
    {
      key: "action",
      header: t("production.workOrders.column.action"),
      defaultWidth: 260,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right",
      cell: (order) => (
        <OrderActions
          order={order}
          locations={locations}
          products={products}
          rawMaterialProducts={rawMaterialProducts}
          workCenters={workCenters}
          recipes={recipes}
          packagingBoms={packagingBoms}
          resourceTypes={resourceTypes}
          completingId={completingId}
          onOpenComplete={(open) => openCompleteDialog(open ? order : null)}
          completeForm={completeForm}
          onStart={() => startMutation.mutate(order.id)}
          onComplete={(input, consumptionEntries) => completeMutation.mutate({ id: order.id, input, consumptionEntries })}
          isStarting={startMutation.isPending && startMutation.variables === order.id}
          isCompleting={completeMutation.isPending && completeMutation.variables?.id === order.id}
          editingId={editingId}
          onOpenEdit={(open) => openEditDialog(open ? order : null)}
          editForm={editForm}
          onSubmitEdit={(input) => submitEdit(order, input)}
          isUpdating={updateMutation.isPending && updateMutation.variables?.id === order.id}
        />
      ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "production.workOrders",
    columns,
  );

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("production.workOrders.stat.total")} value={nonRegrindOrders.length} icon={<ClipboardList className="h-5 w-5" />} />
        <StatCard label={t("production.workOrders.stat.inProgress")} value={inProgressCount} icon={<Timer className="h-5 w-5" />} accent="warning" />
        <StatCard label={t("production.workOrders.stat.completed")} value={completedCount} icon={<CheckCircle2 className="h-5 w-5" />} accent="success" />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("production.workOrders.table.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("production.workOrders.table.subtitle")}</p>
            </div>
            <FilterTabs
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "draft", label: t("status.draft") },
                { value: "in_progress", label: t("status.in_progress") },
                { value: "completed", label: t("status.completed") },
              ]}
            />
            {columnFilters.isActive && (
              <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                {t("common.clearFilters")}
              </Button>
            )}
            <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
          </div>
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="h-4 w-4" />
                {t("production.workOrders.new")}
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-2xl">
              <DialogHeader>
                <DialogTitle>{t("production.workOrders.dialog.title")}</DialogTitle>
                <DialogDescription>{t("production.workOrders.dialog.description")}</DialogDescription>
              </DialogHeader>
              <form className="space-y-4" onSubmit={handleSubmit((input) => createMutation.mutate(input))}>
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <Label htmlFor="product_id">{t("production.workOrders.field.productId")}</Label>
                    <Button type="button" variant="ghost" size="sm" onClick={() => setProductManual((prev) => !prev)}>
                      {productManual ? t("production.regrind.chooseFromList") : t("production.regrind.enterManually")}
                    </Button>
                  </div>
                  {productManual ? (
                    <Input id="product_id" placeholder="e.g. fusilli-500g" {...register("product_id")} />
                  ) : (
                    <Select id="product_id" {...register("product_id")}>
                      <option value="">—</option>
                      {finishedGoodProducts.map((product) => (
                        <option key={product.id} value={product.id}>
                          {product.name}
                        </option>
                      ))}
                    </Select>
                  )}
                  {errors.product_id && <p className="text-sm text-destructive">{errors.product_id.message}</p>}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="quantity">{t("production.workOrders.field.quantity")}</Label>
                  <Input id="quantity" type="number" step="any" {...register("quantity")} />
                  {errors.quantity && <p className="text-sm text-destructive">{errors.quantity.message}</p>}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="work_center_id">{t("production.workOrders.field.workCenter")}</Label>
                  <Select id="work_center_id" {...register("work_center_id")}>
                    <option value="">—</option>
                    {workCenters.map((wc) => (
                      <option key={wc.id} value={wc.id}>
                        {wc.code} — {wc.name}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="recipe_id">{t("production.workOrders.field.recipe")}</Label>
                  <Select id="recipe_id" value={selectedRecipeId ?? ""} onChange={(e) => onRecipeChange(e.target.value)}>
                    <option value="">—</option>
                    {activeRecipes.map((recipe) => (
                      <option key={recipe.id} value={recipe.id}>
                        {recipe.target_product_id} · v{recipe.version}
                      </option>
                    ))}
                  </Select>
                </div>

                {selectedRecipe && (
                  <div className="space-y-1.5 rounded-lg border border-border bg-muted/30 p-3">
                    <Label className="text-xs text-muted-foreground">{t("production.workOrders.field.recipeReference")}</Label>
                    <ul className="space-y-0.5 text-sm">
                      {selectedRecipe.lines.map((line) => (
                        <li key={line.component_product_id} className="flex justify-between text-muted-foreground">
                          <span>{products.find((p) => p.id === line.component_product_id)?.name ?? line.component_product_id}</span>
                          <span className="tabular-nums">{line.default_percentage}%</span>
                        </li>
                      ))}
                    </ul>
                    <p className="text-xs text-muted-foreground">{t("production.workOrders.recipeReferenceHint")}</p>
                  </div>
                )}

                <div className="space-y-2 rounded-lg border border-border p-3">
                  <div className="flex items-center justify-between">
                    <Label>{t("production.workOrders.field.pouredInputs")}</Label>
                    <Button type="button" variant="ghost" size="sm" onClick={() => appendPouredInput({ product_id: "", quantity: 0 })}>
                      <Plus className="h-3.5 w-3.5" />
                      {t("production.workOrders.addPouredInputLine")}
                    </Button>
                  </div>
                  {pouredInputFields.length > 0 && (
                    <div className="space-y-1.5">
                      <Label htmlFor="poured_inputs_location_id" className="text-xs text-muted-foreground">
                        {t("production.workOrders.field.pouredInputsLocation")}
                      </Label>
                      <Select id="poured_inputs_location_id" {...register("poured_inputs_location_id")}>
                        <option value="">—</option>
                        {locations.map((location) => (
                          <option key={location.id} value={location.id}>
                            {location.name}
                          </option>
                        ))}
                      </Select>
                      {errors.poured_inputs_location_id && (
                        <p className="text-sm text-destructive">{errors.poured_inputs_location_id.message}</p>
                      )}
                    </div>
                  )}
                  <AnimatePresence initial={false}>
                    {pouredInputFields.map((field, lineIndex) => (
                      <motion.div
                        key={field.id}
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        transition={{ duration: 0.18 }}
                        className="flex items-center gap-2"
                      >
                        <Select className="flex-1" {...register(`poured_inputs.${lineIndex}.product_id` as const)}>
                          <option value="">—</option>
                          {rawMaterialProducts.map((product) => (
                            <option key={product.id} value={product.id}>
                              {product.name}
                            </option>
                          ))}
                        </Select>
                        <Input
                          type="number"
                          step="any"
                          className="w-28"
                          placeholder={t("production.workOrders.field.quantityUsed")}
                          {...register(`poured_inputs.${lineIndex}.quantity` as const)}
                        />
                        <Button type="button" variant="ghost" size="sm" onClick={() => removePouredInput(lineIndex)} aria-label={t("production.recipes.removeLine")}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </motion.div>
                    ))}
                  </AnimatePresence>
                  {pouredInputFields.length === 0 && <p className="text-xs text-muted-foreground">{t("production.workOrders.noPouredInputLines")}</p>}
                </div>
                {createMutation.isError && (
                  <p className="text-sm text-destructive">
                    {createMutation.error instanceof ApiError ? createMutation.error.message : t("production.workOrders.createError")}
                  </p>
                )}
                <Button type="submit" className="w-full" disabled={createMutation.isPending}>
                  {createMutation.isPending ? t("production.workOrders.creating") : t("production.workOrders.create")}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
        </CardHeader>
        <CardContent className="p-0">
          <Table colWidths={colWidths}>
            <TableHeader>
              <TableRow>
                {visibleColumns.map((column) => (
                  <ResizableTableHead
                    key={column.key}
                    width={getWidth(column.key)}
                    onResize={(width) => setWidth(column.key, width)}
                    className={column.headerClassName}
                  >
                    {column.header}
                  </ResizableTableHead>
                ))}
              </TableRow>
              <ColumnFilterRow cells={visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
            </TableHeader>
            <TableBody>
              {isLoading &&
                Array.from({ length: 3 }).map((_, i) => (
                  <TableRow key={i}>
                    <TableCell colSpan={visibleColumns.length}>
                      <Skeleton className="h-5 w-full" />
                    </TableCell>
                  </TableRow>
                ))}
              {!isLoading && filteredOrders.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <EmptyState
                      icon={<ClipboardList className="h-5 w-5" />}
                      title={t("production.workOrders.empty.title")}
                      description={t("production.workOrders.empty.description")}
                    />
                  </TableCell>
                </TableRow>
              )}
              <AnimatePresence initial={false}>
                {filteredOrders.map((order, i) => (
                  <motion.tr
                    key={order.id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i * 0.04, 0.3) } }}
                    exit={{ opacity: 0 }}
                    className="border-b border-border last:border-0 hover:bg-muted/50"
                  >
                    {visibleColumns.map((column) => (
                      <TableCell key={column.key} className={column.cellClassName}>
                        {column.cell(order)}
                      </TableCell>
                    ))}
                  </motion.tr>
                ))}
              </AnimatePresence>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function OrderActions({
  order,
  locations,
  products,
  rawMaterialProducts,
  workCenters,
  recipes,
  packagingBoms,
  resourceTypes,
  completingId,
  onOpenComplete,
  completeForm,
  onStart,
  onComplete,
  isStarting,
  isCompleting,
  editingId,
  onOpenEdit,
  editForm,
  onSubmitEdit,
  isUpdating,
}: {
  order: WorkOrder;
  locations: Location[];
  products: Product[];
  rawMaterialProducts: Product[];
  workCenters: WorkCenter[];
  recipes: Recipe[];
  packagingBoms: PackagingBom[];
  resourceTypes: ResourceType[];
  completingId: string | null;
  onOpenComplete: (open: boolean) => void;
  completeForm: UseFormReturn<CompleteForm>;
  onStart: () => void;
  onComplete: (input: CompleteWorkOrderInput, consumptionEntries: RecordWorkOrderConsumptionInput[]) => void;
  isStarting: boolean;
  isCompleting: boolean;
  editingId: string | null;
  onOpenEdit: (open: boolean) => void;
  editForm: UseFormReturn<EditOrderForm>;
  onSubmitEdit: (input: EditOrderForm) => void;
  isUpdating: boolean;
}) {
  const { session } = useAuth();
  const token = session!.token;
  const { t } = useI18n();
  const { fields, append, remove } = useFieldArray({ control: completeForm.control, name: "materials" });
  const { fields: consumptionFields, append: appendConsumption, remove: removeConsumption } = useFieldArray({
    control: completeForm.control,
    name: "consumption",
  });
  const productName = (productId: string) => products.find((p) => p.id === productId)?.name ?? productId;
  const isCompleteDialogOpen = completingId === order.id;

  const { data: pouredInputs = [] } = useQuery({
    queryKey: ["production", "work-order-inputs", order.id],
    queryFn: () => listWorkOrderInputs(token, order.id),
    enabled: isCompleteDialogOpen,
  });

  function submitComplete(input: CompleteForm) {
    const scrapEntries: CompleteWorkOrderInput["scrapEntries"] = [];
    if (input.versement_quantity && input.versement_quantity > 0 && input.versement_product_id) {
      scrapEntries.push({ scrapType: "filling_dosing", productId: input.versement_product_id, quantity: input.versement_quantity });
    }
    if (input.decoupe_quantity && input.decoupe_quantity > 0 && input.decoupe_product_id) {
      scrapEntries.push({ scrapType: "cutting", productId: input.decoupe_product_id, quantity: input.decoupe_quantity });
    }
    onComplete(
      {
        correlationId: crypto.randomUUID(),
        locationId: input.location_id,
        actualOutputQuantity: input.actual_output_quantity,
        materialsUsed: input.materials.filter((m) => m.product_id && m.quantity > 0),
        materialsLocationId: input.materials_location_id || undefined,
        scrapEntries,
      },
      input.consumption
        .filter((c) => c.resource_type_id && c.quantity > 0)
        .map((c) => ({ resource_type_id: c.resource_type_id, quantity: c.quantity, note: c.note || undefined })),
    );
  }

  return (
        <div className="flex justify-end gap-2">
          <Dialog open={editingId === order.id} onOpenChange={onOpenEdit}>
            <DialogTrigger asChild>
              <Button size="sm" variant="outline">
                <Pencil className="h-3.5 w-3.5" />
                {t("production.workOrders.edit")}
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{t("production.workOrders.dialog.editTitle")}</DialogTitle>
                <DialogDescription>{t("production.workOrders.dialog.editDescription")}</DialogDescription>
              </DialogHeader>
              <form className="space-y-4" onSubmit={editForm.handleSubmit(onSubmitEdit)}>
                <div className="space-y-1.5">
                  <Label htmlFor={`edit_quantity_${order.id}`}>{t("production.workOrders.field.quantity")}</Label>
                  <Input id={`edit_quantity_${order.id}`} type="number" step="any" {...editForm.register("quantity")} />
                  {editForm.formState.errors.quantity && (
                    <p className="text-sm text-destructive">{editForm.formState.errors.quantity.message}</p>
                  )}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`edit_work_center_${order.id}`}>{t("production.workOrders.field.workCenter")}</Label>
                  <Select id={`edit_work_center_${order.id}`} {...editForm.register("work_center_id")}>
                    <option value="">—</option>
                    {workCenters.map((wc) => (
                      <option key={wc.id} value={wc.id}>
                        {wc.code} — {wc.name}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`edit_recipe_${order.id}`}>{t("production.workOrders.field.recipe")}</Label>
                  <Select id={`edit_recipe_${order.id}`} {...editForm.register("recipe_id")}>
                    <option value="">—</option>
                    {recipes.map((recipe) => (
                      <option key={recipe.id} value={recipe.id}>
                        {recipe.target_product_id} · v{recipe.version}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`edit_packaging_bom_${order.id}`}>{t("production.workOrders.field.packagingBom")}</Label>
                  <Select id={`edit_packaging_bom_${order.id}`} {...editForm.register("packaging_bom_id")}>
                    <option value="">—</option>
                    {packagingBoms.map((bom) => (
                      <option key={bom.id} value={bom.id}>
                        {bom.target_product_id} · v{bom.version}
                      </option>
                    ))}
                  </Select>
                </div>
                <Button type="submit" className="w-full" disabled={isUpdating}>
                  {isUpdating ? t("production.workOrders.updating") : t("production.workOrders.update")}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
          {order.status === "draft" && (
            <Button size="sm" variant="outline" onClick={onStart} disabled={isStarting}>
              <PlayCircle className="h-3.5 w-3.5" />
              {isStarting ? t("production.workOrders.starting") : t("production.workOrders.start")}
            </Button>
          )}
          {order.status === "in_progress" && (
          <Dialog open={completingId === order.id} onOpenChange={onOpenComplete}>
            <DialogTrigger asChild>
              <Button size="sm" variant="outline">
                <CheckCircle2 className="h-3.5 w-3.5" />
                {t("production.workOrders.complete")}
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-2xl">
              <DialogHeader>
                <DialogTitle>{t("production.workOrders.dialog.complete.title")}</DialogTitle>
                <DialogDescription>{t("production.workOrders.dialog.complete.description")}</DialogDescription>
              </DialogHeader>
              <form className="space-y-4" onSubmit={completeForm.handleSubmit(submitComplete)}>
                <div className="space-y-1.5">
                  <Label htmlFor={`complete_location_${order.id}`}>{t("production.workOrders.field.destinationLocation")}</Label>
                  <Select id={`complete_location_${order.id}`} {...completeForm.register("location_id")}>
                    <option value="">—</option>
                    {locations.map((location) => (
                      <option key={location.id} value={location.id}>
                        {location.name}
                      </option>
                    ))}
                  </Select>
                  {completeForm.formState.errors.location_id && (
                    <p className="text-sm text-destructive">{completeForm.formState.errors.location_id.message}</p>
                  )}
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor={`complete_actual_output_${order.id}`}>{t("production.workOrders.field.actualOutputQuantity")}</Label>
                  <Input id={`complete_actual_output_${order.id}`} type="number" step="any" {...completeForm.register("actual_output_quantity")} />
                  {completeForm.formState.errors.actual_output_quantity && (
                    <p className="text-sm text-destructive">{completeForm.formState.errors.actual_output_quantity.message}</p>
                  )}
                </div>

                <div className="space-y-1.5 rounded-lg border border-border bg-muted/30 p-3">
                  <Label className="text-xs text-muted-foreground">{t("production.workOrders.field.pouredInputsReadonly")}</Label>
                  {pouredInputs.length === 0 ? (
                    <p className="text-xs text-muted-foreground">{t("production.workOrders.noPouredInputsRecorded")}</p>
                  ) : (
                    <ul className="space-y-0.5 text-sm">
                      {pouredInputs.map((line) => (
                        <li key={line.id} className="flex justify-between text-muted-foreground">
                          <span>{productName(line.product_id)}</span>
                          <span className="tabular-nums">{line.quantity}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="space-y-2 rounded-lg border border-border p-3">
                  <div className="flex items-center justify-between">
                    <Label>{t("production.workOrders.field.materialsUsed")}</Label>
                    <Button type="button" variant="ghost" size="sm" onClick={() => append({ product_id: "", quantity: 0 })}>
                      <Plus className="h-3.5 w-3.5" />
                      {t("production.workOrders.addMaterialLine")}
                    </Button>
                  </div>
                  {fields.length > 0 && (
                    <div className="space-y-1.5">
                      <Label htmlFor={`materials_location_${order.id}`} className="text-xs text-muted-foreground">
                        {t("production.workOrders.field.materialsLocation")}
                      </Label>
                      <Select id={`materials_location_${order.id}`} {...completeForm.register("materials_location_id")}>
                        <option value="">—</option>
                        {locations.map((location) => (
                          <option key={location.id} value={location.id}>
                            {location.name}
                          </option>
                        ))}
                      </Select>
                    </div>
                  )}
                  <AnimatePresence initial={false}>
                    {fields.map((field, lineIndex) => (
                      <motion.div
                        key={field.id}
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        transition={{ duration: 0.18 }}
                        className="flex items-center gap-2"
                      >
                        <Select className="flex-1" {...completeForm.register(`materials.${lineIndex}.product_id` as const)}>
                          <option value="">—</option>
                          {rawMaterialProducts.map((product) => (
                            <option key={product.id} value={product.id}>
                              {product.name}
                            </option>
                          ))}
                        </Select>
                        <Input
                          type="number"
                          step="any"
                          className="w-28"
                          placeholder={t("production.workOrders.field.quantityUsed")}
                          {...completeForm.register(`materials.${lineIndex}.quantity` as const)}
                        />
                        <Button type="button" variant="ghost" size="sm" onClick={() => remove(lineIndex)} aria-label={t("production.recipes.removeLine")}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </motion.div>
                    ))}
                  </AnimatePresence>
                  {fields.length === 0 && <p className="text-xs text-muted-foreground">{t("production.workOrders.noMaterialLines")}</p>}
                </div>

                <div className="space-y-2 rounded-lg border border-border p-3">
                  <Label>{t("production.workOrders.field.scrapGenerated")}</Label>
                  <div className="grid grid-cols-3 items-center gap-2">
                    <span className="text-sm text-muted-foreground">{t("production.workOrders.scrapStage.versement")}</span>
                    <Input
                      type="number"
                      step="any"
                      placeholder={t("production.workOrders.field.quantityUsed")}
                      {...completeForm.register("versement_quantity")}
                    />
                    <Select {...completeForm.register("versement_product_id")}>
                      <option value="">—</option>
                      {products.map((product) => (
                        <option key={product.id} value={product.id}>
                          {product.name}
                        </option>
                      ))}
                    </Select>
                    <span className="text-sm text-muted-foreground">{t("production.workOrders.scrapStage.decoupe")}</span>
                    <Input
                      type="number"
                      step="any"
                      placeholder={t("production.workOrders.field.quantityUsed")}
                      {...completeForm.register("decoupe_quantity")}
                    />
                    <Select {...completeForm.register("decoupe_product_id")}>
                      <option value="">—</option>
                      {products.map((product) => (
                        <option key={product.id} value={product.id}>
                          {product.name}
                        </option>
                      ))}
                    </Select>
                  </div>
                  <p className="text-xs text-muted-foreground">{t("production.workOrders.scrapHint")}</p>
                </div>

                <div className="space-y-2 rounded-lg border border-border p-3">
                  <div className="flex items-center justify-between">
                    <Label>{t("production.workOrders.field.consumption")}</Label>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => appendConsumption({ resource_type_id: "", quantity: 0, note: "" })}
                    >
                      <Plus className="h-3.5 w-3.5" />
                      {t("production.workOrders.addConsumptionLine")}
                    </Button>
                  </div>
                  <AnimatePresence initial={false}>
                    {consumptionFields.map((field, lineIndex) => (
                      <motion.div
                        key={field.id}
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        transition={{ duration: 0.18 }}
                        className="flex items-center gap-2"
                      >
                        <Select className="flex-1" {...completeForm.register(`consumption.${lineIndex}.resource_type_id` as const)}>
                          <option value="">—</option>
                          {resourceTypes.map((rt) => (
                            <option key={rt.id} value={rt.id}>
                              {rt.name} ({rt.unit})
                            </option>
                          ))}
                        </Select>
                        <Input
                          type="number"
                          step="any"
                          className="w-24"
                          placeholder={t("production.workOrders.field.quantityUsed")}
                          {...completeForm.register(`consumption.${lineIndex}.quantity` as const)}
                        />
                        <Input
                          className="w-32"
                          placeholder={t("production.workOrders.field.note")}
                          {...completeForm.register(`consumption.${lineIndex}.note` as const)}
                        />
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => removeConsumption(lineIndex)}
                          aria-label={t("production.recipes.removeLine")}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </motion.div>
                    ))}
                  </AnimatePresence>
                  {consumptionFields.length === 0 && (
                    <p className="text-xs text-muted-foreground">{t("production.workOrders.noConsumptionLines")}</p>
                  )}
                </div>

                <Button type="submit" className="w-full" disabled={isCompleting}>
                  {isCompleting ? t("production.workOrders.completing") : t("production.workOrders.complete")}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
          )}
        </div>
  );
}
