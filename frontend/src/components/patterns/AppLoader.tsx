import { motion } from "framer-motion";
import { useI18n } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import LoaderSvg from "../../assets/animations/sonalim-erp-loading.svg?react";

interface AppLoaderProps {
  label?: string;
  className?: string;
  fullScreen?: boolean;
}

export function AppLoader({ label, className, fullScreen = false }: AppLoaderProps) {
  const { t } = useI18n();

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex flex-col items-center justify-center gap-3 text-primary",
        fullScreen && "min-h-[60vh]",
        className,
      )}
    >
      <motion.div
        initial={{ opacity: 0, y: 8, scale: 0.96 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.35, ease: "easeOut" }}
        className="flex items-center justify-center"
      >
        <LoaderSvg className="h-[180px] w-[180px] drop-shadow-[0_18px_28px_rgba(18,59,109,0.15)]" />
      </motion.div>
      <motion.span
        initial={{ opacity: 0 }}
        animate={{ opacity: 0.8 }}
        transition={{ duration: 0.4, delay: 0.1 }}
        className="text-[15px] font-medium tracking-[0.08em] text-[#123B6D] uppercase"
      >
        {label ?? t("app.loading")}
      </motion.span>
    </div>
  );
}
