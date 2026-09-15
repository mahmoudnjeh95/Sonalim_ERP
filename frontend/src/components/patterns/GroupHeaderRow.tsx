import { ChevronDown, ChevronRight } from "lucide-react";

/** A full-width, collapsible section header inside a <TableBody>, between a table's row groups. */
export function GroupHeaderRow({
  label,
  count,
  collapsed,
  onToggle,
  colSpan,
}: {
  label: string;
  count: number;
  collapsed: boolean;
  onToggle: () => void;
  colSpan: number;
}) {
  return (
    <tr className="cursor-pointer bg-muted/40 hover:bg-muted/60" onClick={onToggle}>
      <td colSpan={colSpan} className="px-4 py-2">
        <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
          {collapsed ? (
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
          )}
          <span className="truncate">{label}</span>
          <span className="rounded-full bg-background px-2 py-0.5 text-xs font-normal text-muted-foreground">
            {count}
          </span>
        </div>
      </td>
    </tr>
  );
}
