import { motion, useReducedMotion } from "framer-motion";
import { cn } from "../../lib/utils";
import type { WorkOrderStatus } from "./api";

const TONE: Record<WorkOrderStatus, string> = {
  planned: "bg-muted-foreground/25",
  ongoing: "bg-warning",
  suspended: "bg-warning/45",
  closed: "bg-success",
  cancelled: "bg-destructive/50",
};

/**
 * Where an order stands, as one full-width line. Deliberately not a gauge: the
 * plant keeps an order running past its plan, so "produced / planned" is not a
 * completion and a filled share of it would be a number nobody chose. Grey
 * before it starts, yellow while it runs, green once closed.
 */
export function OrderStatusLine({ status, className }: { status: WorkOrderStatus; className?: string }) {
  const reduceMotion = useReducedMotion();
  return (
    <div className={cn("relative h-2 w-full overflow-hidden rounded-full", TONE[status], className)}>
      {status === "ongoing" && !reduceMotion && (
        <motion.span
          aria-hidden
          className="absolute inset-y-0 w-1/3 bg-gradient-to-r from-transparent via-white/45 to-transparent"
          initial={{ left: "-35%" }}
          animate={{ left: "105%" }}
          transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut", repeatDelay: 0.6 }}
        />
      )}
    </div>
  );
}
