import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { getReport, type ProductionReport, type WorkOrderStatus } from "./api";
import { deriveStageStates } from "./productionSteps";

/**
 * Where an OF stands in the plant, read from what its reports actually hold.
 * The list endpoint carries no figures, so each live report's detail is fetched
 * — under the same key the report dialogs use, so opening one costs nothing.
 */
export function useOfStageStates(token: string, reports: ProductionReport[], orderStatus: WorkOrderStatus) {
  const live = useMemo(() => reports.filter((report) => report.status !== "rejected"), [reports]);

  const results = useQueries({
    queries: live.map((report) => ({
      queryKey: ["production", "reports", report.id],
      queryFn: () => getReport(token, report.id),
    })),
  });

  const isLoading = results.some((result) => result.isLoading);
  // useQueries returns a fresh array every render; depend on the data itself.
  const signature = results.map((result) => result.dataUpdatedAt).join(",");

  const details = useMemo(
    () => new Map(live.map((report, index) => [report.id, results[index]?.data?.detail ?? null] as const)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [live, signature],
  );
  const states = useMemo(() => deriveStageStates(reports, details, orderStatus), [reports, details, orderStatus]);

  return { states, details, isLoading };
}
