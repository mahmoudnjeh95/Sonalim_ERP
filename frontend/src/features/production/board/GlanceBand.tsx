import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { useI18n } from "../../../lib/i18n";
import { formatDuration } from "../../../lib/units";
import { outlineIcon } from "../../../components/patterns/outlineIcon";
import DelayIllustration from "../../../assets/illustrations/production-delay.svg?react";
import { MissingState } from "./BoardStates";
import LineSvg from "../../../assets/icons/production/line.svg?react";
import OutputSvg from "../../../assets/icons/production/output.svg?react";
import YieldSvg from "../../../assets/icons/production/yield.svg?react";
import DowntimeSvg from "../../../assets/icons/production/downtime.svg?react";
import ReleaseSvg from "../../../assets/icons/quality/release.svg?react";
import type { BoardDay, Direction, TrendPoint } from "./api";
import { formatNumber, prefersReducedMotion } from "./boardFormat";
import { AppLoader } from "../../../components/patterns/AppLoader";

const LineIcon = outlineIcon(LineSvg);
const OutputIcon = outlineIcon(OutputSvg);
const YieldIcon = outlineIcon(YieldSvg);
const DowntimeIcon = outlineIcon(DowntimeSvg);
const ReleaseIcon = outlineIcon(ReleaseSvg);

/** Counts up to the figure once, then holds it; straight to the figure under reduced motion. */
function AnimatedNumber({ value, decimals, format }: { value: number; decimals: number; format?: (n: number) => string }) {
  const [shown, setShown] = useState(prefersReducedMotion() ? value : 0);

  useEffect(() => {
    if (prefersReducedMotion()) {
      setShown(value);
      return;
    }
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / 900);
      setShown(value * (1 - Math.pow(1 - progress, 3)));
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value]);

  return <>{format ? format(shown) : formatNumber(shown, decimals)}</>;
}

/** A line through the points that have a value; a gap where nobody reported. */
function Spark({ values }: { values: (number | null)[] }) {
  const present = values.filter((v): v is number => v !== null);
  if (present.length < 2) return <div className="h-[26px]" />;
  const min = Math.min(...present);
  const range = Math.max(...present) - min || 1;
  const width = 110;
  const height = 26;
  const step = width / (values.length - 1);
  const segments: string[] = [];
  let current: string[] = [];
  values.forEach((value, index) => {
    if (value === null) {
      if (current.length > 1) segments.push(current.join(" "));
      current = [];
      return;
    }
    current.push(`${(index * step).toFixed(1)},${(height - 3 - ((value - min) / range) * (height - 6)).toFixed(1)}`);
  });
  if (current.length > 1) segments.push(current.join(" "));

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="mt-2" aria-hidden="true">
      {segments.map((points) => (
        <motion.polyline
          key={points}
          points={points}
          fill="none"
          stroke="white"
          strokeWidth={1.6}
          strokeLinecap="round"
          strokeLinejoin="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 1.2, delay: 0.2 }}
        />
      ))}
    </svg>
  );
}

function DirectionText({ direction }: { direction: Direction | undefined }) {
  const { t } = useI18n();
  if (direction === undefined) return null;
  const label =
    direction === "up" ? t("production.board.kpi.up") : direction === "down" ? t("production.board.kpi.down") : direction === "flat" ? t("production.board.kpi.flat") : t("production.board.kpi.noCompare");
  const arrow = direction === "up" ? "▲ " : direction === "down" ? "▼ " : "";
  return (
    <p className="text-xs text-blue-100">
      {arrow}
      {label}
    </p>
  );
}

interface Tile {
  key: string;
  label: string;
  Icon: ReturnType<typeof outlineIcon>;
  value: number;
  decimals: number;
  unit: string;
  format?: (n: number) => string;
  direction?: Direction;
  series?: (number | null)[];
}

/**
 * Yesterday at a glance. Direction is read at the precision shown and never
 * judged: a yield going down is not marked bad, because no target says what
 * a good yield is.
 */
export function GlanceBand({ day, isLoading, trend }: { day: BoardDay | undefined; isLoading: boolean; trend: TrendPoint[] | undefined }) {
  const { t } = useI18n();

  if (isLoading || !day) {
    return (
      <AppLoader size={120} className="py-6" />
    );
  }

  if (day.totals.report_count === 0) {
    return (
      <MissingState
        compact
        illustration={<DelayIllustration className="h-16 w-auto" />}
        title={t("production.board.of.noReport")}
        description={t("production.board.trend.empty.desc")}
      />
    );
  }

  const unit = day.unit ?? "";
  const poured = trend?.map((p) => p.semolina_poured);
  const finished = trend?.map((p) => p.finished_product);
  const yieldSeries = trend?.map((p) =>
    p.semolina_poured && p.finished_product !== null ? (p.finished_product / p.semolina_poured) * 100 : null,
  );

  const tiles: Tile[] = [
    { key: "semolina", label: t("production.board.kpi.semolina"), Icon: LineIcon, value: day.totals.semolina_poured, decimals: 1, unit, direction: day.directions.semolina_poured, series: poured },
    { key: "finished", label: t("production.board.kpi.finished"), Icon: OutputIcon, value: day.totals.finished_product, decimals: 1, unit, direction: day.directions.finished_product, series: finished },
    ...(day.totals.yield_pct !== null
      ? [{ key: "yield", label: t("production.board.kpi.yield"), Icon: YieldIcon, value: day.totals.yield_pct, decimals: 1, unit: "%", direction: day.directions.yield_pct, series: yieldSeries } satisfies Tile]
      : []),
    { key: "downtime", label: t("production.board.kpi.downtime"), Icon: DowntimeIcon, value: day.totals.downtime_minutes, decimals: 0, unit: "", format: (n) => formatDuration(Math.round(n)), direction: day.directions.downtime_minutes },
    { key: "reports", label: t("production.board.kpi.reports"), Icon: ReleaseIcon, value: day.totals.report_count, decimals: 0, unit: "" },
  ];

  return (
    <div className="grid grid-cols-2 overflow-hidden rounded-xl bg-gradient-to-br from-[#173A63] to-[#2F6FA8] text-white shadow-soft lg:grid-cols-5">
      {tiles.map((tile) => (
        <div key={tile.key} className="border-b border-r border-white/15 p-4 last:border-r-0 lg:border-b-0">
          <div className="flex items-center gap-2 text-xs text-blue-100">
            <tile.Icon className="h-4 w-4 text-accent" aria-hidden="true" />
            {tile.label}
          </div>
          <p className="mt-1 text-2xl font-bold tracking-tight tabular-nums">
            <AnimatedNumber value={tile.value} decimals={tile.decimals} format={tile.format} />
            {tile.unit ? <span className="ml-1 text-sm font-medium text-blue-100">{tile.unit}</span> : null}
          </p>
          <DirectionText direction={tile.direction} />
          {tile.series ? <Spark values={tile.series} /> : null}
        </div>
      ))}
    </div>
  );
}
