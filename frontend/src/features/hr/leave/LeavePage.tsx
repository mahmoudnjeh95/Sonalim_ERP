import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { listEmployees } from "../api";
import { HrTabsPage, useBooted, useTabParam } from "../HrTabsPage";
import { HR_KEYS } from "../presenceApi";
import { LeaveBalancesTab } from "./LeaveBalancesTab";
import { LeaveRequestsTab } from "./LeaveRequestsTab";
import { LeaveTypesTab } from "./LeaveTypesTab";

const TABS = ["requests", "balances", "types"] as const;

export function LeavePage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const [tab, setTab] = useTabParam(TABS, "requests");
  const employees = useQuery({ queryKey: HR_KEYS.employees, queryFn: () => listEmployees(session!.token) });
  const booted = useBooted(!employees.isLoading);
  return (
    <HrTabsPage
      title={t("hr.leaveScreen.title")}
      subtitle={t("hr.leaveScreen.subtitle")}
      layoutId="hr-leave-tab"
      active={tab}
      onChange={setTab}
      booted={booted}
      loaderLabel={t("hr.leaveScreen.loading")}
      tabs={[
        { value: "requests", label: t("hr.leaveScreen.tab.requests"), content: <LeaveRequestsTab employees={employees.data ?? []} /> },
        { value: "balances", label: t("hr.leaveScreen.tab.balances"), content: <LeaveBalancesTab employees={employees.data ?? []} /> },
        { value: "types", label: t("hr.leaveScreen.tab.types"), content: <LeaveTypesTab /> },
      ]}
    />
  );
}
