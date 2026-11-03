import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
import ShipmentIcon from "../../../assets/icons/warehouse/shipment.svg?react";
import { listPartners } from "../../partners/api";
import { listLocations } from "../api";
import { listPickLists, listShipments, PICK_LISTS_QUERY_KEY, SHIPMENTS_QUERY_KEY, type PickList, type PickListStatus } from "./api";
import { PickListDetailDialog } from "./PickListDetailDialog";

const STATUS_VARIANT: Record<PickListStatus, BadgeProps["variant"]> = {
  open: "default",
  picking: "warning",
  picked: "primary",
  shipped: "success",
  cancelled: "destructive",
};

const STATUS_FILTERS = ["all", "open", "picking", "picked", "shipped", "cancelled"] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

export function FulfillmentTab() {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;

  const { data: pickLists = [] } = useQuery({ queryKey: PICK_LISTS_QUERY_KEY, queryFn: () => listPickLists(token) });
  const { data: shipments = [] } = useQuery({ queryKey: SHIPMENTS_QUERY_KEY, queryFn: () => listShipments(token) });
  const { data: partners = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token) });
  const { data: locations = [] } = useQuery({ queryKey: ["warehouse", "locations"], queryFn: () => listLocations(token) });

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [openId, setOpenId] = useState<string | null>(null);

  const customerName = (partnerId: string | null) =>
    partnerId ? (partners.find((p) => p.id === partnerId)?.name ?? partnerId) : "—";
  const locationName = (locationId: string) => locations.find((l) => l.id === locationId)?.name ?? locationId;
  const shipmentFor = (pickListId: string) => shipments.find((s) => s.pick_list_id === pickListId);

  const columnFilters = useColumnFilters<PickList>([
    { key: "number", kind: "text", getValue: (row) => row.number },
    { key: "customer", kind: "text", getValue: (row) => customerName(row.partner_id) },
    { key: "location", kind: "text", getValue: (row) => locationName(row.location_id) },
    { key: "shipment", kind: "text", getValue: (row) => shipmentFor(row.id)?.number ?? "" },
  ]);

  const columns: ColumnDef<PickList>[] = [
    {
      key: "number",
      header: t("warehouse.fulfillment.column.number"),
      cell: (row) => <span className="font-mono text-xs">{row.number}</span>,
      filterCell: columnFilters.textCell("number", t("warehouse.fulfillment.column.number")),
    },
    {
      key: "customer",
      header: t("warehouse.fulfillment.column.customer"),
      cell: (row) => customerName(row.partner_id),
      filterCell: columnFilters.textCell("customer", t("warehouse.fulfillment.column.customer")),
    },
    {
      key: "location",
      header: t("warehouse.fulfillment.column.location"),
      cell: (row) => locationName(row.location_id),
      filterCell: columnFilters.textCell("location", t("warehouse.fulfillment.column.location")),
    },
    {
      key: "status",
      header: t("warehouse.fulfillment.column.status"),
      cell: (row) => <Badge variant={STATUS_VARIANT[row.status]}>{t(`warehouse.fulfillment.status.${row.status}`)}</Badge>,
      filterCell: { type: "blank" },
    },
    {
      key: "shipment",
      header: t("warehouse.fulfillment.column.shipment"),
      cell: (row) => {
        const shipment = shipmentFor(row.id);
        return shipment ? <span className="font-mono text-xs">{shipment.number}</span> : "—";
      },
      filterCell: columnFilters.textCell("shipment", t("warehouse.fulfillment.column.shipment")),
    },
    {
      key: "created",
      header: t("warehouse.fulfillment.column.created"),
      cell: (row) => new Date(row.created_at).toLocaleDateString(),
      filterCell: { type: "blank" },
    },
    {
      key: "actions",
      header: "",
      alwaysVisible: true,
      cell: (row) => (
        <Button variant="ghost" size="sm" onClick={() => setOpenId(row.id)}>
          {t("warehouse.fulfillment.action.open")}
        </Button>
      ),
      filterCell: { type: "blank" },
    },
  ];

  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "warehouse.pickLists",
    columns,
  );

  const filteredByStatus = statusFilter === "all" ? pickLists : pickLists.filter((p) => p.status === statusFilter);
  const rows = columnFilters.apply(filteredByStatus);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <FilterTabs
          value={statusFilter}
          onChange={setStatusFilter}
          options={STATUS_FILTERS.map((s) => ({
            value: s,
            label: s === "all" ? t("common.all") : t(`warehouse.fulfillment.status.${s}`),
          }))}
        />
        {columnFilters.isActive && (
          <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
            {t("common.clearFilters")}
          </Button>
        )}
        <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
      </div>

      {rows.length === 0 ? (
        <EmptyState
          icon={<ShipmentIcon className="h-5 w-5" />}
          title={t("warehouse.fulfillment.empty.title")}
          description={t("warehouse.fulfillment.empty.description")}
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

      <PickListDetailDialog
        open={openId !== null}
        onOpenChange={(open) => {
          if (!open) setOpenId(null);
        }}
        pickListId={openId}
        customerName={customerName}
      />
    </div>
  );
}
