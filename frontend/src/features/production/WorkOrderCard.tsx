import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowRight, CalendarDays, Factory, Gauge, Layers, User } from "lucide-react";
import { useI18n } from "../../lib/i18n";
import { formatQuantity } from "../../lib/units";

import { rowEnterProps, highlightRowEnterProps } from "../../components/motion/rowMotion";
import { Badge } from "../../components/ui/badge";
import { Skeleton } from "../../components/ui/skeleton";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { RowActionsMenu, type RowAction } from "../../components/patterns/RowActionsMenu";
import type { WorkOrder, WorkOrderOverview } from "./api";
import { OrderStatusLine } from "./OrderStatusLine";

/**
 * One order, compact. Official figures come from validated shifts; what is still waiting is shown
 * beside them in a muted line and never added to them.
 */
export function WorkOrderCard({
  order,
  overview,
  productNames,
  workCenterName,
  supervisorName,
  index,
  highlighted,
  actions,
}: {
  order: WorkOrder;
  overview: WorkOrderOverview | undefined;
  /** Null while the product list is still loading. */
  productNames: string[] | null;
  workCenterName: string;
  supervisorName: string;
  index: number;
  highlighted: boolean;
  actions: RowAction[];
}) {
  const { t } = useI18n();
  const produced = overview?.produced_quantity ?? 0;
  const pending = overview?.pending_quantity ?? 0;
  const shifts = overview?.shifts ?? { validated: 0, submitted: 0, in_progress: 0, returned: 0 };
  const shiftParts = [
    shifts.validated > 0 ? `${shifts.validated} ${t("production.workOrders.card.validated")}` : null,
    shifts.submitted > 0 ? `${shifts.submitted} ${t("production.workOrders.card.waiting")}` : null,
    shifts.in_progress > 0 ? `${shifts.in_progress} ${t("production.workOrders.card.inProgress")}` : null,
    shifts.returned > 0 ? `${shifts.returned} ${t("production.workOrders.card.returned")}` : null,
  ].filter((part): part is string => part !== null);

  return (
    <motion.article
      {...(highlighted ? highlightRowEnterProps(index) : rowEnterProps(index))}
      className="rounded-xl border border-border bg-card p-3.5 shadow-sm transition-shadow hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <Link
            to={`/production/work-orders/${order.id}`}
            className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
          >
            {order.reference}
            <ArrowRight className="h-3 w-3" />
          </Link>
          <div className="flex flex-wrap items-center gap-1">
            {productNames === null ? (
              <Skeleton className="h-5 w-28" />
            ) : productNames.length === 0 ? (
              <span className="text-xs text-muted-foreground">{t("production.workOrders.card.noProduct")}</span>
            ) : (
              productNames.map((name) => (
                <Badge key={name} variant="outline" className="max-w-full truncate">
                  {name}
                </Badge>
              ))
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {overview?.live && (
            <Badge variant="warning" className="gap-1">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-warning" />
              {t("production.workOrders.card.live")}
            </Badge>
          )}
          <StatusBadge status={order.status} />
          <RowActionsMenu actions={actions} label={t("production.workOrders.column.action")} />
        </div>
      </div>

      <dl className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <Factory className="h-3.5 w-3.5" />
          <dt className="sr-only">{t("production.workOrders.column.workCenter")}</dt>
          <dd className="font-medium text-foreground">{workCenterName}</dd>
        </div>
        <div className="flex items-center gap-1.5">
          <CalendarDays className="h-3.5 w-3.5" />
          <dt className="sr-only">{t("production.workOrders.column.startDate")}</dt>
          <dd className="tabular-nums">{order.start_date ?? "—"}</dd>
        </div>
        <div className="flex items-center gap-1.5">
          <User className="h-3.5 w-3.5" />
          <dt className="sr-only">{t("production.workOrders.column.supervisor")}</dt>
          <dd>{supervisorName || "—"}</dd>
        </div>
      </dl>

      <div className="mt-3 space-y-1">
        <div className="flex items-baseline justify-between gap-2 text-xs">
          <span className="tabular-nums text-foreground">
            <span className="font-semibold">{formatQuantity(produced, "t")}</span>{" "}
            <span className="text-muted-foreground">{t("production.workOrders.card.produced")}</span>
          </span>
          <span className="tabular-nums text-muted-foreground">
            {order.planned_quantity !== null
              ? `${t("production.workOrders.card.planned")} ${formatQuantity(order.planned_quantity, "t")}`
              : t("production.workOrders.card.noPlan")}
          </span>
        </div>
        <OrderStatusLine status={order.status} />
        {pending > 0 && (
          <p className="text-xs text-muted-foreground">
            + {formatQuantity(pending, "t")} {t("production.workOrders.card.pending")}
          </p>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-2.5 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <Layers className="h-3.5 w-3.5" />
          {shiftParts.length > 0 ? shiftParts.join(" · ") : t("production.workOrders.card.noShift")}
          {overview?.last_shift_date && (
            <span className="tabular-nums">
              {" "}
              · {t("production.workOrders.card.lastShift")} {overview.last_shift_date}
            </span>
          )}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Gauge className="h-3.5 w-3.5" />
          {t("production.workOrders.column.yield")}{" "}
          <span className="font-medium tabular-nums text-foreground">
            {overview?.yield_ratio == null ? "—" : `${(overview.yield_ratio * 100).toFixed(1)}%`}
          </span>
        </span>
      </div>
    </motion.article>
  );
}
