import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { motion, useReducedMotion } from "framer-motion";
import DowntimeSvg from "../../../assets/icons/production/downtime.svg?react";
import HistorySvg from "../../../assets/icons/maintenance/history.svg?react";
import CorrectiveSvg from "../../../assets/icons/maintenance/corrective.svg?react";
import PreventiveSvg from "../../../assets/icons/maintenance/preventive.svg?react";
import StatusChangeSvg from "../../../assets/icons/maintenance/status-change.svg?react";
import HistoryEmptyIllustration from "../../../assets/illustrations/maintenance/history-empty.svg?react";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { outlineIcon } from "../../../components/patterns/outlineIcon";
import { Badge } from "../../../components/ui/badge";
import { formatXofWithCode } from "../../../lib/currency";
import { currentLocale, useI18n, type TranslationKey } from "../../../lib/i18n";
import { formatDuration } from "../../../lib/units";
import { cn } from "../../../lib/utils";
import { downtimeLabel } from "../../production/downtimeOptions";
import type { EquipmentStatus, JobStatus } from "../api";
import { formatDateTime, formatDay } from "../jobs/jobFormat";
import { JOB_KIND_LABEL_KEY, JOB_PRIORITY_LABEL_KEY, JOB_STATUS_BADGE_VARIANT, JOB_STATUS_LABEL_KEY } from "../labels";
import type { JournalRow, ProductionStopItem, TimelineItem } from "./api";
import { HISTORY_EASE } from "./IndicatorBlocks";
import { fill, monthKey } from "./historyFormat";

const DowntimeIcon = outlineIcon(DowntimeSvg);
const HistoryIcon = outlineIcon(HistorySvg);
const CorrectiveIcon = outlineIcon(CorrectiveSvg);
const PreventiveIcon = outlineIcon(PreventiveSvg);
const StatusChangeIcon = outlineIcon(StatusChangeSvg);

type TimelineFilter = "all" | "jobs" | "stops" | "status" | "issues";
const FILTERS: TimelineFilter[] = ["all", "jobs", "stops", "status", "issues"];
const LIVE: JobStatus[] = ["in_progress", "rework"];
const STATUS_TEXT: Record<EquipmentStatus, string> = {
  operational: "text-success",
  down: "text-destructive",
  maintenance: "text-warning",
};

function matches(item: TimelineItem, filter: TimelineFilter): boolean {
  switch (filter) {
    case "all":
      return true;
    case "jobs":
      return item.kind === "job";
    case "stops":
      return item.kind === "production_stop";
    case "status":
      return item.kind === "status_change";
    case "issues":
      return (
        (item.kind === "job" && item.job.outcomes.issue > 0) ||
        (item.kind === "production_stop" && item.stop.downtime_type === "corrective")
      );
  }
}

function keyOf(item: TimelineItem): string {
  if (item.kind === "job") return `job-${item.job.job_id}`;
  if (item.kind === "production_stop") return `stop-${item.stop.shift_report_id}-${item.stop.started_at}`;
  return `status-${item.at}-${item.to_status}`;
}

type Tone = "default" | "live" | "done" | "issue";

/** The dot on the spine. The live job's one is the view's single gold highlight. */
function Node({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "absolute -left-[32px] top-2.5 grid h-6 w-6 place-items-center rounded-full border-2 bg-card",
        tone === "default" && "border-border text-primary",
        tone === "live" && "border-accent text-accent shadow-glow",
        tone === "done" && "border-success text-success",
        tone === "issue" && "border-destructive text-destructive",
      )}
    >
      {tone === "live" && (
        <span aria-hidden className="absolute inset-[-2px] animate-ping rounded-full border-2 border-accent opacity-40 motion-reduce:hidden" />
      )}
      {children}
    </span>
  );
}

function JobEntry({ job }: { job: JournalRow }) {
  const { t } = useI18n();
  const live = LIVE.includes(job.status);
  const open = job.status !== "closed" && job.status !== "cancelled";
  const tone: Tone = live ? "live" : job.status === "closed" ? (job.outcomes.issue > 0 ? "issue" : "done") : "default";
  const Icon = job.kind === "preventive" ? PreventiveIcon : CorrectiveIcon;
  const partLines = job.parts.issued_lines + job.parts.purchase_lines;
  return (
    <Link
      to={`/maintenance/jobs/${job.job_id}`}
      className={cn(
        "relative block rounded-lg border border-border bg-card px-3 py-2.5 transition-colors hover:bg-muted/40",
        live && "border-accent/60",
      )}
    >
      <Node tone={tone}>
        <Icon className="h-3.5 w-3.5" />
      </Node>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className="min-w-0 text-sm font-semibold">
          <span className="font-mono text-xs text-muted-foreground">{job.number}</span> · {job.title}
        </p>
        {live ? (
          <span className="inline-flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.12em] text-accent">
            <span className="h-1.5 w-1.5 rounded-full bg-accent" />
            {t("maintenance.history.timeline.live")}
          </span>
        ) : (
          <span className="whitespace-nowrap text-xs text-muted-foreground">{formatDay(job.date ?? job.created_at)}</span>
        )}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <Badge variant={job.kind === "corrective" ? "destructive" : "primary"}>
          {t(JOB_KIND_LABEL_KEY[job.kind])}
          {job.priority === "urgent" ? ` · ${t(JOB_PRIORITY_LABEL_KEY.urgent)}` : ""}
        </Badge>
        {!live && <Badge variant={JOB_STATUS_BADGE_VARIANT[job.status]}>{t(JOB_STATUS_LABEL_KEY[job.status])}</Badge>}
        {job.chef_name && <span>{job.chef_name}</span>}
        {open ? (
          <span>{fill(t("maintenance.history.timeline.progress"), { done: job.checks_done, total: job.checks_total })}</span>
        ) : (
          <span>
            {fill(t("maintenance.history.journal.result"), {
              ok: job.outcomes.ok,
              issue: job.outcomes.issue,
              notDone: job.outcomes.not_done,
            })}
          </span>
        )}
        {job.technician_seconds > 0 && <span className="whitespace-nowrap tabular-nums">{formatDuration(job.technician_seconds / 60)}</span>}
        {partLines > 0 && (
          <span>
            {fill(t("maintenance.history.timeline.parts"), { n: partLines })}
            {job.parts_cost ? ` · ${formatXofWithCode(job.parts_cost)}` : ""}
          </span>
        )}
        {job.machine_stopped && <span>{t("maintenance.history.timeline.machineStopped")}</span>}
        {job.kind === "preventive" && job.closed_on_time !== null && (
          <span className={job.closed_on_time ? "text-success" : "text-destructive"}>
            {t(job.closed_on_time ? "maintenance.history.timeline.onTime" : "maintenance.history.timeline.late")}
          </span>
        )}
      </div>
    </Link>
  );
}

function StopEntry({ stop }: { stop: ProductionStopItem }) {
  const { t } = useI18n();
  const breakdown = stop.downtime_type === "corrective";
  return (
    <div className="relative rounded-lg border border-border bg-card px-3 py-2.5">
      <Node tone={breakdown ? "issue" : "default"}>
        <DowntimeIcon className="h-3.5 w-3.5" />
      </Node>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className="min-w-0 text-sm font-semibold">
          {t("maintenance.history.timeline.stop")}
          {stop.motif ? ` · ${downtimeLabel(t, "motif", stop.motif)}` : ""}
        </p>
        <span className="whitespace-nowrap text-xs text-muted-foreground">{formatDateTime(stop.started_at)}</span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {stop.downtime_type && (
          <Badge variant={breakdown ? "destructive" : "default"}>
            {downtimeLabel(t, "type", stop.downtime_type)}
            {stop.classification ? ` · ${downtimeLabel(t, "classification", stop.classification)}` : ""}
          </Badge>
        )}
        <span className="whitespace-nowrap tabular-nums">{formatDuration(stop.minutes)}</span>
        <span>
          {fill(t("maintenance.history.timeline.shift"), { date: formatDay(stop.report_date) })}
          {stop.team ? ` · ${stop.team}` : ""}
        </span>
        {stop.note && <span className="italic">“{stop.note}”</span>}
        {stop.corrective_action && <span>{fill(t("maintenance.history.timeline.correctiveAction"), { value: stop.corrective_action })}</span>}
      </div>
    </div>
  );
}

function StatusWord({ status }: { status: EquipmentStatus }) {
  const { t } = useI18n();
  return <span className={STATUS_TEXT[status]}>{t(`maintenance.equipment.status.${status}` as TranslationKey)}</span>;
}

function StatusEntry({ item }: { item: Extract<TimelineItem, { kind: "status_change" }> }) {
  const { t } = useI18n();
  const tone: Tone = item.to_status === "operational" ? "done" : item.to_status === "down" ? "issue" : "default";
  return (
    <div className="relative rounded-lg border border-border bg-card px-3 py-2.5">
      <Node tone={tone}>
        <StatusChangeIcon className="h-3.5 w-3.5" />
      </Node>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className="text-sm font-semibold">
          {t("maintenance.history.timeline.status")} <StatusWord status={item.from_status} /> → <StatusWord status={item.to_status} />
        </p>
        <span className="whitespace-nowrap text-xs text-muted-foreground">{formatDateTime(item.at)}</span>
      </div>
      {item.actor_name && <p className="mt-1 text-xs text-muted-foreground">{fill(t("maintenance.history.timeline.by"), { name: item.actor_name })}</p>}
    </div>
  );
}

export function HistoryTimeline({ items }: { items: TimelineItem[] }) {
  const { t } = useI18n();
  const reduce = useReducedMotion();
  const [filter, setFilter] = useState<TimelineFilter>("all");
  const visible = items.filter((item) => matches(item, filter));
  const months: [string, TimelineItem[]][] = [];
  for (const item of visible) {
    const key = monthKey(item.at);
    const last = months[months.length - 1];
    if (last && last[0] === key) last[1].push(item);
    else months.push([key, [item]]);
  }
  const monthLabel = (key: string) =>
    new Intl.DateTimeFormat(currentLocale(), { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(`${key}-01T00:00:00Z`));

  return (
    <div>
      <div className="flex items-baseline justify-between px-4 pb-2 pt-3">
        <h2 className="text-sm font-semibold">{t("maintenance.history.timeline.title")}</h2>
        <span className="text-xs text-muted-foreground">{t("maintenance.history.timeline.hint")}</span>
      </div>
      <div className="px-4 pb-3">
        <FilterTabs<TimelineFilter>
          options={FILTERS.map((value) => ({ value, label: t(`maintenance.history.timeline.filter.${value}` as const) }))}
          value={filter}
          onChange={setFilter}
        />
      </div>
      {visible.length === 0 ? (
        <EmptyState
          icon={<HistoryIcon className="h-5 w-5" />}
          illustration={<HistoryEmptyIllustration aria-hidden className="h-44 w-52" />}
          title={t("maintenance.history.timeline.empty.title")}
          description={t("maintenance.history.timeline.empty.description")}
        />
      ) : (
        <div className="relative pb-4 pl-12 pr-4">
          <span aria-hidden className="absolute bottom-6 left-[27px] top-2 w-0.5 bg-gradient-to-b from-accent via-border to-border" />
          {months.map(([key, group]) => (
            <section key={key} className="space-y-2">
              <p className="pt-2 text-[10px] font-bold uppercase tracking-[0.18em] text-muted-foreground">{monthLabel(key)}</p>
              {group.map((item, index) => (
                <motion.div
                  key={keyOf(item)}
                  initial={reduce ? false : { opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.45, ease: HISTORY_EASE, delay: Math.min(index, 8) * 0.07 }}
                >
                  {item.kind === "job" ? (
                    <JobEntry job={item.job} />
                  ) : item.kind === "production_stop" ? (
                    <StopEntry stop={item.stop} />
                  ) : (
                    <StatusEntry item={item} />
                  )}
                </motion.div>
              ))}
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
