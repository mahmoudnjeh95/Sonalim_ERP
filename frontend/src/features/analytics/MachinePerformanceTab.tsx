import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ClipboardList, Cog, Gauge, Timer } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";
import { InteractiveChart } from "../../components/charts/InteractiveChart";
import { percentAxisMax } from "../../components/charts/percentDomain";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { DateRangeFilter } from "../../components/patterns/DateRangeFilter";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { listMachinePerformance, listMachines, type MachinePerformanceRow, type PerformanceGrain } from "../production/api";
import { AnalyticsErrorState } from "./AnalyticsStates";
import { AppLoader } from "../../components/patterns/AppLoader";

const MACHINE_PERFORMANCE_QUERY_KEY = ["production", "machine-performance"] as const;
const MACHINES_QUERY_KEY = ["production", "machines", "all"] as const;

// Same palette as team performance (see the dataviz skill's palette
// validator) — a machine's colour is fixed by its position in the sorted
// machine-code list, never by rank, so a filtered view never repaints survivors.
const MACHINE_COLORS = ["#0c978b", "#137cec", "#4332e2", "#d926a6"];

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

function ratio(numerator: number, denominator: number): number | null {
  return denominator > 0 ? Math.round((numerator / denominator) * 1000) / 10 : null;
}

export function MachinePerformanceTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [grain, setGrain] = useState<PerformanceGrain>("day");
  // A custom range overrides the grain's rolling default; picking a new grain
  // resets it, same as team performance.
  const [customRange, setCustomRange] = useState<{ from: string; to: string } | null>(null);

  const defaultRange = useMemo(() => ({ from: isoDaysAgo(windowDaysFor(grain)), to: todayIso() }), [grain]);
  const range = customRange ?? defaultRange;

  const { data: machines = [] } = useQuery({ queryKey: MACHINES_QUERY_KEY, queryFn: () => listMachines(token) });
  const {
    data: performance = [],
    isLoading,
    isError: performanceFailed,
    refetch: refetchPerformance,
  } = useQuery({
    queryKey: [...MACHINE_PERFORMANCE_QUERY_KEY, grain, range.from, range.to],
    queryFn: () => listMachinePerformance(token, { grain, date_from: range.from, date_to: range.to }),
  });

  const machineLabel = (equipmentId: string) => {
    const machine = machines.find((m) => m.id === equipmentId);
    return machine ? `${machine.code} — ${machine.name}` : equipmentId;
  };

  const { machineIds, periods, cellFor } = useMemo(() => {
    const byKey = new Map<string, MachinePerformanceRow>();
    const machineIdSet = new Set<string>();
    const periodSet = new Set<string>();
    const key = (equipmentId: string, period: string) => `${equipmentId} ${period}`;

    for (const row of performance) {
      machineIdSet.add(row.equipment_id);
      periodSet.add(row.period);
      byKey.set(key(row.equipment_id, row.period), row);
    }

    // Known machines first, sorted by code, so colour stays stable as the
    // period filter changes which ones have data.
    const orderedIds = [...machineIdSet].sort((a, b) => machineLabel(a).localeCompare(machineLabel(b)));
    const orderedPeriods = [...periodSet].sort();

    return {
      machineIds: orderedIds,
      periods: orderedPeriods,
      cellFor: (equipmentId: string, period: string) => byKey.get(key(equipmentId, period)) ?? null,
    };
    // machines only affects labelling/sort order, not which rows exist.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [performance]);

  const yieldSeries = periods.map((period) => {
    const row: Record<string, number | string | null> = { period };
    for (const id of machineIds) {
      const cell = cellFor(id, period);
      row[machineLabel(id)] = cell ? ratio(cell.produced_quantity, cell.material_input_quantity) : null;
    }
    return row;
  });
  const downtimeSeries = periods.map((period) => {
    const row: Record<string, number | string | null> = { period };
    for (const id of machineIds) {
      const cell = cellFor(id, period);
      row[machineLabel(id)] = cell ? ratio(cell.downtime_minutes, cell.production_minutes + cell.downtime_minutes) : null;
    }
    return row;
  });
  const activitySeries = periods.map((period) => {
    const row: Record<string, number | string> = { period };
    for (const id of machineIds) row[machineLabel(id)] = cellFor(id, period)?.report_count ?? 0;
    return row;
  });

  const latestPeriod = periods.at(-1) ?? null;
  const leaderboard = latestPeriod
    ? machineIds.map((id) => ({ id, cell: cellFor(id, latestPeriod) })).filter((row) => row.cell !== null)
    : [];

  const hasData = machineIds.length > 0 && periods.length > 0;

  const leaderboardColumns: ColumnDef<{ id: string; cell: MachinePerformanceRow | null }>[] = [
    {
      key: "machine",
      header: t("production.machinePerformance.leaderboard.column.machine"),
      defaultWidth: 220,
      cellClassName: "font-medium",
      cell: ({ id }) => {
        const index = machineIds.indexOf(id);
        return (
          <span className="inline-flex items-center gap-2">
            <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: MACHINE_COLORS[index % MACHINE_COLORS.length] }} />
            {machineLabel(id)}
          </span>
        );
      },
      sortValue: ({ id }) => machineLabel(id),
    },
    {
      key: "yield",
      header: t("production.teamPerformance.leaderboard.column.yield"),
      defaultWidth: 140,
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
      defaultWidth: 140,
      cellClassName: "tabular-nums",
      cell: ({ cell }) => {
        const downtimePercent = cell ? ratio(cell.downtime_minutes, cell.production_minutes + cell.downtime_minutes) : null;
        return downtimePercent === null ? t("production.teamPerformance.noData") : `${downtimePercent}%`;
      },
      sortValue: ({ cell }) => (cell ? (ratio(cell.downtime_minutes, cell.production_minutes + cell.downtime_minutes) ?? -1) : -1),
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
  const leaderboardTable = useTableColumns("production.machinePerformance.leaderboard", leaderboardColumns);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">{t("production.machinePerformance.title")}</h2>
          <p className="text-sm text-muted-foreground">{t("production.machinePerformance.subtitle")}</p>
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
        <AppLoader className="py-8" />
      ) : performanceFailed ? (
        <Card>
          <AnalyticsErrorState
            title={t("analytics.error.machinePerformance.title")}
            impact={t("analytics.error.machinePerformance.impact")}
            onRetry={() => void refetchPerformance()}
          />
        </Card>
      ) : !hasData ? (
        <EmptyState
          icon={<Cog className="h-5 w-5" />}
          title={t("production.machinePerformance.empty.title")}
          description={t("production.machinePerformance.empty.description")}
        />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <MachineChart
              icon={<Gauge className="h-4 w-4" />}
              title={t("production.machinePerformance.chart.yield.title")}
              description={t("production.machinePerformance.chart.yield.description")}
              data={yieldSeries}
              machines={machineIds.map(machineLabel)}
              kind="line"
            />
            <MachineChart
              icon={<Timer className="h-4 w-4" />}
              title={t("production.machinePerformance.chart.downtime.title")}
              description={t("production.machinePerformance.chart.downtime.description")}
              data={downtimeSeries}
              machines={machineIds.map(machineLabel)}
              kind="line"
            />
            <MachineChart
              icon={<ClipboardList className="h-4 w-4" />}
              title={t("production.machinePerformance.chart.activity.title")}
              description={t("production.machinePerformance.chart.activity.description")}
              data={activitySeries}
              machines={machineIds.map(machineLabel)}
              kind="bar"
              percent={false}
            />
          </div>

          {leaderboard.length > 0 && (
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>{t("production.machinePerformance.leaderboard.title")}</CardTitle>
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
                    {leaderboardTable.sortRows(leaderboard).map(({ id, cell }) => (
                      <TableRow key={id}>
                        {leaderboardTable.visibleColumns.map((column) => (
                          <TableCell key={column.key} className={column.cellClassName}>
                            {column.cell({ id, cell })}
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

function MachineChart({
  icon,
  title,
  description,
  data,
  machines,
  kind,
  percent = true,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  data: Record<string, number | string | null>[];
  machines: string[];
  kind: "line" | "bar";
  percent?: boolean;
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
        <InteractiveChart height={240}>
          <Chart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" vertical={false} />
            <XAxis dataKey="period" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
            <YAxis
              tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }}
              axisLine={false}
              tickLine={false}
              allowDecimals={!percent}
              domain={percent ? [0, percentAxisMax] : undefined}
              tickFormatter={(value) => (percent ? `${value}%` : `${value}`)}
            />
            <Tooltip
              formatter={(value) => (percent ? `${value}%` : value)}
              contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }}
            />
            {machines.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
            {machines.map((machine, index) =>
              kind === "line" ? (
                <Line
                  key={machine}
                  type="monotone"
                  dataKey={machine}
                  name={machine}
                  stroke={MACHINE_COLORS[index % MACHINE_COLORS.length]}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls
                />
              ) : (
                <Bar key={machine} dataKey={machine} name={machine} fill={MACHINE_COLORS[index % MACHINE_COLORS.length]} radius={[4, 4, 0, 0]} />
              ),
            )}
          </Chart>
        </InteractiveChart>
      </CardContent>
    </Card>
  );
}
