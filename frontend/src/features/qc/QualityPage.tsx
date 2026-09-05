import { useSearchParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { AlertOctagon, FlaskConical, LayoutDashboard } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { useI18n } from "../../lib/i18n";
import { QualityDashboardTab } from "./QualityDashboardTab";
import { QualityReportsTab } from "./QualityReportsTab";
import { NonConformitiesTab } from "./NonConformitiesTab";

const TABS = [
  { value: "dashboard", labelKey: "qc.tabs.dashboard", icon: LayoutDashboard, Component: QualityDashboardTab },
  { value: "reports", labelKey: "qc.tabs.qualityReports", icon: FlaskConical, Component: QualityReportsTab },
  { value: "non-conformities", labelKey: "qc.tabs.nonConformities", icon: AlertOctagon, Component: NonConformitiesTab },
] as const;

type TabValue = (typeof TABS)[number]["value"];

export function QualityPage() {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  // The tab lives in the URL so a dashboard alert, a bookmark or a shared link
  // can land straight on the right screen.
  const requested = searchParams.get("tab") as TabValue | null;
  const tab: TabValue = TABS.some((entry) => entry.value === requested) ? requested! : "dashboard";
  const setTab = (value: TabValue) => setSearchParams({ tab: value }, { replace: true });
  const ActiveTab = TABS.find((entry) => entry.value === tab)!.Component;

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("qc.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("qc.subtitle")}</p>
      </motion.div>

      <Tabs value={tab} onValueChange={(value) => setTab(value as TabValue)}>
        <TabsList>
          {TABS.map((tabDef) => (
            <TabsTrigger
              key={tabDef.value}
              value={tabDef.value}
              active={tab === tabDef.value}
              layoutId="qc-tab-indicator"
            >
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
