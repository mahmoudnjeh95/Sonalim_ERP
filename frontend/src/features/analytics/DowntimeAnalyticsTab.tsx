import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { cn } from "../../lib/utils";
import { useI18n } from "../../lib/i18n";
import { fill, useFormatters } from "./manufacturing/format";
import { useStopsAnalytics } from "./manufacturing/useStopsAnalytics";
import { useMinimumLoading } from "./useMinimumLoading";
import { AnalyticsEmptyState, AnalyticsErrorState, AnalyticsLoadingState } from "./AnalyticsStates";
import { PeriodFilter, type PeriodDays } from "./PeriodFilter";
import MachineMonitoringIllustration from "../../assets/illustrations/machine-monitoring.svg?react";

const BAR = "hsl(217 91% 45%)";
const BAR_MUTED = "hsl(217 60% 78%)";
const GRID = "hsl(214 20% 92%)";
const TICK = { fontSize: 12, fill: "hsl(215 16% 47%)" };
const SOURCE_LABEL_KEY = {
  live: "analytics.downtime.captureQuality.live",
  added_after: "analytics.downtime.captureQuality.addedAfter",
  manual: "analytics.downtime.captureQuality.manual",
  migrated: "analytics.downtime.captureQuality.migrated",
} as const;

/** Every stop of a validated shift: by classification, then the reasons inside one, how
 * the stops were captured, and what no machine was recorded for. */
export function DowntimeAnalyticsTab() {
  const { t } = useI18n();
  const [days, setDays] = useState<PeriodDays>(30);
  const { windows, stops, summary } = useStopsAnalytics(days);
  const showLoader = useMinimumLoading(stops.isLoading);
  const fmt = useFormatters(useMemo(() => (id: string) => id, []));
  // `null` is a real bucket (unclassified stops), so `undefined` means "nothing picked yet".
  const [selectedClassification, setSelectedClassification] = useState<string | null | undefined>(undefined);

  const header = <PeriodFilter days={days} onChange={setDays} windows={windows} />;

  if (showLoader) {
    return (
      <div className="space-y-5">
        {header}
        <AnalyticsLoadingState />
      </div>
    );
  }
  if (stops.isError) {
    return (
      <div className="space-y-5">
        {header}
        <Card>
          <AnalyticsErrorState title={t("analytics.error.production.title")} impact={t("analytics.error.production.impact")} onRetry={() => stops.refetch()} />
        </Card>
      </div>
    );
  }
  if (summary.stopCount === 0) {
    return (
      <div className="space-y-5">
        {header}
        <Card>
          <AnalyticsEmptyState
            illustration={MachineMonitoringIllustration}
            title={t("analytics.downtime.empty.title")}
            description={t("analytics.downtime.empty.description")}
          />
        </Card>
      </div>
    );
  }

  const classificationLabel = (value: string | null) => (value ? fmt.classification(value) : t("analytics.downtime.unclassified"));
  const classificationData = summary.byClassification.map((c) => ({
    classification: c.classification,
    label: classificationLabel(c.classification),
    minutes: c.minutes,
  }));
  const activeClassification =
    selectedClassification === undefined ? (summary.byClassification[0]?.classification ?? null) : selectedClassification;
  const motifData = summary
    .byMotif(activeClassification)
    .map((m) => ({ key: m.motif ?? "__none__", label: m.motif ? fmt.motif(m.motif) : t("analytics.downtime.noReason"), minutes: m.minutes }));

  return (
    <div className="space-y-5">
      {header}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>{t("analytics.downtime.classification.title")}</CardTitle>
              <CardDescription>{t("analytics.downtime.classification.subtitle")}</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={classificationData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke={GRID} vertical={false} />
                  <XAxis dataKey="label" tick={TICK} tickLine={false} axisLine={false} interval={0} />
                  <YAxis tick={TICK} tickLine={false} axisLine={false} width={44} />
                  <Tooltip formatter={(value) => [fmt.duration(Number(value)), t("analytics.downtime.minutes")]} />
                  <Bar
                    dataKey="minutes"
                    radius={[4, 4, 0, 0]}
                    cursor="pointer"
                    onClick={(_, index) => setSelectedClassification(classificationData[index]?.classification ?? null)}
                  >
                    {classificationData.map((entry) => (
                      <Cell key={entry.label} fill={entry.classification === activeClassification ? BAR : BAR_MUTED} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>{t("analytics.downtime.motif.title")}</CardTitle>
              <CardDescription>{t("analytics.downtime.motif.subtitle")}</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap gap-1.5" role="group" aria-label={t("analytics.downtime.classification.title")}>
              {classificationData.map((c) => (
                <button
                  key={c.label}
                  type="button"
                  aria-pressed={c.classification === activeClassification}
                  onClick={() => setSelectedClassification(c.classification)}
                  className={cn(
                    "rounded-md border px-2 py-0.5 text-xs transition-colors",
                    c.classification === activeClassification
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-background text-muted-foreground hover:bg-muted",
                  )}
                >
                  {c.label}
                </button>
              ))}
            </div>
            <ul className="space-y-1.5">
              {motifData.map((m) => (
                <li key={m.key} className="flex items-center justify-between gap-3 text-sm">
                  <span className="min-w-0 truncate">{m.label}</span>
                  <span className="shrink-0 tabular-nums text-muted-foreground">{fmt.duration(m.minutes)}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>{t("analytics.downtime.captureQuality.title")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {summary.bySource.map((s) => (
              <div key={s.source} className="flex items-center gap-3">
                <span className="w-36 shrink-0 whitespace-nowrap text-sm">{t(SOURCE_LABEL_KEY[s.source])}</span>
                <span className="h-2 flex-1 overflow-hidden rounded-full bg-muted" role="presentation">
                  <span className="block h-full rounded-full bg-primary" style={{ width: `${s.sharePct}%` }} />
                </span>
                <span className="w-24 shrink-0 text-right text-sm tabular-nums">
                  {s.sharePct.toFixed(0)}% · {fmt.duration(s.minutes)}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("analytics.downtime.unattributed.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-semibold tabular-nums">{fmt.duration(summary.unattributedMinutes)}</p>
            <p className="text-sm text-muted-foreground">
              {fill(t("analytics.downtime.unattributed.subtitle"), {
                count: String(summary.unattributedCount),
                minutes: fmt.duration(summary.unattributedMinutes),
              })}
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
