import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Button } from "../../components/ui/button";
import { useI18n } from "../../lib/i18n";
import { AnalyticsEmptyState } from "./AnalyticsStates";
import { ManufacturingInsightCard } from "./ManufacturingInsightCard";
import { fill } from "./manufacturing/format";
import type { Insight } from "./manufacturing/insights";
import QualityInspection from "../../assets/illustrations/quality-inspection.svg?react";

const VISIBLE = 3;

/**
 * The rules layer's output, most urgent first. Every card states the figures it
 * rests on and what to open next; a period with nothing worth flagging says so.
 */
export function ManufacturingRecommendationsPanel({
  insights,
  onDrilldown,
}: {
  insights: Insight[];
  onDrilldown: (insight: Insight) => void;
}) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? insights : insights.slice(0, VISIBLE);

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{t("analytics.insights.title")}</CardTitle>
          <CardDescription>{t("analytics.insights.subtitle")}</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {insights.length === 0 ? (
          <AnalyticsEmptyState
            illustration={QualityInspection}
            title={t("analytics.insights.empty.title")}
            description={t("analytics.insights.empty.description")}
          />
        ) : (
          <>
            {shown.map((insight, index) => (
              <ManufacturingInsightCard key={insight.id} insight={insight} index={index} onDrilldown={onDrilldown} />
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
