import { useMutation, useQuery } from "@tanstack/react-query";
import { Plus, Tags, Trash2 } from "lucide-react";
import { useFieldArray, type UseFormReturn } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { formatXofWithCode } from "../../lib/currency";
import { useI18n } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { ProductSelect } from "../../components/patterns/ProductSelect";
import type { CatalogProduct } from "../products/catalog";
import { getSalesSettings, resolvePrices, SALES_SETTINGS_QUERY_KEY } from "./pricingApi";
import { computeTotals, largestDiscount, lineNet } from "./salesMath";

/** A priced line as the quote and order forms hold it. */
export const pricedLineSchema = z.object({
  product_id: z.string().min(1, "Required"),
  quantity: z.coerce.number().positive("Must be > 0"),
  unit_price: z.coerce.number().nonnegative("Must be ≥ 0"),
  discount_rate: z.coerce.number().min(0).max(100).default(0),
  vat_rate: z.coerce.number().min(0).max(100).default(18),
  price_list_id: z.string().nullable().optional(),
});
export type PricedLineForm = z.infer<typeof pricedLineSchema>;

/** The part of a form this editor drives: its lines and its document discount. */
export interface PricedFormShape {
  partner_id: string;
  discount_rate: number;
  lines: PricedLineForm[];
}

export function newPricedLine(defaultVat: number): PricedLineForm {
  return { product_id: "", quantity: 1, unit_price: 0, discount_rate: 0, vat_rate: defaultVat, price_list_id: null };
}

export function useSalesSettings() {
  const { session } = useAuth();
  return useQuery({ queryKey: SALES_SETTINGS_QUERY_KEY, queryFn: () => getSalesSettings(session!.token) });
}

interface Props {
  form: UseFormReturn<PricedFormShape>;
  products: CatalogProduct[];
  idPrefix: string;
  quantityLabel?: (productId: string) => string;
  quantityStep?: (productId: string) => string;
}

/**
 * Lines with price, discount and VAT, the document discount and the totals, shared by the quote and order
 * forms. "Customer prices" fills every line from the customer's price list (or the default list, or the
 * catalog) and the customer's standing discount; a price typed by hand stays until the button is pressed.
 */
export function PricedLinesFields({ form, products, idPrefix, quantityLabel, quantityStep }: Props) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const { register, control, watch, setValue, formState } = form;
  const { fields, append, remove } = useFieldArray({ control, name: "lines" });
  const settings = useSalesSettings().data;
  const defaultVat = Number(settings?.default_vat_rate ?? 18);
  const maxDiscount = Number(settings?.max_discount_rate ?? 10);

  const lines = watch("lines") ?? [];
  const documentDiscount = Number(watch("discount_rate")) || 0;
  const partnerId = watch("partner_id");
  const totals = computeTotals(lines, documentDiscount);
  const overLimit = !settings?.may_exceed_discount && largestDiscount(lines, documentDiscount) > maxDiscount + 0.005;

  const priceMutation = useMutation({
    mutationFn: () =>
      resolvePrices(token, {
        partner_id: partnerId || null,
        items: lines.filter((line) => line.product_id).map((line) => ({ product_id: line.product_id, quantity: Number(line.quantity) || 1 })),
      }),
    onSuccess: (prices) => {
      let next = 0;
      lines.forEach((line, index) => {
        if (!line.product_id) return;
        const price = prices[next++];
        setValue(`lines.${index}.unit_price`, Number(price.unit_price), { shouldDirty: true });
        setValue(`lines.${index}.price_list_id`, price.price_list_id, { shouldDirty: true });
      });
      const standing = Number(prices[0]?.discount_rate ?? 0);
      if (standing && !documentDiscount) setValue("discount_rate", standing, { shouldDirty: true });
      toast.success(t("sales.pricing.applied"));
    },
    onError: (error) => toast.error(t("sales.pricing.applyError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label>{t("sales.field.lines")}</Label>
        <div className="flex gap-1">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!lines.some((line) => line.product_id) || priceMutation.isPending}
            onClick={() => priceMutation.mutate()}
            title={t("sales.pricing.applyHint")}
          >
            <Tags className="h-3.5 w-3.5" />
            {t("sales.pricing.apply")}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => append(newPricedLine(defaultVat))}>
            <Plus className="h-3.5 w-3.5" />
            {t("sales.addLine")}
          </Button>
        </div>
      </div>

      <div className="space-y-2">
        {fields.map((field, index) => {
          const productId = lines[index]?.product_id ?? "";
          return (
            <div key={field.id} className="grid grid-cols-2 gap-2 rounded-md border p-2 sm:grid-cols-[minmax(0,1fr)_5rem_6.5rem_4.5rem_4.5rem_auto]">
              <div className="col-span-2 space-y-1 sm:col-span-1">
                <span className="block text-xs font-medium text-muted-foreground">{t("sales.field.productId")}</span>
                <ProductSelect id={`${idPrefix}_product_${index}`} products={products} placeholder={t("sales.field.productId")}
                  {...register(`lines.${index}.product_id` as const)} />
              </div>
              <div className="space-y-1">
                <span className="block text-xs font-medium text-muted-foreground">{quantityLabel ? quantityLabel(productId) : t("sales.field.qty")}</span>
                <Input type="number" step={quantityStep ? quantityStep(productId) : "any"} {...register(`lines.${index}.quantity` as const)} />
              </div>
              <div className="space-y-1">
                <span className="block text-xs font-medium text-muted-foreground">{t("sales.field.unitPrice")}</span>
                <Input type="number" step="any" {...register(`lines.${index}.unit_price` as const)} />
              </div>
              <div className="space-y-1">
                <span className="block text-xs font-medium text-muted-foreground">{t("sales.pricing.discountPct")}</span>
                <Input type="number" step="any" min={0} max={100} {...register(`lines.${index}.discount_rate` as const)} />
              </div>
              <div className="space-y-1">
                <span className="block text-xs font-medium text-muted-foreground">{t("sales.pricing.vatPct")}</span>
                <Input type="number" step="any" min={0} max={100} {...register(`lines.${index}.vat_rate` as const)} />
              </div>
              <div className="flex items-end justify-between gap-2 sm:flex-col sm:items-end">
                <span className="text-xs tabular-nums text-muted-foreground">{formatXofWithCode(Math.round(lineNet(lines[index] ?? field)))}</span>
                <Button type="button" variant="ghost" size="sm" disabled={fields.length === 1} onClick={() => remove(index)}
                  aria-label={t("sales.removeLine")}>
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          );
        })}
        {formState.errors.lines?.message && <p className="text-sm text-destructive">{formState.errors.lines.message}</p>}
      </div>

      <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
        <div className="space-y-1.5">
          <Label htmlFor={`${idPrefix}_discount`}>{t("sales.pricing.documentDiscount")}</Label>
          <Input id={`${idPrefix}_discount`} type="number" step="any" min={0} max={100} {...register("discount_rate")} />
        </div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-md bg-muted/50 p-3 text-sm">
          <dt className="text-muted-foreground">{t("sales.pricing.gross")}</dt>
          <dd className="text-right tabular-nums">{formatXofWithCode(totals.gross)}</dd>
          <dt className="text-muted-foreground">{t("sales.pricing.discount")}</dt>
          <dd className="text-right tabular-nums">{totals.discount ? `− ${formatXofWithCode(totals.discount)}` : formatXofWithCode(0)}</dd>
          <dt className="text-muted-foreground">{t("sales.pricing.exclTax")}</dt>
          <dd className="text-right tabular-nums">{formatXofWithCode(totals.excl_tax)}</dd>
          <dt className="text-muted-foreground">{t("sales.pricing.vat")}</dt>
          <dd className="text-right tabular-nums">{formatXofWithCode(totals.vat)}</dd>
          <dt className="font-medium">{t("sales.pricing.inclTax")}</dt>
          <dd className="text-right font-medium tabular-nums">{formatXofWithCode(totals.incl_tax)}</dd>
        </dl>
      </div>
      {overLimit && (
        <p className="text-sm text-amber-700 dark:text-amber-400">
          {t("sales.pricing.overLimit")} {maxDiscount} %
        </p>
      )}
    </div>
  );
}
