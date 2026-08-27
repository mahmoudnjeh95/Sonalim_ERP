import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Beaker, Boxes, ClipboardList, Factory, Recycle, Tag, Wrench } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { useI18n } from "../../lib/i18n";
import { WorkOrdersTab } from "./WorkOrdersTab";
import { PackagingBomsTab } from "./PackagingBomsTab";
import { ProductClassificationsTab } from "./ProductClassificationsTab";
import { WorkCentersTab } from "./WorkCentersTab";
import { MachinesTab } from "./MachinesTab";
import { RecipesTab } from "./RecipesTab";
import { RegrindTab } from "./RegrindTab";

const TABS = [
  { value: "work-orders", labelKey: "production.tabs.workOrders", icon: ClipboardList, Component: WorkOrdersTab },
  { value: "recipes", labelKey: "production.tabs.recipes", icon: Beaker, Component: RecipesTab },
  { value: "regrind", labelKey: "production.tabs.regrind", icon: Recycle, Component: RegrindTab },
  { value: "work-centers", labelKey: "production.tabs.workCenters", icon: Factory, Component: WorkCentersTab },
  { value: "machines", labelKey: "production.tabs.machines", icon: Wrench, Component: MachinesTab },
  { value: "packaging-boms", labelKey: "production.tabs.packagingBoms", icon: Boxes, Component: PackagingBomsTab },
  { value: "classifications", labelKey: "production.tabs.classifications", icon: Tag, Component: ProductClassificationsTab },
] as const;

type TabValue = (typeof TABS)[number]["value"];

export function ProductionPage() {
  const { t } = useI18n();
  const [tab, setTab] = useState<TabValue>("work-orders");
  const ActiveTab = TABS.find((t) => t.value === tab)!.Component;

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("production.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("production.subtitle")}</p>
      </motion.div>

      <Tabs value={tab} onValueChange={(value) => setTab(value as TabValue)}>
        <TabsList>
          {TABS.map((tabDef) => (
            <TabsTrigger key={tabDef.value} value={tabDef.value} active={tab === tabDef.value} layoutId="production-tab-indicator">
              <span className="flex items-center gap-1.5">
                <tabDef.icon className="h-4 w-4" />
                {t(tabDef.labelKey)}
              </span>
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

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
