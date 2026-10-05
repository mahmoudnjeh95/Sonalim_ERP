import type { ReactElement } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useI18n } from "../../../lib/i18n";
import type { Outcome } from "../api";
import { formatDay, formatMeasure } from "../jobs/jobFormat";
import type { CheckpointHistory } from "./api";

// Recharts takes literal colours: the brand navy for the one series, the gold highlight
// for its latest value, the error red for a reading recorded as an anomaly.
const NAVY = "#123B6D";
const GOLD = "#F5A900";
const RED = "#E5484D";

interface DotArgs {
  cx?: number;
  cy?: number;
  index?: number;
  payload?: { outcome: Outcome };
}

/**
 * One checkpoint's measured values over time: a single series, so one colour and no
 * legend — the heading names it. No limit lines: no limits are recorded anywhere.
 * The latest value is gold, a reading recorded as an anomaly is red.
 */
export function MeasureTrendChart({ measures, unit }: { measures: CheckpointHistory["measures"]; unit: string | null }) {
  const { t } = useI18n();
  const data = measures.map((measure) => ({ ...measure, label: formatDay(measure.at) }));
  const lastIndex = data.length - 1;
  const renderDot = (raw: unknown): ReactElement => {
    const { cx, cy, index, payload } = raw as DotArgs;
    if (cx === undefined || cy === undefined) return <g key={`dot-${index}`} />;
    const last = index === lastIndex;
    const fill = last ? GOLD : payload?.outcome === "issue" ? RED : NAVY;
    return <circle key={`dot-${index}`} cx={cx} cy={cy} r={last ? 5 : 3.5} fill={fill} stroke="#FFFFFF" strokeWidth={last ? 2 : 1} />;
  };
  return (
    <div className="h-36 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 12, right: 12, bottom: 0, left: -12 }}>
          <CartesianGrid stroke="hsl(214 20% 92%)" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} minTickGap={24} />
          <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} width={44} domain={["auto", "auto"]} />
          <Tooltip
            formatter={(value) => [formatMeasure(Number(value), unit), t("maintenance.history.point.measures").replace(" ({unit})", "")]}
            contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #D7E0EA" }}
          />
          <Line type="monotone" dataKey="value" stroke={NAVY} strokeWidth={2} dot={renderDot} activeDot={{ r: 5, fill: GOLD }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
