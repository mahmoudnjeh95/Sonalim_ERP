import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { endContract, hrKeys, TERMINATION_REASONS, type Contract, type TerminationReason } from "../api";
import { END_REASON_LABEL } from "../employeeLabels";
import { todayIso } from "../employeeFormat";
import { FormField } from "../FormField";

export function EndContractDialog({ open, onOpenChange, contract }: { open: boolean; onOpenChange: (open: boolean) => void; contract: Contract | null }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [day, setDay] = useState(todayIso());
  const [reason, setReason] = useState<TerminationReason>("term_reached");

  useEffect(() => {
    if (open && contract) {
      setDay(contract.end_date ?? todayIso());
      setReason(contract.end_date ? "term_reached" : "resignation");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, contract?.id]);

  const mutation = useMutation({
    mutationFn: () => endContract(session!.token, contract!.id, { end_date: day, end_reason: reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.contracts });
      queryClient.invalidateQueries({ queryKey: hrKeys.employees });
      queryClient.invalidateQueries({ queryKey: hrKeys.alerts });
      toast.success(t("hr.contracts.ended"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(t("hr.contracts.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("hr.contracts.end.title")}</DialogTitle>
          <DialogDescription>{t("hr.contracts.end.description")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <FormField id="end-date" label={t("hr.contracts.end.date")}>
            <Input id="end-date" type="date" required value={day} onChange={(event) => setDay(event.target.value)} />
          </FormField>
          <FormField id="end-reason" label={t("hr.contracts.end.reason")}>
            <Select id="end-reason" value={reason} onChange={(event) => setReason(event.target.value as TerminationReason)}>
              {TERMINATION_REASONS.map((value) => (
                <option key={value} value={value}>
                  {t(END_REASON_LABEL[value])}
                </option>
              ))}
            </Select>
          </FormField>
          <Button type="submit" variant="destructive" className="w-full" disabled={mutation.isPending || !day}>
            {mutation.isPending ? t("common.saving") : t("hr.contracts.end.confirm")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
