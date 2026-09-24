import type { ReactNode } from "react";
import { ArrowDownRight, ArrowUpRight, Info, Minus } from "lucide-react";
import { motion } from "framer-motion";
import { Card } from "../../components/ui/card";
import { AnimatedValue } from "../../components/motion/AnimatedValue";
import { useI18n } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { AnalyticsStatusBadge, TONE_TEXT } from "./AnalyticsStatusBadge";
import type { SvgComponent } from "./AnalyticsStates";
import type { Comparison } from "./manufacturing/metrics";

const DIRECTION_ICON = { up: ArrowUpRight, down: ArrowDownRight, flat: Minus } as const;

export function ProductionKpiCard({
  icon: Icon,
  label,
  value,
  format,
  comparison,
  deltaText,
  previousText,
  driver,
  unavailable,
  index,
  extra,
}: {
  icon: SvgComponent;
  label: string;
  /** null renders "—" plus `unavailable`; never coerce a missing input to 0. */
  value: number | null;
  format: (value: number) => string;
  comparison: Comparison | null;
  /** The change, already formatted with its unit ("+1.2 pp", "−4.0%"). */
  deltaText: string | null;
  previousText: string | null;
  /** One line naming what is driving the figure, taken from the data. */
  driver: string | null;
  /** Why the figure cannot be shown. */
  unavailable: string | null;
  index: number;
  /** A second, unrelated line of context (e.g. a cross-module count with its own link) — rides
   * below `driver` instead of replacing it. */
  extra?: ReactNode;
}) {
  const { t } = useI18n();
  const tone = comparison?.tone ?? "neutral";
  const DirectionIcon = comparison?.direction ? DIRECTION_ICON[comparison.direction] : null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, delay: index * 0.04 }}
      className="min-w-0"
    >
      <Card className="flex h-full min-w-0 flex-col gap-3 p-4">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted">
            <Icon aria-hidden className="h-5 w-5" />
          </span>
          <p className="min-w-0 text-sm font-medium leading-tight text-foreground">{label}</p>
        </div>

        <p className="whitespace-nowrap text-2xl font-semibold tabular-nums tracking-tight">
          {value === null ? "—" : <AnimatedValue value={value} format={format} />}
        </p>

        {value === null ? (
          <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            {unavailable}
          </p>
        ) : (
          <div className="space-y-1.5 text-xs">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <AnalyticsStatusBadge tone={tone} label={comparison?.delta == null ? t("analytics.status.noComparison") : undefined} />
              {deltaText && (
                <span className={cn("flex items-center gap-1 font-medium", TONE_TEXT[tone])}>
                  {DirectionIcon && <DirectionIcon className="h-3.5 w-3.5" aria-hidden />}
                  {deltaText}
                </span>
              )}
            </div>
            {previousText ? <p className="text-muted-foreground">{previousText}</p> : <p className="text-muted-foreground">{t("analytics.kpi.noPrevious")}</p>}
            {driver && <p className="text-muted-foreground">{driver}</p>}
            {extra}
          </div>
        )}
      </Card>
    </motion.div>
  );
}
