import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, Package, PackageOpen, Pencil, Scale } from "lucide-react";
import { toast } from "sonner";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useAuth } from "../../lib/auth";
import { currentLocale, useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { listProducts, listStockMoves } from "./api";
import {
  listClassifications,
  listPackagingVariance,
  updateProduct,
  type ProductPackagingVariance,
} from "../production/api";
import { PackagingVariancePanel } from "../production/PackagingVariancePanel";

const CHART_COLORS = {
  primary: "hsl(217 91% 45%)",
  success: "hsl(142 71% 40%)",
  muted: "hsl(215 16% 65%)",
};

// A distinct line per finished product, cycled if there are more products than colors.
const TREND_LINE_COLORS = [
  "hsl(217 91% 45%)",
  "hsl(142 71% 40%)",
  "hsl(31 91% 48%)",
  "hsl(271 76% 53%)",
  "hsl(199 89% 42%)",
];

const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
// Unfiltered: production output and manual corrections both need to be visible
// here, and the API only supports filtering on one move_type at a time.
const FINISHED_GOODS_MOVES_QUERY_KEY = ["warehouse", "stock", "moves", "finished-goods"] as const;
const CLASSIFICATIONS_QUERY_KEY = ["production", "product-classifications"] as const;

const ADJUSTMENT_MOVE_TYPES = new Set(["adjustment", "admin_correction"]);

type PackagingUnit = "packet" | "carton" | "other";

function formatQty(amount: number) {
  return new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 2 }).format(amount);
}

export function FinishedGoodsAnalysisTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();

  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: stockMoves = [] } = useQuery({
    queryKey: FINISHED_GOODS_MOVES_QUERY_KEY,
    queryFn: () => listStockMoves(token, { limit: 5000 }),
  });
  const { data: classifications = [] } = useQuery({ queryKey: CLASSIFICATIONS_QUERY_KEY, queryFn: () => listClassifications(token) });

  const [periodFrom, setPeriodFrom] = useState("");
  const [periodTo, setPeriodTo] = useState("");

  // The écart is production's calculation, not the warehouse's — this screen
  // reads it rather than recomputing it, so the two can never disagree.
  const { data: varianceRows = [], isLoading: varianceLoading } = useQuery({
    queryKey: ["production", "packaging-variance", "by-product", periodFrom, periodTo],
    queryFn: () =>
      listPackagingVariance(token, {
        date_from: periodFrom || undefined,
        date_to: periodTo || undefined,
      }),
  });

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
    // Sac is a real classification but isn't tracked as its own bucket on this
    // packet-vs-carton dashboard, so it counts toward "other" here rather than
    // toward the unclassified hint (which is only about products with no format set).
    const unit: PackagingUnit = c.packaging_format === "packet" || c.packaging_format === "carton" ? c.packaging_format : "other";
    if (!c.packaging_format) hasUnclassifiedFinishedGood = true;
    packagingUnit.set(c.product_id, unit);
    const product = products.find((p) => p.sku === c.product_id);
    if (product) packagingUnit.set(product.id, unit);
  }

  const finishedGoodMoves = stockMoves.filter((move) => {
    if (!finishedGoodIds.has(move.product_id) && !finishedGoodProductIds.has(move.product_id)) return false;
    const day = move.created_at.slice(0, 10);
    if (periodFrom && day < periodFrom) return false;
    if (periodTo && day > periodTo) return false;
    return true;
  });

  // Only completed work orders post a "production" move — that's the figure the
  // charts and the packaging écart are built on. A physical-count correction
  // (adjustment / admin_correction) is a different thing: it doesn't represent
  // output, so it's tracked and shown separately rather than folded into it,
  // which would silently inflate or deflate what the line actually produced.
  const productionMoves = finishedGoodMoves.filter((move) => move.move_type === "production");
  const adjustmentMoves = finishedGoodMoves.filter((move) => ADJUSTMENT_MOVE_TYPES.has(move.move_type));

  const byDay = new Map<string, { packet: number; carton: number; other: number; tonnage: number }>();
  const byFinishedProduct = new Map<string, number>();
  let hasMissingWeight = false;
  for (const move of productionMoves) {
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

  const byDayAdjustment = new Map<string, number>();
  const byProductAdjustment = new Map<string, number>();
  for (const move of adjustmentMoves) {
    const day = move.created_at.slice(0, 10);
    byDayAdjustment.set(day, (byDayAdjustment.get(day) ?? 0) + move.quantity);
    byProductAdjustment.set(move.product_id, (byProductAdjustment.get(move.product_id) ?? 0) + move.quantity);
  }

  const allDays = new Set([...byDay.keys(), ...byDayAdjustment.keys()]);
  const dailyFinishedGoodsRows = Array.from(allDays)
    .sort((a, b) => a.localeCompare(b))
    .map((date) => {
      const bucket = byDay.get(date) ?? { packet: 0, carton: 0, other: 0, tonnage: 0 };
      return {
        date,
        ...bucket,
        total: bucket.packet + bucket.carton + bucket.other,
        adjustment: byDayAdjustment.get(date) ?? 0,
      };
    });

  const allFinishedProductIds = new Set([...byFinishedProduct.keys(), ...byProductAdjustment.keys()]);
  const finishedProductRows = Array.from(allFinishedProductIds)
    .map((productId) => ({
      productId,
      name: productName(productId),
      unit: packagingUnit.get(productId) ?? "other",
      quantity: byFinishedProduct.get(productId) ?? 0,
      adjustment: byProductAdjustment.get(productId) ?? 0,
      product: products.find((p) => p.id === productId),
    }))
    .sort((a, b) => b.quantity - a.quantity);

  const totalPacket = dailyFinishedGoodsRows.reduce((sum, r) => sum + r.packet, 0);
  const totalCarton = dailyFinishedGoodsRows.reduce((sum, r) => sum + r.carton, 0);
  const totalOther = dailyFinishedGoodsRows.reduce((sum, r) => sum + r.other, 0);
  const totalTonnage = dailyFinishedGoodsRows.reduce((sum, r) => sum + r.tonnage, 0);
  const totalAdjustment = dailyFinishedGoodsRows.reduce((sum, r) => sum + r.adjustment, 0);
  const hasAdjustments = adjustmentMoves.length > 0;

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
      queryClient.invalidateQueries({ queryKey: ["production", "packaging-variance"] });
      toast.success(t("warehouse.analysis.finishedGoods.weight.saved"));
    },
    onError: (error) => {
      toast.error(t("warehouse.analysis.finishedGoods.weight.saveError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const updatePerCartonMutation = useMutation({
    mutationFn: ({ productId, packetsPerCarton }: { productId: string; packetsPerCarton: number }) =>
      updateProduct(token, productId, { packets_per_carton: packetsPerCarton }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PRODUCTS_QUERY_KEY });
      // The écart is computed from these, so it has to be refetched with them.
      queryClient.invalidateQueries({ queryKey: ["production", "packaging-variance"] });
      toast.success(t("warehouse.analysis.finishedGoods.perCarton.saved"));
    },
    onError: (error) => {
      toast.error(t("warehouse.analysis.finishedGoods.perCarton.saveError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const dailyColumns: ColumnDef<(typeof dailyFinishedGoodsRows)[number]>[] = [
    {
      key: "date",
      header: t("warehouse.analysis.finishedGoods.column.date"),
      defaultWidth: 140,
      cell: (row) => <span className="font-medium">{row.date}</span>,
      sortValue: (row) => row.date,
    },
    {
      key: "packet",
      header: t("warehouse.analysis.finishedGoods.column.packet"),
      defaultWidth: 140,
      cell: (row) => <span className="tabular-nums text-muted-foreground">{formatQty(row.packet)}</span>,
      sortValue: (row) => row.packet,
    },
    {
      key: "carton",
      header: t("warehouse.analysis.finishedGoods.column.carton"),
      defaultWidth: 140,
      cell: (row) => <span className="tabular-nums text-muted-foreground">{formatQty(row.carton)}</span>,
      sortValue: (row) => row.carton,
    },
    {
      key: "other",
      header: t("warehouse.analysis.finishedGoods.column.other"),
      defaultWidth: 140,
      cell: (row) => <span className="tabular-nums text-muted-foreground">{formatQty(row.other)}</span>,
      sortValue: (row) => row.other,
    },
    {
      key: "total",
      header: t("warehouse.analysis.finishedGoods.column.total"),
      defaultWidth: 140,
      cell: (row) => <span className="tabular-nums font-medium">{formatQty(row.total)}</span>,
      sortValue: (row) => row.total,
    },
    {
      key: "tonnage",
      header: t("warehouse.analysis.finishedGoods.column.tonnage"),
      defaultWidth: 140,
      cell: (row) => <span className="tabular-nums text-muted-foreground">{formatQty(row.tonnage)}</span>,
      sortValue: (row) => row.tonnage,
    },
    {
      key: "adjustment",
      header: t("warehouse.analysis.finishedGoods.column.adjustment"),
      defaultWidth: 150,
      cell: (row) =>
        row.adjustment === 0 ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          <span className={`tabular-nums ${row.adjustment < 0 ? "text-destructive" : "text-success"}`}>
            {row.adjustment > 0 ? "+" : ""}
            {formatQty(row.adjustment)}
          </span>
        ),
      sortValue: (row) => row.adjustment,
    },
  ];
  const dailyTable = useTableColumns("warehouse.finishedGoods.daily", dailyColumns);
  const sortedDailyRows = dailyTable.sortRows(dailyFinishedGoodsRows);

  const byProductColumns: ColumnDef<(typeof finishedProductRows)[number]>[] = [
    {
      key: "name",
      header: t("warehouse.analysis.finishedGoods.column.product"),
      defaultWidth: 200,
      cell: (row) => <span className="font-medium">{row.name}</span>,
      sortValue: (row) => row.name,
    },
    {
      key: "unit",
      header: t("warehouse.analysis.finishedGoods.column.unit"),
      defaultWidth: 140,
      cell: (row) => <span className="text-muted-foreground">{UNIT_LABEL[row.unit]}</span>,
      sortValue: (row) => UNIT_LABEL[row.unit],
    },
    {
      key: "quantity",
      header: t("warehouse.analysis.finishedGoods.column.quantity"),
      defaultWidth: 140,
      cell: (row) => <span className="tabular-nums text-muted-foreground">{formatQty(row.quantity)}</span>,
      sortValue: (row) => row.quantity,
    },
    {
      key: "weight",
      header: t("warehouse.analysis.finishedGoods.column.weight"),
      defaultWidth: 160,
      alwaysVisible: true,
      cell: (row) => (
        <ParameterCell
          value={row.product?.net_weight_grams}
          suffix="g"
          unsetLabel={t("warehouse.analysis.finishedGoods.weight.unset")}
          onSave={(grams) => updateWeightMutation.mutate({ productId: row.productId, netWeightGrams: grams })}
          isSaving={updateWeightMutation.isPending && updateWeightMutation.variables?.productId === row.productId}
        />
      ),
      sortValue: (row) => row.product?.net_weight_grams,
    },
    {
      key: "packetsPerCarton",
      header: t("warehouse.analysis.finishedGoods.column.packetsPerCarton"),
      defaultWidth: 170,
      alwaysVisible: true,
      cell: (row) => (
        <ParameterCell
          value={row.product?.packets_per_carton}
          unsetLabel={t("warehouse.analysis.finishedGoods.perCarton.unset")}
          onSave={(perCarton) =>
            updatePerCartonMutation.mutate({ productId: row.productId, packetsPerCarton: perCarton })
          }
          isSaving={
            updatePerCartonMutation.isPending &&
            updatePerCartonMutation.variables?.productId === row.productId
          }
        />
      ),
      sortValue: (row) => row.product?.packets_per_carton,
    },
    {
      key: "adjustment",
      header: t("warehouse.analysis.finishedGoods.column.adjustment"),
      defaultWidth: 150,
      cell: (row) =>
        row.adjustment === 0 ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          <span className={`tabular-nums ${row.adjustment < 0 ? "text-destructive" : "text-success"}`}>
            {row.adjustment > 0 ? "+" : ""}
            {formatQty(row.adjustment)}
          </span>
        ),
      sortValue: (row) => row.adjustment,
    },
  ];
  const byProductTable = useTableColumns("warehouse.finishedGoods.byProduct", byProductColumns);
  const sortedProductRows = byProductTable.sortRows(finishedProductRows);

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
          {hasAdjustments && (
            <p className="rounded-lg border border-border bg-muted/40 px-4 py-2.5 text-sm text-muted-foreground">
              {t("warehouse.analysis.finishedGoods.adjustmentHint")}
            </p>
          )}

          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            {t("warehouse.analysis.finishedGoods.help.packagingLabel")}
            <HelpTooltip text={t("warehouse.analysis.finishedGoods.help.packaging")} />
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <StatCard label={t("warehouse.analysis.finishedGoods.stat.packet")} value={Math.round(totalPacket)} icon={<Package className="h-5 w-5" />} accent="primary" />
            <StatCard label={t("warehouse.analysis.finishedGoods.stat.carton")} value={Math.round(totalCarton)} icon={<Boxes className="h-5 w-5" />} accent="success" />
            <StatCard label={t("warehouse.analysis.finishedGoods.stat.other")} value={Math.round(totalOther)} icon={<PackageOpen className="h-5 w-5" />} accent="warning" />
            <StatCard
              label={t("warehouse.analysis.finishedGoods.stat.totalTonnage")}
              value={Number(totalTonnage.toFixed(2))}
              icon={<Scale className="h-5 w-5" />}
              accent="accent"
            />
            <StatCard
              label={t("warehouse.analysis.finishedGoods.stat.adjustment")}
              value={Math.round(totalAdjustment)}
              icon={<Pencil className="h-5 w-5" />}
              accent="destructive"
            />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>{t("warehouse.analysis.finishedGoods.chart.packetTitle")}</CardTitle>
                  <CardDescription>{t("warehouse.analysis.finishedGoods.chart.packetDescription")}</CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={dailyFinishedGoodsRows}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" vertical={false} />
                    <XAxis dataKey="date" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                    <Tooltip
                      formatter={(value) => formatQty(Number(value))}
                      contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }}
                    />
                    <Bar dataKey="packet" name={t("warehouse.analysis.finishedGoods.chart.packet")} fill={CHART_COLORS.primary} radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div>
                  <CardTitle>{t("warehouse.analysis.finishedGoods.chart.cartonTitle")}</CardTitle>
                  <CardDescription>{t("warehouse.analysis.finishedGoods.chart.cartonDescription")}</CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={dailyFinishedGoodsRows}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" vertical={false} />
                    <XAxis dataKey="date" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                    <Tooltip
                      formatter={(value) => formatQty(Number(value))}
                      contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }}
                    />
                    <Bar dataKey="carton" name={t("warehouse.analysis.finishedGoods.chart.carton")} fill={CHART_COLORS.success} radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </div>

          {totalOther > 0 && (
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>{t("warehouse.analysis.finishedGoods.chart.otherTitle")}</CardTitle>
                  <CardDescription>{t("warehouse.analysis.finishedGoods.chart.otherDescription")}</CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={dailyFinishedGoodsRows}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" vertical={false} />
                    <XAxis dataKey="date" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                    <Tooltip
                      formatter={(value) => formatQty(Number(value))}
                      contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }}
                    />
                    <Bar dataKey="other" name={t("warehouse.analysis.finishedGoods.chart.other")} fill={CHART_COLORS.muted} radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}

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
                        sortDirection={dailyTable.sortDirectionFor(column.key)}
                        onSort={column.sortValue ? () => dailyTable.toggleSort(column.key) : undefined}
                      >
                        {column.header}
                      </ResizableTableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedDailyRows.map((row) => (
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
                        sortDirection={byProductTable.sortDirectionFor(column.key)}
                        onSort={column.sortValue ? () => byProductTable.toggleSort(column.key) : undefined}
                      >
                        {column.header}
                      </ResizableTableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedProductRows.map((row) => (
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

      {/* The écart, last: it only means anything once the two parameters above it
          are set, and putting it under them makes that order obvious. */}
      <PackagingVarianceTrendChart rows={varianceRows} productName={productName} />
      <PackagingVarianceSection
        rows={varianceRows}
        productName={productName}
        isLoading={varianceLoading}
      />
    </div>
  );
}

/**
 * Packet écart, as a percentage, per validated report — one line per finished
 * product so a drift specific to one SKU doesn't hide in an average. Gross
 * (report-level), same caveat as the panels below: quality's adjustment only
 * applies at the product/OF grain, not to a single shift.
 */
function PackagingVarianceTrendChart({
  rows,
  productName,
}: {
  rows: ProductPackagingVariance[];
  productName: (productId: string) => string;
}) {
  const { t } = useI18n();

  const byDate = new Map<string, Record<string, string | number>>();
  for (const productRow of rows) {
    const name = productName(productRow.product_id);
    for (const report of productRow.reports) {
      if (report.packet_variance_ratio === null) continue;
      const bucket = byDate.get(report.report_date) ?? { date: report.report_date };
      bucket[name] = Math.round(report.packet_variance_ratio * 1000) / 10;
      byDate.set(report.report_date, bucket);
    }
  }
  const trendRows = Array.from(byDate.values()).sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const productNames = Array.from(new Set(rows.map((r) => productName(r.product_id))));

  if (trendRows.length < 2) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("warehouse.analysis.finishedGoods.varianceTrend.title")}</CardTitle>
        <CardDescription>{t("warehouse.analysis.finishedGoods.varianceTrend.subtitle")}</CardDescription>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={trendRows}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" vertical={false} />
            <XAxis dataKey="date" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
            <YAxis
              tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(value) => `${value}%`}
            />
            <Tooltip
              formatter={(value) => `${value}%`}
              contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <ReferenceLine y={0} stroke="hsl(215 16% 65%)" strokeDasharray="4 4" />
            {productNames.map((name, index) => (
              <Line
                key={name}
                type="monotone"
                dataKey={name}
                stroke={TREND_LINE_COLORS[index % TREND_LINE_COLORS.length]}
                strokeWidth={2}
                dot={{ r: 3 }}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

/**
 * Écart net per finished product: what the reported tonnage should have packed,
 * against what the line counted, less what quality pulled.
 *
 * Read-only — decision 22. The per-report rows underneath carry their own date
 * and are gross, because a non-conformity attaches to an OF and not to a shift:
 * an NC raised a week later cannot honestly be pinned on the Tuesday run.
 */
function PackagingVarianceSection({
  rows,
  productName,
  isLoading,
}: {
  rows: ProductPackagingVariance[];
  productName: (productId: string) => string;
  isLoading: boolean;
}) {
  const { t } = useI18n();

  if (isLoading) return null;

  if (rows.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("warehouse.analysis.finishedGoods.variance.title")}</CardTitle>
          <CardDescription>{t("warehouse.analysis.finishedGoods.variance.subtitle")}</CardDescription>
        </CardHeader>
        <CardContent>
          <EmptyState
            icon={<Scale className="h-8 w-8" />}
            title={t("warehouse.analysis.finishedGoods.variance.empty")}
            description={t("warehouse.analysis.finishedGoods.variance.emptyHint")}
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("warehouse.analysis.finishedGoods.variance.title")}</CardTitle>
        <CardDescription>{t("warehouse.analysis.finishedGoods.variance.subtitle")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {rows.map((row) => (
          <div key={row.product_id} className="space-y-2">
            <p className="text-sm font-medium">{productName(row.product_id)}</p>
            <PackagingVariancePanel variance={row} net />
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

/**
 * One editable packaging parameter, in place in the table.
 *
 * Phase 9, decision 20: the net weight and the packets per carton are both
 * properties of the product and are edited here, together, because they are only
 * meaningful as a pair — a weight without a carton count gives packets and no
 * cartons, and a carton count without a weight gives neither.
 */
function ParameterCell({
  value: current,
  suffix,
  unsetLabel,
  onSave,
  isSaving,
}: {
  value: number | null | undefined;
  suffix?: string;
  unsetLabel: string;
  onSave: (value: number) => void;
  isSaving: boolean;
}) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(() => String(current ?? ""));

  if (!editing) {
    return (
      <button
        type="button"
        className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        onClick={() => {
          setValue(String(current ?? ""));
          setEditing(true);
        }}
      >
        {current != null ? `${formatQty(current)}${suffix ? ` ${suffix}` : ""}` : unsetLabel}
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
