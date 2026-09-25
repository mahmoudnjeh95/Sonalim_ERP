import { useSearchParams } from "react-router-dom";
import { AnimatePresence, MotionConfig, motion } from "framer-motion";
import { Cog, Factory, FileSpreadsheet, Gauge, HeartPulse, PackageSearch, Recycle, ShieldCheck, TrendingUp, Users, Zap } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { StickyTabBar } from "../../components/patterns/StickyTabBar";
import { useI18n } from "../../lib/i18n";
import { AnalyticsOverviewSection } from "./AnalyticsOverviewSection";
import { YieldWasteTab } from "./YieldWasteTab";
import { TeamPerformanceTab } from "./TeamPerformanceTab";
import { MachinePerformanceTab } from "./MachinePerformanceTab";
import { DowntimeAnalyticsTab } from "./DowntimeAnalyticsTab";
import { EnergyAnalyticsTab } from "./EnergyAnalyticsTab";
import { ShiftHealthTab } from "./ShiftHealthTab";
import { QualityAnalyticsTab } from "./QualityAnalyticsTab";
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
// order history (for costing), so it belongs here for the same reason. Quality
// reads qc's verdicts against production's lines, orders and team output --
// the QC page keeps the operational view (backlog, cases, follow-ups), this
// tab keeps the cross-module one.
//
// Two visual groups: "production" (how is the plant running) and "cost" (what
// does it cost) — same ?tab= param, grouped only for the reader's sake now that
// the list has grown past what one flat row reads well at.
const TABS = [
  { value: "overview", labelKey: "analytics.tabs.overview", icon: Factory, Component: AnalyticsOverviewSection, group: "production" },
  { value: "yield-waste", labelKey: "analytics.tabs.yieldWaste", icon: Recycle, Component: YieldWasteTab, group: "production" },
  { value: "team-performance", labelKey: "analytics.tabs.teamPerformance", icon: Users, Component: TeamPerformanceTab, group: "production" },
  { value: "machine-performance", labelKey: "analytics.tabs.machinePerformance", icon: Cog, Component: MachinePerformanceTab, group: "production" },
  { value: "downtime", labelKey: "analytics.tabs.downtime", icon: Gauge, Component: DowntimeAnalyticsTab, group: "production" },
  { value: "energy", labelKey: "analytics.tabs.energy", icon: Zap, Component: EnergyAnalyticsTab, group: "production" },
  { value: "quality", labelKey: "analytics.tabs.quality", icon: ShieldCheck, Component: QualityAnalyticsTab, group: "production" },
  { value: "shift-health", labelKey: "analytics.tabs.shiftHealth", icon: HeartPulse, Component: ShiftHealthTab, group: "production" },
  {
    value: "consumption-report",
    labelKey: "analytics.tabs.consumptionReport",
    icon: PackageSearch,
    Component: ConsumptionReportTab,
    group: "cost",
  },
  {
    value: "production-recap",
    labelKey: "analytics.tabs.productionRecap",
    icon: FileSpreadsheet,
    Component: ProductionRecapExportTab,
    group: "cost",
  },
  { value: "price-history", labelKey: "analytics.tabs.priceHistory", icon: TrendingUp, Component: PriceHistoryTab, group: "cost" },
] as const;

type TabValue = (typeof TABS)[number]["value"];
type TabGroup = (typeof TABS)[number]["group"];
const GROUPS: { group: TabGroup; labelKey: "analytics.group.production" | "analytics.group.cost" }[] = [
  { group: "production", labelKey: "analytics.group.production" },
  { group: "cost", labelKey: "analytics.group.cost" },
];

export function AnalyticsPage() {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get("tab") as TabValue | null;
  const tab: TabValue = TABS.some((entry) => entry.value === requested) ? requested! : "overview";
  const setTab = (value: TabValue) => setSearchParams({ tab: value }, { replace: true });
  const ActiveTab = TABS.find((entry) => entry.value === tab)!.Component;

  return (
    <MotionConfig reducedMotion="user">
      <div className="space-y-6">
        <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
          <h1 className="text-xl font-semibold tracking-tight">{t("analytics.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("analytics.subtitle")}</p>
        </motion.div>

        <StickyTabBar className="flex flex-wrap gap-x-6 gap-y-3">
          {GROUPS.map(({ group, labelKey }) => (
            <div key={group} className="min-w-0 space-y-1.5">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{t(labelKey)}</p>
              <Tabs value={tab} onValueChange={(value) => setTab(value as TabValue)}>
                <TabsList>
                  {TABS.filter((entry) => entry.group === group).map((tabDef) => (
                    // One indicator per group: a shared layoutId cannot slide between two Tabs trees.
                    <TabsTrigger key={tabDef.value} value={tabDef.value} active={tab === tabDef.value} layoutId={`analytics-tab-indicator-${group}`}>
                      <span className="flex items-center gap-1.5">
                        <tabDef.icon className="h-4 w-4" />
                        {t(tabDef.labelKey)}
                      </span>
                    </TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>
            </div>
          ))}
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
    </MotionConfig>
  );
}
