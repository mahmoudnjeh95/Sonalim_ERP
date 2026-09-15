import { zodResolver } from "@hookform/resolvers/zod";
import { useFieldArray, useForm } from "react-hook-form";
import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../../lib/auth";
import { ApiError } from "../../../lib/api";
import { useI18n } from "../../../lib/i18n";
import { productUnit, productRequiresIntegerQuantity } from "../../../lib/units";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { listProducts, listUoms } from "../../production/api";
import { listOpportunityLocations, transitionOpportunity, type Opportunity } from "./api";

const lineSchema = z.object({
  product_id: z.string().min(1, "Required"),
  quantity: z.coerce.number().positive("Must be > 0"),
});
const wonSchema = z.object({
  location_id: z.string().min(1, "Required"),
  requested_ship_date: z.string().min(1, "Required"),
  lines: z.array(lineSchema).min(1, "Add at least one line"),
});
type WonForm = z.infer<typeof wonSchema>;

const OPPORTUNITIES_QUERY_KEY = ["crm", "opportunities"] as const;
const DASHBOARD_QUERY_KEY = ["crm", "dashboard"] as const;
const LOCATIONS_QUERY_KEY = ["crm", "locations"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const UOMS_QUERY_KEY = ["core", "uoms"] as const;

const EMPTY_DEFAULTS: WonForm = {
  location_id: "",
  requested_ship_date: "",
  lines: [{ product_id: "", quantity: 1 }],
};

/**
 * Captures what was actually sold when a deal is won: product lines, quantities,
 * and a ship date. This creates a draft Sales Order behind the scenes (see
 * transition_stage in opportunity_service.py) — pricing is deliberately not
 * asked for here, it's filled in later on the Sales Orders page before the
 * order is confirmed.
 */
export function MarkWonDialog({
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

  const { data: locations = [] } = useQuery({ queryKey: LOCATIONS_QUERY_KEY, queryFn: () => listOpportunityLocations(token) });
  const { data: allProducts = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: uoms = [] } = useQuery({ queryKey: UOMS_QUERY_KEY, queryFn: () => listUoms(token) });
  const availableLocations = locations.filter((location) => !location.is_blocked);
  const products = allProducts.filter((product) => product.is_sellable);

  const {
    register,
    control,
    handleSubmit,
    reset,
    watch,
    formState: { errors },
  } = useForm<WonForm>({ resolver: zodResolver(wonSchema), defaultValues: EMPTY_DEFAULTS });
  const { fields, append, remove } = useFieldArray({ control, name: "lines" });

  useEffect(() => {
    if (opportunity) reset(EMPTY_DEFAULTS);
  }, [opportunity, reset]);

  const mutation = useMutation({
    mutationFn: (input: WonForm) =>
      transitionOpportunity(token, opportunity!.id, "won", {
        wonLines: input.lines,
        wonLocationId: input.location_id,
        requestedShipDate: input.requested_ship_date,
        correlationId: crypto.randomUUID(),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: OPPORTUNITIES_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: DASHBOARD_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["sales", "orders"] });
      toast.success(t("crm.opportunities.won.created"));
      onOpenChange(false);
    },
    onError: (error) => {
      toast.error(t("crm.opportunities.updateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  return (
    <Dialog open={opportunity !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("crm.opportunities.won.title")}</DialogTitle>
          <DialogDescription>{t("crm.opportunities.won.description")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit((input) => mutation.mutate(input))}>
          <div className="space-y-1.5">
            <Label htmlFor="won-location_id">{t("crm.opportunities.won.field.location")}</Label>
            <Select id="won-location_id" {...register("location_id")}>
              <option value="">—</option>
              {availableLocations.map((location) => (
                <option key={location.id} value={location.id}>
                  {location.name}
                </option>
              ))}
            </Select>
            {errors.location_id && <p className="text-sm text-destructive">{errors.location_id.message}</p>}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="won-requested_ship_date">{t("crm.opportunities.won.field.shipDate")}</Label>
            <Input id="won-requested_ship_date" type="date" {...register("requested_ship_date")} />
            {errors.requested_ship_date && <p className="text-sm text-destructive">{errors.requested_ship_date.message}</p>}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>{t("crm.opportunities.won.field.lines")}</Label>
              <Button type="button" variant="ghost" size="sm" onClick={() => append({ product_id: "", quantity: 1 })}>
                <Plus className="h-3.5 w-3.5" />
                {t("crm.opportunities.won.addLine")}
              </Button>
            </div>
            <AnimatePresence initial={false}>
              {fields.map((field, index) => (
                <motion.div
                  key={field.id}
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.18 }}
                  className="flex items-start gap-2"
                >
                  <Select {...register(`lines.${index}.product_id` as const)}>
                    <option value="">{t("crm.opportunities.won.field.product")}</option>
                    {products.map((product) => (
                      <option key={product.id} value={product.id}>
                        {product.name}
                      </option>
                    ))}
                  </Select>
                  <div className="w-28 space-y-1">
                    <span className="block text-xs font-medium text-foreground">
                      {productUnit(watch(`lines.${index}.product_id`), products, uoms)
                        ? `${t("crm.opportunities.won.field.qty")} (${productUnit(watch(`lines.${index}.product_id`), products, uoms)})`
                        : t("crm.opportunities.won.field.qty")}
                    </span>
                    <Input
                      type="number"
                      step={productRequiresIntegerQuantity(watch(`lines.${index}.product_id`), products, uoms) ? "1" : "any"}
                      {...register(`lines.${index}.quantity` as const)}
                    />
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={fields.length === 1}
                    onClick={() => remove(index)}
                    aria-label={t("crm.opportunities.won.removeLine")}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </motion.div>
              ))}
            </AnimatePresence>
            {errors.lines?.message && <p className="text-sm text-destructive">{errors.lines.message}</p>}
          </div>

          {mutation.isError && (
            <p className="text-sm text-destructive">
              {mutation.error instanceof ApiError ? mutation.error.message : t("crm.opportunities.updateError")}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            {mutation.isPending ? t("crm.opportunities.updating") : t("crm.opportunities.won.confirm")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
