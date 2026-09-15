import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AlertTriangle, Boxes, ClipboardCheck, Coins, Package, PackageX, Tags } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useAuth } from "../../lib/auth";
import { currentLocale, useI18n } from "../../lib/i18n";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, TableHead } from "../../components/ui/table";
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { cn } from "../../lib/utils";
import { listProducts, listStock } from "../warehouse/api";

const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const STOCK_QUERY_KEY = ["warehouse", "stock"] as const;

// Same fixed hue order used across other analysis tabs (AnalysisTab.tsx,
// FinishedGoodsAnalysisTab.tsx) -- reused here rather than invented, so PL/PC
// carry the same identity colors everywhere the app charts them.
const TYPE_COLORS: Record<"PL" | "PC", string> = {
  PL: "hsl(217 91% 45%)",
  PC: "hsl(142 71% 40%)",
};

function formatMoney(amount: number) {
  return new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 0 }).format(amount);
}

function formatNumber(amount: number, maximumFractionDigits = 1) {
  return new Intl.NumberFormat(currentLocale(), { maximumFractionDigits }).format(amount);
}

export function StatisticsTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;

  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: stockItems = [] } = useQuery({ queryKey: STOCK_QUERY_KEY, queryFn: () => listStock(token) });

  const onHandByProduct = new Map<string, number>();
  for (const item of stockItems) {
    onHandByProduct.set(item.product_id, (onHandByProduct.get(item.product_id) ?? 0) + item.quantity_on_hand);
  }

  // Below-threshold and out-of-stock are both worth acting on, but they are not
  // the same severity — a sellable product with nothing on hand can't be sold
  // today, while "below its alert" is a warning to reorder soon. Named rows, not
  // just a count, so the reader knows which product to chase without a click.
  const outOfStockProducts = products.filter((p) => p.is_sellable && (onHandByProduct.get(p.id) ?? 0) <= 0);
  const belowAlertProducts = products.filter((p) => {
    const onHand = onHandByProduct.get(p.id) ?? 0;
    return p.stock_alert_threshold != null && onHand > 0 && onHand < p.stock_alert_threshold;
  });

  const stockValueRows = products
    .map((product) => ({
      name: product.name,
      value: (onHandByProduct.get(product.id) ?? 0) * product.selling_price,
    }))
    .filter((row) => row.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, 10);
  const totalStockValue = products.reduce((sum, product) => sum + (onHandByProduct.get(product.id) ?? 0) * product.selling_price, 0);
  const top3Share = totalStockValue > 0 ? (sum(stockValueRows.slice(0, 3).map((r) => r.value)) / totalStockValue) * 100 : null;

  // Products by type (PL/PC) -- a fixed 2-category identity chart, so each type
  // keeps its own color rather than sharing the single magnitude hue below.
  const typeRows = (["PL", "PC"] as const)
    .map((type) => ({ type, label: t(`products.statistics.type${type}`), count: products.filter((p) => p.product_type === type).length }))
    .filter((row) => row.count > 0);

  // Products by family -- pure magnitude (a count), so one hue is correct; family
  // name is already the axis label, so no legend is needed.
  const familyCounts = new Map<string, number>();
  for (const product of products) {
    const key = product.product_family?.trim() || t("products.statistics.noFamily");
    familyCounts.set(key, (familyCounts.get(key) ?? 0) + 1);
  }
  const familyRows = Array.from(familyCounts.entries())
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count);

  // Packaging efficiency -- per-tonne metrics straight from the fiche produit's own
  // formulas (verified against the source sheet): 1 tonne / net weight = sachets/tonne;
  // divide down through the packaging hierarchy for cartons and pallets per tonne.
  const packagingRows = products
    .filter((p) => p.net_weight_grams != null && p.net_weight_grams > 0)
    .map((product) => {
      const sachetsPerTonne = 1_000_000 / product.net_weight_grams!;
      const cartonsPerTonne = product.sachets_per_package ? sachetsPerTonne / product.sachets_per_package : null;
      const palletsPerTonne = cartonsPerTonne != null && product.cartons_per_pallet ? cartonsPerTonne / product.cartons_per_pallet : null;
      const packagingKgPerTonne = product.empty_packaging_weight_grams
        ? (sachetsPerTonne * product.empty_packaging_weight_grams) / 1000
        : null;
      return {
        id: product.id,
        name: product.name,
        family: product.product_family || t("products.statistics.noFamily"),
        type: product.product_type,
        netWeight: product.net_weight_grams!,
        sachetsPerTonne,
        palletsPerTonne,
        packagingKgPerTonne,
      };
    })
    .filter((row) => row.packagingKgPerTonne != null)
    .sort((a, b) => (b.packagingKgPerTonne ?? 0) - (a.packagingKgPerTonne ?? 0));
  const packagingChartRows = packagingRows.slice(0, 10).map((row) => ({ name: row.name, value: row.packagingKgPerTonne ?? 0 }));

  const attentionRows: { code: string; tone: "warning" | "destructive"; title: string; detail: string }[] = [
    ...(outOfStockProducts.length > 0
      ? [
          {
            code: "out-of-stock",
            tone: "destructive" as const,
            title: t("products.statistics.attention.outOfStock"),
            detail: outOfStockProducts.map((p) => p.name).join(", "),
          },
        ]
      : []),
    ...(belowAlertProducts.length > 0
      ? [
          {
            code: "below-alert",
            tone: "warning" as const,
            title: t("products.statistics.attention.belowAlert"),
            detail: belowAlertProducts.map((p) => p.name).join(", "),
          },
        ]
      : []),
  ];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("products.statistics.totalStockValue")} value={Math.round(totalStockValue)} icon={<Coins className="h-5 w-5" />} accent="primary" />
        <StatCard label={t("products.statistics.stat.outOfStock")} value={outOfStockProducts.length} icon={<PackageX className="h-5 w-5" />} accent="destructive" />
        <StatCard label={t("products.statistics.stat.belowAlert")} value={belowAlertProducts.length} icon={<AlertTriangle className="h-5 w-5" />} accent="warning" />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("products.statistics.attention.title")}</CardTitle>
        </CardHeader>
        <CardContent className={attentionRows.length === 0 ? "p-0" : "space-y-2"}>
          {attentionRows.length === 0 ? (
            <EmptyState
              icon={<ClipboardCheck className="h-5 w-5" />}
              title={t("products.statistics.attention.empty.title")}
              description={t("products.statistics.attention.empty.description")}
            />
          ) : (
            attentionRows.map((row) => (
              <Link
                key={row.code}
                to="/warehouse"
                className={cn(
                  "flex items-start gap-3 rounded-lg border p-3 transition-colors",
                  row.tone === "destructive"
                    ? "border-destructive/20 bg-destructive-soft hover:bg-destructive-soft/70"
                    : "border-warning/20 bg-warning-soft hover:bg-warning-soft/70",
                )}
              >
                <AlertTriangle className={cn("mt-0.5 h-4 w-4 shrink-0", row.tone === "destructive" ? "text-destructive" : "text-warning")} />
                <div className="min-w-0">
                  <p className={cn("text-sm font-medium", row.tone === "destructive" ? "text-destructive" : "text-warning")}>{row.title}</p>
                  <p className="text-sm text-muted-foreground">{row.detail}</p>
                </div>
                <span className="ml-auto self-center text-xs text-muted-foreground">{t("products.statistics.attention.open")}</span>
              </Link>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Package className="h-4 w-4 text-muted-foreground" />
            <div>
              <CardTitle>{t("products.statistics.chart.title")}</CardTitle>
              <CardDescription>{t("products.statistics.chart.description")}</CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {stockValueRows.length === 0 ? (
            <EmptyState icon={<Coins className="h-5 w-5" />} title={t("products.statistics.empty.title")} description={t("products.statistics.empty.description")} />
          ) : (
            <>
              {top3Share !== null && (
                <p className="mb-3 text-sm text-muted-foreground">
                  {t("products.statistics.concentration")}: <span className="font-medium text-foreground">{top3Share.toFixed(0)}%</span>
                </p>
              )}
              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={stockValueRows} layout="vertical" margin={{ left: 24 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="name" width={160} tick={{ fontSize: 11, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                  <Tooltip
                    formatter={(value) => formatMoney(Number(value))}
                    contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }}
                  />
                  <Bar dataKey="value" fill="hsl(217 91% 45%)" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Boxes className="h-4 w-4 text-muted-foreground" />
              <div>
                <CardTitle>{t("products.statistics.byType.title")}</CardTitle>
                <CardDescription>{t("products.statistics.byType.description")}</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {typeRows.length === 0 ? (
              <EmptyState icon={<Boxes className="h-5 w-5" />} title={t("products.statistics.empty.title")} description={t("products.statistics.empty.description")} />
            ) : (
              <ResponsiveContainer width="100%" height={Math.max(120, typeRows.length * 60)}>
                <BarChart data={typeRows} layout="vertical" margin={{ left: 24 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" horizontal={false} />
                  <XAxis type="number" allowDecimals={false} tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="label" width={140} tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }} />
                  <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                    {typeRows.map((row) => (
                      <Cell key={row.type} fill={TYPE_COLORS[row.type]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Tags className="h-4 w-4 text-muted-foreground" />
              <div>
                <CardTitle>{t("products.statistics.byFamily.title")}</CardTitle>
                <CardDescription>{t("products.statistics.byFamily.description")}</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {familyRows.length === 0 ? (
              <EmptyState icon={<Tags className="h-5 w-5" />} title={t("products.statistics.empty.title")} description={t("products.statistics.empty.description")} />
            ) : (
              <ResponsiveContainer width="100%" height={Math.max(200, familyRows.length * 32)}>
                <BarChart data={familyRows} layout="vertical" margin={{ left: 24 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" horizontal={false} />
                  <XAxis type="number" allowDecimals={false} tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="name" width={140} tick={{ fontSize: 11, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }} />
                  <Bar dataKey="count" fill="hsl(271 76% 53%)" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Package className="h-4 w-4 text-muted-foreground" />
            <div>
              <CardTitle>{t("products.statistics.packaging.title")}</CardTitle>
              <CardDescription>{t("products.statistics.packaging.description")}</CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {packagingRows.length === 0 ? (
            <EmptyState
              icon={<Package className="h-5 w-5" />}
              title={t("products.statistics.packaging.empty.title")}
              description={t("products.statistics.packaging.empty.description")}
            />
          ) : (
            <>
              <div>
                <p className="mb-3 text-sm font-medium text-foreground">{t("products.statistics.packaging.chart.title")}</p>
                <p className="mb-3 text-sm text-muted-foreground">{t("products.statistics.packaging.chart.description")}</p>
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={packagingChartRows} layout="vertical" margin={{ left: 24 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                    <YAxis type="category" dataKey="name" width={160} tick={{ fontSize: 11, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                    <Tooltip
                      formatter={(value) => `${formatNumber(Number(value))} kg/t`}
                      contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }}
                    />
                    <Bar dataKey="value" fill="hsl(31 91% 48%)" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("products.statistics.packaging.table.product")}</TableHead>
                      <TableHead>{t("products.statistics.packaging.table.family")}</TableHead>
                      <TableHead>{t("products.statistics.packaging.table.type")}</TableHead>
                      <TableHead>{t("products.statistics.packaging.table.netWeight")}</TableHead>
                      <TableHead>{t("products.statistics.packaging.table.sachetsPerTonne")}</TableHead>
                      <TableHead>{t("products.statistics.packaging.table.palletsPerTonne")}</TableHead>
                      <TableHead>{t("products.statistics.packaging.table.packagingPerTonne")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {packagingRows.map((row) => (
                      <TableRow key={row.id}>
                        <TableCell className="font-medium">{row.name}</TableCell>
                        <TableCell className="text-muted-foreground">{row.family}</TableCell>
                        <TableCell>{row.type}</TableCell>
                        <TableCell>{formatNumber(row.netWeight, 0)}</TableCell>
                        <TableCell>{formatNumber(row.sachetsPerTonne, 0)}</TableCell>
                        <TableCell>{row.palletsPerTonne != null ? formatNumber(row.palletsPerTonne, 2) : "—"}</TableCell>
                        <TableCell>{row.packagingKgPerTonne != null ? formatNumber(row.packagingKgPerTonne, 1) : "—"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function sum(values: number[]): number {
  return values.reduce((total, value) => total + value, 0);
}
