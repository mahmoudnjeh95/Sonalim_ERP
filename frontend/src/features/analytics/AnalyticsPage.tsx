import { useSearchParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Cog, FileSpreadsheet, PackageSearch, TrendingUp, Users } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { useI18n } from "../../lib/i18n";
import { TeamPerformanceTab } from "./TeamPerformanceTab";
import { MachinePerformanceTab } from "./MachinePerformanceTab";
import { ConsumptionReportTab } from "./ConsumptionReportTab";
import { ProductionRecapExportTab } from "./ProductionRecapExportTab";
import { PriceHistoryTab } from "./PriceHistoryTab";

// Cross-module KPIs — anything that reads more than one module's data to answer
// one question (here: production's reports and qc's quality reports, by team)
// lives here rather than inside the module whose tables happen to back it, so
// Production's tabs stay about the OF and Quality's about the report/NC record.
// Machine performance is single-module (production only), but sits beside team
// performance rather than inside a Production tab because it answers the same
// kind of cross-cutting "who/what is producing well" question, at a different grain.
// Consumption-by-supplier reads production's report tables *and* procurement's
// order history (for costing), so it belongs here for the same reason.
const TABS = [
  { value: "team-performance", labelKey: "analytics.tabs.teamPerformance", icon: Users, Component: TeamPerformanceTab },
  { value: "machine-performance", labelKey: "analytics.tabs.machinePerformance", icon: Cog, Component: MachinePerformanceTab },
  {
    value: "consumption-report",
    labelKey: "analytics.tabs.consumptionReport",
    icon: PackageSearch,
    Component: ConsumptionReportTab,
  },
  {
    value: "production-recap",
    labelKey: "analytics.tabs.productionRecap",
    icon: FileSpreadsheet,
    Component: ProductionRecapExportTab,
  },
  { value: "price-history", labelKey: "analytics.tabs.priceHistory", icon: TrendingUp, Component: PriceHistoryTab },
] as const;

type TabValue = (typeof TABS)[number]["value"];

export function AnalyticsPage() {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get("tab") as TabValue | null;
  const tab: TabValue = TABS.some((entry) => entry.value === requested) ? requested! : "team-performance";
  const setTab = (value: TabValue) => setSearchParams({ tab: value }, { replace: true });
  const ActiveTab = TABS.find((entry) => entry.value === tab)!.Component;

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("analytics.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("analytics.subtitle")}</p>
      </motion.div>

      {TABS.length > 1 && (
        <Tabs value={tab} onValueChange={(value) => setTab(value as TabValue)}>
          <TabsList>
            {TABS.map((tabDef) => (
              <TabsTrigger key={tabDef.value} value={tabDef.value} active={tab === tabDef.value} layoutId="analytics-tab-indicator">
                <span className="flex items-center gap-1.5">
                  <tabDef.icon className="h-4 w-4" />
                  {t(tabDef.labelKey)}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      )}

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
