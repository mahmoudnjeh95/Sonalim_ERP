import { useSearchParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { CalendarDays, ClipboardList, PackageSearch, Repeat, Users, Wrench } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { StickyTabBar } from "../../components/patterns/StickyTabBar";
import { useI18n } from "../../lib/i18n";
import { useHasPermission } from "./hooks";
import { CalendarTab } from "./CalendarTab";
import { JobsTab } from "./JobsTab";
import { ProgramsTab } from "./ProgramsTab";
import { PartsTab } from "./PartsTab";
import { EquipmentTab } from "./EquipmentTab";
import { TeamsTab } from "./TeamsTab";

const ALL_TABS = [
  { value: "calendar", labelKey: "maintenance.tabs.calendar", icon: CalendarDays, Component: CalendarTab, permission: "maintenance.view_jobs" },
  { value: "jobs", labelKey: "maintenance.tabs.jobs", icon: ClipboardList, Component: JobsTab, permission: "maintenance.view_jobs" },
  { value: "programs", labelKey: "maintenance.tabs.programs", icon: Repeat, Component: ProgramsTab, permission: "maintenance.view_jobs" },
  { value: "parts", labelKey: "maintenance.tabs.parts", icon: PackageSearch, Component: PartsTab, permission: "maintenance.view_jobs" },
  { value: "equipment", labelKey: "maintenance.tabs.equipment", icon: Wrench, Component: EquipmentTab, permission: "maintenance.view_equipment" },
  { value: "teams", labelKey: "maintenance.tabs.teams", icon: Users, Component: TeamsTab, permission: "maintenance.view_jobs" },
] as const;

type TabValue = (typeof ALL_TABS)[number]["value"];

export function MaintenancePage() {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();

  // Each tab needs its own permission check (they're different hook calls),
  // so this can't be `.filter(() => useHasPermission(...))` — build the
  // visible list by checking every known permission up front instead.
  const hasViewJobs = useHasPermission("maintenance.view_jobs");
  const hasViewEquipment = useHasPermission("maintenance.view_equipment");
  const permissionGranted: Record<(typeof ALL_TABS)[number]["permission"], boolean> = {
    "maintenance.view_jobs": hasViewJobs,
    "maintenance.view_equipment": hasViewEquipment,
  };
  const tabs = ALL_TABS.filter((tabDef) => permissionGranted[tabDef.permission]);

  // The tab lives in the URL so a dashboard alert, a bookmark or a shared link
  // can land straight on the right screen.
  const requested = searchParams.get("tab") as TabValue | null;
  const fallback = tabs.some((entry) => entry.value === "calendar") ? "calendar" : tabs[0]?.value;
  const tab: TabValue | undefined = tabs.some((entry) => entry.value === requested) ? requested! : fallback;
  const setTab = (value: TabValue) => setSearchParams({ tab: value }, { replace: true });
  const activeTabDef = tabs.find((entry) => entry.value === tab);

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("maintenance.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("maintenance.subtitle")}</p>
      </motion.div>

      <StickyTabBar>
        <Tabs value={tab} onValueChange={(value) => setTab(value as TabValue)}>
          <TabsList>
            {tabs.map((tabDef) => (
              <TabsTrigger
                key={tabDef.value}
                value={tabDef.value}
                active={tab === tabDef.value}
                layoutId="maintenance-tab-indicator"
              >
                <span className="flex items-center gap-1.5">
                  <tabDef.icon className="h-4 w-4" />
                  {t(tabDef.labelKey)}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </StickyTabBar>

      <AnimatePresence mode="wait">
        {activeTabDef && (
          <motion.div
            key={activeTabDef.value}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
          >
            <activeTabDef.Component />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
