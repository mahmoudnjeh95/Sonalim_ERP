import { useCallback, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { useI18n } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { AnalyticsEmptyState, AnalyticsErrorState, AnalyticsLoadingState } from "../analytics/AnalyticsStates";
import { PeriodFilter, type PeriodDays } from "../analytics/PeriodFilter";
import { ProductionKpiCard } from "../analytics/ProductionKpiCard";
import { fill, formatNumber, formatPercent } from "../analytics/manufacturing/format";
import { compareQuantity, compareRatio, type Comparison } from "../analytics/manufacturing/metrics";
import { useMinimumLoading } from "../analytics/useMinimumLoading";
import { ConformityTrendChart } from "./analytics/ConformityTrendChart";
import { DefectParetoPanel } from "./analytics/DefectParetoPanel";
import { InspectionCoveragePanel } from "./analytics/InspectionCoveragePanel";
import { NcPipelinePanel } from "./analytics/NcPipelinePanel";
import { QualityBreakdownPanel } from "./analytics/QualityBreakdownPanel";
import { QualityInsightsPanel } from "./analytics/QualityInsightCard";
import { RecoveryPanel } from "./analytics/RecoveryPanel";
import type { QualityInsight } from "./analytics/qualityInsights";
import { useQualityAnalytics } from "./analytics/useQualityAnalytics";
import EmptyQualityIllustration from "../../assets/illustrations/empty-states/empty-no-quality.svg?react";
import QualityInspectionIllustration from "../../assets/illustrations/quality-inspection.svg?react";
import ApprovalIcon from "../../assets/icons/quality/approval.svg?react";
import InspectionIcon from "../../assets/icons/quality/inspection.svg?react";
import NonconformityIcon from "../../assets/icons/quality/nonconformity.svg?react";
import SampleIcon from "../../assets/icons/quality/sample.svg?react";
import TraceabilityIcon from "../../assets/icons/quality/traceability.svg?react";

function signed(value: number, digits: number): string {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${formatNumber(Math.abs(value), digits)}`;
}

function deltaText(comparison: Comparison): string | null {
  if (comparison.delta === null) return null;
  return comparison.kind === "points" ? `${signed(comparison.delta, 1)} pp` : `${signed(comparison.delta, 1)}%`;
}

/**
 * Quality at a glance for the last N days against the equal window before it:
 * what was inspected, what was rejected and why, where the non-conformities
 * stand, and what the rules layer thinks deserves attention next.
 */
export function QualityDashboardTab() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [, setSearchParams] = useSearchParams();
  const [days, setDays] = useState<PeriodDays>(30);
  const analytics = useQualityAnalytics(days, { withBacklog: true });
  const { windows, sources, summary, previousSummary, trend, slices, ncSummary, followUpSummary, dispositionRows, awaitingCount, insights } = analytics;
  const showLoader = useMinimumLoading(sources.ledgerCurrent.isLoading);

  const openDrilldown = useCallback(
    (insight: QualityInsight) => {
      if ("tab" in insight.drilldown) setSearchParams({ tab: insight.drilldown.tab });
      else navigate(insight.drilldown.href);
    },
    [navigate, setSearchParams],
  );

  const header = <PeriodFilter days={days} onChange={setDays} windows={windows} />;

  if (showLoader) {
    return (
      <div className="space-y-5">
        {header}
        <AnalyticsLoadingState label={t("qc.analytics.state.loading")} />
      </div>
    );
  }
  if (sources.ledgerCurrent.isError) {
    return (
      <div className="space-y-5">
        {header}
        <Card>
          <AnalyticsErrorState title={t("qc.analytics.error.title")} impact={t("qc.analytics.error.impact")} onRetry={() => sources.ledgerCurrent.refetch()} />
        </Card>
      </div>
    );
  }

  const nothingYet = summary.totals.reportCount === 0 && summary.statusCounts.draft + summary.statusCounts.submitted + summary.statusCounts.rejected === 0 && ncSummary.total === 0 && awaitingCount === 0;
  if (nothingYet) {
    return (
      <div className="space-y-5">
        {header}
        <Card>
          <AnalyticsEmptyState illustration={EmptyQualityIllustration} iconOnly title={t("qc.dashboard.empty.title")} description={t("qc.dashboard.empty.description")} />
        </Card>
      </div>
    );
  }

  const previousOk = !sources.ledgerPrevious.isError && previousSummary !== null && previousSummary.totals.inspected > 0;
  const conformity = compareRatio(summary.totals.conformityPct, previousOk ? previousSummary.totals.conformityPct : null, true);
  const inspected = { ...compareQuantity(summary.totals.inspected, previousOk ? previousSummary.totals.inspected : null, true), tone: "neutral" as const };
  const rejected = compareQuantity(summary.totals.nonConforming, previousOk ? previousSummary.totals.nonConforming : null, false);
  const previousLabel = t("analytics.kpi.previous");
  const worstProduct = slices.product.find((row) => row.conformityPct !== null);
  const topDefect = summary.defects[0];
  const followUpsDue = followUpSummary.overdue + followUpSummary.dueSoon;

  return (
    <div className="space-y-5">
      {header}

      <div className={cn("space-y-5 transition-opacity duration-200", sources.ledgerCurrent.isPlaceholderData && "opacity-60")} aria-busy={sources.ledgerCurrent.isPlaceholderData}>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-5">
          <ProductionKpiCard
            index={0}
            icon={ApprovalIcon}
            label={t("qc.analytics.kpi.conformity")}
            value={summary.totals.conformityPct}
            format={(value) => `${formatNumber(value, 1)}%`}
            comparison={conformity}
            deltaText={deltaText(conformity)}
            previousText={conformity.delta === null ? null : `${previousLabel} ${formatPercent(previousSummary?.totals.conformityPct ?? null)}`}
            driver={worstProduct && slices.product.length > 1 ? fill(t("qc.analytics.kpi.conformity.driver"), { name: worstProduct.label, pct: formatPercent(worstProduct.conformityPct) }) : null}
            unavailable={t("qc.analytics.kpi.conformity.none")}
          />
          <ProductionKpiCard
            index={1}
            icon={InspectionIcon}
            label={t("qc.analytics.kpi.inspected")}
            value={summary.totals.reportCount > 0 ? summary.totals.inspected : null}
            format={(value) => formatNumber(value, 0)}
            comparison={inspected}
            deltaText={deltaText(inspected)}
            previousText={inspected.delta === null ? null : `${previousLabel} ${formatNumber(previousSummary?.totals.inspected ?? 0, 0)}`}
            driver={fill(t("qc.analytics.kpi.inspected.driver"), { reports: formatNumber(summary.totals.reportCount, 0) })}
            unavailable={t("qc.analytics.kpi.conformity.none")}
          />
          <ProductionKpiCard
            index={2}
            icon={SampleIcon}
            label={t("qc.analytics.kpi.rejected")}
            value={summary.totals.reportCount > 0 ? summary.totals.nonConforming : null}
            format={(value) => formatNumber(value, 0)}
            comparison={rejected}
            deltaText={deltaText(rejected)}
            previousText={rejected.delta === null ? null : `${previousLabel} ${formatNumber(previousSummary?.totals.nonConforming ?? 0, 0)}`}
            driver={topDefect ? fill(t("qc.analytics.kpi.rejected.driver"), { defect: topDefect.defect, share: formatNumber(topDefect.sharePct, 0) }) : null}
            unavailable={t("qc.analytics.kpi.conformity.none")}
          />
          <ProductionKpiCard
            index={3}
            icon={NonconformityIcon}
            label={t("qc.analytics.kpi.openNc")}
            value={sources.nonConformities.isError ? null : ncSummary.open}
            format={(value) => formatNumber(value, 0)}
            comparison={null}
            deltaText={null}
            previousText={
              ncSummary.open === 0
                ? t("qc.analytics.kpi.openNc.clear")
                : fill(t("qc.analytics.kpi.openNc.previous"), { critical: formatNumber(ncSummary.bySeverity.critical, 0), major: formatNumber(ncSummary.bySeverity.major, 0) })
            }
            driver={ncSummary.oldestOpenDays !== null ? fill(t("qc.analytics.kpi.openNc.driver"), { days: formatNumber(ncSummary.oldestOpenDays, 0), reference: ncSummary.oldestOpen?.reference ?? "" }) : null}
            unavailable={t("qc.analytics.kpi.openNc.error")}
          />
          <ProductionKpiCard
            index={4}
            icon={TraceabilityIcon}
            label={t("qc.analytics.kpi.followUps")}
            value={sources.followUps.isError ? null : followUpsDue}
            format={(value) => formatNumber(value, 0)}
            comparison={null}
            deltaText={null}
            previousText={fill(t("qc.analytics.kpi.followUps.previous"), { open: formatNumber(followUpSummary.open, 0) })}
            driver={followUpSummary.overdue > 0 ? fill(t("qc.analytics.kpi.followUps.driver"), { overdue: formatNumber(followUpSummary.overdue, 0) }) : null}
            unavailable={t("qc.analytics.kpi.followUps.error")}
          />
        </div>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>{t("qc.dashboard.chart.conformityTrend.title")}</CardTitle>
                <CardDescription>{fill(t("qc.analytics.trend.subtitle"), { days: String(days) })}</CardDescription>
              </div>
              {summary.totals.conformityPct !== null && (
                <p className="shrink-0 text-right">
                  <span className="block text-lg font-semibold leading-tight">{formatPercent(summary.totals.conformityPct)}</span>
                  <span className="text-[11px] text-muted-foreground">{t("qc.analytics.trend.windowAverage")}</span>
                </p>
              )}
            </CardHeader>
            <CardContent>
              {summary.byDay.length === 0 ? (
                <AnalyticsEmptyState illustration={QualityInspectionIllustration} title={t("qc.analytics.trend.empty.title")} description={t("qc.analytics.trend.empty.description")} />
              ) : (
                <ConformityTrendChart trend={trend} />
              )}
            </CardContent>
          </Card>

          <div className="xl:col-start-2 xl:row-span-2 xl:row-start-1">
            <QualityInsightsPanel insights={insights} onDrilldown={openDrilldown} className="h-full" />
          </div>

          <QualityBreakdownPanel slices={slices} plantPct={summary.totals.conformityPct} />
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <DefectParetoPanel defects={summary.defects} />
          <NcPipelinePanel summary={ncSummary} />
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <InspectionCoveragePanel summary={summary} awaiting={awaitingCount} />
          <RecoveryPanel rows={dispositionRows} />
        </div>

      </div>
    </div>
  );
}
