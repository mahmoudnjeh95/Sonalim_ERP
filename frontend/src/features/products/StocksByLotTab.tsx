import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { ListTree } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { Skeleton } from "../../components/ui/skeleton";
import { Badge, type BadgeProps } from "../../components/ui/badge";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { listProducts, listLocations } from "../warehouse/api";
import { listLotStock, type LotStatus, type LotStockRow } from "./api";

const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;
const LOT_STOCK_QUERY_KEY = ["warehouse", "lot-stock"] as const;

const LOT_STATUS_VARIANT: Record<LotStatus, BadgeProps["variant"]> = {
  active: "success",
  consumed: "outline",
  expired: "destructive",
};

type StatusFilter = "all" | LotStatus;

export function StocksByLotTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: locations = [] } = useQuery({ queryKey: LOCATIONS_QUERY_KEY, queryFn: () => listLocations(token) });
  const { data: allRows = [], isLoading } = useQuery({ queryKey: LOT_STOCK_QUERY_KEY, queryFn: () => listLotStock(token) });

  const productName = (id: string) => products.find((p) => p.id === id)?.name ?? "—";
  const locationName = (id: string) => locations.find((l) => l.id === id)?.name ?? "—";

  const statusFilteredRows = statusFilter === "all" ? allRows : allRows.filter((row) => row.status === statusFilter);

  const columnFilterFields: FilterField<LotStockRow>[] = [
    { key: "product", kind: "text", getValue: (r) => productName(r.product_id) },
    { key: "lot_number", kind: "text", getValue: (r) => r.lot_number },
    { key: "location", kind: "text", getValue: (r) => locationName(r.location_id) },
    { key: "quantity_on_hand", kind: "range", getValue: (r) => r.quantity_on_hand },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const rows = columnFilters.apply(statusFilteredRows);

  const columns: ColumnDef<LotStockRow>[] = [
    {
      key: "product",
      header: t("products.column.label"),
      defaultWidth: 200,
      cell: (row) => <span className="font-medium">{productName(row.product_id)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.product ?? "",
        onChange: (v) => columnFilters.setTextValue("product", v),
        placeholder: t("products.column.label"),
      },
      sortValue: (row) => productName(row.product_id),
    },
    {
      key: "lot_number",
      header: t("products.stocksByLot.column.lotNumber"),
      defaultWidth: 160,
      cell: (row) => <span className="text-muted-foreground">{row.lot_number}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.lot_number ?? "",
        onChange: (v) => columnFilters.setTextValue("lot_number", v),
        placeholder: t("products.stocksByLot.column.lotNumber"),
      },
      sortValue: (row) => row.lot_number,
    },
    {
      key: "location",
      header: t("products.stocksByLot.column.location"),
      defaultWidth: 160,
      cell: (row) => <span className="text-muted-foreground">{locationName(row.location_id)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.location ?? "",
        onChange: (v) => columnFilters.setTextValue("location", v),
        placeholder: t("products.stocksByLot.column.location"),
      },
      sortValue: (row) => locationName(row.location_id),
    },
    {
      key: "quantity_on_hand",
      header: t("products.stocksByLot.column.quantity"),
      defaultWidth: 140,
      cell: (row) => <span className="tabular-nums text-muted-foreground">{row.quantity_on_hand}</span>,
      filterCell: {
        type: "range",
        min: columnFilters.range.quantity_on_hand?.min ?? "",
        max: columnFilters.range.quantity_on_hand?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("quantity_on_hand", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("quantity_on_hand", "max", v),
      },
      sortValue: (row) => row.quantity_on_hand,
    },
    {
      key: "expiry_date",
      header: t("products.stocksByLot.column.expiryDate"),
      defaultWidth: 140,
      cell: (row) => <span className="text-muted-foreground">{row.expiry_date ?? "—"}</span>,
      sortValue: (row) => row.expiry_date,
    },
    {
      key: "status",
      header: t("products.column.status"),
      defaultWidth: 140,
      cell: (row) => (
        <Badge variant={LOT_STATUS_VARIANT[row.status]} dot>
          {t(`products.lotStatus.${row.status}` as Parameters<typeof t>[0])}
        </Badge>
      ),
      sortValue: (row) => row.status,
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("products.stocksByLot", columns);
  const sortedRows = sortRows(rows);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <CardTitle>{t("products.stocksByLot.title")}</CardTitle>
            <p className="mt-0.5 text-sm text-muted-foreground">{t("products.stocksByLot.subtitle")}</p>
          </div>
          <FilterTabs
            value={statusFilter}
            onChange={setStatusFilter}
            options={[
              { value: "all", label: t("common.all") },
              { value: "active", label: t("products.lotStatus.active") },
              { value: "consumed", label: t("products.lotStatus.consumed") },
              { value: "expired", label: t("products.lotStatus.expired") },
            ]}
          />
          {columnFilters.isActive && (
            <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
              {t("common.clearFilters")}
            </Button>
          )}
          <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
        </div>
      </CardHeader>
      <CardContent className="p-0">
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
            {isLoading &&
              Array.from({ length: 3 }).map((_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={visibleColumns.length}>
                    <Skeleton className="h-5 w-full" />
                  </TableCell>
                </TableRow>
              ))}
            {!isLoading && rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={visibleColumns.length} className="p-0">
                  <EmptyState icon={<ListTree className="h-5 w-5" />} title={t("products.stocksByLot.empty.title")} description={t("products.stocksByLot.empty.description")} />
                </TableCell>
              </TableRow>
            )}
            <AnimatePresence initial={false}>
              {sortedRows.map((row, i) => (
                <motion.tr
                  key={`${row.lot_id}-${row.location_id}`}
                  layout
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i * 0.04, 0.3) } }}
                  exit={{ opacity: 0 }}
                  className="border-b border-border last:border-0 hover:bg-muted/50"
                >
                  {visibleColumns.map((column) => (
                    <TableCell key={column.key} className={column.cellClassName}>
                      {column.cell(row)}
                    </TableCell>
                  ))}
                </motion.tr>
              ))}
            </AnimatePresence>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
