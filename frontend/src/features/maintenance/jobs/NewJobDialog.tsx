import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useFieldArray, useForm } from "react-hook-form";
import { Plus, Trash2 } from "lucide-react";
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
import { cn } from "../../../lib/utils";
import {
  useChefCandidates,
  useCreateJob,
  useEquipmentList,
  useEquipmentViews,
  useTeams,
  type CheckAction,
} from "../api";
import { CHECK_ACTION_LABEL_KEY, JOB_PRIORITY_LABEL_KEY } from "../labels";
import { CheckpointPicker } from "../map/CheckpointPicker";
import { apiErrorMessage, todayIso } from "./jobFormat";

const TEXTAREA_CLASS =
  "flex w-full rounded-md border border-border bg-background px-3 py-1.5 text-base shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm";

const CHECK_ACTIONS = ["inspect", "lubricate", "tighten", "clean", "replace", "measure", "other"] as const satisfies readonly CheckAction[];
const PRIORITIES = ["normal", "urgent"] as const;

// Messages are translation keys, resolved with t() where they are shown, so a
// validation error reads in the user's language like every other string.
const newJobSchema = z
  .object({
    equipment_id: z.string().min(1, "common.required"),
    title: z.string().trim().min(1, "common.required"),
    description: z.string(),
    priority: z.enum(PRIORITIES),
    due_date: z.string().min(1, "common.required"),
    stops_machine: z.boolean(),
    checkpoint_ids: z.array(z.string()),
    tasks: z.array(
      z.object({
        label: z.string().trim().min(1, "common.required"),
        action: z.enum(CHECK_ACTIONS),
      }),
    ),
    team_id: z.string(),
    chef_user_id: z.string(),
  })
  // A job with nothing to check cannot be created (the API answers NO_CHECKS).
  .refine((values) => values.checkpoint_ids.length + values.tasks.length > 0, {
    message: "maintenance.jobs.new.error.noChecks",
    path: ["checkpoint_ids"],
  });
type NewJobForm = z.infer<typeof newJobSchema>;

function emptyForm(): NewJobForm {
  return {
    equipment_id: "",
    title: "",
    description: "",
    // This dialog is how a supervisor raises a job outside the programs: urgent, due today, unless they say otherwise.
    priority: "urgent",
    due_date: todayIso(),
    stops_machine: false,
    checkpoint_ids: [],
    tasks: [],
    team_id: "",
    chef_user_id: "",
  };
}

/**
 * Supervisor (`maintenance.plan_jobs`): raises a corrective job on a machine —
 * points picked from the machine's map and/or free tasks typed on the spot.
 * With a chef given the job is created already assigned; without, it waits in
 * "À assigner".
 */
export function NewJobDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const token = session!.token;

  const {
    register,
    control,
    handleSubmit,
    reset,
    setValue,
    watch,
    formState: { errors },
  } = useForm<NewJobForm>({ resolver: zodResolver(newJobSchema), defaultValues: emptyForm() });
  const tasks = useFieldArray({ control, name: "tasks" });

  const equipmentId = watch("equipment_id");
  const teamId = watch("team_id");
  const chefUserId = watch("chef_user_id");

  const { data: equipment = [] } = useEquipmentList(token);
  const { data: views = [], isLoading: viewsLoading } = useEquipmentViews(token, equipmentId || null);
  const { data: teams = [] } = useTeams(token);
  const { data: chefCandidates = [] } = useChefCandidates(token);
  const create = useCreateJob(token);

  useEffect(() => {
    if (open) {
      reset(emptyForm());
      create.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, reset]);

  const machines = equipment
    .filter((item) => !item.archived_at)
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name));
  const offeredTeams = teams.filter((team) => !team.archived_at);
  // A team's own chef stays selectable even when the candidates list does not carry them.
  const selectedTeam = teams.find((team) => team.id === teamId);
  const chefOptions =
    selectedTeam?.chef_user_id && selectedTeam.chef_name && !chefCandidates.some((person) => person.id === selectedTeam.chef_user_id)
      ? [...chefCandidates, { id: selectedTeam.chef_user_id, name: selectedTeam.chef_name }]
      : chefCandidates;

  const errorText = (message: string | undefined) => (message ? t(message as TranslationKey) : undefined);

  function onSubmit(values: NewJobForm) {
    create.mutate(
      {
        equipment_id: values.equipment_id,
        title: values.title,
        description: values.description.trim() || null,
        priority: values.priority,
        due_date: values.due_date,
        stops_machine: values.stops_machine,
        checkpoint_ids: values.checkpoint_ids,
        tasks: values.tasks.map((task) => ({ label: task.label, action: task.action })),
        team_id: values.team_id || null,
        chef_user_id: values.chef_user_id || null,
      },
      {
        onSuccess: (job) => {
          toast.success(t("maintenance.jobs.new.created").replace("{number}", job.number), {
            action: { label: t("maintenance.jobs.new.open"), onClick: () => navigate(`/maintenance/jobs/${job.id}`) },
          });
          onOpenChange(false);
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("maintenance.jobs.new.title")}</DialogTitle>
          <DialogDescription>{t("maintenance.jobs.new.description")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-5" onSubmit={handleSubmit(onSubmit)} noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="job-equipment">{t("maintenance.jobs.field.machine")}</Label>
            <Select
              id="job-equipment"
              aria-invalid={errors.equipment_id ? true : undefined}
              {...register("equipment_id", {
                // The points belong to a machine: changing it drops the ones picked on the previous one.
                onChange: () => setValue("checkpoint_ids", []),
              })}
            >
              <option value="">{t("maintenance.jobs.field.machine.choose")}</option>
              {machines.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.code} — {item.name}
                </option>
              ))}
            </Select>
            {errors.equipment_id && <p className="text-sm text-destructive">{errorText(errors.equipment_id.message)}</p>}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="job-title">{t("maintenance.jobs.field.title")}</Label>
            <Input
              id="job-title"
              placeholder={t("maintenance.jobs.field.title.placeholder")}
              error={errorText(errors.title?.message)}
              {...register("title")}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="job-description">
              {t("maintenance.jobs.field.description")}{" "}
              <span className="font-normal text-muted-foreground">({t("common.optional")})</span>
            </Label>
            <textarea id="job-description" rows={2} className={TEXTAREA_CLASS} {...register("description")} />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>{t("maintenance.jobs.field.priority")}</Label>
              <Controller
                control={control}
                name="priority"
                render={({ field }) => (
                  <div className="grid grid-cols-2 gap-1 rounded-lg border border-border bg-muted/40 p-1" role="radiogroup">
                    {PRIORITIES.map((priority) => {
                      const active = field.value === priority;
                      return (
                        <button
                          key={priority}
                          type="button"
                          role="radio"
                          aria-checked={active}
                          onClick={() => field.onChange(priority)}
                          className={cn(
                            "h-9 rounded-md text-sm font-medium transition-colors sm:h-8",
                            active && priority === "urgent" && "bg-destructive text-destructive-foreground shadow-soft",
                            active && priority === "normal" && "bg-background text-foreground shadow-soft",
                            !active && "text-muted-foreground hover:text-foreground",
                          )}
                        >
                          {t(JOB_PRIORITY_LABEL_KEY[priority])}
                        </button>
                      );
                    })}
                  </div>
                )}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="job-due-date">{t("maintenance.jobs.field.dueDate")}</Label>
              <Input id="job-due-date" type="date" error={errorText(errors.due_date?.message)} {...register("due_date")} />
            </div>
          </div>

          <div className="flex items-start justify-between gap-3 rounded-md border border-border p-3">
            <div className="min-w-0">
              <Label htmlFor="job-stops-machine">{t("maintenance.jobs.field.stopsMachine")}</Label>
              <p className="mt-1 text-xs text-muted-foreground">{t("maintenance.jobs.field.stopsMachine.hint")}</p>
            </div>
            <Controller
              control={control}
              name="stops_machine"
              render={({ field }) => <Switch id="job-stops-machine" checked={field.value} onCheckedChange={field.onChange} />}
            />
          </div>

          <div className="space-y-1.5">
            <Label>{t("maintenance.jobs.field.checkpoints")}</Label>
            {equipmentId ? (
              <Controller
                control={control}
                name="checkpoint_ids"
                render={({ field }) => (
                  <CheckpointPicker views={views} value={field.value} onChange={field.onChange} isLoading={viewsLoading} />
                )}
              />
            ) : (
              <p className="rounded-md border border-dashed border-border px-3 py-4 text-sm text-muted-foreground">
                {t("maintenance.jobs.field.checkpoints.pickMachine")}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <Label>{t("maintenance.jobs.field.tasks")}</Label>
                <p className="mt-1 text-xs text-muted-foreground">{t("maintenance.jobs.field.tasks.hint")}</p>
              </div>
              <Button type="button" size="sm" variant="outline" onClick={() => tasks.append({ label: "", action: "other" })}>
                <Plus className="h-3.5 w-3.5" />
                {t("maintenance.jobs.field.tasks.add")}
              </Button>
            </div>
            {tasks.fields.map((field, index) => (
              <div key={field.id} className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 sm:grid-cols-[minmax(0,1fr)_170px_auto]">
                <div className="col-span-2 sm:col-span-1">
                  <Input
                    aria-label={t("maintenance.jobs.field.tasks.label")}
                    placeholder={t("maintenance.jobs.field.tasks.label.placeholder")}
                    error={errorText(errors.tasks?.[index]?.label?.message)}
                    {...register(`tasks.${index}.label`)}
                  />
                </div>
                <Select aria-label={t("maintenance.jobs.field.tasks.action")} {...register(`tasks.${index}.action`)}>
                  {CHECK_ACTIONS.map((action) => (
                    <option key={action} value={action}>
                      {t(CHECK_ACTION_LABEL_KEY[action])}
                    </option>
                  ))}
                </Select>
                <Button
                  type="button"
                  variant="ghost"
                  className="h-10 w-10 px-0 sm:h-9 sm:w-9"
                  aria-label={t("common.delete")}
                  onClick={() => tasks.remove(index)}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
            {errors.checkpoint_ids?.message && (
              <p className="text-sm text-destructive" role="alert">
                {errorText(errors.checkpoint_ids.message)}
              </p>
            )}
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="job-team">{t("maintenance.jobs.field.team")}</Label>
              <Select
                id="job-team"
                {...register("team_id", {
                  // A team brings its own chef; the chef stays editable below.
                  onChange: (event) => {
                    const team = teams.find((entry) => entry.id === event.target.value);
                    if (team?.chef_user_id) setValue("chef_user_id", team.chef_user_id);
                  },
                })}
              >
                <option value="">{t("maintenance.jobs.field.team.none")}</option>
                {offeredTeams.map((team) => (
                  <option key={team.id} value={team.id}>
                    {team.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="job-chef">{t("maintenance.jobs.field.chef")}</Label>
              <Select id="job-chef" {...register("chef_user_id")}>
                <option value="">{t("maintenance.jobs.field.chef.later")}</option>
                {chefOptions.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.name}
                  </option>
                ))}
              </Select>
            </div>
            <p className="text-xs text-muted-foreground sm:col-span-2">
              {chefUserId ? t("maintenance.jobs.new.hint.assigned") : t("maintenance.jobs.new.hint.planned")}
            </p>
          </div>

          {create.isError && (
            <p className="text-sm text-destructive" role="alert">
              {apiErrorMessage(create.error, t("maintenance.jobs.new.error"))}
            </p>
          )}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? t("maintenance.jobs.new.creating") : t("maintenance.jobs.new.create")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
