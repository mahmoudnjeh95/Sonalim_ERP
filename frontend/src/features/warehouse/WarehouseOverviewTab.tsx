import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  CalendarClock,
  ClipboardList,
  Coins,
  Hourglass,
  PackageX,
  ShieldAlert,
  Timer,
  TriangleAlert,
} from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useAuth } from "../../lib/auth";
import { currentLocale, useI18n } from "../../lib/i18n";
import { Badge } from "../../components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHeader, TableRow, ResizableTableHead } from "../../components/ui/table";
import { StatCard } from "../../components/patterns/StatCard";
import { UnitBreakdownStat } from "../../components/patterns/UnitBreakdownStat";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { DateRangeFilter } from "../../components/patterns/DateRangeFilter";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { CategoryBadge } from "../../components/patterns/StatusBadge";
import { AppLoader } from "../../components/patterns/AppLoader";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { useMoveTypeLabels } from "../../lib/stockMoveTypes";
import { listUserDirectory, userDisplayName } from "../../lib/usersApi";
import { fill } from "../analytics/manufacturing/format";
import { CATEGORY_ORDER, useCatalogLabels, useProductCatalog, type CatalogProduct } from "../products/catalog";
import type { ProductCategory } from "../production/api";
import {
  getWarehouseOverview,
  listLocations,
  listUoms,
  type CoverageStatus,
  type OverviewCorrection,
  type OverviewExpiringLot,
  type OverviewProductRow,
} from "./api";

// Same two hues the other warehouse charts use: blue for what came in, green
// for what went out. Fixed per series, never cycled.
const CHART_COLORS = {
  inbound: "hsl(217 91% 45%)",
  outbound: "hsl(142 71% 40%)",
};

const PERIOD_PRESETS = [7, 30, 90] as const;
type PeriodPreset = (typeof PERIOD_PRESETS)[number];
type ProductView = "all" | "atRisk" | "dormant" | "blocked";
type CategoryFilter = "all" | "unclassified" | ProductCategory;

const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;
const UOMS_QUERY_KEY = ["core", "uoms"] as const;
const USER_DIRECTORY_QUERY_KEY = ["core", "users", "directory"] as const;

const COVERAGE_VARIANT: Record<CoverageStatus, "destructive" | "warning" | "success" | "outline"> = {
  out: "destructive",
  critical: "destructive",
  warning: "warning",
  ok: "success",
  idle: "outline",
};
const COVERAGE_RANK: Record<CoverageStatus, number> = { out: 0, critical: 1, warning: 2, ok: 3, idle: 4 };

function isoDate(date: Date) {
  return date.toISOString().slice(0, 10);
}

function daysAgo(days: number) {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return isoDate(date);
}

function formatQty(amount: number) {
  return new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 1 }).format(amount);
}

function formatMoney(amount: number) {
  return new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 0 }).format(amount);
}

function formatDate(iso: string) {
  return new Intl.DateTimeFormat(currentLocale(), { day: "numeric", month: "short", year: "numeric" }).format(new Date(iso));
}

function formatDateTime(iso: string) {
  return new Intl.DateTimeFormat(currentLocale(), { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

function shortDay(iso: string) {
  return new Intl.DateTimeFormat(currentLocale(), { day: "numeric", month: "short" }).format(new Date(`${iso}T00:00:00`));
}

type ProductRow = OverviewProductRow & { category: CatalogProduct["category"]; packaging_kind: CatalogProduct["packaging_kind"] };

export function WarehouseOverviewTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const catalogLabels = useCatalogLabels();
  const moveTypeLabels = useMoveTypeLabels();

  const [preset, setPreset] = useState<PeriodPreset>(30);
  const [range, setRange] = useState<{ from: string; to: string } | null>(null);
  const defaultRange = useMemo(() => ({ from: daysAgo(preset - 1), to: daysAgo(0) }), [preset]);
  const period = range ?? defaultRange;

  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("all");
  const [productView, setProductView] = useState<ProductView>("atRisk");
  const [chartUom, setChartUom] = useState<string | null>(null);

  const { data: overview, isLoading, isError } = useQuery({
    queryKey: ["warehouse", "analytics", "overview", period.from, period.to],
    queryFn: () => getWarehouseOverview(token, { date_from: period.from, date_to: period.to }),
  });
  const { catalog } = useProductCatalog();
  const { data: uoms = [] } = useQuery({ queryKey: UOMS_QUERY_KEY, queryFn: () => listUoms(token) });
  const { data: locations = [] } = useQuery({ queryKey: LOCATIONS_QUERY_KEY, queryFn: () => listLocations(token) });
  // Best-effort: a role that cannot read the user directory just sees the
  // actor id's tail in the corrections table, not an error.
  const { data: users = [] } = useQuery({ queryKey: USER_DIRECTORY_QUERY_KEY, queryFn: () => listUserDirectory(token), retry: false });

  const uomLabel = (uomId: string) => {
    const uom = uoms.find((u) => u.id === uomId);
    return uom ? uom.symbol || uom.code : uomId;
  };
  const locationName = (id: string) => locations.find((l) => l.id === id)?.name ?? "—";
  const actorName = (actorId: string | null) => {
    if (!actorId) return "—";
    const user = users.find((u) => u.id === actorId);
    return user ? userDisplayName(user) : actorId.slice(-6);
  };
  const catalogById = useMemo(() => new Map(catalog.map((p) => [p.id, p])), [catalog]);
  const productName = (productId: string) => catalogById.get(productId)?.name ?? productId;

  const rows: ProductRow[] = useMemo(() => {
    if (!overview) return [];
    return overview.products
      .map((row) => {
        const product = catalogById.get(row.product_id);
        return { ...row, category: product?.category ?? null, packaging_kind: product?.packaging_kind ?? null };
      })
      .filter((row) => {
        if (categoryFilter === "all") return true;
        if (categoryFilter === "unclassified") return row.category === null;
        return row.category === categoryFilter;
      });
  }, [overview, catalogById, categoryFilter]);

  const viewRows = rows.filter((row) => {
    switch (productView) {
      case "atRisk":
        return (
          row.coverage_status === "out" ||
          row.coverage_status === "critical" ||
          row.coverage_status === "warning" ||
          (row.stock_alert_threshold !== null && row.on_hand < row.stock_alert_threshold) ||
          row.on_hand < 0
        );
      case "dormant":
        return row.is_dormant;
      case "blocked":
        return row.blocked_on_hand > 0;
      default:
        return true;
    }
  });

  // One chart per unit would be the honest default, but the plant meters
  // nearly everything in kg or pièces; a unit toggle keeps the reader on one
  // chart and never blends the two.
  const chartUoms = useMemo(() => {
    if (!overview) return [];
    const totals = new Map<string, number>();
    for (const point of overview.daily) totals.set(point.uom_id, (totals.get(point.uom_id) ?? 0) + point.inbound + point.outbound);
    return Array.from(totals.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([uomId]) => uomId);
  }, [overview]);
  const activeChartUom = chartUom && chartUoms.includes(chartUom) ? chartUom : chartUoms[0] ?? null;
  const chartData = useMemo(() => {
    if (!overview || !activeChartUom) return [];
    // Every day of the period, so a silent day shows as a gap rather than vanishing.
    const byDay = new Map(overview.daily.filter((p) => p.uom_id === activeChartUom).map((p) => [p.day, p]));
    const points: { day: string; label: string; inbound: number; outbound: number }[] = [];
    const cursor = new Date(`${overview.period.from}T00:00:00`);
    const end = new Date(`${overview.period.to}T00:00:00`);
    while (cursor <= end) {
      const day = isoDate(cursor);
      const point = byDay.get(day);
      points.push({ day, label: shortDay(day), inbound: point?.inbound ?? 0, outbound: point?.outbound ?? 0 });
      cursor.setDate(cursor.getDate() + 1);
    }
    return points;
  }, [overview, activeChartUom]);

  const coverageLabel: Record<CoverageStatus, string> = {
    out: t("warehouse.overview.coverage.out"),
    critical: t("warehouse.overview.coverage.critical"),
    warning: t("warehouse.overview.coverage.warning"),
    ok: t("warehouse.overview.coverage.ok"),
    idle: t("warehouse.overview.coverage.idle"),
  };

  const productColumns: ColumnDef<ProductRow>[] = [
    {
      key: "product",
      header: t("warehouse.overview.column.product"),
      defaultWidth: 220,
      alwaysVisible: true,
      cell: (row) => (
        <div className="min-w-0">
          <p className="truncate font-medium">{row.name}</p>
          <p className="truncate text-xs text-muted-foreground">{row.sku}</p>
        </div>
      ),
      sortValue: (row) => row.name,
    },
    {
      key: "category",
      header: t("warehouse.overview.column.category"),
      defaultWidth: 220,
      cell: (row) =>
        row.category ? (
          <span className="inline-flex flex-wrap gap-1">
            <CategoryBadge category={row.category} />
            {row.packaging_kind && <Badge variant="outline">{catalogLabels.packagingKind[row.packaging_kind]}</Badge>}
          </span>
        ) : (
          <Badge variant="warning">{catalogLabels.unclassified}</Badge>
        ),
      sortValue: (row) => row.category ?? "~",
    },
    {
      key: "onHand",
      header: t("warehouse.overview.column.onHand"),
      defaultWidth: 130,
      cell: (row) => (
        <span className={row.on_hand < 0 ? "tabular-nums font-medium text-destructive" : "tabular-nums"}>
          {formatQty(row.on_hand)} <span className="text-xs text-muted-foreground">{uomLabel(row.uom_id)}</span>
        </span>
      ),
      sortValue: (row) => row.on_hand,
    },
    {
      key: "threshold",
      header: t("warehouse.overview.column.threshold"),
      defaultWidth: 120,
      cell: (row) =>
        row.stock_alert_threshold === null ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          <span className={row.on_hand < row.stock_alert_threshold ? "tabular-nums font-medium text-warning" : "tabular-nums text-muted-foreground"}>
            {formatQty(row.stock_alert_threshold)}
          </span>
        ),
      sortValue: (row) => row.stock_alert_threshold ?? -1,
    },
    {
      key: "dailyUse",
      header: (
        <span className="inline-flex items-center gap-1">
          {t("warehouse.overview.column.dailyUse")}
          <HelpTooltip text={fill(t("warehouse.overview.help.dailyUse"), { days: String(overview?.period.consumption_window_days ?? 30) })} />
        </span>
      ),
      defaultWidth: 130,
      cell: (row) => <span className="tabular-nums text-muted-foreground">{row.avg_daily_consumption > 0 ? formatQty(row.avg_daily_consumption) : "—"}</span>,
      sortValue: (row) => row.avg_daily_consumption,
    },
    {
      key: "cover",
      header: (
        <span className="inline-flex items-center gap-1">
          {t("warehouse.overview.column.daysOfCover")}
          <HelpTooltip text={t("warehouse.overview.help.daysOfCover")} />
        </span>
      ),
      defaultWidth: 170,
      cell: (row) => (
        <span className="inline-flex items-center gap-2">
          <Badge variant={COVERAGE_VARIANT[row.coverage_status]}>{coverageLabel[row.coverage_status]}</Badge>
          {row.days_of_cover !== null && row.coverage_status !== "out" && (
            <span className="tabular-nums text-muted-foreground">{fill(t("warehouse.overview.days"), { days: formatQty(row.days_of_cover) })}</span>
          )}
        </span>
      ),
      sortValue: (row) => COVERAGE_RANK[row.coverage_status] * 1_000_000 + (row.days_of_cover ?? 0),
    },
    {
      key: "consumed",
      header: t("warehouse.overview.column.consumedInPeriod"),
      defaultWidth: 140,
      cell: (row) => <span className="tabular-nums text-muted-foreground">{row.period_consumed > 0 ? formatQty(row.period_consumed) : "—"}</span>,
      sortValue: (row) => row.period_consumed,
    },
    {
      key: "inbound",
      header: t("warehouse.overview.column.inboundInPeriod"),
      defaultWidth: 130,
      cell: (row) => <span className="tabular-nums text-muted-foreground">{row.period_inbound > 0 ? formatQty(row.period_inbound) : "—"}</span>,
      sortValue: (row) => row.period_inbound,
    },
    {
      key: "corrections",
      header: t("warehouse.overview.column.corrections"),
      defaultWidth: 130,
      cell: (row) =>
        row.period_corrections_count === 0 ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          <span className={`tabular-nums ${row.period_corrections < 0 ? "text-destructive" : "text-success"}`}>
            {row.period_corrections > 0 ? "+" : ""}
            {formatQty(row.period_corrections)}
            <span className="ml-1 text-xs text-muted-foreground">({row.period_corrections_count})</span>
          </span>
        ),
      sortValue: (row) => Math.abs(row.period_corrections),
    },
    {
      key: "blocked",
      header: t("warehouse.overview.column.blocked"),
      defaultWidth: 120,
      cell: (row) =>
        row.blocked_on_hand > 0 ? <span className="tabular-nums font-medium text-warning">{formatQty(row.blocked_on_hand)}</span> : <span className="text-muted-foreground">—</span>,
      sortValue: (row) => row.blocked_on_hand,
    },
    {
      key: "lastMove",
      header: t("warehouse.overview.column.lastMove"),
      defaultWidth: 150,
      cell: (row) =>
        row.last_move_at ? (
          <span className={row.is_dormant ? "text-warning" : "text-muted-foreground"}>
            {row.idle_days === 0
              ? t("warehouse.overview.today")
              : row.idle_days === 1
                ? t("warehouse.overview.yesterday")
                : fill(t("warehouse.overview.daysAgo"), { days: String(row.idle_days ?? 0) })}
          </span>
        ) : (
          <span className="text-warning">{t("warehouse.overview.neverMoved")}</span>
        ),
      sortValue: (row) => row.idle_days ?? Number.MAX_SAFE_INTEGER,
    },
    {
      key: "value",
      header: (
        <span className="inline-flex items-center gap-1">
          {t("warehouse.overview.column.value")}
          <HelpTooltip text={t("warehouse.overview.help.value")} />
        </span>
      ),
      defaultWidth: 140,
      cell: (row) => (row.value === null ? <span className="text-muted-foreground">—</span> : <span className="tabular-nums">{formatMoney(row.value)}</span>),
      sortValue: (row) => row.value ?? -1,
    },
  ];
  const productTable = useTableColumns("warehouse.overview.products", productColumns);
  const sortedProductRows = productTable.sortRows(
    [...viewRows].sort((a, b) => COVERAGE_RANK[a.coverage_status] - COVERAGE_RANK[b.coverage_status] || (a.days_of_cover ?? Infinity) - (b.days_of_cover ?? Infinity)),
  );

  const correctionColumns: ColumnDef<OverviewCorrection>[] = [
    { key: "when", header: t("warehouse.overview.column.when"), defaultWidth: 140, cell: (c) => <span className="text-muted-foreground">{formatDateTime(c.created_at)}</span>, sortValue: (c) => c.created_at },
    { key: "product", header: t("warehouse.overview.column.product"), defaultWidth: 200, cell: (c) => <span className="font-medium">{productName(c.product_id)}</span>, sortValue: (c) => productName(c.product_id) },
    { key: "location", header: t("warehouse.overview.column.location"), defaultWidth: 150, cell: (c) => <span className="text-muted-foreground">{locationName(c.location_id)}</span> },
    {
      key: "delta",
      header: t("warehouse.overview.column.delta"),
      defaultWidth: 120,
      cell: (c) => (
        <span className={`tabular-nums ${c.quantity < 0 ? "text-destructive" : "text-success"}`}>
          {c.quantity > 0 ? "+" : ""}
          {formatQty(c.quantity)} <span className="text-xs text-muted-foreground">{uomLabel(catalogById.get(c.product_id)?.uom_id ?? "")}</span>
        </span>
      ),
      sortValue: (c) => Math.abs(c.quantity),
    },
    { key: "type", header: t("warehouse.overview.column.type"), defaultWidth: 140, cell: (c) => <Badge variant={c.move_type === "admin_correction" ? "destructive" : "accent"}>{moveTypeLabels[c.move_type]}</Badge> },
    { key: "reason", header: t("warehouse.overview.column.reason"), defaultWidth: 220, cell: (c) => <span className="text-muted-foreground">{c.reason ?? "—"}</span> },
    { key: "who", header: t("warehouse.overview.column.who"), defaultWidth: 140, cell: (c) => <span className="text-muted-foreground">{actorName(c.actor_id)}</span> },
  ];
  const correctionTable = useTableColumns("warehouse.overview.corrections", correctionColumns);

  const lotColumns: ColumnDef<OverviewExpiringLot>[] = [
    { key: "lot", header: t("warehouse.overview.column.lot"), defaultWidth: 140, cell: (l) => <span className="font-medium">{l.lot_number}</span>, sortValue: (l) => l.lot_number },
    { key: "product", header: t("warehouse.overview.column.product"), defaultWidth: 200, cell: (l) => productName(l.product_id), sortValue: (l) => productName(l.product_id) },
    { key: "expiry", header: t("warehouse.overview.column.expiry"), defaultWidth: 140, cell: (l) => <span className="text-muted-foreground">{formatDate(l.expiry_date)}</span>, sortValue: (l) => l.expiry_date },
    {
      key: "daysLeft",
      header: t("warehouse.overview.column.daysLeft"),
      defaultWidth: 150,
      cell: (l) =>
        l.days_until_expiry < 0 ? (
          <Badge variant="destructive">{fill(t("warehouse.overview.lots.expiredSince"), { days: String(-l.days_until_expiry) })}</Badge>
        ) : (
          <Badge variant={l.days_until_expiry <= 7 ? "warning" : "outline"}>{fill(t("warehouse.overview.days"), { days: String(l.days_until_expiry) })}</Badge>
        ),
      sortValue: (l) => l.days_until_expiry,
    },
    {
      key: "quantity",
      header: t("warehouse.overview.column.onHand"),
      defaultWidth: 120,
      cell: (l) => (
        <span className="tabular-nums text-muted-foreground">
          {formatQty(l.quantity_on_hand)} {uomLabel(catalogById.get(l.product_id)?.uom_id ?? "")}
        </span>
      ),
      sortValue: (l) => l.quantity_on_hand,
    },
  ];
  const lotTable = useTableColumns("warehouse.overview.lots", lotColumns);

  if (isLoading || !overview) {
    if (isError) {
      return <p className="text-sm text-destructive">{t("warehouse.overview.error")}</p>;
    }
    return <AppLoader />;
  }

  const { summary } = overview;
  const inboundBreakdown = overview.flow_by_uom.filter((f) => f.inbound > 0).map((f) => ({ unit: uomLabel(f.uom_id), value: Math.round(f.inbound * 10) / 10 }));
  const outboundBreakdown = overview.flow_by_uom.filter((f) => f.outbound > 0).map((f) => ({ unit: uomLabel(f.uom_id), value: Math.round(f.outbound * 10) / 10 }));
  const expiringLots = overview.expiring_lots.filter((lot) => categoryFilter === "all" || rows.some((r) => r.product_id === lot.product_id));
  const corrections = overview.corrections.filter((c) => categoryFilter === "all" || rows.some((r) => r.product_id === c.product_id));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <FilterTabs
          value={String(range ? 0 : preset)}
          onChange={(value) => {
            setPreset(Number(value) as PeriodPreset);
            setRange(null);
          }}
          options={PERIOD_PRESETS.map((days) => ({ value: String(days), label: fill(t("analytics.period.days"), { days: String(days) }) }))}
        />
        <DateRangeFilter from={period.from} to={period.to} onChange={setRange} onReset={() => setRange(null)} isDefault={range === null} />
        <FilterTabs
          value={categoryFilter}
          onChange={setCategoryFilter}
          options={[
            { value: "all", label: t("common.all") },
            ...CATEGORY_ORDER.map((category) => ({ value: category, label: catalogLabels.category[category] })),
            { value: "unclassified", label: catalogLabels.unclassified },
          ]}
        />
      </div>

      <section className="space-y-2">
        <h2 className="text-sm font-medium text-muted-foreground">{t("warehouse.overview.section.today")}</h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard label={t("warehouse.overview.stat.stockValue")} value={summary.stock_value} icon={<Coins className="h-5 w-5" />} unit="F CFA" accent="primary" />
          <StatCard
            label={t("warehouse.overview.stat.belowThreshold")}
            value={summary.below_threshold + summary.out_of_stock}
            icon={<TriangleAlert className="h-5 w-5" />}
            accent={summary.below_threshold + summary.out_of_stock > 0 ? "warning" : "success"}
          />
          <StatCard
            label={t("warehouse.overview.stat.critical")}
            value={summary.coverage_critical}
            icon={<Timer className="h-5 w-5" />}
            accent={summary.coverage_critical > 0 ? "destructive" : "success"}
          />
          <StatCard label={t("warehouse.overview.stat.dormant")} value={summary.dormant_count} icon={<Hourglass className="h-5 w-5" />} accent={summary.dormant_count > 0 ? "accent" : "success"} />
          <StatCard label={t("warehouse.overview.stat.blocked")} value={summary.blocked_products} icon={<ShieldAlert className="h-5 w-5" />} accent={summary.blocked_products > 0 ? "warning" : "success"} />
          <StatCard
            label={t("warehouse.overview.stat.negative")}
            value={summary.negative_stock}
            icon={<PackageX className="h-5 w-5" />}
            accent={summary.negative_stock > 0 ? "destructive" : "success"}
          />
          <StatCard
            label={t("warehouse.overview.stat.lotsExpiring")}
            value={summary.lots_expiring_soon + summary.lots_expired}
            icon={<CalendarClock className="h-5 w-5" />}
            accent={summary.lots_expired > 0 ? "destructive" : summary.lots_expiring_soon > 0 ? "warning" : "success"}
          />
          <StatCard label={t("warehouse.overview.stat.productsInStock")} value={summary.products_in_stock} icon={<ClipboardList className="h-5 w-5" />} accent="primary" />
        </div>
        {summary.unvalued_products > 0 && (
          <p className="text-xs text-muted-foreground">{fill(t("warehouse.overview.unvaluedHint"), { count: String(summary.unvalued_products) })}</p>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-medium text-muted-foreground">
          {fill(t("warehouse.overview.section.period"), { from: formatDate(overview.period.from), to: formatDate(overview.period.to) })}
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <UnitBreakdownStat label={t("warehouse.overview.stat.inbound")} icon={<ArrowDownToLine className="h-5 w-5" />} accent="primary" breakdown={inboundBreakdown} />
          <UnitBreakdownStat label={t("warehouse.overview.stat.outbound")} icon={<ArrowUpFromLine className="h-5 w-5" />} accent="success" breakdown={outboundBreakdown} />
          <StatCard label={t("warehouse.overview.stat.movements")} value={summary.movements_count} icon={<ClipboardList className="h-5 w-5" />} accent="primary" />
          <StatCard
            label={t("warehouse.overview.stat.corrections")}
            value={summary.corrections_count}
            icon={<TriangleAlert className="h-5 w-5" />}
            accent={summary.corrections_count > 0 ? "warning" : "success"}
          />
        </div>
      </section>

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>{t("warehouse.overview.chart.title")}</CardTitle>
            <CardDescription>{t("warehouse.overview.chart.description")}</CardDescription>
          </div>
          {chartUoms.length > 1 && (
            <FilterTabs value={activeChartUom ?? ""} onChange={setChartUom} options={chartUoms.map((uomId) => ({ value: uomId, label: uomLabel(uomId) }))} />
          )}
        </CardHeader>
        <CardContent>
          {chartData.length === 0 ? (
            <EmptyState icon={<ClipboardList className="h-5 w-5" />} title={t("warehouse.overview.chart.empty.title")} description={t("warehouse.overview.chart.empty.description")} />
          ) : (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barGap={2}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(214 20% 90%)" />
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} minTickGap={16} />
                  <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} width={56} tickFormatter={(value) => formatQty(Number(value))} />
                  <Tooltip
                    formatter={(value) => `${formatQty(Number(value))} ${activeChartUom ? uomLabel(activeChartUom) : ""}`}
                    contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }}
                  />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="inbound" name={t("warehouse.overview.chart.inbound")} fill={CHART_COLORS.inbound} radius={[4, 4, 0, 0]} />
                  <Bar dataKey="outbound" name={t("warehouse.overview.chart.outbound")} fill={CHART_COLORS.outbound} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>{t("warehouse.overview.products.title")}</CardTitle>
            <CardDescription>
              {fill(t("warehouse.overview.products.description"), {
                window: String(overview.period.consumption_window_days),
                dormant: String(overview.period.dormant_after_days),
              })}
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <FilterTabs
              value={productView}
              onChange={setProductView}
              options={[
                { value: "atRisk", label: t("warehouse.overview.products.view.atRisk") },
                { value: "dormant", label: t("warehouse.overview.products.view.dormant") },
                { value: "blocked", label: t("warehouse.overview.products.view.blocked") },
                { value: "all", label: t("common.all") },
              ]}
            />
            <ColumnVisibilityMenu columns={productColumns} isVisible={productTable.isVisible} onToggle={productTable.toggleVisible} onReset={productTable.resetAll} />
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <Table colWidths={productTable.colWidths}>
            <TableHeader>
              <TableRow>
                {productTable.visibleColumns.map((column) => (
                  <ResizableTableHead
                    key={column.key}
                    width={productTable.getWidth(column.key)}
                    onResize={(width) => productTable.setWidth(column.key, width)}
                    sortDirection={productTable.sortDirectionFor(column.key)}
                    onSort={column.sortValue ? () => productTable.toggleSort(column.key) : undefined}
                  >
                    {column.header}
                  </ResizableTableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedProductRows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={productTable.visibleColumns.length} className="p-0">
                    <EmptyState icon={<ClipboardList className="h-5 w-5" />} title={t("warehouse.overview.products.empty.title")} description={t("warehouse.overview.products.empty.description")} />
                  </TableCell>
                </TableRow>
              )}
              {sortedProductRows.map((row) => (
                <TableRow key={row.product_id}>
                  {productTable.visibleColumns.map((column) => (
                    <TableCell key={column.key}>{column.cell(row)}</TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <div className="grid gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-1.5">
              {t("warehouse.overview.corrections.title")}
              <HelpTooltip text={t("warehouse.overview.help.corrections")} />
            </CardTitle>
            <CardDescription>{t("warehouse.overview.corrections.description")}</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <Table colWidths={correctionTable.colWidths}>
              <TableHeader>
                <TableRow>
                  {correctionTable.visibleColumns.map((column) => (
                    <ResizableTableHead
                      key={column.key}
                      width={correctionTable.getWidth(column.key)}
                      onResize={(width) => correctionTable.setWidth(column.key, width)}
                      sortDirection={correctionTable.sortDirectionFor(column.key)}
                      onSort={column.sortValue ? () => correctionTable.toggleSort(column.key) : undefined}
                    >
                      {column.header}
                    </ResizableTableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {corrections.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={correctionTable.visibleColumns.length} className="p-0">
                      <EmptyState icon={<ClipboardList className="h-5 w-5" />} title={t("warehouse.overview.corrections.empty.title")} description={t("warehouse.overview.corrections.empty.description")} />
                    </TableCell>
                  </TableRow>
                )}
                {correctionTable.sortRows(corrections).map((correction) => (
                  <TableRow key={correction.id}>
                    {correctionTable.visibleColumns.map((column) => (
                      <TableCell key={column.key}>{column.cell(correction)}</TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("warehouse.overview.lots.title")}</CardTitle>
            <CardDescription>{fill(t("warehouse.overview.lots.description"), { days: String(overview.period.expiry_horizon_days) })}</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <Table colWidths={lotTable.colWidths}>
              <TableHeader>
                <TableRow>
                  {lotTable.visibleColumns.map((column) => (
                    <ResizableTableHead
                      key={column.key}
                      width={lotTable.getWidth(column.key)}
                      onResize={(width) => lotTable.setWidth(column.key, width)}
                      sortDirection={lotTable.sortDirectionFor(column.key)}
                      onSort={column.sortValue ? () => lotTable.toggleSort(column.key) : undefined}
                    >
                      {column.header}
                    </ResizableTableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {expiringLots.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={lotTable.visibleColumns.length} className="p-0">
                      <EmptyState icon={<CalendarClock className="h-5 w-5" />} title={t("warehouse.overview.lots.empty.title")} description={t("warehouse.overview.lots.empty.description")} />
                    </TableCell>
                  </TableRow>
                )}
                {lotTable.sortRows(expiringLots).map((lot) => (
                  <TableRow key={lot.lot_id}>
                    {lotTable.visibleColumns.map((column) => (
                      <TableCell key={column.key}>{column.cell(lot)}</TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
