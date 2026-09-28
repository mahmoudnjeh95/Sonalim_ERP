import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save, Users } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Select } from "../../../components/ui/select";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import type { ColumnDef } from "../../../lib/useTableColumns";
import type { Department } from "../api";
import { HrListTable } from "../HrListTable";
import {
  ENTERABLE_STATUSES, HR_KEYS, getPresenceWeek, savePresenceDays,
  type GridDay, type GridRow, type PresenceEntry, type PresenceStatus, type WorkSchedule,
} from "../presenceApi";
import { addDaysIso, errorText, monthStartOf, mondayOf, todayIso } from "../presenceFormat";
import { isEditable } from "./DayGridTab";
import { PRESENCE_STATUS_LABEL, PresenceStatusBadge, WEEKDAY_SHORT_KEYS } from "./PresenceStatusBadge";
import { TeamPicker, teamFilterOf, type Team } from "./TeamPicker";
import { useClosedMonths } from "./useClosedMonths";

interface CellDraft { status: PresenceStatus | ""; late: string; dirty: boolean }
const cellKey = (employeeId: string, workDate: string) => `${employeeId}|${workDate}`;

/** Catch-up entry for a whole week: status (and lateness) per cell. Details stay in the day grid. */
export function WeekGridTab({ departments, schedules }: { departments: Department[]; schedules: WorkSchedule[] }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dateFrom, setDateFrom] = useState(mondayOf(todayIso()));
  const [team, setTeam] = useState<Team>({ kind: "department", id: "" });
  const [drafts, setDrafts] = useState<Record<string, CellDraft>>({});
  const dates = Array.from({ length: 7 }, (_, i) => addDaysIso(dateFrom, i));
  const week = useQuery({
    queryKey: [...HR_KEYS.presence, "week", dateFrom, team.kind, team.id],
    queryFn: () => getPresenceWeek(token, dateFrom, teamFilterOf(team)),
  });
  const closedMonths = useClosedMonths([Number(dates[0].slice(0, 4)), Number(dates[6].slice(0, 4))]);
  const canSave = hasPermission("hr.manage_presence");

  useEffect(() => {
    if (!week.data) return;
    const next: Record<string, CellDraft> = {};
    for (const row of week.data) {
      for (const day of row.days) {
        const status = day.record?.status ?? day.default_status ?? "";
        next[cellKey(row.employee_id, day.work_date)] = { status, late: day.record?.late_minutes ? String(day.record.late_minutes) : "", dirty: false };
      }
    }
    setDrafts(next);
  }, [week.data]);

  const editable = (day: GridDay) => canSave && isEditable(day, closedMonths.has(monthStartOf(day.work_date)));
  const update = (key: string, patch: Partial<CellDraft>) => setDrafts((current) => ({ ...current, [key]: { ...current[key], ...patch, dirty: true } }));

  const entries: PresenceEntry[] = (week.data ?? []).flatMap((row) =>
    row.days.flatMap((day) => {
      const draft = drafts[cellKey(row.employee_id, day.work_date)];
      if (!draft || !draft.status || draft.status === "leave" || !editable(day) || (day.record && !draft.dirty)) return [];
      const status = draft.status;
      return [{
        employee_id: row.employee_id, work_date: day.work_date, status, worked_minutes: null,
        late_minutes: status === "late" ? Number(draft.late || 0) : 0, ot_minutes_day: 0, ot_minutes_night: 0,
        justified: false, note: day.record?.note ?? null,
      }];
    }),
  );
  const save = useMutation({
    mutationFn: () => savePresenceDays(token, entries),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: HR_KEYS.presence });
      toast.success(`${t("hr.presence.saved")} (${result.saved})`);
    },
    onError: (error) => toast.error(errorText(error, t("hr.common.saveError"))),
  });

  const fields: FilterField<GridRow>[] = [{ key: "employee", kind: "text", getValue: (row) => `${row.employee_no} ${row.full_name}` }];
  const filters = useColumnFilters(fields);
  const rows = filters.apply(week.data ?? []);

  const dayColumn = (workDate: string, index: number): ColumnDef<GridRow> => ({
    key: `d${index}`,
    header: `${t(WEEKDAY_SHORT_KEYS[index])} ${workDate.slice(8, 10)}/${workDate.slice(5, 7)}`,
    defaultWidth: 130,
    cell: (row) => {
      const day = row.days[index];
      const key = cellKey(row.employee_id, workDate);
      const draft = drafts[key];
      if (!editable(day)) return day.record ? <PresenceStatusBadge status={day.record.status} /> : <span className="text-muted-foreground">—</span>;
      return (
        <div className="space-y-1">
          <Select className="h-8 text-xs" aria-label={workDate} value={draft?.status ?? ""} onChange={(e) => update(key, { status: e.target.value as PresenceStatus })}>
            <option value="">—</option>
            {ENTERABLE_STATUSES.map((status) => (
              <option key={status} value={status}>{t(PRESENCE_STATUS_LABEL[status])}</option>
            ))}
          </Select>
          {draft?.status === "late" && (
            <Input type="number" min={1} className="h-7 text-xs" placeholder={t("hr.presence.lateMinutes")} value={draft.late} onChange={(e) => update(key, { late: e.target.value })} />
          )}
        </div>
      );
    },
  });
  const columns: ColumnDef<GridRow>[] = [
    {
      key: "employee", header: t("hr.common.employee"), defaultWidth: 220, alwaysVisible: true, sortValue: (row) => row.employee_no,
      cell: (row) => <span className="font-medium">{row.employee_no} · {row.full_name}</span>,
      filterCell: { type: "text", placeholder: t("hr.common.employee"), value: filters.text.employee ?? "", onChange: (v) => filters.setTextValue("employee", v) },
    },
    ...dates.map(dayColumn),
  ];

  return (
    <HrListTable
      tableKey="hr.presence.weekGrid"
      columns={columns}
      rows={rows}
      rowKey={(row) => row.employee_id}
      loading={week.isLoading}
      emptyIcon={<Users className="h-5 w-5" />}
      emptyTitle={t("hr.presence.empty.title")}
      emptyDescription={t("hr.presence.empty.description")}
      filtersActive={filters.isActive}
      onClearFilters={filters.reset}
      toolbar={
        <>
          <label className="flex items-center gap-2 text-sm">
            {t("hr.presence.weekOf")}
            <input type="date" className="h-9 rounded-md border border-border bg-background px-2 text-sm" value={dateFrom} onChange={(e) => e.target.value && setDateFrom(mondayOf(e.target.value))} />
          </label>
          <TeamPicker team={team} onChange={setTeam} departments={departments} schedules={schedules} />
          {canSave && (
            <Button size="sm" disabled={entries.length === 0 || save.isPending} onClick={() => save.mutate()}>
              <Save className="h-4 w-4" />
              {save.isPending ? t("common.saving") : `${t("hr.presence.save")} (${entries.length})`}
            </Button>
          )}
        </>
      }
    />
  );
}
