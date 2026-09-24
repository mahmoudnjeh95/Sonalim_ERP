import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, FileSpreadsheet, Layers, PieChart as PieChartIcon, Scale, TrendingUp } from "lucide-react";
import { toast } from "sonner";
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Table, TableBody, TableCell, TableHeader, TableRow, ResizableTableHead } from "../../components/ui/table";
import { EmptyState } from "../../components/patterns/EmptyState";
import { StatCard } from "../../components/patterns/StatCard";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { formatQuantity } from "../../lib/units";
import {
  exportProductionRecap,
  getProductionAnalytics,
  type ProductionCostAnomaly,
  type ProductionPeriodPoint,
  type ProductionRecapPeriod,
} from "../production/api";
import { listProducts } from "../warehouse/api";
import { listPartners } from "../partners/api";
import { AppLoader } from "../../components/patterns/AppLoader";

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

const PERIODS: ProductionRecapPeriod[] = ["day", "week", "month"];

const CHART_COLORS = {
  primary: "hsl(217 91% 45%)",
  accent: "hsl(258 90% 66%)",
  success: "hsl(152 69% 31%)",
  warning: "hsl(38 92% 42%)",
  destructive: "hsl(0 72% 51%)",
  muted: "hsl(215 16% 70%)",
};
const BREAKDOWN_COLORS = [CHART_COLORS.primary, CHART_COLORS.warning, CHART_COLORS.success, CHART_COLORS.accent, CHART_COLORS.destructive];
const GRID_STROKE = "hsl(214 20% 92%)";
const TICK_STYLE = { fontSize: 12, fill: "hsl(215 16% 47%)" };
const TOOLTIP_STYLE = { borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" };

function cfa(value: number | null | undefined): string {
  return formatQuantity(value);
}

/** Buckets the trend's cost/tonne values into ~6 equal-width bins for the
 * histogram -- Recharts has no histogram primitive, so this is a plain bar
 * chart of pre-counted frequencies. */
function buildHistogram(values: number[]): { bin: string; count: number }[] {
  if (values.length === 0) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (min === max) return [{ bin: cfa(min), count: values.length }];

  const binCount = Math.min(6, Math.max(3, Math.round(Math.sqrt(values.length))));
  const width = (max - min) / binCount;
  const counts = new Array(binCount).fill(0);
  for (const value of values) {
    const index = Math.min(binCount - 1, Math.floor((value - min) / width));
    counts[index] += 1;
  }
  return counts.map((count, index) => {
    const from = min + index * width;
    const to = index === binCount - 1 ? max : from + width;
    return { bin: `${cfa(from)}–${cfa(to)}`, count };
  });
}

export function ProductionRecapExportTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [period, setPeriod] = useState<ProductionRecapPeriod>("day");
  const [date, setDate] = useState(todayIso());
  const [isExporting, setIsExporting] = useState(false);

  const { data: analytics, isLoading, isError } = useQuery({
    queryKey: ["production", "daily-recap", "analytics", period, date],
    queryFn: () => getProductionAnalytics(token, { date, period }),
    enabled: Boolean(date),
  });
  const { data: products = [] } = useQuery({ queryKey: ["core", "products"], queryFn: () => listProducts(token) });
  const { data: suppliers = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token) });

  const productName = (id: string | null) => (id && products.find((p) => p.id === id)?.name) || "—";
  const supplierName = (id: string | null) => (id && suppliers.find((s) => s.id === id)?.name) || "—";

  async function handleExport() {
    setIsExporting(true);
    try {
      const blob = await exportProductionRecap(token, { date, period });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `recap-${period}-${date}.xlsx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch {
      toast.error(t("analytics.productionRecap.exportError"));
    } finally {
      setIsExporting(false);
    }
  }

  const current = analytics?.current;
  const trend = analytics?.trend ?? [];
  const hasData = Boolean(current && (current.tonnage > 0 || trend.some((p) => p.tonnage > 0)));
  const costPerTonneValues = trend.filter((p) => p.cost_per_tonne !== null).map((p) => p.cost_per_tonne as number);

  const summaryColumns: ColumnDef<ProductionPeriodPoint>[] = [
    { key: "period", header: t("analytics.productionRecap.table.summary.column.period"), defaultWidth: 160, cellClassName: "font-medium", cell: (p) => p.label },
    {
      key: "tonnage",
      header: t("analytics.productionRecap.table.summary.column.tonnage"),
      defaultWidth: 130,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (p) => formatQuantity(p.tonnage),
      sortValue: (p) => p.tonnage,
    },
    {
      key: "mpCost",
      header: t("analytics.productionRecap.table.summary.column.mpCost"),
      defaultWidth: 130,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (p) => cfa(p.mp_cost),
      sortValue: (p) => p.mp_cost ?? 0,
    },
    {
      key: "packagingCost",
      header: t("analytics.productionRecap.table.summary.column.packagingCost"),
      defaultWidth: 150,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (p) => cfa(p.packaging_cost),
      sortValue: (p) => p.packaging_cost ?? 0,
    },
    {
      key: "costPerTonne",
      header: t("analytics.productionRecap.table.summary.column.costPerTonne"),
      defaultWidth: 150,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (p) => cfa(p.cost_per_tonne),
      sortValue: (p) => p.cost_per_tonne ?? 0,
    },
    {
      key: "cartons",
      header: t("analytics.productionRecap.table.summary.column.cartons"),
      defaultWidth: 130,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (p) => formatQuantity(p.cartons),
      sortValue: (p) => p.cartons,
    },
    {
      key: "packets",
      header: t("analytics.productionRecap.table.summary.column.packets"),
      defaultWidth: 130,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (p) => formatQuantity(p.packets),
      sortValue: (p) => p.packets,
    },
  ];
  const summaryTable = useTableColumns("analytics.productionRecap.summary", summaryColumns);

  const anomalyColumns: ColumnDef<ProductionCostAnomaly>[] = [
    {
      key: "date",
      header: t("analytics.productionRecap.table.anomalies.column.date"),
      defaultWidth: 130,
      cell: (row) => row.invoice_date ?? "—",
      sortValue: (row) => row.invoice_date ?? "",
    },
    {
      key: "product",
      header: t("analytics.productionRecap.table.anomalies.column.product"),
      defaultWidth: 180,
      cellClassName: "font-medium",
      cell: (row) => productName(row.product_id),
      sortValue: (row) => productName(row.product_id),
    },
    {
      key: "supplier",
      header: t("analytics.productionRecap.table.anomalies.column.supplier"),
      defaultWidth: 180,
      cell: (row) => supplierName(row.supplier_id),
      sortValue: (row) => supplierName(row.supplier_id),
    },
    {
      key: "costPerUnit",
      header: t("analytics.productionRecap.table.anomalies.column.costPerUnit"),
      defaultWidth: 150,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (row) => cfa(row.cost_per_unit_base),
      sortValue: (row) => row.cost_per_unit_base,
    },
    {
      key: "baseline",
      header: t("analytics.productionRecap.table.anomalies.column.baseline"),
      defaultWidth: 150,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (row) => cfa(row.baseline_avg_cost_per_unit),
      sortValue: (row) => row.baseline_avg_cost_per_unit ?? 0,
    },
    {
      key: "deviation",
      header: t("analytics.productionRecap.table.anomalies.column.deviation"),
      defaultWidth: 150,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums font-medium text-destructive",
      cell: (row) => (row.cost_deviation_pct !== null ? `+${row.cost_deviation_pct.toFixed(0)}%` : "—"),
      sortValue: (row) => row.cost_deviation_pct ?? 0,
    },
  ];
  const anomalyTable = useTableColumns("analytics.productionRecap.anomalies", anomalyColumns);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <FileSpreadsheet className="h-4 w-4 text-muted-foreground" />
            <CardTitle>{t("analytics.productionRecap.title")}</CardTitle>
          </div>
          <p className="mt-0.5 text-sm text-muted-foreground">{t("analytics.productionRecap.subtitle")}</p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-4">
            <FilterTabs
              value={period}
              onChange={setPeriod}
              options={PERIODS.map((value) => ({ value, label: t(`analytics.productionRecap.period.${value}` as TranslationKey) }))}
            />
            <div className="space-y-1.5">
              <Label htmlFor="production-recap-date">{t("analytics.productionRecap.dateLabel")}</Label>
              <Input
                id="production-recap-date"
                type="date"
                value={date}
                onChange={(event) => setDate(event.target.value)}
                className="w-40"
              />
            </div>
            <Button size="sm" onClick={handleExport} disabled={isExporting || !date}>
              <Download className="h-3.5 w-3.5" />
              {isExporting ? t("common.saving") : t("analytics.productionRecap.export")}
            </Button>
          </div>
        </CardContent>
      </Card>

      {isLoading && <AppLoader className="py-8" />}

      {!isLoading && isError && (
        <Card>
          <CardContent className="p-0">
            <EmptyState icon={<FileSpreadsheet className="h-5 w-5" />} title={t("analytics.productionRecap.dashboard.loadError")} description="" />
          </CardContent>
        </Card>
      )}

      {!isLoading && !isError && current && !hasData && (
        <Card>
          <CardContent className="p-0">
            <EmptyState
              icon={<FileSpreadsheet className="h-5 w-5" />}
              title={t("analytics.productionRecap.dashboard.empty.title")}
              description={t("analytics.productionRecap.dashboard.empty.description")}
            />
          </CardContent>
        </Card>
      )}

      {!isLoading && !isError && current && hasData && (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label={t("analytics.productionRecap.stat.tonnage")}
              value={current.tonnage}
              icon={<Scale className="h-5 w-5" />}
              accent="primary"
              decimals={2}
            />
            <StatCard
              label={t("analytics.productionRecap.stat.costPerTonne")}
              value={current.cost_per_tonne}
              icon={<TrendingUp className="h-5 w-5" />}
              accent="warning"
            />
            <StatCard
              label={t("analytics.productionRecap.stat.costPerCarton")}
              value={current.variable_cost !== null && current.cartons > 0 ? current.variable_cost / current.cartons : null}
              icon={<Layers className="h-5 w-5" />}
              accent="accent"
            />
            <StatCard
              label={t("analytics.productionRecap.stat.costPerPacket")}
              value={current.variable_cost !== null && current.packets > 0 ? current.variable_cost / current.packets : null}
              icon={<PieChartIcon className="h-5 w-5" />}
              accent="success"
            />
          </div>
          <p className="text-xs text-muted-foreground">{t("analytics.productionRecap.variableCostHint")}</p>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>{t("analytics.productionRecap.chart.costBreakdown.title")}</CardTitle>
                <CardDescription>
                  {t("analytics.productionRecap.chart.costBreakdown.description").replace("{period}", analytics.period_phrase)}
                </CardDescription>
              </CardHeader>
              <CardContent>
                {current.cost_breakdown.length === 0 ? (
                  <EmptyState icon={<Layers className="h-5 w-5" />} title={t("analytics.productionRecap.chart.costBreakdown.empty")} description="" />
                ) : (
                  <ResponsiveContainer width="100%" height={220}>
                    <ComposedChart data={current.cost_breakdown} layout="vertical" margin={{ left: 16 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} horizontal={false} />
                      <XAxis type="number" tick={TICK_STYLE} axisLine={false} tickLine={false} tickFormatter={(v) => cfa(Number(v))} />
                      <YAxis type="category" dataKey="category" width={80} tick={TICK_STYLE} axisLine={false} tickLine={false} />
                      <Tooltip formatter={(value) => cfa(Number(value))} contentStyle={TOOLTIP_STYLE} />
                      <Bar dataKey="cost" radius={[0, 4, 4, 0]}>
                        {current.cost_breakdown.map((entry, index) => (
                          <Cell key={entry.category} fill={BREAKDOWN_COLORS[index % BREAKDOWN_COLORS.length]} />
                        ))}
                      </Bar>
                    </ComposedChart>
                  </ResponsiveContainer>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>{t("analytics.productionRecap.chart.costShare.title")}</CardTitle>
              </CardHeader>
              <CardContent>
                {current.cost_breakdown.length === 0 ? (
                  <EmptyState icon={<PieChartIcon className="h-5 w-5" />} title={t("analytics.productionRecap.chart.costBreakdown.empty")} description="" />
                ) : (
                  <>
                    <ResponsiveContainer width="100%" height={180}>
                      <PieChart>
                        <Pie data={current.cost_breakdown} dataKey="cost" nameKey="category" innerRadius={45} outerRadius={75} paddingAngle={2}>
                          {current.cost_breakdown.map((entry, index) => (
                            <Cell key={entry.category} fill={BREAKDOWN_COLORS[index % BREAKDOWN_COLORS.length]} />
                          ))}
                        </Pie>
                        <Tooltip formatter={(value) => cfa(Number(value))} contentStyle={TOOLTIP_STYLE} />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1.5">
                      {current.cost_breakdown.map((entry, index) => (
                        <div key={entry.category} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: BREAKDOWN_COLORS[index % BREAKDOWN_COLORS.length] }} />
                          {entry.category}
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          </div>

          {trend.length >= 2 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-1.5">
                  <TrendingUp className="h-4 w-4" />
                  {t("analytics.productionRecap.chart.trend.title")}
                </CardTitle>
                <CardDescription>{t("analytics.productionRecap.chart.trend.description")}</CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={280}>
                  <ComposedChart data={trend}>
                    <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
                    <XAxis dataKey="label" tick={TICK_STYLE} axisLine={false} tickLine={false} />
                    <YAxis yAxisId="left" tick={TICK_STYLE} axisLine={false} tickLine={false} tickFormatter={(v) => formatQuantity(Number(v))} />
                    <YAxis
                      yAxisId="right"
                      orientation="right"
                      tick={TICK_STYLE}
                      axisLine={false}
                      tickLine={false}
                      tickFormatter={(v) => cfa(Number(v))}
                    />
                    <Tooltip
                      formatter={(value, name) => (name === t("analytics.productionRecap.chart.trend.costPerTonne") ? cfa(Number(value)) : formatQuantity(Number(value)))}
                      contentStyle={TOOLTIP_STYLE}
                    />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Bar yAxisId="left" dataKey="tonnage" name={t("analytics.productionRecap.chart.trend.tonnage")} fill={CHART_COLORS.primary} radius={[4, 4, 0, 0]} />
                    <Line
                      yAxisId="right"
                      type="monotone"
                      dataKey="cost_per_tonne"
                      name={t("analytics.productionRecap.chart.trend.costPerTonne")}
                      stroke={CHART_COLORS.warning}
                      strokeWidth={2}
                      dot={{ r: 3 }}
                      connectNulls
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {costPerTonneValues.length >= 3 && (
              <Card>
                <CardHeader>
                  <CardTitle>{t("analytics.productionRecap.chart.histogram.title")}</CardTitle>
                  <CardDescription>{t("analytics.productionRecap.chart.histogram.description")}</CardDescription>
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={240}>
                    <ComposedChart data={buildHistogram(costPerTonneValues)} margin={{ bottom: 24 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
                      <XAxis dataKey="bin" tick={{ fontSize: 10, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} angle={-20} textAnchor="end" height={50} />
                      <YAxis tick={TICK_STYLE} axisLine={false} tickLine={false} allowDecimals={false} label={{ value: t("analytics.productionRecap.chart.histogram.axisLabel"), angle: -90, position: "insideLeft", fontSize: 11, fill: "hsl(215 16% 47%)" }} />
                      <Tooltip contentStyle={TOOLTIP_STYLE} />
                      <Bar dataKey="count" fill={CHART_COLORS.accent} radius={[4, 4, 0, 0]} />
                    </ComposedChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            )}

            {trend.filter((p) => p.cost_per_tonne !== null && p.tonnage > 0).length >= 3 && (
              <Card>
                <CardHeader>
                  <CardTitle>{t("analytics.productionRecap.chart.scatter.title")}</CardTitle>
                  <CardDescription>{t("analytics.productionRecap.chart.scatter.description")}</CardDescription>
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={240}>
                    <LineChart data={trend.filter((p) => p.cost_per_tonne !== null && p.tonnage > 0)}>
                      <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
                      <XAxis
                        type="number"
                        dataKey="tonnage"
                        name={t("analytics.productionRecap.chart.scatter.xAxis")}
                        tick={TICK_STYLE}
                        axisLine={false}
                        tickLine={false}
                        label={{ value: t("analytics.productionRecap.chart.scatter.xAxis"), position: "insideBottom", offset: -5, fontSize: 11, fill: "hsl(215 16% 47%)" }}
                      />
                      <YAxis
                        type="number"
                        dataKey="cost_per_tonne"
                        name={t("analytics.productionRecap.chart.scatter.yAxis")}
                        tick={TICK_STYLE}
                        axisLine={false}
                        tickLine={false}
                        tickFormatter={(v) => cfa(Number(v))}
                      />
                      <Tooltip
                        formatter={(value, name) => (name === "cost_per_tonne" ? cfa(Number(value)) : formatQuantity(Number(value)))}
                        labelFormatter={(_, payload) => (payload?.[0]?.payload as ProductionPeriodPoint | undefined)?.label ?? ""}
                        contentStyle={TOOLTIP_STYLE}
                      />
                      <Line type="linear" dataKey="cost_per_tonne" stroke={CHART_COLORS.destructive} strokeWidth={1.5} dot={{ r: 4 }} activeDot={{ r: 6 }} />
                    </LineChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            )}
          </div>

          <Card>
            <CardHeader>
              <CardTitle>{t("analytics.productionRecap.table.summary.title")}</CardTitle>
              <ColumnVisibilityMenu
                columns={summaryColumns}
                isVisible={summaryTable.isVisible}
                onToggle={summaryTable.toggleVisible}
                onReset={summaryTable.resetAll}
              />
            </CardHeader>
            <CardContent className="p-0">
              <Table colWidths={summaryTable.colWidths}>
                <TableHeader>
                  <TableRow>
                    {summaryTable.visibleColumns.map((column) => (
                      <ResizableTableHead
                        key={column.key}
                        width={summaryTable.getWidth(column.key)}
                        onResize={(width) => summaryTable.setWidth(column.key, width)}
                        className={column.headerClassName}
                        sortDirection={summaryTable.sortDirectionFor(column.key)}
                        onSort={column.sortValue ? () => summaryTable.toggleSort(column.key) : undefined}
                      >
                        {column.header}
                      </ResizableTableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {summaryTable.sortRows(trend).map((point) => (
                    <TableRow key={point.date_from} className={point.label === current.label ? "bg-primary/5" : undefined}>
                      {summaryTable.visibleColumns.map((column) => (
                        <TableCell key={column.key} className={column.cellClassName}>
                          {column.cell(point)}
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
              <div>
                <CardTitle>{t("analytics.productionRecap.table.anomalies.title")}</CardTitle>
                <CardDescription>{t("analytics.productionRecap.table.anomalies.description")}</CardDescription>
              </div>
              {analytics.anomalies.length > 0 && (
                <ColumnVisibilityMenu
                  columns={anomalyColumns}
                  isVisible={anomalyTable.isVisible}
                  onToggle={anomalyTable.toggleVisible}
                  onReset={anomalyTable.resetAll}
                />
              )}
            </CardHeader>
            <CardContent className="p-0">
              {analytics.anomalies.length === 0 ? (
                <EmptyState icon={<TrendingUp className="h-5 w-5" />} title={t("analytics.productionRecap.table.anomalies.empty")} description="" />
              ) : (
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
                    {anomalyTable.sortRows(analytics.anomalies).map((row) => (
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
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
