import type { ReactNode } from "react";
import { Badge } from "../../components/ui/badge";
import { Skeleton } from "../../components/ui/skeleton";
import { ResizableTableHead, Table, TableBody, TableCell, TableHeader, TableRow } from "../../components/ui/table";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import { ColumnFilterRow, type FilterCell } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { EmptyState } from "../../components/patterns/EmptyState";
import { useI18n } from "../../lib/i18n";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { cn } from "../../lib/utils";
import type { EntryStatus } from "./ledgerApi";

interface TextFilters {
  text: Record<string, string>;
  setTextValue: (key: string, value: string) => void;
}

interface RangeFilters {
  range: Record<string, { min: string; max: string }>;
  setRangeValue: (key: string, part: "min" | "max", value: string) => void;
}

export function textFilter(filters: TextFilters, key: string, placeholder: string): FilterCell {
  return { type: "text", value: filters.text[key] ?? "", onChange: (value) => filters.setTextValue(key, value), placeholder };
}

export function rangeFilter(filters: RangeFilters, key: string): FilterCell {
  return {
    type: "range",
    min: filters.range[key]?.min ?? "",
    max: filters.range[key]?.max ?? "",
    onMinChange: (value) => filters.setRangeValue(key, "min", value),
    onMaxChange: (value) => filters.setRangeValue(key, "max", value),
  };
}

export function EntryStatusBadge({ status }: { status: EntryStatus }) {
  const { t } = useI18n();
  if (status === "posted") return <Badge variant="success">{t("finance.entries.status.posted")}</Badge>;
  if (status === "reversed") return <Badge variant="warning">{t("finance.entries.status.reversed")}</Badge>;
  return <Badge>{t("finance.entries.status.draft")}</Badge>;
}

/**
 * The ledger screens' table: header, ColumnFilterRow and body all come from one ColumnDef array
 * (useTableColumns: per-user widths, visibility and sorting), with an optional totals row. The page
 * keeps the filtering (FilterTabs + useColumnFilters) and passes the filtered rows in.
 */
export function LedgerTable<Row>({
  tableKey,
  columns,
  rows,
  rowKey,
  isLoading,
  loading = "loader",
  emptyIcon,
  emptyTitle,
  emptyDescription,
  toolbar,
  footer,
  onRowClick,
}: {
  tableKey: string;
  columns: ColumnDef<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  isLoading: boolean;
  /** "loader" for the screen's main table (its one branded loader), "skeleton" for any other table on it. */
  loading?: "loader" | "skeleton";
  emptyIcon: ReactNode;
  emptyTitle: string;
  emptyDescription: string;
  toolbar?: ReactNode;
  /** Content of each visible column's cell in the totals row, by column key. */
  footer?: (columnKey: string) => ReactNode;
  onRowClick?: (row: Row) => void;
}) {
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns(tableKey, columns);
  const sorted = sortRows(rows);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 px-6">
        {toolbar}
        <div className="ml-auto">
          <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
        </div>
      </div>
      <Table colWidths={colWidths}>
        <TableHeader>
          <TableRow>
            {visibleColumns.map((column) => (
              <ResizableTableHead
                key={column.key}
                width={getWidth(column.key)}
                onResize={(width) => setWidth(column.key, width)}
                className={column.headerClassName}
                sortDirection={sortDirectionFor(column.key)}
                onSort={column.sortValue ? () => toggleSort(column.key) : undefined}
              >
                {column.header}
              </ResizableTableHead>
            ))}
          </TableRow>
          <ColumnFilterRow cells={visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
        </TableHeader>
        <TableBody>
          {isLoading && loading === "loader" && <TableLoadingRow colSpan={visibleColumns.length} />}
          {isLoading && loading === "skeleton" && (
            <TableRow>
              <TableCell colSpan={visibleColumns.length}>
                <Skeleton className="h-6 w-full" />
              </TableCell>
            </TableRow>
          )}
          {!isLoading && rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={visibleColumns.length} className="p-0">
                <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyDescription} />
              </TableCell>
            </TableRow>
          )}
          {!isLoading &&
            sorted.map((row) => (
              <TableRow
                key={rowKey(row)}
                className={cn(onRowClick && "cursor-pointer hover:bg-muted/50")}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {visibleColumns.map((column) => (
                  <TableCell key={column.key} className={column.cellClassName}>
                    {column.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          {!isLoading && rows.length > 0 && footer && (
            <TableRow className="bg-muted/40 font-semibold">
              {visibleColumns.map((column) => (
                <TableCell key={column.key} className={column.cellClassName}>
                  {footer(column.key)}
                </TableCell>
              ))}
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
