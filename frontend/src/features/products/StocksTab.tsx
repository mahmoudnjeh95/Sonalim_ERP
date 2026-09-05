import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, Boxes } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { Skeleton } from "../../components/ui/skeleton";
import { Badge } from "../../components/ui/badge";
import { EmptyState } from "../../components/patterns/EmptyState";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { listProducts, listStock, listUoms, type Product } from "../warehouse/api";

const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const STOCK_QUERY_KEY = ["warehouse", "stock"] as const;

interface StockRow {
  product: Product;
  onHand: number;
  reserved: number;
  available: number;
  belowAlert: boolean;
}

type AlertFilter = "all" | "belowAlert";

export function StocksTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [alertFilter, setAlertFilter] = useState<AlertFilter>("all");

  const { data: products = [], isLoading: loadingProducts } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: stockItems = [], isLoading: loadingStock } = useQuery({ queryKey: STOCK_QUERY_KEY, queryFn: () => listStock(token) });
  const { data: uoms = [] } = useQuery({ queryKey: ["core", "uoms"], queryFn: () => listUoms(token) });
  const isLoading = loadingProducts || loadingStock;
  // The printed form, not the code: "pièce" is what a reader expects beside a
  // count, and `code` stays the key imports and integrations match on.
  const uomCode = (uomId: string) => {
    const uom = uoms.find((u) => u.id === uomId);
    return uom ? uom.symbol || uom.code : uomId;
  };

  const byProduct = new Map<string, { onHand: number; reserved: number; available: number }>();
  for (const item of stockItems) {
    const bucket = byProduct.get(item.product_id) ?? { onHand: 0, reserved: 0, available: 0 };
    bucket.onHand += item.quantity_on_hand;
    bucket.reserved += item.quantity_reserved;
    bucket.available += item.quantity_available;
    byProduct.set(item.product_id, bucket);
  }

  const allRows: StockRow[] = products
    .map((product) => {
      const totals = byProduct.get(product.id) ?? { onHand: 0, reserved: 0, available: 0 };
      const belowAlert = product.stock_alert_threshold != null && totals.onHand < product.stock_alert_threshold;
      return { product, ...totals, belowAlert };
    })
    .filter((row) => row.onHand !== 0 || row.reserved !== 0);

  const alertFilteredRows = alertFilter === "belowAlert" ? allRows.filter((row) => row.belowAlert) : allRows;

  const columnFilterFields: FilterField<StockRow>[] = [
    { key: "product", kind: "text", getValue: (r) => r.product.name },
    { key: "onHand", kind: "range", getValue: (r) => r.onHand },
    { key: "reserved", kind: "range", getValue: (r) => r.reserved },
    { key: "available", kind: "range", getValue: (r) => r.available },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const rows = columnFilters.apply(alertFilteredRows);

  const columns: ColumnDef<StockRow>[] = [
    {
      key: "product",
      header: t("products.column.label"),
      defaultWidth: 220,
      cell: (row) => <span className="font-medium">{row.product.name}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.product ?? "",
        onChange: (v) => columnFilters.setTextValue("product", v),
        placeholder: t("products.column.label"),
      },
      sortValue: (row) => row.product.name,
    },
    {
      key: "unit",
      header: t("products.stocks.column.unit"),
      defaultWidth: 100,
      cell: (row) => <span className="text-muted-foreground">{uomCode(row.product.uom_id)}</span>,
      sortValue: (row) => uomCode(row.product.uom_id),
    },
    {
      key: "onHand",
      header: t("products.stocks.column.onHand"),
      defaultWidth: 140,
      cell: (row) => <span className="tabular-nums text-muted-foreground">{row.onHand}</span>,
      filterCell: {
        type: "range",
        min: columnFilters.range.onHand?.min ?? "",
        max: columnFilters.range.onHand?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("onHand", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("onHand", "max", v),
      },
      sortValue: (row) => row.onHand,
    },
    {
      key: "reserved",
      header: (
        <span className="inline-flex items-center gap-1">
          {t("products.stocks.column.reserved")}
          <HelpTooltip text={t("warehouse.stock.help.reserved")} />
        </span>
      ),
      defaultWidth: 140,
      cell: (row) => <span className="tabular-nums text-muted-foreground">{row.reserved}</span>,
      filterCell: {
        type: "range",
        min: columnFilters.range.reserved?.min ?? "",
        max: columnFilters.range.reserved?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("reserved", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("reserved", "max", v),
      },
      sortValue: (row) => row.reserved,
    },
    {
      key: "available",
      header: (
        <span className="inline-flex items-center gap-1">
          {t("products.stocks.column.available")}
          <HelpTooltip text={t("products.stocks.help.available")} />
        </span>
      ),
      defaultWidth: 140,
      cell: (row) => <span className="tabular-nums text-muted-foreground">{row.available}</span>,
      filterCell: {
        type: "range",
        min: columnFilters.range.available?.min ?? "",
        max: columnFilters.range.available?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("available", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("available", "max", v),
      },
      sortValue: (row) => row.available,
    },
    {
      key: "alert",
      header: (
        <span className="inline-flex items-center gap-1">
          {t("products.stocks.column.alert")}
          <HelpTooltip text={t("products.help.stockAlert")} />
        </span>
      ),
      defaultWidth: 160,
      cell: (row) =>
        row.belowAlert ? (
          <Badge variant="warning" dot>
            <AlertTriangle className="h-3 w-3" />
            {t("products.stocks.belowAlert")}
          </Badge>
        ) : (
          "—"
        ),
      sortValue: (row) => row.belowAlert,
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("products.stocks", columns);
  const sortedRows = sortRows(rows);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <CardTitle>{t("products.stocks.title")}</CardTitle>
            <p className="mt-0.5 text-sm text-muted-foreground">{t("products.stocks.subtitle")}</p>
          </div>
          <FilterTabs
            value={alertFilter}
            onChange={setAlertFilter}
            options={[
              { value: "all", label: t("common.all") },
              { value: "belowAlert", label: t("products.stocks.belowAlert") },
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
                  <EmptyState icon={<Boxes className="h-5 w-5" />} title={t("products.stocks.empty.title")} description={t("products.stocks.empty.description")} />
                </TableCell>
              </TableRow>
            )}
            <AnimatePresence initial={false}>
              {sortedRows.map((row, i) => (
                <motion.tr
                  key={row.product.id}
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
