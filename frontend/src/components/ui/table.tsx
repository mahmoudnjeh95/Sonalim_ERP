import * as React from "react";
import { cn } from "../../lib/utils";

export function Table({
  className,
  colWidths,
  children,
  ...props
}: React.TableHTMLAttributes<HTMLTableElement> & { colWidths?: number[] }) {
  return (
    <div className="w-full overflow-x-auto">
      <table
        className={cn("w-full text-sm", className)}
        style={colWidths ? { tableLayout: "fixed" } : undefined}
        {...props}
      >
        {colWidths && (
          <colgroup>
            {colWidths.map((width, i) => (
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
  return <td className={cn("px-4 py-3", className)} {...props} />;
}

/**
 * A TableHead with a drag handle on its right edge for column-width resize.
 * Reports the committed width via onResize(width) on drag end (not per pixel).
 */
export function ResizableTableHead({
  className,
  width,
  onResize,
  children,
  ...props
}: React.ThHTMLAttributes<HTMLTableCellElement> & { width: number; onResize: (width: number) => void }) {
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
      <span className="block truncate">{children}</span>
      <div
        onMouseDown={handleMouseDown}
        className={cn(
          "absolute right-0 top-0 h-full w-1.5 cursor-col-resize touch-none hover:bg-primary/40",
          dragWidth !== null && "bg-primary/40",
        )}
      />
    </th>
  );
}
