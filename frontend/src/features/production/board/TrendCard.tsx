import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";
import { InteractiveChart } from "../../../components/charts/InteractiveChart";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { outlineIcon } from "../../../components/patterns/outlineIcon";
import YieldSvg from "../../../assets/icons/production/yield.svg?react";
import DelayIllustration from "../../../assets/illustrations/production-delay.svg?react";
import { getBoardTrend, type Granularity } from "./api";
import { addDays, formatDay, formatNumber } from "./boardFormat";
import { BlockError, MissingState } from "./BoardStates";
import { Skeleton } from "../../../components/ui/skeleton";

const YieldIcon = outlineIcon(YieldSvg);

type Range = "day" | "week" | "month" | "period";

const NAVY = "#123B6D";
const GOLD = "#E6A52E";

const SERIES = [
  { key: "semolinaCurrent", label: "production.board.trend.semolinaCurrent", color: NAVY, dashed: false },
  { key: "semolinaPrevious", label: "production.board.trend.semolinaPrevious", color: NAVY, dashed: true },
  { key: "finishedCurrent", label: "production.board.trend.finishedCurrent", color: GOLD, dashed: false },
  { key: "finishedPrevious", label: "production.board.trend.finishedPrevious", color: GOLD, dashed: true },
] as const;

interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{
    name: string;
    value: number | null;
    color: string;
    dataKey: string;
  }>;
  label?: string;
  unit: string;
}

function CustomTrendTooltip({ active, payload, label, unit }: CustomTooltipProps) {
  const { t } = useI18n();
  if (!active || !payload || !payload.length) return null;

  const semCurrent = payload.find((p) => p.dataKey === "semolinaCurrent")?.value;
  const semPrev = payload.find((p) => p.dataKey === "semolinaPrevious")?.value;
  const finCurrent = payload.find((p) => p.dataKey === "finishedCurrent")?.value;
  const finPrev = payload.find((p) => p.dataKey === "finishedPrevious")?.value;

  const calcDelta = (curr: number | null | undefined, prev: number | null | undefined) => {
    if (curr == null || prev == null || prev === 0) return null;
    const diff = curr - prev;
    const pct = (diff / prev) * 100;
    return { diff, pct };
  };

  const semDelta = calcDelta(semCurrent, semPrev);
  const finDelta = calcDelta(finCurrent, finPrev);

  return (
    <div className="rounded-xl border border-border/80 bg-white/95 p-3 shadow-lg backdrop-blur-sm text-xs space-y-2">
      <p className="font-semibold text-primary border-b border-border/60 pb-1">{label}</p>
      <div className="space-y-1">
        {payload.map((entry) => (
          <div key={entry.dataKey} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-1.5 font-medium" style={{ color: entry.color }}>
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: entry.color }} />
              {entry.name}
            </span>
            <span className="font-bold tabular-nums text-foreground">
              {typeof entry.value === "number" ? `${formatNumber(entry.value, 1)} ${unit}` : "—"}
            </span>
          </div>
        ))}
      </div>
      {(semDelta || finDelta) && (
        <div className="border-t border-border/60 pt-1 text-[11px] text-muted-foreground space-y-0.5">
          {semDelta && (
            <p className="flex justify-between gap-2">
              <span>{t("production.board.trend.semolinaCurrent")} {t("production.board.trend.delta")}:</span>
              <span className={cn("font-medium tabular-nums", semDelta.pct >= 0 ? "text-success" : "text-destructive")}>
                {semDelta.pct >= 0 ? "+" : ""}{formatNumber(semDelta.pct, 1)}%
              </span>
            </p>
          )}
          {finDelta && (
            <p className="flex justify-between gap-2">
              <span>{t("production.board.trend.finishedCurrent")} {t("production.board.trend.delta")}:</span>
              <span className={cn("font-medium tabular-nums", finDelta.pct >= 0 ? "text-success" : "text-destructive")}>
                {finDelta.pct >= 0 ? "+" : ""}{formatNumber(finDelta.pct, 1)}%
              </span>
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Semoule poured (rebroyat included) against finished product, for the chosen
 * period and the equal-length period just before it. A stretch nobody reported
 * on is a gap in the line, never a drop to zero.
 */
export function TrendCard({ date }: { date: string }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [range, setRange] = useState<Range>("day");
  const [custom, setCustom] = useState<{ from: string; to: string; granularity: Granularity }>({ from: addDays(date, -13), to: date, granularity: "day" });

  const params =
    range === "day"
      ? { date_from: date, date_to: date, granularity: "shift" as Granularity }
      : range === "week"
        ? { date_from: addDays(date, -6), date_to: date, granularity: "day" as Granularity }
        : range === "month"
          ? { date_from: addDays(date, -27), date_to: date, granularity: "week" as Granularity }
          : { date_from: custom.from, date_to: custom.to, granularity: custom.granularity };

  const trend = useQuery({
    queryKey: ["production", "board", "trend", params],
    queryFn: () => getBoardTrend(token, params),
    enabled: params.date_from <= params.date_to,
  });

  const rows = trend.data
    ? trend.data.current.points.map((point, index) => {
        const previous = trend.data!.previous.points[index];
        return {
          label: trend.data!.granularity === "shift" ? point.key : formatDay(point.key),
          semolinaCurrent: point.semolina_poured,
          semolinaPrevious: previous?.semolina_poured ?? null,
          finishedCurrent: point.finished_product,
          finishedPrevious: previous?.finished_product ?? null,
        };
      })
    : [];
  const hasData = rows.some((r) => r.semolinaCurrent !== null || r.semolinaPrevious !== null);

  const tabs: Range[] = ["day", "week", "month", "period"];

  return (
    <section className="rounded-xl border border-border bg-white p-4 shadow-soft">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-primary">
          <YieldIcon className="h-4 w-4" aria-hidden="true" />
          {t("production.board.trend.title")}
          {trend.data?.unit ? <span className="font-normal text-muted-foreground">({trend.data.unit})</span> : null}
        </h3>
        <div className="flex flex-wrap items-center gap-1.5" role="tablist">
          {tabs.map((tab) => (
            <button
              key={tab}
              role="tab"
              aria-selected={range === tab}
              type="button"
              onClick={() => setRange(tab)}
              className={cn("rounded-lg border px-3 py-1 text-sm transition-colors", range === tab ? "border-primary bg-primary text-primary-foreground" : "border-border bg-white text-primary hover:bg-muted")}
            >
              {t(`production.board.trend.${tab}` as TranslationKey)}
            </button>
          ))}
        </div>
      </div>

      {range === "period" ? (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Input type="date" value={custom.from} max={custom.to} onChange={(e) => setCustom({ ...custom, from: e.target.value })} className="w-40" />
          <Input type="date" value={custom.to} min={custom.from} onChange={(e) => setCustom({ ...custom, to: e.target.value })} className="w-40" />
          <Select value={custom.granularity} onChange={(e) => setCustom({ ...custom, granularity: e.target.value as Granularity })} className="w-36">
            {(["day", "week", "month"] as const).map((g) => (
              <option key={g} value={g}>
                {t(`production.board.trend.by.${g}` as TranslationKey)}
              </option>
            ))}
          </Select>
        </div>
      ) : null}

      {trend.isError ? (
        <BlockError onRetry={() => void trend.refetch()} />
      ) : trend.isLoading ? (
        <Skeleton className="h-56 w-full" />
      ) : !hasData ? (
        <MissingState illustration={<DelayIllustration className="h-24 w-auto" />} title={t("production.board.trend.empty.title")} description={t("production.board.trend.empty.desc")} />
      ) : (
        <div className="h-56 w-full">
          <InteractiveChart height="100%">
            <LineChart data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#e8eef5" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#5b6b80" }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 11, fill: "#8a99ab" }} tickLine={false} axisLine={false} width={44} domain={["auto", "auto"]} />
              <Tooltip content={<CustomTrendTooltip unit={trend.data?.unit ?? ""} />} />
              {SERIES.map((s) => (
                <Line key={s.key} type="monotone" dataKey={s.key} name={t(s.label as TranslationKey)} stroke={s.color} strokeWidth={2.4} strokeDasharray={s.dashed ? "6 5" : undefined} strokeOpacity={s.dashed ? 0.7 : 1} dot={s.dashed ? false : { r: 3, fill: "#fff", stroke: s.color, strokeWidth: 2 }} connectNulls={false} isAnimationActive />
              ))}
            </LineChart>
          </InteractiveChart>
        </div>
      )}
      <p className="mt-1 text-xs text-muted-foreground">{t("production.board.trend.hint")}</p>
    </section>
  );
}
