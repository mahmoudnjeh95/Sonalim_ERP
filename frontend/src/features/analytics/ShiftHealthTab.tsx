import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { fill, formatNumber, formatPercent } from "./manufacturing/format";
import { useShiftHealth } from "./manufacturing/useShiftHealth";
import { useMinimumLoading } from "./useMinimumLoading";
import { AnalyticsEmptyState, AnalyticsErrorState, AnalyticsLoadingState } from "./AnalyticsStates";
import { PeriodFilter, type PeriodDays } from "./PeriodFilter";
import ShiftTeamIllustration from "../../assets/illustrations/shift-team.svg?react";

const BAR = "hsl(217 91% 45%)";
const GRID = "hsl(214 20% 92%)";
const TICK = { fontSize: 12, fill: "hsl(215 16% 47%)" };
// The funnel reads left to right in the order a shift moves through.
const STATUS_ORDER = ["open", "returned", "submitted", "validated"];

/** A stored key as the reader sees it, or the key itself if no translation exists yet. */
function translated(t: (key: TranslationKey) => string, key: string): string {
  const text = t(key as TranslationKey);
  return text === key ? key.split(".").pop()! : text;
}

/** Health of the reporting process itself: where shifts sit, how long approval takes,
 * which sections are sent back, and how complete shifts are. No target exists for any
 * of these, so each is shown as the recorded figure only. */
export function ShiftHealthTab() {
  const { t } = useI18n();
  const [days, setDays] = useState<PeriodDays>(30);
  const { windows, health } = useShiftHealth(days);
  const showLoader = useMinimumLoading(health.isLoading);

  const header = <PeriodFilter days={days} onChange={setDays} windows={windows} />;

  if (showLoader) {
    return (
      <div className="space-y-5">
        {header}
        <AnalyticsLoadingState />
      </div>
    );
  }
  if (health.isError) {
    return (
      <div className="space-y-5">
        {header}
        <Card>
          <AnalyticsErrorState title={t("analytics.error.production.title")} impact={t("analytics.error.production.impact")} onRetry={() => health.refetch()} />
        </Card>
      </div>
    );
  }
  const data = health.data;
  if (!data || data.completeness.shift_count === 0) {
    return (
      <div className="space-y-5">
        {header}
        <Card>
          <AnalyticsEmptyState illustration={ShiftTeamIllustration} title={t("analytics.shiftHealth.empty.title")} description={t("analytics.shiftHealth.empty.description")} />
        </Card>
      </div>
    );
  }

  const funnelData = [...data.funnel]
    .sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status))
    .map((f) => ({ status: translated(t, `analytics.shiftHealth.status.${f.status}`), count: f.count }));
  const ttv = data.time_to_validate_minutes;

  return (
    <div className="space-y-5">
      {header}

      <Card>
        <CardHeader>
          <div>
            <CardTitle>{t("analytics.shiftHealth.funnel.title")}</CardTitle>
            <CardDescription>{t("analytics.shiftHealth.funnel.subtitle")}</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={funnelData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={GRID} vertical={false} />
                <XAxis dataKey="status" tick={TICK} tickLine={false} axisLine={false} />
                <YAxis tick={TICK} tickLine={false} axisLine={false} width={32} allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" fill={BAR} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>{t("analytics.shiftHealth.timeToValidate.title")}</CardTitle>
              <CardDescription>{t("analytics.shiftHealth.timeToValidate.subtitle")}</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            {ttv.sample_size === 0 || ttv.median === null || ttv.average === null ? (
              <p className="text-sm text-muted-foreground">{t("analytics.shiftHealth.timeToValidate.empty")}</p>
            ) : (
              <div className="grid grid-cols-2 gap-3 text-center">
                <div>
                  <p className="text-2xl font-semibold tabular-nums">{formatNumber(ttv.median, 0)} min</p>
                  <p className="text-xs text-muted-foreground">{t("analytics.shiftHealth.timeToValidate.median")}</p>
                </div>
                <div>
                  <p className="text-2xl font-semibold tabular-nums">{formatNumber(ttv.average, 0)} min</p>
                  <p className="text-xs text-muted-foreground">{t("analytics.shiftHealth.timeToValidate.average")}</p>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("analytics.shiftHealth.completeness.title")}</CardTitle>
            <CardDescription>{fill(t("analytics.shiftHealth.completeness.subtitle"), { total: String(data.completeness.total_sections) })}</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold tabular-nums">
              {data.completeness.average_sections_filled === null ? "—" : formatNumber(data.completeness.average_sections_filled, 1)} /{" "}
              {data.completeness.total_sections}
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>{t("analytics.shiftHealth.returnRate.title")}</CardTitle>
            <CardDescription>{t("analytics.shiftHealth.returnRate.subtitle")}</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("analytics.shiftHealth.returnRate.section")}</TableHead>
                <TableHead className="text-right">{t("analytics.shiftHealth.returnRate.title")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.return_rate_by_section.map((row) => (
                <TableRow key={row.section_key}>
                  <TableCell className="font-medium">{translated(t, `analytics.shiftHealth.section.${row.section_key}`)}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatPercent(row.return_rate_pct)} ({row.returned_count}/{row.total_count})
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
