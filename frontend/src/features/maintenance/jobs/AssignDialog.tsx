import { useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "../../../components/ui/button";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { useAssignJob, useChefCandidates, useTeams, type JobListItem } from "../api";
import { apiErrorMessage } from "./jobFormat";

/**
 * Supervisor: gives a job its chef d'atelier (and, optionally, its team).
 * Picking a team pre-fills the chef with that team's own; the chef stays
 * editable. Also used to re-assign a job that is still only `assigned`.
 */
export function AssignDialog({
  job,
  open,
  onOpenChange,
}: {
  job: JobListItem;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;

  const { data: teams = [] } = useTeams(token);
  const { data: chefCandidates = [] } = useChefCandidates(token);
  const assign = useAssignJob(token);

  const [teamId, setTeamId] = useState("");
  const [chefUserId, setChefUserId] = useState("");

  // Reopening starts from what the job has today, not from an abandoned edit.
  useEffect(() => {
    if (open) {
      setTeamId(job.team_id ?? "");
      setChefUserId(job.chef_user_id ?? "");
      assign.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, job.id, job.team_id, job.chef_user_id]);

  // An archived team is not offered, except the one the job already has.
  const offeredTeams = teams.filter((team) => !team.archived_at || team.id === job.team_id);
  // The job's current chef stays selectable even if they are no longer in the candidates list.
  const chefOptions =
    job.chef_user_id && job.chef_name && !chefCandidates.some((person) => person.id === job.chef_user_id)
      ? [...chefCandidates, { id: job.chef_user_id, name: job.chef_name }]
      : chefCandidates;

  function handleTeamChange(nextTeamId: string) {
    setTeamId(nextTeamId);
    const team = teams.find((entry) => entry.id === nextTeamId);
    if (team?.chef_user_id) setChefUserId(team.chef_user_id);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!chefUserId) return;
    assign.mutate(
      { jobId: job.id, input: { team_id: teamId || null, chef_user_id: chefUserId } },
      {
        onSuccess: () => {
          toast.success(t("maintenance.jobs.assign.done"));
          onOpenChange(false);
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("maintenance.jobs.assign.title")}</DialogTitle>
          <DialogDescription>
            {job.number} · {job.title}
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-1.5">
            <Label htmlFor="assign-team">{t("maintenance.jobs.field.team")}</Label>
            <Select id="assign-team" value={teamId} onChange={(event) => handleTeamChange(event.target.value)}>
              <option value="">{t("maintenance.jobs.field.team.none")}</option>
              {offeredTeams.map((team) => (
                <option key={team.id} value={team.id}>
                  {team.name}
                </option>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">{t("maintenance.jobs.field.team.hint")}</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="assign-chef">{t("maintenance.jobs.field.chef")}</Label>
            <Select id="assign-chef" value={chefUserId} onChange={(event) => setChefUserId(event.target.value)} required>
              <option value="">{t("maintenance.jobs.field.chef.choose")}</option>
              {chefOptions.map((person) => (
                <option key={person.id} value={person.id}>
                  {person.name}
                </option>
              ))}
            </Select>
          </div>
          {assign.isError && (
            <p className="text-sm text-destructive" role="alert">
              {apiErrorMessage(assign.error, t("maintenance.jobs.assign.error"))}
            </p>
          )}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={!chefUserId || assign.isPending}>
              {assign.isPending ? t("maintenance.jobs.assign.saving") : t("maintenance.jobs.assign.submit")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
