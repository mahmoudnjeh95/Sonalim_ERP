import { ApiError } from "../../lib/api";
import { currentLocale } from "../../lib/i18n";
import type { ScheduleDay } from "./presenceApi";

const pad = (value: number) => String(value).padStart(2, "0");

/** 420 -> "07:00". */
export function minutesToClock(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "";
  return `${pad(Math.floor(minutes / 60) % 24)}:${pad(minutes % 60)}`;
}

/** "07:00" -> 420; anything else -> null. */
export function clockToMinutes(value: string): number | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(value.trim());
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  return hours < 24 && minutes < 60 ? hours * 60 + minutes : null;
}

/** 485 -> "8 h 05", 480 -> "8 h", 0 -> "0". */
export function formatDuration(minutes: number): string {
  if (!minutes) return "0";
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} h ${pad(rest)}` : `${hours} h`;
}

export function spanMinutes(day: ScheduleDay): number {
  return (day.end_minute - day.start_minute + 1440) % 1440;
}

function fromIso(iso: string): Date {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

export function todayIso(): string {
  const now = new Date();
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function addDaysIso(iso: string, days: number): string {
  const date = fromIso(iso);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/** Monday = 0 ... Sunday = 6, the backend's convention. */
export function weekdayOf(iso: string): number {
  return (fromIso(iso).getUTCDay() + 6) % 7;
}

export function mondayOf(iso: string): string {
  return addDaysIso(iso, -weekdayOf(iso));
}

/** "2026-08-17" -> "2026-08-01". */
export function monthStartOf(iso: string): string {
  return `${iso.slice(0, 7)}-01`;
}

/** "2026-08-03" -> "lun. 03 août" / "Mon, Aug 03", in the app's language. */
export function formatDay(iso: string): string {
  return new Intl.DateTimeFormat(currentLocale(), { weekday: "short", day: "2-digit", month: "short", timeZone: "UTC" }).format(fromIso(iso));
}

/** "2026-08-01" -> "août 2026" / "August 2026". */
export function formatMonth(iso: string): string {
  return new Intl.DateTimeFormat(currentLocale(), { month: "long", year: "numeric", timeZone: "UTC" }).format(fromIso(iso));
}

export function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export function employeeLabel(employee: { employee_no: string; first_name: string; last_name: string }): string {
  return `${employee.employee_no} · ${employee.first_name} ${employee.last_name}`;
}
