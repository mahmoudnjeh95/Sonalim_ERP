import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../lib/auth";
import { DASHBOARD_SETTINGS_QUERY_KEY, getDashboardSettings, type ShiftWindowRow } from "./board/api";

/**
 * The hours the plant configured for a shift (Production settings > Dashboard
 * configuration), or null when it has not set them or no shift is chosen.
 *
 * A report form reads a shift's length from here rather than carrying its own
 * 7 / 8 / 9 hours: the Excel this replaces had those three numbers typed into the
 * formulas of its day sheets, so changing a shift's hours meant editing every sheet.
 * Matched on the name case-insensitively, the way the backend matches a report's
 * shift to its window.
 */
export function useShiftWindow() {
  const { session } = useAuth();
  const settings = useQuery({
    queryKey: DASHBOARD_SETTINGS_QUERY_KEY,
    queryFn: () => getDashboardSettings(session!.token),
  });
  const windows = settings.data?.shift_windows;
  return useCallback(
    (shift: string | null | undefined): ShiftWindowRow | null => {
      const wanted = shift?.trim().toLowerCase();
      if (!wanted) return null;
      return windows?.find((window) => window.shift.trim().toLowerCase() === wanted) ?? null;
    },
    [windows],
  );
}
