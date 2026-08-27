import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Coins, Package, ShoppingBag, Tag } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { listProducts, listStock } from "../warehouse/api";

const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const STOCK_QUERY_KEY = ["warehouse", "stock"] as const;

function formatMoney(amount: number) {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(amount);
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

  const sellableCount = products.filter((p) => p.is_sellable).length;
  const purchasableCount = products.filter((p) => p.is_purchasable).length;
  const lotTrackedCount = products.filter((p) => p.lot_serial_tracking !== "none").length;
  const belowAlertCount = products.filter((p) => {
    const onHand = onHandByProduct.get(p.id) ?? 0;
    return p.stock_alert_threshold != null && onHand < p.stock_alert_threshold;
  }).length;

  const stockValueRows = products
    .map((product) => ({
      name: product.name,
      value: (onHandByProduct.get(product.id) ?? 0) * product.selling_price,
    }))
    .filter((row) => row.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, 10);
  const totalStockValue = products.reduce((sum, product) => sum + (onHandByProduct.get(product.id) ?? 0) * product.selling_price, 0);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatCard label={t("products.statistics.stat.total")} value={products.length} icon={<Package className="h-5 w-5" />} />
        <StatCard label={t("products.statistics.stat.sellable")} value={sellableCount} icon={<ShoppingBag className="h-5 w-5" />} accent="success" />
        <StatCard label={t("products.statistics.stat.purchasable")} value={purchasableCount} icon={<ShoppingBag className="h-5 w-5" />} accent="accent" />
        <StatCard label={t("products.statistics.stat.lotTracked")} value={lotTrackedCount} icon={<Tag className="h-5 w-5" />} />
        <StatCard label={t("products.statistics.stat.belowAlert")} value={belowAlertCount} icon={<AlertTriangle className="h-5 w-5" />} accent="warning" />
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Coins className="h-4 w-4 text-muted-foreground" />
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
              <p className="mb-3 text-sm text-muted-foreground">
                {t("products.statistics.totalStockValue")}: <span className="font-medium text-foreground">{formatMoney(totalStockValue)}</span>
              </p>
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
