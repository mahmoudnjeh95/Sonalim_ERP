import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, useReducedMotion } from "framer-motion";
import { CalendarDays, ClipboardList, Lock, RotateCcw, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "../../../lib/api";
import { useAuth } from "../../../lib/auth";
import { cn } from "../../../lib/utils";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent } from "../../../components/ui/card";
import { Input } from "../../../components/ui/input";
import { Label as FieldLabel } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { SectionCard } from "./SectionCard";
import { ShiftRail } from "./ShiftRail";
import type { OptionMap } from "./ShiftGrid";
import { useShiftReferenceData } from "./useShiftReferenceData";
import type { ShiftWindowRow } from "../board/api";
import { SECTIONS } from "./sectionConfig";
import {
  SECTION_KEYS,
  SHIFT_REPORTS_QUERY_KEY,
  getShiftReport,
  listShiftReports,
  openShiftReport,
  updateShiftHeader,
  type HeaderFields,
  type SectionKey,
  type ShiftReport,
} from "./shiftApi";
import { T, useLabel } from "./shiftText";
import { AppLoader } from "../../../components/patterns/AppLoader";

const DONE = new Set(["submitted", "nothing_to_report"]);

const pad = (n: number) => String(n).padStart(2, "0");
const todayIso = () => {
  const now = new Date();
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
};

/** The window the clock is in right now (across midnight for a night shift), else the first. */
function currentShift(windows: ShiftWindowRow[]): string {
  const now = new Date();
  const minutes = now.getHours() * 60 + now.getMinutes();
  const toMinutes = (value: string) => {
    const [h, m] = value.split(":").map(Number);
    return h * 60 + (m || 0);
  };
  const inside = windows.find((w) => {
    const start = toMinutes(w.start_time);
    const end = toMinutes(w.end_time);
    return start <= end ? minutes >= start && minutes < end : minutes >= start || minutes < end;
  });
  return (inside ?? windows[0])?.shift ?? "";
}

const HEADER_FIELDS: { key: keyof HeaderFields; label: typeof T.team }[] = [
  { key: "team", label: T.team },
  { key: "conducteur", label: T.conducteur },
  { key: "agent_fabrication", label: T.agentFabrication },
  { key: "machiniste", label: T.machiniste },
  { key: "aide_machiniste", label: T.aideMachiniste },
];

export function ShiftReportTab() {
  const { session, hasPermission } = useAuth();
  const token = session!.token;
  const label = useLabel();
  const queryClient = useQueryClient();
  const canView = hasPermission("production.shift.view");

  const [date, setDate] = useState(todayIso);
  const [workCenterId, setWorkCenterId] = useState("");
  const [shiftName, setShiftName] = useState("");
  const [openKeys, setOpenKeys] = useState<Set<SectionKey>>(new Set());

  // ---- reference data -------------------------------------------------------
  const reference = useShiftReferenceData(canView);
  const workCenters = { data: reference.workCenters, isLoading: reference.workCentersLoading };
  const windows = reference.windows;

  // The first usable line and the shift the clock is in, until the team picks its own.
  useEffect(() => {
    if (!workCenterId && workCenters.data?.length) {
      setWorkCenterId((workCenters.data.find((w) => !w.is_blocked) ?? workCenters.data[0]).id);
    }
  }, [workCenterId, workCenters.data]);
  useEffect(() => {
    if (!shiftName && windows.length) setShiftName(currentShift(windows));
  }, [shiftName, windows]);

  // ---- the shift for this line, date and shift ------------------------------
  const found = useQuery({
    queryKey: [...SHIFT_REPORTS_QUERY_KEY, "find", date, workCenterId],
    queryFn: () => listShiftReports(token, { report_date: date, work_center_id: workCenterId }),
    enabled: canView && !!workCenterId,
  });
  const existing = found.data?.find((s) => s.shift.trim().toLowerCase() === shiftName.trim().toLowerCase());
  const detail = useQuery({
    queryKey: [...SHIFT_REPORTS_QUERY_KEY, "one", existing?.id],
    queryFn: () => getShiftReport(token, existing!.id),
    enabled: canView && !!existing,
  });
  const shift = detail.data;

  const refresh = () => queryClient.invalidateQueries({ queryKey: SHIFT_REPORTS_QUERY_KEY });

  const fail = (error: unknown) =>
    toast.error(label(T.failed), { description: error instanceof ApiError ? error.message : undefined });

  const open = useMutation({
    mutationFn: () => openShiftReport(token, { work_center_id: workCenterId, report_date: date, shift: shiftName }),
    onSuccess: () => {
      toast.success(label(T.opened));
      refresh();
    },
    onError: fail,
  });

  // Open the first section still to do when a shift loads, so the team lands where the work is.
  const shiftId = shift?.id;
  useEffect(() => {
    if (!shift) return;
    const next = SECTIONS.find((s) => !DONE.has(shift.sections.find((x) => x.key === s.key)?.status ?? "empty"));
    setOpenKeys(new Set(next ? [next.key] : []));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shiftId]);

  const toggle = (key: SectionKey) =>
    setOpenKeys((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const jump = (key: SectionKey) => {
    setOpenKeys((current) => new Set(current).add(key));
    window.setTimeout(() => document.getElementById(`shift-section-${key}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
  };

  // ---- select choices -------------------------------------------------------
  const options = useMemo<OptionMap>(() => reference.buildOptions(shift, workCenterId), [reference.buildOptions, shift, workCenterId]);

  // ---- render ---------------------------------------------------------------
  if (!canView) {
    return (
      <Card>
        <CardContent className="flex items-start gap-3 py-8 text-sm text-muted-foreground">
          <Lock className="mt-0.5 h-4 w-4 shrink-0" />
          {label(T.noAccess)}
        </CardContent>
      </Card>
    );
  }

  const linesReady = !workCenters.isLoading && (workCenters.data?.length ?? 0) > 0;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold tracking-tight">
          <ClipboardList className="h-5 w-5 text-primary" />
          {label(T.title)}
        </h2>
        <p className="text-sm text-muted-foreground">{label(T.subtitle)}</p>
      </div>

      <Card>
        <CardContent className="space-y-4 py-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="space-y-1">
              <FieldLabel htmlFor="shift-date" className="text-xs text-muted-foreground">
                {label(T.date)}
              </FieldLabel>
              <Input id="shift-date" type="date" value={date} onChange={(e) => setDate(e.target.value || todayIso())} />
            </div>
            <div className="space-y-1">
              <FieldLabel htmlFor="shift-line" className="text-xs text-muted-foreground">
                {label(T.line)}
              </FieldLabel>
              <Select id="shift-line" value={workCenterId} onChange={(e) => setWorkCenterId(e.target.value)}>
                {(workCenters.data ?? []).map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1">
              <FieldLabel htmlFor="shift-name" className="text-xs text-muted-foreground">
                {label(T.shift)}
              </FieldLabel>
              <Select id="shift-name" value={shiftName} onChange={(e) => setShiftName(e.target.value)}>
                {windows.map((w) => (
                  <option key={w.shift} value={w.shift}>
                    {w.shift} ({w.start_time.slice(0, 5)}–{w.end_time.slice(0, 5)})
                  </option>
                ))}
              </Select>
            </div>
            <div className="flex items-end">
              {shift && <ShiftStatusBadge status={shift.status} />}
            </div>
          </div>

          {shift && (
            <HeaderNames
              key={shift.id}
              shift={shift}
              locked={shift.status === "validated" || !SECTION_KEYS.some((k) => hasPermission(`production.shift.edit.${k}`))}
              onSaved={refresh}
              onError={fail}
            />
          )}
        </CardContent>
      </Card>

      {!linesReady && !workCenters.isLoading && (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">{label(T.noLines)}</CardContent>
        </Card>
      )}

      {linesReady && (found.isLoading || (existing && detail.isLoading)) && (
        <AppLoader label={label(T.loading)} className="py-8" />
      )}

      {linesReady && !found.isLoading && !existing && (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
            <CalendarDays className="h-8 w-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">{label(T.openHint)}</p>
            <Button
              onClick={() => open.mutate()}
              disabled={open.isPending || !SECTION_KEYS.some((k) => hasPermission(`production.shift.edit.${k}`)) || !shiftName}
            >
              {label(T.openShift)}
            </Button>
          </CardContent>
        </Card>
      )}

      {shift && (
        <div className="space-y-3">
          <ShiftRail states={shift.sections} onJump={jump} />
          <div className="space-y-3">
            {SECTIONS.map((def) => {
              const state = shift.sections.find((s) => s.key === def.key);
              if (!state) return null;
              return (
                <SectionCard
                  key={def.key}
                  def={def}
                  state={state}
                  shift={shift}
                  canEdit={hasPermission(`production.shift.edit.${def.key}`)}
                  options={options}
                  open={openKeys.has(def.key)}
                  onToggle={() => toggle(def.key)}
                  onChanged={refresh}
                />
              );
            })}
          </div>
        </div>
      )}

      {shift && <ShiftStatusBar shift={shift} />}
    </div>
  );
}

function ShiftStatusBadge({ status }: { status: ShiftReport["status"] }) {
  const label = useLabel();
  const variant = status === "validated" ? "success" : status === "returned" ? "destructive" : status === "submitted" ? "primary" : "warning";
  return (
    <Badge variant={variant} dot>
      {label(T.shiftStatus[status])}
    </Badge>
  );
}

/** The names on the paper header, saved when the field is left. */
function HeaderNames({
  shift,
  locked,
  onSaved,
  onError,
}: {
  shift: ShiftReport;
  locked: boolean;
  onSaved: () => void;
  onError: (error: unknown) => void;
}) {
  const { session } = useAuth();
  const label = useLabel();
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(HEADER_FIELDS.map((f) => [f.key, shift[f.key] ?? ""])),
  );
  // What earlier shifts put in each field, most used first, offered as suggestions.
  const earlier = useQuery({
    queryKey: [...SHIFT_REPORTS_QUERY_KEY, "names"],
    queryFn: () => listShiftReports(session!.token),
    staleTime: 5 * 60 * 1000,
  });
  const suggestions = useMemo(() => {
    const out: Record<string, string[]> = {};
    for (const field of HEADER_FIELDS) {
      const counts = new Map<string, number>();
      for (const past of earlier.data ?? []) {
        const value = past[field.key]?.trim();
        if (value) counts.set(value, (counts.get(value) ?? 0) + 1);
      }
      out[field.key] = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([v]) => v);
    }
    return out;
  }, [earlier.data]);

  const save = useMutation({
    mutationFn: (fields: HeaderFields) => updateShiftHeader(session!.token, shift.id, fields),
    onSuccess: () => {
      toast.success(label(T.headerSaved));
      onSaved();
    },
    onError,
  });

  return (
    <div className="grid gap-3 border-t border-border pt-4 sm:grid-cols-2 lg:grid-cols-5">
      {HEADER_FIELDS.map((field) => (
        <div key={field.key} className="space-y-1">
          <FieldLabel htmlFor={`shift-${field.key}`} className="text-xs text-muted-foreground">
            {label(field.label)}
          </FieldLabel>
          <Input
            id={`shift-${field.key}`}
            list={`shift-${field.key}-suggestions`}
            autoComplete="off"
            value={values[field.key]}
            disabled={locked}
            onChange={(e) => setValues((current) => ({ ...current, [field.key]: e.target.value }))}
            onBlur={() => {
              if ((shift[field.key] ?? "") !== values[field.key].trim()) save.mutate({ [field.key]: values[field.key].trim() || null });
            }}
          />
          <datalist id={`shift-${field.key}-suggestions`}>
            {suggestions[field.key].map((value) => (
              <option key={value} value={value} />
            ))}
          </datalist>
        </div>
      ))}
    </div>
  );
}

/** Where the shift stands, pinned to the bottom so it is in view however far the team scrolls. */
function ShiftStatusBar({ shift }: { shift: ShiftReport }) {
  const label = useLabel();
  const reduceMotion = useReducedMotion();
  const done = shift.sections.filter((s) => DONE.has(s.status)).length;
  const total = SECTIONS.length;
  const returned = shift.sections.filter((s) => s.status === "returned").length;

  let tone = "border-border";
  let Icon = ClipboardList;
  let message = `${total - done} ${label(T.toGo)}`;
  if (shift.status === "validated") {
    tone = "border-success/40 bg-success-soft";
    Icon = ShieldCheck;
    message = label(T.validatedHint);
  } else if (shift.status === "returned" || returned > 0) {
    tone = "border-destructive/40 bg-destructive-soft";
    Icon = RotateCcw;
    message = label(T.returnedHint);
  } else if (done === total) {
    tone = "border-success/40 bg-success-soft";
    Icon = ShieldCheck;
    message = label(T.allIn);
  }

  return (
    <div className="pointer-events-none sticky bottom-4 z-20 flex justify-center px-2">
      <div className={cn("pointer-events-auto flex w-full max-w-2xl items-center gap-3 rounded-xl border bg-background px-4 py-2.5 shadow-raised", tone)}>
        <Icon className="h-4 w-4 shrink-0" aria-hidden />
        <span className="min-w-0 flex-1 truncate text-sm">{message}</span>
        <div className="flex shrink-0 items-center gap-2" aria-label={label(T.progress)}>
          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-muted">
            <motion.div
              className="h-full rounded-full bg-success"
              initial={false}
              animate={{ width: `${(done / total) * 100}%` }}
              transition={reduceMotion ? { duration: 0 } : { duration: 0.45, ease: "easeOut" }}
            />
          </div>
          <span className="text-xs tabular-nums text-muted-foreground">
            {done}/{total}
          </span>
        </div>
      </div>
    </div>
  );
}
