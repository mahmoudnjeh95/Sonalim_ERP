import { useEffect, useRef } from "react";
import { animate, motion, useMotionValue, useReducedMotion, useTransform } from "framer-motion";

/** A number that eases to its new value (280ms). Takes a formatter so decimals, units and locale stay the caller's call. */
export function AnimatedValue({ value, format }: { value: number; format: (value: number) => string }) {
  const reduceMotion = useReducedMotion();
  const motionValue = useMotionValue(value);
  const text = useTransform(motionValue, format);
  const previous = useRef(value);

  useEffect(() => {
    if (reduceMotion || previous.current === value) {
      motionValue.set(value);
      previous.current = value;
      return;
    }
    const controls = animate(previous.current, value, {
      duration: 0.28,
      ease: "easeOut",
      onUpdate: (latest) => motionValue.set(latest),
    });
    previous.current = value;
    return () => controls.stop();
  }, [value, reduceMotion, motionValue]);

  return <motion.span>{text}</motion.span>;
}
