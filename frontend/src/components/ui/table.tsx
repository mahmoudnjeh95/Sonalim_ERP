import * as React from "react";
import { ChevronDown, ChevronUp, ChevronsUpDown } from "lucide-react";
import { cn } from "../../lib/utils";

export type SortDirection = "asc" | "desc";

/**
 * Narrowest a column may be squeezed to before the shrink gives up. Below this a
 * header is unreadable, so a scrollbar is the lesser evil -- but eight columns
 * only reach it under about 580px, which is a phone, not a desk.
 */
const MIN_FITTED_WIDTH = 72;

/**
 * Column widths scaled down to the space actually available.
 *
 * Stored widths are what the user chose; this is what fits today's window. Only
 * shrinking is applied -- a table narrower than its container keeps the exact
 * widths that were set, so resizing behaves as it always did and nothing moves
 * on its own. Columns already at the floor stop absorbing the shrink and the
 * remainder is redistributed over the ones with room, which is why this loops.
 */
function fitToWidth(widths: number[], available: number | null): number[] {
  if (available === null || widths.length === 0) return widths;
  const total = widths.reduce((sum, width) => sum + width, 0);
  if (total <= available) return widths;
  if (widths.length * MIN_FITTED_WIDTH >= available) return widths.map(() => MIN_FITTED_WIDTH);

  const fitted = [...widths];
  const pinned = new Array<boolean>(widths.length).fill(false);
  for (let pass = 0; pass < widths.length; pass += 1) {
    const pinnedWidth = fitted.reduce((sum, width, i) => (pinned[i] ? sum + width : sum), 0);
    const flexibleWidth = fitted.reduce((sum, width, i) => (pinned[i] ? sum : sum + width), 0);
    if (flexibleWidth === 0) break;
    const scale = (available - pinnedWidth) / flexibleWidth;
    let hitFloor = false;
    for (let i = 0; i < fitted.length; i += 1) {
      if (pinned[i]) continue;
      const scaled = fitted[i] * scale;
      if (scaled < MIN_FITTED_WIDTH) {
        fitted[i] = MIN_FITTED_WIDTH;
        pinned[i] = true;
        hitFloor = true;
      } else {
        fitted[i] = scaled;
      }
    }
    if (!hitFloor) break;
  }
  return fitted;
}

export function Table({
  className,
  colWidths,
  children,
  ...props
}: React.TableHTMLAttributes<HTMLTableElement> & { colWidths?: number[] }) {
  const wrapperRef = React.useRef<HTMLDivElement>(null);
  const [available, setAvailable] = React.useState<number | null>(null);

  // Measured rather than assumed: the same table sits inside a full-width card
  // on one screen and half a grid on another, and a sidebar can open under it.
  React.useLayoutEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper || !colWidths) return;
    setAvailable(wrapper.clientWidth);
    const observer = new ResizeObserver((entries) => setAvailable(entries[0].contentRect.width));
    observer.observe(wrapper);
    return () => observer.disconnect();
  }, [colWidths]);

  const fitted = React.useMemo(
    () => (colWidths ? fitToWidth(colWidths, available) : undefined),
    [colWidths, available],
  );

  return (
    <div ref={wrapperRef} className="w-full overflow-x-auto">
      <table
        className={cn("w-full text-sm", className)}
        style={colWidths ? { tableLayout: "fixed" } : undefined}
        {...props}
      >
        {fitted && (
          <colgroup>
            {fitted.map((width, i) => (
              <col key={i} style={{ width }} />
            ))}
          </colgroup>
        )}
        {children}
      </table>
    </div>
  );
}

export function TableHeader(props: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className="border-b border-border text-left text-xs uppercase text-muted-foreground" {...props} />;
}

export function TableBody(props: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className="divide-y divide-border" {...props} />;
}

export function TableRow({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn("hover:bg-muted/50", className)} {...props} />;
}

export function TableHead({ className, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return <th className={cn("px-4 py-2 font-medium", className)} {...props} />;
}

export function TableCell({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  // overflow-hidden matters once a table has resizable (fixed-width) columns:
  // without it, a cell whose content is wider than its column -- a long badge,
  // an unbroken id -- paints over the next column instead of clipping.
  return <td className={cn("overflow-hidden px-4 py-3", className)} {...props} />;
}

/**
 * A TableHead with a drag handle on its right edge for column-width resize,
 * and an optional click-to-sort header (pass `onSort` to make it clickable).
 * Reports the committed width via onResize(width) on drag end (not per pixel).
 */
export function ResizableTableHead({
  className,
  width,
  onResize,
  children,
  sortDirection,
  onSort,
  ...props
}: React.ThHTMLAttributes<HTMLTableCellElement> & {
  width: number;
  onResize: (width: number) => void;
  /** Current sort direction of this column, or null/undefined if it isn't the active sort. */
  sortDirection?: SortDirection | null;
  /** Present => header is clickable and toggles this column's sort. */
  onSort?: () => void;
}) {
  const [dragWidth, setDragWidth] = React.useState<number | null>(null);

  function handleMouseDown(event: React.MouseEvent<HTMLDivElement>) {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = width;

    function handleMouseMove(moveEvent: MouseEvent) {
      setDragWidth(startWidth + (moveEvent.clientX - startX));
    }

    function handleMouseUp(upEvent: MouseEvent) {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
      onResize(startWidth + (upEvent.clientX - startX));
      setDragWidth(null);
    }

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
  }

  return (
    <th className={cn("relative select-none overflow-hidden px-4 py-2 font-medium", className)} {...props}>
      {onSort ? (
        // Not a <button>: header content (e.g. a HelpTooltip) can itself contain
        // a real button, and a <button> may not legally contain another one.
        <div
          role="button"
          tabIndex={0}
          onClick={onSort}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              onSort();
            }
          }}
          className={cn(
            "inline-flex max-w-full cursor-pointer items-center gap-1 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring",
            sortDirection && "text-foreground",
          )}
        >
          <span className="min-w-0 truncate">{children}</span>
          {sortDirection === "asc" && <ChevronUp className="h-3 w-3 shrink-0" />}
          {sortDirection === "desc" && <ChevronDown className="h-3 w-3 shrink-0" />}
          {!sortDirection && <ChevronsUpDown className="h-3 w-3 shrink-0 opacity-40" />}
        </div>
      ) : (
        <span className="block truncate">{children}</span>
      )}
      <div
        onMouseDown={handleMouseDown}
        onClick={(event) => event.stopPropagation()}
        className={cn(
          "absolute right-0 top-0 h-full w-1.5 cursor-col-resize touch-none hover:bg-primary/40",
          dragWidth !== null && "bg-primary/40",
        )}
      />
    </th>
  );
}
