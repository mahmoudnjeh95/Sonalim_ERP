import { Link } from "react-router-dom";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { useI18n } from "../../lib/i18n";
import type { Product } from "../warehouse/api";
import { AnalyticsEmptyState } from "./AnalyticsStates";
import { fill, formatNumber, formatPercent } from "./manufacturing/format";
import type { Formatters } from "./manufacturing/insights";
import type { OrdersSummary } from "./manufacturing/metrics";
import ProductionLineIllustration from "../../assets/illustrations/production-line.svg?react";

const MAX_ROWS = 6;

/** Running OFs against their planned quantity. Least-complete first, since that is where attention goes. */
export function OrderProgressPanel({ orders, products, fmt }: { orders: OrdersSummary; products: Product[]; fmt: Formatters }) {
  const { t } = useI18n();
  const productName = new Map(products.map((product) => [product.id, product.name]));
  const rows = orders.open.slice(0, MAX_ROWS);

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{t("analytics.orders.title")}</CardTitle>
          <CardDescription>
            {orders.attainmentPct === null
              ? t("analytics.orders.subtitle")
              : fill(t("analytics.orders.attainment"), {
                  pct: formatPercent(orders.attainmentPct, 0),
                  produced: fmt.tonnes(orders.produced),
                  planned: fmt.tonnes(orders.planned),
                })}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {rows.length === 0 ? (
          <AnalyticsEmptyState
            illustration={ProductionLineIllustration}
            title={t("analytics.orders.empty.title")}
            description={t("analytics.orders.empty.description")}
          />
        ) : (
          <ul className="space-y-4">
            {rows.map((order) => {
              const capped = Math.min(100, order.completionPct);
              return (
                <li key={order.id} className="space-y-1.5">
                  <div className="flex items-baseline justify-between gap-3">
                    <Link to={`/production/work-orders/${order.id}`} className="text-sm font-medium hover:underline">
                      {order.reference}
                    </Link>
                    <span className="truncate text-xs text-muted-foreground">
                      {order.productId ? (productName.get(order.productId) ?? "") : t("analytics.orders.noProduct")}
                    </span>
                  </div>
                  <div
                    role="progressbar"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={Math.round(capped)}
                    aria-label={order.reference}
                    className="h-2 overflow-hidden rounded-full bg-muted"
                  >
                    <div className="h-full rounded-full bg-primary transition-[width] duration-300" style={{ width: `${capped}%` }} />
                  </div>
                  <p className="text-xs tabular-nums text-muted-foreground">
                    {fmt.tonnes(order.produced)} / {fmt.tonnes(order.planned)} · {formatNumber(order.completionPct, 0)}% ·{" "}
                    {fill(t("analytics.orders.remaining"), { remaining: fmt.tonnes(order.remaining) })}
                  </p>
                </li>
              );
            })}
          </ul>
        )}
        {orders.openWithoutPlan > 0 && (
          <p className="text-xs text-muted-foreground">
            {fill(t("analytics.orders.withoutPlan"), { count: String(orders.openWithoutPlan) })}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
