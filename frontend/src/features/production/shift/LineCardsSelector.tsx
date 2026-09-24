import { useMemo, useState, useEffect } from "react";
import { cn } from "../../../lib/utils";
import { Select } from "../../../components/ui/select";
import { LineStatusBadge } from "./LineStatusBadge";
import type { ShiftWindowRow } from "../board/api";

interface Equipment {
  id: string;
  work_center_id: string;
  name: string;
  archived_at: string | null;
}

interface LineCardsSelectorProps {
  value: string;
  onChange: (id: string) => void;
  equipment: Equipment[];
  reportCountByLineDate: Map<string, number>;
  date: string;
  windows: ShiftWindowRow[];
}

export function LineCardsSelector({
  value,
  onChange,
  equipment,
  reportCountByLineDate,
  date,
  windows,
}: LineCardsSelectorProps) {
  const [showCards, setShowCards] = useState(window.innerWidth >= 800);

  useEffect(() => {
    const handleResize = () => setShowCards(window.innerWidth >= 800);
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const totalShifts = windows.length;
  const reportCount = useMemo(
    () => reportCountByLineDate.get(`${date}|${value}`) ?? 0,
    [reportCountByLineDate, date, value]
  );

  if (!showCards) {
    // Fallback dropdown for narrow screens
    return (
      <div className="space-y-1">
        <label htmlFor="shift-line" className="text-xs text-muted-foreground">
          Line
        </label>
        <div className="flex gap-2">
          <Select id="shift-line" value={value} onChange={(e) => onChange(e.target.value)}>
            {equipment.map((e) => (
              <option key={e.id} value={e.id}>
                {e.name}
              </option>
            ))}
          </Select>
          <LineStatusBadge reportCount={reportCount} totalShifts={totalShifts} />
        </div>
      </div>
    );
  }

  // Cards view for wider screens
  return (
    <div className="space-y-1">
      <label className="text-xs text-muted-foreground">Line</label>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
        {equipment.map((e) => {
          const count = reportCountByLineDate.get(`${date}|${e.id}`) ?? 0;
          const isSelected = e.id === value;
          return (
            <button
              key={e.id}
              onClick={() => onChange(e.id)}
              className={cn(
                "rounded-lg border-2 p-3 text-left transition-all",
                isSelected
                  ? "border-primary bg-primary/10"
                  : "border-border hover:border-muted-foreground hover:bg-muted/50"
              )}
            >
              <div className="flex items-start justify-between">
                <div className="text-sm font-medium">{e.name}</div>
              </div>
              <div className="mt-2">
                <LineStatusBadge reportCount={count} totalShifts={totalShifts} />
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
