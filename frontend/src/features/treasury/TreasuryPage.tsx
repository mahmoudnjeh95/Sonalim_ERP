import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowDownToLine, ArrowUpFromLine, Banknote, BookOpen, Landmark, Settings as SettingsIcon, Wallet } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "../../components/ui/tabs";
import { StickyTabBar } from "../../components/patterns/StickyTabBar";
import { useI18n } from "../../lib/i18n";
import { AccountsTab } from "./AccountsTab";
import { BanksTab } from "./BanksTab";
import { TreasurySettingsTab } from "./TreasurySettingsTab";
import { PaymentsTab } from "./PaymentsTab";
import { InstrumentsTab } from "./InstrumentsTab";
import { CashJournalTab } from "./CashJournalTab";

const ReceiptsTab = () => <PaymentsTab direction="in" />;
const DisbursementsTab = () => <PaymentsTab direction="out" />;

const TABS = [
  { value: "accounts", labelKey: "treasury.tabs.accounts", icon: Wallet, Component: AccountsTab },
  { value: "receipts", labelKey: "treasury.tabs.receipts", icon: ArrowDownToLine, Component: ReceiptsTab },
  { value: "disbursements", labelKey: "treasury.tabs.disbursements", icon: ArrowUpFromLine, Component: DisbursementsTab },
  { value: "instruments", labelKey: "treasury.tabs.instruments", icon: Banknote, Component: InstrumentsTab },
  { value: "journal", labelKey: "treasury.tabs.journal", icon: BookOpen, Component: CashJournalTab },
  { value: "banks", labelKey: "treasury.tabs.banks", icon: Landmark, Component: BanksTab },
  { value: "settings", labelKey: "treasury.tabs.settings", icon: SettingsIcon, Component: TreasurySettingsTab },
] as const;

type TabValue = (typeof TABS)[number]["value"];

export function TreasuryPage() {
  const { t } = useI18n();
  const [tab, setTab] = useState<TabValue>("accounts");
  const ActiveTab = TABS.find((def) => def.value === tab)!.Component;

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("treasury.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("treasury.subtitle")}</p>
      </motion.div>

      <StickyTabBar>
        <Tabs value={tab} onValueChange={(value) => setTab(value as TabValue)}>
          <TabsList>
            {TABS.map((def) => (
              <TabsTrigger key={def.value} value={def.value} active={tab === def.value} layoutId="treasury-tab-indicator">
                <span className="flex items-center gap-1.5">
                  <def.icon className="h-4 w-4" />
                  {t(def.labelKey)}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </StickyTabBar>

      <AnimatePresence mode="wait">
        <motion.div key={tab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.2 }}>
          <ActiveTab />
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
