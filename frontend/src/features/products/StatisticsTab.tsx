import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AlertTriangle, ClipboardCheck, Coins, Package, PackageX } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useAuth } from "../../lib/auth";
import { currentLocale, useI18n } from "../../lib/i18n";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { cn } from "../../lib/utils";
import { listProducts, listStock } from "../warehouse/api";

const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const STOCK_QUERY_KEY = ["warehouse", "stock"] as const;

function formatMoney(amount: number) {
  return new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 0 }).format(amount);
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
    </div>
  );
}

function sum(values: number[]): number {
  return values.reduce((total, value) => total + value, 0);
}
