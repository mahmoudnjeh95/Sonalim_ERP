import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Unlock } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { useColumnFilters } from "../../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import { formatMoveReference, useReferenceKindLabels } from "../../../lib/stockMoveTypes";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Badge, type BadgeProps } from "../../../components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../../components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../../components/ui/dialog";
import { FilterTabs } from "../../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../../components/patterns/ColumnVisibilityMenu";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { useProductCatalog } from "../../products/catalog";
import { listLocations } from "../api";
import {
  listReservations,
  releaseReservation,
  updateReservationExpiry,
  RESERVATIONS_QUERY_KEY,
  type ReservationStatus,
  type StockReservation,
} from "./api";

const STATUS_VARIANT: Record<ReservationStatus, BadgeProps["variant"]> = {
  active: "warning",
  released: "outline",
  expired: "default",
};

const STATUS_FILTERS = ["active", "released", "expired", "all"] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

/** `datetime-local` wants local wall-clock time without a zone. */
function toLocalInput(iso: string | null) {
  if (!iso) return "";
  const date = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function ExpiryDialog({ reservation, onClose }: { reservation: StockReservation | null; onClose: () => void }) {
  const { t } = useI18n();
  const { session } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [value, setValue] = useState("");

  useEffect(() => setValue(toLocalInput(reservation?.expires_at ?? null)), [reservation]);

  const mutation = useMutation({
    mutationFn: (expiresAt: string | null) => updateReservationExpiry(token, reservation!.id, expiresAt),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: RESERVATIONS_QUERY_KEY });
      onClose();
    },
  });

  return (
    <Dialog open={reservation !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t("warehouse.reservations.dialog.title")}</DialogTitle>
          <DialogDescription>{t("warehouse.reservations.dialog.description")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1">
            <Label>{t("warehouse.reservations.column.expires")}</Label>
            <Input type="datetime-local" value={value} onChange={(e) => setValue(e.target.value)} />
          </div>
          {mutation.isError && (
            <p className="text-sm text-destructive">
              {mutation.error instanceof ApiError ? mutation.error.message : t("warehouse.reservations.dialog.error")}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => mutation.mutate(null)} disabled={mutation.isPending}>
              {t("warehouse.reservations.action.clearExpiry")}
            </Button>
            {/* toISOString turns the wall-clock input into the zoned instant the API requires. */}
            <Button onClick={() => mutation.mutate(new Date(value).toISOString())} disabled={value === "" || mutation.isPending}>
              {t("common.save")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function ReservationsTab() {
  const { t } = useI18n();
  const { session, hasPermission } = useAuth();
  const token = session!.token;
  const queryClient = useQueryClient();
  const { products } = useProductCatalog();
  const referenceKindLabels = useReferenceKindLabels();

  const { data: reservations = [] } = useQuery({
    queryKey: RESERVATIONS_QUERY_KEY,
    queryFn: () => listReservations(token),
    // The worker expires holds every minute; keep the list roughly in step.
    refetchInterval: 60_000,
  });
  const { data: locations = [] } = useQuery({ queryKey: ["warehouse", "locations"], queryFn: () => listLocations(token) });

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("active");
  const [editing, setEditing] = useState<StockReservation | null>(null);

  const canRelease = hasPermission("warehouse.manage_stock");
  const canEdit = hasPermission("warehouse.admin_reservations");
  const productName = (id: string) => products.find((p) => p.id === id)?.name ?? id;
  const locationName = (id: string) => locations.find((l) => l.id === id)?.name ?? id;
  const referenceText = (reference: string) => {
    const { label, suffix } = formatMoveReference(reference, referenceKindLabels);
    return suffix ? `${label} …${suffix}` : label;
  };

  const releaseMutation = useMutation({
    mutationFn: (id: string) => releaseReservation(token, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: RESERVATIONS_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock"] });
    },
  });

  const columnFilters = useColumnFilters<StockReservation>([
    { key: "product", kind: "text", getValue: (row) => productName(row.product_id) },
    { key: "location", kind: "text", getValue: (row) => locationName(row.location_id) },
    { key: "reference", kind: "text", getValue: (row) => referenceText(row.reference) },
    { key: "open", kind: "range", getValue: (row) => row.quantity_open },
  ]);
  const textFilter = (key: string, placeholder: string) => ({
    type: "text" as const,
    placeholder,
    value: columnFilters.text[key] ?? "",
    onChange: (v: string) => columnFilters.setTextValue(key, v),
  });

  const columns: ColumnDef<StockReservation>[] = [
    {
      key: "product",
      header: t("warehouse.reservations.column.product"),
      cell: (row) => productName(row.product_id),
      filterCell: textFilter("product", t("warehouse.reservations.column.product")),
    },
    {
      key: "location",
      header: t("warehouse.reservations.column.location"),
      cell: (row) => locationName(row.location_id),
      filterCell: textFilter("location", t("warehouse.reservations.column.location")),
    },
    {
      key: "reference",
      header: t("warehouse.reservations.column.reference"),
      cell: (row) => <span title={row.reference}>{referenceText(row.reference)}</span>,
      filterCell: textFilter("reference", t("warehouse.reservations.column.reference")),
    },
    {
      key: "open",
      header: t("warehouse.reservations.column.open"),
      cell: (row) => (
        <span>
          {row.quantity_open}
          <span className="text-muted-foreground"> / {row.quantity}</span>
        </span>
      ),
      filterCell: {
        type: "range",
        min: columnFilters.range.open?.min ?? "",
        max: columnFilters.range.open?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("open", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("open", "max", v),
      },
    },
    {
      key: "expires",
      header: t("warehouse.reservations.column.expires"),
      cell: (row) => (row.expires_at ? new Date(row.expires_at).toLocaleString() : t("warehouse.reservations.noExpiry")),
      filterCell: { type: "blank" },
    },
    {
      key: "status",
      header: t("warehouse.reservations.column.status"),
      cell: (row) => <Badge variant={STATUS_VARIANT[row.status]}>{t(`warehouse.reservations.status.${row.status}`)}</Badge>,
      filterCell: { type: "blank" },
    },
    {
      key: "actions",
      header: "",
      alwaysVisible: true,
      cell: (row) =>
        row.status === "active" ? (
          <div className="flex justify-end gap-1">
            {canEdit && (
              <Button variant="ghost" size="sm" aria-label={t("common.edit")} onClick={() => setEditing(row)}>
                <Pencil className="h-3.5 w-3.5" />
              </Button>
            )}
            {canRelease && (
              <Button variant="ghost" size="sm" onClick={() => releaseMutation.mutate(row.id)} disabled={releaseMutation.isPending}>
                <Unlock className="h-3.5 w-3.5" />
                {t("warehouse.reservations.action.release")}
              </Button>
            )}
          </div>
        ) : null,
      filterCell: { type: "blank" },
    },
  ];

  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "warehouse.reservations",
    columns,
  );
  const rows = columnFilters.apply(statusFilter === "all" ? reservations : reservations.filter((r) => r.status === statusFilter));

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t("warehouse.reservations.description")}</p>
      <div className="flex flex-wrap items-center gap-2">
        <FilterTabs
          value={statusFilter}
          onChange={setStatusFilter}
          options={STATUS_FILTERS.map((s) => ({ value: s, label: s === "all" ? t("common.all") : t(`warehouse.reservations.status.${s}`) }))}
        />
        {columnFilters.isActive && (
          <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
            {t("common.clearFilters")}
          </Button>
        )}
        <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
      </div>
      {releaseMutation.isError && (
        <p className="text-sm text-destructive">
          {releaseMutation.error instanceof ApiError ? releaseMutation.error.message : t("warehouse.reservations.dialog.error")}
        </p>
      )}

      {rows.length === 0 ? (
        <EmptyState
          icon={<Unlock className="h-5 w-5" />}
          title={t("warehouse.reservations.empty.title")}
          description={t("warehouse.reservations.empty.description")}
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

      <ExpiryDialog reservation={editing} onClose={() => setEditing(null)} />
    </div>
  );
}
