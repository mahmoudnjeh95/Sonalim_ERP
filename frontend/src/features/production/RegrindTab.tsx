import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Recycle, Plus, Scale, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Checkbox } from "../../components/ui/checkbox";
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
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import {
  createProduct,
  createRegrindBatch,
  listProducts,
  listRegrindBatches,
  listScrapRecords,
  listUoms,
  listWorkCenters,
  listWorkOrders,
  recordScrap,
  type RegrindBatchSummary,
  type ScrapRecord,
} from "./api";

const scrapSchema = z
  .object({
    scrap_type: z.enum(["filling_dosing", "cutting"]),
    product_id: z.string().min(1, "Required"),
    quantity: z.coerce.number().positive("Must be > 0"),
    work_order_id: z.string().optional(),
    work_center_id: z.string().optional(),
    source_note: z.string().optional(),
  })
  .refine((data) => !!data.work_order_id || !!data.source_note?.trim(), {
    message: "Provide a work order or describe the source",
    path: ["source_note"],
  });
type ScrapForm = z.infer<typeof scrapSchema>;

const batchSchema = z.object({
  output_product_id: z.string().optional(),
  new_sku: z.string().optional(),
  new_name: z.string().optional(),
  output_quantity: z.coerce.number().positive("Must be > 0"),
  work_center_id: z.string().optional(),
});
type BatchForm = z.infer<typeof batchSchema>;

const SCRAP_QUERY_KEY = ["production", "scrap-records"] as const;
const WORK_CENTERS_QUERY_KEY = ["production", "work-centers"] as const;
const WORK_ORDERS_QUERY_KEY = ["production", "work-orders"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const UOMS_QUERY_KEY = ["core", "uoms"] as const;
const REGRIND_BATCHES_QUERY_KEY = ["production", "regrind-batches"] as const;
type RegrindFilter = "all" | "available" | "reground";

function formatKg(value: number) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
}

export function RegrindTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [scrapDialogOpen, setScrapDialogOpen] = useState(false);
  const [batchDialogOpen, setBatchDialogOpen] = useState(false);
  const [selectedScrapIds, setSelectedScrapIds] = useState<string[]>([]);
  const [regrindFilter, setRegrindFilter] = useState<RegrindFilter>("all");
  const [sourceUncertain, setSourceUncertain] = useState(false);
  const [productManual, setProductManual] = useState(false);
  const [outputMode, setOutputMode] = useState<"existing" | "new">("existing");

  const { data: scrapRecords = [], isLoading } = useQuery({ queryKey: SCRAP_QUERY_KEY, queryFn: () => listScrapRecords(token) });
  const { data: workCenters = [] } = useQuery({ queryKey: WORK_CENTERS_QUERY_KEY, queryFn: () => listWorkCenters(token) });
  const { data: workOrders = [] } = useQuery({ queryKey: WORK_ORDERS_QUERY_KEY, queryFn: () => listWorkOrders(token) });
  const inProgressWorkOrders = workOrders.filter((wo) => wo.status === "in_progress");
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: uoms = [] } = useQuery({ queryKey: UOMS_QUERY_KEY, queryFn: () => listUoms(token) });
  const kgUomId = uoms.find((u) => u.code === "kg")?.id;
  const { data: regrindBatches = [] } = useQuery({ queryKey: REGRIND_BATCHES_QUERY_KEY, queryFn: () => listRegrindBatches(token) });
  const productName = (productId: string) => products.find((p) => p.id === productId)?.name ?? productId;
  const workOrderRef = (workOrderId: string) => workOrders.find((wo) => wo.id === workOrderId)?.reference ?? workOrderId;

  const scrapForm = useForm<ScrapForm>({ resolver: zodResolver(scrapSchema), defaultValues: { scrap_type: "cutting" } });

  const recordScrapMutation = useMutation({
    mutationFn: (input: ScrapForm) =>
      recordScrap(token, {
        scrap_type: input.scrap_type,
        product_id: input.product_id,
        quantity: input.quantity,
        work_order_id: sourceUncertain ? undefined : input.work_order_id || undefined,
        work_center_id: sourceUncertain ? undefined : input.work_center_id || undefined,
        source_note: sourceUncertain ? input.source_note?.trim() || undefined : undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: SCRAP_QUERY_KEY });
      setScrapDialogOpen(false);
      setSourceUncertain(false);
      setProductManual(false);
      scrapForm.reset({ scrap_type: "cutting" });
      toast.success(t("production.regrind.recorded"));
    },
    onError: (error) => toast.error(t("production.regrind.recordError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const batchForm = useForm<BatchForm>({ resolver: zodResolver(batchSchema) });

  const createProductMutation = useMutation({
    mutationFn: (input: { sku: string; name: string; uom_id: string }) => createProduct(token, input),
  });

  const createBatchMutation = useMutation({
    mutationFn: (input: { output_product_id: string; output_quantity: number; work_center_id?: string }) =>
      createRegrindBatch(token, { ...input, scrap_record_ids: selectedScrapIds }),
    onSuccess: (batch) => {
      queryClient.invalidateQueries({ queryKey: SCRAP_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: REGRIND_BATCHES_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: PRODUCTS_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["production", "product-classifications"] });
      setBatchDialogOpen(false);
      setSelectedScrapIds([]);
      setOutputMode("existing");
      batchForm.reset();
      toast.success(t("production.regrind.batchCreated"), {
        description: `${batch.work_order.product_id} · ${t("production.regrind.lossLabel")}: ${formatKg(batch.loss_quantity)} KG`,
      });
    },
    onError: (error) => toast.error(t("production.regrind.createBatchError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  async function handleBatchSubmit(input: BatchForm) {
    let outputProductId = input.output_product_id;

    if (outputMode === "new") {
      if (!kgUomId) {
        toast.error(t("production.regrind.noKgUom"));
        return;
      }
      const sku = input.new_sku?.trim();
      const name = input.new_name?.trim();
      if (!sku || !name) {
        toast.error(t("production.regrind.createBatchError"));
        return;
      }
      try {
        const product = await createProductMutation.mutateAsync({ sku, name, uom_id: kgUomId });
        outputProductId = product.id;
        toast.success(t("production.regrind.productCreated"), { description: product.name });
      } catch (error) {
        toast.error(t("production.regrind.createBatchError"), { description: error instanceof ApiError ? error.message : undefined });
        return;
      }
    }

    if (!outputProductId) {
      toast.error(t("production.regrind.createBatchError"));
      return;
    }

    createBatchMutation.mutate({
      output_product_id: outputProductId,
      output_quantity: input.output_quantity,
      work_center_id: input.work_center_id || undefined,
    });
  }

  function selectedScrapSuggestion(): { sku: string; name: string } | null {
    const selected = scrapRecords.filter((s) => selectedScrapIds.includes(s.id));
    const distinctProductIds = new Set(selected.map((s) => s.product_id));
    if (distinctProductIds.size !== 1) return null;
    const baseId = [...distinctProductIds][0];
    const baseProduct = products.find((p) => p.id === baseId);
    const baseSku = baseProduct?.sku ?? baseId;
    const baseName = baseProduct?.name ?? baseId;
    return { sku: `${baseSku}-rebroye`, name: `${baseName} (Rebroyé)` };
  }

  function switchToNewProduct() {
    setOutputMode("new");
    const suggestion = selectedScrapSuggestion();
    if (suggestion) {
      batchForm.setValue("new_sku", suggestion.sku);
      batchForm.setValue("new_name", suggestion.name);
    }
  }

  const availableCount = scrapRecords.filter((s) => !s.is_reground).length;
  const regroundCount = scrapRecords.filter((s) => s.is_reground).length;
  const totalLoss = regrindBatches.reduce((sum, b) => sum + b.loss_quantity, 0);
  const regrindFilteredRecords =
    regrindFilter === "all"
      ? scrapRecords
      : scrapRecords.filter((s) => (regrindFilter === "reground" ? s.is_reground : !s.is_reground));

  function scrapTypeLabel(record: ScrapRecord): string {
    return record.scrap_type === "cutting" ? t("production.regrind.scrapType.cutting") : t("production.regrind.scrapType.fillingDosing");
  }

  function workCenterLabel(workCenterId: string | null): string {
    if (!workCenterId) return "—";
    return workCenters.find((wc) => wc.id === workCenterId)?.code ?? workCenterId;
  }

  const columnFilterFields: FilterField<ScrapRecord>[] = [
    { key: "work_order_id", kind: "text", getValue: (s) => (s.work_order_id ? workOrderRef(s.work_order_id) : s.source_note) },
    { key: "scrap_type", kind: "text", getValue: (s) => scrapTypeLabel(s) },
    { key: "product_id", kind: "text", getValue: (s) => productName(s.product_id) },
    { key: "quantity", kind: "range", getValue: (s) => s.quantity },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredScrapRecords = columnFilters.apply(regrindFilteredRecords);

  function toggleSelected(id: string) {
    setSelectedScrapIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  const scrapColumns: ColumnDef<ScrapRecord>[] = [
    {
      key: "select",
      header: "",
      defaultWidth: 40,
      alwaysVisible: true,
      cell: (scrap) =>
        !scrap.is_reground && (
          <Checkbox
            checked={selectedScrapIds.includes(scrap.id)}
            onCheckedChange={() => toggleSelected(scrap.id)}
            aria-label={t("production.regrind.selectForRegrind")}
          />
        ),
    },
    {
      key: "work_order_id",
      header: t("production.regrind.column.workOrder"),
      defaultWidth: 180,
      cell: (scrap) => {
        const label = scrap.work_order_id ? workOrderRef(scrap.work_order_id) : scrap.source_note ?? "—";
        return (
          <span className="block truncate font-medium" title={label}>
            {label}
          </span>
        );
      },
      filterCell: {
        type: "text",
        value: columnFilters.text.work_order_id ?? "",
        onChange: (v) => columnFilters.setTextValue("work_order_id", v),
        placeholder: t("production.regrind.column.workOrder"),
      },
    },
    {
      key: "line",
      header: t("production.regrind.field.line"),
      defaultWidth: 140,
      cell: (scrap) => <span className="text-muted-foreground">{workCenterLabel(scrap.work_center_id)}</span>,
    },
    {
      key: "scrap_type",
      header: t("production.regrind.column.type"),
      defaultWidth: 160,
      cell: (scrap) => <span className="text-muted-foreground">{scrapTypeLabel(scrap)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.scrap_type ?? "",
        onChange: (v) => columnFilters.setTextValue("scrap_type", v),
        placeholder: t("production.regrind.column.type"),
      },
    },
    {
      key: "product_id",
      header: t("production.regrind.column.product"),
      defaultWidth: 180,
      cell: (scrap) => productName(scrap.product_id),
      filterCell: {
        type: "text",
        value: columnFilters.text.product_id ?? "",
        onChange: (v) => columnFilters.setTextValue("product_id", v),
        placeholder: t("production.regrind.column.product"),
      },
    },
    {
      key: "quantity",
      header: t("production.regrind.column.quantity"),
      defaultWidth: 140,
      cell: (scrap) => <span className="tabular-nums text-muted-foreground">{scrap.quantity}</span>,
      filterCell: {
        type: "range",
        min: columnFilters.range.quantity?.min ?? "",
        max: columnFilters.range.quantity?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("quantity", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("quantity", "max", v),
      },
    },
    {
      key: "status",
      header: t("production.regrind.column.status"),
      defaultWidth: 140,
      cell: (scrap) =>
        scrap.is_reground ? (
          <Badge variant="success" dot>
            {t("production.regrind.reground")}
          </Badge>
        ) : (
          <Badge variant="warning" dot>
            {t("production.regrind.available")}
          </Badge>
        ),
    },
  ];
  const scrapTable = useTableColumns("production.regrind.scrap", scrapColumns);

  const batchColumns: ColumnDef<RegrindBatchSummary>[] = [
    { key: "output", header: t("production.regrind.batches.column.output"), defaultWidth: 200, cell: (batch) => <span className="font-medium">{productName(batch.output_product_id)}</span> },
    { key: "outputQuantity", header: t("production.regrind.batches.column.outputQuantity"), defaultWidth: 140, cell: (batch) => <span className="tabular-nums text-muted-foreground">{formatKg(batch.output_quantity)}</span> },
    { key: "inputTotal", header: t("production.regrind.batches.column.inputTotal"), defaultWidth: 140, cell: (batch) => <span className="tabular-nums text-muted-foreground">{formatKg(batch.input_quantity_total)}</span> },
    {
      key: "loss",
      header: t("production.regrind.batches.column.loss"),
      defaultWidth: 140,
      cell: (batch) => (
        <span className={`tabular-nums ${batch.loss_quantity > 0 ? "text-destructive" : "text-muted-foreground"}`}>
          {formatKg(batch.loss_quantity)}
        </span>
      ),
    },
    { key: "status", header: t("production.regrind.batches.column.status"), defaultWidth: 140, cell: (batch) => <StatusBadge status={batch.status} /> },
    { key: "date", header: t("production.regrind.batches.column.date"), defaultWidth: 160, cell: (batch) => <span className="whitespace-nowrap text-muted-foreground">{new Date(batch.created_at).toLocaleDateString()}</span> },
  ];
  const batchTable = useTableColumns("production.regrind.batches", batchColumns);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
        <StatCard label={t("production.regrind.stat.total")} value={scrapRecords.length} icon={<Recycle className="h-5 w-5" />} />
        <StatCard label={t("production.regrind.stat.available")} value={availableCount} icon={<Trash2 className="h-5 w-5" />} accent="warning" />
        <StatCard label={t("production.regrind.stat.reground")} value={regroundCount} icon={<CheckCircle2 className="h-5 w-5" />} accent="success" />
        <StatCard label={t("production.regrind.stat.totalLoss")} value={Math.round(totalLoss)} icon={<Scale className="h-5 w-5" />} accent="destructive" />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("production.regrind.table.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("production.regrind.table.subtitle")}</p>
            </div>
            <FilterTabs
              value={regrindFilter}
              onChange={setRegrindFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "available", label: t("production.regrind.available") },
                { value: "reground", label: t("production.regrind.reground") },
              ]}
            />
            {columnFilters.isActive && (
              <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                {t("common.clearFilters")}
              </Button>
            )}
            <ColumnVisibilityMenu
              columns={scrapColumns}
              isVisible={scrapTable.isVisible}
              onToggle={scrapTable.toggleVisible}
              onReset={scrapTable.resetAll}
            />
          </div>
          <div className="flex gap-2">
            <Dialog
              open={scrapDialogOpen}
              onOpenChange={(open) => {
                setScrapDialogOpen(open);
                if (!open) {
                  setSourceUncertain(false);
                  setProductManual(false);
                }
              }}
            >
              <DialogTrigger asChild>
                <Button variant="outline">
                  <Plus className="h-4 w-4" />
                  {t("production.regrind.recordScrap")}
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>{t("production.regrind.dialog.scrap.title")}</DialogTitle>
                  <DialogDescription>{t("production.regrind.dialog.scrap.description")}</DialogDescription>
                </DialogHeader>
                <form className="space-y-4" onSubmit={scrapForm.handleSubmit((input) => recordScrapMutation.mutate(input))}>
                  <div className="flex items-center justify-between">
                    <Label>{sourceUncertain ? t("production.regrind.sourceUncertain") : t("production.regrind.sourceKnown")}</Label>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setSourceUncertain((prev) => !prev);
                        scrapForm.setValue("work_order_id", "");
                        scrapForm.setValue("work_center_id", "");
                        scrapForm.setValue("source_note", "");
                      }}
                    >
                      {sourceUncertain ? t("production.regrind.sourceKnown") : t("production.regrind.sourceUncertain")}
                    </Button>
                  </div>

                  {!sourceUncertain && (
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1.5">
                        <Label htmlFor="work_order_id">{t("production.regrind.field.workOrderId")}</Label>
                        <Select id="work_order_id" {...scrapForm.register("work_order_id")}>
                          <option value="">—</option>
                          {inProgressWorkOrders.map((wo) => (
                            <option key={wo.id} value={wo.id}>
                              {wo.reference} · {productName(wo.product_id)} · {wo.quantity}
                            </option>
                          ))}
                        </Select>
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="work_center_id">{t("production.regrind.field.line")}</Label>
                        <Select id="work_center_id" {...scrapForm.register("work_center_id")}>
                          <option value="">—</option>
                          {workCenters.map((wc) => (
                            <option key={wc.id} value={wc.id}>
                              {wc.code} — {wc.name}
                            </option>
                          ))}
                        </Select>
                      </div>
                    </div>
                  )}

                  {sourceUncertain && (
                    <div className="space-y-1.5">
                      <Label htmlFor="source_note">{t("production.regrind.field.sourceNote")}</Label>
                      <Input
                        id="source_note"
                        placeholder={t("production.regrind.field.sourceNotePlaceholder")}
                        {...scrapForm.register("source_note")}
                      />
                      {scrapForm.formState.errors.source_note && (
                        <p className="text-sm text-destructive">{scrapForm.formState.errors.source_note.message}</p>
                      )}
                    </div>
                  )}

                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label htmlFor="scrap_type">{t("production.regrind.field.scrapType")}</Label>
                      <Select id="scrap_type" {...scrapForm.register("scrap_type")}>
                        <option value="cutting">{t("production.regrind.scrapType.cutting")}</option>
                        <option value="filling_dosing">{t("production.regrind.scrapType.fillingDosing")}</option>
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="quantity">{t("production.regrind.field.quantity")}</Label>
                      <Input id="quantity" type="number" step="any" {...scrapForm.register("quantity")} />
                      {scrapForm.formState.errors.quantity && (
                        <p className="text-sm text-destructive">{scrapForm.formState.errors.quantity.message}</p>
                      )}
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                      <Label htmlFor="product_id">{t("production.regrind.field.scrapProductId")}</Label>
                      <Button type="button" variant="ghost" size="sm" onClick={() => setProductManual((prev) => !prev)}>
                        {productManual ? t("production.regrind.chooseFromList") : t("production.regrind.enterManually")}
                      </Button>
                    </div>
                    {productManual ? (
                      <Input id="product_id" placeholder="e.g. fusilli-dough-scrap" {...scrapForm.register("product_id")} />
                    ) : (
                      <Select id="product_id" {...scrapForm.register("product_id")}>
                        <option value="">—</option>
                        {products.map((product) => (
                          <option key={product.id} value={product.id}>
                            {product.name}
                          </option>
                        ))}
                      </Select>
                    )}
                    {scrapForm.formState.errors.product_id && (
                      <p className="text-sm text-destructive">{scrapForm.formState.errors.product_id.message}</p>
                    )}
                  </div>

                  {recordScrapMutation.isError && (
                    <p className="text-sm text-destructive">
                      {recordScrapMutation.error instanceof ApiError ? recordScrapMutation.error.message : t("production.regrind.recordError")}
                    </p>
                  )}
                  <Button type="submit" className="w-full" disabled={recordScrapMutation.isPending}>
                    {recordScrapMutation.isPending ? t("production.regrind.recording") : t("production.regrind.recordScrap")}
                  </Button>
                </form>
              </DialogContent>
            </Dialog>

            <Dialog
              open={batchDialogOpen}
              onOpenChange={(open) => {
                setBatchDialogOpen(open);
                if (!open) setOutputMode("existing");
              }}
            >
              <DialogTrigger asChild>
                <Button disabled={selectedScrapIds.length === 0} title={selectedScrapIds.length === 0 ? t("production.regrind.selectScrapFirst") : undefined}>
                  <Recycle className="h-4 w-4" />
                  {t("production.regrind.createBatch")} ({selectedScrapIds.length})
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>{t("production.regrind.dialog.batch.title")}</DialogTitle>
                  <DialogDescription>
                    {t("production.regrind.dialog.batch.consumes")} {selectedScrapIds.length}{" "}
                    {selectedScrapIds.length === 1 ? t("production.regrind.dialog.batch.recordSingular") : t("production.regrind.dialog.batch.recordPlural")}{" "}
                    {t("production.regrind.dialog.batch.intoWorkOrder")}
                  </DialogDescription>
                </DialogHeader>
                <form className="space-y-4" onSubmit={batchForm.handleSubmit(handleBatchSubmit)}>
                  <div className="flex items-center justify-between">
                    <Label>{outputMode === "new" ? t("production.regrind.outputMode.new") : t("production.regrind.outputMode.existing")}</Label>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => (outputMode === "existing" ? switchToNewProduct() : setOutputMode("existing"))}
                    >
                      {outputMode === "existing" ? t("production.regrind.outputMode.new") : t("production.regrind.outputMode.existing")}
                    </Button>
                  </div>

                  {outputMode === "existing" ? (
                    <div className="space-y-1.5">
                      <Label htmlFor="output_product_id">{t("production.regrind.field.outputProductId")}</Label>
                      <Select id="output_product_id" {...batchForm.register("output_product_id")}>
                        <option value="">—</option>
                        {products.map((product) => (
                          <option key={product.id} value={product.id}>
                            {product.name}
                          </option>
                        ))}
                      </Select>
                    </div>
                  ) : (
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1.5">
                        <Label htmlFor="new_sku">{t("production.regrind.field.newProductSku")}</Label>
                        <Input id="new_sku" {...batchForm.register("new_sku")} />
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="new_name">{t("production.regrind.field.newProductName")}</Label>
                        <Input id="new_name" {...batchForm.register("new_name")} />
                      </div>
                      {!kgUomId && <p className="col-span-2 text-sm text-destructive">{t("production.regrind.noKgUom")}</p>}
                    </div>
                  )}

                  <div className="space-y-1.5">
                    <Label htmlFor="output_quantity">{t("production.regrind.field.outputQuantity")}</Label>
                    <Input id="output_quantity" type="number" step="any" {...batchForm.register("output_quantity")} />
                    {batchForm.formState.errors.output_quantity && (
                      <p className="text-sm text-destructive">{batchForm.formState.errors.output_quantity.message}</p>
                    )}
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="work_center_id">{t("production.regrind.field.workCenterOptional")}</Label>
                    <Select id="work_center_id" {...batchForm.register("work_center_id")}>
                      <option value="">—</option>
                      {workCenters.map((wc) => (
                        <option key={wc.id} value={wc.id}>
                          {wc.code} — {wc.name}
                        </option>
                      ))}
                    </Select>
                  </div>
                  {createBatchMutation.isError && (
                    <p className="text-sm text-destructive">
                      {createBatchMutation.error instanceof ApiError ? createBatchMutation.error.message : t("production.regrind.createBatchError")}
                    </p>
                  )}
                  <Button type="submit" className="w-full" disabled={createBatchMutation.isPending || createProductMutation.isPending}>
                    {createBatchMutation.isPending || createProductMutation.isPending
                      ? t("production.regrind.creatingBatch")
                      : t("production.regrind.createBatchButton")}
                  </Button>
                </form>
              </DialogContent>
            </Dialog>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <Table colWidths={scrapTable.colWidths}>
            <TableHeader>
              <TableRow>
                {scrapTable.visibleColumns.map((column) => (
                  <ResizableTableHead
                    key={column.key}
                    width={scrapTable.getWidth(column.key)}
                    onResize={(width) => scrapTable.setWidth(column.key, width)}
                    className={column.headerClassName}
                  >
                    {column.header}
                  </ResizableTableHead>
                ))}
              </TableRow>
              <ColumnFilterRow cells={scrapTable.visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
            </TableHeader>
            <TableBody>
              {isLoading &&
                Array.from({ length: 3 }).map((_, i) => (
                  <TableRow key={i}>
                    <TableCell colSpan={scrapTable.visibleColumns.length}>
                      <Skeleton className="h-5 w-full" />
                    </TableCell>
                  </TableRow>
                ))}
              {!isLoading && filteredScrapRecords.length === 0 && (
                <TableRow>
                  <TableCell colSpan={scrapTable.visibleColumns.length} className="p-0">
                    <EmptyState
                      icon={<Recycle className="h-5 w-5" />}
                      title={t("production.regrind.empty.title")}
                      description={t("production.regrind.empty.description")}
                    />
                  </TableCell>
                </TableRow>
              )}
              <AnimatePresence initial={false}>
                {filteredScrapRecords.map((scrap, i) => (
                  <motion.tr
                    key={scrap.id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i * 0.04, 0.3) } }}
                    exit={{ opacity: 0 }}
                    className="border-b border-border last:border-0 hover:bg-muted/50"
                  >
                    {scrapTable.visibleColumns.map((column) => (
                      <TableCell key={column.key} className={column.cellClassName}>
                        {column.cell(scrap)}
                      </TableCell>
                    ))}
                  </motion.tr>
                ))}
              </AnimatePresence>
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("production.regrind.batches.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("production.regrind.batches.subtitle")}</p>
            </div>
            <ColumnVisibilityMenu
              columns={batchColumns}
              isVisible={batchTable.isVisible}
              onToggle={batchTable.toggleVisible}
              onReset={batchTable.resetAll}
            />
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <Table colWidths={batchTable.colWidths}>
            <TableHeader>
              <TableRow>
                {batchTable.visibleColumns.map((column) => (
                  <ResizableTableHead
                    key={column.key}
                    width={batchTable.getWidth(column.key)}
                    onResize={(width) => batchTable.setWidth(column.key, width)}
                    className={column.headerClassName}
                  >
                    {column.header}
                  </ResizableTableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {regrindBatches.length === 0 && (
                <TableRow>
                  <TableCell colSpan={batchTable.visibleColumns.length} className="py-8 text-center text-muted-foreground">
                    {t("production.regrind.batches.empty")}
                  </TableCell>
                </TableRow>
              )}
              {regrindBatches.map((batch) => (
                <TableRow key={batch.work_order_id}>
                  {batchTable.visibleColumns.map((column) => (
                    <TableCell key={column.key} className={column.cellClassName}>
                      {column.cell(batch)}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
