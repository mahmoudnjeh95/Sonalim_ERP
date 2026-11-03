import { useState } from "react";
import { AnimatePresence, LayoutGroup, motion, useReducedMotion } from "framer-motion";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { AnalyticsEmptyState } from "../../analytics/AnalyticsStates";
import { fill, formatNumber, formatPercent } from "../../analytics/manufacturing/format";
import { QUALITY_DIMENSIONS, type BreakdownRow, type QualityDimension } from "./qualityMetrics";
import ShiftTeamIllustration from "../../../assets/illustrations/shift-team.svg?react";

// A slice is judged against the plant figure for the same window, the only
// benchmark the system holds: at or above it reads good, within a point below
// reads watch, further below reads attention.
function toneOf(pct: number | null, plantPct: number | null): "success" | "warning" | "destructive" | "muted" {
  if (pct === null || plantPct === null) return "muted";
  if (pct >= plantPct) return "success";
  return plantPct - pct < 1 ? "warning" : "destructive";
}

const FILL: Record<ReturnType<typeof toneOf>, string> = {
  success: "bg-success",
  warning: "bg-warning",
  destructive: "bg-destructive",
  muted: "bg-muted-foreground/40",
};
const TRACK: Record<ReturnType<typeof toneOf>, string> = {
  success: "bg-success-soft",
  warning: "bg-warning-soft",
  destructive: "bg-destructive-soft",
  muted: "bg-muted",
};

export function DimensionSwitch({
  value,
  onChange,
  options = QUALITY_DIMENSIONS,
  layoutId,
}: {
  value: QualityDimension;
  onChange: (value: QualityDimension) => void;
  options?: QualityDimension[];
  layoutId: string;
}) {
  const { t } = useI18n();
  return (
    <LayoutGroup id={layoutId}>
      <div role="tablist" className="inline-flex flex-wrap gap-1 rounded-lg border border-border bg-muted/40 p-1">
        {options.map((option) => {
          const active = option === value;
          return (
            <button
              key={option}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => onChange(option)}
              className={cn(
                "relative rounded-md px-3 py-1 text-xs font-medium transition-colors",
                active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {active && (
                <motion.span
                  layoutId={`${layoutId}-pill`}
                  className="absolute inset-0 rounded-md bg-background shadow-soft"
                  transition={{ type: "spring", stiffness: 500, damping: 40 }}
                />
              )}
              <span className="relative">{t(`qc.analytics.dimension.${option}` as TranslationKey)}</span>
            </button>
          );
        })}
      </div>
    </LayoutGroup>
  );
}

function BreakdownBar({ row, plantPct, floor, index }: { row: BreakdownRow; plantPct: number | null; floor: number; index: number }) {
  const { t } = useI18n();
  const reduceMotion = useReducedMotion();
  const tone = toneOf(row.conformityPct, plantPct);
  // Bars start at the shared floor, not at zero, so a 97% and a 99.5% slice look as far apart as they are.
  const width = row.conformityPct === null ? 0 : Math.max(2, ((row.conformityPct - floor) / (100 - floor)) * 100);

  return (
    <motion.li
      layout
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 8 }}
      transition={{ duration: 0.2, delay: reduceMotion ? 0 : index * 0.03 }}
      className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 py-2 sm:grid-cols-[minmax(7rem,12rem)_minmax(0,1fr)_auto]"
    >
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-foreground">{row.label}</p>
        <p className="truncate text-xs text-muted-foreground">
          {fill(t("qc.analytics.breakdown.rowMeta"), { inspected: formatNumber(row.inspected, 0), reports: formatNumber(row.reportCount, 0) })}
        </p>
      </div>
      <div className="col-span-2 sm:col-span-1">
        <div className={cn("h-2.5 w-full overflow-hidden rounded-full", TRACK[tone])} aria-hidden>
          <motion.div
            className={cn("h-full rounded-full", FILL[tone])}
            initial={{ width: reduceMotion ? `${width}%` : 0 }}
            animate={{ width: `${width}%` }}
            transition={{ duration: reduceMotion ? 0 : 0.5, ease: [0.2, 0.8, 0.2, 1] }}
          />
        </div>
        {row.topDefect && (
          <p className="mt-1 truncate text-[11px] text-muted-foreground">
            {fill(t("qc.analytics.breakdown.topDefect"), { defect: row.topDefect.label, cartons: formatNumber(row.topDefect.cartons, 0) })}
          </p>
        )}
      </div>
      <div className="text-right">
        <p className="text-sm font-semibold tabular-nums">{formatPercent(row.conformityPct)}</p>
        <p className="text-xs tabular-nums text-destructive">{fill(t("qc.analytics.breakdown.rejected"), { cartons: formatNumber(row.nonConforming, 0) })}</p>
      </div>
    </motion.li>
  );
}

/**
 * Validated conformity sliced by product, line, team, shift or order, lowest
 * first. One control above the list re-slices in place; the bars keep their
 * identity through the switch so the eye can follow a slice that stays.
 */
export function QualityBreakdownPanel({
  slices,
  plantPct,
  dimensions,
  initial = "product",
  className,
}: {
  slices: Record<QualityDimension, BreakdownRow[]>;
  plantPct: number | null;
  dimensions?: QualityDimension[];
  initial?: QualityDimension;
  className?: string;
}) {
  const { t } = useI18n();
  const [dimension, setDimension] = useState<QualityDimension>(initial);
  const rows = slices[dimension];
  const values = rows.map((row) => row.conformityPct).filter((value): value is number => value !== null);
  const floor = values.length ? Math.max(0, Math.floor(Math.min(...values) - 2)) : 0;

  return (
    <Card className={className}>
      <CardHeader className="flex-wrap">
        <div>
          <CardTitle>{t("qc.analytics.breakdown.title")}</CardTitle>
          <CardDescription>
            {plantPct === null ? t("qc.analytics.breakdown.subtitle") : fill(t("qc.analytics.breakdown.subtitlePlant"), { plant: formatPercent(plantPct) })}
          </CardDescription>
        </div>
        <DimensionSwitch value={dimension} onChange={setDimension} options={dimensions} layoutId="quality-breakdown" />
      </CardHeader>
      <CardContent className="pt-2">
        {rows.length === 0 ? (
          <AnalyticsEmptyState
            illustration={ShiftTeamIllustration}
            title={t("qc.analytics.breakdown.empty.title")}
            description={t("qc.analytics.breakdown.empty.description")}
          />
        ) : (
          <AnimatePresence mode="popLayout" initial={false}>
            <motion.ul key={dimension} className="divide-y divide-border/60" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}>
              {rows.map((row, index) => (
                <BreakdownBar key={row.key} row={row} plantPct={plantPct} floor={floor} index={index} />
              ))}
            </motion.ul>
          </AnimatePresence>
        )}
      </CardContent>
    </Card>
  );
}
