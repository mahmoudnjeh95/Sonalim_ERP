import { useEffect } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useFieldArray, useForm } from "react-hook-form";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { Select } from "../../../components/ui/select";
import { Skeleton } from "../../../components/ui/skeleton";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { useCreatePartRequest, usePartRequestProducts, type JobDetail } from "../api";
import { apiErrorMessage } from "../jobs/jobFormat";

const TEXTAREA_CLASS =
  "flex w-full rounded-md border border-border bg-background px-3 py-1.5 text-base shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm";

// Messages are translation keys, resolved with t() where they are shown, so a
// validation error reads in the user's language like every other dialog.
const lineSchema = z.object({
  product_id: z.string().min(1, "common.required"),
  quantity: z.string().min(1, "common.required"),
});

const partRequestSchema = z.object({
  lines: z.array(lineSchema).min(1, "maintenance.parts.request.error.noLines"),
  note: z.string(),
});
type PartRequestForm = z.infer<typeof partRequestSchema>;

function emptyForm(): PartRequestForm {
  return { lines: [{ product_id: "", quantity: "" }], note: "" };
}

/** Lines and note a request opens with: a check's spare parts, from the guided check. */
export interface PartRequestInitial {
  lines: { product_id: string; quantity: number }[];
  note: string;
}

function initialForm(initial: PartRequestInitial | undefined): PartRequestForm {
  if (!initial || initial.lines.length === 0) return emptyForm();
  return {
    lines: initial.lines.map((line) => ({ product_id: line.product_id, quantity: String(line.quantity) })),
    note: initial.note,
  };
}

/**
 * The chef's "Demander des pièces" dialog, opened from the job page, or from a
 * step of the guided check with that point's spare parts already filled in
 * (`initial`). A line repeater (product + quantity, always in the product's own
 * unit — the backend refuses any other `uom_id` with `UOM_MISMATCH` because
 * stock is issued in that unit with no conversion) plus a free-text note.
 *
 * Products come from the maintenance module's own list, spare parts first, so a
 * technician without the core product rights still sees them.
 */
export function PartRequestDialog({
  job,
  open,
  onOpenChange,
  initial,
}: {
  job: JobDetail;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initial?: PartRequestInitial;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;

  const { data: products = [], isLoading: productsLoading } = usePartRequestProducts(token);
  const spareProducts = products.filter((product) => product.in_spare_parts);
  const otherProducts = products.filter((product) => !product.in_spare_parts);
  const createRequest = useCreatePartRequest(token);

  const {
    register,
    control,
    handleSubmit,
    reset,
    watch,
    formState: { errors },
  } = useForm<PartRequestForm>({ resolver: zodResolver(partRequestSchema), defaultValues: emptyForm() });
  const lines = useFieldArray({ control, name: "lines" });
  const watchedLines = watch("lines");

  useEffect(() => {
    if (open) {
      reset(initialForm(initial));
      createRequest.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, reset]);

  const errorText = (message: string | undefined) => (message ? t(message as TranslationKey) : undefined);

  function onSubmit(values: PartRequestForm) {
    createRequest.mutate(
      {
        jobId: job.id,
        input: {
          lines: values.lines.map((line) => {
            const product = products.find((p) => p.product_id === line.product_id);
            // The product is always in the list the line was picked from; its unit is the only one accepted.
            return { product_id: line.product_id, uom_id: product?.uom_id ?? "", quantity: Number(line.quantity.replace(",", ".")) };
          }),
          note: values.note.trim() || null,
        },
      },
      {
        onSuccess: () => {
          toast.success(t("maintenance.parts.request.created"));
          onOpenChange(false);
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t("maintenance.parts.request.title")}</DialogTitle>
          <DialogDescription>{t("maintenance.parts.request.description").replace("{number}", job.number)}</DialogDescription>
        </DialogHeader>
        {/* The fields mount once the products are in, so a pre-filled line shows its product, not "—". */}
        {productsLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        ) : (
          <form className="space-y-4" onSubmit={handleSubmit(onSubmit)} noValidate>
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <Label>{t("maintenance.parts.request.field.lines")}</Label>
                <Button type="button" size="sm" variant="outline" onClick={() => lines.append({ product_id: "", quantity: "" })}>
                  <Plus className="h-3.5 w-3.5" />
                  {t("maintenance.parts.request.field.lines.add")}
                </Button>
              </div>
              {lines.fields.map((field, index) => {
                const productId = watchedLines?.[index]?.product_id;
                const product = products.find((p) => p.product_id === productId);
                const unit = product?.uom_code ?? null;
                const wholeNumberOnly = product?.uom_integer_only ?? false;
                return (
                  <div key={field.id} className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 sm:grid-cols-[minmax(0,1fr)_140px_auto]">
                    <div className="col-span-2 sm:col-span-1">
                      <Select
                        aria-label={t("maintenance.parts.request.field.product")}
                        aria-invalid={errors.lines?.[index]?.product_id ? true : undefined}
                        {...register(`lines.${index}.product_id`)}
                      >
                        <option value="">—</option>
                        {spareProducts.length > 0 && (
                          <optgroup label={t("maintenance.parts.request.group.spare")}>
                            {spareProducts.map((option) => (
                              <option key={option.product_id} value={option.product_id}>
                                {option.name}
                              </option>
                            ))}
                          </optgroup>
                        )}
                        {otherProducts.length > 0 && (
                          <optgroup label={t("maintenance.parts.request.group.other")}>
                            {otherProducts.map((option) => (
                              <option key={option.product_id} value={option.product_id}>
                                {option.name}
                              </option>
                            ))}
                          </optgroup>
                        )}
                      </Select>
                      {errors.lines?.[index]?.product_id && (
                        <p className="mt-1 text-sm text-destructive">{errorText(errors.lines[index]?.product_id?.message)}</p>
                      )}
                    </div>
                    <div>
                      <Input
                        type="number"
                        min={0}
                        step={wholeNumberOnly ? "1" : "any"}
                        aria-label={t("maintenance.parts.request.field.quantity")}
                        placeholder={unit ?? t("maintenance.parts.request.field.quantity")}
                        error={errorText(errors.lines?.[index]?.quantity?.message)}
                        {...register(`lines.${index}.quantity`)}
                      />
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      className="h-10 w-10 px-0 sm:h-9 sm:w-9"
                      aria-label={t("common.delete")}
                      disabled={lines.fields.length <= 1}
                      onClick={() => lines.remove(index)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                );
              })}
              {errors.lines?.root?.message && <p className="text-sm text-destructive">{errorText(errors.lines.root.message)}</p>}
              {errors.lines?.message && <p className="text-sm text-destructive">{errorText(errors.lines.message)}</p>}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="part-request-note">
                {t("maintenance.parts.request.field.note")}{" "}
                <span className="font-normal text-muted-foreground">({t("common.optional")})</span>
              </Label>
              <textarea id="part-request-note" rows={2} className={TEXTAREA_CLASS} {...register("note")} />
            </div>

            {createRequest.isError && (
              <p className="text-sm text-destructive" role="alert">
                {apiErrorMessage(createRequest.error, t("maintenance.parts.request.error"))}
              </p>
            )}
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" disabled={createRequest.isPending}>
                {createRequest.isPending ? t("maintenance.parts.request.sending") : t("maintenance.parts.request.submit")}
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
