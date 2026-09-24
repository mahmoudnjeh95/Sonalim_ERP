import { useId, type ReactNode } from "react";
import { motion } from "framer-motion";
import { cn } from "../../lib/utils";

export function FilterTabs<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string; icon?: ReactNode }[];
  value: T;
  onChange: (value: T) => void;
}) {
  // One indicator per FilterTabs instance: layoutId must not collide between
  // two filter rows on the same screen or the pill would fly across them.
  const indicatorId = useId();
  return (
    <div className="inline-flex flex-wrap gap-1 rounded-lg border border-border bg-muted/40 p-1">
      {options.map((option) => {
        const active = value === option.value;
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            className={cn(
              "relative inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-colors",
              active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {active && (
              <motion.span
                layoutId={`filter-tabs-indicator-${indicatorId}`}
                className="absolute inset-0 rounded-md bg-background shadow-soft"
                transition={{ type: "spring", stiffness: 500, damping: 40 }}
                aria-hidden
              />
            )}
            {option.icon && <span className="relative z-10 inline-flex">{option.icon}</span>}
            <span className="relative z-10">{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}
