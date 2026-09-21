import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
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
  const [hidden, setHidden] = useState<Record<string, boolean>>({});

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

      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1">
        {SERIES.map((s) => (
          <button key={s.key} type="button" onClick={() => setHidden({ ...hidden, [s.key]: !hidden[s.key] })} className={cn("inline-flex items-center gap-1.5 text-xs", hidden[s.key] && "line-through opacity-40")}>
            <svg width="26" height="8" aria-hidden="true">
              <line x1="0" y1="4" x2="26" y2="4" stroke={s.color} strokeWidth="2.6" strokeDasharray={s.dashed ? "5 4" : undefined} />
            </svg>
            {t(s.label as TranslationKey)}
          </button>
        ))}
      </div>

      {trend.isError ? (
        <BlockError onRetry={() => void trend.refetch()} />
      ) : trend.isLoading ? (
        <Skeleton className="h-56 w-full" />
      ) : !hasData ? (
        <MissingState illustration={<DelayIllustration className="h-24 w-auto" />} title={t("production.board.trend.empty.title")} description={t("production.board.trend.empty.desc")} />
      ) : (
        <div className="h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#e8eef5" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#5b6b80" }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 11, fill: "#8a99ab" }} tickLine={false} axisLine={false} width={44} domain={["auto", "auto"]} />
              <Tooltip formatter={(value) => (typeof value === "number" ? formatNumber(value, 1) : "—")} />
              {SERIES.filter((s) => !hidden[s.key]).map((s) => (
                <Line key={s.key} type="monotone" dataKey={s.key} name={t(s.label as TranslationKey)} stroke={s.color} strokeWidth={2.4} strokeDasharray={s.dashed ? "6 5" : undefined} strokeOpacity={s.dashed ? 0.7 : 1} dot={s.dashed ? false : { r: 3, fill: "#fff", stroke: s.color, strokeWidth: 2 }} connectNulls={false} isAnimationActive />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="mt-1 text-xs text-muted-foreground">{t("production.board.trend.hint")}</p>
    </section>
  );
}
