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
        className="relative flex items-center justify-center"
      >
        <motion.div
          aria-hidden="true"
          className="absolute inset-[-26px] rounded-[32px] border border-[#F5A900]/40"
          animate={{ scale: [1, 1.08, 1], opacity: [0.25, 0.8, 0.25] }}
          transition={{ duration: 2.1, repeat: Infinity, ease: "easeInOut" }}
        />
        <div className="absolute inset-[-24px] rounded-full bg-[#123B6D]/10 blur-3xl" />
        <motion.div
          animate={{ boxShadow: ["0_0_0_rgba(245,169,0,0)", "0_0_30px_rgba(245,169,0,0.18)", "0_0_0_rgba(245,169,0,0)"] }}
          transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
          className="relative flex h-52 w-52 items-center justify-center rounded-[30px] border border-[#123B6D]/15 bg-[#071F43] shadow-[0_24px_50px_rgba(7,31,67,0.22)]"
        >
          <LoaderSvg className="h-[180px] w-[180px]" />
        </motion.div>
      </motion.div>
      <motion.span
        initial={{ opacity: 0 }}
        animate={{ opacity: 0.8 }}
        transition={{ duration: 0.4, delay: 0.1 }}
        className="text-[15px] font-medium tracking-[0.12em] text-[#123B6D] uppercase"
      >
        {label ?? t("app.loading")}
      </motion.span>
    </div>
  );
}
