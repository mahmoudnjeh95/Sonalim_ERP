import { useFieldArray, type Control, type UseFormReturn, type FieldValues, type Path } from "react-hook-form";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { useI18n } from "../../lib/i18n";
import { productUnit } from "../../lib/units";

/** One row of the semoule editor: one quality, its quantity, and the store it came out of. */
export interface SemolinaLineForm {
  product_id: string;
  quantity: number;
  location_id: string;
}

/**
 * The semoule list on the daily report form.
 *
 * Replaced a single quantity/product pair: the plant runs more than one
 * quality (semoule extra, semoule courante, and so on) and a shift can pour a
 * mix of them, so one field could only ever name one. Each line also carries
 * its own store, unlike rebroyat — different qualities are routinely kept in
 * different silos, and a report-wide location would force a lie onto
 * whichever quality wasn't stored there.
 *
 * Every line leaves stock on validation, from its own location — this is not
 * a déchet list, it is the report's one raw-material consumption.
 */
export function SemolinaLinesField<TFieldValues extends FieldValues>({
  form,
  name,
  products,
  locations,
  uoms,
}: {
  form: UseFormReturn<TFieldValues>;
  name: Path<TFieldValues>;
  products: { id: string; name: string; uom_id: string }[];
  locations: { id: string; name: string }[];
  uoms: { id: string; code: string; symbol?: string | null }[];
}) {
  const { t } = useI18n();
  const { fields, append, remove } = useFieldArray({
    control: form.control as unknown as Control<FieldValues>,
    name: name as unknown as string,
  });

  function addLine() {
    append({ product_id: "", quantity: 0, location_id: "" });
  }

  return (
    <div className="space-y-2">
      {fields.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-3 py-2 text-center text-xs text-muted-foreground">
          {t("production.semolina.empty")}
        </p>
      ) : (
        <div className="space-y-2">
          {fields.map((field, index) => {
            const productId = form.watch(`${name}.${index}.product_id` as Path<TFieldValues>) as
              | string
              | undefined;
            const unit = productUnit(productId, products, uoms);
            return (
              <div
                key={field.id}
                className="grid grid-cols-1 items-end gap-2 rounded-lg border border-border p-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,7rem)_minmax(0,1fr)_auto]"
              >
                <div className="space-y-1">
                  <Label htmlFor={`${name}_${index}_product`} className="text-xs">
                    {t("production.semolina.field.product")}
                  </Label>
                  <Select
                    id={`${name}_${index}_product`}
                    {...form.register(`${name}.${index}.product_id` as Path<TFieldValues>)}
                  >
                    <option value="">—</option>
                    {products.map((product) => (
                      <option key={product.id} value={product.id}>
                        {product.name}
                      </option>
                    ))}
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label htmlFor={`${name}_${index}_quantity`} className="text-xs">
                    {unit
                      ? `${t("production.semolina.field.quantity")} (${unit})`
                      : t("production.semolina.field.quantity")}
                  </Label>
                  <Input
                    id={`${name}_${index}_quantity`}
                    type="number"
                    step="any"
                    {...form.register(`${name}.${index}.quantity` as Path<TFieldValues>)}
                  />
                </div>

                <div className="space-y-1">
                  <Label htmlFor={`${name}_${index}_location`} className="text-xs">
                    {t("production.semolina.field.location")}
                  </Label>
                  <Select
                    id={`${name}_${index}_location`}
                    {...form.register(`${name}.${index}.location_id` as Path<TFieldValues>)}
                  >
                    <option value="">—</option>
                    {locations.map((location) => (
                      <option key={location.id} value={location.id}>
                        {location.name}
                      </option>
                    ))}
                  </Select>
                </div>

                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  aria-label={t("production.semolina.remove")}
                  onClick={() => remove(index)}
                >
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </div>
            );
          })}
        </div>
      )}

      <div className="flex items-center gap-1.5">
        <Button type="button" size="sm" variant="outline" onClick={addLine}>
          <Plus className="h-3.5 w-3.5" />
          {t("production.semolina.addLine")}
        </Button>
        <HelpTooltip text={t("production.semolina.help")} />
      </div>
    </div>
  );
}

/** Form rows for a report being opened for edit; an empty list stays empty. */
export function toSemolinaLineForms(
  lines: { product_id: string | null; quantity: number; location_id: string | null }[] | undefined,
): SemolinaLineForm[] {
  return (lines ?? []).map((line) => ({
    product_id: line.product_id ?? "",
    quantity: line.quantity,
    location_id: line.location_id ?? "",
  }));
}

/**
 * Form rows on their way to the API.
 *
 * Rows that recorded nothing are dropped here rather than sent as zeroes: a
 * shift that pressed "add" and changed its mind poured nothing, and a zero
 * with no product would reach the OF's raw-material total as a quantity with
 * no unit.
 */
export function fromSemolinaLineForms(lines: SemolinaLineForm[] | undefined) {
  return (lines ?? [])
    .filter((line) => Number(line.quantity) > 0)
    .map((line) => ({
      product_id: line.product_id || null,
      quantity: Number(line.quantity),
      location_id: line.location_id || null,
    }));
}
