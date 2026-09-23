import { useMemo } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import { listEnergyAnalytics, type EnergyAnalyticsRow } from "../../production/api";
import { buildWindows, localTodayIso } from "./metrics";
import type { PeriodDays } from "../PeriodFilter";

export interface EnergyTotals {
  fuel: number;
  gasoil: number;
  generatorHours: number;
  electricity: number;
  produced: number;
}

export interface EnergyByLine {
  workCenterId: string;
  totals: EnergyTotals;
  fuelPerTonne: number | null;
  gasoilPerTonne: number | null;
  electricityPerTonne: number | null;
}

export interface EnergySummary {
  totals: EnergyTotals;
  fuelPerTonne: number | null;
  gasoilPerTonne: number | null;
  electricityPerTonne: number | null;
  /** One point per day with a validated shift: a day whose shifts recorded 0 fioul plots 0, not a gap. */
  byDate: { date: string; fuel: number; gasoil: number; electricity: number }[];
  byLine: EnergyByLine[];
}

function emptyTotals(): EnergyTotals {
  return { fuel: 0, gasoil: 0, generatorHours: 0, electricity: 0, produced: 0 };
}

// A blank field adds nothing to a sum; the shift's other figures still count.
function addRow(target: EnergyTotals, row: EnergyAnalyticsRow) {
  target.fuel += row.fuel_quantity ?? 0;
  target.gasoil += row.gasoil_quantity ?? 0;
  target.generatorHours += row.generator_hours ?? 0;
  target.electricity += row.electricity_quantity ?? 0;
  target.produced += row.produced_quantity;
}

const perTonne = (value: number, produced: number) => (produced > 0 ? value / produced : null);

/** Fioul and gasoil stay separate series throughout: they are different fuels. Per-tonne
 * figures divide by produced_quantity read from the same shifts as the energy, so the two
 * can never come from different windows. */
export function summarizeEnergy(rows: EnergyAnalyticsRow[]): EnergySummary {
  const totals = emptyTotals();
  const byDateMap = new Map<string, { fuel: number; gasoil: number; electricity: number }>();
  const byLineMap = new Map<string, EnergyTotals>();

  for (const row of rows) {
    addRow(totals, row);

    const d = byDateMap.get(row.report_date) ?? { fuel: 0, gasoil: 0, electricity: 0 };
    d.fuel += row.fuel_quantity ?? 0;
    d.gasoil += row.gasoil_quantity ?? 0;
    d.electricity += row.electricity_quantity ?? 0;
    byDateMap.set(row.report_date, d);

    const l = byLineMap.get(row.work_center_id) ?? emptyTotals();
    addRow(l, row);
    byLineMap.set(row.work_center_id, l);
  }

  const byLine = [...byLineMap.entries()]
    .map(([workCenterId, t]) => ({
      workCenterId,
      totals: t,
      fuelPerTonne: perTonne(t.fuel, t.produced),
      gasoilPerTonne: perTonne(t.gasoil, t.produced),
      electricityPerTonne: perTonne(t.electricity, t.produced),
    }))
    .sort((a, b) => a.workCenterId.localeCompare(b.workCenterId));

  return {
    totals,
    fuelPerTonne: perTonne(totals.fuel, totals.produced),
    gasoilPerTonne: perTonne(totals.gasoil, totals.produced),
    electricityPerTonne: perTonne(totals.electricity, totals.produced),
    byDate: [...byDateMap.entries()].map(([date, v]) => ({ date, ...v })).sort((a, b) => a.date.localeCompare(b.date)),
    byLine,
  };
}

export function useEnergyAnalytics(days: PeriodDays) {
  const { session } = useAuth();
  const token = session!.token;
  const today = useMemo(() => localTodayIso(), []);
  const windows = useMemo(() => buildWindows(days, today), [days, today]);
  const { current, previous } = windows;

  const energyCurrent = useQuery({
    queryKey: ["analytics", "energy", current.from, current.to],
    placeholderData: keepPreviousData,
    queryFn: () => listEnergyAnalytics(token, { date_from: current.from, date_to: current.to }),
  });
  const energyPrevious = useQuery({
    queryKey: ["analytics", "energy", previous.from, previous.to],
    placeholderData: keepPreviousData,
    queryFn: () => listEnergyAnalytics(token, { date_from: previous.from, date_to: previous.to }),
  });

  const summary = useMemo(() => summarizeEnergy(energyCurrent.data ?? []), [energyCurrent.data]);
  const previousSummary = useMemo(() => summarizeEnergy(energyPrevious.data ?? []), [energyPrevious.data]);

  return { windows, energyCurrent, energyPrevious, summary, previousSummary };
}
