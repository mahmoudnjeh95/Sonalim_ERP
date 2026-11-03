import { useState, useEffect } from "react";
import { cn } from "../../../lib/utils";
import { Select } from "../../../components/ui/select";
import { Label as FieldLabel } from "../../../components/ui/label";
import { T, useLabel } from "./shiftText";
import type { ShiftWindowRow } from "../board/api";

interface ShiftCardsSelectorProps {
  value: string;
  onChange: (shift: string) => void;
  windows: ShiftWindowRow[];
}

export function ShiftCardsSelector({ value, onChange, windows }: ShiftCardsSelectorProps) {
  const label = useLabel();
  const [showCards, setShowCards] = useState(window.innerWidth >= 800);

  useEffect(() => {
    const handleResize = () => setShowCards(window.innerWidth >= 800);
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  if (!showCards) {
    // Fallback dropdown for narrow screens
    return (
      <div className="space-y-1">
        <FieldLabel htmlFor="shift-name" className="text-xs text-muted-foreground">
          {label(T.shift)}
        </FieldLabel>
        <Select id="shift-name" value={value} onChange={(e) => onChange(e.target.value)}>
          {windows.map((w) => (
            <option key={w.shift} value={w.shift}>
              {w.shift} ({w.start_time.slice(0, 5)}–{w.end_time.slice(0, 5)})
            </option>
          ))}
        </Select>
      </div>
    );
  }

  // Cards view for wider screens
  return (
    <div className="space-y-1">
      <label className="text-xs text-muted-foreground">{label(T.shift)}</label>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
        {windows.map((w) => {
          const isSelected = w.shift === value;
          return (
            <button
              key={w.shift}
              onClick={() => onChange(w.shift)}
              className={cn(
                "rounded-lg border-2 p-3 text-left transition-all",
                isSelected
                  ? "border-primary bg-primary/10"
                  : "border-border hover:border-muted-foreground hover:bg-muted/50"
              )}
            >
              <div className="text-sm font-medium">{w.shift}</div>
              <div className="mt-1 text-xs text-muted-foreground">
                {w.start_time.slice(0, 5)}–{w.end_time.slice(0, 5)}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
