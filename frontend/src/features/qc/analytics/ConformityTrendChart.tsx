import { memo } from "react";
import { useReducedMotion } from "framer-motion";
import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis, type TooltipContentProps } from "recharts";
import { InteractiveChart } from "../../../components/charts/InteractiveChart";
import { percentAxisMax } from "../../../components/charts/percentDomain";
import { currentLocale, useI18n } from "../../../lib/i18n";
import { formatNumber } from "../../analytics/manufacturing/format";
import type { ConformityTrendPoint } from "./qualityMetrics";

const CURRENT = "hsl(152 69% 31%)";
const PREVIOUS = "hsl(215 16% 62%)";
const GRID = "hsl(214 20% 92%)";
const TICK = { fontSize: 12, fill: "hsl(215 16% 47%)" };

function shortDate(iso: string): string {
  return new Intl.DateTimeFormat(currentLocale(), { day: "numeric", month: "short" }).format(new Date(`${iso}T00:00:00`));
}

function TrendTooltip({ active, payload }: Partial<TooltipContentProps<number, string>>) {
  const { t } = useI18n();
  const point = payload?.[0]?.payload as ConformityTrendPoint | undefined;
  if (!active || !point) return null;
  const delta = point.current !== null && point.previous !== null ? point.current - point.previous : null;

  return (
    <div className="space-y-1.5 rounded-xl border border-border bg-background/95 p-3 text-xs shadow-lg backdrop-blur-sm">
      <p className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: CURRENT }} aria-hidden />
          <span className="text-muted-foreground">{shortDate(point.date)}</span>
        </span>
        <span className="font-bold tabular-nums text-foreground">{point.current === null ? t("qc.analytics.chart.noReport") : `${formatNumber(point.current, 1)}%`}</span>
      </p>
      {point.current !== null && (
        <p className="flex items-center justify-between gap-3 text-muted-foreground">
          <span>{t("qc.analytics.chart.inspectedRejected")}</span>
          <span className="tabular-nums">
            {formatNumber(point.inspected, 0)} · <span className="text-destructive">{formatNumber(point.rejected, 0)}</span>
          </span>
        </p>
      )}
      <p className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full border border-dashed" style={{ borderColor: PREVIOUS, backgroundColor: `${PREVIOUS}40` }} aria-hidden />
          <span className="text-muted-foreground">{shortDate(point.previousDate)}</span>
        </span>
        <span className="font-semibold tabular-nums text-muted-foreground">{point.previous === null ? t("qc.analytics.chart.noReport") : `${formatNumber(point.previous, 1)}%`}</span>
      </p>
      {delta !== null && (
        <div className="flex items-center justify-between border-t border-border/60 pt-1 text-[11px]">
          <span className="text-muted-foreground">{t("production.board.trend.delta")}:</span>
          <span className={delta >= 0 ? "font-semibold tabular-nums text-success" : "font-semibold tabular-nums text-destructive"}>
            {delta >= 0 ? "+" : "−"}
            {formatNumber(Math.abs(delta), 1)} pp
          </span>
        </div>
      )}
    </div>
  );
}

/**
 * Conformity day by day against the previous equal window. The y-axis starts at
 * the lowest point seen rather than at zero: a plant runs in the high nineties
 * and a 0–100 axis would flatten every movement into a straight line.
 */
function ConformityTrendChartImpl({ trend, height = 256 }: { trend: ConformityTrendPoint[]; height?: number }) {
  const { t } = useI18n();
  const reduceMotion = useReducedMotion();
  const values = trend.flatMap((point) => [point.current, point.previous]).filter((value): value is number => value !== null);
  const floor = values.length ? Math.max(0, Math.floor(Math.min(...values) - 1)) : 90;

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted-foreground">
        <span className="flex items-center gap-2">
          <span className="h-0.5 w-5 rounded" style={{ backgroundColor: CURRENT }} aria-hidden />
          {t("analytics.chart.currentPeriod")}
        </span>
        <span className="flex items-center gap-2">
          <span className="w-5 border-t-2 border-dashed" style={{ borderColor: PREVIOUS }} aria-hidden />
          {t("analytics.chart.previousPeriod")}
        </span>
      </div>
      <div className="w-full" style={{ height }}>
        <InteractiveChart height="100%">
          <LineChart data={trend} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis
              dataKey="index"
              tick={TICK}
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
              minTickGap={32}
              tickFormatter={(index: number) => (trend[index] ? shortDate(trend[index].date) : "")}
            />
            <YAxis
              tick={TICK}
              tickLine={false}
              axisLine={false}
              width={44}
              domain={[floor, percentAxisMax]}
              tickFormatter={(value: number) => `${formatNumber(value, 0)}%`}
            />
            <Tooltip content={<TrendTooltip />} />
            <Line
              type="monotone"
              dataKey="previous"
              stroke={PREVIOUS}
              strokeWidth={1.5}
              strokeDasharray="4 4"
              dot={false}
              connectNulls
              isAnimationActive={!reduceMotion}
              animationDuration={300}
            />
            <Line
              type="monotone"
              dataKey="current"
              stroke={CURRENT}
              strokeWidth={2}
              dot={{ r: 2.5, strokeWidth: 0, fill: CURRENT }}
              activeDot={{ r: 5, stroke: "#fff", strokeWidth: 2 }}
              connectNulls
              isAnimationActive={!reduceMotion}
              animationDuration={300}
            />
          </LineChart>
        </InteractiveChart>
      </div>
    </div>
  );
}

export const ConformityTrendChart = memo(ConformityTrendChartImpl);
