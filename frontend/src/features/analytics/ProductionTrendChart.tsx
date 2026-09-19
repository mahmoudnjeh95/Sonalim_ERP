import { memo } from "react";
import { useReducedMotion } from "framer-motion";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipContentProps } from "recharts";
import { currentLocale, useI18n } from "../../lib/i18n";
import { formatNumber } from "./manufacturing/format";
import type { TrendPoint } from "./manufacturing/metrics";

const CURRENT = "hsl(217 91% 45%)";
const PREVIOUS = "hsl(215 16% 62%)";
const GRID = "hsl(214 20% 92%)";
const TICK = { fontSize: 12, fill: "hsl(215 16% 47%)" };

function shortDate(iso: string): string {
  return new Intl.DateTimeFormat(currentLocale(), { day: "numeric", month: "short" }).format(new Date(`${iso}T00:00:00`));
}

function TrendTooltip({ active, payload }: Partial<TooltipContentProps<number, string>>) {
  const { t } = useI18n();
  const point = payload?.[0]?.payload as TrendPoint | undefined;
  if (!active || !point) return null;
  return (
    <div className="rounded-lg border border-border bg-background px-3 py-2 text-xs shadow-soft">
      <p className="flex items-center gap-2">
        <span className="h-0.5 w-4 rounded" style={{ backgroundColor: CURRENT }} aria-hidden />
        <span className="text-muted-foreground">{shortDate(point.date)}</span>
        <span className="ml-auto font-medium tabular-nums">{point.current === null ? t("analytics.chart.noReport") : `${formatNumber(point.current, 2)} t`}</span>
      </p>
      <p className="mt-1 flex items-center gap-2">
        <span className="h-0.5 w-4 rounded border-t-2 border-dashed" style={{ borderColor: PREVIOUS }} aria-hidden />
        <span className="text-muted-foreground">{shortDate(point.previousDate)}</span>
        <span className="ml-auto font-medium tabular-nums">{point.previous === null ? t("analytics.chart.noReport") : `${formatNumber(point.previous, 2)} t`}</span>
      </p>
    </div>
  );
}

function ProductionTrendChartImpl({ trend }: { trend: TrendPoint[] }) {
  const { t } = useI18n();
  const reduceMotion = useReducedMotion();

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
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
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
            <YAxis tick={TICK} tickLine={false} axisLine={false} width={44} tickFormatter={(value: number) => formatNumber(value, 0)} />
            <Tooltip content={<TrendTooltip />} />
            <Line
              type="linear"
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
              type="linear"
              dataKey="current"
              stroke={CURRENT}
              strokeWidth={2}
              dot={{ r: 2.5 }}
              activeDot={{ r: 5 }}
              connectNulls
              isAnimationActive={!reduceMotion}
              animationDuration={300}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export const ProductionTrendChart = memo(ProductionTrendChartImpl);
