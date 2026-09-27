import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { BarChart3, Boxes, History as HistoryIcon, LayoutDashboard, ListTree, Package } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { StickyTabBar } from "../../components/patterns/StickyTabBar";
import { useI18n } from "../../lib/i18n";
import ScanIcon from "../../assets/icons/warehouse/scan.svg?react";
import LocationTreeIcon from "../../assets/icons/warehouse/location-tree.svg?react";
import { StockTab } from "./StockTab";
import { WarehouseOverviewTab } from "./WarehouseOverviewTab";
import { AnalysisTab } from "./AnalysisTab";
import { FinishedGoodsAnalysisTab } from "./FinishedGoodsAnalysisTab";
import { HistoryTab } from "./HistoryTab";
import { StockHistoryTab } from "./StockHistoryTab";
import { ScannerTab } from "./scanning/ScannerTab";
import { LocationsTab } from "./locations/LocationsTab";

const TABS = [
  { value: "overview", labelKey: "warehouse.tabs.overview", icon: LayoutDashboard, Component: WarehouseOverviewTab },
  { value: "stock", labelKey: "warehouse.tabs.stock", icon: Boxes, Component: StockTab },
  { value: "locations", labelKey: "warehouse.tabs.locations", icon: LocationTreeIcon, Component: LocationsTab },
  { value: "analysis", labelKey: "warehouse.tabs.analysis", icon: BarChart3, Component: AnalysisTab },
  { value: "finished-goods-analysis", labelKey: "warehouse.tabs.finishedGoodsAnalysis", icon: Package, Component: FinishedGoodsAnalysisTab },
  { value: "history", labelKey: "warehouse.tabs.history", icon: HistoryIcon, Component: HistoryTab },
  { value: "stock-history", labelKey: "warehouse.tabs.stockHistory", icon: ListTree, Component: StockHistoryTab },
  { value: "scanning", labelKey: "warehouse.tabs.scanning", icon: ScanIcon, Component: ScannerTab },
] as const;

type TabValue = (typeof TABS)[number]["value"];

export function WarehousePage() {
  const { t } = useI18n();
  const [tab, setTab] = useState<TabValue>("overview");
  const ActiveTab = TABS.find((t) => t.value === tab)!.Component;

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("warehouse.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("warehouse.subtitle")}</p>
      </motion.div>

      <StickyTabBar>
        <Tabs value={tab} onValueChange={(value) => setTab(value as TabValue)}>
          <TabsList>
            {TABS.map((tabDef) => (
              <TabsTrigger key={tabDef.value} value={tabDef.value} active={tab === tabDef.value} layoutId="warehouse-tab-indicator">
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
