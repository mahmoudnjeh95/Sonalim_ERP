import { useEffect, useMemo, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Checkbox } from "../../../components/ui/checkbox";
import { Label } from "../../../components/ui/label";
import { Select } from "../../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { useDelegateJob, useTeamCandidates, useTeams, type DelegateAssignment, type JobDetail, type Person } from "../api";
import { CHECK_ACTION_ICON, CHECK_STATE_LABEL_KEY } from "../labels";
import { apiErrorMessage } from "./jobFormat";

/**
 * Chef d'atelier: hands each point of the job to a team member (an HR
 * employee — technicians need no account). The list offers the job's team
 * members; "Tout le personnel" widens it to every active employee, and a job
 * without a team always shows everyone. Only the points whose assignee
 * changed are sent. Accepted points are locked: nobody will redo them.
 */
export function DelegateDialog({
  job,
  open,
  onOpenChange,
}: {
  job: JobDetail;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;

  const { data: teams = [] } = useTeams(token);
  const { data: candidates = [] } = useTeamCandidates(token);
  const delegate = useDelegateJob(token);

  const teamMembers = useMemo<Person[]>(() => {
    const team = teams.find((entry) => entry.id === job.team_id);
    return team ? team.members.map((member) => ({ id: member.employee_id, name: member.name })) : [];
  }, [teams, job.team_id]);

  const [showEveryone, setShowEveryone] = useState(false);
  // check id -> employee id ("" = nobody).
  const [assignees, setAssignees] = useState<Record<string, string>>({});
  const [bulkEmployeeId, setBulkEmployeeId] = useState("");

  useEffect(() => {
    if (open) {
      setAssignees(Object.fromEntries(job.checks.map((check) => [check.id, check.assignee_employee_id ?? ""])));
      setBulkEmployeeId("");
      setShowEveryone(false);
      delegate.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, job.id]);

  const options = useMemo<Person[]>(() => {
    const base = showEveryone || teamMembers.length === 0 ? candidates : teamMembers;
    // Whoever already holds a point stays in the list, even from outside the team.
    const known = new Map(base.map((person) => [person.id, person]));
    for (const check of job.checks) {
      if (check.assignee_employee_id && check.assignee_name && !known.has(check.assignee_employee_id)) {
        known.set(check.assignee_employee_id, { id: check.assignee_employee_id, name: check.assignee_name });
      }
    }
    return [...known.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [showEveryone, teamMembers, candidates, job.checks]);

  const editableChecks = job.checks.filter((check) => check.state !== "accepted");

  const changes: DelegateAssignment[] = editableChecks
    .filter((check) => (assignees[check.id] ?? "") !== (check.assignee_employee_id ?? ""))
    .map((check) => ({ check_id: check.id, employee_id: assignees[check.id] || null }));

  function applyToAll() {
    setAssignees((current) => {
      const next = { ...current };
      for (const check of editableChecks) next[check.id] = bulkEmployeeId;
      return next;
    });
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (changes.length === 0) return;
    delegate.mutate(
      { jobId: job.id, assignments: changes },
      {
        onSuccess: () => {
          toast.success(t("maintenance.jobs.delegate.done"));
          onOpenChange(false);
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t("maintenance.jobs.delegate.title")}</DialogTitle>
          <DialogDescription>{t("maintenance.jobs.delegate.description")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          {teamMembers.length > 0 && (
            <label className="flex min-h-10 cursor-pointer items-center gap-2 text-sm">
              <Checkbox checked={showEveryone} onCheckedChange={(checked) => setShowEveryone(checked === true)} />
              {t("maintenance.jobs.delegate.showEveryone")}
            </label>
          )}

          <div className="space-y-1.5 rounded-md border border-border bg-muted/40 p-3">
            <Label htmlFor="delegate-bulk">{t("maintenance.jobs.delegate.bulk")}</Label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <div className="min-w-0 flex-1">
                <Select id="delegate-bulk" value={bulkEmployeeId} onChange={(event) => setBulkEmployeeId(event.target.value)}>
                  <option value="">{t("maintenance.jobs.unassigned")}</option>
                  {options.map((person) => (
                    <option key={person.id} value={person.id}>
                      {person.name}
                    </option>
                  ))}
                </Select>
              </div>
              <Button type="button" variant="outline" onClick={applyToAll}>
                {t("maintenance.jobs.delegate.bulkApply")}
              </Button>
            </div>
          </div>

          <ul className="space-y-3">
            {job.checks.map((check, index) => {
              const Icon = CHECK_ACTION_ICON[check.action];
              const locked = check.state === "accepted";
              return (
                <li key={check.id} className="space-y-1.5">
                  <div className="flex items-center gap-2 text-sm">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold">
                      {index + 1}
                    </span>
                    <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                    <span className="min-w-0 flex-1 truncate font-medium">{check.label}</span>
                    {locked && <Badge variant="success">{t(CHECK_STATE_LABEL_KEY.accepted)}</Badge>}
                  </div>
                  <Select
                    aria-label={`${t("maintenance.jobs.column.assignee")} — ${check.label}`}
                    value={assignees[check.id] ?? ""}
                    disabled={locked}
                    onChange={(event) => setAssignees((current) => ({ ...current, [check.id]: event.target.value }))}
                  >
                    <option value="">{t("maintenance.jobs.unassigned")}</option>
                    {options.map((person) => (
                      <option key={person.id} value={person.id}>
                        {person.name}
                      </option>
                    ))}
                  </Select>
                </li>
              );
            })}
          </ul>

          {delegate.isError && (
            <p className="text-sm text-destructive" role="alert">
              {apiErrorMessage(delegate.error, t("maintenance.jobs.delegate.error"))}
            </p>
          )}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={changes.length === 0 || delegate.isPending}>
              {delegate.isPending ? t("maintenance.jobs.delegate.saving") : t("maintenance.jobs.delegate.submit")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
