import type { HTMLMotionProps } from "framer-motion";

const ROW_STAGGER_SECONDS = 0.035;
const ROW_STAGGER_CAP = 8;
const EASE = [0.2, 0.8, 0.2, 1] as const;

/**
 * Spread onto a `motion.tr` (or any motion element) rendered inside an
 * `AnimatePresence` list. Delay is capped so a long table doesn't keep
 * animating rows in for seconds after the first paint.
 */
export function rowEnterProps(index = 0): HTMLMotionProps<"tr"> {
  return {
    layout: true,
    initial: { opacity: 0, y: -6 },
    animate: { opacity: 1, y: 0 },
    exit: { opacity: 0 },
    transition: {
      duration: 0.22,
      ease: EASE,
      delay: Math.min(index, ROW_STAGGER_CAP) * ROW_STAGGER_SECONDS,
    },
  };
}

/**
 * Same entrance as `rowEnterProps`, plus a one-shot gold glow that draws the
 * eye to a row that just appeared as a result of the user's own action (e.g.
 * a work order created from a suggestion), as opposed to routine list data.
 */
export function highlightRowEnterProps(index = 0): HTMLMotionProps<"tr"> {
  const base = rowEnterProps(index);
  return {
    ...base,
    animate: {
      opacity: 1,
      y: 0,
      backgroundColor: ["rgba(245,169,0,0)", "rgba(245,169,0,0.16)", "rgba(245,169,0,0)"],
    },
    transition: {
      ...base.transition,
      backgroundColor: { duration: 0.9, ease: "easeOut", delay: (base.transition?.delay ?? 0) + 0.18 },
    },
  };
}
