import * as React from "react";
import { cn } from "../../lib/utils";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  /** Validation message shown under the field; also switches the border to the destructive color. */
  error?: string;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, error, type, inputMode, ...props }, ref) => (
    <div>
      <input
        ref={ref}
        type={type}
        // A number field should bring up the number keypad on a phone. 159 call
        // sites set type="number" without saying so; defaulting it here covers
        // them all, and "decimal" rather than "numeric" because the shop floor
        // enters weights and quantities, not whole numbers only. An explicit
        // inputMode from the caller still wins.
        inputMode={inputMode ?? (type === "number" ? "decimal" : undefined)}
        aria-invalid={error ? true : undefined}
        className={cn(
          // h-10 and 16px text under sm: a 44px-ish touch target, and iOS zooms
          // the page in on focus for anything under 16px. Desktop keeps the
          // original h-9 / 14px exactly.
          "flex h-10 w-full rounded-md border border-border bg-background px-3 py-1 text-base shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 sm:h-9 sm:text-sm",
          error && "border-destructive focus-visible:ring-destructive",
          className,
        )}
        {...props}
      />
      {error && <p className="mt-1 text-sm text-destructive">{error}</p>}
    </div>
  ),
);
Input.displayName = "Input";
