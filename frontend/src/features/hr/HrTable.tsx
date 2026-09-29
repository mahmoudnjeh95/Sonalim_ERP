import type { ReactNode } from "react";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { EmptyState } from "../../components/patterns/EmptyState";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import { ResizableTableHead, Table, TableBody, TableCell, TableHeader, TableRow } from "../../components/ui/table";
import { useI18n } from "../../lib/i18n";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { cn } from "../../lib/utils";

interface HrTableProps<Row> {
  tableKey: string;
  columns: ColumnDef<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  isLoading?: boolean;
  /** "loader" only for the one table that is the whole screen; tabs and sub-blocks use skeletons. */
  loadingVariant?: "loader" | "skeleton";
  empty: { icon: ReactNode; title: string; description: string };
  toolbar?: ReactNode;
  filtersActive?: boolean;
  onClearFilters?: () => void;
  onRowClick?: (row: Row) => void;
}

/** An hr list: columns as data (resizable, hideable, saved per user), a filter row, sortable headers. */
export function HrTable<Row>({
  tableKey,
  columns,
  rows,
  rowKey,
  isLoading = false,
  loadingVariant = "skeleton",
  empty,
  toolbar,
  filtersActive = false,
  onClearFilters,
  onRowClick,
}: HrTableProps<Row>) {
  const { t } = useI18n();
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns(tableKey, columns);
  const sorted = sortRows(rows);
  const hasFilterRow = columns.some((column) => column.filterCell);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        {toolbar}
        {filtersActive && onClearFilters && (
          <Button variant="ghost" size="sm" onClick={onClearFilters}>
            {t("common.clearFilters")}
          </Button>
        )}
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
          {hasFilterRow && <ColumnFilterRow cells={visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />}
        </TableHeader>
        <TableBody>
          {isLoading && loadingVariant === "loader" && <TableLoadingRow colSpan={visibleColumns.length} />}
          {isLoading &&
            loadingVariant === "skeleton" &&
            [0, 1, 2].map((index) => (
              <TableRow key={`skeleton-${index}`}>
                <TableCell colSpan={visibleColumns.length}>
                  <Skeleton className="h-6 w-full" />
                </TableCell>
              </TableRow>
            ))}
          {!isLoading && rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={visibleColumns.length} className="p-0">
                <EmptyState icon={empty.icon} title={empty.title} description={empty.description} />
              </TableCell>
            </TableRow>
          )}
          {!isLoading &&
            sorted.map((row) => (
              <TableRow key={rowKey(row)} className={cn(onRowClick && "cursor-pointer")} onClick={onRowClick ? () => onRowClick(row) : undefined}>
                {visibleColumns.map((column) => (
                  <TableCell key={column.key} className={column.cellClassName}>
                    {column.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
        </TableBody>
      </Table>
    </div>
  );
}
