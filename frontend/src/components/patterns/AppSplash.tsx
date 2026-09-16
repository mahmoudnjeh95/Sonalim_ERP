import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import OpeningSvg from "../../assets/animations/sonalim-erp-opening.svg?react";
import { useI18n } from "../../lib/i18n";

interface AppSplashProps {
  duration?: number;
  onFinished?: () => void;
}

export function AppSplash({ duration = 3200, onFinished }: AppSplashProps) {
  const { t } = useI18n();
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const id = window.setTimeout(() => setVisible(false), duration);
    return () => window.clearTimeout(id);
  }, [duration]);

  return (
    <AnimatePresence onExitComplete={onFinished}>
      {visible && (
        <motion.div
          key="splash"
          initial={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.45, ease: "easeOut" }}
          className="fixed inset-0 z-[9999] flex items-center justify-center overflow-hidden bg-[#071F43]"
        >
          <OpeningSvg className="block h-full w-full object-cover" aria-label="Sonalim ERP startup" />
          <div className="sr-only">{t("app.startingUp")}</div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
