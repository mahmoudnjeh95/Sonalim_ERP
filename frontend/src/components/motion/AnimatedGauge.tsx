import { motion, useReducedMotion } from "framer-motion";
import { cn } from "../../lib/utils";

interface AnimatedGaugeProps {
  /** 0-100. Values outside that range are clamped. */
  percent: number;
  tone?: "success" | "warning" | "destructive";
  className?: string;
}

const TONE_CLASS: Record<NonNullable<AnimatedGaugeProps["tone"]>, string> = {
  success: "bg-success",
  warning: "bg-warning",
  destructive: "bg-destructive",
};

/** Thin fill gauge, e.g. for how much of a tolerance band a variance has used. */
export function AnimatedGauge({ percent, tone = "success", className }: AnimatedGaugeProps) {
  const clamped = Math.max(0, Math.min(100, percent));
  const prefersReducedMotion = useReducedMotion();

  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-muted", className)}>
      <motion.div
        className={cn("h-full rounded-full", TONE_CLASS[tone])}
        initial={{ width: prefersReducedMotion ? `${clamped}%` : 0 }}
        animate={{ width: `${clamped}%` }}
        transition={{ duration: prefersReducedMotion ? 0 : 0.45, ease: [0.2, 0.8, 0.2, 1] }}
      />
    </div>
  );
}
