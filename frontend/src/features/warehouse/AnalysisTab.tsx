import { useMemo, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Boxes, Coins, Send, TrendingUp } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";
import { InteractiveChart } from "../../components/charts/InteractiveChart";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../lib/auth";
import { currentLocale, useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../components/ui/dialog";
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import {
  getCostSummary,
  listConfirmedReceiptLineDetails,
  listProducts,
  listStock,
  listUoms,
  type CostSummaryRow,
  type Product,
  type ReceiptLineDetail,
} from "./api";
import { listPartners } from "../partners/api";
import { createPurchaseOrder } from "../procurement/api";

interface DesignationRow {
  productId: string;
  name: string;
  totalTons: number;
  totalCost: number;
  avgCostPerTon: number;
  count: number;
}

interface BestCostRow extends CostSummaryRow {
  name: string;
  unitLabel: string;
  isBestForProduct: boolean;
}

interface AnomalyRow extends ReceiptLineDetail {
  name: string;
  unitLabel: string;
}

const CHART_COLORS = {
  primary: "hsl(217 91% 45%)",
  primarySoft: "hsl(217 91% 88%)",
  accent: "hsl(258 90% 66%)",
};

const RECEIPTS_QUERY_KEY = ["procurement", "receipt-lines"] as const;
const COST_SUMMARY_QUERY_KEY = ["procurement", "cost-summary"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const UOMS_QUERY_KEY = ["core", "uoms"] as const;
const STOCK_QUERY_KEY = ["warehouse", "stock"] as const;
const PARTNERS_QUERY_KEY = ["core", "partners"] as const;
const PURCHASE_ORDERS_QUERY_KEY = ["procurement", "purchase-orders"] as const;

const orderSchema = z.object({
  supplier_id: z.string().optional(),
  quantity_ordered: z.coerce.number().positive("Must be > 0"),
});
type OrderForm = z.infer<typeof orderSchema>;

function formatMoney(amount: number) {
  return new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 0 }).format(amount);
}

export function AnalysisTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();

  const { data: allReceipts = [] } = useQuery({ queryKey: RECEIPTS_QUERY_KEY, queryFn: () => listConfirmedReceiptLineDetails(token) });
  const { data: costSummary = [] } = useQuery({ queryKey: COST_SUMMARY_QUERY_KEY, queryFn: () => getCostSummary(token) });
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: uoms = [] } = useQuery({ queryKey: UOMS_QUERY_KEY, queryFn: () => listUoms(token) });
  const { data: stockItems = [] } = useQuery({ queryKey: STOCK_QUERY_KEY, queryFn: () => listStock(token) });
  const { data: partners = [] } = useQuery({ queryKey: PARTNERS_QUERY_KEY, queryFn: () => listPartners(token) });
  const suppliers = partners.filter((p) => (p.kind === "supplier" || p.kind === "both") && p.status === "active");
  // The printed form, not the code: "pièce" is what a reader expects beside a
  // count, and `code` stays the key imports and integrations match on.
  const uomCode = (uomId: string) => {
    const uom = uoms.find((u) => u.id === uomId);
    return uom ? uom.symbol || uom.code : uomId;
  };

  const onHandByProduct = new Map<string, number>();
  for (const item of stockItems) {
    onHandByProduct.set(item.product_id, (onHandByProduct.get(item.product_id) ?? 0) + item.quantity_on_hand);
  }
  const alertRows = products
    .filter((p): p is Product & { stock_alert_threshold: number } => p.stock_alert_threshold != null)
    .map((product) => ({ product, onHand: onHandByProduct.get(product.id) ?? 0, threshold: product.stock_alert_threshold }))
    .filter((row) => row.onHand < row.threshold)
    .sort((a, b) => a.onHand - a.threshold - (b.onHand - b.threshold));

  const [orderingProduct, setOrderingProduct] = useState<Product | null>(null);
  const orderForm = useForm<OrderForm>({ resolver: zodResolver(orderSchema) });
  const createOrderMutation = useMutation({
    mutationFn: (input: OrderForm) =>
      createPurchaseOrder(token, {
        lines: [{ product_id: orderingProduct!.id, uom_id: orderingProduct!.uom_id, quantity_ordered: input.quantity_ordered }],
        supplier_id: input.supplier_id || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PURCHASE_ORDERS_QUERY_KEY });
      setOrderingProduct(null);
      orderForm.reset();
      toast.success(t("warehouse.analysis.alerts.ordered"));
    },
    onError: (error) => {
      toast.error(t("warehouse.analysis.alerts.orderError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  function openOrderDialog(product: Product, deficit: number) {
    setOrderingProduct(product);
    orderForm.reset({ supplier_id: "", quantity_ordered: Math.max(1, Math.ceil(deficit)) });
  }

  const [periodFrom, setPeriodFrom] = useState("");
  const [periodTo, setPeriodTo] = useState("");

  // This tab is a landed-cost-per-ton analysis, so it's scoped to weight-based receipts
  // (kg/ton) only, normalized to tons — same rule as the cost-by-product summary above it.
  // Piece/volume/length receipts (cartons, film, tape, ...) aren't meaningfully summed here.
  const tonsEquivalent = (receipt: { quantity: number; uom_id: string }): number | null => {
    const uom = uoms.find((u) => u.id === receipt.uom_id);
    if (!uom || uom.category !== "weight") return null;
    return (receipt.quantity * uom.ratio_to_base) / 1000;
  };

  const receipts = useMemo(
    () =>
      allReceipts.filter((r) => {
        if (!r.invoice_date) return periodFrom === "" && periodTo === "";
        if (periodFrom && r.invoice_date < periodFrom) return false;
        if (periodTo && r.invoice_date > periodTo) return false;
        return true;
      }),
    [allReceipts, periodFrom, periodTo],
  );

  const productName = (productId: string) => products.find((p) => p.id === productId)?.name ?? productId;

  const byDesignation = new Map<string, { totalTons: number; totalCost: number; count: number }>();
  for (const receipt of receipts) {
    const tons = tonsEquivalent(receipt);
    if (tons === null) continue;
    const bucket = byDesignation.get(receipt.product_id) ?? { totalTons: 0, totalCost: 0, count: 0 };
    bucket.totalTons += tons;
    // total_cost_base (not total_cost): receipts can be priced in different currencies
    // (local CFA vs. imported EUR/TRY) -- summing their own-currency totals directly
    // would silently add unlike amounts together.
    bucket.totalCost += receipt.total_cost_base;
    bucket.count += 1;
    byDesignation.set(receipt.product_id, bucket);
  }
  const designationRows = Array.from(byDesignation.entries())
    .map(([productId, bucket]) => ({
      productId,
      name: productName(productId),
      totalTons: bucket.totalTons,
      totalCost: bucket.totalCost,
      avgCostPerTon: bucket.totalTons > 0 ? bucket.totalCost / bucket.totalTons : 0,
      count: bucket.count,
    }))
    .sort((a, b) => b.totalCost - a.totalCost);

  const byMonth = new Map<string, { totalTons: number; totalCost: number }>();
  for (const receipt of receipts) {
    if (!receipt.invoice_date) continue;
    const tons = tonsEquivalent(receipt);
    if (tons === null) continue;
    const month = receipt.invoice_date.slice(0, 7);
    const bucket = byMonth.get(month) ?? { totalTons: 0, totalCost: 0 };
    bucket.totalTons += tons;
    bucket.totalCost += receipt.total_cost_base;
    byMonth.set(month, bucket);
  }
  const trendData = Array.from(byMonth.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([month, bucket]) => ({
      month,
      avgCostPerTon: bucket.totalTons > 0 ? Math.round(bucket.totalCost / bucket.totalTons) : 0,
    }));

  const weightReceipts = receipts.filter((r) => tonsEquivalent(r) !== null);
  const totalTons = weightReceipts.reduce((sum, r) => sum + (tonsEquivalent(r) ?? 0), 0);
  const totalSpend = weightReceipts.reduce((sum, r) => sum + r.total_cost_base, 0);
  const avgCostPerTon = totalTons > 0 ? totalSpend / totalTons : 0;

  const byDesignationColumns: ColumnDef<DesignationRow>[] = [
    {
      key: "name",
      header: t("warehouse.analysis.column.designation"),
      defaultWidth: 200,
      cell: (row) => <span className="font-medium">{row.name}</span>,
      sortValue: (row) => row.name,
    },
    {
      key: "totalTons",
      header: t("warehouse.analysis.column.totalTons"),
      defaultWidth: 140,
      cell: (row) => <span className="tabular-nums text-muted-foreground">{row.totalTons}</span>,
      sortValue: (row) => row.totalTons,
    },
    {
      key: "totalCost",
      header: t("warehouse.analysis.column.totalCost"),
      defaultWidth: 140,
      cell: (row) => <span className="tabular-nums text-muted-foreground">{formatMoney(row.totalCost)}</span>,
      sortValue: (row) => row.totalCost,
    },
    {
      key: "avgCostPerTon",
      header: t("warehouse.analysis.column.avgCostPerTon"),
      defaultWidth: 160,
      cell: (row) => <span className="tabular-nums text-muted-foreground">{formatMoney(row.avgCostPerTon)}</span>,
      sortValue: (row) => row.avgCostPerTon,
    },
    {
      key: "count",
      header: t("warehouse.analysis.column.receipts"),
      defaultWidth: 120,
      cell: (row) => <span className="tabular-nums text-muted-foreground">{row.count}</span>,
      sortValue: (row) => row.count,
    },
  ];
  const byDesignationTable = useTableColumns("warehouse.analysis.byDesignation", byDesignationColumns);
  const sortedDesignationRows = byDesignationTable.sortRows(designationRows);

  // Best cost per material, split by origin/supplier and import-vs-local -- answers "what's
  // the cheapest this semoule has landed at, and where from" (point 5 of the MP cost plan),
  // never blending origins the way the designation table above intentionally does.
  const bestCostByProduct = new Map<string, number>();
  for (const row of costSummary) {
    const current = bestCostByProduct.get(row.product_id);
    if (current === undefined || row.best_cost_per_unit < current) {
      bestCostByProduct.set(row.product_id, row.best_cost_per_unit);
    }
  }
  const bestCostRows: BestCostRow[] = costSummary
    .map((row) => ({
      ...row,
      name: productName(row.product_id),
      unitLabel: uomCode(row.uom_id),
      isBestForProduct: row.best_cost_per_unit === bestCostByProduct.get(row.product_id),
    }))
    .sort((a, b) => a.name.localeCompare(b.name) || a.best_cost_per_unit - b.best_cost_per_unit);

  const bestCostColumns: ColumnDef<BestCostRow>[] = [
    {
      key: "name",
      header: t("warehouse.analysis.bestCost.column.designation"),
      defaultWidth: 200,
      cell: (row) => <span className="font-medium">{row.name}</span>,
      sortValue: (row) => row.name,
    },
    {
      key: "origin",
      header: t("warehouse.analysis.bestCost.column.origin"),
      defaultWidth: 140,
      cell: (row) => <span className="text-muted-foreground">{row.origin_country || "—"}</span>,
      sortValue: (row) => row.origin_country ?? "",
    },
    {
      key: "isImport",
      header: t("warehouse.analysis.bestCost.column.type"),
      defaultWidth: 110,
      cell: (row) => (
        <Badge variant={row.is_import ? "accent" : "default"}>
          {row.is_import ? t("procurement.field.import") : t("procurement.field.local")}
        </Badge>
      ),
      sortValue: (row) => (row.is_import ? 1 : 0),
    },
    {
      key: "averageCostPerUnit",
      header: t("warehouse.analysis.bestCost.column.average"),
      defaultWidth: 150,
      cell: (row) => (
        <span className="tabular-nums text-muted-foreground">
          {formatMoney(row.average_cost_per_unit)} / {row.unitLabel}
        </span>
      ),
      sortValue: (row) => row.average_cost_per_unit,
    },
    {
      key: "bestCostPerUnit",
      header: t("warehouse.analysis.bestCost.column.best"),
      defaultWidth: 160,
      cell: (row) => (
        <span className={`tabular-nums ${row.isBestForProduct ? "font-semibold text-success" : "text-muted-foreground"}`}>
          {formatMoney(row.best_cost_per_unit)} / {row.unitLabel}
          {row.isBestForProduct && <Badge variant="success" className="ml-2">{t("warehouse.analysis.bestCost.badge")}</Badge>}
        </span>
      ),
      sortValue: (row) => row.best_cost_per_unit,
    },
    {
      key: "receiptCount",
      header: t("warehouse.analysis.column.receipts"),
      defaultWidth: 110,
      cell: (row) => <span className="tabular-nums text-muted-foreground">{row.receipt_count}</span>,
      sortValue: (row) => row.receipt_count,
    },
  ];
  const bestCostTable = useTableColumns("warehouse.analysis.bestCost", bestCostColumns);
  const sortedBestCostRows = bestCostTable.sortRows(bestCostRows);

  // "Majoration" alert -- the warning triangle from the BD MP tracking sheet. Flagged
  // server-side (list_confirmed_receipt_line_details) against every OTHER confirmed
  // receipt for the same product+unit, so this is just filtering + display.
  const anomalyRows: AnomalyRow[] = receipts
    .filter((r) => r.is_cost_anomaly)
    .map((r) => ({ ...r, name: productName(r.product_id), unitLabel: uomCode(r.uom_id) }))
    .sort((a, b) => (b.cost_deviation_pct ?? 0) - (a.cost_deviation_pct ?? 0));

  const anomalyColumns: ColumnDef<AnomalyRow>[] = [
    {
      key: "invoice_date",
      header: t("warehouse.analysis.anomaly.column.date"),
      defaultWidth: 120,
      cell: (row) => <span className="text-muted-foreground">{row.invoice_date ?? "—"}</span>,
      sortValue: (row) => row.invoice_date,
    },
    {
      key: "name",
      header: t("warehouse.analysis.bestCost.column.designation"),
      defaultWidth: 200,
      cell: (row) => <span className="font-medium">{row.name}</span>,
      sortValue: (row) => row.name,
    },
    {
      key: "origin",
      header: t("warehouse.analysis.bestCost.column.origin"),
      defaultWidth: 140,
      cell: (row) => <span className="text-muted-foreground">{row.origin_country || "—"}</span>,
      sortValue: (row) => row.origin_country ?? "",
    },
    {
      key: "costPerUnit",
      header: t("warehouse.analysis.anomaly.column.cost"),
      defaultWidth: 150,
      cell: (row) => (
        <span className="tabular-nums text-muted-foreground">
          {formatMoney(row.cost_per_unit_base)} / {row.unitLabel}
        </span>
      ),
      sortValue: (row) => row.cost_per_unit_base,
    },
    {
      key: "baseline",
      header: t("warehouse.analysis.anomaly.column.baseline"),
      defaultWidth: 150,
      cell: (row) => (
        <span className="tabular-nums text-muted-foreground">
          {row.baseline_avg_cost_per_unit != null ? `${formatMoney(row.baseline_avg_cost_per_unit)} / ${row.unitLabel}` : "—"}
        </span>
      ),
      sortValue: (row) => row.baseline_avg_cost_per_unit ?? 0,
    },
    {
      key: "deviation",
      header: t("warehouse.analysis.anomaly.column.deviation"),
      defaultWidth: 130,
      cell: (row) => (
        <Badge variant="warning" dot>
          +{Math.round(row.cost_deviation_pct ?? 0)}%
        </Badge>
      ),
      sortValue: (row) => row.cost_deviation_pct ?? 0,
    },
  ];
  const anomalyTable = useTableColumns("warehouse.analysis.anomaly", anomalyColumns);
  const sortedAnomalyRows = anomalyTable.sortRows(anomalyRows);

  const alertsSection = (
    <>
      {alertRows.length > 0 && (
        <Card>
          <CardHeader>
            <div>
              <CardTitle className="flex items-center gap-1.5">
                {t("warehouse.analysis.alerts.title")}
                <HelpTooltip text={t("products.help.stockAlert")} />
              </CardTitle>
              <CardDescription>{t("warehouse.analysis.alerts.description")}</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {alertRows.map(({ product, onHand, threshold }) => (
              <div key={product.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-warning/20 bg-warning-soft px-4 py-2.5">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 text-warning" />
                  <span className="font-medium">{product.name}</span>
                  <Badge variant="warning" dot>
                    {onHand} / {threshold} {uomCode(product.uom_id)}
                  </Badge>
                </div>
                <Button size="sm" variant="outline" onClick={() => openOrderDialog(product, threshold - onHand)}>
                  <Send className="h-3.5 w-3.5" />
                  {t("warehouse.analysis.alerts.order")}
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <Dialog open={orderingProduct !== null} onOpenChange={(open) => !open && setOrderingProduct(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("warehouse.analysis.alerts.dialog.title")}</DialogTitle>
            <DialogDescription>{orderingProduct?.name}</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={orderForm.handleSubmit((input) => createOrderMutation.mutate(input))}>
            <div className="space-y-1.5">
              <Label htmlFor="alert_order_supplier">{t("procurement.field.supplier")}</Label>
              <Select id="alert_order_supplier" {...orderForm.register("supplier_id")}>
                <option value="">—</option>
                {suppliers.map((supplier) => (
                  <option key={supplier.id} value={supplier.id}>
                    {supplier.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="alert_order_quantity">{t("procurement.field.quantity")}</Label>
              <Input id="alert_order_quantity" type="number" step="any" {...orderForm.register("quantity_ordered")} />
              {orderForm.formState.errors.quantity_ordered && (
                <p className="text-sm text-destructive">{orderForm.formState.errors.quantity_ordered.message}</p>
              )}
            </div>
            {createOrderMutation.isError && (
              <p className="text-sm text-destructive">
                {createOrderMutation.error instanceof ApiError ? createOrderMutation.error.message : t("warehouse.analysis.alerts.orderError")}
              </p>
            )}
            <Button type="submit" className="w-full" disabled={createOrderMutation.isPending}>
              {createOrderMutation.isPending ? t("procurement.creating") : t("warehouse.analysis.alerts.order")}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );

  if (allReceipts.length === 0) {
    return (
      <div className="space-y-6">
        {alertsSection}
        <Card>
          <CardContent className="p-0">
            <EmptyState icon={<Coins className="h-5 w-5" />} title={t("warehouse.analysis.empty.title")} description={t("warehouse.analysis.empty.description")} />
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {alertsSection}
      <div className="flex flex-wrap items-end gap-3">
        <span className="inline-flex items-center gap-1 text-sm font-medium text-muted-foreground">
          {t("warehouse.analysis.period.label")}
          <HelpTooltip text={t("warehouse.analysis.help.weightOnly")} />
        </span>
        <div className="space-y-1">
          <Label htmlFor="period-from" className="text-xs">
            {t("warehouse.analysis.period.from")}
          </Label>
          <Input id="period-from" type="date" className="h-8 w-40" value={periodFrom} onChange={(e) => setPeriodFrom(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="period-to" className="text-xs">
            {t("warehouse.analysis.period.to")}
          </Label>
          <Input id="period-to" type="date" className="h-8 w-40" value={periodTo} onChange={(e) => setPeriodTo(e.target.value)} />
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

      {receipts.length === 0 ? (
        <Card>
          <CardContent className="p-0">
            <EmptyState icon={<Coins className="h-5 w-5" />} title={t("warehouse.analysis.empty.title")} description={t("warehouse.analysis.empty.description")} />
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <StatCard label={t("warehouse.analysis.stat.totalSpend")} value={Math.round(totalSpend)} icon={<Coins className="h-5 w-5" />} accent="primary" />
            <StatCard label={t("warehouse.analysis.stat.totalTons")} value={Math.round(totalTons)} icon={<Boxes className="h-5 w-5" />} accent="success" />
            <StatCard label={t("warehouse.analysis.stat.avgCostPerTon")} value={Math.round(avgCostPerTon)} icon={<TrendingUp className="h-5 w-5" />} accent="warning" />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>{t("warehouse.analysis.chart.byDesignation.title")}</CardTitle>
                  <CardDescription>{t("warehouse.analysis.chart.byDesignation.description")}</CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                <InteractiveChart height={280}>
                  <BarChart data={designationRows} layout="vertical" margin={{ left: 24 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                    <YAxis
                      type="category"
                      dataKey="name"
                      width={160}
                      tick={{ fontSize: 11, fill: "hsl(215 16% 47%)" }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <Tooltip
                      formatter={(value) => formatMoney(Number(value))}
                      contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }}
                    />
                    <Bar dataKey="avgCostPerTon" fill={CHART_COLORS.primary} radius={[0, 4, 4, 0]} />
                  </BarChart>
                </InteractiveChart>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div>
                  <CardTitle>{t("warehouse.analysis.chart.trend.title")}</CardTitle>
                  <CardDescription>{t("warehouse.analysis.chart.trend.description")}</CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                <InteractiveChart height={280}>
                  <LineChart data={trendData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" vertical={false} />
                    <XAxis dataKey="month" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                    <Tooltip
                      formatter={(value) => formatMoney(Number(value))}
                      contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }}
                    />
                    <Line type="monotone" dataKey="avgCostPerTon" stroke={CHART_COLORS.accent} strokeWidth={2} dot={{ r: 3 }} />
                  </LineChart>
                </InteractiveChart>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center gap-3">
                <CardTitle>{t("warehouse.analysis.table.title")}</CardTitle>
                <ColumnVisibilityMenu
                  columns={byDesignationColumns}
                  isVisible={byDesignationTable.isVisible}
                  onToggle={byDesignationTable.toggleVisible}
                  onReset={byDesignationTable.resetAll}
                />
              </div>
            </CardHeader>
            <CardContent className="p-0">
              <Table colWidths={byDesignationTable.colWidths}>
                <TableHeader>
                  <TableRow>
                    {byDesignationTable.visibleColumns.map((column) => (
                      <ResizableTableHead
                        key={column.key}
                        width={byDesignationTable.getWidth(column.key)}
                        onResize={(width) => byDesignationTable.setWidth(column.key, width)}
                        className={column.headerClassName}
                        sortDirection={byDesignationTable.sortDirectionFor(column.key)}
                        onSort={column.sortValue ? () => byDesignationTable.toggleSort(column.key) : undefined}
                      >
                        {column.header}
                      </ResizableTableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedDesignationRows.map((row) => (
                    <TableRow key={row.productId}>
                      {byDesignationTable.visibleColumns.map((column) => (
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

          {bestCostRows.length > 0 && (
            <Card>
              <CardHeader>
                <div className="flex flex-wrap items-center gap-3">
                  <div>
                    <CardTitle className="flex items-center gap-1.5">
                      {t("warehouse.analysis.bestCost.title")}
                      <HelpTooltip text={t("warehouse.analysis.bestCost.help")} />
                    </CardTitle>
                    <CardDescription>{t("warehouse.analysis.bestCost.description")}</CardDescription>
                  </div>
                  <ColumnVisibilityMenu
                    columns={bestCostColumns}
                    isVisible={bestCostTable.isVisible}
                    onToggle={bestCostTable.toggleVisible}
                    onReset={bestCostTable.resetAll}
                  />
                </div>
              </CardHeader>
              <CardContent className="p-0">
                <Table colWidths={bestCostTable.colWidths}>
                  <TableHeader>
                    <TableRow>
                      {bestCostTable.visibleColumns.map((column) => (
                        <ResizableTableHead
                          key={column.key}
                          width={bestCostTable.getWidth(column.key)}
                          onResize={(width) => bestCostTable.setWidth(column.key, width)}
                          className={column.headerClassName}
                          sortDirection={bestCostTable.sortDirectionFor(column.key)}
                          onSort={column.sortValue ? () => bestCostTable.toggleSort(column.key) : undefined}
                        >
                          {column.header}
                        </ResizableTableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sortedBestCostRows.map((row) => (
                      <TableRow key={`${row.product_id}-${row.uom_id}-${row.origin_country}-${row.is_import}`}>
                        {bestCostTable.visibleColumns.map((column) => (
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
          )}

          {anomalyRows.length > 0 && (
            <Card className="border-warning/30">
              <CardHeader>
                <div className="flex flex-wrap items-center gap-3">
                  <div>
                    <CardTitle className="flex items-center gap-1.5">
                      <AlertTriangle className="h-4 w-4 text-warning" />
                      {t("warehouse.analysis.anomaly.title")}
                      <HelpTooltip text={t("warehouse.analysis.anomaly.help")} />
                    </CardTitle>
                    <CardDescription>{t("warehouse.analysis.anomaly.description")}</CardDescription>
                  </div>
                  <ColumnVisibilityMenu
                    columns={anomalyColumns}
                    isVisible={anomalyTable.isVisible}
                    onToggle={anomalyTable.toggleVisible}
                    onReset={anomalyTable.resetAll}
                  />
                </div>
              </CardHeader>
              <CardContent className="p-0">
                <Table colWidths={anomalyTable.colWidths}>
                  <TableHeader>
                    <TableRow>
                      {anomalyTable.visibleColumns.map((column) => (
                        <ResizableTableHead
                          key={column.key}
                          width={anomalyTable.getWidth(column.key)}
                          onResize={(width) => anomalyTable.setWidth(column.key, width)}
                          className={column.headerClassName}
                          sortDirection={anomalyTable.sortDirectionFor(column.key)}
                          onSort={column.sortValue ? () => anomalyTable.toggleSort(column.key) : undefined}
                        >
                          {column.header}
                        </ResizableTableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sortedAnomalyRows.map((row) => (
                      <TableRow key={row.receipt_id}>
                        {anomalyTable.visibleColumns.map((column) => (
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
          )}
        </>
      )}
    </div>
  );
}
