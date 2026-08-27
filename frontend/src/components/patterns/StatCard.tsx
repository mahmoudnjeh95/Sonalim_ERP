import { useEffect, useRef, type ReactNode } from "react";
import { animate, motion, useMotionValue, useTransform } from "framer-motion";
import { Card } from "../ui/card";
import { cn } from "../../lib/utils";

function AnimatedNumber({ value }: { value: number }) {
  const motionValue = useMotionValue(0);
  const rounded = useTransform(motionValue, (latest) => Math.round(latest).toLocaleString());
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

export function StatCard({
  label,
  value,
  icon,
  accent = "primary",
  prefix,
}: {
  label: string;
  value: number;
  icon: ReactNode;
  accent?: "primary" | "success" | "warning" | "accent" | "destructive";
  prefix?: string;
}) {
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
      <div>
        <p className="text-2xl font-semibold tabular-nums tracking-tight">
          {prefix}
          <AnimatedNumber value={value} />
        </p>
        <p className="text-xs text-muted-foreground">{label}</p>
      </div>
    </Card>
  );
}
