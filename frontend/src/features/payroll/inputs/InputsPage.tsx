import type { ComponentType } from "react";
import { useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { HandCoins, ListChecks, PiggyBank } from "lucide-react";
import { StickyTabBar } from "../../../components/patterns/StickyTabBar";
import { Card, CardContent } from "../../../components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "../../../components/ui/tabs";
import { useI18n, type TranslationKey } from "../../../lib/i18n";
import { AdvancesTab } from "./AdvancesTab";
import { LoansTab } from "./LoansTab";
import { RunInputsTab } from "./RunInputsTab";

type Tab = "runInputs" | "advances" | "loans";

const TABS: { value: Tab; labelKey: TranslationKey; icon: ComponentType<{ className?: string }> }[] = [
  { value: "runInputs", labelKey: "payroll.inputs.tab.runInputs", icon: ListChecks },
  { value: "advances", labelKey: "payroll.inputs.tab.advances", icon: HandCoins },
  { value: "loans", labelKey: "payroll.inputs.tab.loans", icon: PiggyBank },
];

/** /payroll/inputs — one-off inputs of a run, salary advances and loans. Reads need payroll.view_runs, writes payroll.manage_inputs. */
export function InputsPage() {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  // The tab lives in the URL (?tab=), next to the run-inputs tab's ?run=, so a link can land on either.
  const tab: Tab = TABS.find((entry) => entry.value === searchParams.get("tab"))?.value ?? "runInputs";
  const setTab = (value: Tab) => {
    const next = new URLSearchParams(searchParams);
    next.set("tab", value);
    setSearchParams(next, { replace: true });
  };

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("payroll.inputs.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("payroll.inputs.subtitle")}</p>
      </motion.div>

      <StickyTabBar>
        <Tabs value={tab} onValueChange={(value) => setTab(value as Tab)}>
          <TabsList>
            {TABS.map((entry) => (
              <TabsTrigger key={entry.value} value={entry.value} active={tab === entry.value} layoutId="payroll-inputs-tab">
                <span className="flex items-center gap-1.5">
                  <entry.icon className="h-4 w-4" />
                  {t(entry.labelKey)}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </StickyTabBar>

      <Card>
        <CardContent className="pt-6">
          {tab === "runInputs" && <RunInputsTab />}
          {tab === "advances" && <AdvancesTab />}
          {tab === "loans" && <LoansTab />}
        </CardContent>
      </Card>
    </div>
  );
}
