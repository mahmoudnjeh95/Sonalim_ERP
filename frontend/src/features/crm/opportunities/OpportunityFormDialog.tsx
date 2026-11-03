import { useEffect } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../../lib/auth";
import { ApiError } from "../../../lib/api";
import { useI18n } from "../../../lib/i18n";
import { listUserDirectory, userDisplayName } from "../../../lib/usersApi";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { listPartners } from "../../partners/api";
import { createOpportunity, DEFAULT_PROBABILITY_BY_STAGE, updateOpportunity, type Opportunity, type Priority } from "./api";

const opportunitySchema = z.object({
  partner_id: z.string().min(1, "Required"),
  name: z.string().min(1, "Required"),
  amount: z.coerce.number().min(0, "Must be >= 0"),
  expected_close_date: z.string().optional(),
  probability: z.coerce.number().min(0).max(100),
  owner_id: z.string().optional(),
  priority: z.enum(["low", "medium", "high"]),
});
type OpportunityForm = z.infer<typeof opportunitySchema>;

const OPPORTUNITIES_QUERY_KEY = ["crm", "opportunities"] as const;
const DASHBOARD_QUERY_KEY = ["crm", "dashboard"] as const;
const PARTNERS_QUERY_KEY = ["core", "partners"] as const;
const USER_DIRECTORY_QUERY_KEY = ["core", "users", "directory"] as const;

const EMPTY_DEFAULTS: OpportunityForm = {
  partner_id: "",
  name: "",
  amount: 0,
  expected_close_date: "",
  probability: DEFAULT_PROBABILITY_BY_STAGE.prospecting,
  owner_id: "",
  priority: "medium",
};

/**
 * Create/edit form shared by the opportunities table and the pipeline board,
 * so both stay in sync and a fix to one applies everywhere. `opportunity`
 * null means create mode; passing one pre-fills and switches to update.
 */
export function OpportunityFormDialog({
  open,
  onOpenChange,
  opportunity,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  opportunity: Opportunity | null;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();

  const { data: partners = [] } = useQuery({ queryKey: PARTNERS_QUERY_KEY, queryFn: () => listPartners(token) });
  const { data: users = [] } = useQuery({ queryKey: USER_DIRECTORY_QUERY_KEY, queryFn: () => listUserDirectory(token) });
  const activePartners = partners.filter((p) => p.status === "active" && p.kind !== "supplier");

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<OpportunityForm>({ resolver: zodResolver(opportunitySchema), defaultValues: EMPTY_DEFAULTS });

  useEffect(() => {
    if (!open) return;
    if (opportunity) {
      reset({
        partner_id: opportunity.partner_id,
        name: opportunity.name,
        amount: opportunity.amount,
        expected_close_date: opportunity.expected_close_date ?? "",
        probability: opportunity.probability,
        owner_id: opportunity.owner_id ?? "",
        priority: opportunity.priority,
      });
    } else {
      reset(EMPTY_DEFAULTS);
    }
  }, [open, opportunity, reset]);

  const invalidateAndClose = () => {
    queryClient.invalidateQueries({ queryKey: OPPORTUNITIES_QUERY_KEY });
    queryClient.invalidateQueries({ queryKey: DASHBOARD_QUERY_KEY });
    onOpenChange(false);
  };

  const createMutation = useMutation({
    mutationFn: (input: OpportunityForm) =>
      createOpportunity(token, { ...input, expected_close_date: input.expected_close_date || undefined }),
    onSuccess: () => {
      invalidateAndClose();
      toast.success(t("crm.opportunities.created"));
    },
    onError: (error) => {
      toast.error(t("crm.opportunities.createError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (input: OpportunityForm) =>
      updateOpportunity(token, opportunity!.id, { ...input, expected_close_date: input.expected_close_date || undefined }),
    onSuccess: () => {
      invalidateAndClose();
      toast.success(t("crm.opportunities.updated"));
    },
    onError: (error) => {
      toast.error(t("crm.opportunities.updateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const mutation = opportunity ? updateMutation : createMutation;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{opportunity ? t("crm.opportunities.dialog.editTitle") : t("crm.opportunities.dialog.title")}</DialogTitle>
          <DialogDescription>
            {opportunity ? t("crm.opportunities.dialog.editDescription") : t("crm.opportunities.dialog.description")}
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit((input) => mutation.mutate(input))}>
          <div className="space-y-1.5">
            <Label htmlFor="opportunity-partner_id">{t("crm.opportunities.field.account")}</Label>
            <Select id="opportunity-partner_id" {...register("partner_id")}>
              <option value="">—</option>
              {activePartners.map((partner) => (
                <option key={partner.id} value={partner.id}>
                  {partner.name}
                </option>
              ))}
            </Select>
            {errors.partner_id && <p className="text-sm text-destructive">{errors.partner_id.message}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="opportunity-name">{t("crm.opportunities.field.name")}</Label>
            <Input id="opportunity-name" {...register("name")} />
            {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="opportunity-amount">{t("crm.opportunities.field.amount")}</Label>
              <Input id="opportunity-amount" type="number" step="any" {...register("amount")} />
              {errors.amount && <p className="text-sm text-destructive">{errors.amount.message}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="opportunity-expected_close_date">{t("crm.opportunities.field.closeDate")}</Label>
              <Input id="opportunity-expected_close_date" type="date" {...register("expected_close_date")} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="opportunity-probability">{t("crm.opportunities.field.probability")}</Label>
              <Input id="opportunity-probability" type="number" min={0} max={100} {...register("probability")} />
              {errors.probability && <p className="text-sm text-destructive">{errors.probability.message}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="opportunity-priority">{t("crm.opportunities.field.priority")}</Label>
              <Select id="opportunity-priority" {...register("priority")}>
                {(["low", "medium", "high"] as Priority[]).map((priority) => (
                  <option key={priority} value={priority}>
                    {t(`priority.${priority}` as Parameters<typeof t>[0])}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="opportunity-owner_id">{t("crm.opportunities.field.owner")}</Label>
            <Select id="opportunity-owner_id" {...register("owner_id")}>
              <option value="">{t("crm.opportunities.unassigned")}</option>
              {users.map((user) => (
                <option key={user.id} value={user.id}>
                  {userDisplayName(user)}
                </option>
              ))}
            </Select>
          </div>
          {mutation.isError && (
            <p className="text-sm text-destructive">
              {mutation.error instanceof ApiError
                ? mutation.error.message
                : t(opportunity ? "crm.opportunities.updateError" : "crm.opportunities.createError")}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            {opportunity
              ? mutation.isPending
                ? t("crm.opportunities.updating")
                : t("crm.opportunities.update")
              : mutation.isPending
                ? t("crm.opportunities.creating")
                : t("crm.opportunities.create")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
