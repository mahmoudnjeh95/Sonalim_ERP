import { Fragment } from "react";
import { motion } from "framer-motion";
import { Check, ChevronRight } from "lucide-react";
import { AppLoader } from "../../components/patterns/AppLoader";
import { useI18n } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { productionSteps, type ProductionStepId, type StageStates, type StageStatus } from "./productionSteps";

interface Props {
  states: StageStates;
  loading?: boolean;
  onStepClick?: (id: ProductionStepId) => void;
}

const STATUS_KEY = {
  empty: "production.flow.status.empty",
  pending: "production.flow.status.pending",
  done: "production.flow.status.done",
} as const satisfies Record<StageStatus, string>;

const STATUS_TEXT: Record<StageStatus, string> = {
  empty: "text-muted-foreground",
  pending: "text-primary",
  done: "text-success",
};

const STATUS_DOT: Record<StageStatus, string> = {
  empty: "bg-muted-foreground/40",
  pending: "bg-primary",
  done: "bg-success",
};

/**
 * The artwork is never recoloured: a stage with nothing filed is the same
 * picture greyed out, and the status rides on top as a marker.
 */
export function ProductionFlow({ states, loading = false, onStepClick }: Props) {
  const { t } = useI18n();

  // Until the reports are in, every stage would read "nothing declared" — show the loader instead of a false empty flow.
  if (loading) return <AppLoader className="min-h-[264px]" />;

  return (
    <div className="overflow-x-auto">
      <div className="flex min-w-[720px] items-start py-2">
        {productionSteps.map((step, index) => {
          const state = states[step.id];
          const status: StageStatus = state.status;
          const label = t(step.labelKey);
          const count = state.reportCount;
          const isLast = index === productionSteps.length - 1;

          return (
            <Fragment key={step.id}>
              <motion.button
                type="button"
                onClick={() => onStepClick?.(step.id)}
                aria-haspopup="dialog"
                title={
                  state.lastReportDate
                    ? `${label} — ${t("production.flow.lastReport")}: ${state.lastReportDate}`
                    : label
                }
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25, delay: index * 0.05, ease: "easeOut" }}
                className={cn(
                  "group relative min-w-0 flex-1 rounded-xl px-2 pb-3 pt-2 text-center transition-colors",
                  "hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40",
                )}
              >
                <div className="relative mx-auto flex h-28 w-full max-w-[180px] items-center justify-center">
                  <img
                    src={step.image}
                    alt=""
                    draggable={false}
                    className={cn(
                      "h-full w-full object-contain transition-[filter,opacity,transform] duration-300",
                      status === "empty" && "opacity-40 grayscale",
                      status !== "empty" && "group-hover:scale-[1.03]",
                    )}
                  />
                  {status === "pending" && (
                    <span className="absolute bottom-0 right-1 flex h-4 w-4 items-center justify-center rounded-full border-2 border-background bg-primary">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/60 motion-reduce:hidden" />
                    </span>
                  )}
                  {status === "done" && (
                    <motion.span
                      initial={{ scale: 0.3, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      transition={{ type: "spring", stiffness: 420, damping: 18 }}
                      className="absolute bottom-0 right-1 flex h-6 w-6 items-center justify-center rounded-full border-2 border-background bg-success text-success-foreground"
                    >
                      <Check className="h-3.5 w-3.5" strokeWidth={3} />
                    </motion.span>
                  )}
                </div>

                <p className="mt-2 text-sm font-semibold text-foreground">{label}</p>
                <p className={cn("mt-1 flex items-center justify-center gap-1.5 text-xs font-medium", STATUS_TEXT[status])}>
                  <span className={cn("h-1.5 w-1.5 rounded-full", STATUS_DOT[status])} />
                  {t(STATUS_KEY[status])}
                </p>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  {count} {t(count === 1 ? "production.flow.report.one" : "production.flow.report.many")}
                </p>
              </motion.button>

              {!isLast && (
                <ChevronRight
                  aria-hidden
                  className={cn("mt-14 h-5 w-5 shrink-0", status === "done" ? "text-success" : "text-border")}
                />
              )}
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}
