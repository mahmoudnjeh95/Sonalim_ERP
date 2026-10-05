import { Link } from "react-router-dom";
import { MapPin } from "lucide-react";
import CheckpointNeverIllustration from "../../../assets/illustrations/maintenance/checkpoint-never.svg?react";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { Badge } from "../../../components/ui/badge";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "../../../components/ui/sheet";
import { Skeleton } from "../../../components/ui/skeleton";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import { fetchViewImageBlob } from "../api";
import { EntryPhoto } from "../jobs/EntryPhoto";
import { formatClock, formatDay, formatMeasure } from "../jobs/jobFormat";
import { CHECK_ACTION_ICON, CHECK_ACTION_LABEL_KEY, CHECK_STATE_LABEL_KEY, OUTCOME_BADGE_VARIANT, OUTCOME_LABEL_KEY } from "../labels";
import { PinnedPhoto } from "../map/PinnedPhoto";
import { useAuthedImage } from "../useAuthedImage";
import { useCheckpointHistory, type CheckpointHistory, type PointAttempt, type PointCheck } from "./api";
import { fill } from "./historyFormat";
import { MeasureTrendChart } from "./MeasureTrendChart";

function Figure({ label, value, danger = false }: { label: string; value: string; danger?: boolean }) {
  return (
    <div className="px-4 py-2.5">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("text-base font-bold tabular-nums", danger && "text-destructive")}>{value}</p>
    </div>
  );
}

function AttemptCard({ check, attempt, numbered, unit }: { check: PointCheck; attempt: PointAttempt; numbered: boolean; unit: string | null }) {
  const { t } = useI18n();
  const entry = attempt.entries[attempt.entries.length - 1];
  const rejected = attempt.review?.verdict === "rejected";
  return (
    <div className={cn("rounded-lg border border-border px-3 py-2.5", rejected && "border-destructive/40 bg-destructive/5")}>
      <div className="flex items-center justify-between gap-2">
        <Link to={`/maintenance/jobs/${check.job_id}`} className="min-w-0 truncate text-sm font-semibold text-primary hover:underline">
          {check.job_number} · {formatDay(entry?.finished_at)}
          {numbered && ` · ${fill(t("maintenance.history.point.attempt"), { n: attempt.attempt })}`}
        </Link>
        {attempt.review ? (
          <Badge variant={rejected ? "destructive" : "success"}>{t(CHECK_STATE_LABEL_KEY[attempt.review.verdict])}</Badge>
        ) : (
          entry && <Badge variant={OUTCOME_BADGE_VARIANT[entry.outcome]}>{t(OUTCOME_LABEL_KEY[entry.outcome])}</Badge>
        )}
      </div>
      {entry && (
        <p className="mt-1 text-xs text-muted-foreground">
          {entry.performer_name} · {formatClock(entry.duration_seconds)} (
          {t(entry.duration_source === "manual" ? "maintenance.history.point.manual" : "maintenance.history.point.timer")})
          {entry.measured_value !== null && (
            <>
              {" · "}
              <b className={cn("text-foreground", entry.outcome === "issue" && "text-destructive")}>{formatMeasure(entry.measured_value, unit)}</b>
            </>
          )}
          {" · "}
          {t(OUTCOME_LABEL_KEY[entry.outcome])}
          {entry.note && ` · “${entry.note}”`}
        </p>
      )}
      {attempt.review?.reason && (
        <p className="mt-1 text-xs text-muted-foreground">
          {fill(t("maintenance.history.point.review"), { reason: attempt.review.reason, name: attempt.review.reviewer_name })}
        </p>
      )}
      {entry?.has_photo && <EntryPhoto entryId={entry.entry_id} className="mt-2 h-16 w-20" />}
    </div>
  );
}

function PointHistory({ data, photoUrl }: { data: CheckpointHistory; photoUrl: string | undefined }) {
  const { t } = useI18n();
  const point = data.checkpoint;
  const ActionIcon = CHECK_ACTION_ICON[point.action];
  return (
    <div className="pb-6">
      <header className="space-y-1 border-b border-border px-5 pb-3 pr-12 pt-5">
        <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
          {t("maintenance.history.point.eyebrow")} · {point.equipment_name}
        </p>
        <SheetTitle className="flex items-center gap-2 text-base font-bold">
          <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-accent text-[11px] font-bold text-accent-foreground">1</span>
          {point.label}
        </SheetTitle>
        <SheetDescription className="flex flex-wrap items-center gap-1.5 text-xs">
          <ActionIcon className="h-3.5 w-3.5" />
          {t(CHECK_ACTION_LABEL_KEY[point.action])}
          {point.measure_unit && ` · ${point.measure_unit}`}
          {point.instructions && ` · ${point.instructions}`}
        </SheetDescription>
      </header>
      {photoUrl && (
        <div className="bg-[radial-gradient(circle_at_50%_60%,#1A4A85,#071F43)] p-3">
          <PinnedPhoto src={photoUrl} pins={[{ id: point.id, x: point.x_pct, y: point.y_pct, n: 1, tone: "active" }]} />
          <p className="mt-1 text-[10px] uppercase tracking-[0.14em] text-white/80">{point.view_label}</p>
        </div>
      )}
      <div className="grid grid-cols-3 divide-x divide-border border-b border-border">
        <Figure label={t("maintenance.history.point.checked")} value={fill(t("maintenance.history.point.times"), { n: data.summary.checks_count })} />
        <Figure label={t("maintenance.history.point.issues")} value={String(data.summary.issues_count)} danger={data.summary.issues_count > 0} />
        <Figure label={t("maintenance.history.point.last")} value={formatDay(data.summary.last_checked_at)} />
      </div>
      {data.measures.length > 0 && (
        <div className="px-5 pt-4">
          <div className="flex items-baseline justify-between gap-2">
            <p className="text-sm font-semibold">{fill(t("maintenance.history.point.measures"), { unit: point.measure_unit ?? "" })}</p>
            <p className="text-xs text-muted-foreground">{t("maintenance.history.point.noLimits")}</p>
          </div>
          <MeasureTrendChart measures={data.measures} unit={point.measure_unit} />
        </div>
      )}
      <div className="space-y-2 px-5 pt-4">
        <p className="text-sm font-semibold">{t("maintenance.history.point.checks")}</p>
        {data.summary.checks_count === 0 ? (
          <EmptyState
            icon={<MapPin className="h-5 w-5" />}
            illustration={<CheckpointNeverIllustration aria-hidden className="h-40 w-48" />}
            title={t("maintenance.history.point.empty.title")}
            description={t("maintenance.history.point.empty.description")}
          />
        ) : (
          data.checks.map((check) =>
            check.attempts.length === 0 ? (
              <p key={check.check_id} className="rounded-lg border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
                {check.job_number} · {t("maintenance.history.point.notYet")}
              </p>
            ) : (
              check.attempts.map((attempt) => (
                <AttemptCard
                  key={`${check.check_id}-${attempt.attempt}`}
                  check={check}
                  attempt={attempt}
                  numbered={check.attempts.length > 1}
                  unit={point.measure_unit}
                />
              ))
            ),
          )
        )}
      </div>
    </div>
  );
}

/** A checkpoint's whole history, in a panel sliding over the logbook (`?point=<id>`). */
export function CheckpointHistorySheet({ checkpointId, onClose }: { checkpointId: string | null; onClose: () => void }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const history = useCheckpointHistory(session!.token, checkpointId);
  const data = history.data && history.data.checkpoint.id === checkpointId ? history.data : undefined;
  const { url } = useAuthedImage(fetchViewImageBlob, data?.checkpoint.view_id, data?.checkpoint.view_version);
  return (
    <Sheet open={checkpointId !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent closeLabel={t("common.close")}>
        {data ? (
          <PointHistory data={data} photoUrl={url} />
        ) : (
          <div className="space-y-3 p-5">
            <SheetTitle className="sr-only">{t("maintenance.history.point.eyebrow")}</SheetTitle>
            <Skeleton className="h-6 w-2/3" />
            <Skeleton className="h-40 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
