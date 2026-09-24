import type {
  FollowUp,
  InspectionLedgerRow,
  NonConformity,
  NonConformitySeverity,
  NonConformityStatus,
  QualityReportStatus,
} from "../api";
import { ratioPct } from "../../analytics/manufacturing/metrics";

// Everything here is derived from rows the backend already returns. Nothing is
// estimated: when an input is missing the result is null, and the UI renders an
// explicit "unavailable" state instead of a number. Only validated reports feed
// a conformity figure -- a draft or rejected report is a claim, not a verdict,
// the same rule the backend's team_conformity applies.

export type QualityDimension = "product" | "line" | "team" | "shift" | "order";
export const QUALITY_DIMENSIONS: QualityDimension[] = ["product", "line", "team", "shift", "order"];

export const REPORT_STATUSES: QualityReportStatus[] = ["draft", "submitted", "rejected", "validated"];
export const NC_STATUSES: NonConformityStatus[] = ["raised", "quarantined", "dispositioned", "closed"];
export const NC_SEVERITIES: NonConformitySeverity[] = ["minor", "major", "critical"];

// A row is one product line of one report, so report counts are distinct
// report ids, never row counts: a shift that packed two products is one report.
export interface ConformityTotals {
  reportCount: number;
  inspected: number;
  conforming: number;
  nonConforming: number;
  conformityPct: number | null;
}

export interface BreakdownRow extends ConformityTotals {
  key: string;
  label: string;
  /** The defect this slice rejects most cartons for, when it rejected any. */
  topDefect: { label: string; cartons: number } | null;
}

export interface DayPoint {
  date: string;
  reportCount: number;
  conforming: number;
  nonConforming: number;
  /** null on a day with no validated report -- a gap, not a zero. */
  conformityPct: number | null;
}

export interface DefectRow {
  defect: string;
  cartons: number;
  reportCount: number;
  sharePct: number;
  cumulativePct: number;
}

export interface LedgerSummary {
  totals: ConformityTotals;
  /** Every report in the window by status, validated included -- what is still on QC's desk. */
  statusCounts: Record<QualityReportStatus, number>;
  byDay: DayPoint[];
  defects: DefectRow[];
  /** Validated product lines that logged rejects but never had a non-conformity raised for them. */
  rejectsWithoutCase: number;
}

/** Resolves the ids on a ledger row into the names a person reads. */
export interface LedgerLabels {
  product: (productId: string | null) => string;
  line: (ofId: string) => string | null;
  order: (ofId: string) => string;
  shift: (shift: string | null) => string;
  team: (team: string | null) => string;
}

function emptyTotals(): ConformityTotals {
  return { reportCount: 0, inspected: 0, conforming: 0, nonConforming: 0, conformityPct: null };
}

function addRow(target: ConformityTotals, row: InspectionLedgerRow, reports: Set<string>) {
  reports.add(row.report_id);
  target.reportCount = reports.size;
  target.conforming += row.conforming_cartons;
  target.nonConforming += row.non_conforming_cartons;
  target.inspected = target.conforming + target.nonConforming;
  target.conformityPct = ratioPct(target.conforming, target.inspected);
}

export function validatedRows(rows: InspectionLedgerRow[]): InspectionLedgerRow[] {
  return rows.filter((row) => row.status === "validated");
}

export function rankDefects(rows: InspectionLedgerRow[]): DefectRow[] {
  const byDefect = new Map<string, { cartons: number; reportCount: number }>();
  for (const row of validatedRows(rows)) {
    if (row.non_conforming_cartons <= 0) continue;
    const defect = (row.defect_details ?? "").trim();
    if (!defect) continue;
    const entry = byDefect.get(defect) ?? { cartons: 0, reportCount: 0 };
    entry.cartons += row.non_conforming_cartons;
    entry.reportCount += 1;
    byDefect.set(defect, entry);
  }
  const total = [...byDefect.values()].reduce((sum, entry) => sum + entry.cartons, 0);
  let cumulative = 0;
  return [...byDefect.entries()]
    .map(([defect, entry]) => ({ defect, ...entry }))
    .sort((a, b) => b.cartons - a.cartons || a.defect.localeCompare(b.defect))
    .map((entry) => {
      const sharePct = total > 0 ? (entry.cartons / total) * 100 : 0;
      cumulative += sharePct;
      return { ...entry, sharePct, cumulativePct: Math.min(100, cumulative) };
    });
}

export function summarizeLedger(rows: InspectionLedgerRow[]): LedgerSummary {
  const totals = emptyTotals();
  const validatedReports = new Set<string>();
  const reportsByStatus: Record<QualityReportStatus, Set<string>> = { draft: new Set(), submitted: new Set(), rejected: new Set(), validated: new Set() };
  const days = new Map<string, DayPoint & { reports: Set<string> }>();
  let rejectsWithoutCase = 0;

  for (const row of rows) {
    reportsByStatus[row.status].add(row.report_id);
    if (row.status !== "validated") continue;
    addRow(totals, row, validatedReports);
    if (row.non_conforming_cartons > 0 && row.non_conformity_count === 0) rejectsWithoutCase += 1;

    const day = days.get(row.report_date) ?? { date: row.report_date, reportCount: 0, conforming: 0, nonConforming: 0, conformityPct: null, reports: new Set<string>() };
    day.reports.add(row.report_id);
    day.reportCount = day.reports.size;
    day.conforming += row.conforming_cartons;
    day.nonConforming += row.non_conforming_cartons;
    day.conformityPct = ratioPct(day.conforming, day.conforming + day.nonConforming);
    days.set(row.report_date, day);
  }

  return {
    totals,
    statusCounts: {
      draft: reportsByStatus.draft.size,
      submitted: reportsByStatus.submitted.size,
      rejected: reportsByStatus.rejected.size,
      validated: reportsByStatus.validated.size,
    },
    byDay: [...days.values()]
      .sort((a, b) => a.date.localeCompare(b.date))
      .map(({ reports: _reports, ...point }) => point),
    defects: rankDefects(rows),
    rejectsWithoutCase,
  };
}

function dimensionKey(row: InspectionLedgerRow, dimension: QualityDimension, labels: LedgerLabels): { key: string; label: string } | null {
  switch (dimension) {
    case "product":
      return { key: row.product_id, label: labels.product(row.product_id) };
    case "line": {
      const line = labels.line(row.of_id);
      return line ? { key: line, label: line } : null;
    }
    case "team":
      return row.team ? { key: row.team, label: labels.team(row.team) } : null;
    case "shift":
      return row.shift ? { key: row.shift, label: labels.shift(row.shift) } : null;
    case "order":
      return { key: row.of_id, label: labels.order(row.of_id) };
  }
}

/**
 * Validated conformity sliced one way, lowest conformity first so the slice
 * that needs attention leads. A row whose slice cannot be named (no product
 * resolved, no team on the report) counts in the totals but not here.
 */
export function breakdown(rows: InspectionLedgerRow[], dimension: QualityDimension, labels: LedgerLabels): BreakdownRow[] {
  const slices = new Map<string, { label: string; totals: ConformityTotals; rows: InspectionLedgerRow[]; reports: Set<string> }>();
  for (const row of validatedRows(rows)) {
    const named = dimensionKey(row, dimension, labels);
    if (!named) continue;
    const slice = slices.get(named.key) ?? { label: named.label, totals: emptyTotals(), rows: [], reports: new Set<string>() };
    addRow(slice.totals, row, slice.reports);
    slice.rows.push(row);
    slices.set(named.key, slice);
  }
  return [...slices.entries()]
    .map(([key, slice]) => {
      const top = rankDefects(slice.rows)[0];
      return { key, label: slice.label, ...slice.totals, topDefect: top ? { label: top.defect, cartons: top.cartons } : null };
    })
    .sort((a, b) => {
      if (a.conformityPct === null || b.conformityPct === null) return (a.conformityPct ?? 101) - (b.conformityPct ?? 101);
      return a.conformityPct - b.conformityPct || b.inspected - a.inspected;
    });
}

// --- Non-conformities and follow-ups ------------------------------------------

export interface NonConformitySummary {
  total: number;
  open: number;
  byStatus: Record<NonConformityStatus, number>;
  bySeverity: Record<NonConformitySeverity, number>;
  /** Age in days of the open case raised longest ago; null when nothing is open. */
  oldestOpenDays: number | null;
  oldestOpen: NonConformity | null;
  /** Open cases per product id, most first. */
  openByProduct: { productId: string; count: number; quantity: number }[];
}

const DAY_MS = 86_400_000;

function daysBetween(fromIso: string, toIso: string): number {
  return Math.max(0, Math.floor((new Date(toIso).getTime() - new Date(fromIso).getTime()) / DAY_MS));
}

export function summarizeNonConformities(ncs: NonConformity[], todayIso: string): NonConformitySummary {
  const byStatus: Record<NonConformityStatus, number> = { raised: 0, quarantined: 0, dispositioned: 0, closed: 0 };
  const bySeverity: Record<NonConformitySeverity, number> = { minor: 0, major: 0, critical: 0 };
  const openByProduct = new Map<string, { count: number; quantity: number }>();
  let oldestOpen: NonConformity | null = null;
  for (const nc of ncs) {
    byStatus[nc.status] += 1;
    bySeverity[nc.severity] += 1;
    if (nc.status === "closed") continue;
    const entry = openByProduct.get(nc.product_id) ?? { count: 0, quantity: 0 };
    entry.count += 1;
    entry.quantity += nc.quantity;
    openByProduct.set(nc.product_id, entry);
    if (nc.raised_at && (!oldestOpen || !oldestOpen.raised_at || nc.raised_at < oldestOpen.raised_at)) oldestOpen = nc;
  }
  const open = ncs.length - byStatus.closed;
  return {
    total: ncs.length,
    open,
    byStatus,
    bySeverity,
    oldestOpenDays: oldestOpen?.raised_at ? daysBetween(oldestOpen.raised_at, `${todayIso}T00:00:00`) : null,
    oldestOpen,
    openByProduct: [...openByProduct.entries()]
      .map(([productId, entry]) => ({ productId, ...entry }))
      .sort((a, b) => b.count - a.count || b.quantity - a.quantity),
  };
}

export interface FollowUpSummary {
  open: number;
  /** Open windows that end within the next seven days. */
  dueSoon: number;
  /** Open windows whose end date has already passed. */
  overdue: number;
  completed: number;
}

export function summarizeFollowUps(followUps: FollowUp[], todayIso: string, horizonDays = 7): FollowUpSummary {
  const summary: FollowUpSummary = { open: 0, dueSoon: 0, overdue: 0, completed: 0 };
  const horizon = new Date(`${todayIso}T00:00:00`).getTime() + horizonDays * DAY_MS;
  const today = new Date(`${todayIso}T00:00:00`).getTime();
  for (const followUp of followUps) {
    if (followUp.status === "completed") {
      summary.completed += 1;
      continue;
    }
    summary.open += 1;
    const ends = new Date(`${followUp.window_ends_on}T00:00:00`).getTime();
    if (ends < today) summary.overdue += 1;
    else if (ends <= horizon) summary.dueSoon += 1;
  }
  return summary;
}

// --- Trend alignment --------------------------------------------------------------

export interface ConformityTrendPoint {
  index: number;
  date: string;
  previousDate: string;
  current: number | null;
  previous: number | null;
  inspected: number;
  rejected: number;
}

/** The current window day by day, with the previous window lined up underneath by day index. */
export function alignConformityTrend(
  current: DayPoint[],
  previous: DayPoint[],
  windows: { current: { from: string }; previous: { from: string } },
  days: number,
): ConformityTrendPoint[] {
  const currentByDate = new Map(current.map((point) => [point.date, point]));
  const previousByDate = new Map(previous.map((point) => [point.date, point]));
  return Array.from({ length: days }, (_, index) => {
    const date = shiftDate(windows.current.from, index);
    const previousDate = shiftDate(windows.previous.from, index);
    const point = currentByDate.get(date);
    return {
      index,
      date,
      previousDate,
      current: point?.conformityPct ?? null,
      previous: previousByDate.get(previousDate)?.conformityPct ?? null,
      inspected: point ? point.conforming + point.nonConforming : 0,
      rejected: point?.nonConforming ?? 0,
    };
  });
}

function shiftDate(iso: string, days: number): string {
  return new Date(new Date(`${iso}T00:00:00Z`).getTime() + days * DAY_MS).toISOString().slice(0, 10);
}
