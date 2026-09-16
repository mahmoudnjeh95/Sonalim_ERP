import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import LogoMark from "../../assets/animations/logo-mark.svg?react";
import { useI18n } from "../../lib/i18n";

interface AppSplashProps {
  duration?: number;
  onFinished?: () => void;
}

export function AppSplash({ duration = 1600, onFinished }: AppSplashProps) {
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
          exit={{ opacity: 0 }}
          transition={{ duration: 0.45, ease: "easeOut" }}
          className="theme-login bg-background fixed inset-0 z-[9999] flex flex-col items-center justify-center gap-4"
        >
          <motion.div
            initial={{ opacity: 0, y: 16, scale: 0.92 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ duration: 0.5, ease: "easeOut" }}
            className="relative flex items-center justify-center text-primary"
          >
            <LogoMark className="h-24 w-24" />
            <div className="absolute flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-accent text-base font-bold text-primary-foreground shadow-glow">
              SE
            </div>
          </motion.div>
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.25, ease: "easeOut" }}
            className="text-center"
          >
            <p className="text-3xl font-bold text-foreground">
              Sonalim <span className="text-primary">ERP</span>
            </p>
            <p className="mt-1 text-xs uppercase tracking-[0.2em] text-muted-foreground">
              {t("app.tagline")}
            </p>
          </motion.div>
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4, delay: 0.4 }}
            className="text-sm text-muted-foreground"
          >
            {t("app.startingUp")}
          </motion.p>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
