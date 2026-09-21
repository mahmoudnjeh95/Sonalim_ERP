import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ChevronDown, Lock, RotateCcw, Save, Send } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "../../../lib/api";
import { useAuth } from "../../../lib/auth";
import { cn } from "../../../lib/utils";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Label as FieldLabel } from "../../../components/ui/label";
import { Cell, ShiftGrid, type GridRow, type OptionMap } from "./ShiftGrid";
import { RevisionHistory } from "./RevisionHistory";
import { StatusNode } from "./StatusNode";
import type { PartDef, SectionDef } from "./sectionConfig";
import { hasData, rowCount, toDraft, toPayload, type Draft } from "./shiftModel";
import {
  declareSectionEmpty,
  saveShiftSection,
  submitShiftSection,
  type Row,
  type SectionState,
  type SectionStatus,
  type ShiftReport,
} from "./shiftApi";
import { T, useLabel } from "./shiftText";

const STATUS_VARIANT: Record<SectionStatus, "default" | "warning" | "success" | "outline" | "destructive"> = {
  empty: "default",
  draft: "warning",
  submitted: "success",
  nothing_to_report: "outline",
  returned: "destructive",
};

export function SectionCard({
  def,
  state,
  shift,
  canEdit,
  options,
  open,
  onToggle,
  onChanged,
}: {
  def: SectionDef;
  state: SectionState;
  shift: ShiftReport;
  canEdit: boolean;
  options: OptionMap;
  open: boolean;
  onToggle: () => void;
  onChanged: () => void;
}) {
  const { session } = useAuth();
  const token = session!.token;
  const label = useLabel();
  const reduceMotion = useReducedMotion();

  const locked = !canEdit || shift.status === "validated";

  // An editable section opens with one blank line in each table; a locked one shows what was handed in.
  const [draft, setDraft] = useState<Draft>(() => toDraft(def, state.payload, !locked));
  const [dirty, setDirty] = useState(false);

  // What the server holds is the truth: when it changes (a save, a validator's return),
  // the grids follow it and the section is clean again.
  const serverKey = `${state.revision}|${state.status}|${locked}|${JSON.stringify(state.payload ?? {})}`;
  useEffect(() => {
    setDraft(toDraft(def, state.payload, !locked));
    setDirty(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverKey]);

  const filled = hasData(def, draft);
  const count = rowCount(def, draft);
  const submitted = state.status === "submitted";

  const edit = (partKey: string, value: GridRow[] | Row) => {
    setDraft((current) => ({ ...current, [partKey]: value }));
    setDirty(true);
  };

  const fail = (error: unknown) =>
    toast.error(label(T.failed), { description: error instanceof ApiError ? error.message : undefined });

  const save = useMutation({
    mutationFn: () => saveShiftSection(token, shift.id, def.key, toPayload(def, draft)),
    onSuccess: () => {
      toast.success(label(T.saved));
      onChanged();
    },
    onError: fail,
  });
  const submit = useMutation({
    mutationFn: async () => {
      if (dirty) await saveShiftSection(token, shift.id, def.key, toPayload(def, draft));
      return submitShiftSection(token, shift.id, def.key);
    },
    onSuccess: () => {
      toast.success(label(T.handedIn));
      onChanged();
    },
    onError: (error) => {
      fail(error);
      // The save may have gone through before the hand-in was refused.
      onChanged();
    },
  });
  const nothing = useMutation({
    mutationFn: () => declareSectionEmpty(token, shift.id, def.key),
    onSuccess: () => {
      toast.success(label(T.markedEmpty));
      onChanged();
    },
    onError: fail,
  });
  const busy = save.isPending || submit.isPending || nothing.isPending;

  const declareNothing = () => {
    if (filled && !window.confirm(label(T.confirmNothing))) return;
    nothing.mutate();
  };

  const Icon = def.icon;

  return (
    <section
      id={`shift-section-${def.key}`}
      aria-labelledby={`shift-section-${def.key}-title`}
      className={cn(
        "scroll-mt-24 overflow-hidden rounded-xl border bg-background shadow-soft transition-colors",
        state.status === "returned" ? "border-destructive/40" : "border-border",
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-3 bg-muted/50 px-4 py-3 text-left transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="h-[18px] w-[18px]" />
        </span>
        <span className="min-w-0 flex-1">
          <span id={`shift-section-${def.key}-title`} className="block truncate text-sm font-semibold tracking-tight">
            {label(def.title)}
          </span>
          {!open && <span className="block truncate text-xs text-muted-foreground">{label(def.hint)}</span>}
        </span>
        <span className="flex shrink-0 items-center gap-2">
          {count > 0 && <span className="text-xs tabular-nums text-muted-foreground">{count}</span>}
          {dirty && !locked && <Badge variant="warning">{label(T.unsaved)}</Badge>}
          {state.revised_after_submit && (
            <Badge variant="warning">
              {label(T.revised)} ({label(T.revision).toLowerCase()} {state.revision})
            </Badge>
          )}
          <Badge variant={STATUS_VARIANT[state.status]} className="gap-1.5 pl-1.5">
            <StatusNode status={state.status} size={16} />
            {label(T.status[state.status])}
          </Badge>
          {locked && <Lock className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />}
          <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", open && "rotate-180")} />
        </span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="body"
            initial={reduceMotion ? false : { height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={reduceMotion ? undefined : { height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <div className="space-y-4 border-t border-border px-4 py-4">
              <div className="flex items-start justify-between gap-3">
                <p className="text-xs text-muted-foreground">{label(def.hint)}</p>
                <RevisionHistory def={def} shiftId={shift.id} revision={state.revision} options={options} />
              </div>

              {state.status === "returned" && state.return_reason && (
                <div className="flex items-start gap-2 rounded-md bg-destructive-soft px-3 py-2 text-sm text-destructive" role="alert">
                  <RotateCcw className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>
                    <span className="font-medium">{label(T.sentBackBy)}: </span>
                    {state.return_reason}
                  </span>
                </div>
              )}

              {def.parts.map((part) => (
                <Part
                  key={part.payloadKey}
                  part={part}
                  sectionKey={def.key}
                  value={draft[part.payloadKey]}
                  onChange={(value) => edit(part.payloadKey, value)}
                  options={options}
                  disabled={locked || busy}
                />
              ))}

              {!locked && (
                <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
                  {submitted ? (
                    <Button size="sm" onClick={() => save.mutate()} disabled={!dirty || busy}>
                      <Save className="h-3.5 w-3.5" />
                      {label(T.saveChanges)}
                    </Button>
                  ) : (
                    <>
                      <Button size="sm" variant="outline" onClick={() => save.mutate()} disabled={!dirty || busy}>
                        <Save className="h-3.5 w-3.5" />
                        {label(T.saveDraft)}
                      </Button>
                      <Button size="sm" onClick={() => submit.mutate()} disabled={!filled || busy}>
                        <Send className="h-3.5 w-3.5" />
                        {label(T.submit)}
                      </Button>
                    </>
                  )}
                  <Button size="sm" variant="ghost" onClick={declareNothing} disabled={busy || state.status === "nothing_to_report"}>
                    {label(T.nothing)}
                  </Button>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}

export function Part({
  part,
  sectionKey,
  value,
  onChange,
  options,
  disabled,
}: {
  part: PartDef;
  sectionKey: string;
  value: GridRow[] | Row;
  onChange: (value: GridRow[] | Row) => void;
  options: OptionMap;
  disabled: boolean;
}) {
  const label = useLabel();
  const idPrefix = `${sectionKey}-${part.payloadKey}`;

  return (
    <div className="space-y-2">
      {part.title && <h3 className="text-sm font-medium">{label(part.title)}</h3>}
      {part.shape === "single" ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {part.columns.map((column) => (
            <div key={column.key} className="space-y-1">
              <FieldLabel htmlFor={`${idPrefix}-${column.key}`} className="text-xs text-muted-foreground">
                {label(column.label)}
              </FieldLabel>
              <Cell
                column={column}
                value={(value as Row)[column.key]}
                onChange={(next) => onChange({ ...(value as Row), [column.key]: next })}
                options={options}
                disabled={disabled}
                idPrefix={idPrefix}
              />
            </div>
          ))}
        </div>
      ) : (
        <ShiftGrid
          columns={part.columns}
          rows={value as GridRow[]}
          onChange={onChange}
          options={options}
          disabled={disabled}
          addLabel={part.addLabel ? label(part.addLabel) : label(T.addRow)}
          child={part.child}
          idPrefix={idPrefix}
          storageKey={idPrefix}
          keepOne
        />
      )}
    </div>
  );
}
