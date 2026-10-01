import { useEffect, useState } from "react";
import { Check, CheckCheck, ClipboardCheck, Lock, RotateCcw, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { useReviewJob, type JobDetail, type ReviewVerdict } from "../api";
import { CHECK_ACTION_ICON, CHECK_ACTION_LABEL_KEY } from "../labels";
import { CheckHistory } from "./CheckHistory";
import { apiErrorMessage } from "./jobFormat";

const TEXTAREA_CLASS =
  "flex w-full rounded-md border border-border bg-background px-3 py-1.5 text-base shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm";

interface Draft {
  verdict: ReviewVerdict["verdict"] | null;
  reason: string;
}

const EMPTY_DRAFT: Draft = { verdict: null, reason: "" };

/**
 * Supervisor review of a submitted job (`maintenance.plan_jobs`): one verdict
 * per point awaiting review, a reason being mandatory to reject. Posting sends
 * every verdict at once — the API wants exactly one per `done` point. Any
 * rejection sends the job back to rework (only the rejected points reopen);
 * with none, the job stays submitted and can be closed.
 */
export function ReviewPanel({
  job,
  onClose,
  isClosing,
}: {
  job: JobDetail;
  /** Closes the job (the job page owns the mutation, shared with its action bar). */
  onClose: () => void;
  isClosing: boolean;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const review = useReviewJob(token);

  const toReview = job.checks.filter((check) => check.state === "done");
  const allAccepted = job.checks.length > 0 && job.checks.every((check) => check.state === "accepted");

  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [showMissing, setShowMissing] = useState(false);

  // A new round of review (after a rework and a re-submit) starts from a blank sheet.
  useEffect(() => {
    setDrafts({});
    setShowMissing(false);
  }, [job.id, job.submitted_at]);

  const draftOf = (checkId: string) => drafts[checkId] ?? EMPTY_DRAFT;
  const setDraft = (checkId: string, patch: Partial<Draft>) =>
    setDrafts((current) => ({ ...current, [checkId]: { ...(current[checkId] ?? EMPTY_DRAFT), ...patch } }));

  const acceptedCount = toReview.filter((check) => draftOf(check.id).verdict === "accepted").length;
  const rejectedCount = toReview.filter((check) => draftOf(check.id).verdict === "rejected").length;
  const undecidedCount = toReview.length - acceptedCount - rejectedCount;
  const missingReason = toReview.some((check) => {
    const draft = draftOf(check.id);
    return draft.verdict === "rejected" && !draft.reason.trim();
  });
  const complete = undecidedCount === 0 && !missingReason;

  function acceptAll() {
    setDrafts((current) => {
      const next = { ...current };
      for (const check of toReview) {
        // A point already rejected keeps its verdict and reason: "accept all" fills in the blanks.
        if ((next[check.id] ?? EMPTY_DRAFT).verdict === null) next[check.id] = { verdict: "accepted", reason: "" };
      }
      return next;
    });
  }

  function submit() {
    if (!complete) {
      setShowMissing(true);
      return;
    }
    const verdicts: ReviewVerdict[] = toReview.map((check) => {
      const draft = draftOf(check.id);
      return draft.verdict === "rejected"
        ? { check_id: check.id, verdict: "rejected", reason: draft.reason.trim() }
        : { check_id: check.id, verdict: "accepted" };
    });
    review.mutate(
      { jobId: job.id, verdicts },
      {
        onSuccess: (updated) => {
          toast.success(updated.status === "rework" ? t("maintenance.jobs.review.sentBack") : t("maintenance.jobs.review.validated"));
        },
      },
    );
  }

  if (toReview.length === 0) {
    // Every verdict is in. All accepted -> the only thing left is to close.
    if (!allAccepted) return null;
    return (
      <Card className="border-success/30">
        <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-success-soft text-success">
              <CheckCheck className="h-4 w-4" />
            </span>
            <div>
              <p className="text-sm font-medium">{t("maintenance.jobs.review.allAccepted.title")}</p>
              <p className="text-sm text-muted-foreground">{t("maintenance.jobs.review.allAccepted.description")}</p>
            </div>
          </div>
          <Button onClick={onClose} disabled={isClosing} className="sm:shrink-0">
            <Lock className="h-4 w-4" />
            {isClosing ? t("maintenance.jobs.action.closing") : t("maintenance.jobs.action.close")}
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-warning/40">
      <CardHeader>
        <div className="min-w-0">
          <CardTitle className="flex items-center gap-2">
            <ClipboardCheck className="h-4 w-4 text-warning" />
            {t("maintenance.jobs.review.title")}
          </CardTitle>
          <CardDescription>{t("maintenance.jobs.review.description")}</CardDescription>
        </div>
        <Button size="sm" variant="outline" onClick={acceptAll}>
          <CheckCheck className="h-3.5 w-3.5" />
          {t("maintenance.jobs.review.acceptAll")}
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {toReview.map((check) => {
          const Icon = CHECK_ACTION_ICON[check.action];
          const draft = draftOf(check.id);
          const number = job.checks.findIndex((entry) => entry.id === check.id) + 1;
          const reasonMissing = draft.verdict === "rejected" && !draft.reason.trim();
          return (
            <div
              key={check.id}
              className={cn(
                "space-y-3 rounded-lg border p-3 sm:p-4",
                draft.verdict === "accepted" && "border-success/40 bg-success-soft/40",
                draft.verdict === "rejected" && "border-destructive/40 bg-destructive-soft/40",
                draft.verdict === null && (showMissing ? "border-warning" : "border-border"),
              )}
            >
              <div className="flex items-start gap-2">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
                  {number}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-1.5 text-sm font-medium">
                    <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                    <span className="min-w-0 break-words">{check.label}</span>
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {t(CHECK_ACTION_LABEL_KEY[check.action])}
                    {check.attempt > 1 ? ` · ${t("maintenance.jobs.attempt").replace("{n}", String(check.attempt))}` : ""}
                    {check.requires_photo ? ` · ${t("maintenance.jobs.photo.required")}` : ""}
                  </p>
                  {check.instructions && <p className="mt-1 whitespace-pre-wrap break-words text-xs text-muted-foreground">{check.instructions}</p>}
                </div>
              </div>

              <CheckHistory check={check} />

              <div className="grid grid-cols-2 gap-2">
                <Button
                  type="button"
                  variant={draft.verdict === "accepted" ? "default" : "outline"}
                  className={cn("h-11", draft.verdict === "accepted" && "bg-success text-success-foreground hover:bg-success/90")}
                  aria-pressed={draft.verdict === "accepted"}
                  onClick={() => setDraft(check.id, { verdict: "accepted" })}
                >
                  <Check className="h-4 w-4" />
                  {t("maintenance.jobs.review.accept")}
                </Button>
                <Button
                  type="button"
                  variant={draft.verdict === "rejected" ? "destructive" : "outline"}
                  className="h-11"
                  aria-pressed={draft.verdict === "rejected"}
                  onClick={() => setDraft(check.id, { verdict: "rejected" })}
                >
                  <X className="h-4 w-4" />
                  {t("maintenance.jobs.review.reject")}
                </Button>
              </div>

              {draft.verdict === "rejected" && (
                <div className="space-y-1">
                  <textarea
                    rows={2}
                    autoFocus
                    aria-label={t("maintenance.jobs.review.reason")}
                    aria-invalid={reasonMissing && showMissing ? true : undefined}
                    placeholder={t("maintenance.jobs.review.reason.placeholder")}
                    value={draft.reason}
                    onChange={(event) => setDraft(check.id, { reason: event.target.value })}
                    className={cn(TEXTAREA_CLASS, reasonMissing && showMissing && "border-destructive focus-visible:ring-destructive")}
                  />
                  {reasonMissing && showMissing && <p className="text-sm text-destructive">{t("maintenance.jobs.review.reason.required")}</p>}
                </div>
              )}
            </div>
          );
        })}

        <div className="sticky bottom-0 -mx-5 -mb-5 space-y-2 rounded-b-xl border-t border-border bg-background/95 px-5 py-3 backdrop-blur-sm">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-muted-foreground">
              {t("maintenance.jobs.review.summary")
                .replace("{accepted}", String(acceptedCount))
                .replace("{rejected}", String(rejectedCount))
                .replace("{remaining}", String(undecidedCount))}
            </p>
            <Button
              onClick={submit}
              disabled={review.isPending}
              variant={rejectedCount > 0 ? "destructive" : "default"}
              className="h-11 sm:h-9 sm:shrink-0"
            >
              {rejectedCount > 0 ? <RotateCcw className="h-4 w-4" /> : <ClipboardCheck className="h-4 w-4" />}
              {review.isPending
                ? t("maintenance.jobs.review.submitting")
                : rejectedCount > 0
                  ? t("maintenance.jobs.review.sendBack")
                  : t("maintenance.jobs.review.validate")}
            </Button>
          </div>
          {showMissing && !complete && (
            <p className="text-sm text-destructive" role="alert">
              {undecidedCount > 0 ? t("maintenance.jobs.review.incomplete") : t("maintenance.jobs.review.reason.required")}
            </p>
          )}
          {review.isError && (
            <p className="text-sm text-destructive" role="alert">
              {apiErrorMessage(review.error, t("maintenance.jobs.review.error"))}
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
