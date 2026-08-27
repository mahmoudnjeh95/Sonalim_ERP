import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Ban, CheckCircle2, ListTree } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
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
import { listProducts } from "../warehouse/api";
import { listLots, transitionLot, type Lot, type LotStatus } from "./api";

const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const LOTS_QUERY_KEY = ["warehouse", "lots"] as const;

const LOT_STATUS_VARIANT: Record<LotStatus, BadgeProps["variant"]> = {
  active: "success",
  consumed: "outline",
  expired: "destructive",
};

type StatusFilter = "all" | LotStatus;

export function LotsSerialsTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: allLots = [], isLoading } = useQuery({ queryKey: LOTS_QUERY_KEY, queryFn: () => listLots(token) });

  const productName = (id: string) => products.find((p) => p.id === id)?.name ?? id;

  const transitionMutation = useMutation({
    mutationFn: ({ lotId, newStatus }: { lotId: string; newStatus: LotStatus }) => transitionLot(token, lotId, newStatus),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: LOTS_QUERY_KEY });
      toast.success(t("products.lotsSerials.updated"));
    },
    onError: (error) => {
      toast.error(t("products.lotsSerials.updateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const statusFilteredLots = statusFilter === "all" ? allLots : allLots.filter((lot) => lot.status === statusFilter);

  const columnFilterFields: FilterField<Lot>[] = [
    { key: "product", kind: "text", getValue: (l) => productName(l.product_id) },
    { key: "lot_number", kind: "text", getValue: (l) => l.lot_number },
    { key: "source_type", kind: "text", getValue: (l) => l.source_type ?? "" },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const lots = columnFilters.apply(statusFilteredLots);

  const columns: ColumnDef<Lot>[] = [
    {
      key: "product",
      header: t("products.column.label"),
      defaultWidth: 200,
      cell: (lot) => <span className="font-medium">{productName(lot.product_id)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.product ?? "",
        onChange: (v) => columnFilters.setTextValue("product", v),
        placeholder: t("products.column.label"),
      },
    },
    {
      key: "lot_number",
      header: t("products.stocksByLot.column.lotNumber"),
      defaultWidth: 160,
      cell: (lot) => <span className="text-muted-foreground">{lot.lot_number}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.lot_number ?? "",
        onChange: (v) => columnFilters.setTextValue("lot_number", v),
        placeholder: t("products.stocksByLot.column.lotNumber"),
      },
    },
    {
      key: "status",
      header: t("products.column.status"),
      defaultWidth: 140,
      cell: (lot) => (
        <Badge variant={LOT_STATUS_VARIANT[lot.status]} dot>
          {t(`products.lotStatus.${lot.status}` as Parameters<typeof t>[0])}
        </Badge>
      ),
    },
    {
      key: "expiry_date",
      header: t("products.stocksByLot.column.expiryDate"),
      defaultWidth: 140,
      cell: (lot) => <span className="text-muted-foreground">{lot.expiry_date ?? "—"}</span>,
    },
    {
      key: "source_type",
      header: t("products.lotsSerials.column.source"),
      defaultWidth: 160,
      cell: (lot) => <span className="text-muted-foreground">{lot.source_type ?? "—"}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.source_type ?? "",
        onChange: (v) => columnFilters.setTextValue("source_type", v),
        placeholder: t("products.lotsSerials.column.source"),
      },
    },
    {
      key: "action",
      header: t("products.column.action"),
      defaultWidth: 260,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right",
      cell: (lot) =>
        lot.status === "active" && (
          <div className="flex justify-end gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => transitionMutation.mutate({ lotId: lot.id, newStatus: "consumed" })}
              disabled={transitionMutation.isPending}
            >
              <CheckCircle2 className="h-3.5 w-3.5" />
              {t("products.lotsSerials.action.consume")}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => transitionMutation.mutate({ lotId: lot.id, newStatus: "expired" })}
              disabled={transitionMutation.isPending}
            >
              <Ban className="h-3.5 w-3.5" />
              {t("products.lotsSerials.action.expire")}
            </Button>
          </div>
        ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "products.lotsSerials",
    columns,
  );

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <CardTitle>{t("products.lotsSerials.title")}</CardTitle>
            <p className="mt-0.5 text-sm text-muted-foreground">{t("products.lotsSerials.subtitle")}</p>
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
            {!isLoading && lots.length === 0 && (
              <TableRow>
                <TableCell colSpan={visibleColumns.length} className="p-0">
                  <EmptyState icon={<ListTree className="h-5 w-5" />} title={t("products.lotsSerials.empty.title")} description={t("products.lotsSerials.empty.description")} />
                </TableCell>
              </TableRow>
            )}
            <AnimatePresence initial={false}>
              {lots.map((lot: Lot, i) => (
                <motion.tr
                  key={lot.id}
                  layout
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i * 0.04, 0.3) } }}
                  exit={{ opacity: 0 }}
                  className="border-b border-border last:border-0 hover:bg-muted/50"
                >
                  {visibleColumns.map((column) => (
                    <TableCell key={column.key} className={column.cellClassName}>
                      {column.cell(lot)}
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
