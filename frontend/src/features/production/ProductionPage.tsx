import { useSearchParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Boxes, Factory, LayoutDashboard, NotebookPen, Recycle, Settings, Tag } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { outlineIcon } from "../../components/patterns/outlineIcon";
import { useI18n } from "../../lib/i18n";
import ApprovalIcon from "../../assets/icons/quality/approval.svg?react";
import ExtrusionIcon from "../../assets/icons/production/extrusion.svg?react";
import LabIcon from "../../assets/icons/quality/lab.svg?react";
import PackagingIcon from "../../assets/icons/production/packaging.svg?react";
import PlanningIcon from "../../assets/icons/production/planning.svg?react";
import WorkOrderIcon from "../../assets/icons/production/work-order.svg?react";
import { WorkOrdersTab } from "./WorkOrdersTab";
import { PlanningTab } from "./PlanningTab";
import { PackagingBomsTab } from "./PackagingBomsTab";
import { ProductClassificationsTab } from "./ProductClassificationsTab";
import { WorkCentersTab } from "./WorkCentersTab";
import { MoldsTab } from "./MoldsTab";
import { RecipesTab } from "./RecipesTab";
import { RegrindTab } from "./RegrindTab";
import { DailyReportsTab } from "./DailyReportsTab";
import { ConditionnementTab } from "./ConditionnementTab";
import { ValidationCenterTab } from "./ValidationCenterTab";
import { ProductionDashboardTab } from "./ProductionDashboardTab";
import { ProductionSettingsTab } from "./ProductionSettingsTab";

const TABS = [
  { value: "dashboard", labelKey: "production.tabs.dashboard", icon: LayoutDashboard, Component: ProductionDashboardTab },
  { value: "work-orders", labelKey: "production.tabs.workOrders", icon: outlineIcon(WorkOrderIcon), Component: WorkOrdersTab },
  { value: "planning", labelKey: "production.tabs.planning", icon: outlineIcon(PlanningIcon), Component: PlanningTab },
  { value: "daily-reports", labelKey: "production.tabs.dailyReports", icon: NotebookPen, Component: DailyReportsTab },
  { value: "conditionnement", labelKey: "production.tabs.conditionnement", icon: outlineIcon(PackagingIcon), Component: ConditionnementTab },
  { value: "validation", labelKey: "production.tabs.validation", icon: outlineIcon(ApprovalIcon), Component: ValidationCenterTab },
  { value: "recipes", labelKey: "production.tabs.recipes", icon: outlineIcon(LabIcon), Component: RecipesTab },
  { value: "regrind", labelKey: "production.tabs.regrind", icon: Recycle, Component: RegrindTab },
  { value: "work-centers", labelKey: "production.tabs.workCenters", icon: Factory, Component: WorkCentersTab },
  { value: "molds", labelKey: "production.tabs.molds", icon: outlineIcon(ExtrusionIcon), Component: MoldsTab },
  { value: "packaging-boms", labelKey: "production.tabs.packagingBoms", icon: Boxes, Component: PackagingBomsTab },
  { value: "classifications", labelKey: "production.tabs.classifications", icon: Tag, Component: ProductClassificationsTab },
  { value: "settings", labelKey: "production.tabs.settings", icon: Settings, Component: ProductionSettingsTab },
] as const;

type TabValue = (typeof TABS)[number]["value"];

export function ProductionPage() {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  // The tab lives in the URL so a dashboard alert, a bookmark or a shared link
  // can land straight on the right screen.
  const requested = searchParams.get("tab") as TabValue | null;
  const tab: TabValue = TABS.some((entry) => entry.value === requested) ? requested! : "dashboard";
  const setTab = (value: TabValue) => setSearchParams({ tab: value }, { replace: true });
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
