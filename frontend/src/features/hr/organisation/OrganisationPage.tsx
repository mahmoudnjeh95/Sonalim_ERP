import type { ComponentType } from "react";
import { useSearchParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Building2, Layers, Settings, Tag } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { StickyTabBar } from "../../../components/patterns/StickyTabBar";
import { Tabs, TabsList, TabsTrigger } from "../../../components/ui/tabs";
import { DepartmentsTab } from "./DepartmentsTab";
import { GradesTab } from "./GradesTab";
import { HrSettingsTab } from "./HrSettingsTab";
import { PositionsTab } from "./PositionsTab";

type TabValue = "departments" | "positions" | "grades" | "settings";
const TABS: { value: TabValue; labelKey: TranslationKey; icon: ComponentType<{ className?: string }>; permission: string; Component: ComponentType }[] = [
  { value: "departments", labelKey: "hr.org.tab.departments", icon: Building2, permission: "hr.view_departments", Component: DepartmentsTab },
  { value: "positions", labelKey: "hr.org.tab.positions", icon: Tag, permission: "hr.view_positions", Component: PositionsTab },
  { value: "grades", labelKey: "hr.org.tab.grades", icon: Layers, permission: "hr.view_positions", Component: GradesTab },
  { value: "settings", labelKey: "hr.org.tab.settings", icon: Settings, permission: "hr.view_employees", Component: HrSettingsTab },
];

export function OrganisationPage() {
  const { hasPermission } = useAuth();
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const tabs = TABS.filter((entry) => hasPermission(entry.permission));
  const active = tabs.find((entry) => entry.value === searchParams.get("tab")) ?? tabs[0];

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("hr.org.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("hr.org.subtitle")}</p>
      </motion.div>
      {!active ? (
        <EmptyState icon={<Building2 className="h-5 w-5" />} title={t("hr.org.noAccess.title")} description={t("hr.org.noAccess.description")} />
      ) : (
        <>
          <StickyTabBar>
            <Tabs value={active.value} onValueChange={(value) => setSearchParams({ tab: value }, { replace: true })}>
              <TabsList>
                {tabs.map((entry) => (
                  <TabsTrigger key={entry.value} value={entry.value} active={active.value === entry.value} layoutId="hr-organisation-tab">
                    <span className="flex items-center gap-1.5">
                      <entry.icon className="h-4 w-4" />
                      {t(entry.labelKey)}
                    </span>
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          </StickyTabBar>
          <AnimatePresence mode="wait">
            <motion.div key={active.value} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.2 }}>
              <active.Component />
            </motion.div>
          </AnimatePresence>
        </>
      )}
    </div>
  );
}
