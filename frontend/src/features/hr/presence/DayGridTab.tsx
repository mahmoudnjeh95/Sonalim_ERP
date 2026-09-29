import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save, Users } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { Checkbox } from "../../../components/ui/checkbox";
import { Badge } from "../../../components/ui/badge";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import type { Department } from "../api";
import { HrListTable } from "../HrListTable";
import {
  ENTERABLE_STATUSES, HR_KEYS, WORKED_STATUSES, getPresenceGrid, savePresenceDays,
  type GridDay, type GridRow, type PresenceEntry, type PresenceSource, type PresenceStatus, type WorkSchedule,
} from "../presenceApi";
import { errorText, formatDuration, monthStartOf, todayIso } from "../presenceFormat";
import { PRESENCE_STATUS_LABEL, PresenceStatusBadge } from "./PresenceStatusBadge";
import { TeamPicker, teamFilterOf, type Team } from "./TeamPicker";
import { useClosedMonths } from "./useClosedMonths";

interface RowDraft { status: PresenceStatus | ""; late: string; worked: string; otDay: string; otNight: string; justified: boolean; note: string; dirty: boolean }
type View = "all" | "unsaved" | "exceptions";

export const SOURCE_LABEL: Record<PresenceSource, TranslationKey> = {
  manual: "hr.presence.source.manual", clock: "hr.presence.source.clock", leave: "hr.presence.source.leave", holiday: "hr.presence.source.holiday",
};

const count = (value: number) => (value ? String(value) : "");

function draftFrom(day: GridDay): RowDraft {
  const record = day.record;
  if (!record) return { status: day.default_status ?? "", late: "", worked: "", otDay: "", otNight: "", justified: false, note: "", dirty: false };
  const derived = Math.max(0, day.planned_minutes - record.late_minutes);
  return {
    status: record.status, late: count(record.late_minutes),
    worked: record.worked_minutes === derived ? "" : String(record.worked_minutes), // "" = derived from the schedule
    otDay: count(record.ot_minutes_day), otNight: count(record.ot_minutes_night),
    justified: record.justified, note: record.note ?? "", dirty: false,
  };
}

export function isEditable(day: GridDay, closed: boolean): boolean {
  return !closed && day.employed && day.assigned && day.record?.source !== "leave";
}

function toEntry(employeeId: string, day: GridDay, draft: RowDraft): PresenceEntry {
  const status = draft.status as PresenceStatus;
  const worked = WORKED_STATUSES.includes(status);
  const offDay = !day.is_working_day || day.is_holiday;
  return {
    employee_id: employeeId,
    work_date: day.work_date,
    status,
    worked_minutes: worked && draft.worked !== "" ? Number(draft.worked) : null,
    late_minutes: status === "late" ? Number(draft.late || 0) : 0,
    ot_minutes_day: worked && !offDay ? Number(draft.otDay || 0) : 0,
    ot_minutes_night: worked && !offDay ? Number(draft.otNight || 0) : 0,
    justified: status === "absent" && draft.justified,
    note: draft.note.trim() || null,
  };
}

export function DayGridTab({ departments, schedules }: { departments: Department[]; schedules: WorkSchedule[] }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [workDate, setWorkDate] = useState(todayIso());
  const [team, setTeam] = useState<Team>({ kind: "department", id: "" });
  const [view, setView] = useState<View>("all");
  const [drafts, setDrafts] = useState<Record<string, RowDraft>>({});
  const grid = useQuery({
    queryKey: [...HR_KEYS.presence, "grid", workDate, team.kind, team.id],
    queryFn: () => getPresenceGrid(token, workDate, teamFilterOf(team)),
  });
  const closed = useClosedMonths([Number(workDate.slice(0, 4))]).has(monthStartOf(workDate));
  const canSave = hasPermission("hr.manage_presence");

  useEffect(() => {
    if (grid.data) setDrafts(Object.fromEntries(grid.data.map((row) => [row.employee_id, draftFrom(row.days[0])])));
  }, [grid.data]);

  const update = (employeeId: string, patch: Partial<RowDraft>) =>
    setDrafts((current) => ({ ...current, [employeeId]: { ...current[employeeId], ...patch, dirty: true } }));

  const entries = (grid.data ?? []).flatMap((row) => {
    const day = row.days[0];
    const draft = drafts[row.employee_id];
    if (!draft || !draft.status || !isEditable(day, closed) || (day.record && !draft.dirty)) return [];
    return [toEntry(row.employee_id, day, draft)];
  });
  const save = useMutation({
    mutationFn: () => savePresenceDays(token, entries),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: HR_KEYS.presence });
      toast.success(`${t("hr.presence.saved")} (${result.saved})`);
    },
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });

  const fields: FilterField<GridRow>[] = [
    { key: "employee", kind: "text", getValue: (row) => `${row.employee_no} ${row.full_name}` },
    { key: "schedule", kind: "text", getValue: (row) => row.days[0].schedule_code },
  ];
  const filters = useColumnFilters(fields);
  const rows = filters.apply(
    (grid.data ?? []).filter((row) => {
      const draft = drafts[row.employee_id];
      if (view === "unsaved") return row.days[0].record === null;
      if (view === "exceptions") return draft !== undefined && draft.status !== "" && draft.status !== "present" && draft.status !== "rest";
      return true;
    }),
  );

  const numberInput = (row: GridRow, key: "late" | "worked" | "otDay" | "otNight", enabled: boolean, placeholder = "") => (
    <Input
      type="number"
      min={0}
      className="h-8"
      placeholder={placeholder}
      disabled={!enabled}
      value={drafts[row.employee_id]?.[key] ?? ""}
      onChange={(e) => update(row.employee_id, { [key]: e.target.value } as Partial<RowDraft>)}
    />
  );
  const stateOf = (row: GridRow) => {
    const day = row.days[0];
    const draft = drafts[row.employee_id];
    const editable = isEditable(day, closed) && canSave;
    const worked = draft !== undefined && WORKED_STATUSES.includes(draft.status as PresenceStatus);
    const offDay = !day.is_working_day || day.is_holiday;
    return { day, draft, editable, worked, offDay };
  };

  const columns: ColumnDef<GridRow>[] = [
    {
      key: "employee", header: t("hr.common.employee"), defaultWidth: 220, sortValue: (row) => row.employee_no,
      cell: (row) => <span className="font-medium">{row.employee_no} · {row.full_name}</span>,
      filterCell: { type: "text", placeholder: t("hr.common.employee"), value: filters.text.employee ?? "", onChange: (v) => filters.setTextValue("employee", v) },
    },
    {
      key: "schedule", header: t("hr.presence.schedule"), defaultWidth: 160, sortValue: (row) => row.days[0].schedule_code ?? "",
      cell: (row) => {
        const day = row.days[0];
        if (!day.employed) return <span className="text-muted-foreground">{t("hr.presence.notEmployed")}</span>;
        if (!day.assigned) return <Badge variant="warning">{t("hr.presence.noSchedule")}</Badge>;
        return (
          <span className="inline-flex items-center gap-2">
            {day.schedule_code}
            <span className="text-xs text-muted-foreground">{day.is_working_day ? formatDuration(day.planned_minutes) : t("hr.presenceStatus.rest")}</span>
            {day.is_holiday && <Badge variant="accent">{t("hr.presenceStatus.holiday")}</Badge>}
          </span>
        );
      },
      filterCell: { type: "text", placeholder: t("hr.presence.schedule"), value: filters.text.schedule ?? "", onChange: (v) => filters.setTextValue("schedule", v) },
    },
    {
      key: "status", header: t("hr.presence.status"), defaultWidth: 150, alwaysVisible: true,
      cell: (row) => {
        const { day, draft, editable } = stateOf(row);
        if (!editable) return day.record ? <PresenceStatusBadge status={day.record.status} /> : "—";
        return (
          <Select className="h-8" aria-label={t("hr.presence.status")} value={draft?.status ?? ""} onChange={(e) => update(row.employee_id, { status: e.target.value as PresenceStatus })}>
            <option value="">—</option>
            {ENTERABLE_STATUSES.map((status) => (
              <option key={status} value={status}>{t(PRESENCE_STATUS_LABEL[status])}</option>
            ))}
          </Select>
        );
      },
    },
    { key: "late", header: t("hr.presence.lateMinutes"), defaultWidth: 110, cell: (row) => numberInput(row, "late", stateOf(row).editable && stateOf(row).draft?.status === "late") },
    {
      key: "worked", header: t("hr.presence.workedMinutes"), defaultWidth: 130,
      cell: (row) => numberInput(row, "worked", stateOf(row).editable && stateOf(row).worked, stateOf(row).day.planned_minutes ? String(stateOf(row).day.planned_minutes) : t("hr.presence.workedAuto")),
    },
    { key: "otDay", header: t("hr.presence.otDay"), defaultWidth: 120, cell: (row) => numberInput(row, "otDay", stateOf(row).editable && stateOf(row).worked && !stateOf(row).offDay) },
    { key: "otNight", header: t("hr.presence.otNight"), defaultWidth: 120, cell: (row) => numberInput(row, "otNight", stateOf(row).editable && stateOf(row).worked && !stateOf(row).offDay) },
    {
      key: "justified", header: t("hr.presence.justified"), defaultWidth: 100,
      cell: (row) => {
        const { draft, editable } = stateOf(row);
        return (
          <Checkbox
            aria-label={t("hr.presence.justified")}
            disabled={!editable || draft?.status !== "absent"}
            checked={draft?.justified ?? false}
            onCheckedChange={(value) => update(row.employee_id, { justified: value === true })}
          />
        );
      },
    },
    {
      key: "note", header: t("hr.presence.note"), defaultWidth: 200,
      cell: (row) => (
        <Input className="h-8" disabled={!stateOf(row).editable} value={drafts[row.employee_id]?.note ?? ""} onChange={(e) => update(row.employee_id, { note: e.target.value })} />
      ),
    },
    {
      key: "source", header: t("hr.presence.source"), defaultWidth: 130,
      cell: (row) => {
        const record = row.days[0].record;
        return record ? <Badge variant="outline">{t(SOURCE_LABEL[record.source])}</Badge> : <span className="text-xs text-muted-foreground">{t("hr.presence.notSaved")}</span>;
      },
    },
  ];

  return (
    <div className="space-y-3">
      {closed && <p className="rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-sm text-warning">{t("hr.presence.monthClosed")}</p>}
      <p className="text-xs text-muted-foreground">{t("hr.presence.restHolidayHint")}</p>
      <HrListTable
        tableKey="hr.presence.dayGrid"
        columns={columns}
        rows={rows}
        rowKey={(row) => row.employee_id}
        loading={grid.isLoading}
        emptyIcon={<Users className="h-5 w-5" />}
        emptyTitle={t("hr.presence.empty.title")}
        emptyDescription={t("hr.presence.empty.description")}
        filtersActive={filters.isActive}
        onClearFilters={filters.reset}
        toolbar={
          <>
            <input type="date" aria-label={t("hr.presence.date")} className="h-9 rounded-md border border-border bg-background px-2 text-sm" value={workDate} onChange={(e) => e.target.value && setWorkDate(e.target.value)} />
            <TeamPicker team={team} onChange={setTeam} departments={departments} schedules={schedules} />
            <FilterTabs
              value={view}
              onChange={setView}
              options={[
                { value: "all", label: t("hr.presence.view.all") },
                { value: "unsaved", label: t("hr.presence.view.unsaved") },
                { value: "exceptions", label: t("hr.presence.view.exceptions") },
              ]}
            />
            {canSave && (
              <Button size="sm" disabled={entries.length === 0 || save.isPending} onClick={() => save.mutate()}>
                <Save className="h-4 w-4" />
                {save.isPending ? t("common.saving") : `${t("hr.presence.save")} (${entries.length})`}
              </Button>
            )}
          </>
        }
      />
    </div>
  );
}
