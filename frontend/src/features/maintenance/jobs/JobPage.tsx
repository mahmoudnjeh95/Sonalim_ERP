import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowLeft,
  Ban,
  History,
  Images,
  ListChecks,
  Lock,
  PackagePlus,
  Play,
  PowerOff,
  Send,
  UserCheck,
  Users,
} from "lucide-react";
import { toast } from "sonner";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { Label } from "../../../components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { formatDuration } from "../../../lib/units";
import { cn } from "../../../lib/utils";
import { useCancelJob, useCloseJob, useJob, useSubmitJob, type JobDetail } from "../api";
import { useHasPermission } from "../hooks";
import { JOB_KIND_LABEL_KEY, JOB_PRIORITY_LABEL_KEY, JOB_STATUS_BADGE_VARIANT, JOB_STATUS_LABEL_KEY } from "../labels";
import { AssignDialog } from "./AssignDialog";
import { DelegateDialog } from "./DelegateDialog";
import { JobChecks, checkRowId } from "./JobChecks";
import { JobPartRequests } from "./JobPartRequests";
import { JobTimeline } from "./JobTimeline";
import { JobViewsStrip } from "./JobViewsStrip";
import { ReviewPanel } from "./ReviewPanel";
import { WORKABLE_STATUSES, apiErrorMessage, formatDateTime, formatDay, isRedo } from "./jobFormat";
import { PartRequestDialog } from "../parts/PartRequestDialog";

const TEXTAREA_CLASS =
  "flex w-full rounded-md border border-border bg-background px-3 py-1.5 text-base shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm";

const JOBS_LIST_PATH = "/maintenance?tab=jobs";

/** Where the job stands, in one sentence built only from what the job records. */
function statusLine(job: JobDetail, t: (key: TranslationKey) => string): string {
  const pending = job.checks.filter((check) => check.state === "pending").length;
  const allAccepted = job.checks.length > 0 && job.checks.every((check) => check.state === "accepted");
  switch (job.status) {
    case "planned":
      return t("maintenance.jobs.statusLine.planned");
    case "assigned":
      return t("maintenance.jobs.statusLine.assigned").replace("{chef}", job.chef_name ?? "—");
    case "in_progress":
      return pending > 0
        ? t("maintenance.jobs.statusLine.in_progress").replace("{count}", String(pending))
        : t("maintenance.jobs.statusLine.readyToSubmit");
    case "rework":
      return pending > 0
        ? t("maintenance.jobs.statusLine.rework").replace("{count}", String(job.checks.filter(isRedo).length))
        : t("maintenance.jobs.statusLine.readyToSubmit");
    case "submitted":
      return allAccepted
        ? t("maintenance.jobs.statusLine.readyToClose")
        : t("maintenance.jobs.statusLine.submitted").replace("{date}", formatDateTime(job.submitted_at));
    case "closed":
      return t("maintenance.jobs.statusLine.closed").replace("{date}", formatDateTime(job.closed_at));
    case "cancelled":
      return job.cancel_reason
        ? t("maintenance.jobs.statusLine.cancelledWithReason").replace("{reason}", job.cancel_reason)
        : t("maintenance.jobs.statusLine.cancelled");
  }
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 break-words text-sm font-medium">{children}</dd>
    </div>
  );
}

function CancelDialog({ job, open, onOpenChange }: { job: JobDetail; open: boolean; onOpenChange: (open: boolean) => void }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const cancel = useCancelJob(session!.token);
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (open) {
      setReason("");
      cancel.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!reason.trim()) return;
    cancel.mutate(
      { jobId: job.id, reason: reason.trim() },
      {
        onSuccess: () => {
          toast.success(t("maintenance.jobs.cancel.done"));
          onOpenChange(false);
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("maintenance.jobs.cancel.title")}</DialogTitle>
          <DialogDescription>
            {t("maintenance.jobs.cancel.description").replace("{number}", job.number)}
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-1.5">
            <Label htmlFor="job-cancel-reason">{t("maintenance.jobs.cancel.reason")}</Label>
            <textarea
              id="job-cancel-reason"
              rows={3}
              autoFocus
              required
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder={t("maintenance.jobs.cancel.reason.placeholder")}
              className={TEXTAREA_CLASS}
            />
          </div>
          {cancel.isError && (
            <p className="text-sm text-destructive" role="alert">
              {apiErrorMessage(cancel.error, t("maintenance.jobs.cancel.error"))}
            </p>
          )}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("maintenance.jobs.cancel.keep")}
            </Button>
            <Button type="submit" variant="destructive" disabled={!reason.trim() || cancel.isPending}>
              {cancel.isPending ? t("maintenance.jobs.cancel.saving") : t("maintenance.jobs.cancel.submit")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/**
 * One maintenance job (`/maintenance/jobs/:jobId`): header, the actions the
 * signed-in user may take at this status, the supervisor's review, the points,
 * the machine photos, spare-parts requests and the history.
 *
 * Who sees what mirrors the API: supervisor actions need `maintenance.plan_jobs`;
 * chef actions need `maintenance.execute_jobs` AND being the job's chef (or
 * also holding plan_jobs) — the API answers 403 NOT_JOB_CHEF otherwise. Any
 * refusal is shown in the API's own words.
 *
 * Data: `useJob(token, jobId)`. Every maintenance mutation invalidates the
 * `["maintenance"]` query prefix, so this page refetches by itself after an
 * action taken here, in a dialog, in the wizard or on a parts request.
 */
export function JobPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const location = useLocation();
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;

  const canPlan = useHasPermission("maintenance.plan_jobs");
  const canExecute = useHasPermission("maintenance.execute_jobs");

  const { data: job, isLoading, error } = useJob(token, jobId ?? null);
  const submit = useSubmitJob(token);
  const close = useCloseJob(token);

  const [assignOpen, setAssignOpen] = useState(false);
  const [delegateOpen, setDelegateOpen] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [partRequestOpen, setPartRequestOpen] = useState(false);
  const [highlightedCheckId, setHighlightedCheckId] = useState<string | null>(null);

  // The list hands over where it was (its filters live in the URL), so "back" returns to the same view.
  const backTo = (location.state as { from?: string } | null)?.from ?? JOBS_LIST_PATH;

  const backLink = (
    <Button asChild variant="outline" size="sm">
      <Link to={backTo}>
        <ArrowLeft className="h-3.5 w-3.5" />
        {t("maintenance.jobs.back")}
      </Link>
    </Button>
  );

  if (isLoading) {
    return <AppLoader fullScreen />;
  }

  if (!job) {
    return (
      <div className="space-y-4">
        {backLink}
        <Card>
          <CardContent className="p-0">
            <EmptyState
              icon={<AlertTriangle className="h-5 w-5" />}
              title={t("maintenance.jobs.notFound.title")}
              description={apiErrorMessage(error, t("maintenance.jobs.notFound.description"))}
            />
          </CardContent>
        </Card>
      </div>
    );
  }

  const isChef = !!job.chef_user_id && job.chef_user_id === session!.userId;
  // Same rule as the API: the job's own chef, or a supervisor who may also execute.
  const canRun = canExecute && (isChef || canPlan);
  const isWorkable = WORKABLE_STATUSES.includes(job.status);
  const pendingCount = job.checks.filter((check) => check.state === "pending").length;
  const allAccepted = job.checks.length > 0 && job.checks.every((check) => check.state === "accepted");

  const showAssign = canPlan && (job.status === "planned" || job.status === "assigned");
  const showRun = canRun && isWorkable;
  const showSubmit = canRun && (job.status === "in_progress" || job.status === "rework");
  const showClose = canPlan && job.status === "submitted";
  const showCancel = canPlan && job.status !== "closed" && job.status !== "cancelled";
  const hasActions = showAssign || showRun || showSubmit || showClose || showCancel;
  // An executor looking at somebody else's job: say why there is nothing to launch.
  const notTheChef = canExecute && !canRun && isWorkable;

  function handleSubmit() {
    submit.mutate(job!.id, {
      onSuccess: () => toast.success(t("maintenance.jobs.submit.done")),
      onError: (mutationError) => toast.error(apiErrorMessage(mutationError, t("maintenance.jobs.submit.error"))),
    });
  }

  function handleClose() {
    close.mutate(job!.id, {
      onSuccess: () => toast.success(t("maintenance.jobs.close.done")),
      onError: (mutationError) => toast.error(apiErrorMessage(mutationError, t("maintenance.jobs.close.error"))),
    });
  }

  function handlePinClick(checkId: string) {
    setHighlightedCheckId(checkId);
    document.getElementById(checkRowId(checkId))?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  const progress = job.checks_total > 0 ? Math.round((job.checks_done / job.checks_total) * 100) : 0;

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }} className="space-y-4">
        {backLink}

        <Card>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
              <div className="min-w-0 space-y-1">
                <p className="font-mono text-xs text-muted-foreground">{job.number}</p>
                <h1 className="break-words text-xl font-semibold tracking-tight">{job.title}</h1>
                <p className="break-words text-sm text-muted-foreground">
                  <Link to={`/maintenance/equipment/${job.equipment_id}`} className="underline-offset-2 hover:text-primary hover:underline">
                    {job.equipment_code} — {job.equipment_name}
                  </Link>
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge variant={JOB_STATUS_BADGE_VARIANT[job.status]} dot>
                  {t(JOB_STATUS_LABEL_KEY[job.status])}
                </Badge>
                <Badge variant="outline">{t(JOB_KIND_LABEL_KEY[job.kind])}</Badge>
                {job.priority === "urgent" && (
                  <Badge variant="destructive">
                    <AlertTriangle className="h-3 w-3" />
                    {t(JOB_PRIORITY_LABEL_KEY.urgent)}
                  </Badge>
                )}
                {job.stops_machine && (
                  <Badge variant="warning">
                    <PowerOff className="h-3 w-3" />
                    {t("maintenance.jobs.stopsMachine")}
                  </Badge>
                )}
              </div>
            </div>

            <p
              className={cn(
                "rounded-md px-3 py-2 text-sm",
                job.status === "rework" || job.status === "cancelled" ? "bg-destructive-soft text-destructive" : "bg-muted text-foreground",
              )}
            >
              {statusLine(job, t)}
            </p>

            {job.description && <p className="whitespace-pre-wrap break-words text-sm">{job.description}</p>}

            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 lg:grid-cols-6">
              <Fact label={t("maintenance.jobs.column.dueDate")}>
                <span className={cn(job.overdue && "text-destructive")}>
                  {formatDay(job.due_date)}
                  {job.overdue && <span className="block text-xs font-normal">{t("maintenance.jobs.overdue")}</span>}
                </span>
              </Fact>
              <Fact label={t("maintenance.jobs.field.chef")}>{job.chef_name ?? "—"}</Fact>
              <Fact label={t("maintenance.jobs.field.team")}>{job.team_name ?? "—"}</Fact>
              <Fact label={t("maintenance.jobs.column.progress")}>
                <span className="tabular-nums">
                  {job.checks_done}/{job.checks_total}
                </span>
                <span className="mt-1 block h-1.5 w-full max-w-[8rem] overflow-hidden rounded-full bg-muted" aria-hidden>
                  <span className="block h-full rounded-full bg-primary" style={{ width: `${progress}%` }} />
                </span>
              </Fact>
              <Fact label={t("maintenance.jobs.column.minutes")}>{formatDuration(job.minutes_spent)}</Fact>
              <Fact label={t("maintenance.jobs.createdBy")}>
                {job.created_by_name}
                <span className="block text-xs font-normal text-muted-foreground">{formatDay(job.created_at)}</span>
              </Fact>
            </dl>

            {(hasActions || notTheChef) && (
              <div className="space-y-2 border-t border-border pt-4">
                <div className="flex flex-wrap gap-2">
                  {showRun && (
                    <Button asChild variant={pendingCount > 0 ? "default" : "outline"} className="h-11 sm:h-9">
                      <Link to={`/maintenance/jobs/${job.id}/run`}>
                        <Play className="h-4 w-4" />
                        {t("maintenance.jobs.action.wizard")}
                      </Link>
                    </Button>
                  )}
                  {showSubmit && (
                    <Button
                      variant={pendingCount > 0 ? "outline" : "default"}
                      className="h-11 sm:h-9"
                      onClick={handleSubmit}
                      disabled={pendingCount > 0 || submit.isPending}
                    >
                      <Send className="h-4 w-4" />
                      {submit.isPending ? t("maintenance.jobs.action.submitting") : t("maintenance.jobs.action.submit")}
                    </Button>
                  )}
                  {showRun && (
                    <Button variant="outline" className="h-11 sm:h-9" onClick={() => setDelegateOpen(true)}>
                      <Users className="h-4 w-4" />
                      {t("maintenance.jobs.action.delegate")}
                    </Button>
                  )}
                  {showAssign && (
                    <Button
                      variant={job.status === "planned" ? "default" : "outline"}
                      className="h-11 sm:h-9"
                      onClick={() => setAssignOpen(true)}
                    >
                      <UserCheck className="h-4 w-4" />
                      {job.status === "planned" ? t("maintenance.jobs.action.assign") : t("maintenance.jobs.action.reassign")}
                    </Button>
                  )}
                  {showClose && (
                    <Button
                      variant={allAccepted ? "default" : "outline"}
                      className="h-11 sm:h-9"
                      onClick={handleClose}
                      disabled={!allAccepted || close.isPending}
                    >
                      <Lock className="h-4 w-4" />
                      {close.isPending ? t("maintenance.jobs.action.closing") : t("maintenance.jobs.action.close")}
                    </Button>
                  )}
                  {showCancel && (
                    <Button
                      variant="ghost"
                      className="h-11 text-destructive hover:bg-destructive-soft sm:ml-auto sm:h-9"
                      onClick={() => setCancelOpen(true)}
                    >
                      <Ban className="h-4 w-4" />
                      {t("maintenance.jobs.action.cancel")}
                    </Button>
                  )}
                </div>
                {showSubmit && pendingCount > 0 && (
                  <p className="text-xs text-muted-foreground">
                    {t("maintenance.jobs.submit.blocked").replace("{count}", String(pendingCount))}
                  </p>
                )}
                {showClose && !allAccepted && <p className="text-xs text-muted-foreground">{t("maintenance.jobs.close.blocked")}</p>}
                {notTheChef && (
                  <p className="text-xs text-muted-foreground">
                    {t("maintenance.jobs.notTheChef").replace("{chef}", job.chef_name ?? "—")}
                  </p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </motion.div>

      {canPlan && job.status === "submitted" && <ReviewPanel job={job} onClose={handleClose} isClosing={close.isPending} />}

      <Card>
        <CardHeader>
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2">
              <ListChecks className="h-4 w-4 text-muted-foreground" />
              {t("maintenance.jobs.checks.title")}
            </CardTitle>
            <CardDescription>{t("maintenance.jobs.checks.description")}</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="p-3 md:p-0">
          <JobChecks job={job} highlightedCheckId={highlightedCheckId} onSelect={setHighlightedCheckId} />
        </CardContent>
      </Card>

      {job.checks.some((check) => check.view_id !== null) && (
        <Card>
          <CardHeader>
            <div className="min-w-0">
              <CardTitle className="flex items-center gap-2">
                <Images className="h-4 w-4 text-muted-foreground" />
                {t("maintenance.jobs.views.title")}
              </CardTitle>
              <CardDescription>{t("maintenance.jobs.views.description")}</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <JobViewsStrip job={job} highlightedCheckId={highlightedCheckId} onPinClick={handlePinClick} />
          </CardContent>
        </Card>
      )}

      <JobPartRequests
        job={job}
        action={
          showRun ? (
            <Button variant="outline" size="sm" onClick={() => setPartRequestOpen(true)}>
              <PackagePlus className="h-3.5 w-3.5" />
              {t("maintenance.jobs.action.requestParts")}
            </Button>
          ) : undefined
        }
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <History className="h-4 w-4 text-muted-foreground" />
            {t("maintenance.jobs.timeline.title")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <JobTimeline events={job.timeline} />
        </CardContent>
      </Card>

      <AssignDialog job={job} open={assignOpen} onOpenChange={setAssignOpen} />
      <DelegateDialog job={job} open={delegateOpen} onOpenChange={setDelegateOpen} />
      <CancelDialog job={job} open={cancelOpen} onOpenChange={setCancelOpen} />
      <PartRequestDialog job={job} open={partRequestOpen} onOpenChange={setPartRequestOpen} />
    </div>
  );
}
