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
import { createWorkOrder, isProductionLine, listProducts, listSupervisorOptions, listWorkCenters, supervisorLabel } from "./api";
import type { ProductionSuggestion } from "./planning";
import SuggestionToOfIcon from "../../assets/icons/production/suggestion-to-of.svg?react";

// Same fields as the regular "New work order" dialog: type, start date, work center, supervisor.
type FormValues = { work_center_id: string; product_type: "PC" | "PL"; start_date: string; supervisor_id?: string };

const WORK_ORDERS_QUERY_KEY = ["production", "work-orders"] as const;
const WORK_CENTERS_QUERY_KEY = ["production", "work-centers"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const UOMS_QUERY_KEY = ["core", "uoms"] as const;
const SUPERVISORS_QUERY_KEY = ["production", "work-order-supervisors"] as const;

const pad = (n: number) => String(n).padStart(2, "0");
const todayDateInputValue = () => {
  const now = new Date();
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
};

/**
 * Opens an OF from a planning shortfall. It asks the same questions as the
 * regular OF creation; the shortfall only contributes the product (shown for
 * context) and a pre-selected type. The shortfall quantity is still stored on
 * the OF, never asked or shown, so the planning tab stops re-suggesting it.
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

  const formSchema = z.object({
    work_center_id: z.string().min(1, t("common.required")),
    product_type: z.enum(["PC", "PL"]),
    start_date: z.string().min(1, t("common.required")),
    supervisor_id: z.string().optional(),
  });

  const { data: workCenters = [] } = useQuery({ queryKey: WORK_CENTERS_QUERY_KEY, queryFn: () => listWorkCenters(token) });
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: uoms = [] } = useQuery({ queryKey: UOMS_QUERY_KEY, queryFn: () => listUoms(token) });
  const { data: supervisorOptions = [] } = useQuery({ queryKey: SUPERVISORS_QUERY_KEY, queryFn: () => listSupervisorOptions(token) });
  const product = suggestion ? products.find((p) => p.id === suggestion.product_id) : undefined;
  const unit = product ? uoms.find((u) => u.id === product.uom_id) : undefined;
  const unitLabel = unit ? unit.symbol || unit.code : undefined;
  const productType: "PC" | "PL" = product?.product_type === "PL" ? "PL" : "PC";

  const { register, handleSubmit, reset, formState: { errors } } = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: { work_center_id: "", product_type: "PC", start_date: todayDateInputValue(), supervisor_id: "" },
  });

  useEffect(() => {
    if (suggestion) {
      reset({ work_center_id: "", product_type: productType, start_date: todayDateInputValue(), supervisor_id: "" });
    }
  }, [suggestion, productType, reset]);

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
        product_type: input.product_type,
        start_date: input.start_date,
        supervisor_id: input.supervisor_id || undefined,
        product_id: suggestion!.product_id,
        planned_quantity: Math.ceil(suggestion!.shortfallQty * 100) / 100,
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
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("production.planning.dialog.title")}</DialogTitle>
          <DialogDescription>{t("production.planning.dialog.description")}</DialogDescription>
        </DialogHeader>
        {suggestion && (
          <form className="space-y-4" onSubmit={handleSubmit((input) => mutation.mutate(input))}>
            <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/30 p-3">
              <SuggestionToOfIcon className="h-8 w-8 shrink-0 text-primary" />
              <div className="space-y-0.5">
                <Label className="text-xs">{t("production.planning.dialog.field.product")}</Label>
                <p className="text-sm font-medium">{product?.name ?? "—"}</p>
                <p className="text-xs text-muted-foreground">
                  {t("production.planning.column.shortfall")}: {formatQuantity(suggestion.shortfallQty, unitLabel)}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="of-product_type">{t("production.workOrders.field.productType")}</Label>
                <Select id="of-product_type" {...register("product_type")}>
                  <option value="PC">PC</option>
                  <option value="PL">PL</option>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="of-start_date">{t("production.workOrders.field.startDate")}</Label>
                <Input id="of-start_date" type="date" {...register("start_date")} />
                {errors.start_date && <p className="text-sm text-destructive">{errors.start_date.message}</p>}
              </div>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="of-work_center_id">{t("production.workOrders.field.workCenter")}</Label>
              <Select id="of-work_center_id" {...register("work_center_id")}>
                <option value="">—</option>
                {workCenters.filter(isProductionLine).map((wc) => (
                  <option key={wc.id} value={wc.id}>
                    {wc.code} — {wc.name}
                  </option>
                ))}
              </Select>
              {errors.work_center_id && <p className="text-sm text-destructive">{errors.work_center_id.message}</p>}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="of-supervisor_id">{t("production.workOrders.field.supervisor")}</Label>
              <Select id="of-supervisor_id" {...register("supervisor_id")}>
                <option value="">—</option>
                {supervisorOptions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {supervisorLabel(s)}
                  </option>
                ))}
              </Select>
            </div>

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
