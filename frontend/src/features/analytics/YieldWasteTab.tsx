import { useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";
import { InteractiveChart } from "../../components/charts/InteractiveChart";
import { useReducedMotion } from "framer-motion";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { currentLocale, useI18n } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import type { WasteCategory } from "../production/api";
import { AnalyticsEmptyState, AnalyticsErrorState, AnalyticsLoadingState } from "./AnalyticsStates";
import { AnalyticsStatusBadge } from "./AnalyticsStatusBadge";
import { PeriodFilter, type PeriodDays } from "./PeriodFilter";
import { YieldWasteFlowPanel } from "./YieldWasteFlowPanel";
import { useMinimumLoading } from "./useMinimumLoading";
import { fill, formatNumber, formatPercent, useFormatters } from "./manufacturing/format";
import { compareQuantity, rankWasteStages, ratioPct } from "./manufacturing/metrics";
import { useOperationsData } from "./manufacturing/useManufacturingOverview";
import YieldWasteIllustration from "../../assets/illustrations/yield-waste.svg?react";

const LINE = "hsl(217 91% 45%)";
const GRID = "hsl(214 20% 92%)";
const TICK = { fontSize: 12, fill: "hsl(215 16% 47%)" };

function shortDate(iso: string): string {
  return new Intl.DateTimeFormat(currentLocale(), { day: "numeric", month: "short" }).format(new Date(`${iso}T00:00:00`));
}

export function YieldWasteTab() {
  const { t } = useI18n();
  const reduceMotion = useReducedMotion();
  const [days, setDays] = useState<PeriodDays>(30);
  const { windows, teamCurrent, ops, previousOps, humidity } = useOperationsData(days);
  const showLoader = useMinimumLoading(teamCurrent.isLoading);
  // Machine names are not needed on this tab, so ids pass through untouched.
  const fmt = useFormatters(useMemo(() => (id: string) => id, []));

  const yieldSeries = useMemo(
    () => ops.byPeriod.map((point) => ({ date: point.period, yield: ratioPct(point.produced, point.materialInput) })),
    [ops.byPeriod],
  );
  const drivers = useMemo(() => rankWasteStages(ops.totals).slice(0, 3), [ops.totals]);
  // Only the stages that were actually declared somewhere this period get a column.
  const stageColumns = useMemo(() => rankWasteStages(ops.totals).map((entry) => entry.stage), [ops.totals]);

  const header = <PeriodFilter days={days} onChange={setDays} windows={windows} />;

  if (showLoader) {
    return (
      <div className="space-y-5">
        {header}
        <AnalyticsLoadingState />
      </div>
    );
  }
  if (teamCurrent.isError) {
    return (
      <div className="space-y-5">
        {header}
        <Card>
          <AnalyticsErrorState
            title={t("analytics.error.production.title")}
            impact={t("analytics.error.production.impact")}
            onRetry={() => teamCurrent.refetch()}
          />
        </Card>
      </div>
    );
  }
  if (ops.totals.reportCount === 0) {
    return (
      <div className="space-y-5">
        {header}
        <Card>
          <AnalyticsEmptyState
            illustration={YieldWasteIllustration}
            title={t("analytics.empty.production.title")}
            description={t("analytics.empty.production.description")}
          />
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {header}

      <div className={cn("space-y-5 transition-opacity duration-200", teamCurrent.isPlaceholderData && "opacity-60")} aria-busy={teamCurrent.isPlaceholderData}>
        <YieldWasteFlowPanel current={ops} previous={previousOps} fmt={fmt} showIllustration />

        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>{t("analytics.yieldWasteTab.trend.title")}</CardTitle>
                <CardDescription>{t("analytics.yieldWasteTab.trend.subtitle")}</CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <div className="h-64 w-full">
                <InteractiveChart height="100%">
                  <LineChart data={yieldSeries} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid stroke={GRID} vertical={false} />
                    <XAxis dataKey="date" tick={TICK} tickLine={false} axisLine={false} minTickGap={32} tickFormatter={shortDate} />
                    <YAxis
                      tick={TICK}
                      tickLine={false}
                      axisLine={false}
                      width={44}
                      domain={["auto", "auto"]}
                      tickFormatter={(value: number) => `${formatNumber(value, 0)}%`}
                    />
                    <Tooltip
                      formatter={(value) => [formatPercent(typeof value === "number" ? value : null), t("analytics.kpi.yield")]}
                      labelFormatter={(label) => shortDate(String(label))}
                    />
                    <Line
                      type="linear"
                      dataKey="yield"
                      stroke={LINE}
                      strokeWidth={2}
                      dot={{ r: 2.5 }}
                      connectNulls
                      isAnimationActive={!reduceMotion}
                      animationDuration={300}
                    />
                  </LineChart>
                </InteractiveChart>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>{t("analytics.yieldWasteTab.drivers.title")}</CardTitle>
                <CardDescription>{t("analytics.yieldWasteTab.drivers.subtitle")}</CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              {drivers.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("analytics.yieldWasteTab.drivers.none")}</p>
              ) : (
                <ol className="space-y-4">
                  {drivers.map((driver, index) => {
                    const previousKg = previousOps.totals.wasteByStageKg[driver.stage] ?? 0;
                    const comparison = compareQuantity(driver.kg, previousKg > 0 ? previousKg : null, false);
                    return (
                      <li key={driver.stage} className="flex items-start justify-between gap-3">
                        <div className="flex items-start gap-3">
                          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold">
                            {index + 1}
                          </span>
                          <div>
                            <p className="text-sm font-medium">{fmt.stage(driver.stage)}</p>
                            <p className="text-xs text-muted-foreground">
                              {fmt.kg(driver.kg)} · {formatNumber(driver.sharePct, 0)}%
                              {previousKg > 0 && <> · {fill(t("analytics.yieldWasteTab.drivers.previous"), { kg: fmt.kg(previousKg) })}</>}
                            </p>
                          </div>
                        </div>
                        {comparison.delta !== null && (
                          <AnalyticsStatusBadge
                            tone={comparison.tone}
                            label={`${comparison.delta > 0 ? "+" : comparison.delta < 0 ? "−" : ""}${formatNumber(Math.abs(comparison.delta), 0)}%`}
                          />
                        )}
                      </li>
                    );
                  })}
                </ol>
              )}
            </CardContent>
          </Card>
        </div>

        {stageColumns.length > 0 && ops.byTeam.length > 0 && (
          <Card>
            <CardHeader>
              <div>
                <CardTitle>{t("analytics.yieldWasteTab.byTeam.title")}</CardTitle>
                <CardDescription>{t("analytics.yieldWasteTab.byTeam.subtitle")}</CardDescription>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("analytics.teams.column.team")}</TableHead>
                    {stageColumns.map((stage: WasteCategory) => (
                      <TableHead key={stage} className="text-right">
                        {fmt.stage(stage)}
                      </TableHead>
                    ))}
                    <TableHead className="text-right">{t("analytics.yieldWasteTab.byTeam.total")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {ops.byTeam.map((team) => {
                    const total = stageColumns.reduce((sum, stage) => sum + (team.wasteByStageKg[stage] ?? 0), 0);
                    return (
                      <TableRow key={team.team}>
                        <TableCell className="font-medium">{team.team}</TableCell>
                        {stageColumns.map((stage) => (
                          <TableCell key={stage} className="text-right tabular-nums">
                            {formatNumber(team.wasteByStageKg[stage] ?? 0, 0)} kg
                          </TableCell>
                        ))}
                        <TableCell className="text-right font-medium tabular-nums">{formatNumber(total, 0)} kg</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )}

        {humidity.length > 0 && (
          <Card>
            <CardHeader>
              <div>
                <CardTitle>{t("analytics.yieldWasteTab.humidity.title")}</CardTitle>
                <CardDescription>{t("analytics.yieldWasteTab.humidity.subtitle")}</CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <div className="h-64 w-full">
                <InteractiveChart height="100%">
                  <LineChart
                    data={humidity.map((point) => ({ date: point.date, humidity: point.averageHumidityPct }))}
                    margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
                  >
                    <CartesianGrid stroke={GRID} vertical={false} />
                    <XAxis dataKey="date" tick={TICK} tickLine={false} axisLine={false} minTickGap={32} tickFormatter={shortDate} />
                    <YAxis
                      tick={TICK}
                      tickLine={false}
                      axisLine={false}
                      width={44}
                      domain={["auto", "auto"]}
                      tickFormatter={(value: number) => `${formatNumber(value, 1)}%`}
                    />
                    <Tooltip
                      formatter={(value) => [`${formatNumber(Number(value), 1)}%`, t("analytics.yieldWasteTab.humidity.title")]}
                      labelFormatter={(label) => shortDate(String(label))}
                    />
                    <Line type="linear" dataKey="humidity" stroke={LINE} strokeWidth={2} dot={{ r: 2.5 }} connectNulls />
                  </LineChart>
                </InteractiveChart>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
