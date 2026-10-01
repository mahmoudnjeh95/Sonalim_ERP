import { useEffect, useState } from "react";
import { Archive } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Checkbox } from "../../../components/ui/checkbox";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { useI18n } from "../../../lib/i18n";
import { CHECK_ACTION_ICON, CHECK_ACTION_LABEL_KEY } from "../labels";
import type { CheckAction, Checkpoint, CreateCheckpointInput, UpdateCheckpointInput } from "../api";

const TEXTAREA_CLASS =
  "flex w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

const CHECK_ACTIONS: CheckAction[] = ["inspect", "lubricate", "tighten", "clean", "replace", "measure", "other"];

export interface CheckpointFormValues {
  label: string;
  action: CheckAction;
  instructions: string;
  measure_unit: string;
  requires_photo: boolean;
}

function emptyValues(): CheckpointFormValues {
  return { label: "", action: "inspect", instructions: "", measure_unit: "", requires_photo: false };
}

function valuesFrom(checkpoint: Checkpoint): CheckpointFormValues {
  return {
    label: checkpoint.label,
    action: checkpoint.action,
    instructions: checkpoint.instructions ?? "",
    measure_unit: checkpoint.measure_unit ?? "",
    requires_photo: checkpoint.requires_photo,
  };
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
  };
}

function toUpdateInput(values: CheckpointFormValues): UpdateCheckpointInput {
  return {
    label: values.label.trim(),
    action: values.action,
    instructions: values.instructions.trim() || null,
    measure_unit: values.action === "measure" ? values.measure_unit.trim() || null : null,
    requires_photo: values.requires_photo,
  };
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

  useEffect(() => {
    setValues(checkpoint ? valuesFrom(checkpoint) : emptyValues());
  }, [checkpoint]);

  const isEditing = !!checkpoint;
  const canSubmit = values.label.trim().length > 0;

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
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
