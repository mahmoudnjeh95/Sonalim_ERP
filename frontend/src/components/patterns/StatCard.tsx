import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { animate, motion, useMotionValue, useTransform } from "framer-motion";
import { Card } from "../ui/card";
import { cn } from "../../lib/utils";
import { currentLocale } from "../../lib/i18n";
import { pluralizeUnit } from "../../lib/units";
import { FIGURE_STEPS, fitFigureStep } from "./statCardFit";

function AnimatedNumber({ value, decimals = 0 }: { value: number; decimals?: number }) {
  const motionValue = useMotionValue(0);
  const rounded = useTransform(motionValue, (latest) =>
    latest.toLocaleString(currentLocale(), { minimumFractionDigits: decimals, maximumFractionDigits: decimals }),
  );
  const previous = useRef(0);

  useEffect(() => {
    const controls = animate(previous.current, value, {
      duration: 0.5,
      ease: "easeOut",
      onUpdate: (latest) => motionValue.set(latest),
    });
    previous.current = value;
    return () => controls.stop();
  }, [value, motionValue]);

  return <motion.span>{rounded}</motion.span>;
}

/**
 * Shrinks the figure's type until it fits the card, so a long amount is never
 * cut off or rounded away. Without this the figure -- one unbreakable line --
 * spills past the card's right edge and clips its unit on narrow cards
 * (measured at +52px on a 1280px window, +35px at 1366px).
 */
function useFigureFit(deps: unknown[]) {
  const boxRef = useRef<HTMLParagraphElement>(null);
  const [step, setStep] = useState(0);
  // Read in the measure effect without making it re-run on every step change,
  // which would otherwise loop: measure -> setStep -> measure.
  const stepRef = useRef(step);
  stepRef.current = step;

  useLayoutEffect(() => {
    const box = boxRef.current;
    if (!box) return;

    const measure = () => {
      // scrollWidth is the figure's full width even while it overflows; the
      // parent's clientWidth is the room it actually has.
      const available = box.parentElement?.clientWidth ?? 0;
      const next = fitFigureStep(box.scrollWidth, available, stepRef.current);
      setStep((current) => (current === next ? current : next));
    };

    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(box);
    if (box.parentElement) observer.observe(box.parentElement);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { boxRef, step };
}

export function StatCard({
  label,
  value,
  icon,
  accent = "primary",
  prefix,
  unit,
  decimals,
}: {
  label: string;
  /** null renders "—" instead of an animated figure — use for a value that can't be
   * computed yet (e.g. incomplete cost data), never coerce that case to 0. */
  value: number | null;
  icon: ReactNode;
  accent?: "primary" | "success" | "warning" | "accent" | "destructive";
  prefix?: string;
  /** Rendered after the figure. Omit when no single unit is true of it. */
  unit?: string | null;
  /** Fraction digits to display. Defaults to 0 — a whole-number count or amount. */
  decimals?: number;
}) {
  const { boxRef, step } = useFigureFit([value, prefix, unit, decimals, label]);
  const atSmallestStep = step === FIGURE_STEPS.length - 1;

  return (
    <Card className="flex items-center gap-4 p-4">
      <div
        className={cn(
          "flex h-10 w-10 shrink-0 items-center justify-center rounded-lg",
          accent === "primary" && "bg-primary/10 text-primary",
          accent === "success" && "bg-success-soft text-success",
          accent === "warning" && "bg-warning-soft text-warning",
          accent === "accent" && "bg-accent/10 text-accent",
          accent === "destructive" && "bg-destructive-soft text-destructive",
        )}
      >
        {icon}
      </div>
      {/* min-w-0 lets this column shrink instead of pushing the figure out of the
          card -- a flex item's automatic minimum size is its content otherwise. */}
      <div className="min-w-0 flex-1">
        <p
          ref={boxRef}
          className={cn(
            "font-semibold tabular-nums tracking-tight",
            FIGURE_STEPS[step].className,
            // Down to the smallest step the figure stays on one line; at that point
            // the unit is allowed to wrap rather than the number being cut off.
            atSmallestStep ? "whitespace-normal" : "whitespace-nowrap",
          )}
        >
          {value === null ? (
            "—"
          ) : (
            <>
              {prefix}
              <AnimatedNumber value={value} decimals={decimals} />
              {unit && <span className="ml-1 text-base font-medium text-muted-foreground">{pluralizeUnit(unit, value)}</span>}
            </>
          )}
        </p>
        <p className="truncate text-xs text-muted-foreground" title={label}>
          {label}
        </p>
      </div>
    </Card>
  );
}
