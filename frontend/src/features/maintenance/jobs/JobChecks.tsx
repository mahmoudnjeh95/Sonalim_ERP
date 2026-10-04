import { Fragment, useState } from "react";
import { Camera, ChevronDown } from "lucide-react";
import { Badge } from "../../../components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../../components/ui/table";
import { useI18n } from "../../../lib/i18n";
import { useIsMobile } from "../../../lib/useIsMobile";
import { cn } from "../../../lib/utils";
import type { JobCheck, JobDetail } from "../api";
import {
  CHECK_ACTION_ICON,
  CHECK_ACTION_LABEL_KEY,
  CHECK_STATE_BADGE_VARIANT,
  CHECK_STATE_LABEL_KEY,
  OUTCOME_BADGE_VARIANT,
  OUTCOME_LABEL_KEY,
} from "../labels";
import { EntryPhoto } from "./EntryPhoto";
import { CheckHistory } from "./CheckHistory";
import { formatClock, isRedo, latestEntry, latestRejection } from "./jobFormat";

/** The DOM id of a point's row/card, so a pin tapped on a photo can scroll to it. */
export function checkRowId(checkId: string): string {
  return `job-check-${checkId}`;
}

function StateBadge({ check }: { check: JobCheck }) {
  const { t } = useI18n();
  // A rejected point is stored as `pending` on a new attempt; say so rather than a bare "à faire".
  if (isRedo(check)) {
    return (
      <Badge variant="destructive" dot>
        {t("maintenance.checkState.redo")}
      </Badge>
    );
  }
  return (
    <Badge variant={CHECK_STATE_BADGE_VARIANT[check.state]} dot>
      {t(CHECK_STATE_LABEL_KEY[check.state])}
    </Badge>
  );
}

function PointLabel({ check }: { check: JobCheck }) {
  const { t } = useI18n();
  const Icon = CHECK_ACTION_ICON[check.action];
  const rejection = isRedo(check) ? latestRejection(check) : null;
  return (
    <div className="min-w-0">
      <p className="flex items-center gap-1.5 font-medium">
        <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-label={t(CHECK_ACTION_LABEL_KEY[check.action])} />
        <span className="min-w-0 break-words">{check.label}</span>
        {check.requires_photo && (
          <Camera className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-label={t("maintenance.jobs.photo.required")} />
        )}
      </p>
      {rejection?.reason && (
        <p className="mt-0.5 break-words text-xs text-destructive">
          {t("maintenance.jobs.rejectionReason")} : {rejection.reason}
        </p>
      )}
    </div>
  );
}

/**
 * The job's points: a table on desktop, cards on a phone. Each line shows the
 * point's current state and its latest entry; opening a line shows everything
 * ever recorded on it, attempt by attempt (`CheckHistory`).
 */
export function JobChecks({
  job,
  highlightedCheckId,
  onSelect,
}: {
  job: JobDetail;
  highlightedCheckId: string | null;
  /** A point was opened — the page highlights its pin on the photos. */
  onSelect: (checkId: string | null) => void;
}) {
  const { t } = useI18n();
  const isMobile = useIsMobile();
  const [expandedId, setExpandedId] = useState<string | null>(null);

  function toggle(checkId: string) {
    const next = expandedId === checkId ? null : checkId;
    setExpandedId(next);
    onSelect(next);
  }

  if (isMobile) {
    return (
      <ul className="space-y-2">
        {job.checks.map((check, index) => {
          const entry = latestEntry(check);
          const expanded = expandedId === check.id;
          return (
            <li
              key={check.id}
              id={checkRowId(check.id)}
              className={cn(
                "rounded-lg border border-border p-3 transition-colors",
                highlightedCheckId === check.id && "border-accent bg-accent/5",
              )}
            >
              <div className="flex items-start gap-2">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold">
                  {index + 1}
                </span>
                <div className="min-w-0 flex-1 text-sm">
                  <PointLabel check={check} />
                </div>
                <StateBadge check={check} />
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
                <div>
                  <dt className="text-muted-foreground">{t("maintenance.jobs.column.assignee")}</dt>
                  <dd className="break-words">{check.assignee_name ?? "—"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">{t("maintenance.jobs.column.attempt")}</dt>
                  <dd className="tabular-nums">{check.attempt}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">{t("maintenance.jobs.column.performer")}</dt>
                  <dd className="break-words">{entry?.performer_name ?? "—"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">{t("maintenance.jobs.column.duration")}</dt>
                  <dd className="tabular-nums">{entry ? formatClock(entry.duration_seconds) : "—"}</dd>
                </div>
              </dl>
              {entry && (
                <div className="mt-3 flex items-center justify-between gap-3">
                  <Badge variant={OUTCOME_BADGE_VARIANT[entry.outcome]}>{t(OUTCOME_LABEL_KEY[entry.outcome])}</Badge>
                  {entry.has_photo && <EntryPhoto entryId={entry.id} />}
                </div>
              )}
              {(check.entries.length > 0 || check.reviews.length > 0) && (
                <>
                  <button
                    type="button"
                    onClick={() => toggle(check.id)}
                    aria-expanded={expanded}
                    className="mt-3 flex min-h-11 w-full items-center justify-between border-t border-border pt-2 text-sm font-medium text-primary"
                  >
                    {t("maintenance.jobs.history")}
                    <ChevronDown className={cn("h-4 w-4 transition-transform", expanded && "rotate-180")} />
                  </button>
                  {expanded && (
                    <div className="pt-2">
                      <CheckHistory check={check} />
                    </div>
                  )}
                </>
              )}
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-12">#</TableHead>
          <TableHead>{t("maintenance.jobs.column.point")}</TableHead>
          <TableHead>{t("maintenance.jobs.column.assignee")}</TableHead>
          <TableHead>{t("maintenance.jobs.column.state")}</TableHead>
          <TableHead className="text-right">{t("maintenance.jobs.column.attempt")}</TableHead>
          <TableHead>{t("maintenance.jobs.column.performer")}</TableHead>
          <TableHead className="text-right">{t("maintenance.jobs.column.duration")}</TableHead>
          <TableHead>{t("maintenance.jobs.column.outcome")}</TableHead>
          <TableHead>{t("maintenance.jobs.column.photo")}</TableHead>
          <TableHead className="w-10" aria-label={t("maintenance.jobs.history")} />
        </TableRow>
      </TableHeader>
      <TableBody>
        {job.checks.map((check, index) => {
          const entry = latestEntry(check);
          const expanded = expandedId === check.id;
          const hasHistory = check.entries.length > 0 || check.reviews.length > 0;
          return (
            <Fragment key={check.id}>
              <TableRow
                id={checkRowId(check.id)}
                onClick={hasHistory ? () => toggle(check.id) : undefined}
                aria-expanded={hasHistory ? expanded : undefined}
                className={cn(hasHistory && "cursor-pointer", highlightedCheckId === check.id && "bg-accent/5 hover:bg-accent/10")}
              >
                <TableCell className="tabular-nums text-muted-foreground">{index + 1}</TableCell>
                <TableCell>
                  <PointLabel check={check} />
                </TableCell>
                <TableCell>{check.assignee_name ?? <span className="text-muted-foreground">—</span>}</TableCell>
                <TableCell>
                  <StateBadge check={check} />
                </TableCell>
                <TableCell className="text-right tabular-nums">{check.attempt}</TableCell>
                <TableCell>{entry?.performer_name ?? <span className="text-muted-foreground">—</span>}</TableCell>
                <TableCell className="text-right tabular-nums">{entry ? formatClock(entry.duration_seconds) : "—"}</TableCell>
                <TableCell>
                  {entry ? (
                    <Badge variant={OUTCOME_BADGE_VARIANT[entry.outcome]}>{t(OUTCOME_LABEL_KEY[entry.outcome])}</Badge>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell className="py-1.5">
                  {entry?.has_photo ? <EntryPhoto entryId={entry.id} /> : <span className="text-muted-foreground">—</span>}
                </TableCell>
                <TableCell className="px-2 text-muted-foreground">
                  {hasHistory && <ChevronDown className={cn("h-4 w-4 transition-transform", expanded && "rotate-180")} />}
                </TableCell>
              </TableRow>
              {expanded && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={10} className="bg-muted/30">
                    <div className="max-w-3xl">
                      <CheckHistory check={check} />
                    </div>
                  </TableCell>
                </TableRow>
              )}
            </Fragment>
          );
        })}
      </TableBody>
    </Table>
  );
}
