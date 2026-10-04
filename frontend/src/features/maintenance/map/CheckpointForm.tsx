import { useEffect, useState } from "react";
import { Archive, Plus, Trash2 } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Checkbox } from "../../../components/ui/checkbox";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { formatQuantity } from "../../../lib/units";
import { CHECK_ACTION_ICON, CHECK_ACTION_LABEL_KEY } from "../labels";
import {
  useSparePartsCatalog,
  type CheckAction,
  type Checkpoint,
  type CheckpointPartInput,
  type CreateCheckpointInput,
  type SparePartProduct,
  type UpdateCheckpointInput,
} from "../api";

const TEXTAREA_CLASS =
  "flex w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

const CHECK_ACTIONS: CheckAction[] = ["inspect", "lubricate", "tighten", "clean", "replace", "measure", "other"];

/** A part row as typed: the quantity stays text so "0,5" can be typed with a comma. */
interface PartRow {
  product_id: string;
  quantity: string;
}

export interface CheckpointFormValues {
  label: string;
  action: CheckAction;
  instructions: string;
  measure_unit: string;
  requires_photo: boolean;
  parts: PartRow[];
}

function emptyValues(): CheckpointFormValues {
  return { label: "", action: "inspect", instructions: "", measure_unit: "", requires_photo: false, parts: [] };
}

function valuesFrom(checkpoint: Checkpoint): CheckpointFormValues {
  return {
    label: checkpoint.label,
    action: checkpoint.action,
    instructions: checkpoint.instructions ?? "",
    measure_unit: checkpoint.measure_unit ?? "",
    requires_photo: checkpoint.requires_photo,
    parts: checkpoint.parts.map((part) => ({ product_id: part.product_id, quantity: String(part.quantity) })),
  };
}

/** A typed quantity as a number, accepting a decimal comma; NaN when it is not one. */
function parseQuantity(text: string): number {
  const trimmed = text.trim().replace(",", ".");
  return trimmed === "" ? Number.NaN : Number(trimmed);
}

function toPartsInput(parts: PartRow[]): CheckpointPartInput[] {
  return parts.map((part) => ({ product_id: part.product_id, quantity: parseQuantity(part.quantity) }));
}

type PartRowError =
  | "maintenance.map.point.parts.error.product"
  | "maintenance.map.point.parts.error.quantity"
  | "maintenance.map.point.parts.error.whole";

/** What is wrong with a part row, as a translation key; null when it is fine. */
function partRowError(row: PartRow, integerOnly: boolean): PartRowError | null {
  if (!row.product_id) return "maintenance.map.point.parts.error.product";
  const quantity = parseQuantity(row.quantity);
  if (!Number.isFinite(quantity) || quantity <= 0) return "maintenance.map.point.parts.error.quantity";
  if (integerOnly && !Number.isInteger(quantity)) return "maintenance.map.point.parts.error.whole";
  return null;
}

function toCreateInput(values: CheckpointFormValues, x_pct: number, y_pct: number): CreateCheckpointInput {
  return {
    x_pct,
    y_pct,
    label: values.label.trim(),
    action: values.action,
    instructions: values.instructions.trim() || null,
    measure_unit: values.action === "measure" ? values.measure_unit.trim() || null : null,
    requires_photo: values.requires_photo,
    parts: toPartsInput(values.parts),
  };
}

function toUpdateInput(values: CheckpointFormValues): UpdateCheckpointInput {
  return {
    label: values.label.trim(),
    action: values.action,
    instructions: values.instructions.trim() || null,
    measure_unit: values.action === "measure" ? values.measure_unit.trim() || null : null,
    requires_photo: values.requires_photo,
    parts: toPartsInput(values.parts),
  };
}

/**
 * The point's "spare parts needed" rows: a product kept in the spare-parts
 * location (the catalog), a quantity in its own unit, and what that location
 * holds. A part already on the point stays listed even if it has since left
 * the catalog, so editing the point never drops it silently.
 */
function PartsSection({
  rows,
  onChange,
  checkpoint,
  showErrors,
}: {
  rows: PartRow[];
  onChange: (rows: PartRow[]) => void;
  checkpoint: Checkpoint | null;
  showErrors: boolean;
}) {
  const { t } = useI18n();
  const { session } = useAuth();
  const { data: catalog, isLoading } = useSparePartsCatalog(session!.token);
  const products = catalog?.products ?? [];
  const byId = new Map<string, SparePartProduct>(products.map((product) => [product.product_id, product]));
  // Parts already on the point but no longer offered: kept as options under their saved name.
  const savedOnly = (checkpoint?.parts ?? []).filter((part) => !byId.has(part.product_id));

  function update(index: number, patch: Partial<PartRow>) {
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <Label>{t("maintenance.map.point.parts")}</Label>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={isLoading || (products.length === 0 && savedOnly.length === 0)}
          onClick={() => onChange([...rows, { product_id: "", quantity: "" }])}
        >
          <Plus className="h-3.5 w-3.5" />
          {t("maintenance.map.point.parts.add")}
        </Button>
      </div>
      {!isLoading && !catalog?.location_id && (
        <p className="text-xs text-muted-foreground">{t("maintenance.map.point.parts.noLocation")}</p>
      )}
      {!isLoading && catalog?.location_id && products.length === 0 && (
        <p className="text-xs text-muted-foreground">
          {t("maintenance.map.point.parts.noProducts").replace("{location}", catalog.location_name ?? "")}
        </p>
      )}
      {rows.length === 0 && catalog?.location_id && products.length > 0 && (
        <p className="text-xs text-muted-foreground">{t("maintenance.map.point.parts.none")}</p>
      )}
      {rows.map((row, index) => {
        const product = byId.get(row.product_id);
        const saved = savedOnly.find((part) => part.product_id === row.product_id);
        const unit = product?.uom_code ?? saved?.uom_code ?? null;
        const error = showErrors ? partRowError(row, product?.uom_integer_only ?? false) : null;
        const takenElsewhere = new Set(rows.filter((_, i) => i !== index).map((other) => other.product_id));
        return (
          <div key={index} className="space-y-1 rounded-md border border-border p-2">
            <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 sm:grid-cols-[minmax(0,1fr)_110px_auto]">
              <div className="col-span-2 sm:col-span-1">
                <Select
                  aria-label={t("maintenance.map.point.parts.product")}
                  value={row.product_id}
                  onChange={(event) => update(index, { product_id: event.target.value })}
                >
                  <option value="">{t("maintenance.map.point.parts.product.placeholder")}</option>
                  {products.map((option) => (
                    <option key={option.product_id} value={option.product_id} disabled={takenElsewhere.has(option.product_id)}>
                      {option.name}
                    </option>
                  ))}
                  {savedOnly.map((part) => (
                    <option key={part.product_id} value={part.product_id} disabled={takenElsewhere.has(part.product_id)}>
                      {part.product_name}
                    </option>
                  ))}
                </Select>
              </div>
              <Input
                inputMode="decimal"
                aria-label={t("maintenance.map.point.parts.quantity")}
                placeholder={unit ?? t("maintenance.map.point.parts.quantity")}
                value={row.quantity}
                onChange={(event) => update(index, { quantity: event.target.value })}
              />
              <Button
                type="button"
                variant="ghost"
                className="h-10 w-10 px-0 sm:h-9 sm:w-9"
                aria-label={t("common.delete")}
                onClick={() => onChange(rows.filter((_, i) => i !== index))}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
            {product && (
              <p className="text-xs text-muted-foreground">
                {product.available > 0
                  ? product.locations
                      .map((location) => `${location.location_name} : ${formatQuantity(location.available, product.uom_code)}`)
                      .join(" · ")
                  : t("maintenance.parts.stock.out")}
              </p>
            )}
            {saved && <p className="text-xs text-muted-foreground">{t("maintenance.map.point.parts.notOffered")}</p>}
            {error && <p className="text-xs text-destructive">{t(error)}</p>}
          </div>
        );
      })}
    </div>
  );
}

/**
 * The side/below form for a single checkpoint pin: shown for a newly placed
 * pin (no `checkpoint`, caller supplies the dropped `x`/`y`) or for an
 * existing one selected from the points list (`checkpoint` set — edits PATCH
 * in place). `onSubmit` receives the API input shape directly so the editor
 * just calls its create/update mutation.
 */
export function CheckpointForm({
  checkpoint,
  pendingPosition,
  onSubmitCreate,
  onSubmitUpdate,
  onArchive,
  onCancel,
  isSaving,
  isArchiving,
}: {
  checkpoint: Checkpoint | null;
  /** Set only when creating: the % position of the just-placed pin. */
  pendingPosition?: { x: number; y: number };
  onSubmitCreate?: (input: CreateCheckpointInput) => void;
  onSubmitUpdate?: (input: UpdateCheckpointInput) => void;
  onArchive?: () => void;
  onCancel: () => void;
  isSaving: boolean;
  isArchiving?: boolean;
}) {
  const { t } = useI18n();
  const [values, setValues] = useState<CheckpointFormValues>(() => (checkpoint ? valuesFrom(checkpoint) : emptyValues()));
  const [showPartErrors, setShowPartErrors] = useState(false);
  const { session } = useAuth();
  const { data: catalog } = useSparePartsCatalog(session!.token);

  useEffect(() => {
    setValues(checkpoint ? valuesFrom(checkpoint) : emptyValues());
    setShowPartErrors(false);
  }, [checkpoint]);

  const isEditing = !!checkpoint;
  const canSubmit = values.label.trim().length > 0;
  const integerOnly = (productId: string) =>
    catalog?.products.find((product) => product.product_id === productId)?.uom_integer_only ?? false;
  const partsValid = values.parts.every((row) => partRowError(row, integerOnly(row.product_id)) === null);

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    if (!partsValid) {
      setShowPartErrors(true);
      return;
    }
    if (isEditing) {
      onSubmitUpdate?.(toUpdateInput(values));
    } else if (pendingPosition) {
      onSubmitCreate?.(toCreateInput(values, pendingPosition.x, pendingPosition.y));
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {isEditing ? t("maintenance.map.point.editTitle") : t("maintenance.map.point.newTitle")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-1.5">
            <Label htmlFor="checkpoint-label">{t("maintenance.map.point.field.label")}</Label>
            <Input
              id="checkpoint-label"
              autoFocus
              value={values.label}
              onChange={(event) => setValues((prev) => ({ ...prev, label: event.target.value }))}
              placeholder={t("maintenance.map.point.field.label.placeholder")}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="checkpoint-action">{t("maintenance.map.point.field.action")}</Label>
            <Select
              id="checkpoint-action"
              value={values.action}
              onChange={(event) => setValues((prev) => ({ ...prev, action: event.target.value as CheckAction }))}
            >
              {CHECK_ACTIONS.map((action) => (
                <option key={action} value={action}>
                  {t(CHECK_ACTION_LABEL_KEY[action])}
                </option>
              ))}
            </Select>
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              {(() => {
                const Icon = CHECK_ACTION_ICON[values.action];
                return <Icon className="h-3.5 w-3.5" />;
              })()}
              {t(CHECK_ACTION_LABEL_KEY[values.action])}
            </div>
          </div>
          {values.action === "measure" && (
            <div className="space-y-1.5">
              <Label htmlFor="checkpoint-unit">{t("maintenance.map.point.field.unit")}</Label>
              <Input
                id="checkpoint-unit"
                value={values.measure_unit}
                onChange={(event) => setValues((prev) => ({ ...prev, measure_unit: event.target.value }))}
                placeholder={t("maintenance.map.point.field.unit.placeholder")}
              />
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="checkpoint-instructions">{t("maintenance.map.point.field.instructions")}</Label>
            <textarea
              id="checkpoint-instructions"
              rows={3}
              className={TEXTAREA_CLASS}
              value={values.instructions}
              onChange={(event) => setValues((prev) => ({ ...prev, instructions: event.target.value }))}
              placeholder={t("maintenance.map.point.field.instructions.placeholder")}
            />
          </div>
          <PartsSection
            rows={values.parts}
            onChange={(parts) => setValues((prev) => ({ ...prev, parts }))}
            checkpoint={checkpoint}
            showErrors={showPartErrors}
          />
          <label className="flex min-h-11 cursor-pointer items-center gap-2.5" htmlFor="checkpoint-requires-photo">
            <Checkbox
              id="checkpoint-requires-photo"
              checked={values.requires_photo}
              onCheckedChange={(checked) => setValues((prev) => ({ ...prev, requires_photo: checked === true }))}
            />
            <span className="text-sm">{t("maintenance.map.point.field.requiresPhoto")}</span>
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" disabled={!canSubmit || isSaving}>
              {isSaving ? t("maintenance.map.point.saving") : isEditing ? t("maintenance.map.point.saveChanges") : t("maintenance.map.point.create")}
            </Button>
            <Button type="button" variant="outline" onClick={onCancel}>
              {t("common.cancel")}
            </Button>
            {isEditing && onArchive && (
              <Button type="button" variant="outline" className="ml-auto" onClick={onArchive} disabled={isArchiving}>
                <Archive className="h-3.5 w-3.5" />
                {isArchiving ? t("maintenance.map.point.archiving") : t("maintenance.map.point.archive")}
              </Button>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
