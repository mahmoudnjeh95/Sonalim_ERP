import type { TranslationKey } from "../../../lib/i18n";
import { compareQuantity, compareRatio, type Tone } from "../../analytics/manufacturing/metrics";
import type { BreakdownRow, FollowUpSummary, LedgerSummary, NonConformitySummary } from "./qualityMetrics";

// Deterministic rules over real QC figures. Each rule either returns a finding
// whose every number is traceable to the summaries passed in (see `basis`), or
// returns nothing. No model, estimate or default sits behind any of it.

export type QualityInsightKind =
  | "conformityDrift"
  | "worstProduct"
  | "worstTeam"
  | "worstShift"
  | "topDefect"
  | "ncBacklog"
  | "followUpsDue"
  | "awaitingInspection"
  | "rejectsWithoutCase"
  | "steady";

export interface QualityInsightText {
  key: TranslationKey;
  vars: Record<string, string>;
}

export interface QualityInsight {
  id: string;
  kind: QualityInsightKind;
  tone: Tone;
  /** Headline figure, already formatted. */
  value: string;
  /** Change or share, already formatted; null when there is nothing to compare to. */
  variance: string | null;
  explanation: QualityInsightText;
  action: QualityInsightText;
  basis: QualityInsightText;
  /** Where to look next: a quality-page tab, or an app route. */
  drilldown: { tab: string } | { href: string };
}

export interface QualityInsightInput {
  current: LedgerSummary;
  previous: LedgerSummary | null;
  byProduct: BreakdownRow[];
  byTeam: BreakdownRow[];
  byShift: BreakdownRow[];
  nonConformities: NonConformitySummary;
  followUps: FollowUpSummary;
  /** Packing runs validated by production that QC has not opened a report for. */
  awaitingInspection: number;
  fmt: {
    number: (value: number, digits?: number) => string;
    percent: (value: number | null, digits?: number) => string;
    cartons: (value: number) => string;
  };
}

const TONE_ORDER: Record<Tone, number> = { warning: 0, neutral: 1, good: 2 };
const KIND_ORDER: QualityInsightKind[] = [
  "conformityDrift",
  "worstProduct",
  "topDefect",
  "ncBacklog",
  "rejectsWithoutCase",
  "worstTeam",
  "worstShift",
  "followUpsDue",
  "awaitingInspection",
  "steady",
];

// A slice is only worth naming when enough cartons were inspected for its rate
// to mean something, and when it actually trails the plant figure.
const MIN_SLICE_CARTONS = 200;
const MIN_GAP_POINTS = 0.5;

function signed(value: number, digits: number, fmt: QualityInsightInput["fmt"]): string {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${fmt.number(Math.abs(value), digits)}`;
}

function cartonsBasis(totals: LedgerSummary["totals"], fmt: QualityInsightInput["fmt"]): QualityInsightText {
  return {
    key: "qc.analytics.insight.basis.cartons",
    vars: { cartons: fmt.number(totals.inspected, 0), reports: fmt.number(totals.reportCount, 0) },
  };
}

function trailingSlice(rows: BreakdownRow[], plantPct: number | null): BreakdownRow | null {
  if (plantPct === null || rows.length < 2) return null;
  const candidate = rows.find((row) => row.inspected >= MIN_SLICE_CARTONS && row.conformityPct !== null);
  if (!candidate || candidate.conformityPct === null) return null;
  return plantPct - candidate.conformityPct >= MIN_GAP_POINTS ? candidate : null;
}

function conformityDrift({ current, previous, fmt }: QualityInsightInput): QualityInsight | null {
  if (!previous || previous.totals.inspected === 0) return null;
  const cmp = compareRatio(current.totals.conformityPct, previous.totals.conformityPct, true);
  if (cmp.delta === null || cmp.current === null || cmp.previous === null || cmp.tone === "neutral") return null;
  return {
    id: "conformityDrift",
    kind: "conformityDrift",
    tone: cmp.tone,
    value: fmt.percent(cmp.current),
    variance: `${signed(cmp.delta, 1, fmt)} pp`,
    explanation: {
      key: cmp.tone === "warning" ? "qc.analytics.insight.conformityDrift.down" : "qc.analytics.insight.conformityDrift.up",
      vars: {
        delta: fmt.number(Math.abs(cmp.delta), 1),
        current: fmt.percent(cmp.current),
        previous: fmt.percent(cmp.previous),
        rejected: fmt.cartons(current.totals.nonConforming),
        previousRejected: fmt.cartons(previous.totals.nonConforming),
      },
    },
    action: { key: cmp.tone === "warning" ? "qc.analytics.insight.conformityDrift.actionDown" : "qc.analytics.insight.conformityDrift.actionUp", vars: {} },
    basis: cartonsBasis(current.totals, fmt),
    drilldown: { tab: "reports" },
  };
}

function sliceInsight(
  kind: "worstProduct" | "worstTeam" | "worstShift",
  rows: BreakdownRow[],
  { current, fmt }: QualityInsightInput,
): QualityInsight | null {
  const slice = trailingSlice(rows, current.totals.conformityPct);
  if (!slice || slice.conformityPct === null || current.totals.conformityPct === null) return null;
  const gap = current.totals.conformityPct - slice.conformityPct;
  const share = current.totals.nonConforming > 0 ? (slice.nonConforming / current.totals.nonConforming) * 100 : 0;
  return {
    id: kind,
    kind,
    tone: "warning",
    value: slice.label,
    variance: fmt.percent(slice.conformityPct),
    explanation: {
      key: slice.topDefect ? `qc.analytics.insight.${kind}.explainDefect` : `qc.analytics.insight.${kind}.explain`,
      vars: {
        name: slice.label,
        pct: fmt.percent(slice.conformityPct),
        plant: fmt.percent(current.totals.conformityPct),
        gap: fmt.number(gap, 1),
        rejected: fmt.cartons(slice.nonConforming),
        share: fmt.number(share, 0),
        defect: slice.topDefect?.label ?? "",
        defectCartons: slice.topDefect ? fmt.cartons(slice.topDefect.cartons) : "",
      },
    },
    action: { key: `qc.analytics.insight.${kind}.action`, vars: { name: slice.label } },
    basis: { key: "qc.analytics.insight.basis.slice", vars: { cartons: fmt.number(slice.inspected, 0), reports: fmt.number(slice.reportCount, 0) } },
    drilldown: { tab: "reports" },
  };
}

function topDefect({ current, previous, fmt }: QualityInsightInput): QualityInsight | null {
  const top = current.defects[0];
  if (!top) return null;
  const before = previous?.defects.find((row) => row.defect === top.defect) ?? null;
  const cmp = before ? compareQuantity(top.cartons, before.cartons, false) : null;
  return {
    id: "topDefect",
    kind: "topDefect",
    // A ranking, not a verdict, unless the same defect grew against the previous window.
    tone: cmp?.tone === "warning" ? "warning" : "neutral",
    value: top.defect,
    variance: `${fmt.number(top.sharePct, 0)}%`,
    explanation: {
      key: before ? "qc.analytics.insight.topDefect.explainPrevious" : "qc.analytics.insight.topDefect.explain",
      vars: {
        defect: top.defect,
        cartons: fmt.cartons(top.cartons),
        share: fmt.number(top.sharePct, 0),
        reports: fmt.number(top.reportCount, 0),
        previousCartons: before ? fmt.cartons(before.cartons) : "",
      },
    },
    action: { key: "qc.analytics.insight.topDefect.action", vars: { defect: top.defect } },
    basis: { key: "qc.analytics.insight.basis.rejected", vars: { cartons: fmt.number(current.totals.nonConforming, 0) } },
    drilldown: { tab: "non-conformities" },
  };
}

function ncBacklog({ nonConformities, fmt }: QualityInsightInput): QualityInsight | null {
  if (nonConformities.open === 0) return null;
  const waiting = nonConformities.byStatus.raised + nonConformities.byStatus.quarantined;
  return {
    id: "ncBacklog",
    kind: "ncBacklog",
    tone: nonConformities.bySeverity.critical > 0 || (nonConformities.oldestOpenDays ?? 0) > 14 ? "warning" : "neutral",
    value: fmt.number(nonConformities.open, 0),
    variance: nonConformities.oldestOpenDays === null ? null : `${fmt.number(nonConformities.oldestOpenDays, 0)} j`,
    explanation: {
      key: "qc.analytics.insight.ncBacklog.explain",
      vars: {
        open: fmt.number(nonConformities.open, 0),
        waiting: fmt.number(waiting, 0),
        dispositioned: fmt.number(nonConformities.byStatus.dispositioned, 0),
        oldest: nonConformities.oldestOpenDays === null ? "" : fmt.number(nonConformities.oldestOpenDays, 0),
        reference: nonConformities.oldestOpen?.reference ?? "",
      },
    },
    action: { key: "qc.analytics.insight.ncBacklog.action", vars: {} },
    basis: { key: "qc.analytics.insight.basis.nc", vars: { total: fmt.number(nonConformities.total, 0) } },
    drilldown: { tab: "non-conformities" },
  };
}

function rejectsWithoutCase({ current, fmt }: QualityInsightInput): QualityInsight | null {
  if (current.rejectsWithoutCase === 0) return null;
  return {
    id: "rejectsWithoutCase",
    kind: "rejectsWithoutCase",
    tone: "warning",
    value: fmt.number(current.rejectsWithoutCase, 0),
    variance: null,
    explanation: { key: "qc.analytics.insight.rejectsWithoutCase.explain", vars: { count: fmt.number(current.rejectsWithoutCase, 0) } },
    action: { key: "qc.analytics.insight.rejectsWithoutCase.action", vars: {} },
    basis: cartonsBasis(current.totals, fmt),
    drilldown: { tab: "reports" },
  };
}

function followUpsDue({ followUps, fmt }: QualityInsightInput): QualityInsight | null {
  if (followUps.overdue === 0 && followUps.dueSoon === 0) return null;
  return {
    id: "followUpsDue",
    kind: "followUpsDue",
    tone: followUps.overdue > 0 ? "warning" : "neutral",
    value: fmt.number(followUps.overdue + followUps.dueSoon, 0),
    variance: null,
    explanation: {
      key: followUps.overdue > 0 ? "qc.analytics.insight.followUpsDue.explainOverdue" : "qc.analytics.insight.followUpsDue.explain",
      vars: { overdue: fmt.number(followUps.overdue, 0), dueSoon: fmt.number(followUps.dueSoon, 0), open: fmt.number(followUps.open, 0) },
    },
    action: { key: "qc.analytics.insight.followUpsDue.action", vars: {} },
    basis: { key: "qc.analytics.insight.basis.followUps", vars: { open: fmt.number(followUps.open, 0) } },
    drilldown: { tab: "reports" },
  };
}

function awaitingInspection({ current, awaitingInspection: awaiting, fmt }: QualityInsightInput): QualityInsight | null {
  const pending = current.statusCounts.draft + current.statusCounts.submitted + current.statusCounts.rejected;
  if (awaiting === 0 && pending === 0) return null;
  return {
    id: "awaitingInspection",
    kind: "awaitingInspection",
    tone: "neutral",
    value: fmt.number(awaiting + pending, 0),
    variance: null,
    explanation: {
      key: "qc.analytics.insight.awaitingInspection.explain",
      vars: {
        awaiting: fmt.number(awaiting, 0),
        submitted: fmt.number(current.statusCounts.submitted, 0),
        draft: fmt.number(current.statusCounts.draft, 0),
        rejected: fmt.number(current.statusCounts.rejected, 0),
      },
    },
    action: { key: "qc.analytics.insight.awaitingInspection.action", vars: {} },
    basis: { key: "qc.analytics.insight.basis.reports", vars: { reports: fmt.number(current.totals.reportCount, 0) } },
    drilldown: { tab: "reports" },
  };
}

function steady(input: QualityInsightInput): QualityInsight | null {
  const { current, previous, fmt } = input;
  if (!previous || current.totals.inspected === 0 || previous.totals.inspected === 0) return null;
  const cmp = compareRatio(current.totals.conformityPct, previous.totals.conformityPct, true);
  if (cmp.tone !== "neutral" || cmp.current === null) return null;
  return {
    id: "steady",
    kind: "steady",
    tone: "good",
    value: fmt.percent(cmp.current),
    variance: "±0.0 pp",
    explanation: { key: "qc.analytics.insight.steady.explain", vars: { pct: fmt.percent(cmp.current) } },
    action: { key: "qc.analytics.insight.steady.action", vars: {} },
    basis: cartonsBasis(current.totals, fmt),
    drilldown: { tab: "dashboard" },
  };
}

const RULES: ((input: QualityInsightInput) => QualityInsight | null)[] = [
  conformityDrift,
  (input) => sliceInsight("worstProduct", input.byProduct, input),
  (input) => sliceInsight("worstTeam", input.byTeam, input),
  (input) => sliceInsight("worstShift", input.byShift, input),
  topDefect,
  ncBacklog,
  rejectsWithoutCase,
  followUpsDue,
  awaitingInspection,
  steady,
];

/** Findings, worsening ones first, then plain rankings, then reassurance. */
export function buildQualityInsights(input: QualityInsightInput): QualityInsight[] {
  return RULES.map((rule) => rule(input))
    .filter((insight): insight is QualityInsight => insight !== null)
    .sort((a, b) => TONE_ORDER[a.tone] - TONE_ORDER[b.tone] || KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind));
}
