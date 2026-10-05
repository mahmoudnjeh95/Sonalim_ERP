import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "../../../../components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../../components/ui/dialog";
import { Label } from "../../../../components/ui/label";
import { useI18n } from "../../../../lib/i18n";
import { useReverseRun } from "../../api";

/** Reverses an approved or paid run; the server asks for a reason and refuses while a later approved run depends on it. */
export function ReverseDialog({ open, onOpenChange, runId }: { open: boolean; onOpenChange: (open: boolean) => void; runId: string }) {
  const { t } = useI18n();
  const reverse = useReverseRun();
  const [reason, setReason] = useState("");

  // Closing clears the form, so reopening never shows a stale reason or refusal.
  const changeOpen = (next: boolean) => {
    if (!next) {
      setReason("");
      reverse.reset();
    }
    onOpenChange(next);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    reverse.mutate(
      { id: runId, reason: reason.trim() },
      {
        onSuccess: () => {
          toast.success(t("payroll.reverseDialog.done"));
          changeOpen(false);
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("payroll.reverseDialog.title")}</DialogTitle>
          <DialogDescription>{t("payroll.reverseDialog.description")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={submit}>
          <div className="space-y-1.5">
            <Label htmlFor="reverse-reason">{t("payroll.reverseDialog.reason")}</Label>
            <textarea
              id="reverse-reason"
              required
              rows={3}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className="flex w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
          {reverse.isError && (
            <p className="rounded-md border border-destructive/30 bg-destructive-soft px-3 py-2 text-sm text-destructive">
              {reverse.error instanceof Error ? reverse.error.message : null}
            </p>
          )}
          <Button type="submit" variant="destructive" className="w-full" disabled={!reason.trim() || reverse.isPending}>
            {reverse.isPending ? t("common.saving") : t("payroll.reverseDialog.confirm")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
