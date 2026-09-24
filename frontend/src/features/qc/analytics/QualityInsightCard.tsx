import { useState } from "react";
import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { outlineIcon } from "../../../components/patterns/outlineIcon";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { AnalyticsEmptyState } from "../../analytics/AnalyticsStates";
import { AnalyticsStatusBadge, TONE_BORDER } from "../../analytics/AnalyticsStatusBadge";
import { fill } from "../../analytics/manufacturing/format";
import type { QualityInsight, QualityInsightKind } from "./qualityInsights";
import ApprovalSvg from "../../../assets/icons/quality/approval.svg?react";
import HoldSvg from "../../../assets/icons/quality/hold.svg?react";
import InspectionSvg from "../../../assets/icons/quality/inspection.svg?react";
import NonconformitySvg from "../../../assets/icons/quality/nonconformity.svg?react";
import RootCauseSvg from "../../../assets/icons/quality/root_cause.svg?react";
import SampleSvg from "../../../assets/icons/quality/sample.svg?react";
import SpecificationSvg from "../../../assets/icons/quality/specification.svg?react";
import TraceabilitySvg from "../../../assets/icons/quality/traceability.svg?react";
import QualityInspection from "../../../assets/illustrations/quality-inspection.svg?react";

const KIND_ICON: Record<QualityInsightKind, ReturnType<typeof outlineIcon>> = {
  conformityDrift: outlineIcon(SpecificationSvg),
  worstProduct: outlineIcon(SampleSvg),
  worstTeam: outlineIcon(InspectionSvg),
  worstShift: outlineIcon(InspectionSvg),
  topDefect: outlineIcon(RootCauseSvg),
  ncBacklog: outlineIcon(NonconformitySvg),
  followUpsDue: outlineIcon(TraceabilitySvg),
  awaitingInspection: outlineIcon(HoldSvg),
  rejectsWithoutCase: outlineIcon(NonconformitySvg),
  steady: outlineIcon(ApprovalSvg),
};

export function QualityInsightCard({
  insight,
  index = 0,
  onDrilldown,
}: {
  insight: QualityInsight;
  index?: number;
  onDrilldown: (insight: QualityInsight) => void;
}) {
  const { t } = useI18n();
  const Icon = KIND_ICON[insight.kind];
  const text = (entry: { key: TranslationKey; vars: Record<string, string> }) => fill(t(entry.key), entry.vars);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -6 }}
      transition={{ duration: 0.22, delay: index * 0.05 }}
    >
      <Card className={cn("space-y-3 border-l-4 p-4", TONE_BORDER[insight.tone])}>
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
              <Icon aria-hidden className="h-5 w-5" />
            </span>
            <div className="min-w-0">
              <p className="text-sm font-medium leading-tight">{t(`qc.analytics.insight.${insight.kind}.title` as TranslationKey)}</p>
              <p className="truncate text-lg font-semibold leading-tight">{insight.value}</p>
            </div>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <AnalyticsStatusBadge tone={insight.tone} />
            {insight.variance && <span className="text-xs font-medium tabular-nums text-muted-foreground">{insight.variance}</span>}
          </div>
        </div>

        <p className="text-sm text-foreground">{text(insight.explanation)}</p>
        <p className="text-xs text-muted-foreground">{text(insight.basis)}</p>

        <div className="flex items-end justify-between gap-3 border-t border-border pt-3">
          <p className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">{t("analytics.insight.recommended")}</span> {text(insight.action)}
          </p>
          <Button type="button" variant="ghost" size="sm" className="h-7 shrink-0 gap-1 px-2 text-xs" onClick={() => onDrilldown(insight)}>
            {t("analytics.insight.drilldown")}
            <ArrowRight className="h-3.5 w-3.5" aria-hidden />
          </Button>
        </div>
      </Card>
    </motion.div>
  );
}

const VISIBLE = 3;

/** The rules layer's output, most urgent first; a window with nothing worth flagging says so. */
export function QualityInsightsPanel({
  insights,
  onDrilldown,
  className,
}: {
  insights: QualityInsight[];
  onDrilldown: (insight: QualityInsight) => void;
  className?: string;
}) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? insights : insights.slice(0, VISIBLE);

  return (
    <Card className={className}>
      <CardHeader>
        <div>
          <CardTitle>{t("qc.analytics.insights.title")}</CardTitle>
          <CardDescription>{t("qc.analytics.insights.subtitle")}</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {insights.length === 0 ? (
          <AnalyticsEmptyState
            illustration={QualityInspection}
            title={t("qc.analytics.insights.empty.title")}
            description={t("qc.analytics.insights.empty.description")}
          />
        ) : (
          <>
            {shown.map((insight, index) => (
              <QualityInsightCard key={insight.id} insight={insight} index={index} onDrilldown={onDrilldown} />
            ))}
            {insights.length > VISIBLE && (
              <Button type="button" variant="ghost" size="sm" className="w-full text-xs" onClick={() => setExpanded((value) => !value)}>
                {expanded ? t("analytics.insights.showLess") : fill(t("analytics.insights.showAll"), { count: String(insights.length) })}
              </Button>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
