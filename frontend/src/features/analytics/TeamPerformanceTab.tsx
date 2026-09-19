import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ClipboardList, Gauge, Recycle, ShieldCheck, Timer, Users } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { DateRangeFilter } from "../../components/patterns/DateRangeFilter";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { listReportOptions, optionsFor, REPORT_OPTIONS_QUERY_KEY } from "../../lib/reportOptions";
import { totalsByUomCategory, type QuantityByProduct } from "../../lib/units";
import { listTeamPerformance, type PerformanceGrain, type TeamPerformanceRow } from "../production/api";
import { listProducts, listUoms } from "../warehouse/api";
import { listQualityTeamPerformance, type TeamConformityRow } from "../qc/api";
import { AnalyticsErrorState, AnalyticsInlineError } from "./AnalyticsStates";

const TEAM_PERFORMANCE_QUERY_KEY = ["production", "team-performance"] as const;
const TEAM_CONFORMITY_QUERY_KEY = ["qc", "team-performance"] as const;

// Validated categorical palette (see the dataviz skill's palette validator) —
// order is fixed and assigned by each team's position in Production Settings'
// configured list, never by rank, so a filtered view never repaints survivors.
const TEAM_COLORS = ["#0c978b", "#137cec", "#4332e2", "#d926a6"];

const GRAINS: PerformanceGrain[] = ["day", "week", "month", "year"];

function windowDaysFor(grain: PerformanceGrain): number {
  switch (grain) {
    case "day":
      return 30;
    case "week":
      return 7 * 16;
    case "month":
      return 370;
    case "year":
      return 365 * 5;
  }
}

function isoDaysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

interface MergedCell {
  team: string;
  period: string;
  produced_quantity: number;
  material_input_quantity: number;
  production_minutes: number;
  downtime_minutes: number;
  report_count: number;
  conforming_cartons: number;
  non_conforming_cartons: number;
  waste_by_product: QuantityByProduct[];
}

function ratio(numerator: number, denominator: number): number | null {
  return denominator > 0 ? Math.round((numerator / denominator) * 1000) / 10 : null;
}

export function TeamPerformanceTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [grain, setGrain] = useState<PerformanceGrain>("day");
  // A custom range overrides the grain's rolling default; picking a new grain
  // resets it, since "last N weeks" and a hand-picked range from an old grain
  // rarely mean the same thing.
  const [customRange, setCustomRange] = useState<{ from: string; to: string } | null>(null);

  const defaultRange = useMemo(() => ({ from: isoDaysAgo(windowDaysFor(grain)), to: todayIso() }), [grain]);
  const range = customRange ?? defaultRange;

  const { data: reportOptions = [] } = useQuery({ queryKey: REPORT_OPTIONS_QUERY_KEY, queryFn: () => listReportOptions(token) });
  const { data: products = [] } = useQuery({ queryKey: ["core", "products"], queryFn: () => listProducts(token) });
  const { data: uoms = [] } = useQuery({ queryKey: ["core", "uoms"], queryFn: () => listUoms(token) });
  const {
    data: production = [],
    isLoading: loadingProduction,
    isError: productionFailed,
    refetch: refetchProduction,
  } = useQuery({
    queryKey: [...TEAM_PERFORMANCE_QUERY_KEY, grain, range.from, range.to],
    queryFn: () => listTeamPerformance(token, { grain, date_from: range.from, date_to: range.to }),
  });
  const {
    data: conformity = [],
    isError: conformityFailed,
    refetch: refetchConformity,
  } = useQuery({
    queryKey: [...TEAM_CONFORMITY_QUERY_KEY, grain, range.from, range.to],
    queryFn: () => listQualityTeamPerformance(token, { grain, date_from: range.from, date_to: range.to }),
  });

  const configuredTeams = optionsFor(reportOptions, "team");

  const { teams, periods, cellFor } = useMemo(() => {
    const merged = new Map<string, MergedCell>();
    const teamSet = new Set<string>();
    const periodSet = new Set<string>();

    const cellKey = (team: string, period: string) => `${team} ${period}`;
    const touch = (team: string | null, period: string): MergedCell | null => {
      if (!team) return null; // A report with no team assigned cannot be attributed to one.
      teamSet.add(team);
      periodSet.add(period);
      const key = cellKey(team, period);
      let cell = merged.get(key);
      if (!cell) {
        cell = {
          team,
          period,
          produced_quantity: 0,
          material_input_quantity: 0,
          production_minutes: 0,
          downtime_minutes: 0,
          report_count: 0,
          conforming_cartons: 0,
          non_conforming_cartons: 0,
          waste_by_product: [],
        };
        merged.set(key, cell);
      }
      return cell;
    };

    for (const row of production as TeamPerformanceRow[]) {
      const cell = touch(row.team, row.period);
      if (!cell) continue;
      cell.produced_quantity += row.produced_quantity;
      cell.material_input_quantity += row.material_input_quantity;
      cell.production_minutes += row.production_minutes;
      cell.downtime_minutes += row.downtime_minutes;
      cell.report_count += row.report_count;
      cell.waste_by_product.push(...row.waste_by_product);
    }
    for (const row of conformity as TeamConformityRow[]) {
      const cell = touch(row.team, row.period);
      if (!cell) continue;
      cell.conforming_cartons += row.conforming_cartons;
      cell.non_conforming_cartons += row.non_conforming_cartons;
    }

    // Configured teams first, in their settings order, so color stays stable as
    // the period filter changes which teams have data; anything typed on an old
    // report but no longer configured is appended rather than dropped.
    const orderedTeams = [
      ...configuredTeams.filter((team) => teamSet.has(team)),
      ...[...teamSet].filter((team) => !configuredTeams.includes(team)).sort(),
    ];
    const orderedPeriods = [...periodSet].sort();

    return {
      teams: orderedTeams,
      periods: orderedPeriods,
      cellFor: (team: string, period: string) => merged.get(cellKey(team, period)) ?? null,
    };
  }, [production, conformity, configuredTeams]);

  const yieldSeries = periods.map((period) => {
    const row: Record<string, number | string | null> = { period };
    for (const team of teams) {
      const cell = cellFor(team, period);
      row[team] = cell ? ratio(cell.produced_quantity, cell.material_input_quantity) : null;
    }
    return row;
  });
  const downtimeSeries = periods.map((period) => {
    const row: Record<string, number | string | null> = { period };
    for (const team of teams) {
      const cell = cellFor(team, period);
      row[team] = cell ? ratio(cell.downtime_minutes, cell.production_minutes + cell.downtime_minutes) : null;
    }
    return row;
  });
  const conformitySeries = periods.map((period) => {
    const row: Record<string, number | string | null> = { period };
    for (const team of teams) {
      const cell = cellFor(team, period);
      row[team] = cell ? ratio(cell.conforming_cartons, cell.conforming_cartons + cell.non_conforming_cartons) : null;
    }
    return row;
  });
  const activitySeries = periods.map((period) => {
    const row: Record<string, number | string> = { period };
    for (const team of teams) row[team] = cellFor(team, period)?.report_count ?? 0;
    return row;
  });

  // One category charted, not all of them: a "waste" series that silently
  // switched units bar to bar would be unreadable. The category with the
  // largest total across the whole window and every team wins; anything else
  // isn't shown here (it still has its own place — the site-wide dashboard's
  // waste breakdown lists every category, this is one drill-down).
  const allWasteEntries = teams.flatMap((team) => periods.flatMap((period) => cellFor(team, period)?.waste_by_product ?? []));
  const { totals: overallWasteTotals } = totalsByUomCategory(allWasteEntries, products, uoms);
  const wasteUnit = overallWasteTotals[0]?.unit ?? null;
  const wasteSeries = periods.map((period) => {
    const row: Record<string, number | string | null> = { period };
    for (const team of teams) {
      const cell = cellFor(team, period);
      if (!cell || wasteUnit === null) {
        row[team] = null;
        continue;
      }
      const { totals } = totalsByUomCategory(cell.waste_by_product, products, uoms);
      row[team] = Math.round((totals.find((total) => total.unit === wasteUnit)?.value ?? 0) * 100) / 100;
    }
    return row;
  });

  const latestPeriod = periods.at(-1) ?? null;
  const leaderboard = latestPeriod
    ? teams.map((team) => ({ team, cell: cellFor(team, latestPeriod) })).filter((row) => row.cell !== null)
    : [];

  const isLoading = loadingProduction;
  const hasData = teams.length > 0 && periods.length > 0;

  const leaderboardColumns: ColumnDef<{ team: string; cell: MergedCell | null }>[] = [
    {
      key: "team",
      header: t("production.teamPerformance.leaderboard.column.team"),
      defaultWidth: 200,
      cellClassName: "font-medium",
      cell: ({ team }) => {
        const index = teams.indexOf(team);
        return (
          <span className="inline-flex items-center gap-2">
            <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: TEAM_COLORS[index % TEAM_COLORS.length] }} />
            {team}
          </span>
        );
      },
      sortValue: ({ team }) => team,
    },
    {
      key: "yield",
      header: t("production.teamPerformance.leaderboard.column.yield"),
      defaultWidth: 130,
      cellClassName: "tabular-nums",
      cell: ({ cell }) => {
        const yieldPercent = cell ? ratio(cell.produced_quantity, cell.material_input_quantity) : null;
        return yieldPercent === null ? t("production.teamPerformance.noData") : `${yieldPercent}%`;
      },
      sortValue: ({ cell }) => (cell ? (ratio(cell.produced_quantity, cell.material_input_quantity) ?? -1) : -1),
    },
    {
      key: "downtime",
      header: t("production.teamPerformance.leaderboard.column.downtime"),
      defaultWidth: 130,
      cellClassName: "tabular-nums",
      cell: ({ cell }) => {
        const downtimePercent = cell ? ratio(cell.downtime_minutes, cell.production_minutes + cell.downtime_minutes) : null;
        return downtimePercent === null ? t("production.teamPerformance.noData") : `${downtimePercent}%`;
      },
      sortValue: ({ cell }) => (cell ? (ratio(cell.downtime_minutes, cell.production_minutes + cell.downtime_minutes) ?? -1) : -1),
    },
    {
      key: "conformity",
      header: t("production.teamPerformance.leaderboard.column.conformity"),
      defaultWidth: 140,
      cellClassName: "tabular-nums",
      cell: ({ cell }) => {
        const conformityPercent = cell ? ratio(cell.conforming_cartons, cell.conforming_cartons + cell.non_conforming_cartons) : null;
        return conformityPercent === null ? t("production.teamPerformance.noData") : `${conformityPercent}%`;
      },
      sortValue: ({ cell }) => (cell ? (ratio(cell.conforming_cartons, cell.conforming_cartons + cell.non_conforming_cartons) ?? -1) : -1),
    },
    {
      key: "reports",
      header: t("production.teamPerformance.leaderboard.column.reports"),
      defaultWidth: 120,
      cellClassName: "tabular-nums",
      cell: ({ cell }) => cell?.report_count ?? 0,
      sortValue: ({ cell }) => cell?.report_count ?? 0,
    },
  ];
  const leaderboardTable = useTableColumns("production.teamPerformance.leaderboard", leaderboardColumns);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">{t("production.teamPerformance.title")}</h2>
          <p className="text-sm text-muted-foreground">{t("production.teamPerformance.subtitle")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <FilterTabs
            value={grain}
            onChange={(value) => {
              setGrain(value);
              setCustomRange(null);
            }}
            options={GRAINS.map((g) => ({ value: g, label: t(`production.teamPerformance.grain.${g}`) }))}
          />
          <DateRangeFilter
            from={range.from}
            to={range.to}
            onChange={setCustomRange}
            onReset={() => setCustomRange(null)}
            isDefault={customRange === null}
          />
        </div>
      </div>

      {isLoading ? (
        <div className="h-64 w-full animate-pulse rounded-lg bg-muted" />
      ) : productionFailed ? (
        <Card>
          <AnalyticsErrorState
            title={t("analytics.error.teamPerformance.title")}
            impact={t("analytics.error.teamPerformance.impact")}
            onRetry={() => void refetchProduction()}
          />
        </Card>
      ) : !hasData ? (
        <EmptyState
          icon={<Users className="h-5 w-5" />}
          title={t("production.teamPerformance.empty.title")}
          description={t("production.teamPerformance.empty.description")}
        />
      ) : (
        <>
          {conformityFailed && (
            <AnalyticsInlineError
              title={t("analytics.error.teamConformity.title")}
              impact={t("analytics.error.teamConformity.impact")}
              onRetry={() => void refetchConformity()}
            />
          )}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <TeamChart
              icon={<Gauge className="h-4 w-4" />}
              title={t("production.teamPerformance.chart.yield.title")}
              description={t("production.teamPerformance.chart.yield.description")}
              data={yieldSeries}
              teams={teams}
              kind="line"
            />
            <TeamChart
              icon={<Timer className="h-4 w-4" />}
              title={t("production.teamPerformance.chart.downtime.title")}
              description={t("production.teamPerformance.chart.downtime.description")}
              data={downtimeSeries}
              teams={teams}
              kind="line"
            />
            <TeamChart
              icon={<ShieldCheck className="h-4 w-4" />}
              title={t("production.teamPerformance.chart.conformity.title")}
              description={t("production.teamPerformance.chart.conformity.description")}
              data={conformitySeries}
              teams={teams}
              kind="line"
            />
            <TeamChart
              icon={<ClipboardList className="h-4 w-4" />}
              title={t("production.teamPerformance.chart.activity.title")}
              description={t("production.teamPerformance.chart.activity.description")}
              data={activitySeries}
              teams={teams}
              kind="bar"
              percent={false}
            />
            {wasteUnit !== null && (
              <TeamChart
                icon={<Recycle className="h-4 w-4" />}
                title={t("production.teamPerformance.chart.waste.title")}
                description={`${t("production.teamPerformance.chart.waste.description")} (${wasteUnit})`}
                data={wasteSeries}
                teams={teams}
                kind="bar"
                percent={false}
                unit={wasteUnit}
              />
            )}
          </div>

          {leaderboard.length > 0 && (
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>{t("production.teamPerformance.leaderboard.title")}</CardTitle>
                  <CardDescription>{latestPeriod}</CardDescription>
                </div>
                <ColumnVisibilityMenu
                  columns={leaderboardColumns}
                  isVisible={leaderboardTable.isVisible}
                  onToggle={leaderboardTable.toggleVisible}
                  onReset={leaderboardTable.resetAll}
                />
              </CardHeader>
              <CardContent className="p-0">
                <Table colWidths={leaderboardTable.colWidths}>
                  <TableHeader>
                    <TableRow>
                      {leaderboardTable.visibleColumns.map((column) => (
                        <ResizableTableHead
                          key={column.key}
                          width={leaderboardTable.getWidth(column.key)}
                          onResize={(width) => leaderboardTable.setWidth(column.key, width)}
                          sortDirection={leaderboardTable.sortDirectionFor(column.key)}
                          onSort={column.sortValue ? () => leaderboardTable.toggleSort(column.key) : undefined}
                        >
                          {column.header}
                        </ResizableTableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {leaderboardTable.sortRows(leaderboard).map(({ team, cell }) => (
                      <TableRow key={team}>
                        {leaderboardTable.visibleColumns.map((column) => (
                          <TableCell key={column.key} className={column.cellClassName}>
                            {column.cell({ team, cell })}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

function TeamChart({
  icon,
  title,
  description,
  data,
  teams,
  kind,
  percent = true,
  unit,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  data: Record<string, number | string | null>[];
  teams: string[];
  kind: "line" | "bar";
  percent?: boolean;
  unit?: string;
}) {
  const Chart = kind === "line" ? LineChart : BarChart;
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">{icon}</span>
          <div>
            <CardTitle>{title}</CardTitle>
            <CardDescription>{description}</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={240}>
          <Chart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" vertical={false} />
            <XAxis dataKey="period" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
            <YAxis
              tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }}
              axisLine={false}
              tickLine={false}
              allowDecimals={!percent}
              domain={percent ? [0, 100] : undefined}
              tickFormatter={(value) => (percent ? `${value}%` : `${value}`)}
            />
            <Tooltip
              formatter={(value) => (percent ? `${value}%` : unit ? `${value} ${unit}` : value)}
              contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }}
            />
            {teams.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
            {teams.map((team, index) =>
              kind === "line" ? (
                <Line
                  key={team}
                  type="monotone"
                  dataKey={team}
                  name={team}
                  stroke={TEAM_COLORS[index % TEAM_COLORS.length]}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls
                />
              ) : (
                <Bar key={team} dataKey={team} name={team} fill={TEAM_COLORS[index % TEAM_COLORS.length]} radius={[4, 4, 0, 0]} />
              ),
            )}
          </Chart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
