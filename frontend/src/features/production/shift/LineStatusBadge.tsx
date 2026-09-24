import { Circle } from "lucide-react";

interface LineStatusBadgeProps {
  reportCount: number;
  totalShifts: number;
}

export function LineStatusBadge({ reportCount, totalShifts }: LineStatusBadgeProps) {
  let dotColor = "text-destructive"; // red (0 reports)
  if (reportCount > 0 && reportCount < totalShifts) {
    dotColor = "text-yellow-500"; // yellow (partial)
  } else if (reportCount === totalShifts && totalShifts > 0) {
    dotColor = "text-success"; // green (all done)
  }

  return (
    <div className="flex items-center gap-1 rounded-full bg-muted px-2 py-1 text-xs font-medium">
      <Circle className={`h-2 w-2 fill-current ${dotColor}`} />
      <span className="tabular-nums">
        {reportCount}/{totalShifts}
      </span>
    </div>
  );
}
