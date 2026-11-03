import { motion, useReducedMotion } from "framer-motion";
import { AlertTriangle, CheckCircle2, ShieldAlert } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { AnalyticsEmptyState } from "../../analytics/AnalyticsStates";
import { fill, formatNumber } from "../../analytics/manufacturing/format";
import type { NonConformitySeverity } from "../api";
import { NC_SEVERITIES, NC_STATUSES, type NonConformitySummary } from "./qualityMetrics";
import EmptyAllClear from "../../../assets/illustrations/empty-states/empty-all-clear.svg?react";

// Status is always icon + label + colour, so it survives colour-blindness and print.
const SEVERITY: Record<NonConformitySeverity, { icon: typeof AlertTriangle; className: string }> = {
  minor: { icon: CheckCircle2, className: "border-warning/20 bg-warning-soft text-warning" },
  major: { icon: AlertTriangle, className: "border-warning/30 bg-warning-soft text-warning" },
  critical: { icon: ShieldAlert, className: "border-destructive/20 bg-destructive-soft text-destructive" },
};

/**
 * Where every non-conformity sits on its way from raised to closed, read left
 * to right. The open ones are the backlog; how long the oldest has waited says
 * whether the backlog is moving.
 */
export function NcPipelinePanel({ summary, className }: { summary: NonConformitySummary; className?: string }) {
  const { t } = useI18n();
  const reduceMotion = useReducedMotion();
  const max = Math.max(1, ...NC_STATUSES.map((status) => summary.byStatus[status]));

  return (
    <Card className={className}>
      <CardHeader>
        <div>
          <CardTitle>{t("qc.analytics.nc.title")}</CardTitle>
          <CardDescription>
            {summary.open === 0
              ? t("qc.analytics.nc.subtitleClear")
              : fill(t("qc.analytics.nc.subtitle"), {
                  open: formatNumber(summary.open, 0),
                  oldest: summary.oldestOpenDays === null ? "—" : formatNumber(summary.oldestOpenDays, 0),
                })}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {summary.total === 0 ? (
          <AnalyticsEmptyState illustration={EmptyAllClear} title={t("qc.analytics.nc.empty.title")} description={t("qc.analytics.nc.empty.description")} />
        ) : (
          <>
            <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {NC_STATUSES.map((status, index) => {
                const count = summary.byStatus[status];
                const closed = status === "closed";
                return (
                  <li key={status} className="rounded-lg border border-border bg-muted/30 p-3">
                    <p className="text-xs text-muted-foreground">{t(`status.${status}` as TranslationKey)}</p>
                    <p className="mt-0.5 text-xl font-semibold tabular-nums tracking-tight">{formatNumber(count, 0)}</p>
                    <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted" aria-hidden>
                      <motion.div
                        className={cn("h-full rounded-full", closed ? "bg-success" : "bg-primary")}
                        initial={{ width: reduceMotion ? `${(count / max) * 100}%` : 0 }}
                        animate={{ width: `${(count / max) * 100}%` }}
                        transition={{ duration: reduceMotion ? 0 : 0.45, delay: reduceMotion ? 0 : index * 0.06, ease: [0.2, 0.8, 0.2, 1] }}
                      />
                    </div>
                  </li>
                );
              })}
            </ol>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted-foreground">{t("qc.analytics.nc.bySeverity")}</span>
              {NC_SEVERITIES.map((severity) => {
                const { icon: Icon, className: tone } = SEVERITY[severity];
                return (
                  <span key={severity} className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium", tone)}>
                    <Icon className="h-3 w-3" aria-hidden />
                    {t(`qc.dashboard.severity.${severity}` as TranslationKey)}
                    <span className="tabular-nums">{formatNumber(summary.bySeverity[severity], 0)}</span>
                  </span>
                );
              })}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
