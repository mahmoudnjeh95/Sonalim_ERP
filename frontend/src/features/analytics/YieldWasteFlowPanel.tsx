import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { useI18n } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { AnalyticsEmptyState } from "./AnalyticsStates";
import { TONE_TEXT } from "./AnalyticsStatusBadge";
import { fill, formatNumber, formatPercent } from "./manufacturing/format";
import type { Formatters } from "./manufacturing/insights";
import { compareRatio, rankWasteStages, type OperationsSummary } from "./manufacturing/metrics";
import YieldWasteIllustration from "../../assets/illustrations/yield-waste.svg?react";

function FlowStep({ label, value, note, noteClassName }: { label: string; value: string; note?: string; noteClassName?: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-muted/30 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 whitespace-nowrap text-xl font-semibold tabular-nums tracking-tight">{value}</p>
      {note && <p className={cn("mt-1 text-xs", noteClassName ?? "text-muted-foreground")}>{note}</p>}
    </div>
  );
}

/**
 * Material poured → finished pasta → declared waste, on the units the reports
 * record them in. Tonnes (poured, produced) and kilograms (declared waste) are
 * kept apart on purpose: no waste percentage is computed across them.
 */
export function YieldWasteFlowPanel({
  current,
  previous,
  fmt,
  showIllustration = true,
}: {
  current: OperationsSummary;
  previous: OperationsSummary;
  fmt: Formatters;
  showIllustration?: boolean;
}) {
  const { t } = useI18n();
  const { totals } = current;
  const stages = rankWasteStages(totals);
  const declaredKg = stages.reduce((sum, stage) => sum + stage.kg, 0);
  const yieldComparison = compareRatio(current.yieldPct, previous.yieldPct, true);
  const hasData = totals.materialInput > 0 || declaredKg > 0;

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{t("analytics.yieldWaste.title")}</CardTitle>
          <CardDescription>{t("analytics.yieldWaste.subtitle")}</CardDescription>
        </div>
        {showIllustration && hasData && <YieldWasteIllustration aria-hidden className="hidden h-auto w-24 shrink-0 md:block" />}
      </CardHeader>
      <CardContent className="space-y-5">
        {!hasData ? (
          <AnalyticsEmptyState
            illustration={YieldWasteIllustration}
            title={t("analytics.yieldWaste.empty.title")}
            description={t("analytics.yieldWaste.empty.description")}
          />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <FlowStep label={t("analytics.yieldWaste.step.poured")} value={fmt.tonnes(totals.materialInput)} />
              <FlowStep
                label={t("analytics.yieldWaste.step.produced")}
                value={fmt.tonnes(totals.produced)}
                note={
                  current.yieldPct === null
                    ? undefined
                    : fill(t("analytics.yieldWaste.step.yield"), {
                        yield: formatPercent(current.yieldPct),
                        delta: yieldComparison.delta === null ? "" : ` (${yieldComparison.delta > 0 ? "+" : yieldComparison.delta < 0 ? "−" : ""}${formatNumber(Math.abs(yieldComparison.delta), 1)} pp)`,
                      })
                }
                noteClassName={TONE_TEXT[yieldComparison.tone]}
              />
              <FlowStep
                label={t("analytics.yieldWaste.step.declared")}
                value={fmt.kg(declaredKg)}
                note={fill(t("analytics.yieldWaste.step.recovered"), { kg: fmt.kg(totals.regrindKg) })}
              />
              <FlowStep label={t("analytics.yieldWaste.step.net")} value={fmt.kg(totals.netWasteKg)} />
            </div>

            {stages.length > 0 && (
              <div className="space-y-2">
                <p className="text-sm font-medium">{t("analytics.yieldWaste.stages.title")}</p>
                <ul className="space-y-2">
                  {stages.map((stage) => (
                    <li key={stage.stage} className="grid grid-cols-[minmax(0,11rem)_1fr_auto] items-center gap-3 text-sm">
                      <span className="text-muted-foreground">{fmt.stage(stage.stage)}</span>
                      <span className="h-2 overflow-hidden rounded-full bg-muted" role="presentation">
                        <span className="block h-full rounded-full bg-primary" style={{ width: `${stage.sharePct}%` }} />
                      </span>
                      <span className="tabular-nums">
                        {fmt.kg(stage.kg)} <span className="text-xs text-muted-foreground">· {formatNumber(stage.sharePct, 0)}%</span>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <p className="text-xs text-muted-foreground">{t("analytics.yieldWaste.unitsNote")}</p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
