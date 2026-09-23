import { useMemo } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import { listStopsAnalytics, type StopAnalyticsRow } from "../../production/api";
import { buildWindows, localTodayIso } from "./metrics";
import type { PeriodDays } from "../PeriodFilter";

export interface ClassificationBucket {
  classification: string | null;
  minutes: number;
  stopCount: number;
}

export interface MotifBucket {
  motif: string | null;
  minutes: number;
  stopCount: number;
}

export interface SourceBucket {
  source: StopAnalyticsRow["source"];
  minutes: number;
  sharePct: number;
}

export interface StopsSummary {
  totalMinutes: number;
  stopCount: number;
  byClassification: ClassificationBucket[];
  byMotif: (classification: string | null) => MotifBucket[];
  bySource: SourceBucket[];
  unattributedMinutes: number;
  unattributedCount: number;
}

/** Every stop lands in exactly one classification, one motif and one source bucket; a stop
 * with no machine is also counted apart as "unattributed", never dropped from the totals. */
export function summarizeStops(rows: StopAnalyticsRow[]): StopsSummary {
  const totalMinutes = rows.reduce((sum, row) => sum + row.minutes, 0);

  const classificationMap = new Map<string | null, { minutes: number; stopCount: number }>();
  const motifByClassification = new Map<string | null, Map<string | null, { minutes: number; stopCount: number }>>();
  const sourceMap = new Map<StopAnalyticsRow["source"], number>();
  let unattributedMinutes = 0;
  let unattributedCount = 0;

  for (const row of rows) {
    const c = classificationMap.get(row.classification) ?? { minutes: 0, stopCount: 0 };
    c.minutes += row.minutes;
    c.stopCount += 1;
    classificationMap.set(row.classification, c);

    const motifMap = motifByClassification.get(row.classification) ?? new Map<string | null, { minutes: number; stopCount: number }>();
    const m = motifMap.get(row.motif) ?? { minutes: 0, stopCount: 0 };
    m.minutes += row.minutes;
    m.stopCount += 1;
    motifMap.set(row.motif, m);
    motifByClassification.set(row.classification, motifMap);

    sourceMap.set(row.source, (sourceMap.get(row.source) ?? 0) + row.minutes);

    if (row.equipment_id === null) {
      unattributedMinutes += row.minutes;
      unattributedCount += 1;
    }
  }

  const byClassification = [...classificationMap.entries()]
    .map(([classification, v]) => ({ classification, ...v }))
    .sort((a, b) => b.minutes - a.minutes);

  const bySource = [...sourceMap.entries()]
    .map(([source, minutes]) => ({ source, minutes, sharePct: totalMinutes > 0 ? (minutes / totalMinutes) * 100 : 0 }))
    .sort((a, b) => b.minutes - a.minutes);

  return {
    totalMinutes,
    stopCount: rows.length,
    byClassification,
    byMotif: (classification) =>
      [...(motifByClassification.get(classification) ?? new Map<string | null, { minutes: number; stopCount: number }>()).entries()]
        .map(([motif, v]) => ({ motif, ...v }))
        .sort((a, b) => b.minutes - a.minutes),
    bySource,
    unattributedMinutes,
    unattributedCount,
  };
}

export function useStopsAnalytics(days: PeriodDays) {
  const { session } = useAuth();
  const token = session!.token;
  const today = useMemo(() => localTodayIso(), []);
  const windows = useMemo(() => buildWindows(days, today), [days, today]);

  const stops = useQuery({
    queryKey: ["analytics", "stops", windows.current.from, windows.current.to],
    placeholderData: keepPreviousData,
    queryFn: () => listStopsAnalytics(token, { date_from: windows.current.from, date_to: windows.current.to }),
  });

  const summary = useMemo(() => summarizeStops(stops.data ?? []), [stops.data]);

  return { windows, stops, summary };
}
