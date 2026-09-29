import type { ReactNode } from "react";
import { Table, TableBody, TableCell, TableHeader, TableRow, ResizableTableHead } from "../../components/ui/table";
import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { EmptyState } from "../../components/patterns/EmptyState";
import { useI18n } from "../../lib/i18n";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";

interface HrListTableProps<Row> {
  tableKey: string;
  columns: ColumnDef<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  loading: boolean;
  emptyIcon: ReactNode;
  emptyTitle: string;
  emptyDescription: string;
  /** Rendered left of the column menu: FilterTabs, create buttons, pickers. */
  toolbar?: ReactNode;
  filtersActive?: boolean;
  onClearFilters?: () => void;
  rowClassName?: (row: Row) => string | undefined;
}

/**
 * The phase-2 HR list table: columns as data (resize, hide and sort, saved per user through
 * useTableColumns), the per-column filter row under the headers, skeleton rows while loading
 * (the page shows the branded loader once), an empty state.
 */
export function HrListTable<Row>({
  tableKey, columns, rows, rowKey, loading, emptyIcon, emptyTitle, emptyDescription, toolbar, filtersActive, onClearFilters, rowClassName,
}: HrListTableProps<Row>) {
  const { t } = useI18n();
  const table = useTableColumns(tableKey, columns);
  const sorted = table.sortRows(rows);
  const span = table.visibleColumns.length;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {toolbar}
        {filtersActive && onClearFilters && (
          <Button variant="ghost" size="sm" onClick={onClearFilters}>
            {t("common.clearFilters")}
          </Button>
        )}
        <div className="ml-auto">
          <ColumnVisibilityMenu columns={columns} isVisible={table.isVisible} onToggle={table.toggleVisible} onReset={table.resetAll} />
        </div>
      </div>
      <div className="rounded-lg border border-border">
        <Table colWidths={table.colWidths}>
          <TableHeader>
            <TableRow>
              {table.visibleColumns.map((column) => (
                <ResizableTableHead
                  key={column.key}
                  width={table.getWidth(column.key)}
                  onResize={(width) => table.setWidth(column.key, width)}
                  className={column.headerClassName}
                  sortDirection={table.sortDirectionFor(column.key)}
                  onSort={column.sortValue ? () => table.toggleSort(column.key) : undefined}
                >
                  {column.header}
                </ResizableTableHead>
              ))}
            </TableRow>
            <ColumnFilterRow cells={table.visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
          </TableHeader>
          <TableBody>
            {loading &&
              [0, 1, 2].map((index) => (
                <TableRow key={`skeleton-${index}`}>
                  <TableCell colSpan={span}>
                    <Skeleton className="h-5 w-full" />
                  </TableCell>
                </TableRow>
              ))}
            {!loading && sorted.length === 0 && (
              <TableRow>
                <TableCell colSpan={span} className="p-0">
                  <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyDescription} />
                </TableCell>
              </TableRow>
            )}
            {!loading &&
              sorted.map((row) => (
                <TableRow key={rowKey(row)} className={rowClassName?.(row)}>
                  {table.visibleColumns.map((column) => (
                    <TableCell key={column.key} className={column.cellClassName}>
                      {column.cell(row)}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
