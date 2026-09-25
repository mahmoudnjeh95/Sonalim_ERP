import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Trophy, TrendingUp } from "lucide-react";
import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";
import { InteractiveChart } from "../../components/charts/InteractiveChart";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Checkbox } from "../../components/ui/checkbox";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Popover, PopoverTrigger, PopoverContent } from "../../components/ui/popover";
import { Select } from "../../components/ui/select";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { DateRangeFilter } from "../../components/patterns/DateRangeFilter";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { formatQuantity } from "../../lib/units";
import { listProducts, type Product } from "../warehouse/api";
import { listPartners } from "../partners/api";
import { listPriceHistory, listSupplierLeaderboard, type PriceHistoryPoint, type SupplierLeaderboardEntry } from "../procurement/api";
import { AnalyticsErrorState, AnalyticsInlineError, AnalyticsLoadingState } from "./AnalyticsStates";

const SUPPLIER_COLORS = ["#0c978b", "#137cec", "#4332e2", "#d926a6", "#e08a1e", "#2e9e4f"];
const BEST_PRICE_COLOR = "#22c55e";
const CHART_ANIMATION_DURATION = 800;
const RANK_BADGE_STYLES = [
  "border-amber-300 bg-amber-100 text-amber-700 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-300",
  "border-slate-300 bg-slate-100 text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300",
  "border-orange-300 bg-orange-100 text-orange-700 dark:border-orange-800 dark:bg-orange-950 dark:text-orange-300",
];

type SupplierNameFn = (id: string | null) => string;
type TFn = (key: TranslationKey) => string;
type DateRange = { from: string; to: string };
type PeriodPreset = "all" | "day" | "week" | "month";
const PERIOD_PRESETS: PeriodPreset[] = ["all", "day", "week", "month"];

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function daysAgoIso(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

/** The from/to window a quick preset stands for, "all" meaning no window at all. */
function presetRangeFor(preset: PeriodPreset): DateRange | null {
  if (preset === "all") return null;
  const daysBack = preset === "day" ? 0 : preset === "week" ? 6 : 29;
  return { from: daysAgoIso(daysBack), to: todayIso() };
}

function inRange(dateStr: string | null, range: DateRange | null): boolean {
  if (!range) return true;
  if (!dateStr) return false;
  return dateStr >= range.from && dateStr <= range.to;
}

type HistoryPoint = PriceHistoryPoint & { product_id?: string };

function priceHistoryColumns(t: TFn, leadHeader: string, getLead: (point: HistoryPoint) => string, minPrice: number): ColumnDef<HistoryPoint>[] {
  return [
    {
      key: "date",
      header: t("analytics.priceHistory.column.date"),
      defaultWidth: 120,
      cell: (point) => point.order_date ?? "—",
      sortValue: (point) => point.order_date ?? "",
    },
    {
      key: "lead",
      header: leadHeader,
      defaultWidth: 180,
      cell: (point) => getLead(point),
      sortValue: (point) => getLead(point),
    },
    {
      key: "quantity",
      header: t("analytics.priceHistory.column.quantity"),
      defaultWidth: 130,
      cellClassName: "tabular-nums",
      cell: (point) => formatQuantity(point.quantity_ordered),
      sortValue: (point) => point.quantity_ordered ?? 0,
    },
    {
      key: "unitPriceOriginal",
      header: t("analytics.priceHistory.column.unitPriceOriginal"),
      defaultWidth: 160,
      cellClassName: "tabular-nums",
      cell: (point) => `${formatQuantity(point.unit_price)} ${point.unit_price_currency}`,
      sortValue: (point) => point.unit_price ?? 0,
    },
    {
      key: "unitPriceCfa",
      header: t("analytics.priceHistory.column.unitPriceCfa"),
      defaultWidth: 160,
      cellClassName: "tabular-nums",
      cell: (point) => {
        const isBest = point.unit_price_cfa === minPrice;
        if (point.unit_price_cfa == null) return "—";
        return (
          <span className={isBest ? "font-bold text-green-600 dark:text-green-400" : ""}>
            {formatQuantity(point.unit_price_cfa)} CFA
            {isBest && " ⭐"}
          </span>
        );
      },
      sortValue: (point) => point.unit_price_cfa ?? 0,
    },
  ];
}

function PriceHistoryTable({
  tableKey,
  columns,
  points,
  minPrice,
}: {
  tableKey: string;
  columns: ColumnDef<HistoryPoint>[];
  points: HistoryPoint[];
  minPrice: number;
}) {
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns(tableKey, columns);
  const rows = sortRows(points.slice().reverse());

  return (
    <Card>
      <CardContent className="flex justify-end p-3 pb-0">
        <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
      </CardContent>
      <CardContent className="p-0 pt-3">
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
            {rows.map((point) => (
              <TableRow key={point.order_id} className={point.unit_price_cfa === minPrice ? "bg-green-50 dark:bg-green-950" : ""}>
                {visibleColumns.map((column) => (
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
  );
}

export function PriceHistoryTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [productIds, setProductIds] = useState<string[]>([]);
  const [supplierId, setSupplierId] = useState("");
  const [periodPreset, setPeriodPreset] = useState<PeriodPreset>("all");
  const [customRange, setCustomRange] = useState<DateRange | null>(null);
  const presetRange = useMemo(() => presetRangeFor(periodPreset), [periodPreset]);
  const range = customRange ?? presetRange;

  const { data: products = [] } = useQuery({ queryKey: ["core", "products"], queryFn: () => listProducts(token) });
  const { data: suppliers = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token) });
  const {
    data: leaderboard = [],
    isError: leaderboardFailed,
    refetch: refetchLeaderboard,
  } = useQuery({
    queryKey: ["procurement", "supplier-leaderboard"],
    queryFn: () => listSupplierLeaderboard(token),
  });

  const supplierName: SupplierNameFn = (id) => (id && suppliers.find((s) => s.id === id)?.name) || t("common.none");
  const productName = (id: string) => (products.find((p) => p.id === id)?.name) || id;

  const supplierOptions = useMemo(() => suppliers.filter((s) => s.kind === "supplier" || s.kind === "both"), [suppliers]);
  const hasProducts = productIds.length > 0;

  // Supplier-only browsing (no product picked yet): every product this one supplier has been ordered for.
  const {
    data: supplierOnlyHistory = [],
    isLoading: isSupplierOnlyLoading,
    isError: supplierOnlyFailed,
    refetch: refetchSupplierOnly,
  } = useQuery({
    queryKey: ["procurement", "price-history", "by-supplier", supplierId],
    queryFn: async () => {
      const allHistory: (PriceHistoryPoint & { product_id?: string })[] = [];
      const results = await Promise.allSettled(products.map((p) => listPriceHistory(token, p.id, supplierId)));
      // One product failing only drops its own points, but every request failing
      // means the backend is unreachable -- surface that instead of "no history".
      if (results.length > 0 && results.every((result) => result.status === "rejected")) {
        throw new Error("supplier price history unavailable");
      }
      for (let i = 0; i < results.length; i++) {
        const result = results[i];
        if (result.status === "fulfilled") {
          allHistory.push(...result.value.map((p) => ({ ...p, product_id: products[i].id })));
        }
      }
      return allHistory;
    },
    enabled: !hasProducts && !!supplierId,
  });

  const filteredSupplierOnlyHistory = useMemo(
    () => supplierOnlyHistory.filter((p) => inRange(p.order_date, range)),
    [supplierOnlyHistory, range],
  );

  const { productCharts, supplierOnlyMinPrice } = useMemo(() => {
    const byProduct = new Map<string, PriceHistoryPoint[]>();
    for (const point of filteredSupplierOnlyHistory) {
      const pId = point.product_id || "";
      if (!byProduct.has(pId)) byProduct.set(pId, []);
      byProduct.get(pId)!.push(point);
    }
    const charts = Array.from(byProduct.entries()).map(([pId, points]) => ({
      productId: pId,
      productName: productName(pId),
      data: points.sort((a, b) => new Date(a.order_date || "").getTime() - new Date(b.order_date || "").getTime()),
    }));
    const prices = filteredSupplierOnlyHistory.map((p) => p.unit_price_cfa).filter((p) => p != null) as number[];
    return { productCharts: charts, supplierOnlyMinPrice: prices.length > 0 ? Math.min(...prices) : 0 };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filteredSupplierOnlyHistory, products]);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>{t("analytics.priceHistory.title")}</CardTitle>
          <CardDescription>{t("analytics.priceHistory.subtitle")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-64 space-y-1.5">
              <Label>{t("analytics.priceHistory.field.product")}</Label>
              <ProductMultiSelect products={products} selected={productIds} onChange={setProductIds} t={t} />
            </div>
            <div className="w-56 space-y-1.5">
              <Label htmlFor="price_history_supplier">{t("analytics.priceHistory.field.supplier")}</Label>
              <Select id="price_history_supplier" value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
                <option value="">{t("common.all")}</option>
                {supplierOptions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>{t("analytics.priceHistory.field.period")}</Label>
              <div className="flex flex-wrap items-center gap-2">
                <FilterTabs
                  value={periodPreset}
                  onChange={(value) => {
                    setPeriodPreset(value);
                    setCustomRange(null);
                  }}
                  options={PERIOD_PRESETS.map((value) => ({
                    value,
                    label: t(`analytics.priceHistory.period.${value}` as TranslationKey),
                  }))}
                />
                {range && (
                  <DateRangeFilter
                    from={range.from}
                    to={range.to}
                    onChange={setCustomRange}
                    onReset={() => setCustomRange(null)}
                    isDefault={customRange === null}
                  />
                )}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {hasProducts && (
        <div className="space-y-6 animate-in fade-in slide-in-from-top-4 duration-500">
          {productIds.map((pid, idx) => (
            <ProductPriceSection
              key={pid}
              productId={pid}
              productLabel={productName(pid)}
              supplierId={supplierId}
              range={range}
              token={token}
              t={t}
              supplierName={supplierName}
              animationDelay={idx * 80}
            />
          ))}
        </div>
      )}

      {leaderboardFailed ? (
        // The card's own empty text ("once purchase orders are recorded...") would
        // read as "there is no data", which a failed request does not tell us.
        <AnalyticsInlineError
          title={t("analytics.error.supplierLeaderboard.title")}
          impact={t("analytics.error.supplierLeaderboard.impact")}
          onRetry={() => void refetchLeaderboard()}
        />
      ) : (
        <div key={hasProducts ? "collapsed" : "expanded"} className="animate-in fade-in slide-in-from-top-2 duration-500">
          <SupplierLeaderboardCard leaderboard={leaderboard} collapsed={hasProducts} supplierName={supplierName} t={t} />
        </div>
      )}

      {!hasProducts && supplierId && supplierOnlyFailed && (
        <Card>
          <AnalyticsErrorState
            title={t("analytics.error.priceHistory.title")}
            impact={t("analytics.error.priceHistory.impact")}
            onRetry={() => void refetchSupplierOnly()}
          />
        </Card>
      )}

      {!hasProducts && supplierId && isSupplierOnlyLoading && <AnalyticsLoadingState />}

      {!hasProducts && supplierId && !isSupplierOnlyLoading && !supplierOnlyFailed && filteredSupplierOnlyHistory.length === 0 && (
        <EmptyState
          icon={<TrendingUp className="h-5 w-5" />}
          title={t("analytics.priceHistory.empty.noHistory.title")}
          description={t("analytics.priceHistory.empty.noHistory.description")}
        />
      )}

      {!hasProducts && supplierId && filteredSupplierOnlyHistory.length > 0 && (
        <>
          <div className="space-y-4">
            {productCharts.map((chart, chartIdx) => (
              <Card key={chart.productId} className="animate-in fade-in duration-500 slide-in-from-bottom-4" style={{ animationDelay: `${chartIdx * 50}ms` }}>
                <CardHeader>
                  <CardTitle className="text-base">{chart.productName}</CardTitle>
                  <CardDescription>{supplierName(supplierId)} - {t("analytics.priceHistory.chart.subtitle")}</CardDescription>
                </CardHeader>
                <CardContent>
                  <PriceLineChart data={chart.data} minPrice={supplierOnlyMinPrice} colorIdx={chartIdx} t={t} />
                </CardContent>
              </Card>
            ))}
          </div>

          <PriceHistoryTable
            tableKey="analytics.priceHistory.bySupplier"
            columns={priceHistoryColumns(
              t,
              t("analytics.priceHistory.column.product"),
              (point) => productName(point.product_id || ""),
              supplierOnlyMinPrice,
            )}
            points={filteredSupplierOnlyHistory}
            minPrice={supplierOnlyMinPrice}
          />
        </>
      )}
    </div>
  );
}

function ProductMultiSelect({
  products,
  selected,
  onChange,
  t,
}: {
  products: Product[];
  selected: string[];
  onChange: (ids: string[]) => void;
  t: TFn;
}) {
  const [search, setSearch] = useState("");
  const filtered = useMemo(
    () => products.filter((p) => p.name.toLowerCase().includes(search.toLowerCase())),
    [products, search],
  );
  const toggle = (id: string) => onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);

  const triggerLabel =
    selected.length === 0
      ? t("analytics.priceHistory.field.productPlaceholder")
      : selected.length === 1
        ? products.find((p) => p.id === selected[0])?.name || selected[0]
        : `${selected.length} ${t("common.selected")}`;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" className="w-full justify-between font-normal">
          <span className="truncate">{triggerLabel}</span>
          <ChevronDown className="h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0" align="start">
        <div className="border-b border-border p-2">
          <Input
            placeholder={t("analytics.priceHistory.field.productSearch")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="max-h-72 overflow-y-auto p-2">
          {filtered.length === 0 && (
            <p className="px-2 py-4 text-center text-xs text-muted-foreground">{t("analytics.priceHistory.field.noResults")}</p>
          )}
          <div className="space-y-1">
            {filtered.map((p) => (
              <div key={p.id} className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted">
                <Checkbox id={`price-history-product-${p.id}`} checked={selected.includes(p.id)} onCheckedChange={() => toggle(p.id)} />
                <Label htmlFor={`price-history-product-${p.id}`} className="flex-1 cursor-pointer truncate font-normal">
                  {p.name}
                </Label>
              </div>
            ))}
          </div>
        </div>
        {selected.length > 0 && (
          <div className="border-t border-border p-2">
            <Button variant="ghost" size="sm" className="w-full" onClick={() => onChange([])}>
              {t("common.clearSelection")}
            </Button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}

type RankedSupplierEntry = SupplierLeaderboardEntry & { rank: number };

function SupplierLeaderboardCard({
  leaderboard,
  collapsed,
  supplierName,
  t,
}: {
  leaderboard: SupplierLeaderboardEntry[];
  collapsed: boolean;
  supplierName: SupplierNameFn;
  t: TFn;
}) {
  const visible = collapsed ? leaderboard.slice(0, 3) : leaderboard;
  const rankedLeaderboard: RankedSupplierEntry[] = leaderboard.map((entry, idx) => ({ ...entry, rank: idx }));

  const columns: ColumnDef<RankedSupplierEntry>[] = [
    {
      key: "rank",
      header: "#",
      defaultWidth: 60,
      alwaysVisible: true,
      cell: (entry) => (
        <span
          className={`flex h-6 w-6 items-center justify-center rounded-full border text-xs font-bold ${RANK_BADGE_STYLES[entry.rank] ?? "border-border bg-muted text-muted-foreground"}`}
        >
          {entry.rank + 1}
        </span>
      ),
    },
    {
      key: "supplier",
      header: t("analytics.priceHistory.column.supplier"),
      defaultWidth: 180,
      cellClassName: "font-medium",
      cell: (entry) => supplierName(entry.supplier_id),
    },
    {
      key: "wins",
      header: t("analytics.priceHistory.leaderboard.column.wins"),
      defaultWidth: 140,
      cellClassName: "tabular-nums",
      cell: (entry) => (
        <span className="inline-flex items-center gap-1.5">
          {entry.best_price_count}
          {entry.rank === 0 && entry.best_price_count > 0 && <Trophy className="h-3.5 w-3.5 text-amber-500" />}
        </span>
      ),
    },
    {
      key: "products",
      header: t("analytics.priceHistory.leaderboard.column.products"),
      defaultWidth: 140,
      cellClassName: "tabular-nums",
      cell: (entry) => entry.products_supplied,
    },
    {
      key: "orders",
      header: t("analytics.priceHistory.leaderboard.column.orders"),
      defaultWidth: 140,
      cellClassName: "tabular-nums",
      cell: (entry) => entry.total_orders,
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "analytics.priceHistory.leaderboard",
    columns,
  );

  return (
    <Card className={collapsed ? "border-border" : "border-success/20"}>
      <CardHeader className={collapsed ? "py-3" : undefined}>
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <Trophy className="h-4 w-4 text-amber-500" />
            {t("analytics.priceHistory.leaderboard.title")}
          </CardTitle>
          {!collapsed && <CardDescription>{t("analytics.priceHistory.leaderboard.subtitle")}</CardDescription>}
        </div>
        {!collapsed && leaderboard.length > 0 && (
          <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
        )}
      </CardHeader>
      <CardContent className={collapsed ? "flex flex-wrap items-center gap-2 pt-4" : "p-0"}>
        {leaderboard.length === 0 ? (
          <p className={collapsed ? "text-sm text-muted-foreground" : "px-5 py-8 text-center text-sm text-muted-foreground"}>
            {t("analytics.priceHistory.leaderboard.empty.description")}
          </p>
        ) : collapsed ? (
          visible.map((entry, idx) => (
            <div key={entry.supplier_id} className="flex items-center gap-1.5 rounded-full border border-border bg-muted/40 px-3 py-1 text-sm">
              <span
                className={`flex h-5 w-5 items-center justify-center rounded-full border text-[10px] font-bold ${RANK_BADGE_STYLES[idx] ?? "border-border bg-muted text-muted-foreground"}`}
              >
                {idx + 1}
              </span>
              <span className="font-medium">{supplierName(entry.supplier_id)}</span>
              <span className="text-muted-foreground">
                · {entry.best_price_count} {t("analytics.priceHistory.leaderboard.wins")}
              </span>
            </div>
          ))
        ) : (
          <Table colWidths={colWidths}>
            <TableHeader>
              <TableRow>
                {visibleColumns.map((column) => (
                  <ResizableTableHead key={column.key} width={getWidth(column.key)} onResize={(width) => setWidth(column.key, width)}>
                    {column.header}
                  </ResizableTableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rankedLeaderboard.map((entry) => (
                <TableRow key={entry.supplier_id}>
                  {visibleColumns.map((column) => (
                    <TableCell key={column.key} className={column.cellClassName}>
                      {column.cell(entry)}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function ProductPriceSection({
  productId,
  productLabel,
  supplierId,
  range,
  token,
  t,
  supplierName,
  animationDelay,
}: {
  productId: string;
  productLabel: string;
  supplierId: string;
  range: DateRange | null;
  token: string;
  t: TFn;
  supplierName: SupplierNameFn;
  animationDelay: number;
}) {
  // Fetched unfiltered (every supplier, every order) so the best-supplier highlight
  // survives the supplier/period filters -- those narrow `history` below client-side
  // instead of issuing a second, identically-shaped request for the same product.
  const {
    data: rawHistory = [],
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["procurement", "price-history", productId],
    queryFn: () => listPriceHistory(token, productId),
  });

  const history = useMemo(
    () => rawHistory.filter((p) => (!supplierId || p.supplier_id === supplierId) && inRange(p.order_date, range)),
    [rawHistory, supplierId, range],
  );

  const bestSupplier = useMemo(() => {
    const priced = rawHistory.filter((p): p is PriceHistoryPoint & { unit_price_cfa: number } => p.unit_price_cfa != null);
    if (priced.length === 0) return null;
    return priced.reduce((min, p) => (p.unit_price_cfa < min.unit_price_cfa ? p : min));
  }, [rawHistory]);

  const { supplierCharts, minPrice } = useMemo(() => {
    const bySupplier = new Map<string, PriceHistoryPoint[]>();
    for (const point of history) {
      const sId = point.supplier_id || "";
      if (!bySupplier.has(sId)) bySupplier.set(sId, []);
      bySupplier.get(sId)!.push(point);
    }
    const charts = Array.from(bySupplier.entries()).map(([sId, points]) => ({
      supplierId: sId,
      supplierName: supplierName(sId),
      data: points.sort((a, b) => new Date(a.order_date || "").getTime() - new Date(b.order_date || "").getTime()),
    }));
    const prices = history.map((p) => p.unit_price_cfa).filter((p) => p != null) as number[];
    return { supplierCharts: charts, minPrice: prices.length > 0 ? Math.min(...prices) : 0 };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history]);

  return (
    <div className="space-y-4" style={{ animationDelay: `${animationDelay}ms` }}>
      <h3 className="text-sm font-semibold text-muted-foreground">{productLabel}</h3>

      {bestSupplier && (
        <Card className="border-success/30 bg-success-soft">
          <CardContent className="flex flex-wrap items-center gap-4 py-4">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-success/15 text-success">
              <Trophy className="h-5 w-5" />
            </div>
            <div className="flex-1">
              <p className="text-xs font-medium uppercase tracking-wide text-success">
                {t("analytics.priceHistory.bestSupplier.label")}
              </p>
              <p className="text-lg font-semibold text-foreground">{supplierName(bestSupplier.supplier_id)}</p>
            </div>
            <div className="text-right">
              <p className="text-xs text-muted-foreground">{t("analytics.priceHistory.bestSupplier.price")}</p>
              <p className="text-lg font-bold text-success">{formatQuantity(bestSupplier.unit_price_cfa)} CFA</p>
              {bestSupplier.order_date && <p className="text-xs text-muted-foreground">{bestSupplier.order_date}</p>}
            </div>
          </CardContent>
          <p className="border-t border-success/20 px-4 py-2 text-xs text-muted-foreground">
            {t("analytics.priceHistory.bestSupplier.scopeHint")}
          </p>
        </Card>
      )}

      {isError && (
        <Card>
          <AnalyticsErrorState
            title={t("analytics.error.priceHistory.title")}
            impact={t("analytics.error.priceHistory.impact")}
            onRetry={() => void refetch()}
          />
        </Card>
      )}

      {isLoading && <AnalyticsLoadingState />}

      {!isLoading && !isError && history.length === 0 && (
        <EmptyState
          icon={<TrendingUp className="h-5 w-5" />}
          title={t("analytics.priceHistory.empty.noHistory.title")}
          description={t("analytics.priceHistory.empty.noHistory.description")}
        />
      )}

      {history.length > 0 && (
        <>
          <div className="space-y-4">
            {supplierCharts.map((chart, chartIdx) => (
              <Card
                key={chart.supplierId}
                className={`animate-in fade-in duration-500 slide-in-from-bottom-4 ${chart.supplierId === bestSupplier?.supplier_id ? "border-success/40" : ""}`}
                style={{ animationDelay: `${chartIdx * 50}ms` }}
              >
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base">
                    {chart.supplierName}
                    {chart.supplierId === bestSupplier?.supplier_id && (
                      <Badge variant="success">
                        <Trophy className="h-3 w-3" />
                        {t("analytics.priceHistory.bestSupplier.badge")}
                      </Badge>
                    )}
                  </CardTitle>
                  <CardDescription>
                    {productLabel} - {t("analytics.priceHistory.chart.subtitle")}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <PriceLineChart data={chart.data} minPrice={minPrice} colorIdx={chartIdx} t={t} />
                </CardContent>
              </Card>
            ))}
          </div>

          <PriceHistoryTable
            tableKey="analytics.priceHistory.byProduct"
            columns={priceHistoryColumns(t, t("analytics.priceHistory.column.supplier"), (point) => supplierName(point.supplier_id), minPrice)}
            points={history}
            minPrice={minPrice}
          />
        </>
      )}
    </div>
  );
}

function PriceLineChart({ data, minPrice, colorIdx, t }: { data: PriceHistoryPoint[]; minPrice: number; colorIdx: number; t: TFn }) {
  const color = SUPPLIER_COLORS[colorIdx % SUPPLIER_COLORS.length];
  return (
    <InteractiveChart height={240}>
      <LineChart data={data.map((point) => ({ order_date: point.order_date, price: point.unit_price_cfa, isBest: point.unit_price_cfa === minPrice }))}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" vertical={false} />
        <XAxis dataKey="order_date" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
        <YAxis tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} allowDecimals />
        <Tooltip
          formatter={(value, _name, props) => {
            if (typeof value === "number") {
              const isBest = props.payload.isBest;
              const label = isBest ? t("analytics.priceHistory.chart.tooltip.bestPrice") : t("analytics.priceHistory.chart.tooltip.price");
              return [`${formatQuantity(value)} CFA${isBest ? " ⭐" : ""}`, label];
            }
            return value;
          }}
          contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }}
        />
        <Line
          type="monotone"
          dataKey="price"
          stroke={color}
          strokeWidth={2}
          dot={(props) => {
            const { cx, cy, payload } = props;
            const isBest = payload.isBest;
            return (
              <circle
                key={`${cx}-${cy}`}
                cx={cx}
                cy={cy}
                r={isBest ? 6 : 3}
                fill={isBest ? BEST_PRICE_COLOR : color}
                stroke={isBest ? "#ffffff" : "none"}
                strokeWidth={isBest ? 2 : 0}
                className={isBest ? "drop-shadow-lg" : ""}
              />
            );
          }}
          connectNulls
          isAnimationActive
          animationDuration={CHART_ANIMATION_DURATION}
        />
      </LineChart>
    </InteractiveChart>
  );
}
