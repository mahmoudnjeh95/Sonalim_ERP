import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Badge } from "../ui/badge";
import { Popover, PopoverTrigger, PopoverContent } from "../ui/popover";

export interface StatBreakdownRow {
  id: string;
  /** The work order's own reference, e.g. its OF number. */
  label: string;
  href: string;
  /** Rendered beside the reference — typically a StatusBadge. */
  status?: ReactNode;
  /** The team(s) whose validated reports fed this row, if any reported. */
  teams: string[];
  lines: { label: string; value: string }[];
}

/**
 * Turns a dashboard stat tile into a drill-down: which work orders (and
 * which teams) make up the number on the tile, each linking to its own page.
 * The tile itself is passed in unchanged as `trigger`.
 */
export function StatBreakdownPopover({
  trigger,
  title,
  emptyMessage,
  rows,
  footer,
}: {
  trigger: ReactNode;
  title: string;
  emptyMessage: string;
  rows: StatBreakdownRow[];
  footer?: ReactNode;
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="block w-full rounded-xl border-0 bg-transparent p-0 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          {trigger}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-80" align="start">
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</p>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">{emptyMessage}</p>
        ) : (
          <div className="max-h-72 space-y-2 overflow-y-auto">
            {rows.map((row) => (
              <Link
                key={row.id}
                to={row.href}
                className="block rounded-lg border border-border p-2 transition-colors hover:border-primary/30 hover:bg-muted/40"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5">
                    <span className="text-sm font-medium text-primary">{row.label}</span>
                    {row.status}
                  </span>
                  {row.teams.length > 0 && (
                    <span className="flex flex-wrap justify-end gap-1">
                      {row.teams.map((team) => (
                        <Badge key={team} variant="outline" className="text-[10px]">
                          {team}
                        </Badge>
                      ))}
                    </span>
                  )}
                </div>
                {row.lines.length > 0 && (
                  <div className="mt-1 space-y-0.5">
                    {row.lines.map((line, lineIndex) => (
                      <p key={lineIndex} className="text-xs text-muted-foreground">
                        {line.label} — <span className="font-medium text-foreground">{line.value}</span>
                      </p>
                    ))}
                  </div>
                )}
              </Link>
            ))}
          </div>
        )}
        {footer}
      </PopoverContent>
    </Popover>
  );
}
