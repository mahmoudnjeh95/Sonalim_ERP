import type { TranslationKey } from "../../../lib/i18n";
import type { DowntimeBreakdownRow, WasteCategory } from "../../production/api";
import {
  compareQuantity,
  compareRatio,
  rankDowntimeReasons,
  rankWasteStages,
  type CostSummary,
  type MachinesSummary,
  type OperationsSummary,
  type QualitySummary,
  type Tone,
} from "./metrics";

// Deterministic rules over real ERP figures. Each rule either returns an insight
// whose every number is traceable to the summaries passed in (see `basis`),
// or returns nothing. There is no model, estimate or default behind any of it.

export type InsightKind =
  | "productionGap"
  | "yieldDrift"
  | "highestWasteStage"
  | "highestDowntimeMachine"
  | "qualityDrift"
  | "bestTeam"
  | "costVariance";

export interface InsightText {
  key: TranslationKey;
  vars: Record<string, string>;
}

export interface Insight {
  id: string;
  kind: InsightKind;
  tone: Tone;
  /** Headline figure, already formatted. */
  value: string;
  /** Change against the previous period, already formatted; null when there is nothing to compare to. */
  variance: string | null;
  /** The finding, naming the actual team/machine/stage it comes from. */
  explanation: InsightText;
  action: InsightText;
  /** Analytics tab to open, or an app route for modules outside analytics. */
  drilldown: { tab: string } | { href: string };
  /** What data the finding rests on, e.g. "Based on 12 validated production reports". */
  basis: InsightText;
}

export interface Formatters {
  number: (value: number, digits?: number) => string;
  tonnes: (value: number) => string;
  kg: (value: number) => string;
  duration: (minutes: number) => string;
  money: (value: number) => string;
  machine: (equipmentId: string) => string;
  stage: (stage: WasteCategory) => string;
  /** A stored downtime motif as the person reads it: translated if built in, as typed if the plant added it. */
  motif: (motif: string) => string;
  classification: (value: string) => string;
  downtimeType: (value: string) => string;
}

export interface InsightInput {
  current: { ops: OperationsSummary; quality: QualitySummary | null };
  previous: { ops: OperationsSummary; quality: QualitySummary | null };
  machines: MachinesSummary | null;
  breakdown: DowntimeBreakdownRow[];
  cost: CostSummary | null;
  fmt: Formatters;
}

const TONE_ORDER: Record<Tone, number> = { warning: 0, good: 1, neutral: 2 };
const KIND_ORDER: InsightKind[] = [
  "highestDowntimeMachine",
  "yieldDrift",
  "qualityDrift",
  "productionGap",
  "highestWasteStage",
  "costVariance",
  "bestTeam",
];

function signed(value: number, digits: number, fmt: Formatters): string {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${fmt.number(Math.abs(value), digits)}`;
}

function reportsBasis(count: number, fmt: Formatters): InsightText {
  return { key: "analytics.insight.basis.reports", vars: { count: fmt.number(count, 0) } };
}

function productionGap({ current, previous, fmt }: InsightInput): Insight | null {
  const cmp = compareQuantity(current.ops.totals.produced, previous.ops.totals.produced, true);
  if (cmp.delta === null || cmp.tone !== "warning") return null;

  // Union of both windows: a team that produced last period and nothing this one is the biggest drop of all.
  const currentByTeam = new Map(current.ops.byTeam.map((team) => [team.team, team.produced]));
  const previousByTeam = new Map(previous.ops.byTeam.map((team) => [team.team, team.produced]));
  const worstTeam = [...new Set([...currentByTeam.keys(), ...previousByTeam.keys()])]
    .map((team) => ({ team, drop: (currentByTeam.get(team) ?? 0) - (previousByTeam.get(team) ?? 0) }))
    .filter((entry) => entry.drop < 0)
    .sort((a, b) => a.drop - b.drop)[0];

  const vars = {
    delta: `${fmt.number(Math.abs(cmp.delta), 1)}%`,
    current: fmt.tonnes(current.ops.totals.produced),
    previous: fmt.tonnes(previous.ops.totals.produced),
    team: worstTeam?.team ?? "",
    teamDrop: worstTeam ? fmt.tonnes(Math.abs(worstTeam.drop)) : "",
  };
  return {
    id: "productionGap",
    kind: "productionGap",
    tone: cmp.tone,
    value: fmt.tonnes(current.ops.totals.produced),
    variance: `${signed(cmp.delta, 1, fmt)}%`,
    explanation: { key: worstTeam ? "analytics.insight.productionGap.explainDriver" : "analytics.insight.productionGap.explain", vars },
    action: { key: "analytics.insight.productionGap.action", vars: {} },
    drilldown: { tab: "team-performance" },
    basis: reportsBasis(current.ops.totals.reportCount, fmt),
  };
}

function yieldDrift({ current, previous, fmt }: InsightInput): Insight | null {
  const cmp = compareRatio(current.ops.yieldPct, previous.ops.yieldPct, true);
  if (cmp.delta === null || cmp.current === null || cmp.previous === null) return null;
  if (cmp.tone !== "warning") return null;

  const previousByTeam = new Map(previous.ops.byTeam.map((team) => [team.team, team.yieldPct]));
  const worstTeam = current.ops.byTeam
    .flatMap((team) => {
      const before = previousByTeam.get(team.team);
      if (team.yieldPct === null || before === null || before === undefined) return [];
      return [{ team: team.team, now: team.yieldPct, before, drop: team.yieldPct - before }];
    })
    .filter((entry) => entry.drop < 0)
    .sort((a, b) => a.drop - b.drop)[0];

  const vars = {
    delta: fmt.number(Math.abs(cmp.delta), 1),
    current: fmt.number(cmp.current, 1),
    previous: fmt.number(cmp.previous, 1),
    team: worstTeam?.team ?? "",
    teamFrom: worstTeam ? fmt.number(worstTeam.before, 1) : "",
    teamTo: worstTeam ? fmt.number(worstTeam.now, 1) : "",
  };
  return {
    id: "yieldDrift",
    kind: "yieldDrift",
    tone: cmp.tone,
    value: `${vars.current}%`,
    variance: `${signed(cmp.delta, 1, fmt)} pp`,
    explanation: { key: worstTeam ? "analytics.insight.yieldDrift.explainDriver" : "analytics.insight.yieldDrift.explain", vars },
    action: { key: "analytics.insight.yieldDrift.action", vars: {} },
    drilldown: { tab: "team-performance" },
    basis: reportsBasis(current.ops.totals.reportCount, fmt),
  };
}

function highestWasteStage({ current, previous, fmt }: InsightInput): Insight | null {
  const ranked = rankWasteStages(current.ops.totals);
  const top = ranked[0];
  if (!top) return null;

  const cmp = compareQuantity(current.ops.totals.netWasteKg, previous.ops.totals.netWasteKg, false);
  const declaredKg = ranked.reduce((sum, entry) => sum + entry.kg, 0);
  return {
    id: "highestWasteStage",
    kind: "highestWasteStage",
    // The card names the largest stage, so green would read as "this stage is fine"; only flag it when total waste worsened.
    tone: cmp.tone === "good" ? "neutral" : cmp.tone,
    value: fmt.kg(top.kg),
    variance: cmp.delta === null ? null : `${signed(cmp.delta, 1, fmt)}%`,
    explanation: {
      key: "analytics.insight.highestWasteStage.explain",
      vars: {
        stage: fmt.stage(top.stage),
        share: fmt.number(top.sharePct, 0),
        kg: fmt.kg(top.kg),
        total: fmt.kg(declaredKg),
        regrind: fmt.kg(current.ops.totals.regrindKg),
      },
    },
    action: { key: "analytics.insight.highestWasteStage.action", vars: { stage: fmt.stage(top.stage) } },
    drilldown: { tab: "yield-waste" },
    basis: reportsBasis(current.ops.totals.reportCount, fmt),
  };
}

function highestDowntimeMachine({ machines, breakdown, fmt }: InsightInput): Insight | null {
  const worst = machines?.machines[0];
  if (!machines || !worst || worst.downtimeMinutes <= 0) return null;

  // With a single machine its share is trivially 100%; that says nothing about where to look.
  const comparable = machines.machines.length > 1 && worst.shareOfDowntimePct !== null;
  const share = worst.shareOfDowntimePct ?? 0;
  // A ranking, not a verdict: nothing says how much downtime one machine may have.
  const tone: Tone = "neutral";
  const reason = rankDowntimeReasons(breakdown, worst.equipmentId)[0];

  const vars = {
    machine: fmt.machine(worst.equipmentId),
    duration: fmt.duration(worst.downtimeMinutes),
    share: fmt.number(share, 0),
    reason: reason ? fmt.motif(reason.reason) : "",
    reasonDuration: reason ? fmt.duration(reason.minutes) : "",
  };
  const key: TranslationKey = comparable
    ? reason
      ? "analytics.insight.highestDowntimeMachine.explainShareReason"
      : "analytics.insight.highestDowntimeMachine.explainShare"
    : reason
      ? "analytics.insight.highestDowntimeMachine.explainReason"
      : "analytics.insight.highestDowntimeMachine.explain";

  return {
    id: "highestDowntimeMachine",
    kind: "highestDowntimeMachine",
    tone,
    value: fmt.duration(worst.downtimeMinutes),
    variance: comparable ? `${fmt.number(share, 0)}%` : null,
    explanation: { key, vars },
    action: { key: "analytics.insight.highestDowntimeMachine.action", vars: {} },
    drilldown: { tab: "machine-performance" },
    basis: {
      key: "analytics.insight.basis.downtime",
      vars: { duration: fmt.duration(machines.totalDowntimeMinutes), machines: String(machines.machines.length) },
    },
  };
}

function qualityDrift({ current, previous, fmt }: InsightInput): Insight | null {
  if (!current.quality || !previous.quality) return null;
  const cmp = compareRatio(current.quality.conformityPct, previous.quality.conformityPct, true);
  if (cmp.delta === null || cmp.current === null || cmp.previous === null) return null;
  if (cmp.tone !== "warning") return null;

  const lowest = current.quality.byTeam
    .filter((team) => team.conformityPct !== null)
    .sort((a, b) => (a.conformityPct as number) - (b.conformityPct as number))[0];

  const vars = {
    delta: fmt.number(Math.abs(cmp.delta), 1),
    current: fmt.number(cmp.current, 1),
    previous: fmt.number(cmp.previous, 1),
    team: lowest?.team ?? "",
    teamPct: lowest ? fmt.number(lowest.conformityPct as number, 1) : "",
    teamRejected: lowest ? fmt.number(lowest.nonConforming, 0) : "",
  };
  return {
    id: "qualityDrift",
    kind: "qualityDrift",
    tone: cmp.tone,
    value: `${vars.current}%`,
    variance: `${signed(cmp.delta, 1, fmt)} pp`,
    explanation: { key: lowest ? "analytics.insight.qualityDrift.explainDriver" : "analytics.insight.qualityDrift.explain", vars },
    action: { key: "analytics.insight.qualityDrift.action", vars: {} },
    drilldown: { href: "/quality" },
    basis: {
      key: "analytics.insight.basis.cartons",
      vars: { count: fmt.number(current.quality.conforming + current.quality.nonConforming, 0) },
    },
  };
}

function bestTeam({ current, fmt }: InsightInput): Insight | null {
  const ranked = current.ops.byTeam
    .filter((team) => team.yieldPct !== null && team.materialInput > 0)
    .sort((a, b) => (b.yieldPct as number) - (a.yieldPct as number));
  if (ranked.length < 2 || current.ops.yieldPct === null) return null;

  const best = ranked[0];
  const lead = (best.yieldPct as number) - current.ops.yieldPct;
  return {
    id: "bestTeam",
    kind: "bestTeam",
    tone: "good",
    value: best.team,
    variance: `${fmt.number(best.yieldPct as number, 1)}%`,
    explanation: {
      key: "analytics.insight.bestTeam.explain",
      vars: {
        team: best.team,
        yield: fmt.number(best.yieldPct as number, 1),
        produced: fmt.tonnes(best.produced),
        average: fmt.number(current.ops.yieldPct, 1),
        lead: fmt.number(Math.abs(lead), 1),
      },
    },
    action: { key: "analytics.insight.bestTeam.action", vars: {} },
    drilldown: { tab: "team-performance" },
    basis: reportsBasis(best.reportCount, fmt),
  };
}

function costVariance({ cost, fmt }: InsightInput): Insight | null {
  if (!cost || cost.availability !== "ok" || cost.costPerTonne === null || cost.previousCostPerTonne === null) return null;
  const cmp = compareQuantity(cost.costPerTonne, cost.previousCostPerTonne, false);
  if (cmp.delta === null || cmp.tone === "neutral") return null;

  return {
    id: "costVariance",
    kind: "costVariance",
    tone: cmp.tone,
    value: fmt.money(cost.costPerTonne),
    variance: `${signed(cmp.delta, 1, fmt)}%`,
    explanation: {
      key: "analytics.insight.costVariance.explain",
      vars: {
        current: fmt.money(cost.costPerTonne),
        previous: fmt.money(cost.previousCostPerTonne),
        label: cost.label,
        previousLabel: cost.previousLabel ?? "",
      },
    },
    action: { key: "analytics.insight.costVariance.action", vars: {} },
    drilldown: { tab: "production-recap" },
    basis: { key: "analytics.insight.basis.cost", vars: { tonnage: fmt.tonnes(cost.tonnage), label: cost.label } },
  };
}

const RULES = [
  productionGap,
  yieldDrift,
  highestWasteStage,
  highestDowntimeMachine,
  qualityDrift,
  bestTeam,
  costVariance,
];

/** Findings, worsening ones first, then improving, then plain rankings. */
export function buildInsights(input: InsightInput): Insight[] {
  return RULES.map((rule) => rule(input))
    .filter((insight): insight is Insight => insight !== null)
    .sort((a, b) => TONE_ORDER[a.tone] - TONE_ORDER[b.tone] || KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind));
}
