import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ListRestart } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { currentLocale } from "../../../lib/i18n";
import { Badge } from "../../../components/ui/badge";
import { SHIFT_REPORTS_QUERY_KEY, listShiftReports, type ShiftReport } from "./shiftApi";
import { T, useLabel } from "./shiftText";

/** "2026-10-01" -> "1 oct." — the day, short, read as a calendar day rather than an instant. */
function shortDay(iso: string): string {
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  if (!year || !month || !day) return iso;
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString(currentLocale(), {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

/**
 * Shifts nobody has finished: still 'open', or sent back by a validator. Shown across
 * every date so a team does not have to remember which day they left off on.
 */
export function UnfinishedStrip({
  workCenterName,
  onPick,
}: {
  workCenterName: (id: string) => string;
  onPick: (shift: ShiftReport) => void;
}) {
  const { session } = useAuth();
  const token = session!.token;
  const label = useLabel();

  const open = useQuery({
    queryKey: [...SHIFT_REPORTS_QUERY_KEY, "unfinished", "open"],
    queryFn: () => listShiftReports(token, { status: "open" }),
  });
  const returned = useQuery({
    queryKey: [...SHIFT_REPORTS_QUERY_KEY, "unfinished", "returned"],
    queryFn: () => listShiftReports(token, { status: "returned" }),
  });

  // Newest first, and only a handful: this is a way back into recent work, not a list.
  const shifts = useMemo(
    () =>
      [...(open.data ?? []), ...(returned.data ?? [])]
        .sort((a, b) => (a.report_date < b.report_date ? 1 : a.report_date > b.report_date ? -1 : 0))
        .slice(0, 8),
    [open.data, returned.data],
  );

  if (shifts.length === 0) return null;

  return (
    <div className="flex items-center gap-2 overflow-x-auto rounded-lg border border-border bg-muted/30 px-3 py-2">
      <ListRestart className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
      <span className="shrink-0 text-xs font-medium text-muted-foreground">{label(T.unfinishedTitle)}</span>
      <div className="flex items-center gap-2">
        {shifts.map((shift) => (
          <button
            key={shift.id}
            type="button"
            onClick={() => onPick(shift)}
            className="flex shrink-0 items-center gap-2 rounded-md border border-border bg-background px-2.5 py-1 text-xs transition-colors hover:bg-muted"
          >
            <span className="font-medium">{workCenterName(shift.work_center_id)}</span>
            <span className="whitespace-nowrap text-muted-foreground">
              {shortDay(shift.report_date)} · {shift.shift}
            </span>
            {shift.status === "returned" && <Badge variant="destructive">{label(T.shiftStatus.returned)}</Badge>}
          </button>
        ))}
      </div>
    </div>
  );
}
