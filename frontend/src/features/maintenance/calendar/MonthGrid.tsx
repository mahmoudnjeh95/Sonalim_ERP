import { Fragment, type MouseEvent } from "react";
import { cn } from "../../../lib/utils";
import { useI18n } from "../../../lib/i18n";
import type { CalendarProjectedOccurrence, JobListItem } from "../api";
import { JOB_STATUS_LABEL_KEY } from "../labels";

/** One job chip's colour, by job status (urgent/overdue are drawn on top of this). */
function jobChipClassName(job: JobListItem): string {
  switch (job.status) {
    case "closed":
      return "border-success/20 bg-success-soft text-success";
    case "in_progress":
    case "rework":
      return "border-warning/20 bg-warning-soft text-warning";
    case "submitted":
      return "border-primary/20 bg-primary/10 text-primary";
    case "cancelled":
      return "border-border bg-muted text-muted-foreground line-through";
    case "planned":
    case "assigned":
    default:
      return "border-border bg-muted text-foreground";
  }
}

/** A job chip: number + machine code, coloured by status, urgent = red left border, overdue = red text. */
export function JobChip({
  job,
  onClick,
}: {
  job: JobListItem;
  onClick: (event: MouseEvent<HTMLButtonElement>) => void;
}) {
  const { t } = useI18n();
  return (
    <button
      type="button"
      onClick={onClick}
      title={`${job.number} — ${job.equipment_name} — ${t(JOB_STATUS_LABEL_KEY[job.status])}`}
      className={cn(
        "block w-full truncate rounded border px-1.5 py-0.5 text-left text-[11px] font-medium leading-tight transition-colors hover:brightness-95",
        jobChipClassName(job),
        job.priority === "urgent" && "border-l-2 border-l-destructive",
      )}
    >
      <span className={cn(job.overdue && "text-destructive")}>
        {job.number} · {job.equipment_code}
      </span>
    </button>
  );
}

/** A projected program occurrence: dashed outline chip, program name, click → Programs tab. */
export function ProjectedChip({
  occurrence,
  onClick,
}: {
  occurrence: CalendarProjectedOccurrence;
  onClick: (event: MouseEvent<HTMLButtonElement>) => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={`${occurrence.program_name} — ${occurrence.equipment_name}`}
      className="block w-full truncate rounded border border-dashed border-muted-foreground/40 bg-background px-1.5 py-0.5 text-left text-[11px] font-medium leading-tight text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
    >
      {occurrence.program_name}
    </button>
  );
}

export interface CalendarDay {
  iso: string;
  inMonth: boolean;
  isToday: boolean;
  jobs: JobListItem[];
  projected: CalendarProjectedOccurrence[];
}

const MAX_CHIPS_PER_DAY = 3;

/**
 * Monday-first month grid: 6 weeks always shown so the grid height never jumps
 * between months. Each day cell lists its job chips then its projected
 * (dashed) chips, capped with a "+N" that opens the day's full list (reusing
 * the phone day-list behaviour so desktop users aren't stuck scrolling a tiny
 * cell either).
 */
export function MonthGrid({
  days,
  onSelectDay,
  onSelectJob,
  onSelectProjected,
}: {
  days: CalendarDay[];
  onSelectDay: (iso: string) => void;
  onSelectJob: (job: JobListItem) => void;
  onSelectProjected: (occurrence: CalendarProjectedOccurrence) => void;
}) {
  const { t } = useI18n();
  const weekdayKeys = [
    "maintenance.calendar.weekday.mon",
    "maintenance.calendar.weekday.tue",
    "maintenance.calendar.weekday.wed",
    "maintenance.calendar.weekday.thu",
    "maintenance.calendar.weekday.fri",
    "maintenance.calendar.weekday.sat",
    "maintenance.calendar.weekday.sun",
  ] as const;

  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <div className="grid grid-cols-7 border-b border-border bg-muted/40">
        {weekdayKeys.map((key) => (
          <div key={key} className="px-2 py-2 text-center text-xs font-medium text-muted-foreground">
            {t(key)}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7">
        {days.map((day) => {
          const total = day.jobs.length + day.projected.length;
          const shownJobs = day.jobs.slice(0, MAX_CHIPS_PER_DAY);
          const remainingSlots = Math.max(0, MAX_CHIPS_PER_DAY - shownJobs.length);
          const shownProjected = day.projected.slice(0, remainingSlots);
          const hiddenCount = total - shownJobs.length - shownProjected.length;
          const dayNumber = Number(day.iso.slice(8, 10));

          return (
            // A plain clickable div, not a <button>: the day cell holds real
            // <button> chips inside it (job/projected), and a <button> cannot
            // nest another <button> (invalid DOM, breaks click targeting).
            <div
              key={day.iso}
              role="button"
              tabIndex={0}
              onClick={() => onSelectDay(day.iso)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelectDay(day.iso);
                }
              }}
              className={cn(
                "flex min-h-[7rem] cursor-pointer flex-col items-stretch gap-1 border-b border-r border-border p-1.5 text-left transition-colors last:border-r-0 hover:bg-muted/40",
                !day.inMonth && "bg-muted/20",
              )}
            >
              <span
                className={cn(
                  "inline-flex h-6 w-6 items-center justify-center self-start rounded-full text-xs font-medium",
                  day.isToday ? "bg-primary text-primary-foreground" : day.inMonth ? "text-foreground" : "text-muted-foreground",
                )}
              >
                {dayNumber}
              </span>
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                {shownJobs.map((job) => (
                  <Fragment key={job.id}>
                    <JobChip
                      job={job}
                      onClick={(event) => {
                        event.stopPropagation();
                        onSelectJob(job);
                      }}
                    />
                  </Fragment>
                ))}
                {shownProjected.map((occurrence) => (
                  <ProjectedChip
                    key={`${occurrence.program_id}-${occurrence.date}`}
                    occurrence={occurrence}
                    onClick={(event) => {
                      event.stopPropagation();
                      onSelectProjected(occurrence);
                    }}
                  />
                ))}
                {hiddenCount > 0 && (
                  <span className="px-1 text-[11px] font-medium text-muted-foreground">
                    {t("maintenance.calendar.more").replace("{count}", String(hiddenCount))}
                  </span>
                )}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
