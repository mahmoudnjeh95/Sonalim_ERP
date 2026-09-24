import type { ReactNode } from "react";
import { motion } from "framer-motion";
import { CalendarDays, Factory } from "lucide-react";
import { cn } from "../../lib/utils";
import ProductionLineIllustration from "../../assets/illustrations/production-line.svg?react";
import { OrderStatusLine } from "./OrderStatusLine";
import type { WorkOrderStatus } from "./api";

/**
 * The top of an OF: who it is, where it runs, and where it stands. The line
 * under the title is the order's state, not a share of its plan.
 */
export function WorkOrderHero({
  reference,
  status,
  badges,
  lineName,
  period,
  actions,
  children,
}: {
  reference: string;
  status: WorkOrderStatus;
  /** Status badge, product chips, type — rendered beside the reference. */
  badges: ReactNode;
  lineName: string | null;
  period: string;
  actions: ReactNode;
  /** The KPI tiles. */
  children: ReactNode;
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, ease: "easeOut" }}
      className="relative overflow-hidden rounded-2xl border border-border bg-gradient-to-br from-primary/[0.07] via-background to-background shadow-sm"
    >
      <div className="relative flex gap-6 p-5">
      <div className="min-w-0 flex-1 space-y-4">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight">{reference}</h1>
              {badges}
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
              {lineName && (
                <span className="inline-flex items-center gap-1.5">
                  <Factory className="h-3.5 w-3.5" />
                  <span className="font-medium text-foreground">{lineName}</span>
                </span>
              )}
              <span className="inline-flex items-center gap-1.5 tabular-nums">
                <CalendarDays className="h-3.5 w-3.5" />
                {period}
              </span>
            </div>
          </div>
          <div className="ml-auto flex flex-wrap gap-2">{actions}</div>
        </div>
        <OrderStatusLine status={status} />
      </div>
        {/* The plant's own line illustration, whole, at its 8:5 ratio. */}
        <div aria-hidden className="pointer-events-none hidden aspect-[8/5] w-[240px] shrink-0 xl:block">
          <ProductionLineIllustration className="h-full w-full" />
        </div>
      </div>
      <div className="relative grid grid-cols-2 gap-px border-t border-border bg-border sm:grid-cols-3 xl:grid-cols-6">
        {children}
      </div>
    </motion.section>
  );
}

export function KpiTile({
  icon,
  label,
  value,
  sub,
  tone = "primary",
  index = 0,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  sub?: ReactNode;
  tone?: "primary" | "success" | "warning" | "accent" | "muted";
  index?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: 0.05 + index * 0.04, ease: "easeOut" }}
      className="flex min-w-0 flex-col gap-1.5 bg-background px-4 py-3.5"
    >
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <span
          className={cn(
            "flex h-6 w-6 shrink-0 items-center justify-center rounded-md [&_svg]:h-3.5 [&_svg]:w-3.5",
            tone === "primary" && "bg-primary/10 text-primary",
            tone === "success" && "bg-success-soft text-success",
            tone === "warning" && "bg-warning-soft text-warning",
            tone === "accent" && "bg-accent/10 text-accent",
            tone === "muted" && "bg-muted text-muted-foreground",
          )}
        >
          {icon}
        </span>
        <span className="truncate">{label}</span>
      </div>
      <p className="truncate text-xl font-semibold tabular-nums tracking-tight">{value}</p>
      {sub && <div className="truncate text-xs text-muted-foreground">{sub}</div>}
    </motion.div>
  );
}
