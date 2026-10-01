import { useEffect } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Switch } from "../../../components/ui/switch";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import {
  useCreateProgram,
  useEquipmentList,
  useEquipmentViews,
  useTeams,
  useUpdateProgram,
  type Program,
} from "../api";
import { CheckpointPicker } from "../map/CheckpointPicker";
import { apiErrorMessage, todayIso } from "../jobs/jobFormat";

const TEXTAREA_CLASS =
  "flex w-full rounded-md border border-border bg-background px-3 py-1.5 text-base shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm";

const INTERVAL_UNITS = ["day", "week", "month"] as const;

// Messages are translation keys, resolved with t() where they are shown, so a
// validation error reads in the user's language like every other field.
const programSchema = z.object({
  equipment_id: z.string().min(1, "common.required"),
  name: z.string().trim().min(1, "common.required"),
  description: z.string(),
  interval_value: z.coerce.number({ invalid_type_error: "common.required" }).int().min(1, "maintenance.programs.field.intervalValue.error"),
  interval_unit: z.enum(INTERVAL_UNITS),
  start_date: z.string().min(1, "common.required"),
  lead_days: z.coerce.number({ invalid_type_error: "common.required" }).int().min(0, "maintenance.programs.field.leadDays.error"),
  estimated_minutes: z.string(),
  default_team_id: z.string(),
  stops_machine: z.boolean(),
  checkpoint_ids: z.array(z.string()),
});
type ProgramForm = z.infer<typeof programSchema>;

function emptyForm(): ProgramForm {
  return {
    equipment_id: "",
    name: "",
    description: "",
    interval_value: 1,
    interval_unit: "month",
    start_date: todayIso(),
    lead_days: 0,
    estimated_minutes: "",
    default_team_id: "",
    stops_machine: false,
    checkpoint_ids: [],
  };
}

function programToForm(program: Program): ProgramForm {
  return {
    equipment_id: program.equipment_id,
    name: program.name,
    description: program.description ?? "",
    interval_value: program.interval_value,
    interval_unit: program.interval_unit,
    start_date: program.start_date.slice(0, 10),
    lead_days: program.lead_days,
    estimated_minutes: program.estimated_minutes === null || program.estimated_minutes === undefined ? "" : String(program.estimated_minutes),
    default_team_id: program.default_team_id ?? "",
    stops_machine: program.stops_machine,
    checkpoint_ids: program.checkpoint_ids,
  };
}

/**
 * Create/edit a preventive program: fixed recurrence (every N days/weeks/
 * months from the start date), a notice lead time, and the points it checks
 * — picked from the machine's map, grouped by view (reuses F3/F4's
 * `CheckpointPicker`). Leaving every point unchecked means "every active
 * point on the machine", called out in the field's own helper text rather
 * than defaulted silently.
 */
export function ProgramDialog({
  open,
  onOpenChange,
  program,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Present = editing; absent = creating. */
  program?: Program | null;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const isEditing = !!program;

  const {
    register,
    control,
    handleSubmit,
    reset,
    setValue,
    watch,
    formState: { errors },
  } = useForm<ProgramForm>({ resolver: zodResolver(programSchema), defaultValues: emptyForm() });

  const equipmentId = watch("equipment_id");

  const { data: equipment = [] } = useEquipmentList(token);
  const { data: views = [], isLoading: viewsLoading } = useEquipmentViews(token, equipmentId || null);
  const { data: teams = [] } = useTeams(token);
  const create = useCreateProgram(token);
  const update = useUpdateProgram(token);
  const mutation = isEditing ? update : create;

  useEffect(() => {
    if (open) {
      reset(program ? programToForm(program) : emptyForm());
      create.reset();
      update.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, program, reset]);

  const machines = equipment
    .filter((item) => !item.archived_at || item.id === program?.equipment_id)
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name));
  const offeredTeams = teams.filter((team) => !team.archived_at || team.id === program?.default_team_id);

  const errorText = (message: string | undefined) => (message ? t(message as TranslationKey) : undefined);

  function onSubmit(values: ProgramForm) {
    const input = {
      equipment_id: values.equipment_id,
      name: values.name,
      description: values.description.trim() || null,
      interval_value: values.interval_value,
      interval_unit: values.interval_unit,
      start_date: values.start_date,
      lead_days: values.lead_days,
      estimated_minutes: values.estimated_minutes.trim() === "" ? null : Number(values.estimated_minutes),
      default_team_id: values.default_team_id || null,
      stops_machine: values.stops_machine,
      checkpoint_ids: values.checkpoint_ids,
    };
    if (isEditing && program) {
      update.mutate(
        { programId: program.id, input },
        {
          onSuccess: () => {
            toast.success(t("maintenance.programs.dialog.saved"));
            onOpenChange(false);
          },
        },
      );
    } else {
      create.mutate(input, {
        onSuccess: () => {
          toast.success(t("maintenance.programs.dialog.created"));
          onOpenChange(false);
        },
      });
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{isEditing ? t("maintenance.programs.dialog.editTitle") : t("maintenance.programs.dialog.title")}</DialogTitle>
          <DialogDescription>
            {isEditing ? t("maintenance.programs.dialog.editDescription") : t("maintenance.programs.dialog.description")}
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-5" onSubmit={handleSubmit(onSubmit)} noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="program-equipment">{t("maintenance.programs.field.machine")}</Label>
            <Select
              id="program-equipment"
              aria-invalid={errors.equipment_id ? true : undefined}
              {...register("equipment_id", {
                // The points belong to a machine: changing it drops the ones picked on the previous one.
                onChange: () => setValue("checkpoint_ids", []),
              })}
            >
              <option value="">{t("maintenance.programs.field.machine.choose")}</option>
              {machines.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.code} — {item.name}
                </option>
              ))}
            </Select>
            {errors.equipment_id && <p className="text-sm text-destructive">{errorText(errors.equipment_id.message)}</p>}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="program-name">{t("maintenance.programs.field.name")}</Label>
            <Input
              id="program-name"
              placeholder={t("maintenance.programs.field.name.placeholder")}
              error={errorText(errors.name?.message)}
              {...register("name")}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="program-description">
              {t("maintenance.programs.field.description")}{" "}
              <span className="font-normal text-muted-foreground">({t("common.optional")})</span>
            </Label>
            <textarea id="program-description" rows={2} className={TEXTAREA_CLASS} {...register("description")} />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-[1fr_1fr]">
            <div className="space-y-1.5">
              <Label htmlFor="program-interval-value">{t("maintenance.programs.field.interval")}</Label>
              <div className="flex gap-2">
                <Input
                  id="program-interval-value"
                  type="number"
                  min={1}
                  step={1}
                  className="w-20"
                  error={errorText(errors.interval_value?.message)}
                  {...register("interval_value")}
                />
                <div className="flex-1">
                  <Select id="program-interval-unit" {...register("interval_unit")}>
                    <option value="day">{t("maintenance.programs.intervalUnit.day")}</option>
                    <option value="week">{t("maintenance.programs.intervalUnit.week")}</option>
                    <option value="month">{t("maintenance.programs.intervalUnit.month")}</option>
                  </Select>
                </div>
              </div>
              <p className="text-xs text-muted-foreground">{t("maintenance.programs.field.interval.hint")}</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="program-start-date">{t("maintenance.programs.field.startDate")}</Label>
              <Input id="program-start-date" type="date" error={errorText(errors.start_date?.message)} {...register("start_date")} />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="program-lead-days">{t("maintenance.programs.field.leadDays")}</Label>
              <Input
                id="program-lead-days"
                type="number"
                min={0}
                step={1}
                error={errorText(errors.lead_days?.message)}
                {...register("lead_days")}
              />
              <p className="text-xs text-muted-foreground">{t("maintenance.programs.field.leadDays.hint")}</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="program-estimated-minutes">
                {t("maintenance.programs.field.estimatedMinutes")}{" "}
                <span className="font-normal text-muted-foreground">({t("common.optional")})</span>
              </Label>
              <Input id="program-estimated-minutes" type="number" min={0} step={1} {...register("estimated_minutes")} />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="program-team">{t("maintenance.programs.field.team")}</Label>
            <Select id="program-team" {...register("default_team_id")}>
              <option value="">{t("maintenance.programs.field.team.none")}</option>
              {offeredTeams.map((team) => (
                <option key={team.id} value={team.id}>
                  {team.name}
                </option>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">{t("maintenance.programs.field.team.hint")}</p>
          </div>

          <div className="flex items-start justify-between gap-3 rounded-md border border-border p-3">
            <div className="min-w-0">
              <Label htmlFor="program-stops-machine">{t("maintenance.programs.field.stopsMachine")}</Label>
              <p className="mt-1 text-xs text-muted-foreground">{t("maintenance.programs.field.stopsMachine.hint")}</p>
            </div>
            <Controller
              control={control}
              name="stops_machine"
              render={({ field }) => <Switch id="program-stops-machine" checked={field.value} onCheckedChange={field.onChange} />}
            />
          </div>

          <div className="space-y-1.5">
            <Label>{t("maintenance.programs.field.checkpoints")}</Label>
            <p className="text-xs text-muted-foreground">{t("maintenance.programs.field.checkpoints.hint")}</p>
            {equipmentId ? (
              <Controller
                control={control}
                name="checkpoint_ids"
                render={({ field }) => (
                  <CheckpointPicker
                    equipmentId={equipmentId}
                    views={views}
                    value={field.value}
                    onChange={field.onChange}
                    isLoading={viewsLoading}
                  />
                )}
              />
            ) : (
              <p className="rounded-md border border-dashed border-border px-3 py-4 text-sm text-muted-foreground">
                {t("maintenance.programs.field.checkpoints.pickMachine")}
              </p>
            )}
          </div>

          {mutation.isError && (
            <p className="text-sm text-destructive" role="alert">
              {apiErrorMessage(mutation.error, t("maintenance.programs.dialog.error"))}
            </p>
          )}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending
                ? t("maintenance.programs.dialog.saving")
                : isEditing
                  ? t("maintenance.programs.dialog.saveChanges")
                  : t("maintenance.programs.dialog.create")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
