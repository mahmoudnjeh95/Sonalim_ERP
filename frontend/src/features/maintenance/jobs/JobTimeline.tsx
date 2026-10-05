import type { ReactNode } from "react";
import {
  AlarmClock,
  CheckCircle2,
  CircleDot,
  ClipboardCheck,
  Lock,
  PackageCheck,
  PackagePlus,
  PackageX,
  Play,
  PlusCircle,
  RotateCcw,
  Send,
  UserCheck,
  Users,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { humanizeSnakeCase } from "../../../lib/humanize";
import { cn } from "../../../lib/utils";
import type { JobEvent, Outcome } from "../api";
import { OUTCOME_LABEL_KEY } from "../labels";
import { formatClock, formatDateTime, formatDay, formatRelativeTime } from "./jobFormat";

type Tone = "neutral" | "primary" | "success" | "warning" | "destructive";

interface KindMeta {
  icon: LucideIcon;
  labelKey: TranslationKey;
  tone: Tone;
}

/** The event kinds the backend writes to `maintenance.job_events`; an unknown kind still renders, with a neutral dot. */
const KIND_META: Record<string, KindMeta> = {
  created: { icon: PlusCircle, labelKey: "maintenance.jobs.timeline.kind.created", tone: "neutral" },
  assigned: { icon: UserCheck, labelKey: "maintenance.jobs.timeline.kind.assigned", tone: "primary" },
  delegated: { icon: Users, labelKey: "maintenance.jobs.timeline.kind.delegated", tone: "primary" },
  started: { icon: Play, labelKey: "maintenance.jobs.timeline.kind.started", tone: "warning" },
  check_done: { icon: CheckCircle2, labelKey: "maintenance.jobs.timeline.kind.check_done", tone: "primary" },
  submitted: { icon: Send, labelKey: "maintenance.jobs.timeline.kind.submitted", tone: "primary" },
  reviewed: { icon: ClipboardCheck, labelKey: "maintenance.jobs.timeline.kind.reviewed", tone: "success" },
  rework: { icon: RotateCcw, labelKey: "maintenance.jobs.timeline.kind.rework", tone: "destructive" },
  closed: { icon: Lock, labelKey: "maintenance.jobs.timeline.kind.closed", tone: "success" },
  cancelled: { icon: XCircle, labelKey: "maintenance.jobs.timeline.kind.cancelled", tone: "destructive" },
  overdue_notified: { icon: AlarmClock, labelKey: "maintenance.jobs.timeline.kind.overdue_notified", tone: "destructive" },
  parts_requested: { icon: PackagePlus, labelKey: "maintenance.jobs.timeline.kind.parts_requested", tone: "primary" },
  parts_approved: { icon: PackageCheck, labelKey: "maintenance.jobs.timeline.kind.parts_approved", tone: "success" },
  parts_rejected: { icon: PackageX, labelKey: "maintenance.jobs.timeline.kind.parts_rejected", tone: "destructive" },
};

const TONE_CLASS: Record<Tone, string> = {
  neutral: "bg-muted text-muted-foreground",
  primary: "bg-primary/10 text-primary",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  destructive: "bg-destructive-soft text-destructive",
};

// The payload is free-form JSON (`Record<string, unknown>`): read it defensively
// so an event written by a newer backend never breaks the page.
function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function records(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null);
}

const OUTCOMES: readonly string[] = ["ok", "issue", "not_done"];

function isOutcome(value: unknown): value is Outcome {
  return typeof value === "string" && OUTCOMES.includes(value);
}

/** What happened, in one or a few short lines, read from the event's payload. Null when the kind says it all. */
function PayloadSummary({ event }: { event: JobEvent }): ReactNode {
  const { t } = useI18n();
  const { payload } = event;

  switch (event.kind) {
    case "created": {
      const checks = count(payload.checks);
      const due = text(payload.due_date);
      const parts = [
        checks !== null ? t("maintenance.jobs.timeline.summary.checks").replace("{count}", String(checks)) : null,
        due ? t("maintenance.jobs.timeline.summary.due").replace("{date}", formatDay(due)) : null,
      ].filter(Boolean);
      return parts.length > 0 ? parts.join(" · ") : null;
    }
    case "assigned": {
      const chef = text(payload.chef_name);
      const team = text(payload.team_name);
      const parts = [
        chef ? t("maintenance.jobs.timeline.summary.chef").replace("{name}", chef) : null,
        team ? t("maintenance.jobs.timeline.summary.team").replace("{name}", team) : null,
      ].filter(Boolean);
      return parts.length > 0 ? parts.join(" · ") : null;
    }
    case "delegated": {
      const assignments = records(payload.assignments);
      if (assignments.length === 0) return null;
      return (
        <ul className="space-y-0.5">
          {assignments.map((assignment, index) => (
            <li key={text(assignment.check_id) ?? index}>
              {text(assignment.label) ?? "—"} → {text(assignment.employee_name) ?? t("maintenance.jobs.unassigned")}
            </li>
          ))}
        </ul>
      );
    }
    case "started":
      return payload.equipment_stopped === true ? t("maintenance.jobs.timeline.summary.machineStopped") : null;
    case "check_done": {
      const duration = count(payload.duration_seconds);
      const parts = [
        text(payload.label),
        isOutcome(payload.outcome) ? t(OUTCOME_LABEL_KEY[payload.outcome]) : null,
        text(payload.performer_name),
        duration !== null ? formatClock(duration) : null,
      ].filter(Boolean);
      return parts.length > 0 ? parts.join(" · ") : null;
    }
    case "reviewed":
    case "rework": {
      const accepted = records(payload.accepted);
      const rejected = records(payload.rejected);
      if (accepted.length === 0 && rejected.length === 0) return null;
      return (
        <div className="space-y-0.5">
          {accepted.length > 0 && (
            <p>{t("maintenance.jobs.timeline.summary.accepted").replace("{count}", String(accepted.length))}</p>
          )}
          {rejected.length > 0 && (
            <ul className="space-y-0.5">
              {rejected.map((item, index) => (
                <li key={text(item.check_id) ?? index} className="text-destructive">
                  {text(item.label) ?? "—"}
                  {text(item.reason) ? ` — ${text(item.reason)}` : ""}
                </li>
              ))}
            </ul>
          )}
        </div>
      );
    }
    case "closed":
      return payload.equipment_restarted === true ? t("maintenance.jobs.timeline.summary.machineRestarted") : null;
    case "cancelled": {
      const reason = text(payload.reason);
      const machine =
        payload.equipment_status === "down"
          ? t("maintenance.jobs.timeline.summary.machineBackDown")
          : payload.equipment_restarted === true
            ? t("maintenance.jobs.timeline.summary.machineRestarted")
            : null;
      return [reason, machine].filter(Boolean).join(" · ") || null;
    }
    default:
      return null;
  }
}

/**
 * The job's history (`JobDetail.timeline`), newest first: an icon per kind,
 * who did it, how long ago (exact date on hover) and a short summary read from
 * the event payload.
 */
export function JobTimeline({ events }: { events: JobEvent[] }) {
  const { t } = useI18n();
  if (events.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("maintenance.jobs.timeline.empty")}</p>;
  }
  // The API sends the events oldest first; a history reads best with the latest on top.
  const ordered = [...events].reverse();

  return (
    <ol className="space-y-0">
      {ordered.map((event, index) => {
        const meta = KIND_META[event.kind];
        const Icon = meta?.icon ?? CircleDot;
        const isLast = index === ordered.length - 1;
        return (
          <li key={event.id} className="relative flex gap-3 pb-5 last:pb-0">
            {!isLast && <span className="absolute left-4 top-8 h-[calc(100%-2rem)] w-px bg-border" aria-hidden />}
            <span
              className={cn(
                "relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
                TONE_CLASS[meta?.tone ?? "neutral"],
              )}
            >
              <Icon className="h-4 w-4" />
            </span>
            <div className="min-w-0 flex-1 pt-0.5">
              <p className="text-sm font-medium">{meta ? t(meta.labelKey) : humanizeSnakeCase(event.kind)}</p>
              <p className="text-xs text-muted-foreground">
                {event.actor_name ?? t("maintenance.jobs.timeline.system")}
                {" · "}
                <time dateTime={event.at} title={formatDateTime(event.at)}>
                  {formatRelativeTime(event.at)}
                </time>
              </p>
              <div className="mt-1 break-words text-sm text-muted-foreground empty:hidden">
                <PayloadSummary event={event} />
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
