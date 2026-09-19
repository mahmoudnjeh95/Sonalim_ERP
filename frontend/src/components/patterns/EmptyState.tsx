import type { ReactNode } from "react";
import { motion } from "framer-motion";
import { cn } from "../../lib/utils";

export function EmptyState({
  icon,
  illustration,
  title,
  description,
  action,
}: {
  icon: ReactNode;
  /** Larger (ideally animated) artwork that replaces the icon badge. */
  illustration?: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className={cn(
        "flex flex-col items-center justify-center gap-3 text-center",
        illustration ? "py-8" : "py-14",
      )}
    >
      {illustration ? (
        <div aria-hidden="true">{illustration}</div>
      ) : (
        <div className="flex h-11 w-11 items-center justify-center rounded-full bg-muted text-muted-foreground">
          {icon}
        </div>
      )}
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <p className="mx-auto max-w-xs text-sm text-muted-foreground">{description}</p>
      </div>
      {action}
    </motion.div>
  );
}
