import { motion } from "framer-motion";
import { useI18n } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { TableCell, TableRow } from "../ui/table";
import LoaderSvg from "../../assets/animations/sonalim-erp-loading.svg?react";

interface AppLoaderProps {
  label?: string;
  className?: string;
  fullScreen?: boolean;
  /** SVG edge in px. 180 for a page/tab body; go smaller inside cards and dialogs. */
  size?: number;
}

/** Full-width loader row for a table body while its query is loading. */
export function TableLoadingRow({ colSpan, label }: { colSpan: number; label?: string }) {
  return (
    <TableRow>
      <TableCell colSpan={colSpan} className="p-0">
        <AppLoader label={label} className="py-8" />
      </TableCell>
    </TableRow>
  );
}

export function AppLoader({ label, className, fullScreen = false, size = 180 }: AppLoaderProps) {
  const compact = size < 140;
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
        <div className={cn("absolute rounded-full bg-[#123B6D]/10 blur-3xl", compact ? "inset-[-12px]" : "inset-[-24px]")} />
        <motion.div
          animate={{ filter: ["drop-shadow(0 0 0 rgba(245,169,0,0))", "drop-shadow(0 0 20px rgba(245,169,0,0.35))", "drop-shadow(0 0 0 rgba(245,169,0,0))"] }}
          transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
          className="relative flex items-center justify-center"
          style={{ width: size * 1.15, height: size * 1.15 }}
        >
          <LoaderSvg width={size} height={size} />
        </motion.div>
      </motion.div>
      <motion.span
        initial={{ opacity: 0 }}
        animate={{ opacity: 0.8 }}
        transition={{ duration: 0.4, delay: 0.1 }}
        className={cn("font-medium tracking-[0.12em] text-[#123B6D] uppercase", compact ? "text-xs" : "text-[15px]")}
      >
        {label ?? t("app.loading")}
      </motion.span>
    </div>
  );
}
