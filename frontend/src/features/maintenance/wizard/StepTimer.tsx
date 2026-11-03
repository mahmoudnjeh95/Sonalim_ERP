import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Keyboard, Play, RotateCcw, Square, Timer } from "lucide-react";
import { useI18n } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { formatClock, formatTime } from "../jobs/jobFormat";
import type { TimerPhase, TimerState } from "./wizardModel";

const STORAGE_PREFIX = "sonalim-erp.maintenance.wizard-timers.";

function readTimers(jobId: string): Record<string, TimerState> {
  try {
    const raw = sessionStorage.getItem(STORAGE_PREFIX + jobId);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, TimerState>;
    const timers: Record<string, TimerState> = {};
    for (const [checkId, value] of Object.entries(parsed ?? {})) {
      if (value && typeof value.startedAt === "number" && (value.finishedAt === null || typeof value.finishedAt === "number")) {
        timers[checkId] = { startedAt: value.startedAt, finishedAt: value.finishedAt };
      }
    }
    return timers;
  } catch {
    return {};
  }
}

function writeTimers(jobId: string, timers: Record<string, TimerState>) {
  try {
    if (Object.keys(timers).length === 0) sessionStorage.removeItem(STORAGE_PREFIX + jobId);
    else sessionStorage.setItem(STORAGE_PREFIX + jobId, JSON.stringify(timers));
  } catch {
    // Storage blocked (private mode): the timer still runs, it just won't survive a reload.
  }
}

/**
 * Every point's timer on one job, kept in `sessionStorage` (`{checkId: {startedAt, finishedAt}}`)
 * so a reload or a sleeping phone loses nothing: the elapsed time is always recomputed from
 * the wall-clock start. Several points can run at once — two technicians on two points.
 */
export function useWizardTimers(jobId: string) {
  const [timers, setTimers] = useState<Record<string, TimerState>>(() => readTimers(jobId));

  useEffect(() => {
    setTimers(readTimers(jobId));
  }, [jobId]);

  const update = useCallback(
    (change: (current: Record<string, TimerState>) => Record<string, TimerState>) => {
      setTimers((current) => {
        const next = change(current);
        writeTimers(jobId, next);
        return next;
      });
    },
    [jobId],
  );

  return {
    timers,
    start: useCallback((checkId: string) => update((current) => ({ ...current, [checkId]: { startedAt: Date.now(), finishedAt: null } })), [update]),
    finish: useCallback(
      (checkId: string) =>
        update((current) => {
          const timer = current[checkId];
          if (!timer || timer.finishedAt !== null) return current;
          return { ...current, [checkId]: { ...timer, finishedAt: Date.now() } };
        }),
      [update],
    ),
    clear: useCallback(
      (checkId: string) =>
        update((current) => {
          if (!(checkId in current)) return current;
          const next = { ...current };
          delete next[checkId];
          return next;
        }),
      [update],
    ),
    clearAll: useCallback(() => update(() => ({})), [update]),
  };
}

/** Re-renders while `active`, so a running clock ticks. The time shown is always `now - startedAt`. */
export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const handle = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(handle);
  }, [active]);
  return now;
}

interface StepTimerProps {
  phase: TimerPhase;
  timer: TimerState | null;
  manualMinutes: string;
  onReset: () => void;
  onManualChange: (manual: boolean) => void;
  onManualMinutesChange: (value: string) => void;
  error?: string;
  disabled?: boolean;
}

const LINK_CLASS =
  "inline-flex min-h-11 items-center gap-1.5 rounded-md px-2 text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";

/**
 * The point's stopwatch face: the big `mm:ss` (idle, running from the wall-clock start, then
 * frozen at Terminé), its start/end times, "Remettre le chrono à zéro" and "Saisir la durée
 * manuellement", which swaps it for a minutes field (the entry is then flagged as typed by hand).
 * Its big Démarrer / Terminé button is `TimerActionButton`, which the wizard keeps in the sticky
 * bottom bar so it is always under the thumb. The wizard owns the state (`useWizardTimers`).
 */
export function StepTimer({ phase, timer, manualMinutes, onReset, onManualChange, onManualMinutesChange, error, disabled }: StepTimerProps) {
  const { t } = useI18n();
  const now = useNow(phase === "running");
  const elapsedSeconds = timer ? ((timer.finishedAt ?? now) - timer.startedAt) / 1000 : 0;

  if (phase === "manual") {
    return (
      <div className={cn("rounded-xl border bg-background p-4 shadow-soft", error ? "border-destructive" : "border-border")}>
        <label htmlFor="wizard-manual-minutes" className="flex items-center gap-2 text-sm font-medium">
          <Keyboard className="h-4 w-4 text-muted-foreground" />
          {t("maintenance.wizard.timer.minutes")}
        </label>
        <div className="mt-3 flex items-center gap-3">
          <input
            id="wizard-manual-minutes"
            type="text"
            inputMode="decimal"
            autoComplete="off"
            value={manualMinutes}
            disabled={disabled}
            onChange={(event) => onManualMinutesChange(event.target.value)}
            placeholder="0"
            aria-invalid={error ? true : undefined}
            className="h-14 w-full min-w-0 rounded-lg border border-border bg-background px-4 text-center text-3xl font-semibold tabular-nums shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <span className="shrink-0 text-lg font-medium text-muted-foreground">{t("maintenance.wizard.timer.minutesUnit")}</span>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">{t("maintenance.wizard.timer.manualHint")}</p>
        {error && (
          <p className="mt-2 text-sm font-medium text-destructive" role="alert">
            {error}
          </p>
        )}
        <div className="mt-1 flex justify-center">
          <button type="button" className={LINK_CLASS} onClick={() => onManualChange(false)} disabled={disabled}>
            <Timer className="h-4 w-4" />
            {t("maintenance.wizard.timer.useTimer")}
          </button>
        </div>
      </div>
    );
  }

  const running = phase === "running";
  const finished = phase === "finished";

  return (
    <div
      className={cn(
        "overflow-hidden rounded-xl border bg-background shadow-soft transition-colors",
        error ? "border-destructive" : running ? "border-accent" : finished ? "border-success/40" : "border-border",
      )}
    >
      <div className={cn("px-4 pb-4 pt-4 text-center transition-colors", running && "bg-accent/10", finished && "bg-success-soft")}>
        <div className="flex min-h-5 items-center justify-center gap-2 text-sm font-medium text-muted-foreground">
          {running ? (
            <>
              <motion.span
                className="h-2.5 w-2.5 rounded-full bg-destructive"
                animate={{ opacity: [1, 0.25, 1] }}
                transition={{ duration: 1.2, repeat: Infinity }}
                aria-hidden
              />
              <span className="text-foreground">
                {t("maintenance.wizard.timer.running").replace("{time}", formatTime(new Date(timer!.startedAt).toISOString()))}
              </span>
            </>
          ) : finished ? (
            <>
              <CheckCircle2 className="h-4 w-4 text-success" />
              <span className="text-success">
                {t("maintenance.wizard.timer.finished")
                  .replace("{start}", formatTime(new Date(timer!.startedAt).toISOString()))
                  .replace("{end}", formatTime(new Date(timer!.finishedAt!).toISOString()))}
              </span>
            </>
          ) : (
            <>
              <Timer className="h-4 w-4" />
              <span>{t("maintenance.wizard.timer.ready")}</span>
            </>
          )}
        </div>
        <p
          className={cn(
            "mt-2 text-6xl font-semibold leading-none tabular-nums tracking-tight",
            phase === "idle" ? "text-muted-foreground/40" : finished ? "text-success" : "text-foreground",
          )}
          role="timer"
          aria-live={running ? "off" : "polite"}
        >
          {formatClock(elapsedSeconds)}
        </p>
      </div>
      {error && (
        <p className="border-t border-destructive/20 bg-destructive-soft px-4 py-2 text-center text-sm font-medium text-destructive" role="alert">
          {error}
        </p>
      )}
      <div className="flex flex-wrap items-center justify-center gap-x-2 border-t border-border px-2 py-1">
        {phase !== "idle" && (
          <button type="button" className={LINK_CLASS} onClick={onReset} disabled={disabled}>
            <RotateCcw className="h-4 w-4" />
            {t("maintenance.wizard.timer.reset")}
          </button>
        )}
        <button type="button" className={LINK_CLASS} onClick={() => onManualChange(true)} disabled={disabled}>
          <Keyboard className="h-4 w-4" />
          {t("maintenance.wizard.timer.manual")}
        </button>
      </div>
    </div>
  );
}

/**
 * The timer's big button — Démarrer (amber), then Terminé with the running `mm:ss` (navy).
 * The wizard puts it in the sticky bottom bar, under the thumb, whatever the scroll position.
 */
export function TimerActionButton({
  phase,
  timer,
  onStart,
  onFinish,
  disabled,
}: {
  phase: "idle" | "running";
  timer: TimerState | null;
  onStart: () => void;
  onFinish: () => void;
  disabled?: boolean;
}) {
  const { t } = useI18n();
  const now = useNow(phase === "running");
  const elapsedSeconds = timer ? (now - timer.startedAt) / 1000 : 0;

  return (
    <AnimatePresence mode="wait" initial={false}>
      {phase === "idle" ? (
        <motion.button
          key="start"
          type="button"
          onClick={onStart}
          disabled={disabled}
          initial={{ opacity: 0, scale: 0.96 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.96 }}
          transition={{ duration: 0.12 }}
          whileTap={{ scale: 0.97 }}
          className="flex h-14 min-w-0 flex-1 items-center justify-center gap-2.5 rounded-xl bg-accent px-4 text-lg font-bold text-accent-foreground shadow-glow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50"
        >
          <Play className="h-5 w-5 shrink-0 fill-current" />
          <span className="truncate">{t("maintenance.wizard.timer.start")}</span>
        </motion.button>
      ) : (
        <motion.button
          key="finish"
          type="button"
          onClick={onFinish}
          disabled={disabled}
          initial={{ opacity: 0, scale: 0.96 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.96 }}
          transition={{ duration: 0.12 }}
          whileTap={{ scale: 0.97 }}
          className="flex h-14 min-w-0 flex-1 items-center justify-center gap-2.5 rounded-xl bg-primary px-4 text-lg font-bold text-primary-foreground shadow-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50"
        >
          <Square className="h-4 w-4 shrink-0 fill-current" />
          <span className="truncate">{t("maintenance.wizard.timer.finish")}</span>
          <span className="shrink-0 rounded-md bg-white/15 px-2 py-0.5 text-base font-semibold tabular-nums">{formatClock(elapsedSeconds)}</span>
        </motion.button>
      )}
    </AnimatePresence>
  );
}
