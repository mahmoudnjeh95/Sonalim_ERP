import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "../../../components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Label } from "../../../components/ui/label";
import { useI18n } from "../../../lib/i18n";
import { useAdminUpdatePayslip, type PayslipDetail } from "../api";

const TEXTAREA_CLASS =
  "flex w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function paymentMethodsOf(payslip: PayslipDetail): unknown {
  return (payslip.snapshot as { payment_methods?: unknown }).payment_methods ?? [];
}

/**
 * The payslip's note and payment details (payroll.admin_payslips). Only what changed is sent: the
 * server drops the run's payout batches whenever payment details are sent, and refuses them once a
 * batch is confirmed, so a note-only edit must not carry them.
 */
export function PayslipEditDialog({ open, onOpenChange, payslip }: { open: boolean; onOpenChange: (open: boolean) => void; payslip: PayslipDetail }) {
  const { t } = useI18n();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("payroll.payslipEdit.title")}</DialogTitle>
          <DialogDescription>
            {payslip.full_name} ({payslip.employee_no})
          </DialogDescription>
        </DialogHeader>
        {/* Mounted only while open, so every opening starts from the payslip as it is now. */}
        {open && <EditForm payslip={payslip} onDone={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  );
}

function EditForm({ payslip, onDone }: { payslip: PayslipDetail; onDone: () => void }) {
  const { t } = useI18n();
  const update = useAdminUpdatePayslip(payslip.id);
  const original = paymentMethodsOf(payslip);
  const [note, setNote] = useState(payslip.note ?? "");
  const [methodsJson, setMethodsJson] = useState(() => JSON.stringify(original, null, 2));
  const [jsonError, setJsonError] = useState(false);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    let methods: unknown;
    try {
      methods = JSON.parse(methodsJson);
    } catch {
      methods = undefined;
    }
    const isList = Array.isArray(methods) && methods.every((item) => typeof item === "object" && item !== null && !Array.isArray(item));
    setJsonError(!isList);
    if (!isList) return;

    const changes: { note?: string | null; payment_methods?: Record<string, unknown>[] } = {};
    const nextNote = note.trim();
    if (nextNote !== (payslip.note ?? "")) changes.note = nextNote || null;
    if (JSON.stringify(methods) !== JSON.stringify(original)) changes.payment_methods = methods as Record<string, unknown>[];
    if (Object.keys(changes).length === 0) {
      onDone();
      return;
    }
    update.mutate(changes, {
      onSuccess: () => {
        toast.success(t("payroll.payslipEdit.saved"));
        onDone();
      },
    });
  };

  return (
    <form className="space-y-4" onSubmit={submit}>
      <div className="space-y-1.5">
        <Label htmlFor="payslip-note">{t("payroll.payslipEdit.note")}</Label>
        <textarea id="payslip-note" rows={3} value={note} onChange={(event) => setNote(event.target.value)} className={TEXTAREA_CLASS} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="payslip-methods">{t("payroll.payslipEdit.paymentMethods")}</Label>
        <textarea
          id="payslip-methods"
          rows={9}
          spellCheck={false}
          value={methodsJson}
          aria-invalid={jsonError}
          aria-describedby="payslip-methods-hint"
          onChange={(event) => {
            setMethodsJson(event.target.value);
            setJsonError(false);
          }}
          className={`${TEXTAREA_CLASS} font-mono text-xs`}
        />
        <p id="payslip-methods-hint" className="text-xs text-muted-foreground">
          {t("payroll.payslipEdit.paymentMethodsHint")}
        </p>
        {jsonError && <p className="text-xs font-medium text-destructive">{t("payroll.payslipEdit.invalidJson")}</p>}
      </div>
      {/* Refusals (PAYOUT_SPLIT_INVALID, PAYOUT_CONFIRMED, a paid run...) arrive worded in the user's language. */}
      {update.isError && (
        <p role="alert" className="rounded-md border border-destructive/30 bg-destructive-soft px-3 py-2 text-sm text-destructive">
          {update.error instanceof Error ? update.error.message : null}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onDone}>
          {t("common.cancel")}
        </Button>
        <Button type="submit" disabled={update.isPending}>
          {update.isPending ? t("common.saving") : t("common.save")}
        </Button>
      </div>
    </form>
  );
}
