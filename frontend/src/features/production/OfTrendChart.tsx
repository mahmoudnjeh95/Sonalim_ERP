import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useI18n } from "../../lib/i18n";
import { formatQuantity } from "../../lib/units";

// Validated with the dataviz palette checks (light surface): colour-blind ΔE ≥ 30.
const PRESSED = "#0a5adb";
const PACKED = "#e8590c";
const GRID_STROKE = "hsl(214 20% 92%)";
const TICK_STYLE = { fontSize: 11, fill: "hsl(215 16% 47%)" };

type Day = { date: string; pressed_quantity: number; packed_quantity: number };

const shortDate = (date: string) => `${date.slice(8, 10)}/${date.slice(5, 7)}`;

/**
 * Tonnes pressed and packed per day. Both are recorded figures in the same unit,
 * so they share one axis; the gap between the lines is packaging lagging (or
 * catching up with) the press.
 */
export function OfTrendChart({ days }: { days: Day[] }) {
  const { t } = useI18n();
  const series = [
    { key: "pressed_quantity" as const, color: PRESSED, label: t("production.ofDetails.trend.pressed") },
    { key: "packed_quantity" as const, color: PACKED, label: t("production.ofDetails.trend.packed") },
  ];

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {series.map((s) => (
          <span key={s.key} className="inline-flex items-center gap-1.5">
            <span className="h-0.5 w-4 rounded-full" style={{ backgroundColor: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
      <div className="h-56 w-full" role="img" aria-label={t("production.ofDetails.trend.title")}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={days} margin={{ top: 8, right: 12, bottom: 0, left: -8 }}>
            <CartesianGrid stroke={GRID_STROKE} vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={shortDate}
              tick={TICK_STYLE}
              tickLine={false}
              axisLine={false}
              minTickGap={16}
            />
            <YAxis
              tick={TICK_STYLE}
              tickLine={false}
              axisLine={false}
              width={48}
              tickFormatter={(value: number) => `${formatQuantity(value)} t`}
            />
            <Tooltip
              cursor={{ stroke: "hsl(215 16% 70%)", strokeDasharray: "3 3" }}
              content={({ active, payload, label }) =>
                active && payload?.length ? (
                  <div className="rounded-lg border border-border bg-background px-3 py-2 text-xs shadow-md">
                    <p className="mb-1 font-medium tabular-nums">{String(label)}</p>
                    {series.map((s) => {
                      const entry = payload.find((p) => p.dataKey === s.key);
                      return (
                        <p key={s.key} className="flex items-center justify-between gap-4">
                          <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: s.color }} />
                            {s.label}
                          </span>
                          <span className="font-medium tabular-nums">{formatQuantity(Number(entry?.value ?? 0), "t")}</span>
                        </p>
                      );
                    })}
                  </div>
                ) : null
              }
            />
            {series.map((s) => (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.label}
                stroke={s.color}
                strokeWidth={2}
                dot={days.length <= 20 ? { r: 3, strokeWidth: 0, fill: s.color } : false}
                activeDot={{ r: 5, strokeWidth: 2, stroke: "#fff" }}
                isAnimationActive
                animationDuration={700}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
