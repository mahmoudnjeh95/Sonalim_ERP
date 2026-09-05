import { useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  Activity,
  ClipboardCheck,
  Factory,
  Gauge,
  PackageCheck,
  Recycle,
  Timer,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Skeleton } from "../../components/ui/skeleton";
import { Badge } from "../../components/ui/badge";
import { StatCard } from "../../components/patterns/StatCard";
import { UnitBreakdownStat } from "../../components/patterns/UnitBreakdownStat";
import { DateRangeFilter } from "../../components/patterns/DateRangeFilter";
import { commonUnit, convertQuantity, totalsByUomCategory } from "../../lib/units";
import { listUoms } from "../warehouse/api";
import { EmptyState } from "../../components/patterns/EmptyState";
import { cn } from "../../lib/utils";
import {
  getWorkOrderConsolidation,
  listDowntimeReasons,
  listRecipeCorrelation,
  listReports,
  listTeamPerformance,
  listWorkOrders,
  type OfConsolidation,
  type TeamPerformanceRow,
} from "./api";
import { listNonConformities } from "../qc/api";
import { listProducts, listStock } from "../warehouse/api";

const WORK_ORDERS_QUERY_KEY = ["production", "work-orders"] as const;
const PENDING_QUERY_KEY = ["production", "reports", "pending"] as const;
const NC_QUERY_KEY = ["qc", "non-conformities"] as const;
const STOCK_QUERY_KEY = ["warehouse", "stock"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const UOMS_QUERY_KEY = ["core", "uoms"] as const;

// Thresholds the cockpit flags on. Deliberately conservative: an alert that fires
// constantly is an alert nobody reads.
const WASTE_RATIO_ALERT = 0.05;
const DOWNTIME_RATIO_ALERT = 0.15;

type AlertTone = "warning" | "destructive";

interface Alert {
  code: string;
  tone: AlertTone;
  titleKey: string;
  detail: string;
  /** Where the alert is resolved — an alert you cannot act on is just noise. */
  to: string;
}

export function ProductionDashboardTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [customRange, setCustomRange] = useState<{ from: string; to: string } | null>(null);
  const defaultRange = { from: isoWeeksAgo(16), to: todayIso() };
  const range = customRange ?? defaultRange;

  const { data: workOrders = [], isLoading: loadingOrders } = useQuery({
    queryKey: WORK_ORDERS_QUERY_KEY,
    queryFn: () => listWorkOrders(token),
  });
  const { data: pendingReports = [] } = useQuery({
    queryKey: PENDING_QUERY_KEY,
    queryFn: () => listReports(token, { status: "submitted" }),
  });
  const { data: nonConformities = [] } = useQuery({ queryKey: NC_QUERY_KEY, queryFn: () => listNonConformities(token) });
  const { data: stock = [] } = useQuery({ queryKey: STOCK_QUERY_KEY, queryFn: () => listStock(token) });
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: uoms = [] } = useQuery({ queryKey: UOMS_QUERY_KEY, queryFn: () => listUoms(token) });

  const activeOrders = workOrders.filter((o) => o.status === "ongoing" || o.status === "suspended");

  // Plant-wide, week-by-week — every team's validated reports summed together,
  // the same bulk query the team-performance tab reads per team. A real
  // calendar timeline, not one bar per OF, so several OFs running the same week
  // land in the same point instead of competing for the x-axis.
  const { data: teamPerformance = [] } = useQuery({
    queryKey: ["production", "team-performance", "dashboard-trend", range.from, range.to],
    queryFn: () => listTeamPerformance(token, { grain: "week", date_from: range.from, date_to: range.to }),
  });
  const { data: downtimeReasons = [] } = useQuery({
    queryKey: ["production", "downtime-reasons", range.from, range.to],
    queryFn: () => listDowntimeReasons(token, { date_from: range.from, date_to: range.to }),
  });
  const { data: recipeCorrelation = [] } = useQuery({
    queryKey: ["production", "recipe-correlation"],
    queryFn: () => listRecipeCorrelation(token),
  });

  // Consolidation is computed per OF and never stored, so the cockpit asks for
  // each active order's figures rather than reading a cached total.
  const consolidations = useQueries({
    queries: activeOrders.map((order) => ({
      queryKey: ["production", "of-consolidation", order.id],
      queryFn: () => getWorkOrderConsolidation(token, order.id),
    })),
  });
  const loadedConsolidations = consolidations
    .map((q) => q.data)
    .filter((d): d is OfConsolidation => d !== undefined);

  const produced = sum(loadedConsolidations.map((c) => c.produced_quantity));
  const semolina = sum(loadedConsolidations.map((c) => c.raw_material.semolina_quantity));
  // Waste is recorded per item now, and items are counted in different units:
  // rebut in kilos, cartons and scotch in pieces. There is no single number, so
  // this totals within each measurement category and shows them side by side.
  const wasteEntries = loadedConsolidations.flatMap((c) => c.waste.by_product);
  const { totals: wasteTotals } = totalsByUomCategory(wasteEntries, products, uoms);

  // A total spanning several orders only has a unit when they all share one.
  const producedUnit = commonUnit(
    loadedConsolidations.map((c) => c.product_id),
    products,
    uoms,
  );
  const semolinaUnit = commonUnit(
    loadedConsolidations.map((c) => c.raw_material.semolina_product_id),
    products,
    uoms,
  );
  const productionMinutes = sum(loadedConsolidations.map((c) => c.time.production_minutes));
  const downtimeMinutes = sum(loadedConsolidations.map((c) => c.time.downtime_minutes));
  const conforming = sum(loadedConsolidations.map((c) => c.quality.conforming_cartons));
  const nonConforming = sum(loadedConsolidations.map((c) => c.quality.non_conforming_cartons));

  const conformityRate = conforming + nonConforming > 0 ? conforming / (conforming + nonConforming) : null;

  // Waste against what was poured, both restated in the semoule's own unit.
  // Without the conversion this ratio was quietly wrong whenever the plant
  // poured tonnes and weighed its déchets in kilos — a thousandfold error that
  // looked like a very clean line. Items in another category (a count of
  // cartons against a weight of semoule) are left out rather than converted,
  // because no ratio between them exists.
  const semolinaProductId = loadedConsolidations.find(
    (c) => c.raw_material.semolina_product_id,
  )?.raw_material.semolina_product_id;
  const comparableWaste = semolinaProductId
    ? wasteEntries.reduce((total, entry) => {
        const converted = convertQuantity(entry.quantity, entry.product_id, semolinaProductId, products, uoms);
        return converted === null ? total : total + converted;
      }, 0)
    : null;
  const wasteRatio = comparableWaste !== null && semolina > 0 ? comparableWaste / semolina : null;
  const downtimeRatio =
    productionMinutes + downtimeMinutes > 0 ? downtimeMinutes / (productionMinutes + downtimeMinutes) : null;

  // One point per week, every team folded together — the same conversion the
  // snapshot ratios above use, applied per period instead of once. Weeks with
  // nothing validated yet are dropped rather than plotted as a false zero.
  const performanceTrend = buildPerformanceTrend(teamPerformance as TeamPerformanceRow[], semolinaProductId, products, uoms);

  const alerts = buildAlerts({
    pendingCount: pendingReports.length,
    lowStock: lowStockProducts(stock, products),
    wasteRatio,
    downtimeRatio,
    quarantined: nonConformities.filter((n) => n.status === "quarantined").length,
  });

  if (loadingOrders) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label={t("production.dashboard.stat.activeOrders")}
          value={activeOrders.length}
          icon={<Factory className="h-5 w-5" />}
          accent="warning"
        />
        <StatCard
          label={t("production.dashboard.stat.produced")}
          value={Math.round(produced)}
          unit={producedUnit}
          icon={<PackageCheck className="h-5 w-5" />}
          accent="success"
        />
        <StatCard
          label={t("production.dashboard.stat.semolina")}
          value={Math.round(semolina)}
          unit={semolinaUnit}
          icon={<Activity className="h-5 w-5" />}
          accent="primary"
        />
        <UnitBreakdownStat
          label={t("production.dashboard.stat.waste")}
          breakdown={wasteTotals.map((total) => ({ unit: total.unit, value: Math.round(total.value) }))}
          icon={<Recycle className="h-5 w-5" />}
          accent="destructive"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>{t("production.dashboard.alerts.title")}</CardTitle>
            <p className="mt-0.5 text-sm text-muted-foreground">{t("production.dashboard.alerts.subtitle")}</p>
          </CardHeader>
          <CardContent className={alerts.length === 0 ? "p-0" : "space-y-2"}>
            {alerts.length === 0 ? (
              <EmptyState
                icon={<ClipboardCheck className="h-5 w-5" />}
                title={t("production.dashboard.alerts.empty.title")}
                description={t("production.dashboard.alerts.empty.description")}
              />
            ) : (
              alerts.map((alert, index) => (
                <motion.div
                  key={alert.code}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.04 }}
                >
                  <Link
                    to={alert.to}
                    className={cn(
                      "flex items-start gap-3 rounded-lg border p-3 transition-colors",
                      alert.tone === "destructive"
                        ? "border-destructive/20 bg-destructive-soft hover:bg-destructive-soft/70"
                        : "border-warning/20 bg-warning-soft hover:bg-warning-soft/70",
                    )}
                  >
                  <AlertTriangle
                    className={cn(
                      "mt-0.5 h-4 w-4 shrink-0",
                      alert.tone === "destructive" ? "text-destructive" : "text-warning",
                    )}
                  />
                  <div className="min-w-0">
                    <p
                      className={cn(
                        "text-sm font-medium",
                        alert.tone === "destructive" ? "text-destructive" : "text-warning",
                      )}
                    >
                      {t(alert.titleKey as Parameters<typeof t>[0])}
                    </p>
                    <p className="text-sm text-muted-foreground">{alert.detail}</p>
                  </div>
                  <span className="ml-auto self-center text-xs text-muted-foreground">
                    {t("production.dashboard.alerts.open")}
                  </span>
                  </Link>
                </motion.div>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("production.dashboard.health.title")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Ratio
              icon={<Gauge className="h-4 w-4" />}
              label={t("production.dashboard.health.conformity")}
              ratio={conformityRate}
              goodIsHigh
            />
            <Ratio
              icon={<TrendingDown className="h-4 w-4" />}
              label={t("production.dashboard.health.waste")}
              ratio={wasteRatio}
              goodIsHigh={false}
            />
            <Ratio
              icon={<Timer className="h-4 w-4" />}
              label={t("production.dashboard.health.downtime")}
              ratio={downtimeRatio}
              goodIsHigh={false}
            />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("production.dashboard.active.title")}</CardTitle>
          <p className="mt-0.5 text-sm text-muted-foreground">{t("production.dashboard.active.subtitle")}</p>
        </CardHeader>
        <CardContent className={activeOrders.length === 0 ? "p-0" : "space-y-2"}>
          {activeOrders.length === 0 ? (
            <EmptyState
              icon={<Factory className="h-5 w-5" />}
              title={t("production.dashboard.active.empty.title")}
              description={t("production.dashboard.active.empty.description")}
            />
          ) : (
            activeOrders.map((order) => {
              const consolidation = loadedConsolidations.find((c) => c.of_id === order.id);
              const ratio = consolidation?.transformation_ratio ?? 0;
              return (
                <div key={order.id} className="rounded-lg border border-border p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{order.reference}</span>
                    <Badge variant={order.status === "suspended" ? "accent" : "warning"}>
                      {t(`status.${order.status}` as Parameters<typeof t>[0])}
                    </Badge>
                    <span className="ml-auto text-sm tabular-nums text-muted-foreground">
                      {Math.round(consolidation?.produced_quantity ?? 0)} /{" "}
                      {Math.round(consolidation?.material_input_quantity ?? 0)}
                    </span>
                  </div>
                  <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                    <motion.div
                      className="h-full rounded-full bg-success"
                      initial={{ width: 0 }}
                      animate={{ width: `${Math.min(100, Math.round(ratio * 100))}%` }}
                      transition={{ duration: 0.4, ease: "easeOut" }}
                    />
                  </div>
                </div>
              );
            })
          )}
        </CardContent>
      </Card>

      {performanceTrend.length >= 2 && (
        <Card>
          <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-1.5">
                <TrendingUp className="h-4 w-4" />
                {t("production.dashboard.trend.title")}
              </CardTitle>
              <CardDescription>{t("production.dashboard.trend.subtitle")}</CardDescription>
            </div>
            <DateRangeFilter
              from={range.from}
              to={range.to}
              onChange={setCustomRange}
              onReset={() => setCustomRange(null)}
              isDefault={customRange === null}
            />
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={performanceTrend}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" vertical={false} />
                <XAxis dataKey="period" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
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
                <Line type="monotone" dataKey="yieldPercent" name={t("production.dashboard.trend.yield")} stroke="hsl(217 91% 45%)" strokeWidth={2} dot={{ r: 3 }} connectNulls />
                <Line type="monotone" dataKey="wastePercent" name={t("production.dashboard.trend.waste")} stroke="hsl(0 72% 51%)" strokeWidth={2} dot={{ r: 3 }} connectNulls />
                <Line type="monotone" dataKey="downtimePercent" name={t("production.dashboard.trend.downtime")} stroke="hsl(38 92% 42%)" strokeWidth={2} dot={{ r: 3 }} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{t("production.dashboard.chart.downtimeReasons.title")}</CardTitle>
          <CardDescription>{t("production.dashboard.chart.downtimeReasons.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          {downtimeReasons.length === 0 ? (
            <EmptyState
              icon={<Timer className="h-5 w-5" />}
              title={t("production.dashboard.chart.downtimeReasons.empty.title")}
              description={t("production.dashboard.chart.downtimeReasons.empty.description")}
            />
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(160, Math.min(8, downtimeReasons.length) * 36)}>
              <BarChart data={downtimeReasons.slice(0, 8)} layout="vertical" margin={{ left: 24 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} allowDecimals={false} />
                <YAxis type="category" dataKey="reason" width={160} tick={{ fontSize: 11, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                <Tooltip
                  formatter={(value) => `${value} ${t("production.dashboard.chart.downtimeReasons.minutes").toLowerCase()}`}
                  contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }}
                />
                <Bar dataKey="minutes" name={t("production.dashboard.chart.downtimeReasons.minutes")} fill="hsl(38 92% 42%)" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("production.dashboard.chart.recipeCorrelation.title")}</CardTitle>
          <CardDescription>{t("production.dashboard.chart.recipeCorrelation.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          {recipeCorrelation.length < 3 ? (
            <EmptyState
              icon={<Activity className="h-5 w-5" />}
              title={t("production.dashboard.chart.recipeCorrelation.empty.title")}
              description={t("production.dashboard.chart.recipeCorrelation.empty.description")}
            />
          ) : (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <RecipeScatter
                title={t("production.dashboard.chart.recipeCorrelation.water")}
                xLabel={t("production.dashboard.chart.recipeCorrelation.waterAxis")}
                data={recipeCorrelation
                  .filter((r) => r.water_percentage !== null)
                  .map((r) => ({ x: r.water_percentage as number, y: Math.round(r.yield_ratio * 1000) / 10 }))}
              />
              <RecipeScatter
                title={t("production.dashboard.chart.recipeCorrelation.flowRate")}
                xLabel={t("production.dashboard.chart.recipeCorrelation.flowRateAxis")}
                data={recipeCorrelation
                  .filter((r) => r.semolina_flow_rate !== null)
                  .map((r) => ({ x: r.semolina_flow_rate as number, y: Math.round(r.yield_ratio * 1000) / 10 }))}
              />
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function RecipeScatter({ title, xLabel, data }: { title: string; xLabel: string; data: { x: number; y: number }[] }) {
  const { t } = useI18n();
  return (
    <div>
      <p className="mb-2 text-sm font-medium text-foreground">{title}</p>
      <ResponsiveContainer width="100%" height={220}>
        <ScatterChart margin={{ left: 8, right: 8, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" />
          <XAxis
            type="number"
            dataKey="x"
            name={xLabel}
            tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }}
            axisLine={false}
            tickLine={false}
            label={{ value: xLabel, position: "insideBottom", offset: -4, fontSize: 11, fill: "hsl(215 16% 47%)" }}
          />
          <YAxis
            type="number"
            dataKey="y"
            name={t("production.dashboard.chart.recipeCorrelation.yieldAxis")}
            tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(value) => `${value}%`}
          />
          <ZAxis range={[60, 60]} />
          <Tooltip
            cursor={{ strokeDasharray: "3 3" }}
            formatter={(value, name) => (name === t("production.dashboard.chart.recipeCorrelation.yieldAxis") ? `${value}%` : value)}
            contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }}
          />
          <Scatter data={data} fill="hsl(217 91% 45%)" />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

function isoWeeksAgo(weeks: number): string {
  const date = new Date();
  date.setDate(date.getDate() - weeks * 7);
  return date.toISOString().slice(0, 10);
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/** One point per period, every team folded together. */
function buildPerformanceTrend(
  rows: TeamPerformanceRow[],
  semolinaProductId: string | null | undefined,
  products: Parameters<typeof convertQuantity>[3],
  uoms: Parameters<typeof convertQuantity>[4],
): { period: string; yieldPercent: number | null; wastePercent: number | null; downtimePercent: number | null }[] {
  const byPeriod = new Map<
    string,
    { produced: number; materialInput: number; production: number; downtime: number; waste: { product_id: string; quantity: number }[] }
  >();
  for (const row of rows) {
    const entry = byPeriod.get(row.period) ?? { produced: 0, materialInput: 0, production: 0, downtime: 0, waste: [] };
    entry.produced += row.produced_quantity;
    entry.materialInput += row.material_input_quantity;
    entry.production += row.production_minutes;
    entry.downtime += row.downtime_minutes;
    entry.waste.push(...row.waste_by_product);
    byPeriod.set(row.period, entry);
  }

  return [...byPeriod.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([period, entry]) => {
      const comparableWaste = semolinaProductId
        ? entry.waste.reduce((total, item) => {
            const converted = convertQuantity(item.quantity, item.product_id, semolinaProductId, products, uoms);
            return converted === null ? total : total + converted;
          }, 0)
        : null;
      return {
        period,
        yieldPercent: entry.materialInput > 0 ? Math.round((entry.produced / entry.materialInput) * 1000) / 10 : null,
        wastePercent: comparableWaste !== null && entry.materialInput > 0 ? Math.round((comparableWaste / entry.materialInput) * 1000) / 10 : null,
        downtimePercent:
          entry.production + entry.downtime > 0 ? Math.round((entry.downtime / (entry.production + entry.downtime)) * 1000) / 10 : null,
      };
    });
}

function sum(values: number[]): number {
  return values.reduce((total, value) => total + value, 0);
}

function lowStockProducts(
  stock: { product_id: string; quantity_on_hand: number }[],
  products: { id: string; name: string; stock_alert_threshold: number | null }[],
): string[] {
  // Reuses core.products.stock_alert_threshold, the field the warehouse analysis
  // page already flags on — deliberately not a second minimum of production's own.
  const onHand = new Map<string, number>();
  for (const item of stock) {
    onHand.set(item.product_id, (onHand.get(item.product_id) ?? 0) + item.quantity_on_hand);
  }
  return products
    .filter((p) => p.stock_alert_threshold != null && (onHand.get(p.id) ?? 0) < p.stock_alert_threshold)
    .map((p) => p.name);
}

function buildAlerts({
  pendingCount,
  lowStock,
  wasteRatio,
  downtimeRatio,
  quarantined,
}: {
  pendingCount: number;
  lowStock: string[];
  wasteRatio: number | null;
  downtimeRatio: number | null;
  quarantined: number;
}): Alert[] {
  const alerts: Alert[] = [];

  if (pendingCount > 0) {
    alerts.push({
      code: "pending-validations",
      tone: "warning",
      titleKey: "production.dashboard.alert.pendingValidations",
      // Figures that have not posted stock yet, so every downstream number is short.
      detail: String(pendingCount),
      to: "/production?tab=validation",
    });
  }
  if (lowStock.length > 0) {
    alerts.push({
      code: "low-stock",
      tone: "warning",
      titleKey: "production.dashboard.alert.lowStock",
      detail: lowStock.slice(0, 4).join(", "),
      to: "/warehouse",
    });
  }
  if (wasteRatio !== null && wasteRatio > WASTE_RATIO_ALERT) {
    alerts.push({
      code: "excessive-waste",
      tone: "destructive",
      titleKey: "production.dashboard.alert.excessiveWaste",
      detail: `${(wasteRatio * 100).toFixed(1)}%`,
      to: "/production?tab=daily-reports",
    });
  }
  if (downtimeRatio !== null && downtimeRatio > DOWNTIME_RATIO_ALERT) {
    alerts.push({
      code: "excessive-downtime",
      tone: "destructive",
      titleKey: "production.dashboard.alert.excessiveDowntime",
      detail: `${(downtimeRatio * 100).toFixed(1)}%`,
      to: "/production?tab=daily-reports",
    });
  }
  if (quarantined > 0) {
    alerts.push({
      code: "quarantined",
      tone: "destructive",
      titleKey: "production.dashboard.alert.quarantined",
      detail: String(quarantined),
      to: "/quality?tab=non-conformities",
    });
  }
  return alerts;
}

function Ratio({
  icon,
  label,
  ratio,
  goodIsHigh,
}: {
  icon: React.ReactNode;
  label: string;
  ratio: number | null;
  goodIsHigh: boolean;
}) {
  const { t } = useI18n();
  // A null ratio is "nothing measured yet", which is not the same as zero — and
  // showing 0% would read as a catastrophic result rather than no data.
  if (ratio === null) {
    return (
      <div className="space-y-1">
        <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
          {icon}
          {label}
        </div>
        <p className="text-sm text-muted-foreground">{t("production.dashboard.health.noData")}</p>
      </div>
    );
  }

  const percent = Math.min(100, Math.max(0, ratio * 100));
  const healthy = goodIsHigh ? ratio >= 0.95 : ratio <= (goodIsHigh ? 1 : 0.1);

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
        {icon}
        {label}
        <span className={cn("ml-auto font-medium tabular-nums", healthy ? "text-success" : "text-warning")}>
          {percent.toFixed(1)}%
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <motion.div
          className={cn("h-full rounded-full", healthy ? "bg-success" : "bg-warning")}
          initial={{ width: 0 }}
          animate={{ width: `${percent}%` }}
          transition={{ duration: 0.4, ease: "easeOut" }}
        />
      </div>
    </div>
  );
}
