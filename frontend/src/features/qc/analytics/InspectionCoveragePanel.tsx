import { motion, useReducedMotion } from "framer-motion";
import { Link } from "react-router-dom";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { fill, formatNumber } from "../../analytics/manufacturing/format";
import { REPORT_STATUSES, type LedgerSummary } from "./qualityMetrics";

/**
 * How far QC's paperwork has caught up with production: packing runs waiting
 * for a report, then reports by status. Reads left to right in the order a
 * report moves.
 */
export function InspectionCoveragePanel({ summary, awaiting, className }: { summary: LedgerSummary; awaiting: number; className?: string }) {
  const { t } = useI18n();
  const reduceMotion = useReducedMotion();
  const steps = [
    { key: "awaiting", label: t("qc.analytics.coverage.awaiting"), count: awaiting, tone: awaiting > 0 ? "bg-warning" : "bg-muted-foreground/30" },
    ...REPORT_STATUSES.map((status) => ({
      key: status,
      label: t(`status.${status}` as TranslationKey),
      count: summary.statusCounts[status],
      tone: status === "validated" ? "bg-success" : status === "rejected" ? "bg-destructive" : "bg-primary",
    })),
  ];
  const max = Math.max(1, ...steps.map((step) => step.count));
  const total = steps.reduce((sum, step) => sum + step.count, 0);

  return (
    <Card className={className}>
      <CardHeader>
        <div>
          <CardTitle>{t("qc.analytics.coverage.title")}</CardTitle>
          <CardDescription>{fill(t("qc.analytics.coverage.subtitle"), { validated: formatNumber(summary.statusCounts.validated, 0), total: formatNumber(total, 0) })}</CardDescription>
        </div>
        {awaiting > 0 && (
          <Link to="/quality?tab=reports" className="shrink-0 text-xs font-medium text-primary underline-offset-2 hover:underline">
            {t("production.board.quality.viewQc")}
          </Link>
        )}
      </CardHeader>
      <CardContent>
        <ol className="grid grid-cols-5 gap-2">
          {steps.map((step, index) => (
            <li key={step.key} className="min-w-0">
              <p className="truncate text-[11px] text-muted-foreground">{step.label}</p>
              <p className="text-lg font-semibold tabular-nums leading-tight">{formatNumber(step.count, 0)}</p>
              <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-muted" aria-hidden>
                <motion.div
                  className={cn("h-full rounded-full", step.tone)}
                  initial={{ width: reduceMotion ? `${(step.count / max) * 100}%` : 0 }}
                  animate={{ width: `${(step.count / max) * 100}%` }}
                  transition={{ duration: reduceMotion ? 0 : 0.45, delay: reduceMotion ? 0 : index * 0.05, ease: [0.2, 0.8, 0.2, 1] }}
                />
              </div>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
