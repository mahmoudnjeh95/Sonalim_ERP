import { ChevronDown } from "lucide-react";
import { Card } from "../../components/ui/card";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import type { SvgComponent } from "./AnalyticsStates";
import BatchTraceability from "../../assets/illustrations/batch-traceability.svg?react";
import ProductionCost from "../../assets/illustrations/production-cost.svg?react";
import ProductionDelay from "../../assets/illustrations/production-delay.svg?react";
import QualityInspection from "../../assets/illustrations/quality-inspection.svg?react";
import YieldWaste from "../../assets/illustrations/yield-waste.svg?react";

const ITEMS: { key: string; illustration: SvgComponent; title: TranslationKey; reason: TranslationKey }[] = [
  { key: "delay", illustration: ProductionDelay, title: "analytics.coverage.delay.title", reason: "analytics.coverage.delay.reason" },
  { key: "cost", illustration: ProductionCost, title: "analytics.coverage.cost.title", reason: "analytics.coverage.cost.reason" },
  { key: "waste", illustration: YieldWaste, title: "analytics.coverage.waste.title", reason: "analytics.coverage.waste.reason" },
  { key: "targets", illustration: QualityInspection, title: "analytics.coverage.targets.title", reason: "analytics.coverage.targets.reason" },
  { key: "batch", illustration: BatchTraceability, title: "analytics.coverage.batch.title", reason: "analytics.coverage.batch.reason" },
];

/**
 * What this view deliberately does not show, and the missing input behind each.
 * Collapsed by default: it is documentation of gaps, not part of the daily read.
 */
export function DataCoveragePanel() {
  const { t } = useI18n();
  return (
    <Card>
      <details className="group">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 [&::-webkit-details-marker]:hidden">
          <span>
            <span className="block text-base font-semibold tracking-tight">{t("analytics.coverage.title")}</span>
            <span className="block text-sm text-muted-foreground">{t("analytics.coverage.subtitle")}</span>
          </span>
          <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" aria-hidden />
        </summary>
        <ul className="grid grid-cols-1 gap-4 border-t border-border p-5 sm:grid-cols-2">
          {ITEMS.map(({ key, illustration: Illustration, title, reason }) => (
            <li key={key} className="flex items-start gap-3">
              <Illustration aria-hidden className="h-auto w-28 shrink-0" />
              <div className="space-y-1">
                <p className="text-sm font-medium">{t(title)}</p>
                <p className="text-xs text-muted-foreground">{t(reason)}</p>
              </div>
            </li>
          ))}
        </ul>
      </details>
    </Card>
  );
}
