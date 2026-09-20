import { motion } from "framer-motion";
import { useI18n } from "../../lib/i18n";
import { ProductionBoard } from "./board/ProductionBoard";

/** The production board as its own sidebar destination, not a tab of the work-order page. */
export function ProductionDashboardPage() {
  const { t } = useI18n();

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("nav.dashboard")}</h1>
      </motion.div>
      <ProductionBoard />
    </div>
  );
}
