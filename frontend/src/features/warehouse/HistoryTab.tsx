import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { History } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { listAuditLog, type AuditLogEntry } from "../admin/activityLog/api";
import { listPurchaseOrders, type PurchaseOrder } from "../procurement/api";
import { listPartners } from "../partners/api";
import { TableLoadingRow } from "../../components/patterns/AppLoader";

const HISTORY_QUERY_KEY = ["core", "audit-log", "purchase_order_receipt"] as const;
const PURCHASE_ORDERS_QUERY_KEY = ["procurement", "purchase-orders"] as const;
const PARTNERS_QUERY_KEY = ["core", "partners"] as const;

const KNOWN_ACTIONS = ["created", "confirmed"] as const;
type ActionFilter = "all" | (typeof KNOWN_ACTIONS)[number];

function actionSuffix(action: string): string {
  return action.split(".").pop() ?? "";
}

function formatWhen(iso: string, language: string) {
  return new Date(iso).toLocaleString(language === "fr" ? "fr-FR" : "en-US", { dateStyle: "medium", timeStyle: "short" });
}

export function HistoryTab() {
  const { session } = useAuth();
  const { t, language } = useI18n();
  const token = session!.token;
  const [actionFilter, setActionFilter] = useState<ActionFilter>("all");

  const { data: entries = [], isLoading } = useQuery({
    queryKey: HISTORY_QUERY_KEY,
    queryFn: () => listAuditLog(token, { entity_type: "purchase_order_receipt", limit: 500 }),
  });
  const { data: purchaseOrders = [] } = useQuery({ queryKey: PURCHASE_ORDERS_QUERY_KEY, queryFn: () => listPurchaseOrders(token) });
  const { data: partners = [] } = useQuery({ queryKey: PARTNERS_QUERY_KEY, queryFn: () => listPartners(token) });
  const partnerName = (partnerId: string | null) => (partnerId ? partners.find((p) => p.id === partnerId)?.name ?? partnerId : "—");
  const orderLabel = (order: PurchaseOrder | undefined) => (order ? partnerName(order.supplier_id) : "—");
  const orderForReceipt = (entry: AuditLogEntry) => purchaseOrders.find((o) => o.id === (entry.payload.purchase_order_id as string | undefined));

  function describePayload(entry: AuditLogEntry): string {
    const payload = entry.payload;
    if (entry.action === "purchase_order_receipt.created") {
      const lineCount = payload.line_count as number | undefined;
      const totalCost = payload.total_cost as number | undefined;
      return `${lineCount ?? "?"} ${t("warehouse.history.lines")} · ${totalCost ?? "?"}`;
    }
    if (entry.action === "purchase_order_receipt.confirmed") {
      return `${payload.from_status ?? "?"} → ${payload.to_status ?? "?"}`;
    }
    return "—";
  }

  function actionLabel(action: string): string {
    const suffix = actionSuffix(action);
    if ((KNOWN_ACTIONS as readonly string[]).includes(suffix)) {
      return t(`warehouse.history.action.${suffix}` as Parameters<typeof t>[0]);
    }
    return action;
  }

  const actionFilteredEntries = actionFilter === "all" ? entries : entries.filter((entry) => actionSuffix(entry.action) === actionFilter);

  const columnFilterFields: FilterField<AuditLogEntry>[] = [
    { key: "who", kind: "text", getValue: (entry) => entry.actor_email ?? entry.actor_id },
    { key: "supplier", kind: "text", getValue: (entry) => orderLabel(orderForReceipt(entry)) },
    { key: "details", kind: "text", getValue: (entry) => describePayload(entry) },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredEntries = columnFilters.apply(actionFilteredEntries);

  const columns: ColumnDef<AuditLogEntry>[] = [
    {
      key: "when",
      header: t("warehouse.history.column.when"),
      defaultWidth: 180,
      cell: (entry) => <span className="whitespace-nowrap text-muted-foreground">{formatWhen(entry.occurred_at, language)}</span>,
      sortValue: (entry) => entry.occurred_at,
    },
    {
      key: "who",
      header: t("warehouse.history.column.who"),
      defaultWidth: 180,
      cell: (entry) => <span className="whitespace-nowrap">{entry.actor_email ?? entry.actor_id}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.who ?? "",
        onChange: (v) => columnFilters.setTextValue("who", v),
        placeholder: t("warehouse.history.column.who"),
      },
      sortValue: (entry) => entry.actor_email ?? entry.actor_id,
    },
    {
      key: "supplier",
      header: t("warehouse.history.column.supplier"),
      defaultWidth: 180,
      cell: (entry) => <span className="whitespace-nowrap">{orderLabel(orderForReceipt(entry))}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.supplier ?? "",
        onChange: (v) => columnFilters.setTextValue("supplier", v),
        placeholder: t("warehouse.history.column.supplier"),
      },
      sortValue: (entry) => orderLabel(orderForReceipt(entry)),
    },
    {
      key: "action",
      header: t("warehouse.history.column.action"),
      defaultWidth: 180,
      cell: (entry) => <span className="whitespace-nowrap font-medium">{actionLabel(entry.action)}</span>,
      sortValue: (entry) => actionLabel(entry.action),
    },
    {
      key: "details",
      header: t("warehouse.history.column.details"),
      defaultWidth: 240,
      cell: (entry) => <span className="text-muted-foreground">{describePayload(entry)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.details ?? "",
        onChange: (v) => columnFilters.setTextValue("details", v),
        placeholder: t("warehouse.history.column.details"),
      },
      sortValue: (entry) => describePayload(entry),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("warehouse.history", columns);
  const sortedEntries = sortRows(filteredEntries);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <CardTitle>{t("warehouse.history.title")}</CardTitle>
            <CardDescription>{t("warehouse.history.subtitle")}</CardDescription>
          </div>
          <FilterTabs
            value={actionFilter}
            onChange={setActionFilter}
            options={[
              { value: "all", label: t("common.all") },
              ...KNOWN_ACTIONS.map((action) => ({
                value: action,
                label: t(`warehouse.history.action.${action}` as Parameters<typeof t>[0]),
              })),
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
            {isLoading && <TableLoadingRow colSpan={visibleColumns.length} />}
            {!isLoading && filteredEntries.length === 0 && (
              <TableRow>
                <TableCell colSpan={visibleColumns.length} className="p-0">
                  <EmptyState icon={<History className="h-5 w-5" />} title={t("warehouse.history.empty.title")} description={t("warehouse.history.empty.description")} />
                </TableCell>
              </TableRow>
            )}
            {sortedEntries.map((entry) => (
              <TableRow key={entry.id}>
                {visibleColumns.map((column) => (
                  <TableCell key={column.key} className={column.cellClassName}>
                    {column.cell(entry)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
