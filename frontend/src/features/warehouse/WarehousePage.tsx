import { useState, type ComponentType } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { BarChart3, Boxes, Coins, FileText, History as HistoryIcon, LayoutDashboard, ListTree, Lock, Package, Repeat } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { StickyTabBar } from "../../components/patterns/StickyTabBar";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { useAuth } from "../../lib/auth";
import ScanIcon from "../../assets/icons/warehouse/scan.svg?react";
import LocationTreeIcon from "../../assets/icons/warehouse/location-tree.svg?react";
import CountSheetIcon from "../../assets/icons/warehouse/count-sheet.svg?react";
import PutawayIcon from "../../assets/icons/warehouse/putaway.svg?react";
import ShipmentIcon from "../../assets/icons/warehouse/shipment.svg?react";
import { StockTab } from "./StockTab";
import { WarehouseOverviewTab } from "./WarehouseOverviewTab";
import { AnalysisTab } from "./AnalysisTab";
import { FinishedGoodsAnalysisTab } from "./FinishedGoodsAnalysisTab";
import { HistoryTab } from "./HistoryTab";
import { StockHistoryTab } from "./StockHistoryTab";
import { VouchersTab } from "./VouchersTab";
import { FrozenLocationsNotice } from "./FrozenLocationsNotice";
import { ScannerTab } from "./scanning/ScannerTab";
import { LocationsTab } from "./locations/LocationsTab";
import { CycleCountsTab } from "./cycleCounts/CycleCountsTab";
import { PutAwayTab } from "./putaway/PutAwayTab";
import { FulfillmentTab } from "./fulfillment/FulfillmentTab";
import { ReservationsTab } from "./reservations/ReservationsTab";
import { ValuationTab } from "./valuation/ValuationTab";
import { ReplenishmentTab } from "./replenishment/ReplenishmentTab";

// A tab with a `permission` is only shown to users who hold it -- stock value
// is financial information, not something every warehouse user should see.
const TABS: readonly {
  value: string;
  labelKey: TranslationKey;
  icon: ComponentType<{ className?: string }>;
  Component: ComponentType;
  permission?: string;
}[] = [
  { value: "overview", labelKey: "warehouse.tabs.overview", icon: LayoutDashboard, Component: WarehouseOverviewTab },
  { value: "stock", labelKey: "warehouse.tabs.stock", icon: Boxes, Component: StockTab },
  { value: "locations", labelKey: "warehouse.tabs.locations", icon: LocationTreeIcon, Component: LocationsTab },
  { value: "putaway", labelKey: "warehouse.tabs.putaway", icon: PutawayIcon, Component: PutAwayTab },
  { value: "fulfillment", labelKey: "warehouse.tabs.fulfillment", icon: ShipmentIcon, Component: FulfillmentTab },
  { value: "reservations", labelKey: "warehouse.tabs.reservations", icon: Lock, Component: ReservationsTab },
  { value: "cycle-counts", labelKey: "warehouse.tabs.cycleCounts", icon: CountSheetIcon, Component: CycleCountsTab },
  { value: "replenishment", labelKey: "warehouse.tabs.replenishment", icon: Repeat, Component: ReplenishmentTab, permission: "warehouse.view_replenishment" },
  { value: "valuation", labelKey: "warehouse.tabs.valuation", icon: Coins, Component: ValuationTab, permission: "warehouse.view_valuation" },
  { value: "analysis", labelKey: "warehouse.tabs.analysis", icon: BarChart3, Component: AnalysisTab },
  { value: "finished-goods-analysis", labelKey: "warehouse.tabs.finishedGoodsAnalysis", icon: Package, Component: FinishedGoodsAnalysisTab },
  { value: "history", labelKey: "warehouse.tabs.history", icon: HistoryIcon, Component: HistoryTab },
  { value: "stock-history", labelKey: "warehouse.tabs.stockHistory", icon: ListTree, Component: StockHistoryTab },
  { value: "vouchers", labelKey: "warehouse.tabs.vouchers", icon: FileText, Component: VouchersTab },
  { value: "scanning", labelKey: "warehouse.tabs.scanning", icon: ScanIcon, Component: ScannerTab },
];

type TabValue = string;

export function WarehousePage() {
  const { t } = useI18n();
  const { hasPermission } = useAuth();
  const [tab, setTab] = useState<TabValue>("overview");
  const tabs = TABS.filter((tabDef) => !tabDef.permission || hasPermission(tabDef.permission));
  const ActiveTab = (tabs.find((tabDef) => tabDef.value === tab) ?? tabs[0]).Component;

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("warehouse.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("warehouse.subtitle")}</p>
      </motion.div>

      <FrozenLocationsNotice />

      <StickyTabBar>
        <Tabs value={tab} onValueChange={(value) => setTab(value as TabValue)}>
          <TabsList>
            {tabs.map((tabDef) => (
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
