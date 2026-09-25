import { useSearchParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Wrench } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { StickyTabBar } from "../../components/patterns/StickyTabBar";
import { useI18n } from "../../lib/i18n";
import { EquipmentTab } from "./EquipmentTab";

const TABS = [{ value: "equipment", labelKey: "maintenance.tabs.equipment", icon: Wrench, Component: EquipmentTab }] as const;

type TabValue = (typeof TABS)[number]["value"];

export function MaintenancePage() {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  // The tab lives in the URL so a dashboard alert, a bookmark or a shared link
  // can land straight on the right screen.
  const requested = searchParams.get("tab") as TabValue | null;
  const tab: TabValue = TABS.some((entry) => entry.value === requested) ? requested! : "equipment";
  const setTab = (value: TabValue) => setSearchParams({ tab: value }, { replace: true });
  const ActiveTab = TABS.find((entry) => entry.value === tab)!.Component;

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("maintenance.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("maintenance.subtitle")}</p>
      </motion.div>

      <StickyTabBar>
        <Tabs value={tab} onValueChange={(value) => setTab(value as TabValue)}>
          <TabsList>
            {TABS.map((tabDef) => (
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
        <motion.div
          key={tab}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.2 }}
        >
          <ActiveTab />
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
