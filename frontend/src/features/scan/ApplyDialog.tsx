import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { Button } from "../../components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { SECTIONS } from "../production/shift/sectionConfig";
import { SHIFT_REPORTS_QUERY_KEY, type SectionKey } from "../production/shift/shiftApi";
import { useLabel } from "../production/shift/shiftText";
import { APPLY_ORDER, applyBody, type Missing } from "./reviewModel";
import { applySession, SCAN_QUERY_KEY, type ReviewValues, type SessionDetail, type ShiftState } from "./scanApi";
import { S } from "./scanText";

export function ApplyDialog({
  open, onOpenChange, session, values, shift, writing, missing, doubts,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  session: SessionDetail;
  values: ReviewValues;
  shift: ShiftState | null;
  writing: SectionKey[];
  missing: Missing[];
  doubts: number;
}) {
  const { session: auth } = useAuth();
  const label = useLabel();
  const queryClient = useQueryClient();
  const blocking = missing.filter((m) => m.blocking);
  const later = missing.length - blocking.length;
  const title = (key: SectionKey) => label(SECTIONS.find((d) => d.key === key)!.title);

  const apply = useMutation({
    mutationFn: () => applySession(auth!.token, session.id, applyBody(values, writing, shift)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: SCAN_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: SHIFT_REPORTS_QUERY_KEY });
      toast.success(label(S.applied));
      onOpenChange(false);
    },
    onError: (error) => toast.error(label(S.failed), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const outcome = (key: SectionKey) => {
    const existing = shift?.sections[key];
    if (!writing.includes(key)) return label(S.keptExisting);
    if (!existing || existing.rows === 0) return label(S.writeNew);
    return label(existing.status === "submitted" ? S.replaceSubmitted : S.replaceDraft);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{label(S.applyTitle)}</DialogTitle>
          <DialogDescription>{label(S.applyHint)}</DialogDescription>
        </DialogHeader>
        <ul className="space-y-1 text-sm">
          {APPLY_ORDER.filter((key) => values.sections[key]).map((key) => (
            <li key={key} className="flex justify-between gap-3">
              <span className="font-medium">{title(key)}</span>
              <span className="text-muted-foreground">{outcome(key)}</span>
            </li>
          ))}
        </ul>
        {blocking.length > 0 && (
          <div className="rounded-md bg-destructive-soft px-3 py-2 text-sm text-destructive">
            <p className="font-medium">{label(S.blockingTitle)}</p>
            <ul className="list-disc pl-5">
              {blocking.map((m) => (
                <li key={`${m.section}-${m.ref}-${m.column.key}`}>{`${title(m.section)} — ${label(m.column.label)}`}</li>
              ))}
            </ul>
          </div>
        )}
        {later > 0 && <p className="text-sm text-muted-foreground">{`${later} — ${label(S.requiredLater)}`}</p>}
        {doubts > 0 && <p className="text-sm text-warning">{`${doubts} ${label(S.doubtsLeft)}`}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>{label(S.cancel)}</Button>
          <Button onClick={() => apply.mutate()} disabled={blocking.length > 0 || writing.length === 0 || apply.isPending}>
            {apply.isPending ? label(S.saving) : label(S.confirmSave)}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
