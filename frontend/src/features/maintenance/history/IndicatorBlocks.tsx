import type { ReactNode } from "react";
import { motion, useReducedMotion } from "framer-motion";
import DowntimeSvg from "../../../assets/icons/production/downtime.svg?react";
import WrenchSvg from "../../../assets/icons/maintenance/wrench.svg?react";
import NoBreakdownIllustration from "../../../assets/illustrations/maintenance/no-breakdown.svg?react";
import { CountUp } from "../../../components/motion/CountUp";
import { outlineIcon } from "../../../components/patterns/outlineIcon";
import { Card } from "../../../components/ui/card";
import { CURRENCY_CODE, formatXof } from "../../../lib/currency";
import { useI18n } from "../../../lib/i18n";
import { formatDuration } from "../../../lib/units";
import { cn } from "../../../lib/utils";
import { downtimeLabel } from "../../production/downtimeOptions";
import type { MaintenanceBlock, ProductionBlock } from "./api";
import { fill, largestIndex, minutesOrDash } from "./historyFormat";

const DowntimeIcon = outlineIcon(DowntimeSvg);
const WrenchIcon = outlineIcon(WrenchSvg);

/** The brand's easing (LoginPage, BrandLoader). */
export const HISTORY_EASE = [0.22, 1, 0.36, 1] as const;

function BlockHeader({ icon, title, caption }: { icon: ReactNode; title: string; caption: string }) {
  return (
    <div className="flex min-w-0 items-center gap-2 border-b border-border px-4 py-2.5">
      <span className="shrink-0 text-primary">{icon}</span>
      <p className="shrink-0 text-sm font-semibold">{title}</p>
      <p className="truncate text-xs text-muted-foreground">· {caption}</p>
    </div>
  );
}

function Tiles({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-px bg-border sm:grid-cols-4">{children}</div>;
}

/**
 * One figure. A long one ("2 j 15 h 40 min") steps down a size or two rather than
 * wrapping or spilling into the next tile -- figures shrink, they are never rounded away.
 */
function Tile({ label, sub, children }: { label: string; sub?: ReactNode; children: ReactNode }) {
  const length = typeof children === "string" ? children.length : 0;
  return (
    <div className="min-w-0 bg-card px-4 py-3">
      <p className="truncate text-xs text-muted-foreground">{label}</p>
      <p
        className={cn(
          "whitespace-nowrap font-bold tabular-nums tracking-tight",
          length > 13 ? "text-sm" : length > 9 ? "text-base" : "text-lg sm:text-xl",
        )}
      >
        {children}
      </p>
      {sub && <p className="truncate text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

function SystemBars({ rows }: { rows: ProductionBlock["breakdowns_by_system"] }) {
  const { t } = useI18n();
  const reduce = useReducedMotion();
  if (rows.length === 0) {
    return (
      <div className="flex items-center gap-3 px-4 py-3">
        <NoBreakdownIllustration aria-hidden className="h-16 w-20 shrink-0" />
        <p className="text-sm text-muted-foreground">{t("maintenance.history.noBreakdown")}</p>
      </div>
    );
  }
  const top = largestIndex(rows.map((row) => row.minutes));
  const max = rows[top].minutes || 1;
  return (
    <div className="space-y-1.5 px-4 py-3">
      <p className="text-xs text-muted-foreground">{t("maintenance.history.bySystem")}</p>
      {rows.map((row, index) => (
        <div key={row.classification ?? "none"} className="flex items-center gap-2 text-xs">
          <span className="w-24 shrink-0 truncate text-muted-foreground">
            {row.classification ? downtimeLabel(t, "classification", row.classification) : "—"}
          </span>
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
            <motion.div
              className={cn("h-full rounded-full", index === top ? "bg-accent" : "bg-primary/70")}
              initial={reduce ? false : { width: 0 }}
              animate={{ width: `${(row.minutes / max) * 100}%` }}
              transition={{ duration: 0.6, ease: HISTORY_EASE }}
            />
          </div>
          <span className="w-20 shrink-0 text-right tabular-nums text-muted-foreground">{formatDuration(row.minutes)}</span>
        </div>
      ))}
    </div>
  );
}

export function ProductionCard({ block, available }: { block: ProductionBlock | null; available: boolean }) {
  const { t } = useI18n();
  return (
    <Card className="overflow-hidden">
      <BlockHeader
        icon={<DowntimeIcon className="h-4 w-4" />}
        title={t("maintenance.history.production.title")}
        caption={t("maintenance.history.production.caption")}
      />
      {!available || !block ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">{t("maintenance.history.production.unavailable")}</p>
      ) : (
        <>
          <Tiles>
            <Tile label={t("maintenance.history.kpi.breakdowns")} sub={formatDuration(block.breakdown_minutes)}>
              <CountUp value={block.breakdowns} duration={350} />
            </Tile>
            <Tile
              label={t("maintenance.history.kpi.mtbf")}
              sub={t(block.mtbf_minutes === null ? "maintenance.history.kpi.noBreakdown" : "maintenance.history.kpi.mtbfHint")}
            >
              {minutesOrDash(block.mtbf_minutes)}
            </Tile>
            <Tile
              label={t("maintenance.history.kpi.mttr")}
              sub={t(block.mttr_minutes === null ? "maintenance.history.kpi.noBreakdown" : "maintenance.history.kpi.mttrHint")}
            >
              {minutesOrDash(block.mttr_minutes)}
            </Tile>
            <Tile label={t("maintenance.history.kpi.allStops")} sub={formatDuration(block.stop_minutes)}>
              <CountUp value={block.stops} duration={350} />
            </Tile>
          </Tiles>
          <SystemBars rows={block.breakdowns_by_system} />
        </>
      )}
    </Card>
  );
}

function PreventiveRing({ due, closed }: { due: number; closed: number }) {
  const reduce = useReducedMotion();
  const radius = 22;
  const circumference = 2 * Math.PI * radius;
  const share = due > 0 ? Math.min(closed / due, 1) : 0;
  const label = due > 0 ? `${closed}/${due}` : "—";
  return (
    <svg viewBox="0 0 54 54" className="h-14 w-14 shrink-0" role="img" aria-label={label}>
      <circle cx="27" cy="27" r={radius} fill="none" className="stroke-muted" strokeWidth="7" />
      {due > 0 && (
        <motion.circle
          cx="27"
          cy="27"
          r={radius}
          fill="none"
          className="stroke-accent"
          strokeWidth="7"
          strokeLinecap="round"
          transform="rotate(-90 27 27)"
          strokeDasharray={circumference}
          initial={reduce ? false : { strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: circumference * (1 - share) }}
          transition={{ duration: 0.6, ease: HISTORY_EASE }}
        />
      )}
      <text x="27" y="31" textAnchor="middle" className="fill-primary text-[12px] font-bold">
        {label}
      </text>
    </svg>
  );
}

export function MaintenanceCard({ block, costsVisible }: { block: MaintenanceBlock; costsVisible: boolean }) {
  const { t } = useI18n();
  const technician = formatDuration(block.technician_seconds / 60);
  const { due, closed, closed_on_time: onTime, overdue } = block.preventive;
  return (
    <Card className="overflow-hidden">
      <BlockHeader
        icon={<WrenchIcon className="h-4 w-4" />}
        title={t("maintenance.history.maintenance.title")}
        caption={t("maintenance.history.maintenance.caption")}
      />
      <Tiles>
        <Tile label={t("maintenance.history.kpi.breakdowns")} sub={t("maintenance.history.kpi.corrective")}>
          <CountUp value={block.breakdowns} duration={350} />
        </Tile>
        <Tile
          label={t("maintenance.history.kpi.immobilisation")}
          sub={
            block.mean_immobilisation_minutes === null
              ? undefined
              : fill(t("maintenance.history.kpi.meanImmobilisation"), { value: formatDuration(block.mean_immobilisation_minutes) })
          }
        >
          {formatDuration(block.immobilised_minutes)}
        </Tile>
        <Tile
          label={t("maintenance.history.kpi.betweenBreakdowns")}
          sub={t(block.calendar_mtbf_minutes === null ? "maintenance.history.kpi.noBreakdown" : "maintenance.history.kpi.calendar")}
        >
          {minutesOrDash(block.calendar_mtbf_minutes)}
        </Tile>
        {costsVisible ? (
          <Tile
            label={`${t("maintenance.history.kpi.partsCost")} (${CURRENCY_CODE})`}
            sub={block.parts_unvalued_quantity ? fill(t("maintenance.history.kpi.unvalued"), { value: block.parts_unvalued_quantity }) : undefined}
          >
            {block.parts_cost === null ? "—" : formatXof(block.parts_cost)}
          </Tile>
        ) : (
          <Tile label={t("maintenance.history.kpi.technician")}>{technician}</Tile>
        )}
      </Tiles>
      <div className="flex items-center gap-4 px-4 py-3">
        <PreventiveRing due={due} closed={closed} />
        <div className="min-w-0 space-y-0.5 text-xs">
          <p className="text-sm font-semibold">
            {due === 0 ? t("maintenance.history.preventive.none") : fill(t("maintenance.history.preventive.summary"), { due, closed })}
          </p>
          {due > 0 && (
            <p className="text-muted-foreground">
              {fill(t("maintenance.history.preventive.onTime"), { n: onTime })} ·{" "}
              <span className={cn(overdue > 0 && "font-semibold text-destructive")}>
                {fill(t("maintenance.history.preventive.overdue"), { n: overdue })}
              </span>
            </p>
          )}
          {costsVisible && (
            <p className="text-muted-foreground">
              {t("maintenance.history.kpi.technician")} {technician}
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}

export function IndicatorBlocks({
  production,
  maintenance,
  costsVisible,
  productionAvailable,
}: {
  production: ProductionBlock | null;
  maintenance: MaintenanceBlock;
  costsVisible: boolean;
  productionAvailable: boolean;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <ProductionCard block={production} available={productionAvailable} />
      <MaintenanceCard block={maintenance} costsVisible={costsVisible} />
    </div>
  );
}
