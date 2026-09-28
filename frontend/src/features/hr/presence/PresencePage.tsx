import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { listDepartments, listEmployees } from "../api";
import { HrTabsPage, useBooted, useTabParam } from "../HrTabsPage";
import { HR_KEYS, listSchedules } from "../presenceApi";
import { DayGridTab } from "./DayGridTab";
import { EmployeeMonthTab } from "./EmployeeMonthTab";
import { MonthCloseTab } from "./MonthCloseTab";
import { WeekGridTab } from "./WeekGridTab";

const TABS = ["day", "week", "calendar", "month"] as const;

export function PresencePage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [tab, setTab] = useTabParam(TABS, "day");
  const departments = useQuery({ queryKey: HR_KEYS.departments, queryFn: () => listDepartments(token) });
  const schedules = useQuery({ queryKey: HR_KEYS.schedules, queryFn: () => listSchedules(token) });
  const employees = useQuery({ queryKey: HR_KEYS.employees, queryFn: () => listEmployees(token) });
  const booted = useBooted(!departments.isLoading && !schedules.isLoading && !employees.isLoading);
  const teams = { departments: departments.data ?? [], schedules: schedules.data ?? [] };
  return (
    <HrTabsPage
      title={t("hr.presence.title")}
      subtitle={t("hr.presence.subtitle")}
      layoutId="hr-presence-tab"
      active={tab}
      onChange={setTab}
      booted={booted}
      loaderLabel={t("hr.presence.loading")}
      tabs={[
        { value: "day", label: t("hr.presence.tab.day"), content: <DayGridTab {...teams} /> },
        { value: "week", label: t("hr.presence.tab.week"), content: <WeekGridTab {...teams} /> },
        { value: "calendar", label: t("hr.presence.tab.calendar"), content: <EmployeeMonthTab employees={employees.data ?? []} /> },
        { value: "month", label: t("hr.presence.tab.month"), content: <MonthCloseTab employees={employees.data ?? []} /> },
      ]}
    />
  );
}
