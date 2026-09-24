import { currentLocale } from "../../../lib/i18n";

/** Local calendar day as YYYY-MM-DD. Not toISOString(): that is UTC and can name the wrong day. */
export function isoDay(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

export function addDays(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00`);
  date.setDate(date.getDate() + days);
  return isoDay(date);
}

export function clockTime(date: Date): string {
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

export function formatNumber(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat(currentLocale(), { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(value);
}

export function formatDay(iso: string, options: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" }): string {
  return new Intl.DateTimeFormat(currentLocale(), options).format(new Date(`${iso}T00:00:00`));
}

/** The three teams' colours are the ones the repo's shift-team illustration uses. */
export const SHIFT_COLORS = ["#173A63", "#35A66F", "#E6A52E"] as const;

export function shiftColor(index: number): string {
  return SHIFT_COLORS[index % SHIFT_COLORS.length];
}

/** Minutes since midnight for "HH:MM". */
export function minutesOfDay(hhmm: string): number {
  const [hours, minutes] = hhmm.split(":").map(Number);
  return hours * 60 + minutes;
}

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}
