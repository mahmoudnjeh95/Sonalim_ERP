import { motion, useReducedMotion } from "framer-motion";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { useI18n } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { AnalyticsEmptyState } from "../../analytics/AnalyticsStates";
import { fill, formatNumber } from "../../analytics/manufacturing/format";
import type { DefectRow } from "./qualityMetrics";
import QualityInspection from "../../../assets/illustrations/quality-inspection.svg?react";

const VITAL_FEW_PCT = 80;

/**
 * Rejected cartons by defect, largest first, with the running share: the
 * defects that together explain four fifths of the rejects are the ones worth
 * a corrective action, and they are marked so.
 */
export function DefectParetoPanel({ defects, className, limit = 8 }: { defects: DefectRow[]; className?: string; limit?: number }) {
  const { t } = useI18n();
  const reduceMotion = useReducedMotion();
  const rows = defects.slice(0, limit);
  const max = rows[0]?.cartons ?? 0;
  const vitalFew = rows.filter((row) => row.cumulativePct - row.sharePct < VITAL_FEW_PCT).length;

  return (
    <Card className={className}>
      <CardHeader>
        <div>
          <CardTitle>{t("qc.analytics.defects.title")}</CardTitle>
          <CardDescription>
            {rows.length > 0 && vitalFew > 0 ? fill(t("qc.analytics.defects.subtitleVital"), { count: String(vitalFew) }) : t("qc.analytics.defects.subtitle")}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="pt-2">
        {rows.length === 0 ? (
          <AnalyticsEmptyState illustration={QualityInspection} title={t("qc.analytics.defects.empty.title")} description={t("qc.analytics.defects.empty.description")} />
        ) : (
          <ol className="divide-y divide-border/60">
            {rows.map((row, index) => {
              const vital = index < vitalFew;
              return (
                <li key={row.defect} className="grid grid-cols-[1.5rem_minmax(0,1fr)_auto] items-center gap-x-3 py-2">
                  <span className={cn("text-xs font-semibold tabular-nums", vital ? "text-foreground" : "text-muted-foreground")}>{index + 1}</span>
                  <div className="min-w-0">
                    <p className="truncate text-sm text-foreground">{row.defect}</p>
                    <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-muted" aria-hidden>
                      <motion.div
                        className={cn("h-full rounded-full", vital ? "bg-primary" : "bg-primary/35")}
                        initial={{ width: reduceMotion ? `${(row.cartons / max) * 100}%` : 0 }}
                        animate={{ width: `${(row.cartons / max) * 100}%` }}
                        transition={{ duration: reduceMotion ? 0 : 0.45, delay: reduceMotion ? 0 : index * 0.04, ease: [0.2, 0.8, 0.2, 1] }}
                      />
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-semibold tabular-nums">{formatNumber(row.cartons, 0)}</p>
                    <p className="text-[11px] tabular-nums text-muted-foreground">
                      {formatNumber(row.sharePct, 0)}% · Σ {formatNumber(row.cumulativePct, 0)}%
                    </p>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
