import { ApiError } from "../../../lib/api";
import { currentLocale } from "../../../lib/i18n";
import type { CheckEntry, JobCheck, JobStatus } from "../api";
import type { PinTone } from "../map/PinnedPhoto";

/**
 * Formatting and small derivations shared by the jobs list, the job page, the
 * review panel and the timeline (and reusable by the wizard). Nothing here
 * decides anything: every rule mirrors what the API already enforces
 * (`modules/maintenance/domain/jobs.py`).
 */

const pad = (value: number) => String(value).padStart(2, "0");

/** Today as `YYYY-MM-DD` in the user's own timezone (what a date input expects). */
export function todayIso(): string {
  const now = new Date();
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** "2026-10-01" -> "1 oct. 2026". Built in UTC so a date-only value never slips a day with the timezone. */
export function formatDay(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  if (!year || !month || !day) return iso;
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString(currentLocale(), {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** An ISO timestamp as a local date + time: "1 oct. 2026, 14:05". */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(currentLocale(), {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** An ISO timestamp as a local time of day: "14:05". */
export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString(currentLocale(), { hour: "2-digit", minute: "2-digit" });
}

/** Seconds as `mm:ss` (minutes keep counting past the hour: 3725 s -> "62:05"). */
export function formatClock(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const total = Math.max(0, Math.round(seconds));
  return `${pad(Math.floor(total / 60))}:${pad(total % 60)}`;
}

/** A measured value in the app's number format, followed by the point's unit as it was typed ("2,5 bar"). */
export function formatMeasure(value: number | null | undefined, unit: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const formatted = new Intl.NumberFormat(currentLocale(), { maximumFractionDigits: 3 }).format(value);
  return unit ? `${formatted} ${unit}` : formatted;
}

const RELATIVE_UNITS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ["year", 60 * 60 * 24 * 365],
  ["month", 60 * 60 * 24 * 30],
  ["week", 60 * 60 * 24 * 7],
  ["day", 60 * 60 * 24],
  ["hour", 60 * 60],
  ["minute", 60],
];

/** "il y a 3 heures" / "3 hours ago", in the app's language (same wording as the notification bell). */
export function formatRelativeTime(iso: string): string {
  const deltaSeconds = (new Date(iso).getTime() - Date.now()) / 1000;
  const formatter = new Intl.RelativeTimeFormat(currentLocale(), { numeric: "auto" });
  for (const [unit, secondsInUnit] of RELATIVE_UNITS) {
    if (Math.abs(deltaSeconds) >= secondsInUnit) {
      return formatter.format(Math.round(deltaSeconds / secondsInUnit), unit);
    }
  }
  return formatter.format(Math.round(deltaSeconds), "second");
}

/** The API's own wording (already in the user's language: `message_fr` for a French user), else the given fallback. */
export function apiErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError && error.message ? error.message : fallback;
}

/** The statuses in which the chef works a job: delegate, record entries, request parts. */
export const WORKABLE_STATUSES: readonly JobStatus[] = ["assigned", "in_progress", "rework"];

/** The most recent entry of a check, whatever its attempt (entries come oldest first). */
export function latestEntry(check: JobCheck): CheckEntry | null {
  return check.entries.length > 0 ? check.entries[check.entries.length - 1] : null;
}

/** True for a point a reviewer rejected and that is waiting to be redone (a reject reopens it as `pending` on the next attempt). */
export function isRedo(check: JobCheck): boolean {
  return check.state === "pending" && check.attempt > 1;
}

/** The latest rejection of a check, for "why does this need redoing". */
export function latestRejection(check: JobCheck) {
  for (let index = check.reviews.length - 1; index >= 0; index -= 1) {
    if (check.reviews[index].verdict === "rejected") return check.reviews[index];
  }
  return null;
}

/**
 * Pin colour on the job page's photos, by the point's state:
 * grey = still to do, red = rejected and to redo, blue = done (awaiting
 * review), green = accepted.
 */
export function checkPinTone(check: JobCheck): PinTone {
  if (check.state === "accepted") return "done";
  if (check.state === "done") return "default";
  return isRedo(check) || check.state === "rejected" ? "issue" : "dim";
}
