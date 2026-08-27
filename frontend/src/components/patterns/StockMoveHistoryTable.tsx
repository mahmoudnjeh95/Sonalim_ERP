import { History } from "lucide-react";
import { Badge } from "../ui/badge";
import { Skeleton } from "../ui/skeleton";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../ui/table";
import { EmptyState } from "./EmptyState";
import { ColumnVisibilityMenu } from "./ColumnVisibilityMenu";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { MOVE_TYPE_VARIANT, useMoveTypeLabels } from "../../lib/stockMoveTypes";
import { useI18n } from "../../lib/i18n";
import type { StockMove } from "../../features/warehouse/api";

function formatWhen(iso: string, language: string) {
  return new Date(iso).toLocaleString(language === "fr" ? "fr-FR" : "en-US", { dateStyle: "medium", timeStyle: "short" });
}

/**
 * Compact, self-contained stock-move history table — used both embedded in a
 * dialog (per-product history) and could be reused for any other move-list view.
 * Unlike StockHistoryTab's own table, this has no per-column filters (the
 * caller is expected to have already scoped `moves` down, e.g. to one product).
 */
export function StockMoveHistoryTable({
  tableKey,
  moves,
  isLoading,
  locationName,
  productName,
  showProductColumn = false,
}: {
  tableKey: string;
  moves: StockMove[];
  isLoading: boolean;
  locationName: (id: string) => string;
  productName?: (id: string) => string;
  showProductColumn?: boolean;
}) {
  const { t, language } = useI18n();
  const MOVE_TYPE_LABEL = useMoveTypeLabels();

  const allColumns: ColumnDef<StockMove>[] = [
    {
      key: "when",
      header: t("warehouse.stockHistory.column.when"),
      defaultWidth: 180,
      cell: (move) => <span className="whitespace-nowrap text-muted-foreground">{formatWhen(move.created_at, language)}</span>,
    },
    {
      key: "product",
      header: t("warehouse.stockHistory.column.product"),
      defaultWidth: 200,
      cell: (move) => <span className="font-medium">{productName ? productName(move.product_id) : move.product_id}</span>,
    },
    {
      key: "location",
      header: t("warehouse.stockHistory.column.location"),
      defaultWidth: 160,
      cell: (move) => <span className="text-muted-foreground">{locationName(move.location_id)}</span>,
    },
    {
      key: "type",
      header: t("warehouse.stockHistory.column.type"),
      defaultWidth: 170,
      cell: (move) => (
        <Badge variant={MOVE_TYPE_VARIANT[move.move_type]} dot>
          {MOVE_TYPE_LABEL[move.move_type]}
        </Badge>
      ),
    },
    {
      key: "quantity",
      header: t("warehouse.stockHistory.column.quantity"),
      defaultWidth: 140,
      cell: (move) => (
        <span className={`tabular-nums ${move.quantity < 0 || move.move_type === "issue" ? "text-destructive" : "text-success"}`}>
          {move.move_type === "issue" ? "-" : move.quantity > 0 && move.move_type !== "adjustment" ? "+" : ""}
          {move.quantity}
        </span>
      ),
    },
    {
      key: "reference",
      header: t("warehouse.stockHistory.column.reference"),
      defaultWidth: 180,
      cell: (move) => <span className="text-muted-foreground">{move.reference}</span>,
    },
    {
      key: "reason",
      header: t("warehouse.stockHistory.column.reason"),
      defaultWidth: 200,
      cell: (move) => <span className="text-muted-foreground">{move.reason ?? "—"}</span>,
    },
  ];
  const columns = showProductColumn ? allColumns : allColumns.filter((column) => column.key !== "product");
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(tableKey, columns);

  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
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
              >
                {column.header}
              </ResizableTableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading &&
            Array.from({ length: 4 }).map((_, i) => (
              <TableRow key={i}>
                <TableCell colSpan={visibleColumns.length}>
                  <Skeleton className="h-5 w-full" />
                </TableCell>
              </TableRow>
            ))}
          {!isLoading && moves.length === 0 && (
            <TableRow>
              <TableCell colSpan={visibleColumns.length} className="p-0">
                <EmptyState
                  icon={<History className="h-5 w-5" />}
                  title={t("warehouse.stockHistory.empty.title")}
                  description={t("warehouse.stockHistory.empty.description")}
                />
              </TableCell>
            </TableRow>
          )}
          {moves.map((move) => (
            <TableRow key={move.id}>
              {visibleColumns.map((column) => (
                <TableCell key={column.key} className={column.cellClassName}>
                  {column.cell(move)}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
