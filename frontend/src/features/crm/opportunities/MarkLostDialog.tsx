import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { ApiError } from "../../../lib/api";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { transitionOpportunity, type Opportunity } from "./api";

const LOST_REASON_CATEGORIES = ["price", "competitor", "timing", "budget", "no_response", "other"] as const;
const OPPORTUNITIES_QUERY_KEY = ["crm", "opportunities"] as const;
const DASHBOARD_QUERY_KEY = ["crm", "dashboard"] as const;

/**
 * Shared "mark as lost" confirmation used by both the opportunities table and
 * the pipeline board, so a loss is always categorized the same way — the
 * dashboard's loss analysis depends on these categories being consistent no
 * matter where the deal was rejected from.
 */
export function MarkLostDialog({
  opportunity,
  onOpenChange,
}: {
  opportunity: Opportunity | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [category, setCategory] = useState("");
  const [otherReason, setOtherReason] = useState("");

  useEffect(() => {
    if (opportunity) {
      setCategory("");
      setOtherReason("");
    }
  }, [opportunity]);

  const mutation = useMutation({
    mutationFn: (reason: string) =>
      transitionOpportunity(token, opportunity!.id, "lost", { lostReason: reason, correlationId: crypto.randomUUID() }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: OPPORTUNITIES_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: DASHBOARD_QUERY_KEY });
      toast.success(t("crm.opportunities.updated"));
      onOpenChange(false);
    },
    onError: (error) => {
      toast.error(t("crm.opportunities.updateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  return (
    <Dialog open={opportunity !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("crm.opportunities.dialog.lostReasonTitle")}</DialogTitle>
          <DialogDescription>{t("crm.opportunities.dialog.lostReasonDescription")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            const reason = category === "other" ? otherReason : category;
            mutation.mutate(reason);
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="lost-reason-category">{t("crm.opportunities.field.lostReason")}</Label>
            <Select id="lost-reason-category" required value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">—</option>
              {LOST_REASON_CATEGORIES.map((reason) => (
                <option key={reason} value={reason}>
                  {t(`crm.opportunities.lostReason.${reason}` as Parameters<typeof t>[0])}
                </option>
              ))}
            </Select>
          </div>
          {category === "other" && (
            <Input
              required
              value={otherReason}
              onChange={(e) => setOtherReason(e.target.value)}
              placeholder={t("crm.opportunities.lostReason.other")}
            />
          )}
          <Button
            type="submit"
            className="w-full"
            disabled={mutation.isPending || !category || (category === "other" && !otherReason.trim())}
          >
            {mutation.isPending ? t("crm.opportunities.updating") : t("crm.opportunities.confirmMarkLost")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
