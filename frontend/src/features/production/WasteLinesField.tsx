import { useFieldArray, type Control, type UseFormReturn, type FieldValues, type Path } from "react-hook-form";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { useI18n } from "../../lib/i18n";
import { productUnit } from "../../lib/units";
import type { WasteCategory } from "./api";

/**
 * One row of the déchet editor.
 *
 * Generic over the category so each report type narrows it: a daily form's rows
 * can only be `raw_material` or `press`, which is what lets the schema refuse a
 * packing stage before the request is ever made.
 */
export interface WasteLineForm<C extends WasteCategory = WasteCategory> {
  category: C;
  product_id: string;
  quantity: number;
  note: string;
}

/**
 * The déchet list on a report form.
 *
 * It replaced a fixed column per category, which could not record scotch at all
 * and — worse — never said which item a figure counted, so every screen had to
 * borrow a unit from whatever product looked closest. Naming the item is what
 * makes "5" readable: five kilos of rebut and five cartons are different facts.
 *
 * The unit is shown, never chosen. A product has one stock unit and that is the
 * unit the warehouse would count it in; offering a choice would invite a figure
 * that disagrees with the item it names.
 *
 * Nothing here moves stock. Semoule left stock when it was poured, packaging when
 * it was consumed, and the finished product only ever enters at the good
 * quantity — so a waste line records a loss rather than posting one.
 */
export function WasteLinesField<TFieldValues extends FieldValues>({
  form,
  name,
  categories,
  products,
  uoms,
  defaultProductFor,
}: {
  form: UseFormReturn<TFieldValues>;
  name: Path<TFieldValues>;
  /** The stages this report type has. A daily report has no packaging stage. */
  categories: WasteCategory[];
  products: { id: string; name: string; uom_id: string }[];
  uoms: { id: string; code: string; symbol?: string | null }[];
  /**
   * The item a stage usually loses, filled in when a row is added. A guess the
   * shift can override beats an empty dropdown they must resolve every time.
   */
  defaultProductFor?: (category: WasteCategory) => string | undefined;
}) {
  const { t } = useI18n();
  const { fields, append, remove } = useFieldArray({
    control: form.control as unknown as Control<FieldValues>,
    name: name as unknown as string,
  });

  const categoryLabel = (category: WasteCategory) =>
    t(`production.waste.category.${category}` as Parameters<typeof t>[0]);

  function addLine() {
    const category = categories[0];
    append({
      category,
      product_id: defaultProductFor?.(category) ?? "",
      quantity: 0,
      note: "",
    });
  }

  return (
    <div className="space-y-2">
      {fields.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-3 py-2 text-center text-xs text-muted-foreground">
          {t("production.waste.empty")}
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
                className="grid grid-cols-1 items-end gap-2 rounded-lg border border-border p-2 sm:grid-cols-[minmax(0,7rem)_minmax(0,1fr)_minmax(0,7rem)_minmax(0,1fr)_auto]"
              >
                <div className="space-y-1">
                  <Label htmlFor={`${name}_${index}_category`} className="text-xs">
                    {t("production.waste.field.category")}
                  </Label>
                  <Select
                    id={`${name}_${index}_category`}
                    {...form.register(`${name}.${index}.category` as Path<TFieldValues>)}
                  >
                    {categories.map((category) => (
                      <option key={category} value={category}>
                        {categoryLabel(category)}
                      </option>
                    ))}
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label htmlFor={`${name}_${index}_product`} className="text-xs">
                    {t("production.waste.field.product")}
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
                    {/* The item's own stock unit, shown rather than chosen. */}
                    {unit
                      ? `${t("production.waste.field.quantity")} (${unit})`
                      : t("production.waste.field.quantity")}
                  </Label>
                  <Input
                    id={`${name}_${index}_quantity`}
                    type="number"
                    step="any"
                    {...form.register(`${name}.${index}.quantity` as Path<TFieldValues>)}
                  />
                </div>

                <div className="space-y-1">
                  <Label htmlFor={`${name}_${index}_note`} className="text-xs">
                    {t("production.waste.field.note")}
                  </Label>
                  <Input
                    id={`${name}_${index}_note`}
                    placeholder={t("production.waste.notePlaceholder")}
                    {...form.register(`${name}.${index}.note` as Path<TFieldValues>)}
                  />
                </div>

                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  aria-label={t("production.waste.remove")}
                  onClick={() => remove(index)}
                >
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </div>
            );
          })}
        </div>
      )}

      {/* The explanation is long and standing text costs the form four lines of
          height on every screen. It reads the same in a tooltip. */}
      <div className="flex items-center gap-1.5">
        <Button type="button" size="sm" variant="outline" onClick={addLine}>
          <Plus className="h-3.5 w-3.5" />
          {t("production.waste.addLine")}
        </Button>
        <HelpTooltip text={t("production.waste.help")} />
      </div>
    </div>
  );
}

/** Form rows for a report being opened for edit; an empty list stays empty. */
export function toWasteLineForms<C extends WasteCategory = WasteCategory>(
  lines: { category: WasteCategory; product_id: string | null; quantity: number; note: string | null }[] | undefined,
): WasteLineForm<C>[] {
  // The narrowing is the backend's guarantee, not a hope: a daily report's lines
  // are refused unless they name a daily stage, so what comes back is already in
  // the report type's own set.
  return (lines ?? []).map((line) => ({
    category: line.category as C,
    product_id: line.product_id ?? "",
    quantity: line.quantity,
    note: line.note ?? "",
  }));
}

/**
 * Form rows on their way to the API.
 *
 * Rows that recorded nothing are dropped here rather than sent as zeroes: a
 * shift that pressed "add" and changed its mind has reported no waste, and an
 * empty row with no item would reach the OF's consolidation as a quantity with
 * no unit.
 */
export function fromWasteLineForms(lines: WasteLineForm<WasteCategory>[] | undefined) {
  return (lines ?? [])
    .filter((line) => Number(line.quantity) > 0 || line.note.trim().length > 0)
    .map((line) => ({
      category: line.category,
      product_id: line.product_id || null,
      quantity: Number(line.quantity),
      note: line.note.trim() || null,
    }));
}
