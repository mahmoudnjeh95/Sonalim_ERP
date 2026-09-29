import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { hrKeys, terminateEmployee, TERMINATION_REASONS, type EmployeeRecord, type TerminationReason } from "../api";
import { END_REASON_LABEL } from "../employeeLabels";
import { todayIso } from "../employeeFormat";
import { FormField } from "../FormField";

export function TerminateDialog({ open, onOpenChange, employee }: { open: boolean; onOpenChange: (open: boolean) => void; employee: EmployeeRecord }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [day, setDay] = useState(todayIso());
  const [reason, setReason] = useState<TerminationReason>("resignation");
  const mutation = useMutation({
    mutationFn: () => terminateEmployee(session!.token, employee.id, { termination_date: day, termination_reason: reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: hrKeys.employees });
      queryClient.invalidateQueries({ queryKey: hrKeys.contracts });
      queryClient.invalidateQueries({ queryKey: hrKeys.alerts });
      toast.success(t("hr.terminate.done"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(t("hr.terminate.error"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("hr.terminate.title")}</DialogTitle>
          <DialogDescription>{t("hr.terminate.description")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            mutation.mutate();
          }}
        >
          <FormField id="termination-date" label={t("hr.field.terminationDate")}>
            <Input id="termination-date" type="date" required value={day} onChange={(event) => setDay(event.target.value)} />
          </FormField>
          <FormField id="termination-reason" label={t("hr.field.terminationReason")}>
            <Select id="termination-reason" value={reason} onChange={(event) => setReason(event.target.value as TerminationReason)}>
              {TERMINATION_REASONS.map((value) => (
                <option key={value} value={value}>
                  {t(END_REASON_LABEL[value])}
                </option>
              ))}
            </Select>
          </FormField>
          <Button type="submit" variant="destructive" className="w-full" disabled={mutation.isPending || !day}>
            {mutation.isPending ? t("common.saving") : t("hr.terminate.confirm")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
