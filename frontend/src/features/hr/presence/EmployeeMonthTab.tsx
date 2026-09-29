import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { Select } from "../../../components/ui/select";
import { Skeleton } from "../../../components/ui/skeleton";
import { Badge } from "../../../components/ui/badge";
import { cn } from "../../../lib/utils";
import type { Employee } from "../api";
import { HR_KEYS, getEmployeeMonth, getMonthSummary, type MonthSummary } from "../presenceApi";
import { employeeLabel, formatDuration, todayIso, weekdayOf } from "../presenceFormat";
import { PresenceStatusBadge, WEEKDAY_SHORT_KEYS } from "./PresenceStatusBadge";

export const SUMMARY_TILES: { key: keyof MonthSummary; label: TranslationKey; minutes?: boolean }[] = [
  { key: "scheduled_days", label: "hr.presence.summary.scheduledDays" },
  { key: "worked_days", label: "hr.presence.summary.workedDays" },
  { key: "unpaid_absence_days", label: "hr.presence.summary.unpaidAbsenceDays" },
  { key: "paid_leave_days", label: "hr.presence.summary.paidLeaveDays" },
  { key: "sick_days", label: "hr.presence.summary.sickDays" },
  { key: "holiday_days", label: "hr.presence.summary.holidayDays" },
  { key: "holidays_worked_days", label: "hr.presence.summary.holidaysWorkedDays" },
  { key: "ot_minutes_day", label: "hr.presence.summary.otDay", minutes: true },
  { key: "ot_minutes_night", label: "hr.presence.summary.otNight", minutes: true },
  { key: "ot_minutes_rest_holiday", label: "hr.presence.summary.otRestHoliday", minutes: true },
  { key: "night_minutes", label: "hr.presence.summary.nightHours", minutes: true },
  { key: "late_minutes", label: "hr.presence.summary.lateMinutes", minutes: true },
];


export function EmployeeMonthTab({ employees }: { employees: Employee[] }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [employeeId, setEmployeeId] = useState("");
  const [month, setMonth] = useState(todayIso().slice(0, 7));
  const period = `${month}-01`;
  const detail = useQuery({
    queryKey: [...HR_KEYS.presence, "employee-month", employeeId, period],
    queryFn: () => getEmployeeMonth(token, employeeId, period),
    enabled: employeeId !== "",
  });
  const summary = useQuery({
    queryKey: [...HR_KEYS.presence, "summary", period, employeeId],
    queryFn: () => getMonthSummary(token, period, employeeId),
    enabled: employeeId !== "",
  });
  const figures = summary.data?.[0];
  const days = detail.data?.days ?? [];
  const leading = days.length ? weekdayOf(days[0].work_date) : 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Select aria-label={t("hr.common.employee")} value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
          <option value="">{t("hr.presence.pickEmployee")}</option>
          {employees.map((employee) => (
            <option key={employee.id} value={employee.id}>{employeeLabel(employee)}</option>
          ))}
        </Select>
        <input type="month" aria-label={t("hr.presence.month")} className="h-9 rounded-md border border-border bg-background px-2 text-sm" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} />
        {detail.data?.closed && (
          <Badge variant="default"><Lock className="mr-1 h-3 w-3" />{t("hr.presence.months.status.closed")}</Badge>
        )}
      </div>
      {employeeId && detail.isLoading && <Skeleton className="h-96 w-full" />}
      {detail.data && (
        <>
          <div className="grid grid-cols-7 gap-1 text-xs">
            {WEEKDAY_SHORT_KEYS.map((key) => (
              <div key={key} className="px-1 font-medium text-muted-foreground">{t(key)}</div>
            ))}
            {Array.from({ length: leading }, (_, i) => <div key={`pad-${i}`} />)}
            {days.map((day) => {
              const record = day.record;
              const overtime = record ? record.ot_minutes_day + record.ot_minutes_night + record.ot_minutes_rest_holiday : 0;
              return (
                <div
                  key={day.work_date}
                  className={cn("min-h-20 space-y-1 rounded-md border border-border p-1.5", !day.employed && "opacity-40", day.is_holiday && "bg-accent/5")}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{Number(day.work_date.slice(8, 10))}</span>
                    {record?.locked && <Lock className="h-3 w-3 text-muted-foreground" />}
                  </div>
                  {record ? (
                    <PresenceStatusBadge status={record.status} />
                  ) : day.default_status ? (
                    <span className="text-muted-foreground">{t("hr.presence.planned")}</span>
                  ) : null}
                  {record && record.worked_minutes > 0 && <div className="tabular-nums">{formatDuration(record.worked_minutes)}</div>}
                  {overtime > 0 && <div className="tabular-nums text-warning">+{formatDuration(overtime)}</div>}
                </div>
              );
            })}
          </div>
          {figures && (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
              {SUMMARY_TILES.map((tile) => (
                <div key={tile.key} className="rounded-md border border-border p-2">
                  <p className="text-lg font-semibold tabular-nums">
                    {tile.minutes ? formatDuration(Number(figures[tile.key])) : figures[tile.key]}
                  </p>
                  <p className="text-xs text-muted-foreground">{t(tile.label)}</p>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
