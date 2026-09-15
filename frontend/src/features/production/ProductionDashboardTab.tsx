import { useState } from "react";
import { useMutation, useQueries, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  Activity,
  CalendarClock,
  ClipboardCheck,
  Droplets,
  Factory,
  Gauge,
  Loader2,
  PackageCheck,
  Recycle,
  Scale,
  Sparkles,
  Timer,
  TrendingDown,
  TrendingUp,
  Users,
} from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { useAuth } from "../../lib/auth";
import { currentLocale, useI18n } from "../../lib/i18n";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell, ResizableTableHead } from "../../components/ui/table";
import { Skeleton } from "../../components/ui/skeleton";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { StatCard } from "../../components/patterns/StatCard";
import { UnitBreakdownStat } from "../../components/patterns/UnitBreakdownStat";
import { StatBreakdownPopover, type StatBreakdownRow } from "../../components/patterns/StatBreakdownPopover";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { DateRangeFilter } from "../../components/patterns/DateRangeFilter";
import { commonUnit, convertQuantity, formatQuantity, productUnit, totalsByUomCategory, UTILITY_UNITS } from "../../lib/units";
import { listUoms } from "../warehouse/api";
import { EmptyState } from "../../components/patterns/EmptyState";
import { cn } from "../../lib/utils";
import {
  getRecipeCorrelationInsight,
  getWorkOrderConsolidation,
  listDowntimeBreakdown,
  listDowntimeReasons,
  listMachinePerformance,
  listMachines,
  listPackagingVariance,
  listRecipeCorrelation,
  listRecipeDrift,
  listRegrindBatches,
  listReports,
  listTeamPerformance,
  listWorkOrders,
  type DowntimeBreakdownRow,
  type Machine,
  type MachinePerformanceRow,
  type OfConsolidation,
  type ProductPackagingVariance,
  type RecipeCorrelationRow,
  type RegrindBatchSummary,
  type TeamPerformanceRow,
  type WasteCategory,
  type WorkOrder,
} from "./api";
import { listNonConformities } from "../qc/api";
import { listLots, type Lot } from "../products/api";
import { listProducts, listStock, type Product } from "../warehouse/api";

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
// A lot within two weeks of its DLC is worth watching; within three days is
// worth acting on today.
const DLC_WARNING_DAYS = 14;
const DLC_URGENT_DAYS = 3;

// The daily report's own waste stages, in the plant's form order — never
// product/packaging, which is the packing report's and isn't semoule any more.
const DAILY_WASTE_CATEGORIES = [
  "raw_material",
  "press",
  "pouring",
  "cross",
  "kneading",
  "finished_product_conditioning",
] as const satisfies readonly WasteCategory[];

// Fixed categorical order (never cycled, never reassigned by a filter) — the
// validated palette's first six slots, which clear the adjacent-pair CVD gate
// stacked segments need.
const WASTE_CATEGORY_COLORS: Record<(typeof DAILY_WASTE_CATEGORIES)[number], string> = {
  raw_material: "#2a78d6",
  press: "#eb6834",
  pouring: "#1baf7a",
  cross: "#eda100",
  kneading: "#e87ba4",
  finished_product_conditioning: "#008300",
};

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
  const { data: downtimeBreakdown = [] } = useQuery({
    queryKey: ["production", "downtime-breakdown", range.from, range.to],
    queryFn: () => listDowntimeBreakdown(token, { date_from: range.from, date_to: range.to }),
  });
  const { data: recipeCorrelation = [] } = useQuery({
    queryKey: ["production", "recipe-correlation"],
    queryFn: () => listRecipeCorrelation(token),
  });
  const { data: recipeDrift = [] } = useQuery({
    queryKey: ["production", "recipe-drift", range.from, range.to],
    queryFn: () => listRecipeDrift(token, { date_from: range.from, date_to: range.to }),
  });
  // Same grouping as team performance, keyed by machine instead of team — a
  // line can run more than one machine at once, so productivity has to be
  // checkable per machine, not just per line it sits on.
  const { data: machinePerformance = [] } = useQuery({
    queryKey: ["production", "machine-performance", range.from, range.to],
    queryFn: () => listMachinePerformance(token, { grain: "week", date_from: range.from, date_to: range.to }),
  });
  const { data: machines = [] } = useQuery({
    queryKey: ["production", "machines"],
    queryFn: () => listMachines(token),
  });
  // Écart de conditionnement, plant-wide by product — the scale against the
  // counter. Already computed by the backend for the OF/report drill-downs;
  // this is the same figure folded across the dashboard's own date range.
  const { data: packagingVariance = [] } = useQuery({
    queryKey: ["production", "packaging-variance", range.from, range.to],
    queryFn: () => listPackagingVariance(token, { date_from: range.from, date_to: range.to }),
  });
  // No date filter on the endpoint itself -- it returns every batch ever
  // opened, so the dashboard buckets by created_at against its own range
  // client-side (see buildRegrindSummary).
  const { data: regrindBatches = [] } = useQuery({
    queryKey: ["production", "regrind-batches"],
    queryFn: () => listRegrindBatches(token),
  });
  // Every lot, tenant-wide -- no date filter on the endpoint (only
  // product_id), so near-expiry is a client-side filter against today.
  const { data: lots = [] } = useQuery({
    queryKey: ["warehouse", "lots"],
    queryFn: () => listLots(token),
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

  // Same validated reports the consolidation above sums, fetched again here
  // only for their `team` field — so a tile can say which OF and which team
  // a figure actually came from, not just the plant-wide total.
  const activeOrderReports = useQueries({
    queries: activeOrders.map((order) => ({
      queryKey: ["production", "reports", "of", order.id, "validated"],
      queryFn: () => listReports(token, { of_id: order.id, status: "validated" }),
    })),
  });
  function teamsForOrder(index: number): string[] {
    return [
      ...new Set(
        (activeOrderReports[index]?.data ?? [])
          .map((report) => report.team)
          .filter((team): team is string => Boolean(team)),
      ),
    ];
  }

  // One drill-down row set per stat tile, each answering "which OF, and which
  // team" for that tile's own number. Built from the same activeOrders /
  // consolidations already fetched above, never a second source of truth.
  const activeOrdersRows: StatBreakdownRow[] = activeOrders.map((order, index) => {
    const data = consolidations[index]?.data;
    return {
      id: order.id,
      label: order.reference,
      href: `/production/work-orders/${order.id}`,
      status: <StatusBadge status={order.status} />,
      teams: teamsForOrder(index),
      lines: data
        ? [
            {
              label: t("production.dashboard.active.breakdown.progress"),
              value: `${Math.round(data.produced_quantity)} / ${Math.round(data.material_input_quantity)}`,
            },
          ]
        : [],
    };
  });

  const producedRows: StatBreakdownRow[] = activeOrders
    .map((order, index): StatBreakdownRow | null => {
      const data = consolidations[index]?.data;
      if (!data || data.produced_quantity <= 0) return null;
      return {
        id: order.id,
        label: order.reference,
        href: `/production/work-orders/${order.id}`,
        teams: teamsForOrder(index),
        lines: [
          {
            label: t("production.dashboard.stat.produced"),
            value: formatQuantity(data.produced_quantity, productUnit(data.product_id, products, uoms)),
          },
        ],
      };
    })
    .filter((row): row is StatBreakdownRow => row !== null);

  const semolinaRows: StatBreakdownRow[] = activeOrders
    .map((order, index): StatBreakdownRow | null => {
      const data = consolidations[index]?.data;
      if (!data || data.raw_material.semolina_quantity <= 0) return null;
      return {
        id: order.id,
        label: order.reference,
        href: `/production/work-orders/${order.id}`,
        teams: teamsForOrder(index),
        lines: [
          {
            label: t("production.dashboard.stat.semolina"),
            value: formatQuantity(
              data.raw_material.semolina_quantity,
              productUnit(data.raw_material.semolina_product_id, products, uoms),
            ),
          },
        ],
      };
    })
    .filter((row): row is StatBreakdownRow => row !== null);

  const wasteRows: StatBreakdownRow[] = activeOrders
    .map((order, index): StatBreakdownRow | null => {
      const data = consolidations[index]?.data;
      if (!data || data.waste.by_product.length === 0) return null;
      return {
        id: order.id,
        label: order.reference,
        href: `/production/work-orders/${order.id}`,
        teams: teamsForOrder(index),
        lines: data.waste.by_product.map((entry) => ({
          label:
            (entry.product_id && products.find((p) => p.id === entry.product_id)?.name) ||
            t("production.waste.unknownItem"),
          value: formatQuantity(entry.quantity, productUnit(entry.product_id, products, uoms)),
        })),
      };
    })
    .filter((row): row is StatBreakdownRow => row !== null);

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
  //
  // The anchor only needs to name *a* weight unit, not a specific quality —
  // convertQuantity only checks that the categories agree. So an order that
  // poured two qualities (semolina_product_id null, per _semolina_totals)
  // still yields a usable anchor here: pick the single largest quality across
  // every active order instead of the collapsed, possibly-null per-order id.
  const semolinaProductId = loadedConsolidations
    .flatMap((c) => c.raw_material.semolina_by_product)
    .reduce<{ product_id: string; quantity: number } | null>(
      (best, entry) => (best === null || entry.quantity > best.quantity ? entry : best),
      null,
    )?.product_id;
  const comparableWaste = semolinaProductId
    ? wasteEntries.reduce((total, entry) => {
        const converted = convertQuantity(entry.quantity, entry.product_id, semolinaProductId, products, uoms);
        return converted === null ? total : total + converted;
      }, 0)
    : null;
  const wasteRatio = comparableWaste !== null && semolina > 0 ? comparableWaste / semolina : null;
  const downtimeRatio =
    productionMinutes + downtimeMinutes > 0 ? downtimeMinutes / (productionMinutes + downtimeMinutes) : null;

  // Which single active order is behind the plant-wide ratio above — so the
  // alert can send the reader somewhere specific instead of a generic tab.
  const worstWaste = worstWasteOrder(loadedConsolidations, products, uoms);
  const worstDowntime = worstDowntimeOrder(loadedConsolidations);

  // Utilities are recorded per shift but have no product to derive a unit
  // from — they're fixed columns (see UTILITY_UNITS), so summing them needs
  // no conversion. produced_quantity is always tonnes (decision 17), so
  // dividing by it is already a true per-tonne figure.
  const waterQuantity = sum(loadedConsolidations.map((c) => c.utilities.water_quantity));
  const fuelQuantity = sum(loadedConsolidations.map((c) => c.utilities.fuel_quantity));
  const electricityQuantity = sum(loadedConsolidations.map((c) => c.utilities.electricity_quantity));

  // Écart de conditionnement, worst first — the same tolerance check the
  // per-OF drill-down already computes, just never surfaced plant-wide.
  const packagingAccuracyRows = buildPackagingAccuracyRows(packagingVariance as ProductPackagingVariance[], products);
  const outOfTolerance = packagingAccuracyRows.filter((row) => row.withinTolerance === false).map((row) => row.label);

  // Same team-performance rows the trend line and semoule-waste chart already
  // fetch, folded per team instead of per period — "whose yield is it," not
  // just "whose déchet is it."
  const teamLeaderboard = buildTeamLeaderboard(
    teamPerformance as TeamPerformanceRow[],
    semolinaProductId,
    products,
    uoms,
    t("production.dashboard.chart.semouleWaste.noTeam"),
  );

  // Rebroyat recovery: what a regrind batch actually gave back against what
  // scrap went into it — distinct from the Quality dashboard's disposition
  // chart, which tracks where *rejected* product ends up, not a batch's own
  // input/output efficiency.
  const regrindSummary = buildRegrindSummary(regrindBatches as RegrindBatchSummary[], range);

  // Finished-goods lots approaching their DLC, soonest first -- independent
  // of the dashboard's own date-range filter, since a lot doesn't stop being
  // a risk just because it was produced outside the selected window.
  const nearExpiryRows = buildNearExpiryRows(lots as Lot[], products, DLC_WARNING_DAYS);
  const urgentExpiry = nearExpiryRows.filter((row) => row.daysRemaining <= DLC_URGENT_DAYS);

  // One point per week, every team folded together — the same conversion the
  // snapshot ratios above use, applied per period instead of once. Weeks with
  // nothing validated yet are dropped rather than plotted as a false zero.
  const performanceTrend = buildPerformanceTrend(teamPerformance as TeamPerformanceRow[], semolinaProductId, products, uoms);

  // Folded across the whole selected range, per team rather than per period —
  // the trend above answers "is it improving," this answers "whose semoule is
  // it." Worst offender first, matching the downtime-reasons ranking below.
  const teamSemouleWaste = buildTeamSemouleWaste(
    teamPerformance as TeamPerformanceRow[],
    t("production.dashboard.chart.semouleWaste.noTeam"),
  );

  // Folded across the whole selected range, per machine — same shape as
  // teamSemouleWaste above. Most produced first: this answers "which machine
  // is carrying the line," downtime is a column here rather than the sort key.
  const machineSummary = buildMachineSummary(machinePerformance as MachinePerformanceRow[], machines);

  // Same downtime-reasons rows as the plant-wide Pareto above, re-folded by
  // team and by machine so the root cause is visible per dimension, not just
  // plant-wide -- one fetch, two client-side slices.
  const downtimeByTeam = buildDowntimeByTeam(
    downtimeBreakdown as DowntimeBreakdownRow[],
    t("production.dashboard.chart.semouleWaste.noTeam"),
  );
  const downtimeByMachine = buildDowntimeByMachine(
    downtimeBreakdown as DowntimeBreakdownRow[],
    machines,
    t("production.dashboard.downtimeBreakdown.noMachine"),
  );

  const alerts = buildAlerts({
    pendingCount: pendingReports.length,
    lowStock: lowStockProducts(stock, products),
    wasteRatio,
    worstWaste,
    downtimeRatio,
    worstDowntime,
    quarantined: nonConformities.filter((n) => n.status === "quarantined").length,
    outOfTolerance,
    urgentExpiryCount: urgentExpiry.length,
    soonestExpiry: nearExpiryRows[0] ?? null,
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
        <StatBreakdownPopover
          trigger={
            <StatCard
              label={t("production.dashboard.stat.activeOrders")}
              value={activeOrders.length}
              icon={<Factory className="h-5 w-5" />}
              accent="warning"
            />
          }
          title={t("production.dashboard.stat.activeOrders.breakdown.title")}
          emptyMessage={t("production.dashboard.stat.activeOrders.breakdown.empty")}
          rows={activeOrdersRows}
          footer={
            <a href="#active-work-orders" className="mt-2 block text-xs font-medium text-primary hover:underline">
              {t("production.dashboard.stat.activeOrders.breakdown.tableLink")}
            </a>
          }
        />
        <StatBreakdownPopover
          trigger={
            <StatCard
              label={t("production.dashboard.stat.produced")}
              value={Math.round(produced)}
              unit={producedUnit}
              icon={<PackageCheck className="h-5 w-5" />}
              accent="success"
            />
          }
          title={t("production.dashboard.stat.produced.breakdown.title")}
          emptyMessage={t("production.dashboard.stat.produced.breakdown.empty")}
          rows={producedRows}
        />
        <StatBreakdownPopover
          trigger={
            <StatCard
              label={t("production.dashboard.stat.semolina")}
              value={Math.round(semolina)}
              unit={semolinaUnit}
              icon={<Activity className="h-5 w-5" />}
              accent="primary"
            />
          }
          title={t("production.dashboard.stat.semolina.breakdown.title")}
          emptyMessage={t("production.dashboard.stat.semolina.breakdown.empty")}
          rows={semolinaRows}
        />
        <StatBreakdownPopover
          trigger={
            <UnitBreakdownStat
              label={t("production.dashboard.stat.waste")}
              breakdown={wasteTotals.map((total) => ({ unit: total.unit, value: Math.round(total.value) }))}
              icon={<Recycle className="h-5 w-5" />}
              accent="destructive"
            />
          }
          title={t("production.dashboard.stat.waste.breakdown.title")}
          emptyMessage={t("production.dashboard.stat.waste.breakdown.empty")}
          rows={wasteRows}
          footer={
            <a href="#team-waste-breakdown" className="mt-2 block text-xs font-medium text-primary hover:underline">
              {t("production.dashboard.stat.waste.breakdown.teamsLink")}
            </a>
          }
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
              // Quality checks are validated per OF; a closed OF's checks
              // don't count here even if they exist elsewhere -- say so
              // instead of leaving "nothing measured" to read as data loss.
              noDataLabel={t("production.dashboard.health.conformityNoData")}
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
          <CardTitle className="flex items-center gap-1.5">
            <Droplets className="h-4 w-4" />
            {t("production.dashboard.utilities.title")}
          </CardTitle>
          <CardDescription>{t("production.dashboard.utilities.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          {produced <= 0 ? (
            <EmptyState
              icon={<Droplets className="h-5 w-5" />}
              title={t("production.dashboard.utilities.empty.title")}
              description={t("production.dashboard.utilities.empty.description")}
            />
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <UtilityStat
                label={t("production.dailyReports.field.water")}
                perTonne={waterQuantity / produced}
                unit={UTILITY_UNITS.water}
              />
              <UtilityStat
                label={t("production.dailyReports.field.fuel")}
                perTonne={fuelQuantity / produced}
                unit={UTILITY_UNITS.fuel}
              />
              <UtilityStat
                label={t("production.dailyReports.field.electricity")}
                perTonne={electricityQuantity / produced}
                unit={UTILITY_UNITS.electricity}
              />
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            <Recycle className="h-4 w-4" />
            {t("production.dashboard.regrind.title")}
          </CardTitle>
          <CardDescription>{t("production.dashboard.regrind.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          {regrindSummary.finishedCount === 0 ? (
            <EmptyState
              icon={<Recycle className="h-5 w-5" />}
              title={t("production.dashboard.regrind.empty.title")}
              description={t("production.dashboard.regrind.empty.description")}
            />
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <MiniStat
                label={t("production.dashboard.regrind.yield")}
                value={regrindSummary.yieldRatio !== null ? `${(regrindSummary.yieldRatio * 100).toFixed(1)}%` : "—"}
              />
              <MiniStat
                label={t("production.regrind.stat.totalLoss")}
                value={
                  <>
                    {formatQty(regrindSummary.lossTotal)} <span className="text-sm font-normal text-muted-foreground">KG</span>
                  </>
                }
              />
              <MiniStat label={t("production.dashboard.regrind.finishedBatches")} value={regrindSummary.finishedCount} />
            </div>
          )}
        </CardContent>
      </Card>

      <Card id="active-work-orders" className="scroll-mt-4">
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
          <CardTitle className="flex items-center gap-1.5">
            <Users className="h-4 w-4" />
            {t("production.dashboard.teamPerformance.title")}
          </CardTitle>
          <CardDescription>{t("production.dashboard.teamPerformance.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          {teamLeaderboard.length === 0 ? (
            <EmptyState
              icon={<Users className="h-5 w-5" />}
              title={t("production.dashboard.teamPerformance.empty.title")}
              description={t("production.dashboard.teamPerformance.empty.description")}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("production.dashboard.teamPerformance.column.team")}</TableHead>
                  <TableHead className="text-right">{t("production.dashboard.machinePerformance.column.reports")}</TableHead>
                  <TableHead className="text-right">{t("production.dashboard.trend.yield")}</TableHead>
                  <TableHead className="text-right">{t("production.dashboard.trend.waste")}</TableHead>
                  <TableHead className="text-right">{t("production.dashboard.trend.downtime")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {teamLeaderboard.map((row) => (
                  <TableRow key={row.team}>
                    <TableCell className="font-medium">{row.team}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.reportCount}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.yieldPercent !== null ? `${row.yieldPercent}%` : "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      <span
                        className={
                          row.wastePercent !== null && row.wastePercent > WASTE_RATIO_ALERT * 100
                            ? "text-destructive"
                            : undefined
                        }
                      >
                        {row.wastePercent !== null ? `${row.wastePercent}%` : "—"}
                      </span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      <span
                        className={
                          row.downtimePercent !== null && row.downtimePercent > DOWNTIME_RATIO_ALERT * 100
                            ? "text-destructive"
                            : undefined
                        }
                      >
                        {row.downtimePercent !== null ? `${row.downtimePercent}%` : "—"}
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card id="team-waste-breakdown" className="scroll-mt-4">
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            <Recycle className="h-4 w-4" />
            {t("production.dashboard.chart.semouleWaste.title")}
          </CardTitle>
          <CardDescription>{t("production.dashboard.chart.semouleWaste.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          {teamSemouleWaste.length === 0 ? (
            <EmptyState
              icon={<Recycle className="h-5 w-5" />}
              title={t("production.dashboard.chart.semouleWaste.empty.title")}
              description={t("production.dashboard.chart.semouleWaste.empty.description")}
            />
          ) : (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <ResponsiveContainer width="100%" height={Math.max(200, Math.min(8, teamSemouleWaste.length) * 48)}>
                <BarChart data={teamSemouleWaste} layout="vertical" margin={{ left: 24 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                  <YAxis
                    type="category"
                    dataKey="team"
                    width={110}
                    tick={{ fontSize: 11, fill: "hsl(215 16% 47%)" }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    formatter={(value) => formatWasteStageQuantity(Number(value))}
                    contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }}
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  {DAILY_WASTE_CATEGORIES.map((category) => (
                    <Bar
                      key={category}
                      dataKey={category}
                      stackId="semoule-waste"
                      name={t(`production.waste.category.${category}` as Parameters<typeof t>[0])}
                      fill={WASTE_CATEGORY_COLORS[category]}
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
              <div className="space-y-1.5">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {t("production.dashboard.chart.semouleWaste.netLabel")}
                </p>
                {teamSemouleWaste.map((row) => (
                  <div
                    key={row.team}
                    className="flex items-center justify-between rounded-lg border border-border px-3 py-2 text-sm"
                  >
                    <span className="font-medium">{row.team}</span>
                    <span className={cn("tabular-nums", row.netSemouleWaste > 0 ? "text-destructive" : "text-muted-foreground")}>
                      {formatQty(row.netSemouleWaste)} <span className="text-xs font-normal text-muted-foreground">KG</span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

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
          <CardTitle>{t("production.dashboard.downtimeBreakdown.title")}</CardTitle>
          <CardDescription>{t("production.dashboard.downtimeBreakdown.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          {downtimeByMachine.length === 0 && downtimeByTeam.length === 0 ? (
            <EmptyState
              icon={<Timer className="h-5 w-5" />}
              title={t("production.dashboard.chart.downtimeReasons.empty.title")}
              description={t("production.dashboard.chart.downtimeReasons.empty.description")}
            />
          ) : (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div>
                <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {t("production.dashboard.downtimeBreakdown.byMachine")}
                </p>
                <div className="space-y-1.5">
                  {downtimeByMachine.slice(0, 6).map((row) => (
                    <div key={row.key} className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2 text-sm">
                      <div className="min-w-0">
                        <p className="truncate font-medium">{row.label}</p>
                        {row.topReason && (
                          <p className="truncate text-xs text-muted-foreground">
                            {row.topReason} · {row.topReasonMinutes} {t("production.dashboard.chart.downtimeReasons.minutes").toLowerCase()}
                          </p>
                        )}
                      </div>
                      <span className="shrink-0 tabular-nums font-medium text-destructive">{row.totalMinutes}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {t("production.dashboard.downtimeBreakdown.byTeam")}
                </p>
                <div className="space-y-1.5">
                  {downtimeByTeam.slice(0, 6).map((row) => (
                    <div key={row.key} className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2 text-sm">
                      <div className="min-w-0">
                        <p className="truncate font-medium">{row.label}</p>
                        {row.topReason && (
                          <p className="truncate text-xs text-muted-foreground">
                            {row.topReason} · {row.topReasonMinutes} {t("production.dashboard.chart.downtimeReasons.minutes").toLowerCase()}
                          </p>
                        )}
                      </div>
                      <span className="shrink-0 tabular-nums font-medium text-destructive">{row.totalMinutes}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("production.dashboard.machinePerformance.title")}</CardTitle>
          <CardDescription>{t("production.dashboard.machinePerformance.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          {machineSummary.length === 0 ? (
            <EmptyState
              icon={<Gauge className="h-5 w-5" />}
              title={t("production.dashboard.machinePerformance.empty.title")}
              description={t("production.dashboard.machinePerformance.empty.description")}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("production.dashboard.machinePerformance.column.machine")}</TableHead>
                  <TableHead className="text-right">{t("production.dashboard.machinePerformance.column.reports")}</TableHead>
                  <TableHead className="text-right">{t("production.dashboard.machinePerformance.column.produced")}</TableHead>
                  <TableHead className="text-right">{t("production.dashboard.machinePerformance.column.productionMinutes")}</TableHead>
                  <TableHead className="text-right">{t("production.dashboard.machinePerformance.column.downtimeMinutes")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {machineSummary.map((row) => (
                  <TableRow key={row.equipmentId}>
                    <TableCell className="font-medium">{row.label}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.reportCount}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatQty(row.produced)}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.productionMinutes}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      <span className={row.downtimeMinutes > 0 ? "text-destructive" : undefined}>{row.downtimeMinutes}</span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card id="packaging-accuracy" className="scroll-mt-4">
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            <Scale className="h-4 w-4" />
            {t("production.dashboard.packagingAccuracy.title")}
          </CardTitle>
          <CardDescription>{t("production.dashboard.packagingAccuracy.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          {packagingAccuracyRows.length === 0 ? (
            <EmptyState
              icon={<Scale className="h-5 w-5" />}
              title={t("production.dashboard.packagingAccuracy.empty.title")}
              description={t("production.dashboard.packagingAccuracy.empty.description")}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("production.dashboard.packagingAccuracy.column.product")}</TableHead>
                  <TableHead className="text-right">{t("production.packagingVariance.field.expectedPackets")}</TableHead>
                  <TableHead className="text-right">{t("production.packagingVariance.field.countedPackets")}</TableHead>
                  <TableHead className="text-right">{t("production.packagingVariance.field.packetVariance")}</TableHead>
                  <TableHead className="text-right">{t("production.dashboard.packagingAccuracy.column.status")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {packagingAccuracyRows.map((row) => (
                  <TableRow key={row.productId}>
                    <TableCell className="font-medium">{row.label}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.expectedPackets !== null ? formatQty(row.expectedPackets) : "—"}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatQty(row.countedPackets)}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {/* Colored by within_tolerance, not by sign: a small negative
                          variance inside the tolerance band is expected, not a
                          problem -- and rounding to a whole packet avoids an
                          Intl.NumberFormat "-0" for a variance that rounds to zero. */}
                      <span className={row.withinTolerance === false ? "text-destructive" : undefined}>
                        {row.packetVariance !== null
                          ? `${row.packetVariance > 0 ? "+" : ""}${formatQty(Math.round(row.packetVariance) || 0)}`
                          : "—"}
                      </span>
                      {row.packetVarianceRatio !== null && (
                        <span className="ml-1 text-xs text-muted-foreground">
                          ({row.packetVarianceRatio > 0 ? "+" : ""}
                          {(row.packetVarianceRatio * 100).toFixed(1)}%)
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {row.withinTolerance === null ? (
                        <span className="text-xs text-muted-foreground">—</span>
                      ) : (
                        <Badge variant={row.withinTolerance ? "success" : "destructive"}>
                          {t(
                            row.withinTolerance
                              ? "production.dashboard.packagingAccuracy.withinTolerance"
                              : "production.dashboard.packagingAccuracy.outOfTolerance",
                          )}
                        </Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            <CalendarClock className="h-4 w-4" />
            {t("production.dashboard.nearExpiry.title")}
          </CardTitle>
          <CardDescription>{t("production.dashboard.nearExpiry.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          {nearExpiryRows.length === 0 ? (
            <EmptyState
              icon={<CalendarClock className="h-5 w-5" />}
              title={t("production.dashboard.nearExpiry.empty.title")}
              description={t("production.dashboard.nearExpiry.empty.description")}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("production.dashboard.nearExpiry.column.product")}</TableHead>
                  <TableHead>{t("production.dashboard.nearExpiry.column.lot")}</TableHead>
                  <TableHead className="text-right">{t("production.dashboard.nearExpiry.column.expiryDate")}</TableHead>
                  <TableHead className="text-right">{t("production.dashboard.nearExpiry.column.daysRemaining")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {nearExpiryRows.map((row) => (
                  <TableRow key={row.lotId}>
                    <TableCell className="font-medium">{row.productLabel}</TableCell>
                    <TableCell>{row.lotNumber}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {new Intl.DateTimeFormat(currentLocale()).format(new Date(row.expiryDate))}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      <span className={row.daysRemaining <= DLC_URGENT_DAYS ? "text-destructive font-medium" : undefined}>
                        {row.daysRemaining}
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {recipeDrift.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{t("production.dashboard.recipeDrift.title")}</CardTitle>
            <CardDescription>{t("production.dashboard.recipeDrift.description")}</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("production.dashboard.recipeDrift.column.recipe")}</TableHead>
                  <TableHead className="text-right">{t("production.dashboard.recipeDrift.column.ofCount")}</TableHead>
                  <TableHead className="text-right">{t("production.dashboard.recipeDrift.column.hardFindings")}</TableHead>
                  <TableHead className="text-right">{t("production.dashboard.recipeDrift.column.softFindings")}</TableHead>
                  <TableHead>{t("production.dashboard.recipeDrift.column.topFinding")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recipeDrift.map((row) => (
                  <TableRow key={row.recipe_id}>
                    <TableCell className="font-medium">{row.recipe_id}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.of_count}</TableCell>
                    <TableCell className={`text-right tabular-nums ${row.hard_finding_of_count > 0 ? "text-destructive font-medium" : ""}`}>
                      {row.hard_finding_of_count}
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-amber-600">{row.soft_finding_of_count}</TableCell>
                    <TableCell className="text-sm">
                      {row.top_finding_code ? (
                        <span className="text-muted-foreground">
                          {t(
                            `production.recipeCheck.finding.${
                              row.top_finding_code === "BELOW_MINIMUM"
                                ? "belowMinimum"
                                : row.top_finding_code === "ABOVE_MAXIMUM"
                                  ? "aboveMaximum"
                                  : row.top_finding_code === "COMPONENT_NOT_POURED"
                                    ? "notPoured"
                                    : row.top_finding_code === "NOT_IN_RECIPE"
                                      ? "notInRecipe"
                                      : row.top_finding_code === "NEGATIVE_QUANTITY"
                                        ? "negative"
                                        : "unknown"
                            }`,
                          )}{" "}
                          ({row.top_finding_count}×)
                        </span>
                      ) : (
                        <span className="text-muted-foreground text-xs">—</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{t("production.dashboard.chart.recipeCorrelation.title")}</CardTitle>
          <CardDescription>{t("production.dashboard.chart.recipeCorrelation.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          {recipeCorrelation.length === 0 ? (
            <EmptyState
              icon={<Activity className="h-5 w-5" />}
              title={t("production.dashboard.chart.recipeCorrelation.empty.title")}
              description={t("production.dashboard.chart.recipeCorrelation.empty.description")}
            />
          ) : (
            <RecipeCorrelationSection rows={recipeCorrelation} workOrders={workOrders} products={products} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/** Below this, a scatter is a handful of dots, not a trend — a table reads better. */
const RECIPE_CORRELATION_SCATTER_MIN_ROWS = 20;
/** Mirrors MIN_ROWS_FOR_INSIGHT in recipe_correlation_insight_service.py — kept in
 * sync so the button disables itself instead of round-tripping to learn the same thing. */
const RECIPE_CORRELATION_INSIGHT_MIN_ROWS = 10;

function recipeWaterStatus(row: RecipeCorrelationRow): "below" | "above" | null {
  if (row.water_percentage === null || row.water_target_min === null || row.water_target_max === null) return null;
  if (row.water_percentage < row.water_target_min) return "below";
  if (row.water_percentage > row.water_target_max) return "above";
  return null;
}

function RecipeCorrelationSection({
  rows,
  workOrders,
  products,
}: {
  rows: RecipeCorrelationRow[];
  workOrders: WorkOrder[];
  products: Product[];
}) {
  const { t, language } = useI18n();
  const { session } = useAuth();
  const token = session!.token;

  // User-triggered only -- never on mount or on a data refetch. Each call is a
  // real request against the Groq free tier's rate limit, and every viewer
  // opening this dashboard must not silently spend it.
  const insightMutation = useMutation({
    mutationFn: () => getRecipeCorrelationInsight(token, language),
  });

  const columns: ColumnDef<RecipeCorrelationRow>[] = [
    {
      key: "date",
      header: t("production.dashboard.chart.recipeCorrelation.column.date"),
      defaultWidth: 110,
      // Guarded against a stale/partial API response rather than trusting report_date
      // is always a valid date string -- Intl.DateTimeFormat.format throws (not NaN)
      // on an Invalid Date, which would otherwise take the whole card down.
      cell: (row) => {
        if (!row.report_date) return "—";
        const parsed = new Date(row.report_date);
        return Number.isNaN(parsed.getTime()) ? "—" : new Intl.DateTimeFormat(currentLocale()).format(parsed);
      },
      sortValue: (row) => row.report_date ?? "",
    },
    {
      key: "team",
      header: t("production.dashboard.chart.recipeCorrelation.column.team"),
      defaultWidth: 110,
      cell: (row) => row.team ?? t("production.dashboard.chart.semouleWaste.noTeam"),
      sortValue: (row) => row.team ?? "",
    },
    {
      key: "workOrder",
      header: t("production.dashboard.chart.recipeCorrelation.column.workOrder"),
      defaultWidth: 140,
      cell: (row) => <span className="font-medium">{workOrders.find((o) => o.id === row.of_id)?.reference ?? row.of_id}</span>,
      sortValue: (row) => workOrders.find((o) => o.id === row.of_id)?.reference ?? row.of_id,
    },
    {
      key: "product",
      header: t("production.dashboard.chart.recipeCorrelation.column.product"),
      defaultWidth: 160,
      cell: (row) => products.find((p) => p.id === row.product_id)?.name ?? "—",
      sortValue: (row) => products.find((p) => p.id === row.product_id)?.name ?? "",
    },
    {
      key: "water",
      header: t("production.dashboard.chart.recipeCorrelation.waterAxis"),
      defaultWidth: 190,
      headerClassName: "text-right",
      cellClassName: "text-right",
      cell: (row) => {
        const status = recipeWaterStatus(row);
        return (
          <div>
            <div className="flex items-center justify-end gap-2 tabular-nums">
              <span>{row.water_percentage !== null ? `${row.water_percentage}%` : "—"}</span>
              {status && (
                <Badge variant="warning">
                  {t(
                    status === "below"
                      ? "production.dashboard.chart.recipeCorrelation.badge.belowTarget"
                      : "production.dashboard.chart.recipeCorrelation.badge.aboveTarget",
                  )}
                </Badge>
              )}
            </div>
            {row.water_target_min !== null && row.water_target_max !== null && (
              <div className="text-xs text-muted-foreground">
                {t("production.dashboard.chart.recipeCorrelation.column.target")} {row.water_target_min}–{row.water_target_max}%
              </div>
            )}
          </div>
        );
      },
      sortValue: (row) => row.water_percentage,
    },
    {
      key: "flowRate",
      header: t("production.dashboard.chart.recipeCorrelation.flowRateAxis"),
      defaultWidth: 130,
      headerClassName: "text-right",
      cellClassName: "text-right tabular-nums",
      cell: (row) => (row.semolina_flow_rate !== null ? row.semolina_flow_rate : "—"),
      sortValue: (row) => row.semolina_flow_rate,
    },
    {
      key: "yield",
      header: t("production.dashboard.chart.recipeCorrelation.yieldAxis"),
      defaultWidth: 120,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right font-medium tabular-nums",
      cell: (row) => `${Math.round(row.yield_ratio * 1000) / 10}%`,
      sortValue: (row) => row.yield_ratio,
    },
  ];

  const { visibleColumns, colWidths, getWidth, setWidth, sortDirectionFor, toggleSort, sortRows } = useTableColumns(
    "production.dashboard.recipeCorrelation",
    columns,
  );
  // Newest shift first until a header is actually clicked. Falls back to "" rather
  // than crashing the whole card if a stale backend response is missing the field.
  const sortedRows = sortRows([...rows].sort((a, b) => (b.report_date ?? "").localeCompare(a.report_date ?? "")));

  const hasEnoughRowsForInsight = rows.length >= RECIPE_CORRELATION_INSIGHT_MIN_ROWS;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="outline"
          size="sm"
          onClick={() => insightMutation.mutate()}
          disabled={insightMutation.isPending || !hasEnoughRowsForInsight}
        >
          {insightMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
          {insightMutation.isPending
            ? t("production.dashboard.chart.recipeCorrelation.insight.loading")
            : t("production.dashboard.chart.recipeCorrelation.insight.button")}
        </Button>
        {!hasEnoughRowsForInsight && (
          <p className="text-sm text-muted-foreground">{t("production.dashboard.chart.recipeCorrelation.insight.minRowsHint")}</p>
        )}
        {hasEnoughRowsForInsight && insightMutation.isSuccess && (
          <p className="text-sm text-muted-foreground">
            {insightMutation.data.available ? insightMutation.data.text : t("production.dashboard.chart.recipeCorrelation.insight.unavailable")}
          </p>
        )}
        {hasEnoughRowsForInsight && insightMutation.isError && (
          <p className="text-sm text-destructive">{t("production.dashboard.chart.recipeCorrelation.insight.error")}</p>
        )}
      </div>

      <Table colWidths={colWidths}>
        <TableHeader>
          <TableRow>
            {visibleColumns.map((column) => (
              <ResizableTableHead
                key={column.key}
                width={getWidth(column.key)}
                onResize={(width) => setWidth(column.key, width)}
                className={column.headerClassName}
                sortDirection={sortDirectionFor(column.key)}
                onSort={column.sortValue ? () => toggleSort(column.key) : undefined}
              >
                {column.header}
              </ResizableTableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {sortedRows.map((row) => (
            <TableRow key={row.report_id}>
              {visibleColumns.map((column) => (
                <TableCell key={column.key} className={column.cellClassName}>
                  {column.cell(row)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {rows.length >= RECIPE_CORRELATION_SCATTER_MIN_ROWS ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <RecipeScatter
            title={t("production.dashboard.chart.recipeCorrelation.water")}
            xLabel={t("production.dashboard.chart.recipeCorrelation.waterAxis")}
            data={rows
              .filter((r) => r.water_percentage !== null)
              .map((r) => ({ x: r.water_percentage as number, y: Math.round(r.yield_ratio * 1000) / 10 }))}
          />
          <RecipeScatter
            title={t("production.dashboard.chart.recipeCorrelation.flowRate")}
            xLabel={t("production.dashboard.chart.recipeCorrelation.flowRateAxis")}
            data={rows
              .filter((r) => r.semolina_flow_rate !== null)
              .map((r) => ({ x: r.semolina_flow_rate as number, y: Math.round(r.yield_ratio * 1000) / 10 }))}
          />
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">{t("production.dashboard.chart.recipeCorrelation.scatter.hint")}</p>
      )}
    </div>
  );
}

/** Padded to the data's own range rather than from zero — a tight cluster (e.g.
 * yield sitting at 95-115%) would otherwise be squeezed into a sliver of a
 * 0-120% axis. */
function paddedDomain(padding: number): [(min: number) => number, (max: number) => number] {
  return [(min: number) => Math.floor(min - padding), (max: number) => Math.ceil(max + padding)];
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
            domain={paddedDomain(1)}
            tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }}
            axisLine={false}
            tickLine={false}
            label={{ value: xLabel, position: "insideBottom", offset: -4, fontSize: 11, fill: "hsl(215 16% 47%)" }}
          />
          <YAxis
            type="number"
            dataKey="y"
            name={t("production.dashboard.chart.recipeCorrelation.yieldAxis")}
            domain={paddedDomain(2)}
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

function MiniStat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums">{value}</p>
    </div>
  );
}

function UtilityStat({ label, perTonne, unit }: { label: string; perTonne: number; unit: string }) {
  const { t } = useI18n();
  return (
    <MiniStat
      label={label}
      value={
        <>
          {formatQty(perTonne)}{" "}
          <span className="text-sm font-normal text-muted-foreground">
            {unit}/{t("production.dashboard.utilities.tonneAbbr")}
          </span>
        </>
      }
    />
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

interface TeamSemouleWasteRow {
  team: string;
  raw_material: number;
  press: number;
  pouring: number;
  cross: number;
  kneading: number;
  finished_product_conditioning: number;
  regrindQuantity: number;
  netSemouleWaste: number;
}

/**
 * Folded across the whole selected range, per team — the écart the plant
 * wants to minimise: daily-report déchet (never conditionnement's product/
 * packaging, which isn't semoule any more) net of the rebroyat the team
 * declared over the same reports. Worst team first, same ranking shape as
 * `list_downtime_reasons` below.
 */
function buildTeamSemouleWaste(rows: TeamPerformanceRow[], noTeamLabel: string): TeamSemouleWasteRow[] {
  const byTeam = new Map<string, TeamSemouleWasteRow>();
  for (const row of rows) {
    const team = row.team ?? noTeamLabel;
    const entry: TeamSemouleWasteRow =
      byTeam.get(team) ??
      {
        team,
        raw_material: 0,
        press: 0,
        pouring: 0,
        cross: 0,
        kneading: 0,
        finished_product_conditioning: 0,
        regrindQuantity: 0,
        netSemouleWaste: 0,
      };
    for (const category of DAILY_WASTE_CATEGORIES) {
      entry[category] += row.daily_waste_by_category[category] ?? 0;
    }
    entry.regrindQuantity += row.regrind_quantity;
    // Not derived from the categories above minus regrindQuantity: those
    // categories are each converted into their own product's unit (e.g. tons
    // for semoule stocked by the ton), while regrind_quantity is always raw
    // kilograms off the report form — subtracting one from the other would
    // net tons against kilos. net_semoule_waste is the backend's own figure,
    // computed on a consistent raw-kg basis on both sides (see
    // TeamPerformanceService.list_team_performance), and is additive across
    // periods since kilograms don't need converting to be summed.
    entry.netSemouleWaste += row.net_semoule_waste;
    byTeam.set(team, entry);
  }
  return [...byTeam.values()].sort((a, b) => b.netSemouleWaste - a.netSemouleWaste);
}

interface MachineSummaryRow {
  equipmentId: string;
  label: string;
  reportCount: number;
  produced: number;
  productionMinutes: number;
  downtimeMinutes: number;
}

/**
 * Folded across the whole selected range, per machine — same shape as
 * buildTeamSemouleWaste, grouped by equipment_id instead of team. equipment_id
 * is an opaque reference into the Maintenance module (production holds no live
 * FK into its schema), so it's resolved to a code/name via the machines list
 * fetched from GET /production/machines; a machine deleted since the report
 * was filed falls back to showing its raw id rather than dropping the row.
 */
function buildMachineSummary(rows: MachinePerformanceRow[], machines: Machine[]): MachineSummaryRow[] {
  const byMachine = new Map<string, MachineSummaryRow>();
  for (const row of rows) {
    if (!row.equipment_id) continue;
    const machine = machines.find((m) => m.id === row.equipment_id);
    const entry: MachineSummaryRow =
      byMachine.get(row.equipment_id) ??
      {
        equipmentId: row.equipment_id,
        label: machine ? `${machine.code} — ${machine.name}` : row.equipment_id,
        reportCount: 0,
        produced: 0,
        productionMinutes: 0,
        downtimeMinutes: 0,
      };
    entry.reportCount += row.report_count;
    entry.produced += row.produced_quantity;
    entry.productionMinutes += row.production_minutes;
    entry.downtimeMinutes += row.downtime_minutes;
    byMachine.set(row.equipment_id, entry);
  }
  return [...byMachine.values()].sort((a, b) => b.produced - a.produced);
}

interface DowntimeDimensionRow {
  key: string;
  label: string;
  totalMinutes: number;
  topReason: string | null;
  topReasonMinutes: number;
}

/** The single biggest reason within one team's or machine's own minutes --
 * "which motif is dragging this row down," not just its total. */
function topDowntimeReasonRow(key: string, label: string, reasonMinutes: Map<string, number>): DowntimeDimensionRow {
  const totalMinutes = [...reasonMinutes.values()].reduce((a, b) => a + b, 0);
  const top = [...reasonMinutes.entries()].sort((a, b) => b[1] - a[1])[0];
  return { key, label, totalMinutes, topReason: top?.[0] ?? null, topReasonMinutes: top?.[1] ?? 0 };
}

/** Same downtime-breakdown rows the plant-wide Pareto reads, re-folded by
 * team -- worst team first, each with its own dominant reason called out. */
function buildDowntimeByTeam(rows: DowntimeBreakdownRow[], noTeamLabel: string): DowntimeDimensionRow[] {
  const byTeam = new Map<string, Map<string, number>>();
  for (const row of rows) {
    const team = row.team ?? noTeamLabel;
    const reasons = byTeam.get(team) ?? new Map<string, number>();
    reasons.set(row.reason, (reasons.get(row.reason) ?? 0) + row.minutes);
    byTeam.set(team, reasons);
  }
  return [...byTeam.entries()]
    .map(([team, reasons]) => topDowntimeReasonRow(team, team, reasons))
    .sort((a, b) => b.totalMinutes - a.totalMinutes);
}

/** Same idea, keyed by machine -- equipment_id resolved to code/name via the
 * machines list, same fallback-to-raw-id convention as buildMachineSummary. */
function buildDowntimeByMachine(
  rows: DowntimeBreakdownRow[],
  machines: Machine[],
  noMachineLabel: string,
): DowntimeDimensionRow[] {
  const NO_MACHINE_KEY = "__none__";
  const byMachine = new Map<string, Map<string, number>>();
  for (const row of rows) {
    const key = row.equipment_id ?? NO_MACHINE_KEY;
    const reasons = byMachine.get(key) ?? new Map<string, number>();
    reasons.set(row.reason, (reasons.get(row.reason) ?? 0) + row.minutes);
    byMachine.set(key, reasons);
  }
  return [...byMachine.entries()]
    .map(([key, reasons]) => {
      const machine = machines.find((m) => m.id === key);
      const label = key === NO_MACHINE_KEY ? noMachineLabel : machine ? `${machine.code} — ${machine.name}` : key;
      return topDowntimeReasonRow(key, label, reasons);
    })
    .sort((a, b) => b.totalMinutes - a.totalMinutes);
}

interface PackagingAccuracyRow {
  productId: string;
  label: string;
  expectedPackets: number | null;
  countedPackets: number;
  packetVariance: number | null;
  packetVarianceRatio: number | null;
  withinTolerance: boolean | null;
}

/**
 * Écart de conditionnement, plant-wide by product, worst mismatch first. Only
 * products with an expected-packet figure are shown — without a net weight
 * there is nothing to compare the count against (see PackagingVariance.missing).
 */
function buildPackagingAccuracyRows(rows: ProductPackagingVariance[], products: Product[]): PackagingAccuracyRow[] {
  return rows
    .filter((row) => row.expected_packets !== null)
    .map((row) => ({
      productId: row.product_id,
      label: products.find((p) => p.id === row.product_id)?.name ?? row.product_id,
      expectedPackets: row.expected_packets,
      countedPackets: row.counted_packets,
      packetVariance: row.packet_variance,
      packetVarianceRatio: row.packet_variance_ratio,
      withinTolerance: row.within_tolerance,
    }))
    .sort((a, b) => Math.abs(b.packetVarianceRatio ?? 0) - Math.abs(a.packetVarianceRatio ?? 0));
}

interface TeamLeaderboardRow {
  team: string;
  reportCount: number;
  yieldPercent: number | null;
  wastePercent: number | null;
  downtimePercent: number | null;
}

/**
 * Same team-performance rows the trend chart and semoule-waste chart already
 * fetch, folded per team across the whole selected range instead of per
 * period or by waste category alone — the ranking the plant floor actually
 * asks for: whose yield, not just whose déchet. Best yield first.
 */
function buildTeamLeaderboard(
  rows: TeamPerformanceRow[],
  semolinaProductId: string | null | undefined,
  products: Parameters<typeof convertQuantity>[3],
  uoms: Parameters<typeof convertQuantity>[4],
  noTeamLabel: string,
): TeamLeaderboardRow[] {
  const byTeam = new Map<
    string,
    {
      team: string;
      reportCount: number;
      produced: number;
      materialInput: number;
      production: number;
      downtime: number;
      waste: { product_id: string; quantity: number }[];
    }
  >();
  for (const row of rows) {
    const team = row.team ?? noTeamLabel;
    const entry = byTeam.get(team) ?? {
      team,
      reportCount: 0,
      produced: 0,
      materialInput: 0,
      production: 0,
      downtime: 0,
      waste: [],
    };
    entry.reportCount += row.report_count;
    entry.produced += row.produced_quantity;
    entry.materialInput += row.material_input_quantity;
    entry.production += row.production_minutes;
    entry.downtime += row.downtime_minutes;
    entry.waste.push(...row.waste_by_product);
    byTeam.set(team, entry);
  }
  return [...byTeam.values()]
    .map((entry): TeamLeaderboardRow => {
      const comparableWaste = semolinaProductId
        ? entry.waste.reduce((total, item) => {
            const converted = convertQuantity(item.quantity, item.product_id, semolinaProductId, products, uoms);
            return converted === null ? total : total + converted;
          }, 0)
        : null;
      return {
        team: entry.team,
        reportCount: entry.reportCount,
        yieldPercent: entry.materialInput > 0 ? Math.round((entry.produced / entry.materialInput) * 1000) / 10 : null,
        wastePercent:
          comparableWaste !== null && entry.materialInput > 0
            ? Math.round((comparableWaste / entry.materialInput) * 1000) / 10
            : null,
        downtimePercent:
          entry.production + entry.downtime > 0
            ? Math.round((entry.downtime / (entry.production + entry.downtime)) * 1000) / 10
            : null,
      };
    })
    .sort((a, b) => (b.yieldPercent ?? -Infinity) - (a.yieldPercent ?? -Infinity));
}

interface RegrindSummary {
  finishedCount: number;
  pendingCount: number;
  inputTotal: number;
  outputTotal: number;
  lossTotal: number;
  yieldRatio: number | null;
}

/**
 * listRegrindBatches has no date filter, so this buckets by created_at
 * against the dashboard's own range -- same string-compare the rest of the
 * cockpit uses ("YYYY-MM-DD" sorts lexicographically). Only finished batches
 * (actual_output_quantity set) have a real yield; a batch still new or
 * assigned has not been weighed back in yet.
 */
function buildRegrindSummary(batches: RegrindBatchSummary[], range: { from: string; to: string }): RegrindSummary {
  const inRange = batches.filter((b) => {
    const day = b.created_at.slice(0, 10);
    return day >= range.from && day <= range.to;
  });
  const finished = inRange.filter((b) => b.actual_output_quantity !== null);
  const inputTotal = sum(finished.map((b) => b.input_quantity_total));
  const outputTotal = sum(finished.map((b) => b.actual_output_quantity as number));
  const lossTotal = sum(finished.map((b) => b.loss_quantity ?? 0));
  return {
    finishedCount: finished.length,
    pendingCount: inRange.length - finished.length,
    inputTotal,
    outputTotal,
    lossTotal,
    yieldRatio: inputTotal > 0 ? outputTotal / inputTotal : null,
  };
}

interface NearExpiryRow {
  lotId: string;
  productLabel: string;
  lotNumber: string;
  expiryDate: string;
  daysRemaining: number;
}

/**
 * Active lots within `warningDays` of their DLC, soonest first. A negative
 * daysRemaining means the lot is already past its date and still marked
 * active -- worth surfacing rather than silently excluding, since that is
 * itself a data-hygiene problem (it should have been dispositioned).
 */
function buildNearExpiryRows(lots: Lot[], products: Product[], warningDays: number): NearExpiryRow[] {
  const todayMs = new Date(todayIso()).getTime();
  return lots
    .filter((lot): lot is Lot & { expiry_date: string } => lot.status === "active" && lot.expiry_date !== null)
    .map((lot) => ({
      lotId: lot.id,
      productLabel: products.find((p) => p.id === lot.product_id)?.name ?? lot.product_id,
      lotNumber: lot.lot_number,
      expiryDate: lot.expiry_date,
      daysRemaining: Math.round((new Date(lot.expiry_date).getTime() - todayMs) / 86_400_000),
    }))
    .filter((row) => row.daysRemaining <= warningDays)
    .sort((a, b) => a.daysRemaining - b.daysRemaining);
}

// The dashboard's other quantities (tonnes produced, tonnes of semoule) run
// into the thousands, so Math.round reads fine there. A team's net semoule
// waste is routinely a small fraction of that unit and Math.round would
// flatten every real value to the same "0" — this keeps two decimal places
// instead of rounding them away.
function formatQty(amount: number): string {
  return new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 2 }).format(amount);
}

// The per-stage waste bars are always raw kilos (see
// TeamPerformanceRow.daily_waste_by_category) — deliberately never each
// stage's own item unit, so stages stay comparable when stacked together
// (a finished-goods item logged in kg must not out-size bulk semoule logged
// in tonnes just because the raw numbers happen to look similar). A spill
// under a tonne is easier to read in kg, matching how the plant itself talks
// about a small spill; at or above a tonne it switches to tonnes.
function formatWasteStageQuantity(kg: number): string {
  return Math.abs(kg) < 1000 ? formatQuantity(kg, "kg") : formatQuantity(kg / 1000, "t");
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

interface OrderRatio {
  of_id: string;
  reference: string;
  ratio: number;
}

/**
 * Which single active order contributes most to the plant-wide waste ratio.
 *
 * The alert fires on the aggregate (the KPI the plant tracks), but a
 * plant-wide percentage gives nobody a place to start looking — this is
 * where to send them instead. Same conversion as the aggregate above, applied
 * per order rather than once across all of them.
 */
function worstWasteOrder(
  consolidations: OfConsolidation[],
  products: Parameters<typeof convertQuantity>[3],
  uoms: Parameters<typeof convertQuantity>[4],
): OrderRatio | null {
  let worst: OrderRatio | null = null;
  for (const c of consolidations) {
    // Largest quality poured on this order, same reasoning as the plant-wide
    // ratio above — an order that mixed qualities (semolina_product_id null)
    // still has a usable anchor unit, it just isn't a single named product.
    const semolinaProductId = c.raw_material.semolina_by_product.reduce<
      { product_id: string; quantity: number } | null
    >((best, entry) => (best === null || entry.quantity > best.quantity ? entry : best), null)?.product_id;
    if (!semolinaProductId || c.raw_material.semolina_quantity <= 0) continue;
    const comparableWaste = c.waste.by_product.reduce((total, entry) => {
      const converted = convertQuantity(entry.quantity, entry.product_id, semolinaProductId, products, uoms);
      return converted === null ? total : total + converted;
    }, 0);
    const ratio = comparableWaste / c.raw_material.semolina_quantity;
    if (worst === null || ratio > worst.ratio) {
      worst = { of_id: c.of_id, reference: c.reference, ratio };
    }
  }
  return worst;
}

/** Same idea as worstWasteOrder, for downtime instead of déchet. */
function worstDowntimeOrder(consolidations: OfConsolidation[]): OrderRatio | null {
  let worst: OrderRatio | null = null;
  for (const c of consolidations) {
    const total = c.time.production_minutes + c.time.downtime_minutes;
    if (total <= 0) continue;
    const ratio = c.time.downtime_minutes / total;
    if (worst === null || ratio > worst.ratio) {
      worst = { of_id: c.of_id, reference: c.reference, ratio };
    }
  }
  return worst;
}

function buildAlerts({
  pendingCount,
  lowStock,
  wasteRatio,
  worstWaste,
  downtimeRatio,
  worstDowntime,
  quarantined,
  outOfTolerance,
  urgentExpiryCount,
  soonestExpiry,
}: {
  pendingCount: number;
  lowStock: string[];
  wasteRatio: number | null;
  worstWaste: OrderRatio | null;
  downtimeRatio: number | null;
  worstDowntime: OrderRatio | null;
  quarantined: number;
  outOfTolerance: string[];
  urgentExpiryCount: number;
  soonestExpiry: NearExpiryRow | null;
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
      // Named when one order stands out, not just the plant-wide number --
      // an alert that only says "13%" gives nobody a place to start.
      detail: worstWaste
        ? `${(wasteRatio * 100).toFixed(1)}% — ${worstWaste.reference}`
        : `${(wasteRatio * 100).toFixed(1)}%`,
      to: worstWaste ? `/production/work-orders/${worstWaste.of_id}` : "/production?tab=daily-reports",
    });
  }
  if (downtimeRatio !== null && downtimeRatio > DOWNTIME_RATIO_ALERT) {
    alerts.push({
      code: "excessive-downtime",
      tone: "destructive",
      titleKey: "production.dashboard.alert.excessiveDowntime",
      detail: worstDowntime
        ? `${(downtimeRatio * 100).toFixed(1)}% — ${worstDowntime.reference}`
        : `${(downtimeRatio * 100).toFixed(1)}%`,
      to: worstDowntime ? `/production/work-orders/${worstDowntime.of_id}` : "/production?tab=daily-reports",
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
  if (outOfTolerance.length > 0) {
    alerts.push({
      code: "packaging-variance",
      tone: "warning",
      titleKey: "production.dashboard.alert.packagingVariance",
      detail: outOfTolerance.slice(0, 4).join(", "),
      to: "#packaging-accuracy",
    });
  }
  if (urgentExpiryCount > 0) {
    alerts.push({
      code: "near-expiry",
      tone: "destructive",
      titleKey: "production.dashboard.alert.nearExpiry",
      detail: soonestExpiry
        ? `${urgentExpiryCount} — ${soonestExpiry.productLabel} (${soonestExpiry.lotNumber})`
        : String(urgentExpiryCount),
      to: "/products?tab=lots-serials",
    });
  }
  return alerts;
}

function Ratio({
  icon,
  label,
  ratio,
  goodIsHigh,
  noDataLabel,
}: {
  icon: React.ReactNode;
  label: string;
  ratio: number | null;
  goodIsHigh: boolean;
  /** Overrides the generic "nothing measured" text when a metric's own null
   * reason needs saying — e.g. conformity's scope is active OFs only, so a
   * closed OF's quality checks don't make it read as data gone missing. */
  noDataLabel?: string;
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
        <p className="text-sm text-muted-foreground">{noDataLabel ?? t("production.dashboard.health.noData")}</p>
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
