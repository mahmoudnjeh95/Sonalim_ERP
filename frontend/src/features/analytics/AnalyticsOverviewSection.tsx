import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { CURRENCY_CODE } from "../../lib/currency";
import { cn } from "../../lib/utils";
import { FINISHED_GOODS_LOT_SOURCE, listLots } from "../warehouse/api";
import { AnalyticsEmptyState, AnalyticsErrorState, AnalyticsLoadingState } from "./AnalyticsStates";
import { DataCoveragePanel } from "./DataCoveragePanel";
import { MachineDowntimePanel } from "./MachineDowntimePanel";
import { ManufacturingRecommendationsPanel } from "./ManufacturingRecommendationsPanel";
import { OrderProgressPanel } from "./OrderProgressPanel";
import { PeriodFilter, type PeriodDays } from "./PeriodFilter";
import { ProductionKpiCard } from "./ProductionKpiCard";
import { ProductionTrendChart } from "./ProductionTrendChart";
import { TeamComparisonPanel } from "./TeamComparisonPanel";
import { YieldWasteFlowPanel } from "./YieldWasteFlowPanel";
import { useMinimumLoading } from "./useMinimumLoading";
import { buildInsights, type Insight } from "./manufacturing/insights";
import { fill, formatNumber, formatPercent, useFormatters } from "./manufacturing/format";
import { compareQuantity, compareRatio, rankWasteStages, type Comparison } from "./manufacturing/metrics";
import { useManufacturingOverview } from "./manufacturing/useManufacturingOverview";
import CostIcon from "../../assets/icons/cost.svg?react";
import ProductionIcon from "../../assets/icons/production.svg?react";
import QualityIcon from "../../assets/icons/quality.svg?react";
import WasteIcon from "../../assets/icons/waste.svg?react";
import YieldIcon from "../../assets/icons/yield.svg?react";
import ProductionLineIllustration from "../../assets/illustrations/production-line.svg?react";

function signed(value: number, digits: number): string {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${formatNumber(Math.abs(value), digits)}`;
}

function deltaText(comparison: Comparison): string | null {
  if (comparison.delta === null) return null;
  return comparison.kind === "points" ? `${signed(comparison.delta, 1)} pp` : `${signed(comparison.delta, 1)}%`;
}

export function AnalyticsOverviewSection() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [, setSearchParams] = useSearchParams();
  const [days, setDays] = useState<PeriodDays>(30);
  const overview = useManufacturingOverview(days);
  const { windows, sources, ops, previousOps, quality, previousQuality, machines, breakdown, machineRecords, productRecords, orders, cost, trend } =
    overview;
  const showLoader = useMinimumLoading(sources.teamCurrent.isLoading);
  const { session } = useAuth();
  const dlcAwaiting = useQuery({
    queryKey: ["analytics", "overview", "dlc-awaiting"],
    queryFn: () => listLots(session!.token, { sourceType: FINISHED_GOODS_LOT_SOURCE, withoutExpiry: true }),
  });

  const machineLabel = useCallback(
    (equipmentId: string) => {
      const machine = machineRecords.find((record) => record.id === equipmentId);
      return machine ? `${machine.code} — ${machine.name}` : equipmentId;
    },
    [machineRecords],
  );
  const fmt = useFormatters(machineLabel);

  // Comparing against a previous window that failed to load would read as "no change" — treat it as no comparison instead.
  const previousOk = !sources.teamPrevious.isError;
  const previousQualityOk = !sources.qualityPrevious.isError;
  const insights = useMemo(
    () =>
      buildInsights({
        current: { ops, quality },
        previous: { ops: previousOk ? previousOps : ops, quality: previousQualityOk ? previousQuality : null },
        machines,
        breakdown,
        cost,
        fmt,
      }),
    [ops, previousOps, previousOk, quality, previousQuality, previousQualityOk, machines, breakdown, cost, fmt],
  );

  const openDrilldown = useCallback(
    (insight: Insight) => {
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
        <AnalyticsLoadingState />
      </div>
    );
  }

  if (sources.teamCurrent.isError) {
    return (
      <div className="space-y-5">
        {header}
        <Card>
          <AnalyticsErrorState
            title={t("analytics.error.production.title")}
            impact={t("analytics.error.production.impact")}
            onRetry={() => sources.teamCurrent.refetch()}
          />
        </Card>
      </div>
    );
  }

  const noProduction = ops.totals.reportCount === 0;
  const previousOpsForCompare = previousOk ? previousOps : null;

  const production = compareQuantity(ops.totals.produced, previousOpsForCompare && previousOps.totals.reportCount > 0 ? previousOps.totals.produced : null, true);
  const yieldComparison = compareRatio(ops.yieldPct, previousOpsForCompare ? previousOps.yieldPct : null, true);
  const waste = compareQuantity(
    ops.totals.netWasteKg,
    previousOpsForCompare && previousOps.totals.reportCount > 0 ? previousOps.totals.netWasteKg : null,
    false,
  );
  const conformity = compareRatio(quality?.conformityPct ?? null, previousQualityOk ? (previousQuality?.conformityPct ?? null) : null, true);
  const costComparison = compareQuantity(cost?.costPerTonne ?? null, cost?.previousCostPerTonne ?? null, false);

  const previousLabel = t("analytics.kpi.previous");
  const lowestYieldTeam = ops.byTeam
    .filter((team) => team.yieldPct !== null)
    .sort((a, b) => (a.yieldPct as number) - (b.yieldPct as number))[0];
  const topStage = rankWasteStages(ops.totals)[0];
  const lowestConformityTeam = quality?.byTeam
    .filter((team) => team.conformityPct !== null)
    .sort((a, b) => (a.conformityPct as number) - (b.conformityPct as number))[0];

  const qualityUnavailable = sources.qualityCurrent.isLoading
    ? t("analytics.state.loading")
    : sources.qualityCurrent.isError
    ? t("analytics.kpi.quality.error")
    : quality && quality.conforming + quality.nonConforming === 0
      ? t("analytics.kpi.quality.none")
      : null;
  const costUnavailable = sources.costAnalytics.isLoading
    ? t("analytics.state.loading")
    : sources.costAnalytics.isError
    ? t("analytics.kpi.cost.error")
    : cost?.availability === "unpriced"
      ? t("analytics.kpi.cost.unpriced")
      : cost?.availability === "noProduction"
        ? fill(t("analytics.kpi.cost.noProduction"), { label: cost.label })
        : null;

  return (
    <div className="space-y-5">
      {header}

      <div className={cn("space-y-5 transition-opacity duration-200", sources.teamCurrent.isPlaceholderData && "opacity-60")} aria-busy={sources.teamCurrent.isPlaceholderData}>
        {noProduction ? (
          <Card>
            <AnalyticsEmptyState
              illustration={ProductionLineIllustration}
              title={t("analytics.empty.production.title")}
              description={t("analytics.empty.production.description")}
            />
          </Card>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-5">
              <ProductionKpiCard
                index={0}
                icon={ProductionIcon}
                label={t("analytics.kpi.production")}
                value={ops.totals.produced}
                format={(value) => `${formatNumber(value, 1)} t`}
                comparison={production}
                deltaText={deltaText(production)}
                previousText={production.delta === null ? null : `${previousLabel} ${fmt.tonnes(previousOps.totals.produced)}`}
                driver={
                  orders && orders.attainmentPct !== null
                    ? fill(t("analytics.kpi.production.driver"), { pct: formatPercent(orders.attainmentPct, 0), count: String(orders.open.length) })
                    : null
                }
                unavailable={null}
              />
              <ProductionKpiCard
                index={1}
                icon={YieldIcon}
                label={t("analytics.kpi.yield")}
                value={ops.yieldPct}
                format={(value) => `${formatNumber(value, 1)}%`}
                comparison={yieldComparison}
                deltaText={deltaText(yieldComparison)}
                previousText={yieldComparison.delta === null ? null : `${previousLabel} ${formatPercent(previousOps.yieldPct)}`}
                driver={
                  lowestYieldTeam && ops.byTeam.length > 1
                    ? fill(t("analytics.kpi.yield.driver"), { team: lowestYieldTeam.team, yield: formatPercent(lowestYieldTeam.yieldPct) })
                    : null
                }
                unavailable={t("analytics.kpi.yield.none")}
              />
              <ProductionKpiCard
                index={2}
                icon={WasteIcon}
                label={t("analytics.kpi.waste")}
                value={ops.totals.netWasteKg}
                format={(value) => `${formatNumber(value, 0)} kg`}
                comparison={waste}
                deltaText={deltaText(waste)}
                previousText={waste.delta === null ? null : `${previousLabel} ${fmt.kg(previousOps.totals.netWasteKg)}`}
                driver={topStage ? fill(t("analytics.kpi.waste.driver"), { stage: fmt.stage(topStage.stage), kg: fmt.kg(topStage.kg) }) : null}
                unavailable={null}
              />
              <ProductionKpiCard
                index={3}
                icon={QualityIcon}
                label={t("analytics.kpi.quality")}
                value={qualityUnavailable ? null : (quality?.conformityPct ?? null)}
                format={(value) => `${formatNumber(value, 1)}%`}
                comparison={conformity}
                deltaText={deltaText(conformity)}
                previousText={conformity.delta === null ? null : `${previousLabel} ${formatPercent(previousQuality?.conformityPct ?? null)}`}
                driver={
                  lowestConformityTeam && (quality?.byTeam.length ?? 0) > 1
                    ? fill(t("analytics.kpi.quality.driver"), { team: lowestConformityTeam.team, pct: formatPercent(lowestConformityTeam.conformityPct) })
                    : null
                }
                unavailable={qualityUnavailable ?? t("analytics.kpi.quality.none")}
                extra={
                  dlcAwaiting.data && dlcAwaiting.data.length > 0 ? (
                    <button
                      type="button"
                      onClick={() => navigate("/quality?tab=lot-dlc")}
                      className="text-left text-primary underline-offset-2 hover:underline"
                    >
                      {fill(t("analytics.overview.dlcAwaiting"), { count: String(dlcAwaiting.data.length) })}
                    </button>
                  ) : null
                }
              />
              <ProductionKpiCard
                index={4}
                icon={CostIcon}
                label={t("analytics.kpi.cost")}
                value={costUnavailable ? null : (cost?.costPerTonne ?? null)}
                format={(value) => `${formatNumber(value, 0)} ${CURRENCY_CODE}`}
                comparison={costComparison}
                deltaText={deltaText(costComparison)}
                previousText={
                  costComparison.delta === null || !cost?.previousLabel ? null : `${cost.previousLabel}: ${fmt.money(cost.previousCostPerTonne ?? 0)}`
                }
                driver={cost?.availability === "ok" ? fill(t("analytics.kpi.cost.driver"), { label: cost.label }) : null}
                unavailable={costUnavailable ?? t("analytics.kpi.cost.error")}
              />
            </div>

            <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
              <Card>
                <CardHeader>
                  <div>
                    <CardTitle>{t("analytics.chart.production.title")}</CardTitle>
                    <CardDescription>{fill(t("analytics.chart.production.subtitle"), { days: String(days) })}</CardDescription>
                  </div>
                </CardHeader>
                <CardContent>
                  <ProductionTrendChart trend={trend} />
                </CardContent>
              </Card>

              <div className="xl:col-start-2 xl:row-span-2 xl:row-start-1">
                <ManufacturingRecommendationsPanel insights={insights} onDrilldown={openDrilldown} />
              </div>

              <YieldWasteFlowPanel current={ops} previous={previousOps} fmt={fmt} />
            </div>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {sources.machinePerformance.isError ? (
                <Card>
                  <AnalyticsErrorState
                    title={t("analytics.error.machines.title")}
                    impact={t("analytics.error.machines.impact")}
                    onRetry={() => sources.machinePerformance.refetch()}
                  />
                </Card>
              ) : !machines ? (
                <Card>
                  <AnalyticsLoadingState />
                </Card>
              ) : (
                <MachineDowntimePanel
                  machines={machines}
                  breakdown={breakdown}
                  machineRecords={machineRecords}
                  fmt={fmt}
                />
              )}

              {sources.workOrders.isError || sources.workOrderYields.isError ? (
                <Card>
                  <AnalyticsErrorState
                    title={t("analytics.error.orders.title")}
                    impact={t("analytics.error.orders.impact")}
                    onRetry={() => {
                      sources.workOrders.refetch();
                      sources.workOrderYields.refetch();
                    }}
                  />
                </Card>
              ) : !orders ? (
                <Card>
                  <AnalyticsLoadingState />
                </Card>
              ) : (
                <OrderProgressPanel orders={orders} products={productRecords} fmt={fmt} />
              )}
            </div>

            <TeamComparisonPanel ops={ops} quality={quality} qualityUnavailable={sources.qualityCurrent.isError} fmt={fmt} />
          </>
        )}

      </div>

      <DataCoveragePanel />
    </div>
  );
}
