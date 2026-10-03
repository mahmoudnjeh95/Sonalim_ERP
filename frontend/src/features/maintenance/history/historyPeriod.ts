import { useSearchParams } from "react-router-dom";

export interface Period {
  from: string;
  to: string;
}

export type PeriodPreset = "month" | "lastMonth" | "threeMonths" | "year";
export const PERIOD_PRESETS: readonly PeriodPreset[] = ["month", "lastMonth", "threeMonths", "year"];
export const DEFAULT_PRESET: PeriodPreset = "year";

/** A calendar day as YYYY-MM-DD, in local time (the plant runs on UTC, so they agree there). */
export function isoDay(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

export function presetRange(preset: PeriodPreset, today: Date = new Date()): Period {
  const year = today.getFullYear();
  const month = today.getMonth();
  switch (preset) {
    case "month":
      return { from: isoDay(new Date(year, month, 1)), to: isoDay(today) };
    case "lastMonth":
      return { from: isoDay(new Date(year, month - 1, 1)), to: isoDay(new Date(year, month, 0)) };
    case "threeMonths":
      return { from: isoDay(new Date(year, month - 2, 1)), to: isoDay(today) };
    case "year":
      return { from: isoDay(new Date(year, 0, 1)), to: isoDay(today) };
  }
}

export function matchingPreset(period: Period, today: Date = new Date()): PeriodPreset | null {
  return (
    PERIOD_PRESETS.find((preset) => {
      const range = presetRange(preset, today);
      return range.from === period.from && range.to === period.to;
    }) ?? null
  );
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

/** `?from=&to=`; missing, malformed or reversed falls back to the default preset. */
export function periodFromParams(params: URLSearchParams, today: Date = new Date()): Period {
  const from = params.get("from");
  const to = params.get("to");
  if (from && to && ISO_DAY.test(from) && ISO_DAY.test(to) && from <= to) return { from, to };
  return presetRange(DEFAULT_PRESET, today);
}

/** The period of a history screen, kept in the URL so a link, a reload or the print sheet opens on the same dates. */
export function usePeriod() {
  const [searchParams, setSearchParams] = useSearchParams();
  const period = periodFromParams(searchParams);
  const preset = matchingPreset(period);

  function setRange(range: Period) {
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.set("from", range.from);
        next.set("to", range.to);
        return next;
      },
      { replace: true },
    );
  }

  function reset() {
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.delete("from");
        next.delete("to");
        return next;
      },
      { replace: true },
    );
  }

  return {
    period,
    preset,
    isDefault: preset === DEFAULT_PRESET,
    setRange,
    setPreset: (next: PeriodPreset) => setRange(presetRange(next)),
    reset,
  };
}
