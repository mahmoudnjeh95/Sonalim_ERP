import type { ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { Card } from "../ui/card";
import { Skeleton } from "../ui/skeleton";
import { EmptyState } from "./EmptyState";
import { mobileCardLayout } from "./mobileCardColumns";
import type { ColumnDef } from "../../lib/useTableColumns";
import { cn } from "../../lib/utils";

/**
 * A table's rows as cards, for phone widths.
 *
 * Built from the same `ColumnDef[]` the table renders, so a screen describes its
 * columns once and no page maintains a second, mobile-only copy of its row
 * markup. Each column keeps its own `cell` renderer, which is what lets badges,
 * formatted quantities and action menus work here unchanged.
 *
 * Stored column widths are deliberately ignored: they are per-user preferences
 * saved from a desktop window, and replaying them at 390px produces a layout
 * nobody chose.
 */
export function MobileCardList<Row>({
  columns,
  rows,
  rowKey,
  loading,
  emptyIcon,
  emptyTitle,
  emptyDescription,
  onRowClick,
  rowClassName,
}: {
  /** The visible columns, in table order. */
  columns: ColumnDef<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  loading?: boolean;
  emptyIcon: ReactNode;
  emptyTitle: string;
  emptyDescription: string;
  onRowClick?: (row: Row) => void;
  rowClassName?: (row: Row) => string | undefined;
}) {
  const layout = mobileCardLayout(columns);

  if (loading) {
    return (
      <div className="space-y-2">
        {[0, 1, 2].map((index) => (
          <Card key={index} className="space-y-2 p-4">
            <Skeleton className="h-5 w-1/2" />
            <Skeleton className="h-4 w-3/4" />
          </Card>
        ))}
      </div>
    );
  }

  if (!layout || rows.length === 0) {
    return <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyDescription} />;
  }

  return (
    <div className="space-y-2">
      {rows.map((row) => {
        const interactive = Boolean(onRowClick);
        return (
          <Card
            key={rowKey(row)}
            onClick={onRowClick ? () => onRowClick(row) : undefined}
            className={cn("p-4", interactive && "cursor-pointer active:bg-muted/60", rowClassName?.(row))}
          >
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold">{layout.title.cell(row)}</div>
                {layout.subtitle && (
                  <div className="truncate text-xs text-muted-foreground">{layout.subtitle.cell(row)}</div>
                )}
              </div>
              {interactive && <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />}
            </div>

            {layout.details.length > 0 && (
              <dl className="mt-3 space-y-1.5 border-t border-border pt-3">
                {layout.details.map((column) => (
                  <div key={column.key} className="flex items-start justify-between gap-3 text-xs">
                    <dt className="shrink-0 text-muted-foreground">{column.header}</dt>
                    <dd className="min-w-0 break-words text-right">{column.cell(row)}</dd>
                  </div>
                ))}
              </dl>
            )}

            {layout.actions.length > 0 && (
              // The actions are controls in their own right; a tap on one must not
              // also open the row.
              <div
                className="mt-3 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-3"
                onClick={(event) => event.stopPropagation()}
              >
                {layout.actions.map((column) => (
                  <div key={column.key}>{column.cell(row)}</div>
                ))}
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}
