import { motion } from "framer-motion";
import { AlertTriangle, Ban, CheckCircle2, ChevronRight, ClipboardList, Clock, Timer, type LucideIcon } from "lucide-react";
import { Badge } from "../../../components/ui/badge";
import { useI18n } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import type { JobCheck, JobDetail, Outcome } from "../api";
import { OUTCOME_LABEL_KEY } from "../labels";
import { currentEntry, formatSpan, isRecorded, missingProof, type TimerState } from "./wizardModel";

const OUTCOME_ICON: Record<Outcome, LucideIcon> = { ok: CheckCircle2, issue: AlertTriangle, not_done: Ban };

const OUTCOME_TEXT: Record<Outcome, string> = {
  ok: "text-success",
  issue: "text-destructive",
  not_done: "text-muted-foreground",
};

const PIN: Record<Outcome | "pending", string> = {
  ok: "border-success bg-success text-success-foreground",
  issue: "border-destructive bg-destructive text-destructive-foreground",
  not_done: "border-foreground/70 bg-foreground/70 text-background",
  pending: "border-border bg-muted text-muted-foreground",
};

function Stat({ label, value, tone, icon: Icon }: { label: string; value: string; tone?: "danger"; icon: LucideIcon }) {
  return (
    <div className={cn("rounded-xl border bg-background p-3 shadow-soft", tone === "danger" ? "border-destructive/30" : "border-border")}>
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        <span className="truncate">{label}</span>
      </p>
      <p className={cn("mt-1 whitespace-nowrap text-xl font-semibold tabular-nums", tone === "danger" && "text-destructive")}>{value}</p>
    </div>
  );
}

/**
 * The wizard's last screen: every point walked with its outcome, duration and performer, the
 * total time, anomalies highlighted, and what is still to record. A row reopens its point.
 * Submitting is the wizard's bottom bar, enabled once nothing is left to record.
 */
export function WizardSummary({
  job,
  steps,
  numbers,
  timers,
  onOpenStep,
}: {
  job: JobDetail;
  steps: JobCheck[];
  /** The point's number on the job (its row in the checks table). */
  numbers: Map<string, number>;
  timers: Record<string, TimerState>;
  onOpenStep: (index: number) => void;
}) {
  const { t } = useI18n();
  const recorded = steps.filter(isRecorded);
  const pendingCount = steps.length - recorded.length;
  const totalSeconds = recorded.reduce((sum, check) => sum + (currentEntry(check)?.duration_seconds ?? 0), 0);
  const issues = recorded.filter((check) => currentEntry(check)?.outcome === "issue").length;
  const notDone = recorded.filter((check) => currentEntry(check)?.outcome === "not_done").length;
  const acceptedCount = job.checks.length - steps.length;
  const allDone = pendingCount === 0;

  return (
    <div className="space-y-4">
      <motion.div
        initial={{ opacity: 0, scale: 0.97 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.25 }}
        className={cn(
          "flex items-center gap-4 rounded-xl border p-4",
          allDone ? "border-success/30 bg-success-soft" : "border-warning/30 bg-warning-soft",
        )}
      >
        <motion.span
          initial={{ scale: 0.5, rotate: -20 }}
          animate={{ scale: 1, rotate: 0 }}
          transition={{ type: "spring", stiffness: 320, damping: 16, delay: 0.05 }}
          className={cn(
            "flex h-12 w-12 shrink-0 items-center justify-center rounded-full",
            allDone ? "bg-success text-success-foreground" : "bg-warning text-warning-foreground",
          )}
        >
          {allDone ? <CheckCircle2 className="h-7 w-7" /> : <ClipboardList className="h-6 w-6" />}
        </motion.span>
        <div className="min-w-0">
          <p className={cn("font-semibold", allDone ? "text-success" : "text-warning")}>
            {allDone
              ? t("maintenance.wizard.summary.allDone")
              : t("maintenance.wizard.summary.remaining").replace("{count}", String(pendingCount))}
          </p>
          <p className="text-sm text-foreground/80">
            {allDone ? t("maintenance.wizard.summary.allDoneHint") : t("maintenance.wizard.summary.remainingHint")}
          </p>
        </div>
      </motion.div>

      <div className="grid grid-cols-[1fr_1.45fr_1fr] gap-2">
        <Stat icon={ClipboardList} label={t("maintenance.wizard.summary.points")} value={`${recorded.length}/${steps.length}`} />
        <Stat icon={Clock} label={t("maintenance.wizard.summary.totalTime")} value={formatSpan(totalSeconds)} />
        <Stat
          icon={AlertTriangle}
          label={t("maintenance.wizard.summary.issues")}
          value={String(issues)}
          tone={issues > 0 ? "danger" : undefined}
        />
      </div>
      {notDone > 0 && (
        <p className="text-sm text-muted-foreground">{t("maintenance.wizard.summary.notDone").replace("{count}", String(notDone))}</p>
      )}
      {acceptedCount > 0 && (
        <p className="text-sm text-muted-foreground">
          {t("maintenance.wizard.summary.acceptedKept").replace("{count}", String(acceptedCount))}
        </p>
      )}

      <ul className="space-y-2">
        {steps.map((check, index) => {
          const entry = currentEntry(check);
          const done = isRecorded(check) && entry !== null;
          const outcome = done ? entry.outcome : null;
          const proof = done ? missingProof(check) : null;
          const timer = timers[check.id];
          const OutcomeIcon = outcome ? OUTCOME_ICON[outcome] : null;
          return (
            <motion.li
              key={check.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: Math.min(index, 12) * 0.03 }}
            >
              <button
                type="button"
                onClick={() => onOpenStep(index)}
                className={cn(
                  "flex w-full items-start gap-3 rounded-xl border bg-background p-3 text-left shadow-soft transition-colors hover:border-primary/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  outcome === "issue" ? "border-destructive/40 bg-destructive-soft/60" : "border-border",
                  !done && "border-dashed",
                )}
              >
                <span
                  className={cn(
                    "flex h-9 w-9 shrink-0 items-center justify-center rounded-full border-2 text-sm font-semibold",
                    PIN[outcome ?? "pending"],
                  )}
                >
                  {numbers.get(check.id)}
                </span>
                <span className="min-w-0 flex-1 space-y-1">
                  <span className="block break-words font-medium leading-snug">{check.label}</span>
                  {done ? (
                    <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
                      <span>{entry.performer_name}</span>
                      <span aria-hidden>·</span>
                      <span className="tabular-nums">{formatSpan(entry.duration_seconds)}</span>
                      {entry.duration_source === "manual" && <Badge variant="outline">{t("maintenance.jobs.entry.manual")}</Badge>}
                    </span>
                  ) : (
                    <span className="flex flex-wrap items-center gap-2 text-sm">
                      <Badge variant="warning">{t("maintenance.wizard.summary.todo")}</Badge>
                      {timer && (
                        <Badge variant="accent">
                          <Timer className="h-3 w-3" />
                          {timer.finishedAt === null ? t("maintenance.wizard.summary.timerRunning") : t("maintenance.wizard.summary.timerStopped")}
                        </Badge>
                      )}
                    </span>
                  )}
                  {done && entry.note && outcome !== "ok" && (
                    <span className="block whitespace-pre-wrap break-words text-sm text-foreground">{entry.note}</span>
                  )}
                  {proof && (
                    <span className="flex items-center gap-1.5 text-sm font-medium text-destructive">
                      <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                      {proof === "photo" ? t("maintenance.wizard.summary.missingPhoto") : t("maintenance.wizard.summary.missingMeasure")}
                    </span>
                  )}
                </span>
                {OutcomeIcon && outcome ? (
                  <span className={cn("flex shrink-0 items-center gap-1 whitespace-nowrap pt-1.5 text-sm font-semibold", OUTCOME_TEXT[outcome])}>
                    <OutcomeIcon className="h-4 w-4" />
                    {t(OUTCOME_LABEL_KEY[outcome])}
                  </span>
                ) : (
                  <ChevronRight className="mt-2 h-5 w-5 shrink-0 text-muted-foreground" />
                )}
              </button>
            </motion.li>
          );
        })}
      </ul>

    </div>
  );
}
