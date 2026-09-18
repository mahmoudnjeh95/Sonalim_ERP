import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "framer-motion";

interface CountUpProps {
  value: number;
  duration?: number;
  formatter?: (value: number) => string;
  className?: string;
}

/** Animates a KPI number counting up (or down) to `value` on change. */
export function CountUp({ value, duration = 450, formatter, className }: CountUpProps) {
  const [display, setDisplay] = useState(value);
  const fromRef = useRef(value);
  const prefersReducedMotion = useReducedMotion();

  useEffect(() => {
    const from = fromRef.current;
    if (prefersReducedMotion || from === value) {
      setDisplay(value);
      fromRef.current = value;
      return;
    }

    let frame: number;
    const start = performance.now();
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(Math.round(from + (value - from) * eased));
      if (progress < 1) {
        frame = requestAnimationFrame(tick);
      } else {
        fromRef.current = value;
      }
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration, prefersReducedMotion]);

  return <span className={className}>{formatter ? formatter(display) : display}</span>;
}
