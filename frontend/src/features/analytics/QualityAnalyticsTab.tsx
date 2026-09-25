import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { useI18n } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { ConformityTrendChart } from "../qc/analytics/ConformityTrendChart";
import { DefectParetoPanel } from "../qc/analytics/DefectParetoPanel";
import { QualityBreakdownPanel } from "../qc/analytics/QualityBreakdownPanel";
import { QualityInsightsPanel } from "../qc/analytics/QualityInsightCard";
import type { QualityInsight } from "../qc/analytics/qualityInsights";
import { useQualityAnalytics } from "../qc/analytics/useQualityAnalytics";
import { AnalyticsEmptyState, AnalyticsErrorState, AnalyticsInlineError, AnalyticsLoadingState } from "./AnalyticsStates";
import { PeriodFilter, type PeriodDays } from "./PeriodFilter";
import { ProductionKpiCard } from "./ProductionKpiCard";
import { fill, formatNumber, formatPercent } from "./manufacturing/format";
import { compareQuantity, compareRatio, type Comparison } from "./manufacturing/metrics";
import { useOperationsData } from "./manufacturing/useManufacturingOverview";
import { useMinimumLoading } from "./useMinimumLoading";
import QualityIcon from "../../assets/icons/quality.svg?react";
import InspectionIcon from "../../assets/icons/quality/inspection.svg?react";
import NonconformityIcon from "../../assets/icons/quality/nonconformity.svg?react";
import SampleIcon from "../../assets/icons/quality/sample.svg?react";
import QualityInspectionIllustration from "../../assets/illustrations/quality-inspection.svg?react";
import ShiftTeamIllustration from "../../assets/illustrations/shift-team.svg?react";

function signed(value: number, digits: number): string {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${formatNumber(Math.abs(value), digits)}`;
}

function deltaText(comparison: Comparison): string | null {
  if (comparison.delta === null) return null;
  return comparison.kind === "points" ? `${signed(comparison.delta, 1)} pp` : `${signed(comparison.delta, 1)}%`;
}

/**
 * Quality read across modules: QC's verdicts sliced by the production line,
 * product, team and shift that packed the cartons, and set beside each team's
 * output and yield -- the "is quality stable, and where not" question the
 * Overview only answers with one number.
 */
export function QualityAnalyticsTab() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [days, setDays] = useState<PeriodDays>(30);
  const quality = useQualityAnalytics(days);
  const operations = useOperationsData(days);
  const { windows, sources, summary, previousSummary, trend, slices, ncSummary, insights } = quality;
  const showLoader = useMinimumLoading(sources.ledgerCurrent.isLoading);

  const openDrilldown = useCallback(
    (insight: QualityInsight) => {
      if ("tab" in insight.drilldown) navigate(`/quality?tab=${insight.drilldown.tab}`);
      else navigate(insight.drilldown.href);
    },
    [navigate],
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
  if (summary.totals.reportCount === 0) {
    return (
      <div className="space-y-5">
        {header}
        <Card>
          <AnalyticsEmptyState illustration={QualityInspectionIllustration} title={t("qc.analytics.trend.empty.title")} description={t("qc.analytics.trend.empty.description")} />
        </Card>
      </div>
    );
  }

  const previousOk = !sources.ledgerPrevious.isError && previousSummary !== null && previousSummary.totals.inspected > 0;
  const conformity = compareRatio(summary.totals.conformityPct, previousOk ? previousSummary.totals.conformityPct : null, true);
  const inspected = { ...compareQuantity(summary.totals.inspected, previousOk ? previousSummary.totals.inspected : null, true), tone: "neutral" as const };
  const rejected = compareQuantity(summary.totals.nonConforming, previousOk ? previousSummary.totals.nonConforming : null, false);
  const previousLabel = t("analytics.kpi.previous");
  const worstLine = slices.line.find((row) => row.conformityPct !== null);
  const topDefect = summary.defects[0];
  const conformityByTeam = new Map(slices.team.map((row) => [row.key, row]));
  const teams = operations.ops.byTeam;

  return (
    <div className="space-y-5">
      {header}

      <div className={cn("space-y-5 transition-opacity duration-200", sources.ledgerCurrent.isPlaceholderData && "opacity-60")} aria-busy={sources.ledgerCurrent.isPlaceholderData}>
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
          <ProductionKpiCard
            index={0}
            icon={QualityIcon}
            label={t("qc.analytics.kpi.conformity")}
            value={summary.totals.conformityPct}
            format={(value) => `${formatNumber(value, 1)}%`}
            comparison={conformity}
            deltaText={deltaText(conformity)}
            previousText={conformity.delta === null ? null : `${previousLabel} ${formatPercent(previousSummary?.totals.conformityPct ?? null)}`}
            driver={worstLine && slices.line.length > 1 ? fill(t("qc.analytics.kpi.conformity.driverLine"), { name: worstLine.label, pct: formatPercent(worstLine.conformityPct) }) : null}
            unavailable={t("qc.analytics.kpi.conformity.none")}
          />
          <ProductionKpiCard
            index={1}
            icon={InspectionIcon}
            label={t("qc.analytics.kpi.inspected")}
            value={summary.totals.inspected}
            format={(value) => formatNumber(value, 0)}
            comparison={inspected}
            deltaText={deltaText(inspected)}
            previousText={inspected.delta === null ? null : `${previousLabel} ${formatNumber(previousSummary?.totals.inspected ?? 0, 0)}`}
            driver={fill(t("qc.analytics.kpi.inspected.driver"), { reports: formatNumber(summary.totals.reportCount, 0) })}
            unavailable={null}
          />
          <ProductionKpiCard
            index={2}
            icon={SampleIcon}
            label={t("qc.analytics.kpi.rejected")}
            value={summary.totals.nonConforming}
            format={(value) => formatNumber(value, 0)}
            comparison={rejected}
            deltaText={deltaText(rejected)}
            previousText={rejected.delta === null ? null : `${previousLabel} ${formatNumber(previousSummary?.totals.nonConforming ?? 0, 0)}`}
            driver={topDefect ? fill(t("qc.analytics.kpi.rejected.driver"), { defect: topDefect.defect, share: formatNumber(topDefect.sharePct, 0) }) : null}
            unavailable={null}
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
        </div>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>{t("qc.dashboard.chart.conformityTrend.title")}</CardTitle>
                <CardDescription>{fill(t("qc.analytics.trend.subtitle"), { days: String(days) })}</CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <ConformityTrendChart trend={trend} />
            </CardContent>
          </Card>

          <div className="xl:col-start-2 xl:row-span-2 xl:row-start-1">
            <QualityInsightsPanel insights={insights} onDrilldown={openDrilldown} className="h-full" />
          </div>

          <QualityBreakdownPanel slices={slices} plantPct={summary.totals.conformityPct} dimensions={["line", "product", "team", "shift"]} initial="line" />
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <DefectParetoPanel defects={summary.defects} />

          <Card>
            <CardHeader>
              <div>
                <CardTitle>{t("qc.analytics.teams.title")}</CardTitle>
                <CardDescription>{t("qc.analytics.teams.subtitle")}</CardDescription>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              {operations.teamCurrent.isError ? (
                <AnalyticsInlineError className="m-4" title={t("analytics.error.production.title")} impact={t("analytics.error.production.impact")} onRetry={() => operations.teamCurrent.refetch()} />
              ) : teams.length === 0 ? (
                <AnalyticsEmptyState illustration={ShiftTeamIllustration} title={t("analytics.teams.empty.title")} description={t("analytics.teams.empty.description")} />
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("analytics.teams.column.team")}</TableHead>
                      <TableHead className="text-right">{t("analytics.teams.column.produced")}</TableHead>
                      <TableHead className="text-right">{t("analytics.teams.column.yield")}</TableHead>
                      <TableHead className="text-right">{t("analytics.teams.column.conformity")}</TableHead>
                      <TableHead className="text-right">{t("qc.analytics.teams.column.rejected")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {teams.map((team) => {
                      const qualityRow = conformityByTeam.get(team.team);
                      return (
                        <TableRow key={team.team}>
                          <TableCell className="font-medium">{team.team}</TableCell>
                          <TableCell className="text-right tabular-nums">{formatNumber(team.produced, team.produced < 10 ? 2 : 1)} t</TableCell>
                          <TableCell className="text-right tabular-nums">{formatPercent(team.yieldPct)}</TableCell>
                          <TableCell className="text-right tabular-nums">{formatPercent(qualityRow?.conformityPct ?? null)}</TableCell>
                          <TableCell className="text-right tabular-nums">{qualityRow ? formatNumber(qualityRow.nonConforming, 0) : "—"}</TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
