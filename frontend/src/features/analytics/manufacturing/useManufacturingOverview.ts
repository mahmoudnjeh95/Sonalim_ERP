import { useMemo } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import {
  getProductionAnalytics,
  listDowntimeBreakdown,
  listMachinePerformance,
  listMachines,
  listTeamPerformance,
  listWorkOrders,
  listWorkOrderYields,
} from "../../production/api";
import { listQualityTeamPerformance } from "../../qc/api";
import { listProducts } from "../../warehouse/api";
import {
  alignTrend,
  buildWindows,
  localTodayIso,
  summarizeConformity,
  summarizeCost,
  summarizeMachines,
  summarizeOperations,
  summarizeOrders,
} from "./metrics";

const ROOT = ["analytics", "overview"] as const;

/**
 * Output, yield, downtime and waste for the last `days` days and the equal
 * window before it — the part of the Overview that the Yield & waste tab shares.
 */
export function useOperationsData(days: number) {
  const { session } = useAuth();
  const token = session!.token;
  const today = useMemo(() => localTodayIso(), []);
  const windows = useMemo(() => buildWindows(days, today), [days, today]);
  const { current, previous } = windows;

  const teamCurrent = useQuery({
    queryKey: [...ROOT, "team", current.from, current.to],
    placeholderData: keepPreviousData,
    queryFn: () => listTeamPerformance(token, { grain: "day", date_from: current.from, date_to: current.to }),
  });
  const teamPrevious = useQuery({
    queryKey: [...ROOT, "team", previous.from, previous.to],
    placeholderData: keepPreviousData,
    queryFn: () => listTeamPerformance(token, { grain: "day", date_from: previous.from, date_to: previous.to }),
  });

  const ops = useMemo(() => summarizeOperations(teamCurrent.data ?? []), [teamCurrent.data]);
  const previousOps = useMemo(() => summarizeOperations(teamPrevious.data ?? []), [teamPrevious.data]);
  const trend = useMemo(
    () => alignTrend(ops.byPeriod, previousOps.byPeriod, windows, days),
    [ops.byPeriod, previousOps.byPeriod, windows, days],
  );

  return { token, today, windows, teamCurrent, teamPrevious, ops, previousOps, trend };
}

/**
 * Every figure on the Overview, from the endpoints the team/machine/recap tabs
 * already use. Each source is its own query so one failing (e.g. no QC
 * permission) leaves the others rendering; callers read `.isError` per source
 * and show an explicit unavailable state rather than a zero.
 */
export function useManufacturingOverview(days: number) {
  const { token, today, windows, teamCurrent, teamPrevious, ops, previousOps, trend } = useOperationsData(days);
  const { current, previous } = windows;

  const qualityCurrent = useQuery({
    queryKey: [...ROOT, "quality", current.from, current.to],
    placeholderData: keepPreviousData,
    queryFn: () => listQualityTeamPerformance(token, { grain: "day", date_from: current.from, date_to: current.to }),
  });
  const qualityPrevious = useQuery({
    queryKey: [...ROOT, "quality", previous.from, previous.to],
    placeholderData: keepPreviousData,
    queryFn: () => listQualityTeamPerformance(token, { grain: "day", date_from: previous.from, date_to: previous.to }),
  });
  const machinePerformance = useQuery({
    queryKey: [...ROOT, "machines", current.from, current.to],
    placeholderData: keepPreviousData,
    queryFn: () => listMachinePerformance(token, { grain: "year", date_from: current.from, date_to: current.to }),
  });
  const downtimeBreakdown = useQuery({
    queryKey: [...ROOT, "downtime", current.from, current.to],
    placeholderData: keepPreviousData,
    queryFn: () => listDowntimeBreakdown(token, { date_from: current.from, date_to: current.to }),
  });
  const machineList = useQuery({ queryKey: ["production", "machines", "all"], queryFn: () => listMachines(token) });
  const workOrders = useQuery({ queryKey: [...ROOT, "work-orders"], queryFn: () => listWorkOrders(token) });
  const workOrderYields = useQuery({ queryKey: [...ROOT, "work-order-yields"], queryFn: () => listWorkOrderYields(token) });
  const products = useQuery({ queryKey: ["core", "products"], queryFn: () => listProducts(token) });
  const costAnalytics = useQuery({
    queryKey: [...ROOT, "cost", today],
    queryFn: () => getProductionAnalytics(token, { date: today, period: "month" }),
  });

  const quality = useMemo(() => (qualityCurrent.data ? summarizeConformity(qualityCurrent.data) : null), [qualityCurrent.data]);
  const previousQuality = useMemo(() => (qualityPrevious.data ? summarizeConformity(qualityPrevious.data) : null), [qualityPrevious.data]);
  const machines = useMemo(() => (machinePerformance.data ? summarizeMachines(machinePerformance.data) : null), [machinePerformance.data]);
  const orders = useMemo(
    () => (workOrders.data && workOrderYields.data ? summarizeOrders(workOrders.data, workOrderYields.data) : null),
    [workOrders.data, workOrderYields.data],
  );
  const cost = useMemo(() => summarizeCost(costAnalytics.data), [costAnalytics.data]);

  return {
    windows,
    sources: {
      teamCurrent,
      teamPrevious,
      qualityCurrent,
      qualityPrevious,
      machinePerformance,
      downtimeBreakdown,
      machineList,
      workOrders,
      workOrderYields,
      products,
      costAnalytics,
    },
    ops,
    previousOps,
    quality,
    previousQuality,
    machines,
    breakdown: downtimeBreakdown.data ?? [],
    machineRecords: machineList.data ?? [],
    productRecords: products.data ?? [],
    orders,
    cost,
    trend,
  };
}
