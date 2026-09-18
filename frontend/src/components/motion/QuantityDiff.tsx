import { motion } from "framer-motion";
import { cn } from "../../lib/utils";

interface QuantityDiffProps {
  from: string;
  to: string;
  className?: string;
}

/** Inline "before → after" quantity, e.g. for a stock adjustment confirmation. */
export function QuantityDiff({ from, to, className }: QuantityDiffProps) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 tabular-nums", className)}>
      <span className="text-muted-foreground line-through">{from}</span>
      <motion.span
        key={to}
        initial={{ opacity: 0, y: -4 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }}
        className="font-semibold text-primary"
      >
        {to}
      </motion.span>
    </span>
  );
}
