import { useMemo } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { getReport, getStageSignals, type ProductionReport, type WorkOrderStatus } from "./api";
import { deriveStageStates, type ProductionStepId } from "./productionSteps";

/**
 * Where an OF stands in the plant, read from what its reports actually hold.
 *
 * `states` (which stage is empty/pending/done) needs only three booleans per
 * report, so it comes from one call to the stage-signals endpoint rather than
 * fetching every report's full detail — a long-running OF can carry hundreds
 * of reports, and that used to mean hundreds of round trips just to draw the
 * Flux de production card.
 *
 * `details` — the actual figures, for the popup a click on a stage opens —
 * stays per-report, but only for the reports the open stage's `state.reports`
 * names, and only once a stage is actually open. `openStepId` is `null` while
 * nothing is open, which fetches nothing.
 */
export function useOfStageStates(
  token: string,
  reports: ProductionReport[],
  orderStatus: WorkOrderStatus,
  openStepId: ProductionStepId | null,
) {
  const of_id = reports[0]?.of_id;

  const signalsQuery = useQuery({
    queryKey: ["production", "stage-signals", of_id],
    queryFn: () => getStageSignals(token, of_id!),
    enabled: Boolean(of_id),
  });
  const signals = useMemo(() => new Map(Object.entries(signalsQuery.data ?? {})), [signalsQuery.data]);

  const states = useMemo(() => deriveStageStates(reports, signals, orderStatus), [reports, signals, orderStatus]);

  const openReports = openStepId ? (states[openStepId]?.reports ?? []) : [];
  const detailResults = useQueries({
    queries: openReports.map((report) => ({
      queryKey: ["production", "reports", report.id],
      queryFn: () => getReport(token, report.id),
    })),
  });
  const detailSignature = detailResults.map((result) => result.dataUpdatedAt).join(",");
  const details = useMemo(
    () => new Map(openReports.map((report, index) => [report.id, detailResults[index]?.data?.detail ?? null] as const)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [openReports, detailSignature],
  );

  return {
    states,
    details,
    isLoading: signalsQuery.isLoading,
    detailsLoading: openStepId !== null && detailResults.some((result) => result.isLoading),
  };
}
