import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, Package, PackageOpen, Pencil, Plus, Scale, Zap } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
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
import { listProducts, listStockMoves, type Product } from "./api";
import {
  createResourceType,
  listClassifications,
  listDailyConsumption,
  listResourceTypes,
  recordDailyConsumption,
  updateProduct,
  updateResourceType,
  type ResourceType,
} from "../production/api";

const CHART_COLORS = {
  primary: "hsl(217 91% 45%)",
  success: "hsl(142 71% 40%)",
  muted: "hsl(215 16% 65%)",
};

const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const PRODUCTION_MOVES_QUERY_KEY = ["warehouse", "stock", "moves", "production"] as const;
const CLASSIFICATIONS_QUERY_KEY = ["production", "product-classifications"] as const;
const RESOURCE_TYPES_QUERY_KEY = ["production", "resource-types"] as const;
const DAILY_CONSUMPTION_QUERY_KEY = ["production", "daily-consumption"] as const;

type PackagingUnit = "packet" | "carton" | "other";

function formatQty(amount: number) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(amount);
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

const resourceTypeSchema = z.object({
  code: z.string().min(1, "Required"),
  name: z.string().min(1, "Required"),
  unit: z.string().min(1, "Required"),
});
type ResourceTypeForm = z.infer<typeof resourceTypeSchema>;

const consumptionSchema = z.object({
  consumption_date: z.string().min(1, "Required"),
  resource_type_id: z.string().min(1, "Required"),
  quantity: z.coerce.number().min(0),
  note: z.string().optional(),
});
type ConsumptionForm = z.infer<typeof consumptionSchema>;

export function FinishedGoodsAnalysisTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();

  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: productionMoves = [] } = useQuery({
    queryKey: PRODUCTION_MOVES_QUERY_KEY,
    queryFn: () => listStockMoves(token, { move_type: "production", limit: 5000 }),
  });
  const { data: classifications = [] } = useQuery({ queryKey: CLASSIFICATIONS_QUERY_KEY, queryFn: () => listClassifications(token) });
  const { data: resourceTypes = [] } = useQuery({ queryKey: RESOURCE_TYPES_QUERY_KEY, queryFn: () => listResourceTypes(token) });
  const { data: dailyConsumption = [] } = useQuery({ queryKey: DAILY_CONSUMPTION_QUERY_KEY, queryFn: () => listDailyConsumption(token) });

  const [periodFrom, setPeriodFrom] = useState("");
  const [periodTo, setPeriodTo] = useState("");
  const [resourceTypeDialogOpen, setResourceTypeDialogOpen] = useState(false);
  const [editingResourceType, setEditingResourceType] = useState<ResourceType | null>(null);

  const productName = (productId: string) => products.find((p) => p.id === productId)?.name ?? productId;

  // Packaging unit is set explicitly per product (Production > Product Classifications),
  // not inferred from a BOM — "PL"/"PC" in product names are pasta shapes (long/short),
  // unrelated to packet-vs-carton packaging format.
  //
  // Classifications key products by sku, but a work order's product_id (and so a
  // "production" stock move's product_id) is product.id when created through the
  // Work Orders picker — so every lookup below is keyed under both forms.
  const finishedGoodIds = new Set(classifications.filter((c) => c.category === "finished_good").map((c) => c.product_id));
  const finishedGoodProductIds = new Set(products.filter((p) => finishedGoodIds.has(p.sku)).map((p) => p.id));
  const packagingUnit = new Map<string, PackagingUnit>();
  let hasUnclassifiedFinishedGood = false;
  for (const c of classifications) {
    if (c.category !== "finished_good") continue;
    const unit: PackagingUnit = c.packaging_format ?? "other";
    if (!c.packaging_format) hasUnclassifiedFinishedGood = true;
    packagingUnit.set(c.product_id, unit);
    const product = products.find((p) => p.sku === c.product_id);
    if (product) packagingUnit.set(product.id, unit);
  }

  const finishedGoodMoves = productionMoves.filter((move) => {
    if (!finishedGoodIds.has(move.product_id) && !finishedGoodProductIds.has(move.product_id)) return false;
    const day = move.created_at.slice(0, 10);
    if (periodFrom && day < periodFrom) return false;
    if (periodTo && day > periodTo) return false;
    return true;
  });

  const byDay = new Map<string, { packet: number; carton: number; other: number; tonnage: number }>();
  const byFinishedProduct = new Map<string, number>();
  let hasMissingWeight = false;
  for (const move of finishedGoodMoves) {
    const day = move.created_at.slice(0, 10);
    const unit = packagingUnit.get(move.product_id) ?? "other";
    const dayBucket = byDay.get(day) ?? { packet: 0, carton: 0, other: 0, tonnage: 0 };
    dayBucket[unit] += move.quantity;
    const product = products.find((p) => p.id === move.product_id);
    if (product?.net_weight_grams != null) {
      dayBucket.tonnage += (move.quantity * product.net_weight_grams) / 1_000_000;
    } else {
      hasMissingWeight = true;
    }
    byDay.set(day, dayBucket);
    byFinishedProduct.set(move.product_id, (byFinishedProduct.get(move.product_id) ?? 0) + move.quantity);
  }

  const dailyFinishedGoodsRows = Array.from(byDay.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, bucket]) => ({ date, ...bucket, total: bucket.packet + bucket.carton + bucket.other }));

  const finishedProductRows = Array.from(byFinishedProduct.entries())
    .map(([productId, quantity]) => ({
      productId,
      name: productName(productId),
      unit: packagingUnit.get(productId) ?? "other",
      quantity,
      product: products.find((p) => p.id === productId),
    }))
    .sort((a, b) => b.quantity - a.quantity);

  const totalPacket = dailyFinishedGoodsRows.reduce((sum, r) => sum + r.packet, 0);
  const totalCarton = dailyFinishedGoodsRows.reduce((sum, r) => sum + r.carton, 0);
  const totalOther = dailyFinishedGoodsRows.reduce((sum, r) => sum + r.other, 0);
  const totalTonnage = dailyFinishedGoodsRows.reduce((sum, r) => sum + r.tonnage, 0);

  const UNIT_LABEL: Record<PackagingUnit, string> = {
    packet: t("warehouse.analysis.finishedGoods.unit.packet"),
    carton: t("warehouse.analysis.finishedGoods.unit.carton"),
    other: t("warehouse.analysis.finishedGoods.unit.other"),
  };

  // --- Weight editing (net_weight_grams per product) ------------------------

  const updateWeightMutation = useMutation({
    mutationFn: ({ productId, netWeightGrams }: { productId: string; netWeightGrams: number }) =>
      updateProduct(token, productId, { net_weight_grams: netWeightGrams }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PRODUCTS_QUERY_KEY });
      toast.success(t("warehouse.analysis.finishedGoods.weight.saved"));
    },
    onError: (error) => {
      toast.error(t("warehouse.analysis.finishedGoods.weight.saveError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  // --- Daily resource consumption (electricity, fuel, ...) ------------------

  const resourceTypeForm = useForm<ResourceTypeForm>({ resolver: zodResolver(resourceTypeSchema) });
  const createResourceTypeMutation = useMutation({
    mutationFn: (input: ResourceTypeForm) => createResourceType(token, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: RESOURCE_TYPES_QUERY_KEY });
      setResourceTypeDialogOpen(false);
      resourceTypeForm.reset();
      toast.success(t("warehouse.analysis.consumption.resourceTypeCreated"));
    },
    onError: (error) => {
      toast.error(t("warehouse.analysis.consumption.createResourceTypeError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const updateResourceTypeMutation = useMutation({
    mutationFn: (input: ResourceTypeForm) => updateResourceType(token, editingResourceType!.id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: RESOURCE_TYPES_QUERY_KEY });
      setResourceTypeDialogOpen(false);
      setEditingResourceType(null);
      resourceTypeForm.reset();
      toast.success(t("warehouse.analysis.consumption.resourceTypeUpdated"));
    },
    onError: (error) => {
      toast.error(t("warehouse.analysis.consumption.updateResourceTypeError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  function openCreateResourceTypeDialog() {
    setEditingResourceType(null);
    resourceTypeForm.reset({ code: "", name: "", unit: "" });
    setResourceTypeDialogOpen(true);
  }

  function openEditResourceTypeDialog(resourceType: ResourceType) {
    setEditingResourceType(resourceType);
    resourceTypeForm.reset({ code: resourceType.code, name: resourceType.name, unit: resourceType.unit });
    setResourceTypeDialogOpen(true);
  }

  const consumptionForm = useForm<ConsumptionForm>({
    resolver: zodResolver(consumptionSchema),
    defaultValues: { consumption_date: todayIso(), resource_type_id: "", quantity: 0, note: "" },
  });
  const recordConsumptionMutation = useMutation({
    mutationFn: (input: ConsumptionForm) =>
      recordDailyConsumption(token, { ...input, note: input.note?.trim() || undefined }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: DAILY_CONSUMPTION_QUERY_KEY });
      consumptionForm.reset({ consumption_date: todayIso(), resource_type_id: "", quantity: 0, note: "" });
      toast.success(t("warehouse.analysis.consumption.recorded"));
    },
    onError: (error) => {
      toast.error(t("warehouse.analysis.consumption.recordError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const tonnageByDate = new Map(dailyFinishedGoodsRows.map((r) => [r.date, r.tonnage]));
  const consumptionByDate = new Map<string, typeof dailyConsumption>();
  for (const entry of dailyConsumption) {
    const list = consumptionByDate.get(entry.consumption_date) ?? [];
    list.push(entry);
    consumptionByDate.set(entry.consumption_date, list);
  }
  const allConsumptionDates = Array.from(new Set([...tonnageByDate.keys(), ...consumptionByDate.keys()])).sort().reverse();

  const totalsByResourceType = new Map<string, number>();
  for (const entry of dailyConsumption) {
    totalsByResourceType.set(entry.resource_type_id, (totalsByResourceType.get(entry.resource_type_id) ?? 0) + entry.quantity);
  }

  const dailyColumns: ColumnDef<(typeof dailyFinishedGoodsRows)[number]>[] = [
    { key: "date", header: t("warehouse.analysis.finishedGoods.column.date"), defaultWidth: 140, cell: (row) => <span className="font-medium">{row.date}</span> },
    { key: "packet", header: t("warehouse.analysis.finishedGoods.column.packet"), defaultWidth: 140, cell: (row) => <span className="tabular-nums text-muted-foreground">{formatQty(row.packet)}</span> },
    { key: "carton", header: t("warehouse.analysis.finishedGoods.column.carton"), defaultWidth: 140, cell: (row) => <span className="tabular-nums text-muted-foreground">{formatQty(row.carton)}</span> },
    { key: "other", header: t("warehouse.analysis.finishedGoods.column.other"), defaultWidth: 140, cell: (row) => <span className="tabular-nums text-muted-foreground">{formatQty(row.other)}</span> },
    { key: "total", header: t("warehouse.analysis.finishedGoods.column.total"), defaultWidth: 140, cell: (row) => <span className="tabular-nums font-medium">{formatQty(row.total)}</span> },
    { key: "tonnage", header: t("warehouse.analysis.finishedGoods.column.tonnage"), defaultWidth: 140, cell: (row) => <span className="tabular-nums text-muted-foreground">{formatQty(row.tonnage)}</span> },
  ];
  const dailyTable = useTableColumns("warehouse.finishedGoods.daily", dailyColumns);

  const byProductColumns: ColumnDef<(typeof finishedProductRows)[number]>[] = [
    { key: "name", header: t("warehouse.analysis.finishedGoods.column.product"), defaultWidth: 200, cell: (row) => <span className="font-medium">{row.name}</span> },
    { key: "unit", header: t("warehouse.analysis.finishedGoods.column.unit"), defaultWidth: 140, cell: (row) => <span className="text-muted-foreground">{UNIT_LABEL[row.unit]}</span> },
    { key: "quantity", header: t("warehouse.analysis.finishedGoods.column.quantity"), defaultWidth: 140, cell: (row) => <span className="tabular-nums text-muted-foreground">{formatQty(row.quantity)}</span> },
    {
      key: "weight",
      header: t("warehouse.analysis.finishedGoods.column.weight"),
      defaultWidth: 160,
      alwaysVisible: true,
      cell: (row) => (
        <WeightCell
          product={row.product}
          onSave={(grams) => updateWeightMutation.mutate({ productId: row.productId, netWeightGrams: grams })}
          isSaving={updateWeightMutation.isPending && updateWeightMutation.variables?.productId === row.productId}
        />
      ),
    },
  ];
  const byProductTable = useTableColumns("warehouse.finishedGoods.byProduct", byProductColumns);

  const consumptionColumns: ColumnDef<string>[] = [
    { key: "date", header: t("warehouse.analysis.consumption.column.date"), defaultWidth: 140, cell: (date) => <span className="font-medium">{date}</span> },
    {
      key: "tonnage",
      header: t("warehouse.analysis.finishedGoods.column.tonnage"),
      defaultWidth: 140,
      cell: (date) => <span className="tabular-nums text-muted-foreground">{formatQty(tonnageByDate.get(date) ?? 0)}</span>,
    },
    ...resourceTypes.map((rt): ColumnDef<string> => ({
      key: `resource:${rt.id}`,
      header: `${rt.name} (${rt.unit})`,
      defaultWidth: 140,
      cell: (date) => {
        const entries = consumptionByDate.get(date) ?? [];
        const entry = entries.find((e) => e.resource_type_id === rt.id);
        return <span className="tabular-nums text-muted-foreground">{entry ? formatQty(entry.quantity) : "—"}</span>;
      },
    })),
  ];
  const consumptionTable = useTableColumns("warehouse.finishedGoods.consumption", consumptionColumns);

  return (
    <div className="space-y-6">
      <p className="text-sm text-muted-foreground">{t("warehouse.analysis.finishedGoods.subtitle")}</p>

      <div className="flex flex-wrap items-end gap-3">
        <span className="text-sm font-medium text-muted-foreground">{t("warehouse.analysis.period.label")}</span>
        <div className="space-y-1">
          <Label htmlFor="fg-period-from" className="text-xs">
            {t("warehouse.analysis.period.from")}
          </Label>
          <Input id="fg-period-from" type="date" className="h-8 w-40" value={periodFrom} onChange={(e) => setPeriodFrom(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="fg-period-to" className="text-xs">
            {t("warehouse.analysis.period.to")}
          </Label>
          <Input id="fg-period-to" type="date" className="h-8 w-40" value={periodTo} onChange={(e) => setPeriodTo(e.target.value)} />
        </div>
        {(periodFrom || periodTo) && (
          <button
            type="button"
            className="h-8 text-sm text-muted-foreground underline-offset-2 hover:underline"
            onClick={() => {
              setPeriodFrom("");
              setPeriodTo("");
            }}
          >
            {t("warehouse.analysis.period.all")}
          </button>
        )}
      </div>

      {finishedGoodMoves.length === 0 ? (
        <Card>
          <CardContent className="p-0">
            <EmptyState
              icon={<PackageOpen className="h-5 w-5" />}
              title={t("warehouse.analysis.finishedGoods.empty.title")}
              description={t("warehouse.analysis.finishedGoods.empty.description")}
            />
          </CardContent>
        </Card>
      ) : (
        <>
          {hasUnclassifiedFinishedGood && (
            <p className="rounded-lg border border-warning/20 bg-warning-soft px-4 py-2.5 text-sm text-warning">
              {t("warehouse.analysis.finishedGoods.noBomHint")}
            </p>
          )}
          {hasMissingWeight && (
            <p className="rounded-lg border border-warning/20 bg-warning-soft px-4 py-2.5 text-sm text-warning">
              {t("warehouse.analysis.finishedGoods.missingWeightHint")}
            </p>
          )}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
            <StatCard label={t("warehouse.analysis.finishedGoods.stat.packet")} value={Math.round(totalPacket)} icon={<Package className="h-5 w-5" />} accent="primary" />
            <StatCard label={t("warehouse.analysis.finishedGoods.stat.carton")} value={Math.round(totalCarton)} icon={<Boxes className="h-5 w-5" />} accent="success" />
            <StatCard label={t("warehouse.analysis.finishedGoods.stat.other")} value={Math.round(totalOther)} icon={<PackageOpen className="h-5 w-5" />} accent="warning" />
            <StatCard
              label={t("warehouse.analysis.finishedGoods.stat.totalTonnage")}
              value={Number(totalTonnage.toFixed(2))}
              icon={<Scale className="h-5 w-5" />}
              accent="accent"
            />
          </div>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>{t("warehouse.analysis.finishedGoods.chart.title")}</CardTitle>
                <CardDescription>{t("warehouse.analysis.finishedGoods.chart.description")}</CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={dailyFinishedGoodsRows}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                  <Tooltip
                    formatter={(value) => formatQty(Number(value))}
                    contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }}
                  />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="packet" name={t("warehouse.analysis.finishedGoods.chart.packet")} stackId="fg" fill={CHART_COLORS.primary} radius={[4, 4, 0, 0]} />
                  <Bar dataKey="carton" name={t("warehouse.analysis.finishedGoods.chart.carton")} stackId="fg" fill={CHART_COLORS.success} />
                  <Bar dataKey="other" name={t("warehouse.analysis.finishedGoods.chart.other")} stackId="fg" fill={CHART_COLORS.muted} />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center gap-3">
                <CardTitle>{t("warehouse.analysis.finishedGoods.table.title")}</CardTitle>
                <ColumnVisibilityMenu
                  columns={dailyColumns}
                  isVisible={dailyTable.isVisible}
                  onToggle={dailyTable.toggleVisible}
                  onReset={dailyTable.resetAll}
                />
              </div>
            </CardHeader>
            <CardContent className="p-0">
              <Table colWidths={dailyTable.colWidths}>
                <TableHeader>
                  <TableRow>
                    {dailyTable.visibleColumns.map((column) => (
                      <ResizableTableHead
                        key={column.key}
                        width={dailyTable.getWidth(column.key)}
                        onResize={(width) => dailyTable.setWidth(column.key, width)}
                        className={column.headerClassName}
                      >
                        {column.header}
                      </ResizableTableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {dailyFinishedGoodsRows.map((row) => (
                    <TableRow key={row.date}>
                      {dailyTable.visibleColumns.map((column) => (
                        <TableCell key={column.key} className={column.cellClassName}>
                          {column.cell(row)}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center gap-3">
                <CardTitle>{t("warehouse.analysis.finishedGoods.byProduct.title")}</CardTitle>
                <ColumnVisibilityMenu
                  columns={byProductColumns}
                  isVisible={byProductTable.isVisible}
                  onToggle={byProductTable.toggleVisible}
                  onReset={byProductTable.resetAll}
                />
              </div>
            </CardHeader>
            <CardContent className="p-0">
              <Table colWidths={byProductTable.colWidths}>
                <TableHeader>
                  <TableRow>
                    {byProductTable.visibleColumns.map((column) => (
                      <ResizableTableHead
                        key={column.key}
                        width={byProductTable.getWidth(column.key)}
                        onResize={(width) => byProductTable.setWidth(column.key, width)}
                        className={column.headerClassName}
                      >
                        {column.header}
                      </ResizableTableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {finishedProductRows.map((row) => (
                    <TableRow key={row.productId}>
                      {byProductTable.visibleColumns.map((column) => (
                        <TableCell key={column.key} className={column.cellClassName}>
                          {column.cell(row)}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}

      <div>
        <h2 className="text-lg font-semibold tracking-tight">{t("warehouse.analysis.consumption.title")}</h2>
        <p className="text-sm text-muted-foreground">{t("warehouse.analysis.consumption.subtitle")}</p>
      </div>

      {resourceTypes.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {resourceTypes.map((rt) => {
            const total = totalsByResourceType.get(rt.id) ?? 0;
            const perTon = totalTonnage > 0 ? total / totalTonnage : null;
            return (
              <Card key={rt.id} className="group flex items-center gap-4 p-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-warning-soft text-warning">
                  <Zap className="h-5 w-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-2xl font-semibold tabular-nums tracking-tight">
                    {perTon !== null ? formatQty(perTon) : "—"}
                    <span className="ml-1 text-sm font-normal text-muted-foreground">{rt.unit}/t</span>
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {rt.name} · {formatQty(total)} {rt.unit} {t("warehouse.analysis.consumption.periodTotal")}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => openEditResourceTypeDialog(rt)}
                  title={t("warehouse.analysis.consumption.editResourceType")}
                  className="shrink-0 rounded-md p-1.5 text-muted-foreground opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100"
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
              </Card>
            );
          })}
        </div>
      )}

      <Card>
        <CardHeader>
          <div>
            <CardTitle>{t("warehouse.analysis.consumption.form.title")}</CardTitle>
          </div>
          <Dialog
            open={resourceTypeDialogOpen}
            onOpenChange={(open) => {
              setResourceTypeDialogOpen(open);
              if (!open) setEditingResourceType(null);
            }}
          >
            <DialogTrigger asChild>
              <Button variant="outline" size="sm" onClick={openCreateResourceTypeDialog}>
                <Plus className="h-3.5 w-3.5" />
                {t("warehouse.analysis.consumption.newResourceType")}
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>
                  {editingResourceType
                    ? t("warehouse.analysis.consumption.dialog.editResourceType.title")
                    : t("warehouse.analysis.consumption.newResourceType")}
                </DialogTitle>
                <DialogDescription>
                  {editingResourceType
                    ? t("warehouse.analysis.consumption.dialog.editResourceType.description")
                    : t("warehouse.analysis.consumption.newResourceTypeDescription")}
                </DialogDescription>
              </DialogHeader>
              <form
                className="space-y-4"
                onSubmit={resourceTypeForm.handleSubmit((input) =>
                  editingResourceType ? updateResourceTypeMutation.mutate(input) : createResourceTypeMutation.mutate(input),
                )}
              >
                <div className="space-y-1.5">
                  <Label htmlFor="rt_code">{t("warehouse.analysis.consumption.field.code")}</Label>
                  <Input id="rt_code" placeholder="e.g. electricity" {...resourceTypeForm.register("code")} />
                  {resourceTypeForm.formState.errors.code && (
                    <p className="text-sm text-destructive">{resourceTypeForm.formState.errors.code.message}</p>
                  )}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="rt_name">{t("warehouse.analysis.consumption.field.name")}</Label>
                  <Input id="rt_name" placeholder="e.g. Électricité" {...resourceTypeForm.register("name")} />
                  {resourceTypeForm.formState.errors.name && (
                    <p className="text-sm text-destructive">{resourceTypeForm.formState.errors.name.message}</p>
                  )}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="rt_unit">{t("warehouse.analysis.consumption.field.unit")}</Label>
                  <Input id="rt_unit" placeholder="e.g. kWh" {...resourceTypeForm.register("unit")} />
                  {resourceTypeForm.formState.errors.unit && (
                    <p className="text-sm text-destructive">{resourceTypeForm.formState.errors.unit.message}</p>
                  )}
                </div>
                {(editingResourceType ? updateResourceTypeMutation.isError : createResourceTypeMutation.isError) && (
                  <p className="text-sm text-destructive">
                    {(editingResourceType ? updateResourceTypeMutation.error : createResourceTypeMutation.error) instanceof ApiError
                      ? (editingResourceType ? updateResourceTypeMutation.error : createResourceTypeMutation.error)?.message
                      : t(
                          editingResourceType
                            ? "warehouse.analysis.consumption.updateResourceTypeError"
                            : "warehouse.analysis.consumption.createResourceTypeError",
                        )}
                  </p>
                )}
                <Button
                  type="submit"
                  className="w-full"
                  disabled={editingResourceType ? updateResourceTypeMutation.isPending : createResourceTypeMutation.isPending}
                >
                  {editingResourceType
                    ? updateResourceTypeMutation.isPending
                      ? t("warehouse.analysis.consumption.updatingResourceType")
                      : t("warehouse.analysis.consumption.updateResourceType")
                    : t("warehouse.analysis.consumption.newResourceType")}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
        </CardHeader>
        <CardContent>
          {resourceTypes.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("warehouse.analysis.consumption.noResourceTypes")}</p>
          ) : (
            <form
              className="grid grid-cols-1 gap-3 sm:grid-cols-5 sm:items-end"
              onSubmit={consumptionForm.handleSubmit((input) => recordConsumptionMutation.mutate(input))}
            >
              <div className="space-y-1.5">
                <Label htmlFor="consumption_date">{t("warehouse.analysis.consumption.field.date")}</Label>
                <Input id="consumption_date" type="date" {...consumptionForm.register("consumption_date")} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="resource_type_id">{t("warehouse.analysis.consumption.field.resourceType")}</Label>
                <Select id="resource_type_id" {...consumptionForm.register("resource_type_id")}>
                  <option value="">—</option>
                  {resourceTypes.map((rt) => (
                    <option key={rt.id} value={rt.id}>
                      {rt.name} ({rt.unit})
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="quantity">{t("warehouse.analysis.consumption.field.quantity")}</Label>
                <Input id="quantity" type="number" step="any" {...consumptionForm.register("quantity")} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="note">{t("warehouse.analysis.consumption.field.note")}</Label>
                <Input id="note" {...consumptionForm.register("note")} />
              </div>
              <Button type="submit" disabled={recordConsumptionMutation.isPending}>
                {recordConsumptionMutation.isPending ? t("warehouse.analysis.consumption.recording") : t("warehouse.analysis.consumption.record")}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>

      {allConsumptionDates.length > 0 && (
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-center gap-3">
              <CardTitle>{t("warehouse.analysis.consumption.table.title")}</CardTitle>
              <ColumnVisibilityMenu
                columns={consumptionColumns}
                isVisible={consumptionTable.isVisible}
                onToggle={consumptionTable.toggleVisible}
                onReset={consumptionTable.resetAll}
              />
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <Table colWidths={consumptionTable.colWidths}>
              <TableHeader>
                <TableRow>
                  {consumptionTable.visibleColumns.map((column) => (
                    <ResizableTableHead
                      key={column.key}
                      width={consumptionTable.getWidth(column.key)}
                      onResize={(width) => consumptionTable.setWidth(column.key, width)}
                      className={column.headerClassName}
                    >
                      {column.header}
                    </ResizableTableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {allConsumptionDates.map((date) => (
                  <TableRow key={date}>
                    {consumptionTable.visibleColumns.map((column) => (
                      <TableCell key={column.key} className={column.cellClassName}>
                        {column.cell(date)}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function WeightCell({
  product,
  onSave,
  isSaving,
}: {
  product: Product | undefined;
  onSave: (grams: number) => void;
  isSaving: boolean;
}) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(() => String(product?.net_weight_grams ?? ""));

  if (!editing) {
    return (
      <button
        type="button"
        className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        onClick={() => {
          setValue(String(product?.net_weight_grams ?? ""));
          setEditing(true);
        }}
      >
        {product?.net_weight_grams != null ? `${formatQty(product.net_weight_grams)} g` : t("warehouse.analysis.finishedGoods.weight.unset")}
        <Pencil className="h-3 w-3" />
      </button>
    );
  }

  return (
    <div className="flex items-center gap-1.5">
      <Input
        type="number"
        step="any"
        className="h-8 w-24"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        autoFocus
      />
      <Button
        size="sm"
        variant="outline"
        disabled={isSaving || !value || Number(value) <= 0}
        onClick={() => {
          onSave(Number(value));
          setEditing(false);
        }}
      >
        {t("common.save")}
      </Button>
    </div>
  );
}
