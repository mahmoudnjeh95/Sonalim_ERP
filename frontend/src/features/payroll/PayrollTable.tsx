import { useEffect, useState, type ReactNode } from "react";
import { Inbox, SearchX } from "lucide-react";
import { AppLoader } from "../../components/patterns/AppLoader";
import { ColumnFilterRow, type FilterCell } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { EmptyState } from "../../components/patterns/EmptyState";
import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import { ResizableTableHead, Table, TableBody, TableCell, TableHeader, TableRow } from "../../components/ui/table";
import { useI18n } from "../../lib/i18n";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";

export interface PayrollTableProps<Row> {
  /** Module-qualified, e.g. "payroll.runs" — the key the column preferences are saved under. */
  tableKey: string;
  columns: ColumnDef<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  loading: boolean;
  emptyTitle: string;
  emptyDescription: string;
  /** Left of the column menu: FilterTabs, create buttons, pickers. */
  toolbar?: ReactNode;
  filtersActive?: boolean;
  onClearFilters?: () => void;
  /** One filter control per entry of `columns` (same order); a column's own `filterCell` is used otherwise. */
  filterCells?: FilterCell[];
  onRowClick?: (row: Row) => void;
  emptyIcon?: ReactNode;
}

/**
 * The payroll list table: columns as data (resize, hide and sort, saved per user through
 * useTableColumns), an optional per-column filter row, the branded loader for the first load
 * only (a filter change or refetch shows skeleton rows in the mounted table instead), and an
 * empty state that says when the filters, not the data, emptied it.
 */
export function PayrollTable<Row>({
  tableKey,
  columns,
  rows,
  rowKey,
  loading,
  emptyTitle,
  emptyDescription,
  toolbar,
  filtersActive,
  onClearFilters,
  filterCells,
  onRowClick,
  emptyIcon,
}: PayrollTableProps<Row>) {
  const { t } = useI18n();
  const table = useTableColumns(tableKey, columns);
  const [booted, setBooted] = useState(false);
  useEffect(() => {
    if (!loading) setBooted(true);
  }, [loading]);

  const sorted = table.sortRows(rows);
  const span = Math.max(table.visibleColumns.length, 1);
  const filterRow: FilterCell[] | null = filterCells
    ? table.visibleColumns.map((column) => filterCells[columns.findIndex((c) => c.key === column.key)] ?? { type: "blank" })
    : columns.some((column) => column.filterCell)
      ? table.visibleColumns.map((column) => column.filterCell ?? { type: "blank" })
      : null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {toolbar}
        {filtersActive && onClearFilters && (
          <Button variant="ghost" size="sm" onClick={onClearFilters}>
            {t("payroll.common.clearFilters")}
          </Button>
        )}
        <div className="ml-auto">
          <ColumnVisibilityMenu columns={columns} isVisible={table.isVisible} onToggle={table.toggleVisible} onReset={table.resetAll} />
        </div>
      </div>
      {loading && !booted ? (
        <AppLoader label={t("payroll.common.loading")} className="py-10" />
      ) : (
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
              {filterRow && <ColumnFilterRow cells={filterRow} />}
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
                    {filtersActive ? (
                      <EmptyState
                        icon={<SearchX className="h-5 w-5" />}
                        title={t("payroll.common.noRowsMatchFilters")}
                        description={t("payroll.common.noRowsMatchFiltersHint")}
                        action={
                          onClearFilters && (
                            <Button variant="outline" size="sm" onClick={onClearFilters}>
                              {t("payroll.common.clearFilters")}
                            </Button>
                          )
                        }
                      />
                    ) : (
                      <EmptyState icon={emptyIcon ?? <Inbox className="h-5 w-5" />} title={emptyTitle} description={emptyDescription} />
                    )}
                  </TableCell>
                </TableRow>
              )}
              {!loading &&
                sorted.map((row) => (
                  <TableRow
                    key={rowKey(row)}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                    className={onRowClick ? "cursor-pointer" : undefined}
                  >
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
      )}
    </div>
  );
}
