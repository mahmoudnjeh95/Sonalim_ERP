import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { History } from "lucide-react";
import { Badge } from "../ui/badge";
import { Skeleton } from "../ui/skeleton";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../ui/table";
import { EmptyState } from "./EmptyState";
import { ColumnVisibilityMenu } from "./ColumnVisibilityMenu";
import { StockMoveDetailDialog } from "./StockMoveDetailDialog";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { MOVE_TYPE_VARIANT, formatMoveReference, signedMoveQuantity, useMoveTypeLabels, useReferenceKindLabels } from "../../lib/stockMoveTypes";
import { useI18n } from "../../lib/i18n";
import type { StockMove } from "../../features/warehouse/api";
import type { RegrindScrapInput } from "../../features/production/api";

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
  locationCode,
  productName,
  productSku,
  unit,
  workOrders,
  regrindSources,
  showProductColumn = false,
}: {
  tableKey: string;
  moves: StockMove[];
  isLoading: boolean;
  locationName: (id: string) => string;
  /** Optional -- the row-detail dialog shows the location's code alongside its name when given. */
  locationCode?: (id: string) => string | null | undefined;
  productName?: (id: string) => string;
  /** Optional -- the row-detail dialog shows the product's SKU alongside its name when given. */
  productSku?: (id: string) => string | null | undefined;
  /** Optional -- lets the row-detail dialog print the quantity with its unit. */
  unit?: (productId: string) => string | null;
  /** Optional -- lets the row-detail dialog show the work order behind a movement, by its own reference. */
  workOrders?: { id: string; reference: string }[];
  /** Optional -- lets the row-detail dialog trace a regrind receipt back to the production OF(s) its scrap came from, keyed by the regrind batch's own work order id. */
  regrindSources?: Record<string, RegrindScrapInput[]>;
  showProductColumn?: boolean;
}) {
  const { t, language } = useI18n();
  const MOVE_TYPE_LABEL = useMoveTypeLabels();
  const REFERENCE_KIND_LABEL = useReferenceKindLabels();
  const [selectedMove, setSelectedMove] = useState<StockMove | null>(null);

  const allColumns: ColumnDef<StockMove>[] = [
    {
      key: "when",
      header: t("warehouse.stockHistory.column.when"),
      defaultWidth: 180,
      cell: (move) => <span className="whitespace-nowrap text-muted-foreground">{formatWhen(move.created_at, language)}</span>,
      sortValue: (move) => move.created_at,
    },
    {
      key: "product",
      header: t("warehouse.stockHistory.column.product"),
      defaultWidth: 200,
      cell: (move) => <span className="font-medium">{productName ? productName(move.product_id) : move.product_id}</span>,
      sortValue: (move) => (productName ? productName(move.product_id) : move.product_id),
    },
    {
      key: "location",
      header: t("warehouse.stockHistory.column.location"),
      defaultWidth: 160,
      cell: (move) => <span className="text-muted-foreground">{locationName(move.location_id)}</span>,
      sortValue: (move) => locationName(move.location_id),
    },
    {
      key: "type",
      header: t("warehouse.stockHistory.column.type"),
      defaultWidth: 220,
      cell: (move) => (
        <Badge variant={MOVE_TYPE_VARIANT[move.move_type]} dot className="max-w-full" title={MOVE_TYPE_LABEL[move.move_type]}>
          <span className="min-w-0 truncate">{MOVE_TYPE_LABEL[move.move_type]}</span>
        </Badge>
      ),
      sortValue: (move) => MOVE_TYPE_LABEL[move.move_type],
    },
    {
      key: "quantity",
      header: t("warehouse.stockHistory.column.quantity"),
      defaultWidth: 140,
      cell: (move) => {
        const signed = signedMoveQuantity(move);
        return (
          <span className={`tabular-nums ${signed < 0 ? "text-destructive" : "text-success"}`}>
            {signed > 0 ? "+" : ""}
            {signed}
          </span>
        );
      },
      sortValue: (move) => signedMoveQuantity(move),
    },
    {
      key: "reference",
      header: t("warehouse.stockHistory.column.reference"),
      defaultWidth: 220,
      cell: (move) => {
        const { label, suffix } = formatMoveReference(move.reference, REFERENCE_KIND_LABEL);
        return (
          <span className="flex min-w-0 items-baseline gap-1 text-muted-foreground" title={move.reference}>
            <span className="min-w-0 truncate">{label}</span>
            {suffix && <span className="shrink-0 font-mono text-xs text-muted-foreground/70">#{suffix}</span>}
          </span>
        );
      },
      sortValue: (move) => move.reference,
    },
    {
      key: "reason",
      header: t("warehouse.stockHistory.column.reason"),
      defaultWidth: 200,
      cell: (move) => <span className="text-muted-foreground">{move.reason ?? "—"}</span>,
      sortValue: (move) => move.reason,
    },
  ];
  const columns = showProductColumn ? allColumns : allColumns.filter((column) => column.key !== "product");
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns(tableKey, columns);
  const sortedMoves = sortRows(moves);

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
                sortDirection={sortDirectionFor(column.key)}
                onSort={column.sortValue ? () => toggleSort(column.key) : undefined}
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
          <AnimatePresence initial={false}>
            {sortedMoves.map((move) => (
              <motion.tr
                key={move.id}
                layout
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="cursor-pointer border-b border-border transition-colors hover:bg-muted/50"
                onClick={() => setSelectedMove(move)}
              >
                {visibleColumns.map((column) => (
                  <TableCell key={column.key} className={column.cellClassName}>
                    {column.cell(move)}
                  </TableCell>
                ))}
              </motion.tr>
            ))}
          </AnimatePresence>
        </TableBody>
      </Table>

      {selectedMove && (
        <StockMoveDetailDialog
          move={selectedMove}
          moveTypeLabel={MOVE_TYPE_LABEL[selectedMove.move_type]}
          productLabel={productName ? productName(selectedMove.product_id) : selectedMove.product_id}
          productSku={productSku?.(selectedMove.product_id)}
          locationLabel={locationName(selectedMove.location_id)}
          locationCode={locationCode?.(selectedMove.location_id)}
          unit={unit ? unit(selectedMove.product_id) : null}
          workOrders={workOrders}
          productName={productName}
          regrindSources={regrindSources}
          onClose={() => setSelectedMove(null)}
        />
      )}
    </div>
  );
}
