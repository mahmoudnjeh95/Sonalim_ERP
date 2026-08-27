import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { BarChart3, Boxes, ListTree, Package, Tags, Warehouse as WarehouseIcon } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { useI18n } from "../../lib/i18n";
import { ProductListTab } from "./ProductListTab";
import { StocksTab } from "./StocksTab";
import { StocksByLotTab } from "./StocksByLotTab";
import { LotsSerialsTab } from "./LotsSerialsTab";
import { VariantAttributesTab } from "./VariantAttributesTab";
import { StatisticsTab } from "./StatisticsTab";

const TABS = [
  { value: "list", labelKey: "products.tabs.list", icon: Package, Component: ProductListTab },
  { value: "stocks", labelKey: "products.tabs.stocks", icon: WarehouseIcon, Component: StocksTab },
  { value: "stocks-by-lot", labelKey: "products.tabs.stocksByLot", icon: Boxes, Component: StocksByLotTab },
  { value: "lots-serials", labelKey: "products.tabs.lotsSerials", icon: ListTree, Component: LotsSerialsTab },
  { value: "variant-attributes", labelKey: "products.tabs.variantAttributes", icon: Tags, Component: VariantAttributesTab },
  { value: "statistics", labelKey: "products.tabs.statistics", icon: BarChart3, Component: StatisticsTab },
] as const;

type TabValue = (typeof TABS)[number]["value"];

export function ProductsPage() {
  const { t } = useI18n();
  const [tab, setTab] = useState<TabValue>("list");
  const ActiveTab = TABS.find((t) => t.value === tab)!.Component;

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("products.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("products.subtitle")}</p>
      </motion.div>

      <Tabs value={tab} onValueChange={(value) => setTab(value as TabValue)}>
        <TabsList>
          {TABS.map((tabDef) => (
            <TabsTrigger key={tabDef.value} value={tabDef.value} active={tab === tabDef.value} layoutId="products-tab-indicator">
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
