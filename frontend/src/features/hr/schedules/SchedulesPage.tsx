import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { HrTabsPage, useBooted, useTabParam } from "../HrTabsPage";
import { HR_KEYS, listSchedules } from "../presenceApi";
import { AssignmentsTab } from "./AssignmentsTab";
import { HolidaysTab } from "./HolidaysTab";
import { PresenceSettingsCard } from "./PresenceSettingsCard";
import { RotationsTab } from "./RotationsTab";
import { WorkSchedulesTab } from "./WorkSchedulesTab";

const TABS = ["schedules", "rotations", "assignments", "holidays", "settings"] as const;

export function SchedulesPage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const [tab, setTab] = useTabParam(TABS, "schedules");
  const schedules = useQuery({ queryKey: HR_KEYS.schedules, queryFn: () => listSchedules(session!.token) });
  const booted = useBooted(!schedules.isLoading);
  return (
    <HrTabsPage
      title={t("hr.schedules.title")}
      subtitle={t("hr.schedules.subtitle")}
      layoutId="hr-schedules-tab"
      active={tab}
      onChange={setTab}
      booted={booted}
      loaderLabel={t("hr.schedules.loading")}
      tabs={[
        { value: "schedules", label: t("hr.schedules.tab.schedules"), content: <WorkSchedulesTab /> },
        { value: "rotations", label: t("hr.schedules.tab.rotations"), content: <RotationsTab /> },
        { value: "assignments", label: t("hr.schedules.tab.assignments"), content: <AssignmentsTab /> },
        { value: "holidays", label: t("hr.schedules.tab.holidays"), content: <HolidaysTab /> },
        { value: "settings", label: t("hr.schedules.tab.settings"), content: <PresenceSettingsCard /> },
      ]}
    />
  );
}
