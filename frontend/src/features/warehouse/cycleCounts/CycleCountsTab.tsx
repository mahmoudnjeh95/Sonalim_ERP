import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import { Button } from "../../../components/ui/button";
import { Badge, type BadgeProps } from "../../../components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../../components/ui/table";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../../components/patterns/ColumnVisibilityMenu";
import { EmptyState } from "../../../components/patterns/EmptyState";
import CountSheetIcon from "../../../assets/icons/warehouse/count-sheet.svg?react";
import { listSites } from "../locations/api";
import { listLocations } from "../api";
import { CYCLE_COUNTS_QUERY_KEY, listCycleCounts, type CycleCount, type CycleCountStatus } from "./api";
import { NewCycleCountDialog } from "./NewCycleCountDialog";
import { CycleCountDetailDialog } from "./CycleCountDetailDialog";

const STATUS_VARIANT: Record<CycleCountStatus, BadgeProps["variant"]> = {
  draft: "default",
  in_progress: "warning",
  completed: "success",
  cancelled: "destructive",
};

const STATUS_FILTERS = ["all", "draft", "in_progress", "completed", "cancelled"] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

export function CycleCountsTab() {
  const { t } = useI18n();
  const { session, hasPermission } = useAuth();
  const token = session!.token;

  const { data: counts = [] } = useQuery({ queryKey: CYCLE_COUNTS_QUERY_KEY, queryFn: () => listCycleCounts(token) });
  const { data: sites = [] } = useQuery({ queryKey: ["warehouse", "sites"], queryFn: () => listSites(token) });
  const { data: locations = [] } = useQuery({ queryKey: ["warehouse", "locations"], queryFn: () => listLocations(token) });

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [newDialogOpen, setNewDialogOpen] = useState(false);
  const [openCountId, setOpenCountId] = useState<string | null>(null);

  const canManage = hasPermission("warehouse.manage_cycle_counts");

  const siteName = (siteId: string) => sites.find((s) => s.id === siteId)?.name ?? siteId;
  const scopeName = (scopeLocationId: string | null) =>
    scopeLocationId ? (locations.find((l) => l.id === scopeLocationId)?.name ?? scopeLocationId) : t("warehouse.cycleCounts.field.scope.wholeSite");

  const columnFilters = useColumnFilters<CycleCount>([
    { key: "site", kind: "text", getValue: (row) => siteName(row.site_id) },
    { key: "scope", kind: "text", getValue: (row) => scopeName(row.scope_location_id) },
  ]);

  const columns: ColumnDef<CycleCount>[] = [
    {
      key: "number",
      header: t("warehouse.cycleCounts.column.number"),
      cell: (row) => row.number ?? "—",
    },
    {
      key: "site",
      header: t("warehouse.cycleCounts.column.site"),
      cell: (row) => siteName(row.site_id),
      filterCell: {
        type: "text",
        placeholder: t("warehouse.cycleCounts.column.site"),
        value: columnFilters.text.site ?? "",
        onChange: (v) => columnFilters.setTextValue("site", v),
      },
    },
    {
      key: "scope",
      header: t("warehouse.cycleCounts.column.scope"),
      cell: (row) => scopeName(row.scope_location_id),
      filterCell: {
        type: "text",
        placeholder: t("warehouse.cycleCounts.column.scope"),
        value: columnFilters.text.scope ?? "",
        onChange: (v) => columnFilters.setTextValue("scope", v),
      },
    },
    {
      key: "type",
      header: t("warehouse.cycleCounts.column.type"),
      cell: (row) => <Badge variant="outline">{t(`warehouse.cycleCounts.type.${row.count_type}`)}</Badge>,
      filterCell: { type: "blank" },
    },
    {
      key: "status",
      header: t("warehouse.cycleCounts.column.status"),
      cell: (row) => <Badge variant={STATUS_VARIANT[row.status]}>{t(`warehouse.cycleCounts.status.${row.status}`)}</Badge>,
      filterCell: { type: "blank" },
    },
    {
      key: "created",
      header: t("warehouse.cycleCounts.column.created"),
      cell: (row) => new Date(row.created_at).toLocaleDateString(),
      filterCell: { type: "blank" },
    },
    {
      key: "actions",
      header: "",
      alwaysVisible: true,
      cell: (row) => (
        <Button variant="ghost" size="sm" onClick={() => setOpenCountId(row.id)}>
          {t("warehouse.cycleCounts.action.open")}
        </Button>
      ),
      filterCell: { type: "blank" },
    },
  ];

  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "warehouse.cycleCounts",
    columns,
  );

  const filteredByStatus = statusFilter === "all" ? counts : counts.filter((c) => c.status === statusFilter);
  const rows = columnFilters.apply(filteredByStatus);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <FilterTabs
          value={statusFilter}
          onChange={setStatusFilter}
          options={STATUS_FILTERS.map((s) => ({
            value: s,
            label: s === "all" ? t("common.all") : t(`warehouse.cycleCounts.status.${s}`),
          }))}
        />
        {columnFilters.isActive && (
          <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
            {t("common.clearFilters")}
          </Button>
        )}
        <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
        <div className="flex-1" />
        {canManage && (
          <Button size="sm" onClick={() => setNewDialogOpen(true)}>
            <Plus className="h-3.5 w-3.5" />
            {t("warehouse.cycleCounts.newCount")}
          </Button>
        )}
      </div>

      {rows.length === 0 ? (
        <EmptyState
          icon={<CountSheetIcon className="h-5 w-5" />}
          title={t("warehouse.cycleCounts.empty.title")}
          description={t("warehouse.cycleCounts.empty.description")}
        />
      ) : (
        <Table colWidths={colWidths}>
          <TableHeader>
            <TableRow>
              {visibleColumns.map((column) => (
                <ResizableTableHead key={column.key} width={getWidth(column.key)} onResize={(width) => setWidth(column.key, width)}>
                  {column.header}
                </ResizableTableHead>
              ))}
            </TableRow>
            <ColumnFilterRow cells={visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.id}>
                {visibleColumns.map((column) => (
                  <TableCell key={column.key}>{column.cell(row)}</TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <NewCycleCountDialog open={newDialogOpen} onOpenChange={setNewDialogOpen} />
      <CycleCountDetailDialog open={openCountId !== null} onOpenChange={(open) => { if (!open) setOpenCountId(null); }} cycleCountId={openCountId} />
    </div>
  );
}
