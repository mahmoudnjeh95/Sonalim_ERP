import { useMemo } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import { getShiftHealth } from "../../production/api";
import { buildWindows, localTodayIso } from "./metrics";
import type { PeriodDays } from "../PeriodFilter";

export function useShiftHealth(days: PeriodDays) {
  const { session } = useAuth();
  const token = session!.token;
  const today = useMemo(() => localTodayIso(), []);
  const windows = useMemo(() => buildWindows(days, today), [days, today]);

  const health = useQuery({
    queryKey: ["analytics", "shift-health", windows.current.from, windows.current.to],
    placeholderData: keepPreviousData,
    queryFn: () => getShiftHealth(token, { date_from: windows.current.from, date_to: windows.current.to }),
  });

  return { windows, health };
}
