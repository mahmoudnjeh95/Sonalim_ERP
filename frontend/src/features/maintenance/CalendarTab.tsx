import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronLeft, ChevronRight, AlertTriangle } from "lucide-react";
import { Button } from "../../components/ui/button";
import { Card, CardContent } from "../../components/ui/card";
import { Select } from "../../components/ui/select";
import { AppLoader } from "../../components/patterns/AppLoader";
import { EmptyState } from "../../components/patterns/EmptyState";
import { useAuth } from "../../lib/auth";
import { currentLocale, useI18n } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { useCalendar, useEquipmentList, type CalendarProjectedOccurrence, type JobListItem } from "./api";
import { JOB_STATUS_LABEL_KEY } from "./labels";
import { JobChip, MonthGrid, ProjectedChip, type CalendarDay } from "./calendar/MonthGrid";
import { apiErrorMessage } from "./jobs/jobFormat";

const pad = (value: number) => String(value).padStart(2, "0");

function toIso(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function todayDate(): Date {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

/** Monday=0 .. Sunday=6, unlike `Date#getDay()` which is Sunday=0. */
function mondayFirstWeekday(date: Date): number {
  return (date.getDay() + 6) % 7;
}

function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

/** The Monday that starts the week containing `date`. */
function startOfWeek(date: Date): Date {
  return addDays(date, -mondayFirstWeekday(date));
}

/** 6 full weeks (42 days), Monday-first, always covering the whole visible month. */
function monthGridRange(monthAnchor: Date): { gridStart: Date; gridEnd: Date } {
  const firstOfMonth = new Date(monthAnchor.getFullYear(), monthAnchor.getMonth(), 1);
  const gridStart = startOfWeek(firstOfMonth);
  const gridEnd = addDays(gridStart, 41);
  return { gridStart, gridEnd };
}

/**
 * Calendar tab: the default tab of the maintenance page. Month grid on
 * desktop/tablet, a 7-day list on a phone (`< 640px`, matching the dialog
 * sheet breakpoint and the brief's own wording) since a tiny month grid on a
 * phone can't show a chip legibly. Supervisor's "what we did, what we're
 * doing, what's next" view: real jobs (coloured by status) plus projected
 * (not-yet-materialised) program occurrences as dashed chips.
 */
export function CalendarTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const token = session!.token;
  const isNarrow = useIsNarrow();

  const [anchor, setAnchor] = useState<Date>(() => todayDate());
  const [equipmentId, setEquipmentId] = useState("");
  const [selectedDayIso, setSelectedDayIso] = useState<string | null>(null);

  const today = todayDate();
  const todayIso = toIso(today);

  const { gridStart, gridEnd } = useMemo(() => monthGridRange(anchor), [anchor]);
  const weekStart = useMemo(() => startOfWeek(anchor), [anchor]);
  const weekEnd = useMemo(() => addDays(weekStart, 6), [weekStart]);

  const rangeStart = isNarrow ? weekStart : gridStart;
  const rangeEnd = isNarrow ? weekEnd : gridEnd;
  const from = toIso(rangeStart);
  const to = toIso(rangeEnd);

  const { data: equipment = [] } = useEquipmentList(token);
  const { data, isLoading, isError, error } = useCalendar(token, from, to);

  const machines = useMemo(
    () =>
      equipment
        .filter((item) => !item.archived_at || item.id === equipmentId)
        .slice()
        .sort((a, b) => a.name.localeCompare(b.name)),
    [equipment, equipmentId],
  );

  const jobs = useMemo(
    () => (data?.jobs ?? []).filter((job) => !equipmentId || job.equipment_id === equipmentId),
    [data, equipmentId],
  );
  const projected = useMemo(
    () => (data?.projected ?? []).filter((occurrence) => !equipmentId || occurrence.equipment_id === equipmentId),
    [data, equipmentId],
  );

  const jobsByDay = useMemo(() => {
    const map = new Map<string, JobListItem[]>();
    for (const job of jobs) {
      const key = job.due_date.slice(0, 10);
      const list = map.get(key) ?? [];
      list.push(job);
      map.set(key, list);
    }
    for (const list of map.values()) {
      list.sort((a, b) => (a.priority === b.priority ? 0 : a.priority === "urgent" ? -1 : 1));
    }
    return map;
  }, [jobs]);

  const projectedByDay = useMemo(() => {
    const map = new Map<string, CalendarProjectedOccurrence[]>();
    for (const occurrence of projected) {
      const key = occurrence.date.slice(0, 10);
      const list = map.get(key) ?? [];
      list.push(occurrence);
      map.set(key, list);
    }
    return map;
  }, [projected]);

  const days: CalendarDay[] = useMemo(() => {
    const list: CalendarDay[] = [];
    let cursor = rangeStart;
    while (cursor <= rangeEnd) {
      const iso = toIso(cursor);
      list.push({
        iso,
        inMonth: cursor.getMonth() === anchor.getMonth(),
        isToday: iso === todayIso,
        jobs: jobsByDay.get(iso) ?? [],
        projected: projectedByDay.get(iso) ?? [],
      });
      cursor = addDays(cursor, 1);
    }
    return list;
  }, [rangeStart, rangeEnd, anchor, todayIso, jobsByDay, projectedByDay]);

  function goPrev() {
    setAnchor((current) => (isNarrow ? addDays(current, -7) : new Date(current.getFullYear(), current.getMonth() - 1, 1)));
  }
  function goNext() {
    setAnchor((current) => (isNarrow ? addDays(current, 7) : new Date(current.getFullYear(), current.getMonth() + 1, 1)));
  }
  function goToday() {
    setAnchor(todayDate());
    setSelectedDayIso(null);
  }

  function openJob(job: JobListItem) {
    navigate(`/maintenance/jobs/${job.id}`, { state: { from: "/maintenance?tab=calendar" } });
  }
  function openProjected(_occurrence: CalendarProjectedOccurrence) {
    navigate("/maintenance?tab=programs");
  }

  const monthLabel = anchor.toLocaleDateString(currentLocale(), { month: "long", year: "numeric" });
  const weekLabel = `${weekStart.toLocaleDateString(currentLocale(), { day: "numeric", month: "short" })} – ${weekEnd.toLocaleDateString(currentLocale(), { day: "numeric", month: "short", year: "numeric" })}`;

  const selectedDay = selectedDayIso ? days.find((day) => day.iso === selectedDayIso) : undefined;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={goPrev} aria-label={t("maintenance.calendar.previous")}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="sm" onClick={goNext} aria-label={t("maintenance.calendar.next")}>
            <ChevronRight className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="sm" onClick={goToday}>
            {t("maintenance.calendar.today")}
          </Button>
          <span className="ml-1 text-sm font-semibold capitalize">{isNarrow ? weekLabel : monthLabel}</span>
        </div>
        {machines.length > 0 && (
          <div className="w-full sm:w-64">
            <Select
              aria-label={t("maintenance.calendar.machine")}
              value={equipmentId}
              onChange={(event) => setEquipmentId(event.target.value)}
            >
              <option value="">{t("maintenance.calendar.machine.all")}</option>
              {machines.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.code} — {item.name}
                </option>
              ))}
            </Select>
          </div>
        )}
      </div>

      {isLoading ? (
        <AppLoader className="py-16" />
      ) : isError ? (
        <Card>
          <CardContent>
            <EmptyState
              icon={<AlertTriangle className="h-5 w-5" />}
              title={t("maintenance.calendar.loadError.title")}
              description={apiErrorMessage(error, t("maintenance.calendar.loadError.description"))}
            />
          </CardContent>
        </Card>
      ) : isNarrow ? (
        <div className="space-y-2">
          {days.map((day) => (
            <DayListRow key={day.iso} day={day} onOpenJob={openJob} onOpenProjected={openProjected} />
          ))}
        </div>
      ) : (
        <MonthGrid days={days} onSelectDay={setSelectedDayIso} onSelectJob={openJob} onSelectProjected={openProjected} />
      )}

      <CalendarLegend />

      {!isNarrow && selectedDay && (
        <DayDetailCard day={selectedDay} onClose={() => setSelectedDayIso(null)} onOpenJob={openJob} onOpenProjected={openProjected} />
      )}
    </div>
  );
}

const NARROW_MEDIA_QUERY = "(max-width: 639px)";

/** Narrower than the dialog's own `sm` breakpoint (640px): a month grid cell can't carry a legible chip below it, so a phone gets the week list instead. */
function useIsNarrow(): boolean {
  const [narrow, setNarrow] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia(NARROW_MEDIA_QUERY).matches : false,
  );
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(NARROW_MEDIA_QUERY);
    const onChange = (event: MediaQueryListEvent) => setNarrow(event.matches);
    setNarrow(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
  return narrow;
}

function DayListRow({
  day,
  onOpenJob,
  onOpenProjected,
}: {
  day: CalendarDay;
  onOpenJob: (job: JobListItem) => void;
  onOpenProjected: (occurrence: CalendarProjectedOccurrence) => void;
}) {
  const { t } = useI18n();
  const date = new Date(`${day.iso}T00:00:00`);
  const hasContent = day.jobs.length > 0 || day.projected.length > 0;
  return (
    <Card className={cn(day.isToday && "border-primary/40 bg-primary/5")}>
      <CardContent className="space-y-2 p-3">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
              day.isToday ? "bg-primary text-primary-foreground" : "bg-muted text-foreground",
            )}
          >
            {date.getDate()}
          </span>
          <span className="text-sm font-medium capitalize">
            {date.toLocaleDateString(currentLocale(), { weekday: "long", day: "numeric", month: "short" })}
          </span>
        </div>
        {hasContent ? (
          <div className="space-y-1 pl-9">
            {day.jobs.map((job) => (
              <JobChip key={job.id} job={job} onClick={() => onOpenJob(job)} />
            ))}
            {day.projected.map((occurrence) => (
              <ProjectedChip
                key={`${occurrence.program_id}-${occurrence.date}`}
                occurrence={occurrence}
                onClick={() => onOpenProjected(occurrence)}
              />
            ))}
          </div>
        ) : (
          <p className="pl-9 text-xs text-muted-foreground">{t("maintenance.calendar.dayEmpty")}</p>
        )}
      </CardContent>
    </Card>
  );
}

function DayDetailCard({
  day,
  onClose,
  onOpenJob,
  onOpenProjected,
}: {
  day: CalendarDay;
  onClose: () => void;
  onOpenJob: (job: JobListItem) => void;
  onOpenProjected: (occurrence: CalendarProjectedOccurrence) => void;
}) {
  const { t } = useI18n();
  const date = new Date(`${day.iso}T00:00:00`);
  const hasContent = day.jobs.length > 0 || day.projected.length > 0;
  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-semibold capitalize">
            {date.toLocaleDateString(currentLocale(), { weekday: "long", day: "numeric", month: "long", year: "numeric" })}
          </span>
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t("common.close")}
          </Button>
        </div>
        {hasContent ? (
          <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
            {day.jobs.map((job) => (
              <JobChip key={job.id} job={job} onClick={() => onOpenJob(job)} />
            ))}
            {day.projected.map((occurrence) => (
              <ProjectedChip
                key={`${occurrence.program_id}-${occurrence.date}`}
                occurrence={occurrence}
                onClick={() => onOpenProjected(occurrence)}
              />
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{t("maintenance.calendar.dayEmpty")}</p>
        )}
      </CardContent>
    </Card>
  );
}

function CalendarLegend() {
  const { t } = useI18n();
  const entries: { labelKey: typeof JOB_STATUS_LABEL_KEY["closed"]; className: string }[] = [
    { labelKey: "maintenance.jobStatus.closed", className: "border-success/20 bg-success-soft text-success" },
    { labelKey: "maintenance.jobStatus.in_progress", className: "border-warning/20 bg-warning-soft text-warning" },
    { labelKey: "maintenance.jobStatus.submitted", className: "border-primary/20 bg-primary/10 text-primary" },
    { labelKey: "maintenance.jobStatus.planned", className: "border-border bg-muted text-foreground" },
  ];
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
      {entries.map((entry) => (
        <span key={entry.labelKey} className="inline-flex items-center gap-1.5">
          <span className={cn("inline-block h-3 w-3 rounded border", entry.className)} />
          {t(entry.labelKey)}
        </span>
      ))}
      <span className="inline-flex items-center gap-1.5">
        <span className="inline-block h-3 w-3 rounded border border-l-2 border-border border-l-destructive bg-muted" />
        {t("maintenance.calendar.legend.urgent")}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="text-destructive">{t("maintenance.calendar.legend.overdueSample")}</span>
        {t("maintenance.calendar.legend.overdue")}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="inline-block h-3 w-3 rounded border border-dashed border-muted-foreground/40 bg-background" />
        {t("maintenance.calendar.legend.projected")}
      </span>
    </div>
  );
}
