import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, ClipboardCheck, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "../../../lib/api";
import { useAuth } from "../../../lib/auth";
import { cn } from "../../../lib/utils";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Input } from "../../../components/ui/input";
import { Part } from "./SectionCard";
import type { OptionMap } from "./ShiftGrid";
import { StatusNode } from "./StatusNode";
import { SECTIONS, type SectionDef } from "./sectionConfig";
import { toDraft } from "./shiftModel";
import {
  SHIFT_REPORTS_QUERY_KEY,
  getShiftReport,
  listShiftReports,
  rejectShiftSections,
  validateShiftReport,
  type SectionKey,
  type SectionState,
} from "./shiftApi";
import { T, useLabel } from "./shiftText";
import { useShiftReferenceData } from "./useShiftReferenceData";
import { AppLoader } from "../../../components/patterns/AppLoader";

/**
 * The shifts whose every section is in, waiting for a validator. One approval takes the
 * whole shift; sections that need fixing are sent back by name, with a reason, and the
 * rest stay handed in.
 */
export function ShiftValidationPanel() {
  const { session, hasPermission } = useAuth();
  const token = session!.token;
  const label = useLabel();
  const allowed = hasPermission("production.shift.validate") && hasPermission("production.shift.view");
  const reference = useShiftReferenceData(allowed);
  const [reviewing, setReviewing] = useState<string | null>(null);

  const waiting = useQuery({
    queryKey: [...SHIFT_REPORTS_QUERY_KEY, "awaiting"],
    queryFn: () => listShiftReports(token, { status: "submitted" }),
    enabled: allowed,
  });

  if (!allowed) return null;
  const lineName = new Map((reference.workCenters ?? []).map((w) => [w.id, w.name]));
  const shifts = waiting.data ?? [];

  return (
    <>
      <Card>
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2">
              <ClipboardCheck className="h-4 w-4 text-primary" />
              {label(T.awaitingTitle)}
            </CardTitle>
            <p className="mt-0.5 text-sm text-muted-foreground">{label(T.awaitingHint)}</p>
          </div>
          {shifts.length > 0 && <Badge variant="primary">{shifts.length}</Badge>}
        </CardHeader>
        <CardContent className="p-0">
          {waiting.isLoading ? (
            <AppLoader size={120} className="py-6" />
          ) : shifts.length === 0 ? (
            <p className="px-5 py-8 text-center text-sm text-muted-foreground">{label(T.noneAwaiting)}</p>
          ) : (
            <ul className="max-h-[28rem] divide-y divide-border overflow-y-auto">
              {shifts.map((shift) => (
                <li key={shift.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">
                      {shift.report_date} – {lineName.get(shift.work_center_id) ?? "—"}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {shift.shift}
                      {shift.team ? `, ${shift.team}` : ""}
                    </p>
                  </div>
                  <span className="flex items-center gap-1" aria-hidden>
                    {SECTIONS.map((section) => (
                      <StatusNode key={section.key} status={shift.sections.find((s) => s.key === section.key)?.status ?? "empty"} size={14} />
                    ))}
                  </span>
                  <Button size="sm" variant="outline" onClick={() => setReviewing(shift.id)}>
                    {label(T.review)}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {reviewing && (
        <ShiftReviewDialog
          shiftId={reviewing}
          lineName={(id) => lineName.get(id) ?? "—"}
          reference={reference}
          onClose={() => setReviewing(null)}
        />
      )}
    </>
  );
}

function ShiftReviewDialog({
  shiftId,
  lineName,
  reference,
  onClose,
}: {
  shiftId: string;
  lineName: (id: string) => string;
  reference: ReturnType<typeof useShiftReferenceData>;
  onClose: () => void;
}) {
  const { session } = useAuth();
  const token = session!.token;
  const label = useLabel();
  const queryClient = useQueryClient();

  const detail = useQuery({ queryKey: [...SHIFT_REPORTS_QUERY_KEY, "review", shiftId], queryFn: () => getShiftReport(token, shiftId) });
  const shift = detail.data;
  const options = useMemo(() => reference.buildOptions(shift, shift?.work_center_id ?? ""), [reference.buildOptions, shift]);

  const [ticked, setTicked] = useState<Set<SectionKey>>(new Set());
  const [reason, setReason] = useState("");
  const [shortfall, setShortfall] = useState<string | null>(null);
  const [opened, setOpened] = useState<Set<SectionKey>>(new Set());

  // Sections edited after hand-in are the ones worth a look first.
  useEffect(() => {
    if (shift) setOpened(new Set(shift.sections.filter((s) => s.revised_after_submit).map((s) => s.key)));
  }, [shift?.id]);

  const done = () => {
    queryClient.invalidateQueries({ queryKey: SHIFT_REPORTS_QUERY_KEY });
    onClose();
  };
  const fail = (error: unknown) => {
    if (error instanceof ApiError && error.code === "SHORTFALL_COMMENT_REQUIRED") {
      setShortfall((current) => current ?? "");
      toast.error(label(T.shortfallTitle), { description: label(T.shortfallHint) });
      return;
    }
    if (error instanceof ApiError && error.code === "CHANGED_SINCE_OPENED") {
      toast.error(label(T.failed), { description: label(T.changedSince) });
      queryClient.invalidateQueries({ queryKey: SHIFT_REPORTS_QUERY_KEY });
      return;
    }
    toast.error(label(T.failed), { description: error instanceof ApiError ? error.message : undefined });
  };

  const approve = useMutation({
    mutationFn: () =>
      validateShiftReport(token, shiftId, {
        // What is on the screen right now: if a section moves on, the server refuses.
        seen_revisions: Object.fromEntries(shift!.sections.map((s) => [s.key, s.revision])),
        shortfall_comment: shortfall?.trim() || null,
      }),
    onSuccess: () => {
      toast.success(label(T.approved));
      done();
    },
    onError: fail,
  });
  const sendBack = useMutation({
    mutationFn: () => rejectShiftSections(token, shiftId, { sections: [...ticked], reason: reason.trim() }),
    onSuccess: () => {
      toast.success(label(T.sentBack));
      done();
    },
    onError: fail,
  });
  const busy = approve.isPending || sendBack.isPending;

  const toggleTick = (key: SectionKey) =>
    setTicked((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const toggleOpen = (key: SectionKey) =>
    setOpened((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-6xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{label(T.reviewTitle)}</DialogTitle>
          <DialogDescription>
            {shift ? `${shift.report_date} – ${lineName(shift.work_center_id)}, ${shift.shift}` : label(T.loading)}
          </DialogDescription>
        </DialogHeader>

        {!shift ? (
          <AppLoader size={120} className="py-6" />
        ) : (
          <div className="space-y-3">
            <dl className="grid gap-x-6 gap-y-1 rounded-md bg-muted/50 px-4 py-3 text-sm sm:grid-cols-2 lg:grid-cols-5">
              {(
                [
                  [T.team, shift.team],
                  [T.conducteur, shift.conducteur],
                  [T.agentFabrication, shift.agent_fabrication],
                  [T.machiniste, shift.machiniste],
                  [T.aideMachiniste, shift.aide_machiniste],
                ] as const
              ).map(([name, value]) => (
                <div key={name.en}>
                  <dt className="text-xs text-muted-foreground">{label(name)}</dt>
                  <dd className="font-medium">{value || "—"}</dd>
                </div>
              ))}
            </dl>

            {SECTIONS.map((def) => {
              const state = shift.sections.find((s) => s.key === def.key);
              if (!state) return null;
              return (
                <ReviewSection
                  key={def.key}
                  def={def}
                  state={state}
                  options={options}
                  open={opened.has(def.key)}
                  onToggle={() => toggleOpen(def.key)}
                  ticked={ticked.has(def.key)}
                  onTick={() => toggleTick(def.key)}
                />
              );
            })}

            {shortfall !== null && (
              <div className="space-y-1.5 rounded-md border border-warning/40 bg-warning-soft px-4 py-3">
                <p className="text-sm font-medium">{label(T.shortfallTitle)}</p>
                <p className="text-xs text-muted-foreground">{label(T.shortfallHint)}</p>
                <Input value={shortfall} onChange={(e) => setShortfall(e.target.value)} aria-label={label(T.shortfallTitle)} />
              </div>
            )}

            {ticked.size > 0 && (
              <div className="space-y-1.5 rounded-md border border-destructive/30 bg-destructive-soft px-4 py-3">
                <p className="text-sm font-medium text-destructive">{label(T.sendBackReason)}</p>
                <Input value={reason} onChange={(e) => setReason(e.target.value)} aria-label={label(T.sendBackReason)} />
                <p className="text-xs text-muted-foreground">{label(T.sendBackReasonHint)}</p>
              </div>
            )}

            <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-3">
              {ticked.size > 0 ? (
                <Button variant="destructive" onClick={() => sendBack.mutate()} disabled={busy || !reason.trim()}>
                  <RotateCcw className="h-4 w-4" />
                  {label(T.sendBackSections)} ({ticked.size})
                </Button>
              ) : null}
              <Button onClick={() => approve.mutate()} disabled={busy || ticked.size > 0}>
                <CircleCheck className="h-4 w-4" />
                {approve.isPending ? label(T.approving) : label(T.approve)}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ReviewSection({
  def,
  state,
  options,
  open,
  onToggle,
  ticked,
  onTick,
}: {
  def: SectionDef;
  state: SectionState;
  options: OptionMap;
  open: boolean;
  onToggle: () => void;
  ticked: boolean;
  onTick: () => void;
}) {
  const label = useLabel();
  const draft = useMemo(() => toDraft(def, state.payload), [def, state.payload]);
  const Icon = def.icon;
  const empty = state.status === "nothing_to_report";

  return (
    <section className={cn("overflow-hidden rounded-lg border", ticked ? "border-destructive/50" : "border-border")}>
      <div className="flex items-center gap-3 bg-muted/50 px-3 py-2">
        <label className="flex items-center gap-2 text-xs text-muted-foreground" title={label(T.tickToSendBack)}>
          <input type="checkbox" checked={ticked} onChange={onTick} className="h-4 w-4 accent-[#123B6D]" aria-label={`${label(T.tickToSendBack)}: ${label(def.title)}`} />
        </label>
        <button type="button" onClick={onToggle} aria-expanded={open} className="flex min-w-0 flex-1 items-center gap-3 text-left">
          <Icon className="h-4 w-4 shrink-0 text-primary" />
          <span className="min-w-0 flex-1 truncate text-sm font-medium">{label(def.title)}</span>
          {state.revised_after_submit && (
            <Badge variant="warning">
              {label(T.revisedNote)} ({label(T.revision).toLowerCase()} {state.revision})
            </Badge>
          )}
          <StatusNode status={state.status} size={18} />
        </button>
      </div>
      {open && (
        <div className="space-y-3 px-3 py-3">
          {empty ? (
            <p className="text-sm text-muted-foreground">{label(T.nothingSection)}</p>
          ) : (
            def.parts.map((part) => (
              <Part
                key={part.payloadKey}
                part={part}
                sectionKey={`review-${def.key}`}
                value={draft[part.payloadKey]}
                onChange={() => undefined}
                options={options}
                disabled
              />
            ))
          )}
        </div>
      )}
    </section>
  );
}

