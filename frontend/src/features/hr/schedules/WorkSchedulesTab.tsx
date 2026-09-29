import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Pencil, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Checkbox } from "../../../components/ui/checkbox";
import { Badge } from "../../../components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../../components/ui/dialog";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import { HrListTable } from "../HrListTable";
import { HR_KEYS, createSchedule, listSchedules, updateSchedule, type ScheduleDay, type WorkSchedule } from "../presenceApi";
import { clockToMinutes, errorText, formatDuration, minutesToClock, spanMinutes } from "../presenceFormat";
import { WEEKDAY_KEYS, WEEKDAY_SHORT_KEYS } from "../presence/PresenceStatusBadge";

interface DayDraft { works: boolean; start: string; end: string; breakMinutes: string }
interface ScheduleDraft { code: string; name: string; isNight: boolean; days: DayDraft[] }
type ActiveFilter = "active" | "inactive" | "all";

const blankDay = (): DayDraft => ({ works: false, start: "", end: "", breakMinutes: "" });
const emptyDraft = (): ScheduleDraft => ({ code: "", name: "", isNight: false, days: Array.from({ length: 7 }, blankDay) });

function toDraft(schedule: WorkSchedule): ScheduleDraft {
  return {
    code: schedule.code,
    name: schedule.name,
    isNight: schedule.is_night,
    days: Array.from({ length: 7 }, (_, weekday) => {
      const day = schedule.days.find((item) => item.weekday === weekday);
      return day
        ? { works: true, start: minutesToClock(day.start_minute), end: minutesToClock(day.end_minute), breakMinutes: String(day.break_minutes) }
        : blankDay();
    }),
  };
}

/** The ticked days as backend lines, or null when a ticked day lacks a valid time. */
function toDays(draft: ScheduleDraft): ScheduleDay[] | null {
  const days: ScheduleDay[] = [];
  for (const [weekday, day] of draft.days.entries()) {
    if (!day.works) continue;
    const start = clockToMinutes(day.start);
    const end = clockToMinutes(day.end);
    const breakMinutes = Number(day.breakMinutes || 0);
    if (start === null || end === null || !Number.isInteger(breakMinutes) || breakMinutes < 0) return null;
    days.push({ weekday, start_minute: start, end_minute: end, break_minutes: breakMinutes });
  }
  return days;
}

export function weeklyMinutes(schedule: WorkSchedule): number {
  return schedule.days.reduce((sum, day) => sum + spanMinutes(day) - day.break_minutes, 0);
}

export function weekSummary(schedule: WorkSchedule, t: (key: TranslationKey) => string): string {
  if (schedule.days.length === 0) return "—";
  const first = schedule.days[0];
  const names = schedule.days.map((day) => t(WEEKDAY_SHORT_KEYS[day.weekday])).join(", ");
  const same = schedule.days.every((day) => day.start_minute === first.start_minute && day.end_minute === first.end_minute);
  return same ? `${names} · ${minutesToClock(first.start_minute)}–${minutesToClock(first.end_minute)}` : names;
}

export function WorkSchedulesTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const schedules = useQuery({ queryKey: HR_KEYS.schedules, queryFn: () => listSchedules(token) });
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>("active");
  const [editing, setEditing] = useState<WorkSchedule | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<ScheduleDraft>(emptyDraft);
  const [formError, setFormError] = useState<string | null>(null);
  const canEdit = hasPermission("hr.admin_presence");

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: HR_KEYS.schedules });
    queryClient.invalidateQueries({ queryKey: HR_KEYS.presence });
  };
  const save = useMutation({
    mutationFn: (days: ScheduleDay[]) => {
      const body = { code: draft.code.trim(), name: draft.name.trim(), is_night: draft.isNight, days };
      return editing ? updateSchedule(token, editing.id, body) : createSchedule(token, body);
    },
    onSuccess: () => {
      refresh();
      setOpen(false);
      toast.success(t(editing ? "hr.schedules.updated" : "hr.schedules.created"));
    },
    onError: (error) => setFormError(errorText(error, t("hr.common.saveError"))),
  });
  const toggleActive = useMutation({
    mutationFn: (schedule: WorkSchedule) => updateSchedule(token, schedule.id, { active: !schedule.active }),
    onSuccess: refresh,
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });

  function openDialog(schedule: WorkSchedule | null) {
    setEditing(schedule);
    setDraft(schedule ? toDraft(schedule) : emptyDraft());
    setFormError(null);
    setOpen(true);
  }
  function submit() {
    const days = toDays(draft);
    if (!draft.code.trim() || !draft.name.trim()) {
      setFormError(t("hr.schedules.error.codeName"));
      return;
    }
    if (days === null || days.length === 0) {
      setFormError(t("hr.schedules.error.times"));
      return;
    }
    save.mutate(days);
  }
  const setDay = (weekday: number, patch: Partial<DayDraft>) =>
    setDraft((current) => ({ ...current, days: current.days.map((day, index) => (index === weekday ? { ...day, ...patch } : day)) }));

  const fields: FilterField<WorkSchedule>[] = [
    { key: "code", kind: "text", getValue: (s) => s.code },
    { key: "name", kind: "text", getValue: (s) => s.name },
    { key: "weekly", kind: "range", getValue: (s) => weeklyMinutes(s) / 60 },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply((schedules.data ?? []).filter((s) => activeFilter === "all" || (activeFilter === "active") === s.active));

  const columns: ColumnDef<WorkSchedule>[] = [
    {
      key: "code", header: t("hr.schedules.code"), defaultWidth: 110, sortValue: (s) => s.code,
      cell: (s) => <span className="font-medium">{s.code}</span>,
      filterCell: { type: "text", placeholder: t("hr.schedules.code"), value: filters.text.code ?? "", onChange: (v) => filters.setTextValue("code", v) },
    },
    {
      key: "name", header: t("hr.schedules.name"), defaultWidth: 200, sortValue: (s) => s.name, cell: (s) => s.name,
      filterCell: { type: "text", placeholder: t("hr.schedules.name"), value: filters.text.name ?? "", onChange: (v) => filters.setTextValue("name", v) },
    },
    { key: "days", header: t("hr.schedules.days"), defaultWidth: 280, cell: (s) => weekSummary(s, t) },
    {
      key: "weekly", header: t("hr.schedules.weeklyHours"), defaultWidth: 130, cellClassName: "tabular-nums",
      sortValue: (s) => weeklyMinutes(s), cell: (s) => formatDuration(weeklyMinutes(s)),
      filterCell: {
        type: "range", min: filters.range.weekly?.min ?? "", max: filters.range.weekly?.max ?? "",
        onMinChange: (v) => filters.setRangeValue("weekly", "min", v), onMaxChange: (v) => filters.setRangeValue("weekly", "max", v),
      },
    },
    { key: "night", header: t("hr.schedules.night"), defaultWidth: 90, cell: (s) => (s.is_night ? <Badge variant="accent">{t("hr.schedules.night")}</Badge> : null) },
    { key: "active", header: t("hr.common.active"), defaultWidth: 90, cell: (s) => (s.active ? t("common.yes") : t("common.no")) },
    {
      key: "actions", header: "", defaultWidth: 200, alwaysVisible: true,
      cell: (s) =>
        canEdit ? (
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => openDialog(s)}>
              <Pencil className="h-3.5 w-3.5" />
              {t("common.edit")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => toggleActive.mutate(s)}>
              {s.active ? t("hr.common.deactivate") : t("hr.common.activate")}
            </Button>
          </div>
        ) : null,
    },
  ];

  return (
    <>
      <HrListTable
        tableKey="hr.schedules"
        columns={columns}
        rows={rows}
        rowKey={(s) => s.id}
        loading={schedules.isLoading}
        emptyIcon={<CalendarClock className="h-5 w-5" />}
        emptyTitle={t("hr.schedules.empty.title")}
        emptyDescription={t("hr.schedules.empty.description")}
        filtersActive={filters.isActive}
        onClearFilters={filters.reset}
        toolbar={
          <>
            <FilterTabs
              value={activeFilter}
              onChange={setActiveFilter}
              options={[
                { value: "active", label: t("hr.common.activeOnly") },
                { value: "inactive", label: t("hr.common.inactiveOnly") },
                { value: "all", label: t("common.all") },
              ]}
            />
            {hasPermission("hr.manage_presence") && (
              <Button size="sm" onClick={() => openDialog(null)}>
                <Plus className="h-4 w-4" />
                {t("hr.schedules.new")}
              </Button>
            )}
          </>
        }
      />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t(editing ? "hr.schedules.editTitle" : "hr.schedules.new")}</DialogTitle>
            <DialogDescription>{t("hr.schedules.dialogHelp")}</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="schedule-code">{t("hr.schedules.code")}</Label>
              <Input id="schedule-code" value={draft.code} onChange={(e) => setDraft({ ...draft, code: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="schedule-name">{t("hr.schedules.name")}</Label>
              <Input id="schedule-name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={draft.isNight} onCheckedChange={(value) => setDraft({ ...draft, isNight: value === true })} />
            {t("hr.schedules.isNight")}
          </label>
          <div className="space-y-2">
            <div className="grid grid-cols-[130px_1fr_1fr_1fr] gap-2 text-xs text-muted-foreground">
              <span />
              <span>{t("hr.schedules.start")}</span>
              <span>{t("hr.schedules.end")}</span>
              <span>{t("hr.schedules.breakMinutes")}</span>
            </div>
            {draft.days.map((day, weekday) => (
              <div key={weekday} className="grid grid-cols-[130px_1fr_1fr_1fr] items-center gap-2">
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox checked={day.works} onCheckedChange={(value) => setDay(weekday, { works: value === true })} />
                  {t(WEEKDAY_KEYS[weekday])}
                </label>
                <Input type="time" aria-label={t("hr.schedules.start")} disabled={!day.works} value={day.start} onChange={(e) => setDay(weekday, { start: e.target.value })} />
                <Input type="time" aria-label={t("hr.schedules.end")} disabled={!day.works} value={day.end} onChange={(e) => setDay(weekday, { end: e.target.value })} />
                <Input type="number" min={0} aria-label={t("hr.schedules.breakMinutes")} disabled={!day.works} value={day.breakMinutes} onChange={(e) => setDay(weekday, { breakMinutes: e.target.value })} />
              </div>
            ))}
          </div>
          {formError && <p className="text-sm text-destructive">{formError}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>{t("common.cancel")}</Button>
            <Button onClick={submit} disabled={save.isPending}>{save.isPending ? t("common.saving") : t("common.save")}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
