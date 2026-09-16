import { useFieldArray, type Control, type UseFormReturn, type FieldValues, type Path } from "react-hook-form";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { useI18n } from "../../lib/i18n";
import { formatDuration } from "../../lib/units";
import { DOWNTIME_MOTIFS, DOWNTIME_TYPES, DOWNTIME_CLASSIFICATIONS } from "./DowntimeMotifSelect";

/** One row of the arrêt editor. */
export interface DowntimeLineForm {
  motif: string;
  downtime_type: string;
  classification: string;
  minutes: number;
  note: string;
}

/**
 * The arrêt list on the daily report form.
 *
 * It replaced a single downtime_minutes/downtime_reason pair, which could only
 * ever hold one stoppage — a shift with a mixer jam and a power cut had to pick
 * one to report and fold the other's minutes into it. Naming each stoppage's own
 * motif is what makes the total legible: 35 minutes for one reason is a different
 * fact than 20 for one and 15 for another.
 */
export function DowntimeLinesField<TFieldValues extends FieldValues>({
  form,
  name,
}: {
  form: UseFormReturn<TFieldValues>;
  name: Path<TFieldValues>;
}) {
  const { t } = useI18n();
  const { fields, append, remove } = useFieldArray({
    control: form.control as unknown as Control<FieldValues>,
    name: name as unknown as string,
  });

  function addLine() {
    append({ motif: "", downtime_type: "", classification: "", minutes: 0, note: "" });
  }

  const watchedLines = (form.watch(name) ?? []) as DowntimeLineForm[];
  const totalMinutes = watchedLines.reduce((sum, line) => sum + (Number(line.minutes) || 0), 0);

  return (
    <div className="space-y-2">
      {fields.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-3 py-2 text-center text-xs text-muted-foreground">
          {t("production.downtime.empty")}
        </p>
      ) : (
        <div className="space-y-2">
          {fields.map((field, index) => (
            <div key={field.id} className="space-y-2 rounded-lg border border-border p-2">
              <div className="grid grid-cols-1 items-end gap-2 sm:grid-cols-3">
                <div className="space-y-1">
                  <Label htmlFor={`${name}_${index}_downtime_type`} className="text-xs">
                    {t("production.downtime.field.type")}
                  </Label>
                  <Select
                    id={`${name}_${index}_downtime_type`}
                    {...form.register(`${name}.${index}.downtime_type` as Path<TFieldValues>)}
                  >
                    <option value="">—</option>
                    {DOWNTIME_TYPES.map((type) => (
                      <option key={type} value={type}>
                        {t(`production.downtime.type.${type}` as Parameters<typeof t>[0])}
                      </option>
                    ))}
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label htmlFor={`${name}_${index}_classification`} className="text-xs">
                    {t("production.downtime.field.classification")}
                  </Label>
                  <Select
                    id={`${name}_${index}_classification`}
                    {...form.register(`${name}.${index}.classification` as Path<TFieldValues>)}
                  >
                    <option value="">—</option>
                    {DOWNTIME_CLASSIFICATIONS.map((classification) => (
                      <option key={classification} value={classification}>
                        {t(`production.downtime.classification.${classification}` as Parameters<typeof t>[0])}
                      </option>
                    ))}
                  </Select>
                </div>

                <div className="space-y-1">
                  <Label htmlFor={`${name}_${index}_motif`} className="text-xs">
                    {t("production.downtime.field.motif")}
                  </Label>
                  <Select
                    id={`${name}_${index}_motif`}
                    {...form.register(`${name}.${index}.motif` as Path<TFieldValues>)}
                  >
                    <option value="">—</option>
                    {DOWNTIME_MOTIFS.map((motif) => (
                      <option key={motif} value={motif}>
                        {t(`production.downtime.motif.${motif}` as Parameters<typeof t>[0])}
                      </option>
                    ))}
                  </Select>
                </div>
              </div>

              <div className="grid grid-cols-1 items-end gap-2 sm:grid-cols-[minmax(0,7rem)_minmax(0,1fr)_auto]">
                <div className="space-y-1">
                  <Label htmlFor={`${name}_${index}_minutes`} className="text-xs">
                    {t("production.downtime.field.minutes")}
                  </Label>
                  <Input
                    id={`${name}_${index}_minutes`}
                    type="number"
                    step="1"
                    min={0}
                    {...form.register(`${name}.${index}.minutes` as Path<TFieldValues>)}
                  />
                </div>

                <div className="space-y-1">
                  <Label htmlFor={`${name}_${index}_note`} className="text-xs">
                    {t("production.downtime.field.note")}
                  </Label>
                  <Input
                    id={`${name}_${index}_note`}
                    {...form.register(`${name}.${index}.note` as Path<TFieldValues>)}
                  />
                </div>

                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  aria-label={t("production.downtime.remove")}
                  onClick={() => remove(index)}
                >
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <Button type="button" size="sm" variant="outline" onClick={addLine}>
            <Plus className="h-3.5 w-3.5" />
            {t("production.downtime.addLine")}
          </Button>
          <HelpTooltip text={t("production.downtime.help")} />
        </div>
        {fields.length > 0 && (
          <p className="text-xs font-medium text-muted-foreground">
            {t("production.downtime.total")}: {formatDuration(totalMinutes)}
          </p>
        )}
      </div>
    </div>
  );
}

/** Form rows for a report being opened for edit; an empty list stays empty. */
export function toDowntimeLineForms(
  lines:
    | { motif: string | null; downtime_type: string | null; classification: string | null; minutes: number; note: string | null }[]
    | undefined,
): DowntimeLineForm[] {
  return (lines ?? []).map((line) => ({
    motif: line.motif ?? "",
    downtime_type: line.downtime_type ?? "",
    classification: line.classification ?? "",
    minutes: line.minutes,
    note: line.note ?? "",
  }));
}

/**
 * Form rows on their way to the API.
 *
 * Rows that recorded nothing are dropped here rather than sent as zeroes: a
 * shift that pressed "add" and changed its mind has reported no stoppage.
 */
export function fromDowntimeLineForms(lines: DowntimeLineForm[] | undefined) {
  return (lines ?? [])
    .filter((line) => Number(line.minutes) > 0 || line.note.trim().length > 0)
    .map((line) => ({
      motif: line.motif.trim() || null,
      downtime_type: line.downtime_type.trim() || null,
      classification: line.classification.trim() || null,
      minutes: Number(line.minutes),
      note: line.note.trim() || null,
    }));
}
