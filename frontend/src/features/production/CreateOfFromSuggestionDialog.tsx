import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { z } from "zod";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { formatQuantity } from "../../lib/units";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { listUoms } from "../warehouse/api";
import { createWorkOrder, listProducts, listWorkCenters } from "./api";
import type { ProductionSuggestion } from "./planning";
import SuggestionToOfIcon from "../../assets/icons/production/suggestion-to-of.svg?react";

const formSchema = z.object({
  work_center_id: z.string().min(1, t("common.required")),
  planned_quantity: z.coerce.number().positive(t("common.mustBeGreaterThanZero")),
  start_date: z.string().optional(),
});
type FormValues = z.infer<typeof formSchema>;

const WORK_ORDERS_QUERY_KEY = ["production", "work-orders"] as const;
const WORK_CENTERS_QUERY_KEY = ["production", "work-centers"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const UOMS_QUERY_KEY = ["core", "uoms"] as const;

/**
 * Pre-fills an OF from a planning shortfall (product + quantity already known,
 * unlike the general work-order creation flow which starts empty and lets
 * Conditionnement name the product later). Only the work center is genuinely
 * required input here.
 */
export function CreateOfFromSuggestionDialog({
  suggestion,
  onOpenChange,
}: {
  suggestion: ProductionSuggestion | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();

  const { data: workCenters = [] } = useQuery({ queryKey: WORK_CENTERS_QUERY_KEY, queryFn: () => listWorkCenters(token) });
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: uoms = [] } = useQuery({ queryKey: UOMS_QUERY_KEY, queryFn: () => listUoms(token) });
  const availableWorkCenters = workCenters.filter((wc) => !wc.is_blocked);
  const product = suggestion ? products.find((p) => p.id === suggestion.product_id) : undefined;
  const unit = product ? uoms.find((u) => u.id === product.uom_id) : undefined;
  const unitLabel = unit ? unit.symbol || unit.code : undefined;

  const { register, handleSubmit, reset, formState: { errors } } = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: { work_center_id: "", planned_quantity: 0, start_date: "" },
  });

  useEffect(() => {
    if (suggestion) {
      reset({
        work_center_id: "",
        planned_quantity: Math.ceil(suggestion.shortfallQty * 100) / 100,
        start_date: suggestion.earliestShipDate ?? "",
      });
    }
  }, [suggestion, reset]);

  const mutation = useMutation({
    mutationFn: (input: FormValues) => {
      const notesParts = [
        t("production.planning.notes.autoSuggested"),
        `${suggestion!.contributingOrders.length} ${t("production.planning.notes.openOrders")}`,
      ];
      if (suggestion!.earliestShipDate) {
        notesParts.push(`— ${t("production.planning.notes.shipBy")} ${suggestion!.earliestShipDate}`);
      }
      return createWorkOrder(token, {
        work_center_id: input.work_center_id,
        product_id: suggestion!.product_id,
        planned_quantity: input.planned_quantity,
        start_date: input.start_date || undefined,
        product_type: product?.product_type,
        notes: notesParts.join(" "),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: WORK_ORDERS_QUERY_KEY });
      toast.success(t("production.planning.created"));
      onOpenChange(false);
    },
    onError: (error) => {
      toast.error(t("production.planning.createError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  return (
    <Dialog open={suggestion !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("production.planning.dialog.title")}</DialogTitle>
          <DialogDescription>{t("production.planning.dialog.description")}</DialogDescription>
        </DialogHeader>
        {suggestion && (
          <form className="space-y-4" onSubmit={handleSubmit((input) => mutation.mutate(input))}>
            <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/30 p-3">
              <SuggestionToOfIcon className="h-8 w-8 shrink-0 text-primary" />
              <div className="space-y-1.5">
                <Label className="text-xs">{t("production.planning.dialog.field.product")}</Label>
                <p className="text-sm font-medium">{product?.name ?? "—"}</p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="of-planned_quantity">
                  {t("production.planning.dialog.field.quantity")} {unitLabel ? `(${unitLabel})` : ""}
                </Label>
                <Input id="of-planned_quantity" type="number" step="any" {...register("planned_quantity")} />
                {errors.planned_quantity && <p className="text-sm text-destructive">{errors.planned_quantity.message}</p>}
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="of-start_date">{t("production.planning.dialog.field.startDate")}</Label>
                <Input id="of-start_date" type="date" {...register("start_date")} />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="of-work_center_id">{t("production.planning.dialog.field.workCenter")}</Label>
              <Select id="of-work_center_id" {...register("work_center_id")}>
                <option value="">—</option>
                {availableWorkCenters.map((workCenter) => (
                  <option key={workCenter.id} value={workCenter.id}>
                    {workCenter.name}
                  </option>
                ))}
              </Select>
              {errors.work_center_id && <p className="text-sm text-destructive">{errors.work_center_id.message}</p>}
            </div>

            <p className="text-xs text-muted-foreground">
              {t("production.planning.column.shortfall")}: {formatQuantity(suggestion.shortfallQty, unitLabel)}
            </p>

            {mutation.isError && (
              <p className="text-sm text-destructive">
                {mutation.error instanceof ApiError ? mutation.error.message : t("production.planning.createError")}
              </p>
            )}
            <Button type="submit" className="w-full" disabled={mutation.isPending}>
              {mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {mutation.isPending ? t("production.planning.creating") : t("production.planning.dialog.confirm")}
            </Button>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
