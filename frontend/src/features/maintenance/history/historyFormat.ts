import { formatDuration } from "../../../lib/units";

/** Replaces every `{name}` of a translated string; an unknown placeholder is left as it is. */
export function fill(text: string, values: Record<string, string | number>): string {
  return text.replace(/\{(\w+)\}/g, (match, name: string) => (name in values ? String(values[name]) : match));
}

/** A duration in minutes, or "—" for a figure that cannot be computed (e.g. MTBF with no breakdown). */
export function minutesOrDash(minutes: number | null | undefined): string {
  return minutes === null || minutes === undefined ? "—" : formatDuration(minutes);
}

/** "2026-09-28T09:40:00+00:00" -> "2026-09": the timeline's month group. */
export function monthKey(iso: string): string {
  return iso.slice(0, 7);
}

/** Index of the largest value (the first on a tie), -1 when empty: the bar that gets the gold highlight. */
export function largestIndex(values: number[]): number {
  let best = -1;
  values.forEach((value, index) => {
    if (best === -1 || value > values[best]) best = index;
  });
  return best;
}

/** Points of a sparkline in a width x height box, oldest on the left; a flat series sits in the middle. */
export function sparklinePoints(values: number[], width: number, height: number, padding = 2): { x: number; y: number }[] {
  if (values.length === 0) return [];
  const min = Math.min(...values);
  const span = Math.max(...values) - min;
  const step = values.length > 1 ? (width - 2 * padding) / (values.length - 1) : 0;
  return values.map((value, index) => ({
    x: padding + index * step,
    y: span === 0 ? height / 2 : padding + (1 - (value - min) / span) * (height - 2 * padding),
  }));
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}
