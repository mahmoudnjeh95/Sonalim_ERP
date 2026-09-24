import { useReducedMotion } from "framer-motion";
import { Line, LineChart, ResponsiveContainer, Tooltip, YAxis } from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { currentLocale, useI18n, type TranslationKey } from "../../../lib/i18n";
import { AnalyticsEmptyState } from "../../analytics/AnalyticsStates";
import { formatNumber } from "../../analytics/manufacturing/format";
import type { ReadingSeries } from "./qualityMetrics";
import CalibrationSvg from "../../../assets/icons/quality/calibration.svg?react";

const LINE = "hsl(217 91% 45%)";

const LABEL: Record<ReadingSeries["key"], TranslationKey> = {
  pre_dryer_index: "qc.dashboard.chart.indexTrend.preDryer",
  humidity_percentage: "qc.dashboard.chart.indexTrend.humidity",
  cooling_index: "qc.dashboard.chart.indexTrend.cooling",
  pf_index: "qc.dashboard.chart.indexTrend.pf",
  sumo_index: "qc.dashboard.chart.indexTrend.sumo",
};

function shortDate(iso: string): string {
  return new Intl.DateTimeFormat(currentLocale(), { day: "numeric", month: "short" }).format(new Date(`${iso}T00:00:00`));
}

function Sparkline({ series }: { series: ReadingSeries }) {
  const { t } = useI18n();
  const reduceMotion = useReducedMotion();
  const unit = series.key === "humidity_percentage" ? "%" : "";
  return (
    <div className="rounded-lg border border-border bg-muted/30 p-3">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs text-muted-foreground">{t(LABEL[series.key])}</p>
        <p className="text-lg font-semibold tabular-nums leading-tight">
          {formatNumber(series.latest, 1)}
          {unit}
        </p>
      </div>
      <div className="mt-2 h-14 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={series.points} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
            <YAxis hide domain={["auto", "auto"]} />
            <Tooltip
              cursor={{ stroke: "hsl(214 20% 85%)" }}
              content={({ active, payload }) => {
                const point = payload?.[0]?.payload as ReadingSeries["points"][number] | undefined;
                if (!active || !point) return null;
                return (
                  <div className="rounded-lg border border-border bg-background/95 px-2 py-1 text-[11px] shadow-lg">
                    <span className="text-muted-foreground">{shortDate(point.date)}</span> ·{" "}
                    <span className="font-semibold tabular-nums">
                      {formatNumber(point.value, 1)}
                      {unit}
                    </span>
                  </div>
                );
              }}
            />
            <Line type="monotone" dataKey="value" stroke={LINE} strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: "#fff", strokeWidth: 2 }} isAnimationActive={!reduceMotion} animationDuration={300} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-[11px] tabular-nums text-muted-foreground">
        {t("qc.analytics.readings.range")} {formatNumber(series.min, 1)}
        {unit} – {formatNumber(series.max, 1)}
        {unit}
      </p>
    </div>
  );
}

/** The process readings inspectors record, each on its own scale -- descriptive, not a target line. */
export function ProcessReadingsPanel({ readings, className }: { readings: ReadingSeries[]; className?: string }) {
  const { t } = useI18n();
  const plotted = readings.filter((series) => series.points.length >= 2);
  return (
    <Card className={className}>
      <CardHeader>
        <div>
          <CardTitle>{t("qc.dashboard.chart.indexTrend.title")}</CardTitle>
          <CardDescription>{t("qc.dashboard.chart.indexTrend.description")}</CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        {plotted.length === 0 ? (
          <AnalyticsEmptyState iconOnly illustration={CalibrationSvg} title={t("qc.analytics.readings.empty.title")} description={t("qc.analytics.readings.empty.description")} />
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {plotted.map((series) => (
              <Sparkline key={series.key} series={series} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
