import { motion, useReducedMotion } from "framer-motion";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { AnalyticsEmptyState } from "../../analytics/AnalyticsStates";
import { formatNumber } from "../../analytics/manufacturing/format";
import type { DispositionSummaryRow, NcDisposition } from "../api";
import RecycleSvg from "../../../assets/icons/waste.svg?react";

const ORDER: NcDisposition[] = ["return_to_stock", "rework", "regrind", "dechet"];

function formatWeightKg(weightKg: number): string {
  if (weightKg >= 1000) return `${formatNumber(weightKg / 1000, 1)} t`;
  return `${formatNumber(weightKg, weightKg < 10 ? 1 : 0)} kg`;
}

/** Where rejected product ended up: recovered (back to stock, rework, regrind) or lost as déchet. */
export function RecoveryPanel({ rows, className }: { rows: DispositionSummaryRow[]; className?: string }) {
  const { t } = useI18n();
  const reduceMotion = useReducedMotion();
  const total = rows.reduce((sum, row) => sum + row.quantity, 0);
  const data = ORDER.flatMap((disposition) => {
    const row = rows.find((entry) => entry.disposition === disposition);
    return row ? [{ disposition, quantity: row.quantity, weightKg: row.weight_kg, sharePct: total > 0 ? (row.quantity / total) * 100 : 0 }] : [];
  });
  const recovered = data.filter((row) => row.disposition !== "dechet").reduce((sum, row) => sum + row.sharePct, 0);

  return (
    <Card className={className}>
      <CardHeader>
        <div>
          <CardTitle>{t("qc.dashboard.chart.recovery.title")}</CardTitle>
          <CardDescription>{t("qc.dashboard.chart.recovery.description")}</CardDescription>
        </div>
        {data.length > 0 && (
          <p className="shrink-0 text-right">
            <span className="block text-lg font-semibold tabular-nums leading-tight text-success">{formatNumber(recovered, 0)}%</span>
            <span className="text-[11px] text-muted-foreground">{t("qc.analytics.recovery.recovered")}</span>
          </p>
        )}
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <AnalyticsEmptyState iconOnly illustration={RecycleSvg} title={t("qc.dashboard.chart.recovery.empty.title")} description={t("qc.dashboard.chart.recovery.empty.description")} />
        ) : (
          <>
            <div className="flex h-3 w-full gap-0.5 overflow-hidden rounded-full" aria-hidden>
              {data.map((row, index) => (
                <motion.div
                  key={row.disposition}
                  className={cn("h-full", row.disposition === "dechet" ? "bg-destructive" : "bg-success", row.disposition !== "dechet" && index > 0 && "opacity-80")}
                  initial={{ flexBasis: reduceMotion ? `${row.sharePct}%` : 0 }}
                  animate={{ flexBasis: `${row.sharePct}%` }}
                  transition={{ duration: reduceMotion ? 0 : 0.5, ease: [0.2, 0.8, 0.2, 1] }}
                />
              ))}
            </div>
            <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
              {data.map((row) => (
                <li key={row.disposition} className="flex items-start gap-2">
                  <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", row.disposition === "dechet" ? "bg-destructive" : "bg-success")} aria-hidden />
                  <div className="min-w-0">
                    <p className="truncate text-xs text-muted-foreground">{t(`qc.nc.disposition.${row.disposition}` as TranslationKey)}</p>
                    <p className="text-sm font-semibold tabular-nums">
                      {formatNumber(row.sharePct, 0)}%
                      {row.weightKg !== null && <span className="ml-1 text-xs font-normal text-muted-foreground">{formatWeightKg(row.weightKg)}</span>}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}
