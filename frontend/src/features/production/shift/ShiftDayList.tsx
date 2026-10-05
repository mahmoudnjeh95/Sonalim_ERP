import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { currentLocale } from "../../../lib/i18n";
import { listUserDirectory, userDisplayName } from "../../../lib/usersApi";
import { cn } from "../../../lib/utils";
import { Badge } from "../../../components/ui/badge";
import { SECTIONS } from "./sectionConfig";
import { SECTION_KEYS, SHIFT_REPORTS_QUERY_KEY, listShiftReports, type ShiftReport } from "./shiftApi";
import { T, useLabel } from "./shiftText";
import { AppLoader } from "../../../components/patterns/AppLoader";

const DONE = new Set(["submitted", "nothing_to_report"]);

interface Combo {
  workCenterId: string;
  workCenterName: string;
  shiftName: string;
  shift: ShiftReport | null;
}

/** One row per line-and-shift for a date, across every line — what the paper folder for that day would show. */
export function ShiftDayList({
  date,
  workCenters,
  windows,
  currentShiftName,
  onOpen,
}: {
  date: string;
  workCenters: { id: string; name: string }[];
  windows: { shift: string }[];
  /** The shift the plant clock is in right now, or "" when today is not the date shown. */
  currentShiftName: string;
  onOpen: (workCenterId: string, shiftName: string) => void;
}) {
  const { session, hasPermission } = useAuth();
  const token = session!.token;
  const label = useLabel();
  const canCreate = SECTION_KEYS.some((k) => hasPermission(`production.shift.edit.${k}`));

  const day = useQuery({
    queryKey: [...SHIFT_REPORTS_QUERY_KEY, "day", date],
    queryFn: () => listShiftReports(token, { report_date: date }),
  });
  const users = useQuery({ queryKey: ["core", "user-directory"], queryFn: () => listUserDirectory(token) });
  const who = (id: string | null) => {
    const user = users.data?.find((u) => u.id === id);
    return user ? userDisplayName(user) : null;
  };

  const combos = useMemo<Combo[]>(() => {
    const byLineShift = new Map((day.data ?? []).map((s) => [`${s.work_center_id}|${s.shift.trim().toLowerCase()}`, s]));
    const out: Combo[] = [];
    for (const wc of workCenters) {
      for (const w of windows) {
        const shift = byLineShift.get(`${wc.id}|${w.shift.trim().toLowerCase()}`) ?? null;
        if (!shift && !canCreate) continue; // nothing to see and nothing this viewer could create
        out.push({ workCenterId: wc.id, workCenterName: wc.name, shiftName: w.shift, shift });
      }
    }
    return out;
  }, [day.data, workCenters, windows, canCreate]);

  if (day.isLoading) return <AppLoader label={label(T.loading)} className="py-8" />;

  return (
    <div className="space-y-2">
      {combos.map((combo) => {
        const isCurrent = combo.shiftName.trim().toLowerCase() === currentShiftName.trim().toLowerCase();
        const total = SECTIONS.length;
        const done = combo.shift ? combo.shift.sections.filter((s) => DONE.has(s.status)).length : 0;
        const lastTouched = combo.shift
          ? [...combo.shift.sections]
              .filter((s) => s.submitted_at)
              .sort((a, b) => (a.submitted_at! < b.submitted_at! ? 1 : -1))[0]
          : undefined;
        return (
          <button
            key={`${combo.workCenterId}|${combo.shiftName}`}
            type="button"
            onClick={() => onOpen(combo.workCenterId, combo.shiftName)}
            className={cn(
              "flex w-full flex-wrap items-center gap-3 rounded-lg border bg-background px-4 py-3 text-left transition-colors hover:bg-muted",
              isCurrent ? "border-primary/50 ring-1 ring-primary/30" : "border-border",
            )}
          >
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">
                {combo.workCenterName} — {combo.shiftName}
              </p>
              <p className="text-xs text-muted-foreground">
                {combo.shift
                  ? lastTouched
                    ? `${label(T.lastTouched)} ${who(lastTouched.submitted_by) ?? "—"}, ${new Date(lastTouched.submitted_at!).toLocaleString(currentLocale(), { dateStyle: "medium", timeStyle: "short" })}`
                    : label(T.status.empty)
                  : label(T.noReportYet)}
              </p>
            </div>
            {combo.shift ? (
              <>
                {/* Named, because the line cards above show a different count (reports
                    opened out of shifts) and a bare "3/3" beside "0/9" reads as a contradiction. */}
                <span className="whitespace-nowrap text-xs tabular-nums text-muted-foreground">
                  {done}/{total} {label(T.sectionsHandedIn)}
                </span>
                <Badge
                  variant={
                    combo.shift.status === "validated"
                      ? "success"
                      : combo.shift.status === "returned"
                        ? "destructive"
                        : combo.shift.status === "submitted"
                          ? "primary"
                          : "warning"
                  }
                  dot
                >
                  {label(T.shiftStatus[combo.shift.status])}
                </Badge>
                {isCurrent && <Badge variant="primary">{label(T.continueShift)}</Badge>}
              </>
            ) : (
              <Badge variant="outline" className="gap-1">
                <Plus className="h-3 w-3" />
                {label(T.newShift)}
              </Badge>
            )}
          </button>
        );
      })}
    </div>
  );
}
