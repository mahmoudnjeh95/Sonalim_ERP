import type { TranslationKey } from "../../../lib/i18n";
import { formatDuration } from "../../../lib/units";
import type { CheckEntry, JobCheck, JobDetail, Outcome } from "../api";

/**
 * The guided check's pure rules: which points the wizard walks through, what a
 * point still needs before it can be saved, and what the summary flags. Every
 * rule here mirrors one the API enforces (`modules/maintenance/domain/jobs.py`)
 * or one the spec gives the client (note required on Anomalie / Non fait).
 */

/** A point's timer, as wall-clock epoch milliseconds (so it survives a sleeping phone or a reload). */
export interface TimerState {
  startedAt: number;
  finishedAt: number | null;
}

export type TimerPhase = "idle" | "running" | "finished" | "manual";

/** What the chef has typed on one point and not saved yet. */
export interface StepDraft {
  /** `null` until the chef picks someone: the point's assignee (or the last person used) applies meanwhile. */
  performerId: string | null;
  outcome: Outcome | null;
  measure: string;
  note: string;
  photo: File | null;
  /** "Saisir la durée manuellement" instead of the timer. */
  manual: boolean;
  manualMinutes: string;
  /** "Refaire" on a point already recorded: a new entry will be posted. */
  redo: boolean;
}

export const EMPTY_DRAFT: StepDraft = {
  performerId: null,
  outcome: null,
  measure: "",
  note: "",
  photo: null,
  manual: false,
  manualMinutes: "",
  redo: false,
};

export type DraftField = "performer" | "timing" | "outcome" | "measure" | "note" | "photo";

/** Order the fields appear on screen, so the first error found is the first one on the page. */
export const DRAFT_FIELDS: readonly DraftField[] = ["performer", "timing", "outcome", "measure", "note", "photo"];

/**
 * The points the wizard walks through, in the job's order: every point not yet
 * accepted by a reviewer. Before the first review that is every point; in a
 * rework it is only the rejected ones (accepted points are locked by the API).
 * Points already recorded stay in the list so Précédent shows them, read-only,
 * with "Refaire".
 */
export function wizardStepIds(job: JobDetail): string[] {
  return job.checks.filter((check) => check.state !== "accepted").map((check) => check.id);
}

/** The latest entry of the point's current attempt — what the reviewer will judge. */
export function currentEntry(check: JobCheck): CheckEntry | null {
  for (let index = check.entries.length - 1; index >= 0; index -= 1) {
    if (check.entries[index].attempt === check.attempt) return check.entries[index];
  }
  return null;
}

/** True once the point has an entry for its current attempt (`done`, or `accepted` after review). */
export function isRecorded(check: JobCheck): boolean {
  return check.state !== "pending";
}

/** The first point still to record after `fromIndex` (exclusive), or -1. */
export function nextPendingIndex(steps: JobCheck[], fromIndex: number): number {
  for (let index = fromIndex + 1; index < steps.length; index += 1) {
    if (!isRecorded(steps[index])) return index;
  }
  return -1;
}

/** "2,5" or "2.5" -> 2.5; anything that is not a plain finite number -> null. French keypads type a comma. */
export function parseDecimal(text: string): number | null {
  const cleaned = text.trim().replace(/\s/g, "").replace(",", ".");
  if (!/^[-+]?(\d+\.?\d*|\.\d+)$/.test(cleaned)) return null;
  const value = Number(cleaned);
  return Number.isFinite(value) ? value : null;
}

export function timerPhase(draft: StepDraft, timer: TimerState | null): TimerPhase {
  if (draft.manual) return "manual";
  if (!timer) return "idle";
  return timer.finishedAt === null ? "running" : "finished";
}

/** The measure field is shown for a "Mesurer" point. */
export function needsMeasure(check: JobCheck): boolean {
  return check.action === "measure";
}

/**
 * What still stops a point from being saved, field by field, as i18n keys.
 * Same rules as the API's submit check (photo when `requires_photo`, a value
 * for a measure — both waived when the point was not done), plus the spec's
 * client-side rule: an Anomalie or a Non fait needs a note.
 */
export function validateDraft(
  check: JobCheck,
  draft: StepDraft,
  performerId: string,
  timer: TimerState | null,
): Partial<Record<DraftField, TranslationKey>> {
  const errors: Partial<Record<DraftField, TranslationKey>> = {};
  if (!performerId) errors.performer = "maintenance.wizard.error.performer";

  const phase = timerPhase(draft, timer);
  if (phase === "idle") errors.timing = "maintenance.wizard.error.timerNotStarted";
  else if (phase === "running") errors.timing = "maintenance.wizard.error.timerRunning";
  else if (phase === "manual") {
    const minutes = parseDecimal(draft.manualMinutes);
    if (minutes === null || minutes <= 0) errors.timing = "maintenance.wizard.error.minutes";
  } else if (timer && timer.finishedAt !== null && timer.finishedAt <= timer.startedAt) {
    errors.timing = "maintenance.wizard.error.timerNotStarted";
  }

  if (!draft.outcome) {
    errors.outcome = "maintenance.wizard.error.outcome";
    return errors;
  }
  const done = draft.outcome !== "not_done";
  if (needsMeasure(check) && done && parseDecimal(draft.measure) === null) {
    errors.measure = "maintenance.wizard.error.measure";
  } else if (draft.measure.trim() && parseDecimal(draft.measure) === null) {
    errors.measure = "maintenance.wizard.error.measureInvalid";
  }
  if (draft.outcome !== "ok" && !draft.note.trim()) errors.note = "maintenance.wizard.error.note";
  if (check.requires_photo && done && !draft.photo) errors.photo = "maintenance.wizard.error.photo";
  return errors;
}

/** True when leaving now would lose something the chef typed or picked on a point. */
export function draftHasInput(draft: StepDraft): boolean {
  return (
    draft.outcome !== null ||
    draft.measure.trim() !== "" ||
    draft.note.trim() !== "" ||
    draft.photo !== null ||
    draft.manualMinutes.trim() !== ""
  );
}

/**
 * A recorded duration spelled out ("14 min 5 s", "1 h 26 min"): next to a performer's name a bare
 * "14:05" reads like a time of day. The running stopwatch keeps `mm:ss`.
 */
export function formatSpan(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} s`;
  if (total < 3600) return `${Math.floor(total / 60)} min${total % 60 ? ` ${total % 60} s` : ""}`;
  return formatDuration(total / 60);
}

/** A recorded point whose entry lacks the proof the API's submit will ask for (so the chef redoes it before submitting). */
export function missingProof(check: JobCheck): "photo" | "measure" | null {
  const entry = currentEntry(check);
  if (!entry || entry.outcome === "not_done") return null;
  if (check.requires_photo && !entry.has_photo) return "photo";
  if (needsMeasure(check) && entry.measured_value === null) return "measure";
  return null;
}
