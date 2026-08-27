import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { History } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { Skeleton } from "../../components/ui/skeleton";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { listAuditLog, listProducts, type AuditLogEntry } from "./api";

const HISTORY_QUERY_KEY = ["core", "audit-log", "material_receipt"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;

const KNOWN_ACTIONS = ["created", "status_changed", "status_forced", "updated", "deleted"] as const;
type ActionFilter = "all" | (typeof KNOWN_ACTIONS)[number];

function actionSuffix(action: string): string {
  return action.split(".").pop() ?? "";
}

function formatWhen(iso: string, language: string) {
  return new Date(iso).toLocaleString(language === "fr" ? "fr-FR" : "en-US", { dateStyle: "medium", timeStyle: "short" });
}

function describePayload(entry: AuditLogEntry, productName: (id: string) => string): string {
  const payload = entry.payload;
  if (entry.action === "material_receipt.created") {
    const productId = payload.product_id as string | undefined;
    return productId ? productName(productId) : "—";
  }
  if (entry.action === "material_receipt.status_changed" || entry.action === "material_receipt.status_forced") {
    return `${payload.from_status ?? "?"} → ${payload.to_status ?? "?"}`;
  }
  if (entry.action === "material_receipt.updated") {
    const changes = payload.changes as Record<string, string> | undefined;
    return changes ? Object.keys(changes).join(", ") : "—";
  }
  if (entry.action === "material_receipt.deleted") {
    return String(payload.invoice_number ?? payload.product_id ?? "—");
  }
  return "—";
}

export function HistoryTab() {
  const { session } = useAuth();
  const { t, language } = useI18n();
  const token = session!.token;
  const [actionFilter, setActionFilter] = useState<ActionFilter>("all");

  const { data: entries = [], isLoading } = useQuery({
    queryKey: HISTORY_QUERY_KEY,
    queryFn: () => listAuditLog(token, { entity_type: "material_receipt", limit: 500 }),
  });
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const productName = (productId: string) => products.find((p) => p.id === productId)?.name ?? productId;

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
    { key: "details", kind: "text", getValue: (entry) => describePayload(entry, productName) },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredEntries = columnFilters.apply(actionFilteredEntries);

  const columns: ColumnDef<AuditLogEntry>[] = [
    {
      key: "when",
      header: t("warehouse.history.column.when"),
      defaultWidth: 180,
      cell: (entry) => <span className="whitespace-nowrap text-muted-foreground">{formatWhen(entry.occurred_at, language)}</span>,
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
    },
    {
      key: "action",
      header: t("warehouse.history.column.action"),
      defaultWidth: 180,
      cell: (entry) => <span className="whitespace-nowrap font-medium">{actionLabel(entry.action)}</span>,
    },
    {
      key: "details",
      header: t("warehouse.history.column.details"),
      defaultWidth: 240,
      cell: (entry) => <span className="text-muted-foreground">{describePayload(entry, productName)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.details ?? "",
        onChange: (v) => columnFilters.setTextValue("details", v),
        placeholder: t("warehouse.history.column.details"),
      },
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "warehouse.history",
    columns,
  );

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
                >
                  {column.header}
                </ResizableTableHead>
              ))}
            </TableRow>
            <ColumnFilterRow cells={visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
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
            {!isLoading && filteredEntries.length === 0 && (
              <TableRow>
                <TableCell colSpan={visibleColumns.length} className="p-0">
                  <EmptyState icon={<History className="h-5 w-5" />} title={t("warehouse.history.empty.title")} description={t("warehouse.history.empty.description")} />
                </TableCell>
              </TableRow>
            )}
            {filteredEntries.map((entry) => (
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
