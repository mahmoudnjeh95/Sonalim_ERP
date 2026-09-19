import { useEffect, useRef, type ReactNode } from "react";
import { useReducedMotion } from "framer-motion";
import { cn } from "../../lib/utils";

/**
 * Wraps an inline SVG that animates itself with SMIL (<animate>), which the
 * CSS prefers-reduced-motion media query cannot switch off. Under reduced
 * motion the animation is paused on its first frame, so the asset stays
 * visible as a static graphic instead of looping.
 */
export function MotionSafeSvg({ children, className }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    const svg = ref.current?.querySelector("svg");
    if (!svg) return;
    if (reduceMotion) svg.pauseAnimations();
    else svg.unpauseAnimations();
  }, [reduceMotion]);

  return (
    <span ref={ref} className={cn("inline-flex", className)}>
      {children}
    </span>
  );
}
