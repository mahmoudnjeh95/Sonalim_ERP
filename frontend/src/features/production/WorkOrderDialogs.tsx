import { useEffect } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { useI18n } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import {
  supervisorLabel,
  type PackagingBom,
  type Product,
  type Recipe,
  type SupervisorOption,
  type UpdateWorkOrderInput,
  type WorkCenter,
  type WorkOrder,
} from "./api";

type EditOrderForm = {
  work_center_id?: string;
  supervisor_id?: string;
  recipe_id?: string;
  packaging_bom_id?: string;
  product_type?: string;
};

function nowDatetimeLocalValue(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

/** Edits the fields an OF can still change. The product is not among them: it comes from the validated shifts. */
export function EditWorkOrderDialog({
  order,
  onClose,
  onSubmit,
  isPending,
  workCenters,
  supervisorOptions,
  recipes,
  packagingBoms,
  products,
}: {
  order: WorkOrder | null;
  onClose: () => void;
  onSubmit: (id: string, input: UpdateWorkOrderInput) => void;
  isPending: boolean;
  workCenters: WorkCenter[];
  supervisorOptions: SupervisorOption[];
  recipes: Recipe[];
  packagingBoms: PackagingBom[];
  products: Product[];
}) {
  const { t } = useI18n();
  const form = useForm<EditOrderForm>({
    resolver: zodResolver(
      z.object({
        work_center_id: z.string().optional(),
        supervisor_id: z.string().optional(),
        recipe_id: z.string().optional(),
        packaging_bom_id: z.string().optional(),
        product_type: z.string().optional(),
      }),
    ),
  });

  useEffect(() => {
    if (!order) return;
    form.reset({
      work_center_id: order.work_center_id ?? "",
      supervisor_id: order.supervisor_id ?? "",
      recipe_id: order.recipe_id ?? "",
      packaging_bom_id: order.packaging_bom_id ?? "",
      product_type: order.product_type ?? "",
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [order?.id]);

  const productName = (id: string | null) => (id && products.find((p) => p.id === id)?.name) || "—";

  return (
    <Dialog open={order !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("production.workOrders.dialog.editTitle")}</DialogTitle>
          <DialogDescription>{t("production.workOrders.dialog.editDescription")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={form.handleSubmit((input) =>
            order &&
            onSubmit(order.id, {
              work_center_id: input.work_center_id || undefined,
              supervisor_id: input.supervisor_id || undefined,
              recipe_id: input.recipe_id || undefined,
              packaging_bom_id: input.packaging_bom_id || undefined,
              product_type: input.product_type || undefined,
            }),
          )}
        >
          <div className="space-y-1.5">
            <Label htmlFor="edit_work_center">{t("production.workOrders.field.workCenter")}</Label>
            <Select id="edit_work_center" {...form.register("work_center_id")}>
              <option value="">—</option>
              {workCenters.map((wc) => (
                <option key={wc.id} value={wc.id}>
                  {wc.code} — {wc.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="edit_supervisor">{t("production.workOrders.field.supervisor")}</Label>
            <Select id="edit_supervisor" {...form.register("supervisor_id")}>
              <option value="">—</option>
              {supervisorOptions.map((s) => (
                <option key={s.id} value={s.id}>
                  {supervisorLabel(s)}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="edit_product_type">{t("production.workOrders.field.productType")}</Label>
            <Select id="edit_product_type" {...form.register("product_type")}>
              <option value="">—</option>
              <option value="PC">PC</option>
              <option value="PL">PL</option>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="edit_recipe">{t("production.workOrders.field.recipe")}</Label>
            <Select id="edit_recipe" {...form.register("recipe_id")}>
              <option value="">—</option>
              {recipes.map((recipe) => (
                <option key={recipe.id} value={recipe.id}>
                  {productName(recipe.target_product_id)} · v{recipe.version}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="edit_packaging_bom">{t("production.workOrders.field.packagingBom")}</Label>
            <Select id="edit_packaging_bom" {...form.register("packaging_bom_id")}>
              <option value="">—</option>
              {packagingBoms.map((bom) => (
                <option key={bom.id} value={bom.id}>
                  {productName(bom.target_product_id)} · v{bom.version}
                </option>
              ))}
            </Select>
          </div>
          <Button type="submit" className="w-full" disabled={isPending}>
            {isPending ? t("production.workOrders.updating") : t("production.workOrders.update")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Asks when the order really finished, so an order closed the next morning records the true time. */
export function CloseWorkOrderDialog({
  order,
  onClose,
  onSubmit,
  isPending,
}: {
  order: WorkOrder | null;
  onClose: () => void;
  onSubmit: (id: string, closedAt: string) => void;
  isPending: boolean;
}) {
  const { t } = useI18n();
  const form = useForm<{ closed_at: string }>({
    resolver: zodResolver(z.object({ closed_at: z.string().min(1, t("common.required")) })),
  });

  useEffect(() => {
    if (order) form.reset({ closed_at: nowDatetimeLocalValue() });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [order?.id]);

  return (
    <Dialog open={order !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("production.workOrders.dialog.closeTitle")}</DialogTitle>
          <DialogDescription>{t("production.workOrders.dialog.closeDescription")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={form.handleSubmit((input) => order && onSubmit(order.id, new Date(input.closed_at).toISOString()))}
        >
          <div className="space-y-1.5">
            <Label htmlFor="close_at">{t("production.workOrders.field.closedAt")}</Label>
            <Input id="close_at" type="datetime-local" {...form.register("closed_at")} />
            {form.formState.errors.closed_at && <p className="text-sm text-destructive">{form.formState.errors.closed_at.message}</p>}
          </div>
          <Button type="submit" className="w-full" disabled={isPending}>
            {isPending ? t("production.workOrders.closing") : t("production.workOrders.close")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
