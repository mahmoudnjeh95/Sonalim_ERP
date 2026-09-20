import type {
  DowntimeBreakdownRow,
  MachinePerformanceRow,
  ProductionAnalytics,
  TeamPerformanceRow,
  WasteCategory,
  WorkOrder,
  WorkOrderYield,
} from "../../production/api";
import type { TeamConformityRow } from "../../qc/api";

// Everything here is derived from rows the backend already returns. Nothing is
// estimated: when an input is missing the result is null, and the UI renders an
// explicit "unavailable" state instead of a number.

// --- Windows ---------------------------------------------------------------

export interface DateWindow {
  from: string;
  to: string;
}

const DAY_MS = 86_400_000;

export function shiftIso(iso: string, days: number): string {
  return new Date(new Date(`${iso}T00:00:00Z`).getTime() + days * DAY_MS).toISOString().slice(0, 10);
}

export function localTodayIso(now: Date = new Date()): string {
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/** The last `days` days ending today, and the equal-length window right before it. */
export function buildWindows(days: number, today: string): { current: DateWindow; previous: DateWindow } {
  return {
    current: { from: shiftIso(today, -(days - 1)), to: today },
    previous: { from: shiftIso(today, -(2 * days - 1)), to: shiftIso(today, -days) },
  };
}

// --- Ratios and comparison -------------------------------------------------

export function ratioPct(numerator: number, denominator: number): number | null {
  return denominator > 0 ? (numerator / denominator) * 100 : null;
}

export type Tone = "good" | "warning" | "neutral";

/**
 * A change against the previous period is judged by its direction alone. The
 * plant has no configured yield/downtime/quality target anywhere in the system,
 * so the only honest benchmark is the previous equal-length period, and no
 * "small" or "large" band is invented on top of it. Both sides are compared at
 * the precision the cards print (one decimal): a move that reads 96.5% → 96.5%
 * is no change.
 */
function atDisplayPrecision(value: number): number {
  return Math.round(value * 10) / 10;
}

export interface Comparison {
  current: number | null;
  previous: number | null;
  /** Percentage points for ratio metrics, percent for quantity metrics. null when either side is missing. */
  delta: number | null;
  kind: "points" | "percent";
  tone: Tone;
  direction: "up" | "down" | "flat" | null;
}

function toneFor(delta: number | null, higherIsBetter: boolean): Tone {
  if (delta === null || delta === 0) return "neutral";
  return (higherIsBetter ? delta > 0 : delta < 0) ? "good" : "warning";
}

function directionFor(delta: number | null): Comparison["direction"] {
  if (delta === null) return null;
  if (delta === 0) return "flat";
  return delta > 0 ? "up" : "down";
}

/** For a metric already expressed as a percentage (yield, conformity, downtime rate). */
export function compareRatio(current: number | null, previous: number | null, higherIsBetter: boolean): Comparison {
  const delta =
    current !== null && previous !== null ? atDisplayPrecision(atDisplayPrecision(current) - atDisplayPrecision(previous)) : null;
  return { current, previous, delta, kind: "points", tone: toneFor(delta, higherIsBetter), direction: directionFor(delta) };
}

/** For an absolute quantity (tonnes, kg, minutes, cost per tonne). */
export function compareQuantity(current: number | null, previous: number | null, higherIsBetter: boolean): Comparison {
  const delta =
    current !== null && previous !== null && previous > 0 ? atDisplayPrecision(((current - previous) / previous) * 100) : null;
  return { current, previous, delta, kind: "percent", tone: toneFor(delta, higherIsBetter), direction: directionFor(delta) };
}

// --- Production / yield / waste (team-performance rows) ---------------------

export interface OperationsTotals {
  reportCount: number;
  produced: number;
  materialInput: number;
  productionMinutes: number;
  downtimeMinutes: number;
  /** Semolina-side declared waste in raw kg, minus what was declared as rebroyat. */
  netWasteKg: number;
  regrindKg: number;
  /** Raw kg by daily-report stage. */
  wasteByStageKg: Partial<Record<WasteCategory, number>>;
}

export interface TeamSummary extends OperationsTotals {
  team: string;
  yieldPct: number | null;
  downtimeRatePct: number | null;
  wasteRatePct: number | null;
}

export interface PeriodPoint {
  period: string;
  produced: number;
  materialInput: number;
}

export interface OperationsSummary {
  totals: OperationsTotals;
  yieldPct: number | null;
  downtimeRatePct: number | null;
  /** Net declared waste as a share of material poured — see wasteRate(). */
  wasteRatePct: number | null;
  /** Rows with no team on the report are in `totals` but cannot be attributed to a team. */
  byTeam: TeamSummary[];
  byPeriod: PeriodPoint[];
}

function emptyTotals(): OperationsTotals {
  return {
    reportCount: 0,
    produced: 0,
    materialInput: 0,
    productionMinutes: 0,
    downtimeMinutes: 0,
    netWasteKg: 0,
    regrindKg: 0,
    wasteByStageKg: {},
  };
}

function addRow(target: OperationsTotals, row: TeamPerformanceRow) {
  target.reportCount += row.report_count;
  target.produced += row.produced_quantity;
  target.materialInput += row.material_input_quantity;
  target.productionMinutes += row.production_minutes;
  target.downtimeMinutes += row.downtime_minutes;
  target.netWasteKg += row.net_semoule_waste;
  target.regrindKg += row.regrind_quantity;
  for (const [category, kg] of Object.entries(row.daily_waste_by_category)) {
    const key = category as WasteCategory;
    target.wasteByStageKg[key] = (target.wasteByStageKg[key] ?? 0) + (kg ?? 0);
  }
}

const KG_PER_TONNE = 1000;

/**
 * Net declared waste (kg) as a percentage of material poured.
 *
 * Waste is declared in raw kg on the daily report form, while material poured
 * is in the semolina's own unit — tonnes for this tenant (the same basis
 * WorkOrderYieldService documents, and the "t" the rest of the app formats
 * these quantities with). The kg figure is converted to tonnes before dividing.
 * A tenant that stocked semolina in kg would need this conversion revisited.
 */
export function wasteRate(totals: Pick<OperationsTotals, "netWasteKg" | "materialInput">): number | null {
  return ratioPct(totals.netWasteKg / KG_PER_TONNE, totals.materialInput);
}

export function downtimeRate(totals: Pick<OperationsTotals, "productionMinutes" | "downtimeMinutes">): number | null {
  return ratioPct(totals.downtimeMinutes, totals.productionMinutes + totals.downtimeMinutes);
}

export function summarizeOperations(rows: TeamPerformanceRow[]): OperationsSummary {
  const totals = emptyTotals();
  const teams = new Map<string, OperationsTotals>();
  const periods = new Map<string, PeriodPoint>();

  for (const row of rows) {
    addRow(totals, row);

    const point = periods.get(row.period) ?? { period: row.period, produced: 0, materialInput: 0 };
    point.produced += row.produced_quantity;
    point.materialInput += row.material_input_quantity;
    periods.set(row.period, point);

    if (!row.team) continue;
    const team = teams.get(row.team) ?? emptyTotals();
    addRow(team, row);
    teams.set(row.team, team);
  }

  const byTeam = [...teams.entries()]
    .map(([team, t]) => ({
      team,
      ...t,
      yieldPct: ratioPct(t.produced, t.materialInput),
      downtimeRatePct: downtimeRate(t),
      wasteRatePct: wasteRate(t),
    }))
    .sort((a, b) => a.team.localeCompare(b.team));

  return {
    totals,
    yieldPct: ratioPct(totals.produced, totals.materialInput),
    downtimeRatePct: downtimeRate(totals),
    wasteRatePct: wasteRate(totals),
    byTeam,
    byPeriod: [...periods.values()].sort((a, b) => a.period.localeCompare(b.period)),
  };
}

/** Waste stages ranked by declared kg, largest first, each with its share of the total. */
export function rankWasteStages(totals: OperationsTotals): { stage: WasteCategory; kg: number; sharePct: number }[] {
  const entries = Object.entries(totals.wasteByStageKg)
    .map(([stage, kg]) => ({ stage: stage as WasteCategory, kg: kg ?? 0 }))
    .filter((entry) => entry.kg > 0)
    .sort((a, b) => b.kg - a.kg);
  const total = entries.reduce((sum, entry) => sum + entry.kg, 0);
  return entries.map((entry) => ({ ...entry, sharePct: total > 0 ? (entry.kg / total) * 100 : 0 }));
}

// --- Trend -----------------------------------------------------------------

export interface TrendPoint {
  /** Day index inside the window, 0-based, so the previous window lines up underneath the current one. */
  index: number;
  date: string;
  /** The day of the previous window this index lines up with. */
  previousDate: string;
  /** null on days with no validated report — a gap, not a zero. */
  current: number | null;
  previous: number | null;
}

export function alignTrend(
  current: PeriodPoint[],
  previous: PeriodPoint[],
  windows: { current: DateWindow; previous: DateWindow },
  days: number,
): TrendPoint[] {
  const currentByDate = new Map(current.map((point) => [point.period, point.produced]));
  const previousByDate = new Map(previous.map((point) => [point.period, point.produced]));
  return Array.from({ length: days }, (_, index) => {
    const date = shiftIso(windows.current.from, index);
    const previousDate = shiftIso(windows.previous.from, index);
    return {
      index,
      date,
      previousDate,
      current: currentByDate.get(date) ?? null,
      previous: previousByDate.get(previousDate) ?? null,
    };
  });
}

// --- Quality ---------------------------------------------------------------

export interface TeamConformity {
  team: string;
  conforming: number;
  nonConforming: number;
  conformityPct: number | null;
}

export interface QualitySummary {
  conforming: number;
  nonConforming: number;
  conformityPct: number | null;
  byTeam: TeamConformity[];
}

export function summarizeConformity(rows: TeamConformityRow[]): QualitySummary {
  let conforming = 0;
  let nonConforming = 0;
  const teams = new Map<string, { conforming: number; nonConforming: number }>();
  for (const row of rows) {
    conforming += row.conforming_cartons;
    nonConforming += row.non_conforming_cartons;
    if (!row.team) continue;
    const team = teams.get(row.team) ?? { conforming: 0, nonConforming: 0 };
    team.conforming += row.conforming_cartons;
    team.nonConforming += row.non_conforming_cartons;
    teams.set(row.team, team);
  }
  return {
    conforming,
    nonConforming,
    conformityPct: ratioPct(conforming, conforming + nonConforming),
    byTeam: [...teams.entries()]
      .map(([team, t]) => ({ team, ...t, conformityPct: ratioPct(t.conforming, t.conforming + t.nonConforming) }))
      .sort((a, b) => a.team.localeCompare(b.team)),
  };
}

// --- Machines --------------------------------------------------------------

export interface MachineSummary {
  equipmentId: string;
  produced: number;
  productionMinutes: number;
  downtimeMinutes: number;
  downtimeRatePct: number | null;
  shareOfDowntimePct: number | null;
}

export interface MachinesSummary {
  totalDowntimeMinutes: number;
  /** Worst downtime first. */
  machines: MachineSummary[];
}

export function summarizeMachines(rows: MachinePerformanceRow[]): MachinesSummary {
  const byMachine = new Map<string, Omit<MachineSummary, "downtimeRatePct" | "shareOfDowntimePct">>();
  for (const row of rows) {
    const machine = byMachine.get(row.equipment_id) ?? {
      equipmentId: row.equipment_id,
      produced: 0,
      productionMinutes: 0,
      downtimeMinutes: 0,
    };
    machine.produced += row.produced_quantity;
    machine.productionMinutes += row.production_minutes;
    machine.downtimeMinutes += row.downtime_minutes;
    byMachine.set(row.equipment_id, machine);
  }
  const totalDowntimeMinutes = [...byMachine.values()].reduce((sum, machine) => sum + machine.downtimeMinutes, 0);
  const machines = [...byMachine.values()]
    .map((machine) => ({
      ...machine,
      downtimeRatePct: downtimeRate(machine),
      shareOfDowntimePct: ratioPct(machine.downtimeMinutes, totalDowntimeMinutes),
    }))
    .sort((a, b) => b.downtimeMinutes - a.downtimeMinutes);
  return { totalDowntimeMinutes, machines };
}

export interface DowntimeReason {
  reason: string;
  minutes: number;
  sharePct: number;
}

/** Minutes per stated reason, largest first. Pass `equipmentId` to restrict to one machine. */
export function rankDowntimeReasons(breakdown: DowntimeBreakdownRow[], equipmentId?: string): DowntimeReason[] {
  const byReason = new Map<string, number>();
  for (const row of breakdown) {
    if (equipmentId !== undefined && row.equipment_id !== equipmentId) continue;
    byReason.set(row.reason, (byReason.get(row.reason) ?? 0) + row.minutes);
  }
  const total = [...byReason.values()].reduce((sum, minutes) => sum + minutes, 0);
  return [...byReason.entries()]
    .map(([reason, minutes]) => ({ reason, minutes, sharePct: total > 0 ? (minutes / total) * 100 : 0 }))
    .sort((a, b) => b.minutes - a.minutes);
}

// --- Orders (OF) -----------------------------------------------------------

export interface OrderProgress {
  id: string;
  reference: string;
  productId: string | null;
  planned: number;
  produced: number;
  completionPct: number;
  remaining: number;
}

export interface OrdersSummary {
  /** Running OFs that have a planned quantity, least complete first. */
  open: OrderProgress[];
  /** Running OFs with no planned quantity — progress cannot be computed for them. */
  openWithoutPlan: number;
  planned: number;
  produced: number;
  attainmentPct: number | null;
}

export function summarizeOrders(orders: WorkOrder[], yields: WorkOrderYield[]): OrdersSummary {
  const producedByOrder = new Map(yields.map((y) => [y.work_order_id, y.produced_quantity]));
  const open: OrderProgress[] = [];
  let openWithoutPlan = 0;

  for (const order of orders) {
    if (order.status !== "ongoing") continue;
    if (order.planned_quantity === null || order.planned_quantity <= 0) {
      openWithoutPlan += 1;
      continue;
    }
    const produced = producedByOrder.get(order.id) ?? 0;
    open.push({
      id: order.id,
      reference: order.reference,
      productId: order.product_id,
      planned: order.planned_quantity,
      produced,
      completionPct: (produced / order.planned_quantity) * 100,
      remaining: Math.max(0, order.planned_quantity - produced),
    });
  }

  open.sort((a, b) => a.completionPct - b.completionPct);
  const planned = open.reduce((sum, order) => sum + order.planned, 0);
  const produced = open.reduce((sum, order) => sum + order.produced, 0);
  return { open, openWithoutPlan, planned, produced, attainmentPct: ratioPct(produced, planned) };
}

// --- Cost ------------------------------------------------------------------

export type CostAvailability = "ok" | "noProduction" | "unpriced";

export interface CostSummary {
  availability: CostAvailability;
  costPerTonne: number | null;
  previousCostPerTonne: number | null;
  variableCost: number | null;
  tonnage: number;
  label: string;
  previousLabel: string | null;
}

/**
 * Variable cost (raw material + packaging) per tonne for the recap's current
 * calendar period against the one before it. Fixed charges are not in the
 * database, so this is never the full cost of production. `unpriced` means at
 * least one consumed item has no purchase price yet — the backend deliberately
 * returns null then rather than an understated figure.
 */
export function summarizeCost(analytics: ProductionAnalytics | undefined): CostSummary | null {
  if (!analytics) return null;
  const current = analytics.current;
  const previous = analytics.trend.length >= 2 ? analytics.trend[analytics.trend.length - 2] : null;
  const availability: CostAvailability = current.tonnage <= 0 ? "noProduction" : current.cost_per_tonne === null ? "unpriced" : "ok";
  return {
    availability,
    costPerTonne: current.cost_per_tonne,
    previousCostPerTonne: previous?.cost_per_tonne ?? null,
    variableCost: current.variable_cost,
    tonnage: current.tonnage,
    label: current.label,
    previousLabel: previous?.label ?? null,
  };
}
