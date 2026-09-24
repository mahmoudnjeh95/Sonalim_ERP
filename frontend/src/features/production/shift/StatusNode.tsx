import { motion, useReducedMotion } from "framer-motion";
import { Minus, PenLine, RotateCcw } from "lucide-react";
import { cn } from "../../../lib/utils";
import type { SectionStatus } from "./shiftApi";

/**
 * The mark of a section's state: a dashed ring before it is started, a pen while it is
 * a draft, a check that draws itself when it is handed in, a dash when there is
 * nothing to report, and a returned arrow that shakes once when a validator sends it back.
 *
 * The rail carries one per section, and it is the only place motion plays without the
 * team having asked for it: a hand-in changes the mark, and that change is the point.
 */
export function StatusNode({ status, size = 22 }: { status: SectionStatus; size?: number }) {
  const reduceMotion = useReducedMotion();
  const base = "relative inline-flex shrink-0 items-center justify-center rounded-full";
  const style = { width: size, height: size };

  switch (status) {
    case "submitted":
      return (
        <span className={cn(base, "bg-success text-success-foreground")} style={style} aria-hidden>
          <svg viewBox="0 0 24 24" className="h-3/5 w-3/5" fill="none" stroke="currentColor" strokeWidth={3.2} strokeLinecap="round" strokeLinejoin="round">
            <motion.path
              key="check"
              d="M5 12.5l4.5 4.5L19 7.5"
              initial={reduceMotion ? false : { pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 0.35, ease: "easeOut" }}
            />
          </svg>
        </span>
      );
    case "nothing_to_report":
      return (
        <span className={cn(base, "bg-muted text-muted-foreground ring-1 ring-inset ring-border")} style={style} aria-hidden>
          <Minus className="h-3/5 w-3/5" strokeWidth={3} />
        </span>
      );
    case "draft":
      return (
        <span className={cn(base, "bg-warning-soft text-warning ring-1 ring-inset ring-warning/40")} style={style} aria-hidden>
          <PenLine className="h-3/5 w-3/5" strokeWidth={2.4} />
        </span>
      );
    case "returned":
      return (
        <span className={cn(base, "bg-destructive text-destructive-foreground", !reduceMotion && "animate-shake")} style={style} aria-hidden>
          <RotateCcw className="h-3/5 w-3/5" strokeWidth={2.8} />
        </span>
      );
    default:
      return <span className={cn(base, "border-[1.5px] border-dashed border-border bg-background")} style={style} aria-hidden />;
  }
}
