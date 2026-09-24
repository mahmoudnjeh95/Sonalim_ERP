import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { formatDuration } from "../../../lib/units";
import { cn } from "../../../lib/utils";
import { StatusAnimation } from "../../../components/patterns/StatusAnimation";
import { outlineIcon } from "../../../components/patterns/outlineIcon";
import { Button } from "../../../components/ui/button";
import { Skeleton } from "../../../components/ui/skeleton";
import MachineSvg from "../../../assets/icons/maintenance/machine.svg?react";
import WrenchSvg from "../../../assets/icons/maintenance/wrench.svg?react";
import RejectSvg from "../../../assets/icons/production/reject.svg?react";
import ShiftSvg from "../../../assets/icons/production/shift.svg?react";
import EmptyNoOrders from "../../../assets/illustrations/empty-states/empty-no-orders.svg?react";
import SyncSvg from "../../../assets/animations/status/sync.svg?react";
import Team1Blue from "../../../assets/animations/teams/team_1_blue.svg?react";
import Team2Green from "../../../assets/animations/teams/team_2_green.svg?react";
import Team3Orange from "../../../assets/animations/teams/team_3_orange.svg?react";
import Team4Purple from "../../../assets/animations/teams/team_4_purple.svg?react";
import versementImage from "../../../assets/illustrations/production/stage-melange.webp";
import extrusionImage from "../../../assets/illustrations/production/stage-extrusion.webp";
import conditionnementImage from "../../../assets/illustrations/production/stage-conditionnement.webp";
import { downtimeLabel } from "../downtimeOptions";
import type {
  BoardDay,
  BoardLine,
  BoardLines,
  BoardLive,
  BoardMachine,
  BoardOf,
  DayOf,
  LineState,
  LiveLine,
  LiveStatus,
  MachineStatus,
  Stage,
  TeamStatusEntry,
} from "./api";
import { formatDay, formatNumber, minutesOfDay, prefersReducedMotion, shiftColor } from "./boardFormat";
import { MissingState } from "./BoardStates";

const MachineIcon = outlineIcon(MachineSvg);
const WrenchIcon = outlineIcon(WrenchSvg);
const RejectIcon = outlineIcon(RejectSvg);
const ShiftIcon = outlineIcon(ShiftSvg);

const STAGE_IMAGE: Record<Stage, string> = {
  versement: versementImage,
  extrusion: extrusionImage,
  conditionnement: conditionnementImage,
};

const STATE_LABEL: Record<LineState, TranslationKey> = {
  running: "production.board.state.running",
  maintenance: "production.board.state.maintenance",
  down: "production.board.state.down",
  suspended: "production.board.state.suspended",
};

const STATE_BORDER: Record<LineState, string> = {
  running: "border-l-success",
  maintenance: "border-l-warning",
  down: "border-l-destructive",
  suspended: "border-l-border",
};

const MACHINE_RING: Record<MachineStatus, string> = {
  operational: "border-success",
  maintenance: "border-warning bg-warning-soft",
  down: "border-destructive bg-destructive-soft",
};

function StateGlyph({ state }: { state: LineState }) {
  if (state === "running") return <StatusAnimation type="machine" size={38} />;
  if (state === "maintenance") return <StatusAnimation type="warning" size={38} />;
  if (state === "down") return <StatusAnimation type="error" size={38} />;
  return <MachineIcon className="h-8 w-8 text-muted-foreground" aria-hidden="true" />;
}

// --- Shift strip ------------------------------------------------------------

/** The day as one bar: each configured shift where it sits on the clock, and now. */
function ShiftStrip({ board }: { board: BoardLines }) {
  const { t } = useI18n();
  if (board.shift_windows.length === 0) {
    return <p className="mb-3 rounded-lg border border-dashed border-border bg-white px-3 py-2 text-xs text-muted-foreground">{t("production.board.roster.noShiftTimes")}</p>;
  }
  const now = minutesOfDay(board.at);
  return (
    <div className="relative mb-3 mt-6 h-7 overflow-visible rounded-lg border border-border bg-white">
      {board.shift_windows.flatMap((window) => {
        const start = minutesOfDay(window.start_time);
        const end = minutesOfDay(window.end_time);
        // A shift through midnight is drawn as two pieces, one at each end of the bar.
        const spans = start < end ? [[start, end]] : [[start, 1440], [0, end]];
        const isCurrent = board.current_shift?.shift === window.shift;
        // The label goes on the wider piece, so a night shift is named on its long half.
        const labelled = spans.length === 2 && spans[1][1] - spans[1][0] > spans[0][1] - spans[0][0] ? 1 : 0;
        return spans.map(([from, to], part) => (
          <div
            key={`${window.shift}-${part}`}
            className={cn("absolute inset-y-0 flex items-center gap-1 overflow-hidden border-r border-dashed border-border px-2 text-[11px]", isCurrent ? "bg-muted font-semibold text-primary" : "text-muted-foreground")}
            style={{ left: `${(from / 1440) * 100}%`, width: `${((to - from) / 1440) * 100}%` }}
            title={`${window.shift} ${window.start_time}–${window.end_time}`}
          >
            {part === labelled ? <ShiftIcon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" /> : null}
            <span className="truncate">{part === labelled ? window.shift : ""}</span>
          </div>
        ));
      })}
      <div className="absolute -bottom-1 -top-1 w-0.5 bg-accent" style={{ left: `${(now / 1440) * 100}%` }}>
        <span className="absolute -top-4 -translate-x-1/2 text-[11px] font-bold text-warning">{board.at}</span>
      </div>
    </div>
  );
}

// --- Team status --------------------------------------------------------------

const TEAM_STATUS_BORDER: Record<"none" | LiveStatus, string> = {
  none: "border-muted-foreground text-muted-foreground",
  open: "border-muted-foreground text-muted-foreground",
  submitted: "border-primary text-primary",
  validated: "border-success text-success",
  returned: "border-destructive text-destructive",
};

const TEAM_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  "Équipe A": Team1Blue,
  "Équipe B": Team2Green,
  "Équipe C": Team3Orange,
  "Équipe D": Team4Purple,
};

function TeamStatusPills({ teamStatus }: { teamStatus: TeamStatusEntry[] }) {
  return (
    <div className="flex items-start gap-1">
      {teamStatus.map((entry) => {
        const TeamIcon = TEAM_ICON[entry.team];
        return (
          <div
            key={entry.team}
            className={cn("flex w-[52px] flex-col items-center text-[10.5px] text-muted-foreground")}
            title={entry.shift ?? undefined}
          >
            <div className={cn("relative flex items-center justify-center h-[26px] w-[26px] rounded-full border-2 overflow-hidden", TEAM_STATUS_BORDER[entry.status ?? "none"])}>
              {TeamIcon ? (
                <TeamIcon className="h-[26px] w-[26px]" aria-hidden="true" />
              ) : (
                <span className="text-[11px] font-bold">{entry.team.charAt(entry.team.length - 1)}</span>
              )}
              {entry.is_current && (
                <SyncSvg className="absolute inset-0 h-[26px] w-[26px] text-primary" aria-hidden="true" />
              )}
            </div>
            <b className="max-w-full truncate text-[11.5px] text-foreground">{entry.team}</b>
          </div>
        );
      })}
    </div>
  );
}

// --- The shift running now ----------------------------------------------------

const LIVE_STATUS_TONE: Record<LiveStatus, string> = {
  open: "bg-muted text-muted-foreground",
  submitted: "bg-warning-soft text-warning",
  returned: "bg-destructive-soft text-destructive",
  validated: "bg-success/10 text-success",
};

/**
 * What the team on shift has entered for this OF so far. It sits apart from the validated
 * figures below and says it is not validated until a validator has approved the shift.
 */
function LiveStrip({ live, liveLine, of }: { live: BoardLive; liveLine: LiveLine | undefined; of: BoardOf }) {
  const { t } = useI18n();
  if (!live.shift) return null;
  const liveOf = liveLine?.ofs.find((o) => o.of_id === of.of_id);
  const status = liveLine?.report.status;
  return (
    <div className="mx-4 mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-dashed border-border bg-muted/40 px-3 py-2 text-sm">
      <span className="flex items-center gap-2 font-semibold text-primary">
        <ShiftIcon className="h-4 w-4" aria-hidden="true" />
        {t("production.board.live.now")} · {live.shift.shift} {live.shift.start_time}–{live.shift.end_time}
        {liveLine?.report.team ? ` · ${liveLine.report.team}` : ""}
      </span>
      {status ? (
        <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-semibold", LIVE_STATUS_TONE[status])}>
          {t(`production.board.live.status.${status}` as TranslationKey)}
        </span>
      ) : null}
      {status && status !== "validated" ? (
        <span className="text-[11px] font-semibold uppercase tracking-wide text-warning">{t("production.board.live.notValidated")}</span>
      ) : null}
      {liveOf ? (
        <span className="tabular-nums">
          <b>
            {formatNumber(liveOf.semolina_poured, 1)} → {formatNumber(liveOf.finished_product, 1)} {live.unit ?? ""}
          </b>
          {liveOf.yield_pct !== null ? ` · ${formatNumber(liveOf.yield_pct, 1)}%` : ""}
          {` · ${formatDuration(liveOf.production_minutes)}`}
          {liveOf.packets_counted !== null ? ` · ${formatNumber(liveOf.packets_counted, 0)} ${t("production.board.of.packets").toLowerCase()}` : ""}
          {liveOf.downtime_minutes > 0 ? ` · ${t("production.board.of.stops")} ${formatDuration(liveOf.downtime_minutes)}` : ""}
        </span>
      ) : (
        <span className="text-muted-foreground">
          {liveLine ? (status === "returned" ? "" : t("production.board.live.nothingForOf")) : t("production.board.live.noReport")}
        </span>
      )}
    </div>
  );
}

// --- Conveyor ---------------------------------------------------------------

/** The stage is the machine's own record in Maintenance; a machine registered with none points there. */
function MachineStageLine({ machine }: { machine: BoardMachine }) {
  const { t } = useI18n();
  const { hasPermission } = useAuth();
  if (machine.stage) {
    return <span className="text-[10.5px] font-medium text-primary">{t(`production.board.stage.${machine.stage}` as TranslationKey)}</span>;
  }
  const label = t("production.board.machine.stageNotSet");
  if (hasPermission("maintenance.view_equipment")) {
    return (
      <Link to="/maintenance" title={t("production.board.machine.setInMaintenance")} className="text-[10.5px] text-muted-foreground underline decoration-dotted underline-offset-2 hover:text-primary">
        {label}
      </Link>
    );
  }
  return <span className="text-[10.5px] text-muted-foreground">{label}</span>;
}

/** One machine of the line: its stage's picture once the stage is known, its own status ring always. */
function MachineNode({ machine, left, stoppedSince }: { machine: BoardMachine; left: string; stoppedSince?: string }) {
  const { t } = useI18n();
  const { status, stage } = machine;
  return (
    <div
      className="absolute top-2 flex w-[116px] -translate-x-1/2 flex-col items-center text-center"
      style={{ left }}
      title={`${machine.code} · ${machine.name}: ${t(`production.board.machine.status.${status}` as TranslationKey)}`}
    >
      <div className={cn("relative flex h-[88px] w-[88px] items-center justify-center rounded-2xl border-2 bg-white shadow-[0_0_0_4px_white]", MACHINE_RING[status])}>
        {stage ? (
          <motion.img
            key={stage}
            src={STAGE_IMAGE[stage]}
            alt=""
            initial={prefersReducedMotion() ? false : { opacity: 0, scale: 0.85 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.35 }}
            className={cn("h-full w-full rounded-xl object-contain p-1", status === "down" && "grayscale", status === "maintenance" && "saturate-50")}
          />
        ) : (
          <MachineIcon className="h-10 w-10 text-primary" aria-hidden="true" />
        )}
        {status !== "operational" ? (
          <span className={cn("absolute -right-2 -top-2 flex h-5 w-5 items-center justify-center rounded-full text-white", status === "maintenance" ? "bg-warning" : "bg-destructive")}>
            {status === "maintenance" ? <WrenchIcon className="h-3 w-3" aria-hidden="true" /> : <RejectIcon className="h-3 w-3" aria-hidden="true" />}
          </span>
        ) : null}
      </div>
      <span className="mt-1 max-w-full truncate rounded bg-white px-1 text-[11.5px] font-semibold text-primary">{machine.code}</span>
      <span className="max-w-full truncate bg-white px-1 text-[10.5px] text-muted-foreground">{machine.name}</span>
      <MachineStageLine machine={machine} />
      {stoppedSince ? (
        <span className="mt-0.5 rounded bg-destructive-soft px-1 text-[10px] font-semibold text-destructive">
          {t("production.board.live.stoppedSince")} {new Date(stoppedSince).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </span>
      ) : null}
    </div>
  );
}

/** Every machine declared on the line, side by side; a long line scrolls sideways rather than crowd them. */
function LineBelt({ line, state, stoppedSince }: { line: BoardLine; state: LineState; stoppedSince?: Map<string, string> }) {
  const { t } = useI18n();
  if (line.machines.length === 0) {
    return <p className="mx-4 mb-3 ml-14 text-xs text-muted-foreground">{t("production.board.machine.none")}</p>;
  }

  return (
    <div className="mx-4 mb-2 ml-14 overflow-x-auto">
      <div className={cn("relative h-[172px]", `board-belt-${state}`)} style={{ minWidth: line.machines.length * 124 }}>
        <div className="absolute inset-x-0 top-[50px] h-1.5 rounded-full bg-border" />
        {Array.from({ length: 8 }).map((_, i) => (
          <span key={i} className="board-pellet" style={{ top: 48.5, ["--d" as string]: `${(i * 0.42).toFixed(2)}s` }} />
        ))}
        {line.machines.map((machine, index) => (
          <MachineNode key={machine.id} machine={machine} left={`${((index + 0.5) / line.machines.length) * 100}%`} stoppedSince={stoppedSince?.get(machine.id)} />
        ))}
      </div>
    </div>
  );
}

// --- One OF -----------------------------------------------------------------

const SEMOULE_SEGMENT_COLORS = ["#123B6D", "#2F6FA8", "#7FA8D1", "#B6CBE0"] as const;

function OfDetails({ figures }: { figures: DayOf }) {
  const { t } = useI18n();
  const parts = [
    ...figures.semolina_by_product.map((p) => ({ label: p.name ?? "—", value: p.quantity, unit: p.unit })),
    ...(figures.regrind_input > 0 ? [{ label: t("production.board.of.rebroyat"), value: figures.regrind_input, unit: figures.semolina_by_product[0]?.unit ?? null }] : []),
  ];
  const total = parts.reduce((sum, p) => sum + p.value, 0) || 1;
  const biggestShift = Math.max(...figures.output_by_shift.map((o) => o.finished_product), 0) || 1;

  return (
    <div className="grid grid-cols-1 gap-4 p-4 md:grid-cols-3">
      <div>
        <h4 className="mb-2 text-sm font-semibold text-primary">{t("production.board.of.byProduct")}</h4>
        <div className="flex h-2 overflow-hidden rounded-full bg-muted">
          {parts.map((p, i) => (
            <motion.span key={p.label} className="h-full" style={{ background: SEMOULE_SEGMENT_COLORS[i % SEMOULE_SEGMENT_COLORS.length] }} initial={{ width: 0 }} animate={{ width: `${(p.value / total) * 100}%` }} transition={{ duration: 0.8 }} />
          ))}
        </div>
        <ul className="mt-2 space-y-0.5 text-sm">
          {parts.map((p, i) => (
            <li key={p.label} className="flex items-center gap-2">
              <i className="h-2 w-2 rounded-sm" style={{ background: SEMOULE_SEGMENT_COLORS[i % SEMOULE_SEGMENT_COLORS.length] }} />
              <span className="truncate">{p.label}</span>
              <span className="ml-auto tabular-nums">{formatNumber(p.value, 1)} {p.unit ?? ""}</span>
            </li>
          ))}
        </ul>
        {figures.packets_counted !== null ? (
          <p className="mt-2 text-sm text-muted-foreground">
            {t("production.board.of.packets")}: <b className="text-foreground">{formatNumber(figures.packets_counted, 0)}</b>
          </p>
        ) : null}
      </div>

      <div>
        <h4 className="mb-2 text-sm font-semibold text-primary">{t("production.board.of.byShift")}</h4>
        <div className="space-y-1.5">
          {figures.output_by_shift.map((o, i) => (
            <div key={`${o.shift}-${o.team}-${i}`} className="flex items-center gap-2 text-sm">
              <span className="w-24 truncate text-muted-foreground" title={`${o.shift ?? ""} ${o.team ?? ""}`}>{o.team ?? o.shift ?? "—"}</span>
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                <motion.div className="h-full rounded-full" style={{ background: shiftColor(i) }} initial={{ width: 0 }} animate={{ width: `${(o.finished_product / biggestShift) * 100}%` }} transition={{ duration: 0.8 }} />
              </div>
              <span className="w-14 text-right tabular-nums">{formatNumber(o.finished_product, 1)}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-2 text-sm">
        <h4 className="text-sm font-semibold text-primary">{t("production.board.of.stops")}</h4>
        {figures.stops.length ? (
          <ul className="space-y-0.5">
            {figures.stops.slice(0, 3).map((s, i) => (
              <li key={`${s.motif}-${s.team}-${i}`} className="flex items-center gap-2">
                <span className="truncate">{s.motif ? downtimeLabel(t, "motif", s.motif) : "—"}{s.team ? ` (${s.team})` : ""}</span>
                {s.minutes >= 60 ? (
                  <span className="rounded bg-destructive-soft px-1 text-[10px] font-semibold text-destructive">
                    &gt;1h
                  </span>
                ) : null}
                <span className={cn("ml-auto tabular-nums", s.minutes >= 60 && "font-semibold text-destructive")}>
                  {formatDuration(s.minutes)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground">—</p>
        )}
        <p>
          {t("production.board.of.waste")}: <b>{formatNumber(figures.waste_kg, 0)} kg</b>
        </p>
      </div>
    </div>
  );
}

function OfCard({ of, line, figures, dayIsLoading, unit, defaultOpen, live, liveLine, viewingDate, today }: { of: BoardOf; line: BoardLine; figures: DayOf | undefined; dayIsLoading: boolean; unit: string | null; defaultOpen: boolean; live: BoardLive | undefined; liveLine: LiveLine | undefined; viewingDate: string; today: string }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(defaultOpen);
  // The machine behind the line's colour: a down machine outranks one in maintenance.
  const troubleName = line.machines.find((m) => m.status === (of.state === "down" ? "down" : "maintenance"))?.code ?? null;

  // Filter teams: on past days, only show teams with reports; on today, show all 4 teams
  const filteredTeamStatus = line.team_status.filter((entry) => {
    if (viewingDate === today) return true; // Show all teams on today
    // On past days: show only teams that filed reports or the resting team
    return entry.status !== null || entry.shift === null;
  });

  return (
    <div className={cn("overflow-hidden rounded-xl border border-l-[5px] border-border bg-white shadow-soft", STATE_BORDER[of.state])}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex w-full flex-wrap items-center gap-x-5 gap-y-2 px-4 pb-2 pt-3 text-left">
        <StateGlyph state={of.state} />
        <div className="w-44">
          <Link to={`/production/work-orders/${of.of_id}`} onClick={(e) => e.stopPropagation()} className="text-[15px] font-bold text-primary hover:underline">
            {of.reference}
          </Link>
          {of.product_type ? <span className="ml-1.5 rounded bg-muted px-1.5 py-0.5 text-[11px] font-semibold text-primary">{of.product_type}</span> : null}
          <p className="text-xs text-muted-foreground">
            {line.name} · {t(STATE_LABEL[of.state])}
            {(of.state === "maintenance" || of.state === "down") && troubleName ? ` ${t("production.board.state.on")} ${troubleName}` : ""}
          </p>
        </div>
        {filteredTeamStatus.length ? (
          <TeamStatusPills teamStatus={filteredTeamStatus} />
        ) : (
          <p className="max-w-[12rem] text-xs text-muted-foreground">{t("production.board.roster.notSet.title")}</p>
        )}
        <div className="min-w-[10rem] text-sm">
          <p className="text-xs text-muted-foreground">{t("production.board.of.flow")}</p>
          {dayIsLoading ? (
            <Skeleton className="mt-1 h-4 w-36" />
          ) : figures ? (
            <b className="tabular-nums">
              {formatNumber(figures.semolina_poured, 1)} {unit ?? ""} → {formatNumber(figures.finished_product, 1)} {unit ?? ""}
              {figures.yield_pct !== null ? ` · ${formatNumber(figures.yield_pct, 1)}%` : ""}
            </b>
          ) : (
            <span className="text-xs text-muted-foreground">{t("production.board.of.noReport")}</span>
          )}
        </div>
        <ChevronRight className={cn("ml-auto h-4 w-4 text-muted-foreground transition-transform", open && "rotate-90")} aria-hidden="true" />
      </button>

      {live ? <LiveStrip live={live} liveLine={liveLine} of={of} /> : null}

      <LineBelt
        line={line}
        state={of.state}
        stoppedSince={new Map((liveLine?.ongoing_stops ?? []).flatMap((s) => (s.equipment_id ? [[s.equipment_id, s.since] as [string, string]] : [])))}
      />

      <AnimatePresence initial={false}>
        {open ? (
          <motion.div key="details" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.3 }} className="overflow-hidden border-t border-border bg-muted/30">
            {figures ? <OfDetails figures={figures} /> : <p className="p-4 text-sm text-muted-foreground">{t("production.board.of.noReport")}</p>}
            <p className="border-t border-border/60 px-4 py-2 text-xs text-muted-foreground">
              {of.product_name ? `${of.product_name} · ` : ""}
              {of.start_date ? `${t("production.board.of.since")} ${formatDay(of.start_date)}` : ""}
            </p>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

// --- The board --------------------------------------------------------------

/**
 * Only the lines that have an OF open on them: the board is about what is being
 * made now, so a line with nothing running is not drawn at all. Several OFs on
 * one line are stacked, one card each.
 */
export function LinesBoard({ board, day, dayIsLoading, live, today }: { board: BoardLines; day: BoardDay | undefined; dayIsLoading: boolean; live: BoardLive | undefined; today: string }) {
  const { t } = useI18n();
  const figuresByOf = new Map((day?.ofs ?? []).map((o) => [o.of_id, o]));
  const active = board.lines.filter((line) => line.ofs.length > 0);
  const viewingDate = day?.date ?? today;
  let first = true;

  if (active.length === 0) {
    return (
      <div className="mt-3">
        <MissingState
          illustration={<EmptyNoOrders className="h-16 w-16" />}
          title={t("production.board.lines.empty.title")}
          description={t("production.board.lines.empty.desc")}
          action={
            <div className="flex flex-wrap items-center justify-center gap-2">
              <Button asChild variant="outline" size="sm">
                <Link to="/production?tab=planning">{t("production.board.lines.empty.actionPlan")}</Link>
              </Button>
              <Button asChild size="sm">
                <Link to="/production?tab=work-orders">{t("production.board.lines.empty.actionWorkOrders")}</Link>
              </Button>
            </div>
          }
        />
      </div>
    );
  }

  return (
    <div>
      <ShiftStrip board={board} />
      <div className="space-y-3">
        {active.flatMap((line) =>
          line.ofs.map((of) => {
            const open = first;
            first = false;
            return (
              <OfCard
                key={of.of_id}
                of={of}
                line={line}
                figures={figuresByOf.get(of.of_id)}
                dayIsLoading={dayIsLoading}
                unit={day?.unit ?? null}
                defaultOpen={open}
                live={live}
                liveLine={live?.lines.find((l) => l.work_center_id === line.work_center_id)}
                viewingDate={viewingDate}
                today={today}
              />
            );
          }),
        )}
      </div>
    </div>
  );
}
