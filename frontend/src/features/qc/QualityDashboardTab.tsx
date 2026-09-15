import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertOctagon, CheckCircle2, ClipboardList, Gauge, Recycle } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, LabelList, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { DateRangeFilter } from "../../components/patterns/DateRangeFilter";
import {
  getDispositionSummary,
  listNonConformities,
  listQualityIndexTrend,
  listQualityTeamPerformance,
  type NcDisposition,
  type NonConformitySeverity,
} from "./api";

const NC_QUERY_KEY = ["qc", "non-conformities"] as const;
const TEAM_CONFORMITY_QUERY_KEY = ["qc", "team-performance", "dashboard-trend"] as const;
const DISPOSITION_SUMMARY_QUERY_KEY = ["qc", "disposition-summary"] as const;
const INDEX_TREND_QUERY_KEY = ["qc", "index-trend"] as const;

// Fixed order, first five slots of the validated categorical palette (same
// hexes as production's WASTE_CATEGORY_COLORS) -- each index gets its own
// small chart with its own axis rather than sharing one, since these are
// different process measurements with no guarantee of a comparable scale.
const INDEX_CHARTS = [
  { key: "pre_dryer_index", labelKey: "qc.dashboard.chart.indexTrend.preDryer", color: "#2a78d6" },
  { key: "humidity_percentage", labelKey: "qc.dashboard.chart.indexTrend.humidity", color: "#eb6834" },
  { key: "cooling_index", labelKey: "qc.dashboard.chart.indexTrend.cooling", color: "#1baf7a" },
  { key: "pf_index", labelKey: "qc.dashboard.chart.indexTrend.pf", color: "#eda100" },
  { key: "sumo_index", labelKey: "qc.dashboard.chart.indexTrend.sumo", color: "#e87ba4" },
] as const;

const SEVERITY_COLORS: Record<NonConformitySeverity, string> = {
  minor: "hsl(38 92% 50%)",
  major: "hsl(24 88% 48%)",
  critical: "hsl(0 72% 51%)",
};

const DISPOSITION_ORDER: NcDisposition[] = ["regrind", "rework", "return_to_stock", "dechet"];
const STATUS_ORDER = ["raised", "quarantined", "dispositioned", "closed"] as const;

function isoDaysAgo(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().slice(0, 10);
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function formatWeightKg(weightKg: number): string {
  if (weightKg >= 1000) return `${(weightKg / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} t`;
  return `${Math.round(weightKg * 10) / 10} kg`;
}

export function QualityDashboardTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [customRange, setCustomRange] = useState<{ from: string; to: string } | null>(null);
  const defaultRange = { from: isoDaysAgo(7 * 16), to: todayIso() };
  const range = customRange ?? defaultRange;

  const { data: nonConformities = [], isLoading } = useQuery({ queryKey: NC_QUERY_KEY, queryFn: () => listNonConformities(token) });
  const { data: teamConformity = [] } = useQuery({
    queryKey: [...TEAM_CONFORMITY_QUERY_KEY, range.from, range.to],
    queryFn: () => listQualityTeamPerformance(token, { grain: "week", date_from: range.from, date_to: range.to }),
  });
  const { data: dispositionSummary = [] } = useQuery({
    queryKey: DISPOSITION_SUMMARY_QUERY_KEY,
    queryFn: () => getDispositionSummary(token),
  });
  const { data: indexTrend = [] } = useQuery({
    queryKey: [...INDEX_TREND_QUERY_KEY, range.from, range.to],
    queryFn: () => listQualityIndexTrend(token, { grain: "week", date_from: range.from, date_to: range.to }),
  });

  const conformityTrend = useMemo(() => {
    const byPeriod = new Map<string, { conforming: number; nonConforming: number }>();
    for (const row of teamConformity) {
      const entry = byPeriod.get(row.period) ?? { conforming: 0, nonConforming: 0 };
      entry.conforming += row.conforming_cartons;
      entry.nonConforming += row.non_conforming_cartons;
      byPeriod.set(row.period, entry);
    }
    return [...byPeriod.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([period, v]) => ({
        period,
        conformityPercent: v.conforming + v.nonConforming > 0 ? Math.round((v.conforming / (v.conforming + v.nonConforming)) * 1000) / 10 : null,
      }))
      .filter((r): r is { period: string; conformityPercent: number } => r.conformityPercent !== null);
  }, [teamConformity]);

  const severityCounts = useMemo(() => {
    const counts: Record<NonConformitySeverity, number> = { minor: 0, major: 0, critical: 0 };
    for (const nc of nonConformities) counts[nc.severity] += 1;
    return (["minor", "major", "critical"] as const).map((severity) => ({
      severity,
      label: t(`qc.dashboard.severity.${severity}`),
      count: counts[severity],
      fill: SEVERITY_COLORS[severity],
    }));
  }, [nonConformities, t]);

  const topDefectTypes = useMemo(() => {
    const counts = new Map<string, number>();
    for (const nc of nonConformities) counts.set(nc.defect_type, (counts.get(nc.defect_type) ?? 0) + 1);
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([defect_type, count]) => ({ defect_type, count }));
  }, [nonConformities]);

  const recoveryData = useMemo(() => {
    const totalQuantity = dispositionSummary.reduce((sum, row) => sum + row.quantity, 0);
    return DISPOSITION_ORDER.filter((disposition) => dispositionSummary.some((row) => row.disposition === disposition)).map((disposition) => {
      const row = dispositionSummary.find((r) => r.disposition === disposition);
      const quantity = row?.quantity ?? 0;
      return {
        disposition,
        label: t(`qc.nc.disposition.${disposition}`),
        percent: totalQuantity > 0 ? Math.round((quantity / totalQuantity) * 1000) / 10 : 0,
        weightKg: row?.weight_kg ?? null,
      };
    });
  }, [dispositionSummary, t]);

  // One series per index, each only the periods where that particular index
  // was actually recorded -- a period with no reading for pf_index must not
  // plot as zero, and connectNulls would draw a false flat line across the gap.
  const indexSeries = useMemo(
    () =>
      INDEX_CHARTS.map((chart) => ({
        ...chart,
        data: indexTrend
          .filter((row) => row[chart.key] !== null)
          .map((row) => ({ period: row.period, value: row[chart.key] as number })),
      })).filter((series) => series.data.length >= 2),
    [indexTrend],
  );

  const statusCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const nc of nonConformities) counts.set(nc.status, (counts.get(nc.status) ?? 0) + 1);
    return STATUS_ORDER.map((status) => ({ status, label: t(`status.${status}`), count: counts.get(status) ?? 0 }));
  }, [nonConformities, t]);

  const openCount = statusCounts.find((s) => s.status !== "closed")
    ? statusCounts.filter((s) => s.status !== "closed").reduce((sum, s) => sum + s.count, 0)
    : 0;
  const latestConformity = conformityTrend.at(-1)?.conformityPercent ?? null;

  if (isLoading) {
    return (
      <div className="space-y-3">
        <div className="h-24 w-full animate-pulse rounded-lg bg-muted" />
        <div className="h-64 w-full animate-pulse rounded-lg bg-muted" />
      </div>
    );
  }

  const hasAnyData = nonConformities.length > 0 || conformityTrend.length > 0 || dispositionSummary.length > 0;
  if (!hasAnyData) {
    return (
      <EmptyState
        icon={<Gauge className="h-5 w-5" />}
        title={t("qc.dashboard.empty.title")}
        description={t("qc.dashboard.empty.description")}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard
          label={t("qc.dashboard.chart.conformityTrend.conformity")}
          value={latestConformity ?? 0}
          unit="%"
          decimals={1}
          icon={<Gauge className="h-5 w-5" />}
          accent={latestConformity !== null && latestConformity >= 95 ? "success" : "warning"}
        />
        <StatCard
          label={t("qc.dashboard.chart.status.title")}
          value={openCount}
          icon={<ClipboardList className="h-5 w-5" />}
          accent="warning"
        />
        <StatCard
          label={t("qc.tabs.nonConformities")}
          value={nonConformities.length}
          icon={<AlertOctagon className="h-5 w-5" />}
          accent="destructive"
        />
      </div>

      {conformityTrend.length >= 2 && (
        <Card>
          <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>{t("qc.dashboard.chart.conformityTrend.title")}</CardTitle>
              <CardDescription>{t("qc.dashboard.chart.conformityTrend.subtitle")}</CardDescription>
            </div>
            <DateRangeFilter
              from={range.from}
              to={range.to}
              onChange={setCustomRange}
              onReset={() => setCustomRange(null)}
              isDefault={customRange === null}
            />
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={conformityTrend}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" vertical={false} />
                <XAxis dataKey="period" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                <YAxis
                  tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }}
                  axisLine={false}
                  tickLine={false}
                  domain={[0, 100]}
                  tickFormatter={(value) => `${value}%`}
                />
                <Tooltip
                  formatter={(value) => `${value}%`}
                  contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }}
                />
                <Line
                  type="monotone"
                  dataKey="conformityPercent"
                  name={t("qc.dashboard.chart.conformityTrend.conformity")}
                  stroke="hsl(152 69% 31%)"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {indexSeries.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{t("qc.dashboard.chart.indexTrend.title")}</CardTitle>
            <CardDescription>{t("qc.dashboard.chart.indexTrend.description")}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {indexSeries.map((series) => (
                <div key={series.key}>
                  <p className="mb-1 text-sm font-medium text-foreground">{t(series.labelKey)}</p>
                  <ResponsiveContainer width="100%" height={160}>
                    <LineChart data={series.data}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" vertical={false} />
                      <XAxis dataKey="period" tick={{ fontSize: 10, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fontSize: 10, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} domain={["auto", "auto"]} />
                      <Tooltip contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }} />
                      <Line type="monotone" dataKey="value" name={t(series.labelKey)} stroke={series.color} strokeWidth={2} dot={{ r: 2 }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>{t("qc.dashboard.chart.severity.title")}</CardTitle>
            <CardDescription>{t("qc.dashboard.chart.severity.subtitle")}</CardDescription>
          </CardHeader>
          <CardContent>
            {nonConformities.length === 0 ? (
              <EmptyState icon={<AlertOctagon className="h-5 w-5" />} title={t("qc.dashboard.empty.title")} description={t("qc.dashboard.empty.description")} />
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={severityCounts}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} allowDecimals={false} />
                  <Tooltip contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }} />
                  <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                    {severityCounts.map((entry) => (
                      <Cell key={entry.severity} fill={entry.fill} />
                    ))}
                    <LabelList dataKey="count" position="insideTop" fill="#fff" fontSize={12} fontWeight={600} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("qc.dashboard.chart.status.title")}</CardTitle>
            <CardDescription>{t("qc.dashboard.chart.status.subtitle")}</CardDescription>
          </CardHeader>
          <CardContent>
            {nonConformities.length === 0 ? (
              <EmptyState icon={<CheckCircle2 className="h-5 w-5" />} title={t("qc.dashboard.empty.title")} description={t("qc.dashboard.empty.description")} />
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={statusCounts}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} allowDecimals={false} />
                  <Tooltip contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }} />
                  <Bar dataKey="count" fill="hsl(217 91% 45%)" radius={[4, 4, 0, 0]}>
                    <LabelList dataKey="count" position="insideTop" fill="#fff" fontSize={12} fontWeight={600} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>
      </div>

      {topDefectTypes.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{t("qc.dashboard.chart.defectTypes.title")}</CardTitle>
            <CardDescription>{t("qc.dashboard.chart.defectTypes.subtitle")}</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={Math.max(160, topDefectTypes.length * 36)}>
              <BarChart data={topDefectTypes} layout="vertical" margin={{ left: 24 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} allowDecimals={false} />
                <YAxis type="category" dataKey="defect_type" width={160} tick={{ fontSize: 11, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }} />
                <Bar dataKey="count" fill="hsl(217 91% 45%)" radius={[0, 4, 4, 0]}>
                  <LabelList dataKey="count" position="insideRight" fill="#fff" fontSize={12} fontWeight={600} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{t("qc.dashboard.chart.recovery.title")}</CardTitle>
          <CardDescription>{t("qc.dashboard.chart.recovery.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          {recoveryData.length === 0 ? (
            <EmptyState
              icon={<Recycle className="h-5 w-5" />}
              title={t("qc.dashboard.chart.recovery.empty.title")}
              description={t("qc.dashboard.chart.recovery.empty.description")}
            />
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={recoveryData} layout="vertical" margin={{ left: 24 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(214 20% 92%)" horizontal={false} />
                <XAxis type="number" domain={[0, 100]} tickFormatter={(value) => `${value}%`} tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="label" width={120} tick={{ fontSize: 12, fill: "hsl(215 16% 47%)" }} axisLine={false} tickLine={false} />
                <Tooltip
                  formatter={(value) => `${value}%`}
                  contentStyle={{ borderRadius: 10, border: "1px solid hsl(214 20% 88%)", fontSize: 13, fontFamily: "Inter, sans-serif" }}
                />
                <Bar dataKey="percent" radius={[0, 4, 4, 0]}>
                  {recoveryData.map((entry) => (
                    <Cell key={entry.disposition} fill={entry.disposition === "dechet" ? "hsl(0 72% 51%)" : "hsl(152 69% 31%)"} />
                  ))}
                  <LabelList
                    position="insideRight"
                    fill="#fff"
                    fontSize={12}
                    fontWeight={600}
                    valueAccessor={(entry) => {
                      const row = (entry as unknown as { payload: (typeof recoveryData)[number] }).payload;
                      return row.weightKg !== null ? `${row.percent}% · ${formatWeightKg(row.weightKg)}` : `${row.percent}%`;
                    }}
                  />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
