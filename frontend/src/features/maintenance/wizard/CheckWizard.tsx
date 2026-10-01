import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, ArrowLeft, Check, ChevronLeft, ChevronRight, ListChecks, Loader2, Lock, Send } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import {
  MAINTENANCE_TEAM_CANDIDATES_QUERY_KEY,
  listTeamCandidates,
  maintenanceJobKey,
  useAddCheckEntry,
  useEquipmentViews,
  useJob,
  useSubmitJob,
  useTeams,
  type AddCheckEntryInput,
  type JobCheck,
  type JobDetail,
  type Person,
} from "../api";
import { useHasPermission } from "../hooks";
import { JOB_STATUS_LABEL_KEY } from "../labels";
import type { Pin } from "../map/PinnedPhoto";
import { WORKABLE_STATUSES, apiErrorMessage, latestEntry } from "../jobs/jobFormat";
import { TimerActionButton, useWizardTimers } from "./StepTimer";
import { WizardStep, fieldId } from "./WizardStep";
import { WizardSummary } from "./WizardSummary";
import { PartRequestDialog } from "../parts/PartRequestDialog";
import {
  DRAFT_FIELDS,
  EMPTY_DRAFT,
  currentEntry,
  draftHasInput,
  isRecorded,
  nextPendingIndex,
  parseDecimal,
  timerPhase,
  validateDraft,
  wizardStepIds,
  type DraftField,
  type StepDraft,
} from "./wizardModel";

const SUMMARY = "summary";
const LAST_PERFORMER_KEY = "sonalim-erp.maintenance.last-performer";

function readLastPerformer(): string | null {
  try {
    return localStorage.getItem(LAST_PERFORMER_KEY);
  } catch {
    return null;
  }
}

function rememberPerformer(employeeId: string) {
  try {
    localStorage.setItem(LAST_PERFORMER_KEY, employeeId);
  } catch {
    // Storage blocked: the next point simply won't pre-select this person.
  }
}

const jobPath = (jobId: string) => `/maintenance/jobs/${jobId}`;

// Bottom bar: icon-only arrows on a phone (the primary action gets the width), labelled from `sm`.
const NAV_BUTTON = "h-14 w-14 shrink-0 px-0 text-base sm:h-14 sm:w-auto sm:px-4";
const PRIMARY_BUTTON = "h-14 min-w-0 flex-1 rounded-xl text-base font-semibold sm:h-14";

const SLIDE = {
  enter: (direction: number) => ({ x: direction * 48, opacity: 0 }),
  center: { x: 0, opacity: 1 },
  exit: (direction: number) => ({ x: direction * -48, opacity: 0 }),
};

/** A plain full-screen message in the wizard's frame (not found, not allowed, nothing left to record). */
function WizardMessage({ backTo, title, description }: { backTo: string; title: string; description: string }) {
  const { t } = useI18n();
  return (
    <div className="flex h-[100dvh] flex-col bg-muted/40">
      <header className="shrink-0 bg-primary pt-[env(safe-area-inset-top)] text-primary-foreground shadow-raised">
        <div className="mx-auto flex max-w-2xl items-center gap-2 px-2 py-2 sm:px-4">
          <Link
            to={backTo}
            aria-label={t("maintenance.wizard.back")}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition-colors hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
          >
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <p className="truncate text-base font-semibold">{t("maintenance.wizard.title")}</p>
        </div>
      </header>
      <main className="flex min-h-0 flex-1 items-center justify-center p-4">
        <div className="w-full max-w-md space-y-4 rounded-xl border border-border bg-background p-6 text-center shadow-soft">
          <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-warning-soft text-warning">
            <Lock className="h-6 w-6" />
          </span>
          <div className="space-y-1">
            <p className="text-base font-semibold">{title}</p>
            <p className="text-sm text-muted-foreground">{description}</p>
          </div>
          <Button asChild className="h-12 w-full text-base">
            <Link to={backTo}>
              <ArrowLeft className="h-4 w-4" />
              {t("maintenance.wizard.back")}
            </Link>
          </Button>
        </div>
      </main>
    </div>
  );
}

/** Shown for a moment after "Soumettre pour validation", then back to the job page. */
function SubmittedScreen({ jobId }: { jobId: string }) {
  const { t } = useI18n();
  const navigate = useNavigate();

  useEffect(() => {
    const handle = window.setTimeout(() => {
      toast.success(t("maintenance.jobs.submit.done"));
      navigate(jobPath(jobId), { replace: true });
    }, 1600);
    return () => window.clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  return (
    <div className="flex h-[100dvh] flex-col items-center justify-center gap-5 bg-primary px-6 text-center text-primary-foreground">
      <motion.div
        initial={{ scale: 0.6, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: "spring", stiffness: 260, damping: 18 }}
        className="flex h-28 w-28 items-center justify-center rounded-full bg-white/10"
      >
        <svg viewBox="0 0 64 64" className="h-24 w-24" fill="none" aria-hidden>
          <motion.circle
            cx="32"
            cy="32"
            r="27"
            stroke="#34d399"
            strokeWidth="4"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 0.5, ease: "easeOut" }}
          />
          <motion.path
            d="m20 33 8 8 17-18"
            stroke="#34d399"
            strokeWidth="5"
            strokeLinecap="round"
            strokeLinejoin="round"
            initial={{ pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ delay: 0.4, duration: 0.35, ease: "easeOut" }}
          />
        </svg>
      </motion.div>
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }} className="space-y-1">
        <p className="text-xl font-semibold">{t("maintenance.jobs.submit.done")}</p>
        <p className="text-sm text-primary-foreground/75">{t("maintenance.wizard.submitted.hint")}</p>
      </motion.div>
    </div>
  );
}

/**
 * The guided check (`/maintenance/jobs/:jobId/run`), full screen and phone-first: one point at a
 * time — where it is on the machine, what to do, who does it, the timer, the outcome and its
 * proof — then a summary and "Soumettre pour validation". Rendered outside the sidebar layout.
 *
 * Who may run it mirrors the API: `maintenance.execute_jobs` AND (the job's chef OR `plan_jobs`),
 * on a job that is assigned, in progress or in rework. Anything else gets a plain message.
 */
export function CheckWizard() {
  const { jobId = "" } = useParams<{ jobId: string }>();
  const { session } = useAuth();
  const { t } = useI18n();
  const canPlan = useHasPermission("maintenance.plan_jobs");
  const canExecute = useHasPermission("maintenance.execute_jobs");
  const { data: job, isLoading, error } = useJob(session!.token, jobId || null);
  const [submitted, setSubmitted] = useState(false);

  if (submitted) return <SubmittedScreen jobId={jobId} />;

  if (isLoading) {
    return (
      <div className="flex h-[100dvh] items-center justify-center bg-background">
        <AppLoader />
      </div>
    );
  }

  if (!job) {
    return (
      <WizardMessage
        backTo="/maintenance?tab=jobs"
        title={t("maintenance.jobs.notFound.title")}
        description={apiErrorMessage(error, t("maintenance.jobs.notFound.description"))}
      />
    );
  }

  const isChef = !!job.chef_user_id && job.chef_user_id === session!.userId;
  if (!canExecute) {
    return (
      <WizardMessage
        backTo={jobPath(job.id)}
        title={t("maintenance.wizard.blocked.title")}
        description={t("maintenance.wizard.blocked.noPermission")}
      />
    );
  }
  if (!isChef && !canPlan) {
    return (
      <WizardMessage
        backTo={jobPath(job.id)}
        title={t("maintenance.wizard.blocked.title")}
        description={t("maintenance.jobs.notTheChef").replace("{chef}", job.chef_name ?? "—")}
      />
    );
  }
  if (!WORKABLE_STATUSES.includes(job.status)) {
    return (
      <WizardMessage
        backTo={jobPath(job.id)}
        title={t("maintenance.wizard.blocked.title")}
        description={t("maintenance.wizard.blocked.status").replace("{status}", t(JOB_STATUS_LABEL_KEY[job.status]))}
      />
    );
  }

  return <WizardRun key={job.id} job={job} onSubmitted={() => setSubmitted(true)} />;
}

function WizardRun({ job, onSubmitted }: { job: JobDetail; onSubmitted: () => void }) {
  const { session } = useAuth();
  const token = session!.token;
  const { t } = useI18n();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const mainRef = useRef<HTMLElement>(null);

  // The points walked are fixed when the wizard opens, so a point keeps its place ("Point 3 / 12")
  // after it is recorded and Précédent can still reach it.
  const [stepIds] = useState(() => wizardStepIds(job));
  const steps = useMemo(
    () => stepIds.map((id) => job.checks.find((check) => check.id === id)).filter((check): check is JobCheck => !!check),
    [stepIds, job.checks],
  );
  const numbers = useMemo(() => new Map(job.checks.map((check, index) => [check.id, index + 1])), [job.checks]);

  const timers = useWizardTimers(job.id);
  const [drafts, setDrafts] = useState<Record<string, StepDraft>>({});
  const [attempted, setAttempted] = useState<Set<string>>(() => new Set());
  const [direction, setDirection] = useState(1);
  const [savedFlash, setSavedFlash] = useState<{ n: number; key: number } | null>(null);
  const [leaveOpen, setLeaveOpen] = useState(false);
  // The check whose spare parts fill the open parts request; null when it is closed.
  const [partsCheck, setPartsCheck] = useState<JobDetail["checks"][number] | null>(null);
  const [showEveryone, setShowEveryone] = useState(false);
  const [lastPerformer, setLastPerformer] = useState<string | null>(() => readLastPerformer());

  const addEntry = useAddCheckEntry(token);
  const submit = useSubmitJob(token);

  // --- where we are --------------------------------------------------------
  const point = searchParams.get("point");
  const pointIndex = point && point !== SUMMARY ? steps.findIndex((check) => check.id === point) : -1;
  // Opening (or a stale link): the first point still to record, else the summary.
  const defaultIndex = steps.findIndex((check) => !isRecorded(check));
  const onSummary = point === SUMMARY || (pointIndex === -1 && defaultIndex === -1);
  const index = onSummary ? -1 : pointIndex !== -1 ? pointIndex : defaultIndex;
  const current = index >= 0 ? steps[index] : null;
  const positionKey = current?.id ?? SUMMARY;

  function goTo(target: string, nextDirection: number) {
    setDirection(nextDirection);
    addEntry.reset();
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.set("point", target);
        return next;
      },
      { replace: true },
    );
  }

  useEffect(() => {
    mainRef.current?.scrollTo({ top: 0 });
  }, [positionKey]);

  useEffect(() => {
    if (!savedFlash) return;
    const handle = window.setTimeout(() => setSavedFlash(null), 1800);
    return () => window.clearTimeout(handle);
  }, [savedFlash]);

  // --- machine photos ------------------------------------------------------
  const { data: views = [], isLoading: viewsLoading } = useEquipmentViews(token, job.equipment_id);
  const viewVersion = current?.view_id ? (views.find((view) => view.id === current.view_id)?.updated_at ?? null) : null;
  const pins: Pin[] = useMemo(() => {
    if (!current?.view_id) return [];
    return job.checks
      .filter((check) => check.view_id === current.view_id && check.x_pct !== null && check.y_pct !== null)
      .map((check) => ({
        id: check.id,
        x: check.x_pct ?? 0,
        y: check.y_pct ?? 0,
        n: numbers.get(check.id) ?? 0,
        tone: check.id === current.id ? "active" : isRecorded(check) ? "done" : "dim",
      }));
  }, [current, job.checks, numbers]);

  // --- performers: the job's team, else every active employee ---------------
  const { data: teams = [], isLoading: teamsLoading } = useTeams(token);
  const teamMembers = useMemo<Person[]>(() => {
    const team = job.team_id ? teams.find((entry) => entry.id === job.team_id) : undefined;
    return team ? team.members.map((member) => ({ id: member.employee_id, name: member.name })) : [];
  }, [teams, job.team_id]);
  const listEveryone = showEveryone || (!teamsLoading && teamMembers.length === 0);
  const { data: candidates = [], isLoading: candidatesLoading } = useQuery({
    queryKey: MAINTENANCE_TEAM_CANDIDATES_QUERY_KEY,
    queryFn: () => listTeamCandidates(token),
    enabled: !!token && listEveryone,
  });
  const performerOptions = useMemo<Person[]>(() => {
    const known = new Map((listEveryone ? candidates : teamMembers).map((person) => [person.id, person]));
    // Whoever holds or already did a point stays selectable, even from outside the list.
    for (const check of job.checks) {
      if (check.assignee_employee_id && check.assignee_name && !known.has(check.assignee_employee_id)) {
        known.set(check.assignee_employee_id, { id: check.assignee_employee_id, name: check.assignee_name });
      }
      for (const entry of check.entries) {
        if (!known.has(entry.performer_employee_id)) known.set(entry.performer_employee_id, { id: entry.performer_employee_id, name: entry.performer_name });
      }
    }
    return [...known.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [listEveryone, candidates, teamMembers, job.checks]);
  const performersLoading = teamsLoading || (listEveryone && candidatesLoading);

  function defaultPerformer(check: JobCheck): string {
    if (check.assignee_employee_id) return check.assignee_employee_id;
    const known = new Set(performerOptions.map((person) => person.id));
    // "Refaire" / a rework: whoever did this point last.
    const previous = latestEntry(check);
    if (previous && known.has(previous.performer_employee_id)) return previous.performer_employee_id;
    if (lastPerformer && known.has(lastPerformer)) return lastPerformer;
    return "";
  }

  // --- drafts ----------------------------------------------------------------
  const draftOf = (checkId: string) => drafts[checkId] ?? EMPTY_DRAFT;
  function patchDraft(checkId: string, patch: Partial<StepDraft>) {
    setDrafts((all) => ({ ...all, [checkId]: { ...(all[checkId] ?? EMPTY_DRAFT), ...patch } }));
  }
  function dropDraft(checkId: string) {
    setDrafts((all) => {
      const next = { ...all };
      delete next[checkId];
      return next;
    });
    setAttempted((all) => {
      const next = new Set(all);
      next.delete(checkId);
      return next;
    });
  }

  const hasUnsaved = Object.values(drafts).some(draftHasInput);
  function leave() {
    if (hasUnsaved) setLeaveOpen(true);
    else navigate(jobPath(job.id));
  }

  // --- saving a point ----------------------------------------------------------
  function save(check: JobCheck, at: number) {
    const draft = draftOf(check.id);
    const performerId = draft.performerId ?? defaultPerformer(check);
    const timer = timers.timers[check.id] ?? null;
    const problems = validateDraft(check, draft, performerId, timer);
    const first = DRAFT_FIELDS.find((field) => problems[field]);
    if (first) {
      setAttempted((all) => new Set(all).add(check.id));
      window.requestAnimationFrame(() =>
        document.getElementById(fieldId(first))?.scrollIntoView({ behavior: "smooth", block: "center" }),
      );
      return;
    }

    const input: AddCheckEntryInput = {
      performer_employee_id: performerId,
      outcome: draft.outcome!,
      note: draft.note.trim() || null,
      measured_value: parseDecimal(draft.measure),
      photo: draft.photo,
    };
    if (draft.manual) input.manual_minutes = parseDecimal(draft.manualMinutes)!;
    else {
      // The client clock, sent with its offset (toISOString is UTC, "Z"): the API refuses a bare timestamp.
      input.started_at = new Date(timer!.startedAt).toISOString();
      input.finished_at = new Date(timer!.finishedAt!).toISOString();
    }

    addEntry.mutate(
      { jobId: job.id, checkId: check.id, input },
      {
        onSuccess: (detail) => {
          queryClient.setQueryData(maintenanceJobKey(job.id), detail);
          timers.clear(check.id);
          dropDraft(check.id);
          rememberPerformer(performerId);
          setLastPerformer(performerId);
          setSavedFlash({ n: numbers.get(check.id) ?? at + 1, key: Date.now() });
          navigator.vibrate?.(30);
          const updated = stepIds
            .map((id) => detail.checks.find((item) => item.id === id))
            .filter((item): item is JobCheck => !!item);
          const next = nextPendingIndex(updated, at);
          goTo(next === -1 ? SUMMARY : updated[next].id, 1);
        },
      },
    );
  }

  // --- render ------------------------------------------------------------------
  const recordedCount = steps.filter(isRecorded).length;
  const pendingCount = steps.length - recordedCount;
  const canSubmit = (job.status === "in_progress" || job.status === "rework") && pendingCount === 0;

  const draft = current ? draftOf(current.id) : EMPTY_DRAFT;
  const timer = current ? (timers.timers[current.id] ?? null) : null;
  const recording = current ? current.state === "pending" || draft.redo : false;
  const phase = timerPhase(draft, timer);
  const readyToSave = recording && (phase === "finished" || phase === "manual");
  const isLast = index === steps.length - 1;

  const visibleErrors: Partial<Record<DraftField, string>> = {};
  if (current && attempted.has(current.id)) {
    const problems = validateDraft(current, draft, draft.performerId ?? defaultPerformer(current), timer);
    for (const field of DRAFT_FIELDS) {
      const key = problems[field];
      if (key) visibleErrors[field] = t(key);
    }
  }
  const saveError =
    current && addEntry.isError && addEntry.variables?.checkId === current.id
      ? apiErrorMessage(addEntry.error, t("maintenance.wizard.error.save"))
      : null;

  // The API's refusal, in the user's language, kept in the sticky bar so it is never below the fold.
  const footerError = onSummary
    ? submit.isError
      ? apiErrorMessage(submit.error, t("maintenance.jobs.submit.error"))
      : null
    : saveError;

  function segmentClass(check: JobCheck, position: number): string {
    if (position === index) return "bg-accent";
    if (!isRecorded(check)) return "bg-white/20";
    const outcome = currentEntry(check)?.outcome;
    if (outcome === "issue") return "bg-red-400";
    if (outcome === "not_done") return "bg-white/55";
    return "bg-emerald-400";
  }

  return (
    <div className="flex h-[100dvh] flex-col bg-muted/40">
      <header className="relative z-10 shrink-0 bg-primary pt-[env(safe-area-inset-top)] text-primary-foreground shadow-raised">
        <div className="mx-auto flex max-w-2xl items-center gap-1 px-2 pt-2 sm:px-4">
          <button
            type="button"
            onClick={leave}
            aria-label={t("maintenance.wizard.back")}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition-colors hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
          >
            <ArrowLeft className="h-5 w-5" />
          </button>
          <div className="min-w-0 flex-1 px-1">
            <p className="truncate text-xs text-primary-foreground/70">
              <span className="font-mono">{job.number}</span> · {job.equipment_name}
            </p>
            <p className="truncate text-[15px] font-semibold leading-tight">{job.title}</p>
          </div>
          {onSummary ? (
            <span className="flex min-h-11 shrink-0 items-center gap-1.5 rounded-full px-3 text-sm font-semibold">
              <ListChecks className="h-4 w-4" />
              {t("maintenance.wizard.summaryTitle")}
            </span>
          ) : (
            <button
              type="button"
              onClick={() => goTo(SUMMARY, 1)}
              aria-label={t("maintenance.wizard.openSummary")}
              className="flex min-h-11 shrink-0 items-center gap-1.5 rounded-full bg-white/10 px-3 text-sm font-semibold tabular-nums transition-colors hover:bg-white/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
            >
              {t("maintenance.wizard.pointOf").replace("{n}", String(index + 1)).replace("{total}", String(steps.length))}
              <ListChecks className="h-4 w-4 opacity-80" />
            </button>
          )}
        </div>
        <div className="mx-auto max-w-2xl px-4 pb-3 pt-2">
          <div
            className="flex items-center gap-1"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={steps.length}
            aria-valuenow={recordedCount}
            aria-label={t("maintenance.wizard.progress").replace("{done}", String(recordedCount)).replace("{total}", String(steps.length))}
          >
            {steps.map((check, position) => (
              <span
                key={check.id}
                className={cn("block flex-1 rounded-full transition-all duration-300", position === index ? "h-2" : "h-1.5", segmentClass(check, position))}
              />
            ))}
          </div>
        </div>
        <AnimatePresence>
          {savedFlash && (
            <motion.div
              key={savedFlash.key}
              initial={{ opacity: 0, y: -8, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.2 }}
              className="pointer-events-none absolute left-1/2 top-full mt-2 flex -translate-x-1/2 items-center gap-1.5 whitespace-nowrap rounded-full bg-success px-4 py-2 text-sm font-semibold text-success-foreground shadow-raised"
              role="status"
            >
              <Check className="h-4 w-4" />
              {t("maintenance.wizard.saved").replace("{n}", String(savedFlash.n))}
            </motion.div>
          )}
        </AnimatePresence>
      </header>

      <main ref={mainRef} className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden overscroll-contain">
        <AnimatePresence mode="wait" custom={direction} initial={false}>
          <motion.div
            key={positionKey}
            custom={direction}
            variants={SLIDE}
            initial="enter"
            animate="center"
            exit="exit"
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="mx-auto max-w-2xl px-4 pb-8 pt-4"
          >
            {current ? (
              <WizardStep
                check={current}
                equipmentName={job.equipment_name}
                number={numbers.get(current.id) ?? index + 1}
                pins={pins}
                viewsReady={!viewsLoading}
                viewVersion={viewVersion}
                onPinClick={(checkId) => {
                  const target = steps.findIndex((check) => check.id === checkId);
                  if (target !== -1 && target !== index) goTo(checkId, target > index ? 1 : -1);
                }}
                draft={draft}
                performerId={draft.performerId ?? defaultPerformer(current)}
                performerOptions={performerOptions}
                performersLoading={performersLoading}
                showEveryone={showEveryone}
                canShowEveryone={teamMembers.length > 0}
                onShowEveryoneChange={setShowEveryone}
                timer={timer}
                errors={visibleErrors}
                saving={addEntry.isPending}
                onDraftChange={(patch) => patchDraft(current.id, patch)}
                onResetTimer={() => timers.clear(current.id)}
                onRedo={() => patchDraft(current.id, { redo: true })}
                onCancelRedo={() => {
                  dropDraft(current.id);
                  timers.clear(current.id);
                }}
                onRequestParts={() => setPartsCheck(current)}
              />
            ) : (
              <WizardSummary
                job={job}
                steps={steps}
                numbers={numbers}
                timers={timers.timers}
                onOpenStep={(target) => goTo(steps[target].id, -1)}
              />
            )}
          </motion.div>
        </AnimatePresence>
      </main>

      <footer className="shrink-0 border-t border-border bg-background/95 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 shadow-[0_-6px_16px_-10px_hsl(215_35%_16%/0.25)] backdrop-blur">
        <div className="mx-auto max-w-2xl space-y-2 px-4">
          <AnimatePresence initial={false}>
            {footerError && (
              <motion.p
                key={footerError}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                role="alert"
                className="flex items-start gap-2 rounded-lg bg-destructive-soft px-3 py-2 text-sm font-medium text-destructive"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span className="min-w-0 break-words">{footerError}</span>
              </motion.p>
            )}
          </AnimatePresence>
          {onSummary && pendingCount > 0 && (
            <p className="flex items-center justify-center gap-1.5 text-center text-sm text-muted-foreground">
              <AlertTriangle className="h-4 w-4 shrink-0 text-warning" />
              {t("maintenance.jobs.submit.blocked").replace("{count}", String(pendingCount))}
            </p>
          )}
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              className={NAV_BUTTON}
              aria-label={t("maintenance.wizard.previous")}
              disabled={(!onSummary && index <= 0) || steps.length === 0 || addEntry.isPending || submit.isPending}
              onClick={() => (onSummary ? goTo(steps[steps.length - 1].id, -1) : goTo(steps[index - 1].id, -1))}
            >
              <ChevronLeft className="h-6 w-6" />
              <span className="hidden sm:inline">{t("maintenance.wizard.previous")}</span>
            </Button>

            {onSummary ? (
              <Button
                className={PRIMARY_BUTTON}
                disabled={!canSubmit || submit.isPending}
                onClick={() =>
                  submit.mutate(job.id, {
                    onSuccess: () => {
                      timers.clearAll();
                      onSubmitted();
                    },
                  })
                }
              >
                {submit.isPending ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
                <span className="truncate">
                  {submit.isPending ? t("maintenance.jobs.action.submitting") : t("maintenance.wizard.submit")}
                </span>
              </Button>
            ) : current && recording && (phase === "idle" || phase === "running") ? (
              <TimerActionButton
                phase={phase}
                timer={timer}
                disabled={addEntry.isPending}
                onStart={() => {
                  navigator.vibrate?.(30);
                  timers.start(current.id);
                  document.getElementById(fieldId("timing"))?.scrollIntoView({ behavior: "smooth", block: "center" });
                }}
                onFinish={() => {
                  navigator.vibrate?.(30);
                  timers.finish(current.id);
                }}
              />
            ) : readyToSave ? (
              <Button className={PRIMARY_BUTTON} disabled={addEntry.isPending} onClick={() => current && save(current, index)}>
                {addEntry.isPending ? <Loader2 className="h-5 w-5 animate-spin" /> : <Check className="h-5 w-5" />}
                <span className="truncate">{addEntry.isPending ? t("maintenance.wizard.saving") : t("maintenance.wizard.saveNext")}</span>
              </Button>
            ) : (
              <Button className={PRIMARY_BUTTON} onClick={() => goTo(isLast ? SUMMARY : steps[index + 1].id, 1)}>
                <span className="truncate">{isLast ? t("maintenance.wizard.toSummary") : t("maintenance.wizard.next")}</span>
                <ChevronRight className="h-5 w-5" />
              </Button>
            )}

            {current && recording && (
              // Leave this point for later without recording it.
              <Button
                variant="outline"
                className={NAV_BUTTON}
                aria-label={isLast ? t("maintenance.wizard.toSummary") : t("maintenance.wizard.next")}
                disabled={addEntry.isPending}
                onClick={() => goTo(isLast ? SUMMARY : steps[index + 1].id, 1)}
              >
                <span className="hidden sm:inline">{isLast ? t("maintenance.wizard.toSummary") : t("maintenance.wizard.next")}</span>
                <ChevronRight className="h-6 w-6" />
              </Button>
            )}
          </div>
        </div>
      </footer>

      <PartRequestDialog
        job={job}
        open={partsCheck !== null}
        onOpenChange={(open) => {
          if (!open) setPartsCheck(null);
        }}
        initial={
          partsCheck
            ? {
                lines: partsCheck.parts.map((part) => ({ product_id: part.product_id, quantity: part.quantity })),
                note: t("maintenance.parts.requestFromPoint.note")
                  .replace("{number}", String(numbers.get(partsCheck.id) ?? ""))
                  .replace("{label}", partsCheck.label),
              }
            : undefined
        }
      />

      <Dialog open={leaveOpen} onOpenChange={setLeaveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("maintenance.wizard.leave.title")}</DialogTitle>
            <DialogDescription>{t("maintenance.wizard.leave.description")}</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button variant="outline" className="h-12 sm:h-9" onClick={() => setLeaveOpen(false)}>
              {t("maintenance.wizard.leave.stay")}
            </Button>
            <Button variant="destructive" className="h-12 sm:h-9" onClick={() => navigate(jobPath(job.id))}>
              {t("maintenance.wizard.leave.confirm")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

