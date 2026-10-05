import { Badge } from "../../../components/ui/badge";
import { useI18n } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import type { CheckEntry, CheckReview, JobCheck } from "../api";
import { OUTCOME_BADGE_VARIANT, OUTCOME_LABEL_KEY } from "../labels";
import { EntryPhoto } from "./EntryPhoto";
import { formatClock, formatDateTime, formatDay, formatMeasure, formatTime } from "./jobFormat";

/** One recorded entry: who, when, how long, the outcome, and whatever proof came with it. */
function EntryLine({ entry, measureUnit }: { entry: CheckEntry; measureUnit: string | null }) {
  const { t } = useI18n();
  return (
    <div className="flex items-start gap-3">
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          <span className="font-medium">{entry.performer_name}</span>
          <Badge variant={OUTCOME_BADGE_VARIANT[entry.outcome]}>{t(OUTCOME_LABEL_KEY[entry.outcome])}</Badge>
          {entry.duration_source === "manual" && <Badge variant="outline">{t("maintenance.jobs.entry.manual")}</Badge>}
        </div>
        <p className="text-xs text-muted-foreground">
          {formatDay(entry.started_at)} · {formatTime(entry.started_at)} – {formatTime(entry.finished_at)} ·{" "}
          <span className="tabular-nums">{formatClock(entry.duration_seconds)}</span>
        </p>
        {entry.measured_value !== null && (
          <p className="text-sm">
            <span className="text-muted-foreground">{t("maintenance.jobs.entry.measure")} : </span>
            <span className="font-medium tabular-nums">{formatMeasure(entry.measured_value, measureUnit)}</span>
          </p>
        )}
        {entry.note && <p className="whitespace-pre-wrap break-words text-sm">{entry.note}</p>}
        {entry.recorded_by_name && (
          <p className="text-xs text-muted-foreground">
            {t("maintenance.jobs.entry.recordedBy").replace("{name}", entry.recorded_by_name)}
          </p>
        )}
      </div>
      {entry.has_photo && <EntryPhoto entryId={entry.id} className="h-16 w-16" />}
    </div>
  );
}

function ReviewLine({ review }: { review: CheckReview }) {
  const { t } = useI18n();
  const rejected = review.verdict === "rejected";
  return (
    <div className={cn("rounded-md px-3 py-2 text-sm", rejected ? "bg-destructive-soft" : "bg-success-soft")}>
      <p className={cn("font-medium", rejected ? "text-destructive" : "text-success")}>
        {rejected ? t("maintenance.jobs.review.previous.rejected") : t("maintenance.jobs.review.previous.accepted")}
        <span className="font-normal text-muted-foreground">
          {" · "}
          {review.reviewer_name} · {formatDateTime(review.created_at)}
        </span>
      </p>
      {review.reason && <p className="mt-0.5 whitespace-pre-wrap break-words">{review.reason}</p>}
    </div>
  );
}

/**
 * Everything recorded on one point, attempt by attempt (oldest first): the
 * entries of the attempt, then the verdict it received. Nothing is hidden —
 * a rework keeps every earlier attempt visible. Used by the checks table (any status)
 * and by the supervisor's review panel.
 */
export function CheckHistory({ check }: { check: JobCheck }) {
  const { t } = useI18n();
  const attempts = [...new Set([...check.entries.map((entry) => entry.attempt), ...check.reviews.map((review) => review.attempt)])].sort(
    (a, b) => a - b,
  );
  if (attempts.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("maintenance.jobs.entry.none")}</p>;
  }
  return (
    <div className="space-y-3">
      {attempts.map((attempt) => (
        <div key={attempt} className="space-y-2">
          {(attempts.length > 1 || attempt > 1) && (
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {t("maintenance.jobs.attempt").replace("{n}", String(attempt))}
            </p>
          )}
          {check.entries
            .filter((entry) => entry.attempt === attempt)
            .map((entry) => (
              <EntryLine key={entry.id} entry={entry} measureUnit={check.measure_unit} />
            ))}
          {check.reviews
            .filter((review) => review.attempt === attempt)
            .map((review) => (
              <ReviewLine key={review.id} review={review} />
            ))}
        </div>
      ))}
    </div>
  );
}
