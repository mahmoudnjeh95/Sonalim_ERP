import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { AlertTriangle, Factory, Lightbulb } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { currentLocale, useI18n } from "../../lib/i18n";
import { formatQuantity } from "../../lib/units";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import { EmptyState } from "../../components/patterns/EmptyState";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { listOrders } from "../sales/api";
import { listOpportunities } from "../crm/opportunities/api";
import { listStock, listLocations, listUoms } from "../warehouse/api";
import { listPartners } from "../partners/api";
import { listProducts, listWorkOrders } from "./api";
import { computeProductionSuggestions, type ProductionSuggestion } from "./planning";
import { CreateOfFromSuggestionDialog } from "./CreateOfFromSuggestionDialog";

const ORDERS_QUERY_KEY = ["sales", "orders"] as const;
const OPPORTUNITIES_QUERY_KEY = ["crm", "opportunities"] as const;
const STOCK_QUERY_KEY = ["warehouse", "stock"] as const;
const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;
const PARTNERS_QUERY_KEY = ["core", "partners"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const UOMS_QUERY_KEY = ["core", "uoms"] as const;
const WORK_ORDERS_QUERY_KEY = ["production", "work-orders"] as const;

const DUE_SOON_DAYS = 7;

function daysUntil(dateIso: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(dateIso);
  return Math.round((target.getTime() - today.getTime()) / 86_400_000);
}

export function PlanningTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const canManageWorkOrders = hasPermission("production.manage_work_orders");
  const [selectedSuggestion, setSelectedSuggestion] = useState<ProductionSuggestion | null>(null);

  const { data: orders = [], isLoading: loadingOrders } = useQuery({ queryKey: ORDERS_QUERY_KEY, queryFn: () => listOrders(token) });
  const { data: opportunities = [] } = useQuery({ queryKey: OPPORTUNITIES_QUERY_KEY, queryFn: () => listOpportunities(token) });
  const { data: stock = [] } = useQuery({ queryKey: STOCK_QUERY_KEY, queryFn: () => listStock(token) });
  const { data: locations = [] } = useQuery({ queryKey: LOCATIONS_QUERY_KEY, queryFn: () => listLocations(token) });
  const { data: partners = [] } = useQuery({ queryKey: PARTNERS_QUERY_KEY, queryFn: () => listPartners(token) });
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: uoms = [] } = useQuery({ queryKey: UOMS_QUERY_KEY, queryFn: () => listUoms(token) });
  const { data: workOrders = [] } = useQuery({ queryKey: WORK_ORDERS_QUERY_KEY, queryFn: () => listWorkOrders(token) });

  const suggestions = useMemo(
    () => computeProductionSuggestions(orders, opportunities, stock, locations, workOrders),
    [orders, opportunities, stock, locations, workOrders],
  );

  const productName = (productId: string) => products.find((p) => p.id === productId)?.name ?? "—";
  const productUnitLabel = (productId: string) => {
    const product = products.find((p) => p.id === productId);
    const uom = product ? uoms.find((u) => u.id === product.uom_id) : undefined;
    return uom ? uom.symbol || uom.code : undefined;
  };
  const partnerNames = (suggestion: ProductionSuggestion) =>
    [...new Set(suggestion.contributingOrders.map((o) => partners.find((p) => p.id === o.partner_id)?.name ?? "—"))];

  const isLoading = loadingOrders;

  const columns: ColumnDef<ProductionSuggestion>[] = [
    {
      key: "product",
      header: t("production.planning.column.product"),
      defaultWidth: 180,
      cellClassName: "font-medium",
      cell: (suggestion) => productName(suggestion.product_id),
      sortValue: (suggestion) => productName(suggestion.product_id),
    },
    {
      key: "demand",
      header: t("production.planning.column.demand"),
      defaultWidth: 130,
      cellClassName: "tabular-nums",
      cell: (suggestion) => formatQuantity(suggestion.demandQty, productUnitLabel(suggestion.product_id)),
      sortValue: (suggestion) => suggestion.demandQty,
    },
    {
      key: "available",
      header: t("production.planning.column.available"),
      defaultWidth: 130,
      cellClassName: "tabular-nums text-muted-foreground",
      cell: (suggestion) => formatQuantity(suggestion.availableQty, productUnitLabel(suggestion.product_id)),
      sortValue: (suggestion) => suggestion.availableQty,
    },
    {
      key: "plannedOf",
      header: t("production.planning.column.plannedOf"),
      defaultWidth: 130,
      cellClassName: "tabular-nums text-muted-foreground",
      cell: (suggestion) => formatQuantity(suggestion.openOfQty, productUnitLabel(suggestion.product_id)),
      sortValue: (suggestion) => suggestion.openOfQty,
    },
    {
      key: "shortfall",
      header: t("production.planning.column.shortfall"),
      defaultWidth: 130,
      cellClassName: "font-medium tabular-nums text-destructive",
      cell: (suggestion) => formatQuantity(suggestion.shortfallQty, productUnitLabel(suggestion.product_id)),
      sortValue: (suggestion) => suggestion.shortfallQty,
    },
    {
      key: "shipDate",
      header: (
        <span className="inline-flex items-center gap-1">
          {t("production.planning.column.shipDate")}
          <HelpTooltip text={t("production.planning.subtitle")} />
        </span>
      ),
      defaultWidth: 180,
      cell: (suggestion) => {
        const daysAway = suggestion.earliestShipDate ? daysUntil(suggestion.earliestShipDate) : null;
        const isOverdue = daysAway !== null && daysAway < 0;
        const isDueSoon = daysAway !== null && daysAway >= 0 && daysAway <= DUE_SOON_DAYS;
        return suggestion.earliestShipDate ? (
          <span className="flex items-center gap-1.5">
            {new Date(suggestion.earliestShipDate).toLocaleDateString(currentLocale())}
            {(isOverdue || isDueSoon) && (
              <Badge variant={isOverdue ? "destructive" : "warning"}>
                <AlertTriangle className="h-3 w-3" />
                {isOverdue ? t("production.planning.urgency.overdue") : t("production.planning.urgency.dueSoon")}
              </Badge>
            )}
          </span>
        ) : (
          <span className="text-muted-foreground">{t("production.planning.noShipDate")}</span>
        );
      },
      sortValue: (suggestion) => suggestion.earliestShipDate ?? "",
    },
    {
      key: "deals",
      header: t("production.planning.column.deals"),
      defaultWidth: 220,
      cellClassName: "max-w-[220px] truncate text-muted-foreground",
      cell: (suggestion) => (
        <span title={partnerNames(suggestion).join(", ")}>
          {suggestion.contributingOrders.length} · {partnerNames(suggestion).join(", ")}
        </span>
      ),
    },
    {
      key: "action",
      header: t("production.planning.column.action"),
      defaultWidth: 140,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right",
      cell: (suggestion) => (
        <Button
          size="sm"
          variant="outline"
          disabled={!canManageWorkOrders}
          title={canManageWorkOrders ? undefined : t("production.planning.createOf")}
          onClick={() => setSelectedSuggestion(suggestion)}
        >
          <Factory className="h-3.5 w-3.5" />
          {t("production.planning.createOf")}
        </Button>
      ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("production.planning", columns);
  const sortedSuggestions = sortRows(suggestions);

  return (
    <div className="space-y-6">
      <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 className="text-xl font-semibold tracking-tight">{t("production.planning.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("production.planning.subtitle")}</p>
      </motion.div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            <Lightbulb className="h-4 w-4" />
            {t("production.planning.title")}
          </CardTitle>
          <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
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
              {!isLoading && suggestions.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <EmptyState
                      icon={<Factory className="h-5 w-5" />}
                      title={t("production.planning.empty.title")}
                      description={t("production.planning.empty.description")}
                    />
                  </TableCell>
                </TableRow>
              )}
              {sortedSuggestions.map((suggestion) => (
                <TableRow key={suggestion.product_id}>
                  {visibleColumns.map((column) => (
                    <TableCell key={column.key} className={column.cellClassName}>
                      {column.cell(suggestion)}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <CreateOfFromSuggestionDialog suggestion={selectedSuggestion} onOpenChange={(open) => !open && setSelectedSuggestion(null)} />
    </div>
  );
}
