import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { Button } from "../../components/ui/button";
import { Card } from "../../components/ui/card";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { AnalyticsStatusBadge, TONE_BORDER } from "./AnalyticsStatusBadge";
import type { SvgComponent } from "./AnalyticsStates";
import { useInsightText } from "./manufacturing/format";
import type { Insight, InsightKind } from "./manufacturing/insights";
import CostIcon from "../../assets/icons/cost.svg?react";
import MachineIcon from "../../assets/icons/machine.svg?react";
import ProductionIcon from "../../assets/icons/production.svg?react";
import QualityIcon from "../../assets/icons/quality.svg?react";
import ShiftIcon from "../../assets/icons/shift.svg?react";
import WasteIcon from "../../assets/icons/waste.svg?react";
import YieldIcon from "../../assets/icons/yield.svg?react";

const KIND_ICON: Record<InsightKind, SvgComponent> = {
  productionGap: ProductionIcon,
  yieldDrift: YieldIcon,
  highestWasteStage: WasteIcon,
  highestDowntimeMachine: MachineIcon,
  qualityDrift: QualityIcon,
  bestTeam: ShiftIcon,
  costVariance: CostIcon,
};

export function ManufacturingInsightCard({
  insight,
  index = 0,
  onDrilldown,
}: {
  insight: Insight;
  index?: number;
  onDrilldown: (insight: Insight) => void;
}) {
  const { t } = useI18n();
  const text = useInsightText();
  const Icon = KIND_ICON[insight.kind];

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.22, delay: index * 0.05 }}>
      <Card className={cn("space-y-3 border-l-4 p-4", TONE_BORDER[insight.tone])}>
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted">
              <Icon aria-hidden className="h-5 w-5" />
            </span>
            <div>
              <p className="flex items-center gap-1.5 text-sm font-medium leading-tight">
                {t(`analytics.insight.${insight.kind}.title` as TranslationKey)}
              </p>
              <p className="text-lg font-semibold tabular-nums leading-tight">{insight.value}</p>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1">
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
