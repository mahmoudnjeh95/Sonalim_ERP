import type { ReactNode } from "react";
import { Card } from "../ui/card";
import { cn } from "../../lib/utils";
import { currentLocale } from "../../lib/i18n";
import { pluralizeUnit } from "../../lib/units";

export interface UnitBreakdownEntry {
  unit: string;
  value: number;
}

/**
 * Like StatCard, but for a quantity that spans several units of measure —
 * summing raw quantities across products with different units (kg + pieces +
 * L) into one number is meaningless, so this renders one figure per unit
 * instead of a single blended total.
 */
export function UnitBreakdownStat({
  label,
  icon,
  accent = "primary",
  breakdown,
}: {
  label: string;
  icon: ReactNode;
  accent?: "primary" | "success" | "warning" | "accent" | "destructive";
  breakdown: UnitBreakdownEntry[];
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
      <div className="min-w-0">
        <p className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-lg font-semibold tabular-nums tracking-tight">
          {breakdown.length === 0
            ? "—"
            : breakdown.map((entry) => (
                <span key={entry.unit}>
                  {entry.value.toLocaleString(currentLocale())} <span className="text-xs font-normal text-muted-foreground">{pluralizeUnit(entry.unit, entry.value)}</span>
                </span>
              ))}
        </p>
        <p className="text-xs text-muted-foreground">{label}</p>
      </div>
    </Card>
  );
}
