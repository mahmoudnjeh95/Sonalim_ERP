import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowLeftRight,
  Boxes,
  MoreHorizontal,
  PackageCheck,
  PackageMinus,
  PackageSearch,
  Pencil,
  Plus,
  Trash2,
  Warehouse,
  Wrench,
} from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { productRequiresIntegerQuantity } from "../../lib/units";
import { ApiError } from "../../lib/api";
import { cn } from "../../lib/utils";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Checkbox } from "../../components/ui/checkbox";
import { Badge } from "../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { Skeleton } from "../../components/ui/skeleton";
import { Popover, PopoverTrigger, PopoverContent, PopoverClose } from "../../components/ui/popover";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "../../components/ui/dialog";
import { StatCard } from "../../components/patterns/StatCard";
import { UnitBreakdownStat, type UnitBreakdownEntry } from "../../components/patterns/UnitBreakdownStat";
import { EmptyState } from "../../components/patterns/EmptyState";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { StockMoveHistoryTable } from "../../components/patterns/StockMoveHistoryTable";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import {
  adjustStock,
  adminSetStock,
  createLocation,
  deleteStockItem,
  listLocations,
  listProducts,
  listStock,
  listStockMoves,
  listUoms,
  reserveStock,
  transferStock,
  updateLocation,
  type Location,
  type StockItem,
} from "./api";

const reserveSchema = z.object({
  product_id: z.string().min(1, "Required"),
  location_id: z.string().min(1, "Required"),
  quantity: z.coerce.number().positive("Must be > 0"),
  reference: z.string().min(1, "Required"),
});
type ReserveForm = z.infer<typeof reserveSchema>;

const newLocationSchema = z.object({
  code: z.string().min(1, "Required"),
  name: z.string().min(1, "Required"),
});
type NewLocationForm = z.infer<typeof newLocationSchema>;

const rowAdjustSchema = z.object({
  delta: z.coerce.number().refine((v) => v !== 0, "Must not be zero"),
  reason: z.string().min(1, "Required"),
});
type RowAdjustForm = z.infer<typeof rowAdjustSchema>;

const adminSetSchema = z.object({
  quantity_on_hand: z.coerce.number().min(0),
  quantity_reserved: z.coerce.number().min(0),
  quantity_in_production: z.coerce.number().min(0),
});
type AdminSetForm = z.infer<typeof adminSetSchema>;

const transferSchema = z.object({
  to_location_id: z.string().min(1, "Required"),
  quantity: z.coerce.number().positive("Must be > 0"),
  reference: z.string().min(1, "Required"),
});
type TransferForm = z.infer<typeof transferSchema>;

type RowAction = { item: StockItem; action: "adjust" | "edit" | "move" | "delete" };

const STOCK_QUERY_KEY = ["warehouse", "stock"] as const;
const STOCK_MOVES_QUERY_KEY = ["warehouse", "stock", "moves"] as const;
const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const UOMS_QUERY_KEY = ["core", "uoms"] as const;

function breakdownByUnit(items: StockItem[], unitOf: (item: StockItem) => string, pick: (item: StockItem) => number): UnitBreakdownEntry[] {
  const totals = new Map<string, number>();
  for (const item of items) {
    const unit = unitOf(item);
    totals.set(unit, (totals.get(unit) ?? 0) + pick(item));
  }
  return Array.from(totals.entries())
    .map(([unit, value]) => ({ unit, value }))
    .sort((a, b) => b.value - a.value);
}

export function StockTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [locationDialogOpen, setLocationDialogOpen] = useState(false);
  const [editingLocation, setEditingLocation] = useState<Location | null>(null);
  const [activeLocationId, setActiveLocationId] = useState<string | "all">("all");
  const [historyProductId, setHistoryProductId] = useState<string | null>(null);
  const [rowAction, setRowAction] = useState<RowAction | null>(null);

  const { data: items = [], isLoading } = useQuery({ queryKey: STOCK_QUERY_KEY, queryFn: () => listStock(token) });
  const { data: locations = [] } = useQuery({ queryKey: LOCATIONS_QUERY_KEY, queryFn: () => listLocations(token) });
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: uoms = [] } = useQuery({ queryKey: UOMS_QUERY_KEY, queryFn: () => listUoms(token) });
  const productName = (productId: string) => products.find((p) => p.id === productId)?.name ?? "—";
  // The printed form, not the code: "pièce" is what a reader expects beside a
  // count, and `code` stays the key imports and integrations match on.
  const uomCode = (uomId: string) => {
    const uom = uoms.find((u) => u.id === uomId);
    return uom ? uom.symbol || uom.code : uomId;
  };
  const productUomCode = (productId: string) => {
    const product = products.find((p) => p.id === productId);
    return product ? uomCode(product.uom_id) : "?";
  };
  // The unit, plus a "whole number" cue for a carton/pièce-counted product --
  // the input's `step="1"` enforces it, this makes the reason visible.
  const quantityLabelSuffix = (productId: string | undefined) => {
    if (!productId) return null;
    const unit = productUomCode(productId);
    return productRequiresIntegerQuantity(productId, products, uoms) ? `${unit} · ${t("common.wholeNumberOnly")}` : unit;
  };

  const { data: historyMoves = [], isLoading: historyLoading } = useQuery({
    queryKey: [...STOCK_MOVES_QUERY_KEY, "product", historyProductId],
    queryFn: () => listStockMoves(token, { product_id: historyProductId! }),
    enabled: historyProductId !== null,
  });

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors },
  } = useForm<ReserveForm>({ resolver: zodResolver(reserveSchema) });
  const reserveProductId = watch("product_id");

  const reserveMutation = useMutation({
    mutationFn: (input: ReserveForm) => reserveStock(token, input),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: STOCK_QUERY_KEY });
      setDialogOpen(false);
      reset();
      toast.success(t("warehouse.stock.reservedToast"), { description: result.product_id });
    },
    onError: (error) => {
      toast.error(t("warehouse.stock.reserveError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const locationForm = useForm<NewLocationForm>({ resolver: zodResolver(newLocationSchema) });

  const createLocationMutation = useMutation({
    mutationFn: (input: NewLocationForm) => createLocation(token, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: LOCATIONS_QUERY_KEY });
      setLocationDialogOpen(false);
      locationForm.reset();
      toast.success(t("warehouse.stock.locationCreated"));
    },
    onError: (error) => {
      toast.error(t("warehouse.stock.createLocationError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const updateLocationMutation = useMutation({
    mutationFn: (input: NewLocationForm) => updateLocation(token, editingLocation!.id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: LOCATIONS_QUERY_KEY });
      setLocationDialogOpen(false);
      setEditingLocation(null);
      locationForm.reset();
      toast.success(t("warehouse.stock.locationUpdated"));
    },
    onError: (error) => {
      toast.error(t("warehouse.stock.updateLocationError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  function openCreateLocationDialog() {
    setEditingLocation(null);
    locationForm.reset({ code: "", name: "" });
    setLocationDialogOpen(true);
  }

  function openEditLocationDialog(location: Location) {
    setEditingLocation(location);
    locationForm.reset({ code: location.code, name: location.name });
    setLocationDialogOpen(true);
  }

  function locationName(id: string) {
    return locations.find((l) => l.id === id)?.name ?? "—";
  }

  function invalidateStock() {
    queryClient.invalidateQueries({ queryKey: STOCK_QUERY_KEY });
    queryClient.invalidateQueries({ queryKey: STOCK_MOVES_QUERY_KEY });
  }

  const rowAdjustForm = useForm<RowAdjustForm>({ resolver: zodResolver(rowAdjustSchema) });
  const rowAdjustMutation = useMutation({
    mutationFn: (input: RowAdjustForm) =>
      adjustStock(token, {
        product_id: rowAction!.item.product_id,
        location_id: rowAction!.item.location_id,
        delta: input.delta,
        reason: input.reason,
      }),
    onSuccess: () => {
      invalidateStock();
      setRowAction(null);
      toast.success(t("warehouse.stockHistory.adjusted"));
    },
    onError: (error) => {
      toast.error(t("warehouse.stockHistory.adjustError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const adminSetForm = useForm<AdminSetForm>({ resolver: zodResolver(adminSetSchema) });
  const adminSetMutation = useMutation({
    mutationFn: (input: AdminSetForm) => adminSetStock(token, rowAction!.item.location_id, rowAction!.item.product_id, input),
    onSuccess: () => {
      invalidateStock();
      setRowAction(null);
      toast.success(t("warehouse.stock.adminUpdated"));
    },
    onError: (error) => {
      toast.error(t("warehouse.stock.adminUpdateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const transferForm = useForm<TransferForm>({ resolver: zodResolver(transferSchema) });
  const transferAll = transferForm.watch("quantity") === rowAction?.item.quantity_available;
  const transferMutation = useMutation({
    mutationFn: (input: TransferForm) =>
      transferStock(token, {
        product_id: rowAction!.item.product_id,
        from_location_id: rowAction!.item.location_id,
        to_location_id: input.to_location_id,
        quantity: input.quantity,
        reference: input.reference,
      }),
    onSuccess: () => {
      invalidateStock();
      setRowAction(null);
      toast.success(t("warehouse.stock.transferred"));
    },
    onError: (error) => {
      toast.error(t("warehouse.stock.transferError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteStockItem(token, rowAction!.item.location_id, rowAction!.item.product_id),
    onSuccess: () => {
      invalidateStock();
      setRowAction(null);
      toast.success(t("warehouse.stock.deleted"));
    },
    onError: (error) => {
      toast.error(t("warehouse.stock.deleteError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const locationFilteredItems = activeLocationId === "all" ? items : items.filter((i) => i.location_id === activeLocationId);

  const columnFilterFields: FilterField<StockItem>[] = [
    { key: "product", kind: "text", getValue: (i) => productName(i.product_id) },
    { key: "location", kind: "text", getValue: (i) => locationName(i.location_id) },
    { key: "quantity_on_hand", kind: "range", getValue: (i) => i.quantity_on_hand },
    { key: "quantity_reserved", kind: "range", getValue: (i) => i.quantity_reserved },
    { key: "quantity_available", kind: "range", getValue: (i) => i.quantity_available },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const visibleItems = columnFilters.apply(locationFilteredItems);
  const onHandBreakdown = breakdownByUnit(visibleItems, (item) => productUomCode(item.product_id), (item) => item.quantity_on_hand);
  const reservedBreakdown = breakdownByUnit(visibleItems, (item) => productUomCode(item.product_id), (item) => item.quantity_reserved);

  const canAdjust = hasPermission("warehouse.adjust_stock");
  const canMove = hasPermission("warehouse.manage_stock");
  const canAdmin = hasPermission("warehouse.admin_stock");
  const canModify = canAdjust || canMove || canAdmin;

  const columns: ColumnDef<StockItem>[] = [
    {
      key: "product",
      header: t("warehouse.stock.column.product"),
      defaultWidth: 200,
      cell: (item) => (
        <button type="button" className="text-left font-medium hover:underline" onClick={() => setHistoryProductId(item.product_id)}>
          {productName(item.product_id)}
        </button>
      ),
      filterCell: {
        type: "text",
        value: columnFilters.text.product ?? "",
        onChange: (v) => columnFilters.setTextValue("product", v),
        placeholder: t("warehouse.stock.column.product"),
      },
      sortValue: (item) => productName(item.product_id),
    },
    {
      key: "unit",
      header: t("warehouse.stock.column.unit"),
      defaultWidth: 100,
      cell: (item) => <span className="text-muted-foreground">{productUomCode(item.product_id)}</span>,
      sortValue: (item) => productUomCode(item.product_id),
    },
    {
      key: "location",
      header: t("warehouse.stock.column.location"),
      defaultWidth: 160,
      cell: (item) => <span className="text-muted-foreground">{locationName(item.location_id)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.location ?? "",
        onChange: (v) => columnFilters.setTextValue("location", v),
        placeholder: t("warehouse.stock.column.location"),
      },
      sortValue: (item) => locationName(item.location_id),
    },
    {
      key: "quantity_on_hand",
      header: t("warehouse.stock.column.onHand"),
      defaultWidth: 140,
      cell: (item) => <span className="tabular-nums text-muted-foreground">{item.quantity_on_hand}</span>,
      filterCell: {
        type: "range",
        min: columnFilters.range.quantity_on_hand?.min ?? "",
        max: columnFilters.range.quantity_on_hand?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("quantity_on_hand", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("quantity_on_hand", "max", v),
      },
      sortValue: (item) => item.quantity_on_hand,
    },
    {
      key: "quantity_reserved",
      header: (
        <span className="inline-flex items-center gap-1">
          {t("warehouse.stock.column.reserved")}
          <HelpTooltip text={t("warehouse.stock.help.reserved")} />
        </span>
      ),
      defaultWidth: 140,
      cell: (item) => <span className="tabular-nums text-muted-foreground">{item.quantity_reserved}</span>,
      filterCell: {
        type: "range",
        min: columnFilters.range.quantity_reserved?.min ?? "",
        max: columnFilters.range.quantity_reserved?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("quantity_reserved", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("quantity_reserved", "max", v),
      },
      sortValue: (item) => item.quantity_reserved,
    },
    {
      key: "quantity_in_production",
      header: (
        <span className="inline-flex items-center gap-1">
          {t("warehouse.stock.column.inProduction")}
          <HelpTooltip text={t("warehouse.stock.help.inProduction")} />
        </span>
      ),
      defaultWidth: 140,
      cell: (item) => <span className="tabular-nums text-muted-foreground">{item.quantity_in_production}</span>,
      sortValue: (item) => item.quantity_in_production,
    },
    {
      key: "quantity_available",
      header: t("warehouse.stock.column.available"),
      defaultWidth: 140,
      cell: (item) => (
        <Badge variant={item.quantity_available > 0 ? "success" : "destructive"} dot>
          {item.quantity_available}
        </Badge>
      ),
      filterCell: {
        type: "range",
        min: columnFilters.range.quantity_available?.min ?? "",
        max: columnFilters.range.quantity_available?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("quantity_available", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("quantity_available", "max", v),
      },
      sortValue: (item) => item.quantity_available,
    },
    {
      key: "modifier",
      header: t("warehouse.stock.column.modifier"),
      defaultWidth: 140,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right",
      cell: (item) =>
        canModify && (
          <Popover>
            <PopoverTrigger asChild>
              <Button size="sm" variant="outline">
                <MoreHorizontal className="h-3.5 w-3.5" />
                {t("warehouse.stock.modifier")}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-56" align="end">
              <div className="space-y-1">
                {canAdjust && (
                  <PopoverClose asChild>
                    <button
                      type="button"
                      className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted"
                      onClick={() => {
                        rowAdjustForm.reset({ delta: 0, reason: "" });
                        setRowAction({ item, action: "adjust" });
                      }}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                      {t("warehouse.stock.action.adjust")}
                    </button>
                  </PopoverClose>
                )}
                {canAdmin && (
                  <PopoverClose asChild>
                    <button
                      type="button"
                      className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted"
                      onClick={() => {
                        adminSetForm.reset({
                          quantity_on_hand: item.quantity_on_hand,
                          quantity_reserved: item.quantity_reserved,
                          quantity_in_production: item.quantity_in_production,
                        });
                        setRowAction({ item, action: "edit" });
                      }}
                    >
                      <Wrench className="h-3.5 w-3.5" />
                      {t("warehouse.stock.action.editDirectly")}
                    </button>
                  </PopoverClose>
                )}
                {canMove && (
                  <PopoverClose asChild>
                    <button
                      type="button"
                      className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted"
                      onClick={() => {
                        transferForm.reset({ to_location_id: "", quantity: 0, reference: "" });
                        setRowAction({ item, action: "move" });
                      }}
                    >
                      <ArrowLeftRight className="h-3.5 w-3.5" />
                      {t("warehouse.stock.action.move")}
                    </button>
                  </PopoverClose>
                )}
                {canAdmin && (
                  <PopoverClose asChild>
                    <button
                      type="button"
                      className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-destructive hover:bg-destructive-soft"
                      onClick={() => setRowAction({ item, action: "delete" })}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      {t("warehouse.stock.action.delete")}
                    </button>
                  </PopoverClose>
                )}
              </div>
            </PopoverContent>
          </Popover>
        ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("warehouse.stock", columns);
  const sortedItems = sortRows(visibleItems);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <div className="inline-flex flex-wrap gap-1 rounded-lg border border-border bg-muted/40 p-1">
          <button
            onClick={() => setActiveLocationId("all")}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              activeLocationId === "all" ? "bg-background text-foreground shadow-soft" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t("warehouse.stock.allLocations")}
          </button>
          {locations.map((location) => (
            <span
              key={location.id}
              className={cn(
                "group inline-flex items-center rounded-md transition-colors",
                activeLocationId === location.id ? "bg-background shadow-soft" : "hover:text-foreground",
              )}
            >
              <button
                onClick={() => setActiveLocationId(location.id)}
                className={cn(
                  "rounded-md py-1.5 pl-3 text-sm font-medium transition-colors",
                  activeLocationId === location.id ? "text-foreground" : "text-muted-foreground",
                  "pr-1",
                )}
              >
                {location.name}
              </button>
              <button
                onClick={() => openEditLocationDialog(location)}
                title={t("warehouse.stock.editLocation")}
                className="rounded-md p-1.5 text-muted-foreground opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100"
              >
                <Pencil className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
        {columnFilters.isActive && (
          <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
            {t("common.clearFilters")}
          </Button>
        )}
        <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
        <Dialog
          open={locationDialogOpen}
          onOpenChange={(open) => {
            setLocationDialogOpen(open);
            if (!open) setEditingLocation(null);
          }}
        >
          <DialogTrigger asChild>
            <Button variant="ghost" size="sm" onClick={openCreateLocationDialog}>
              <Warehouse className="h-3.5 w-3.5" />
              {t("warehouse.stock.newLocation")}
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>
                {editingLocation ? t("warehouse.stock.dialog.editLocation.title") : t("warehouse.stock.dialog.newLocation.title")}
              </DialogTitle>
              <DialogDescription>
                {editingLocation
                  ? t("warehouse.stock.dialog.editLocation.description")
                  : t("warehouse.stock.dialog.newLocation.description")}
              </DialogDescription>
            </DialogHeader>
            <form
              className="space-y-4"
              onSubmit={locationForm.handleSubmit((input) =>
                editingLocation ? updateLocationMutation.mutate(input) : createLocationMutation.mutate(input),
              )}
            >
              <div className="space-y-1.5">
                <Label htmlFor="loc-code">{t("warehouse.stock.field.code")}</Label>
                <Input id="loc-code" placeholder="e.g. spare-parts" {...locationForm.register("code")} />
                {locationForm.formState.errors.code && (
                  <p className="text-sm text-destructive">{locationForm.formState.errors.code.message}</p>
                )}
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="loc-name">{t("warehouse.stock.field.name")}</Label>
                <Input id="loc-name" placeholder="e.g. Pièces de rechange" {...locationForm.register("name")} />
                {locationForm.formState.errors.name && (
                  <p className="text-sm text-destructive">{locationForm.formState.errors.name.message}</p>
                )}
              </div>
              {(editingLocation ? updateLocationMutation.isError : createLocationMutation.isError) && (
                <p className="text-sm text-destructive">
                  {(editingLocation ? updateLocationMutation.error : createLocationMutation.error) instanceof ApiError
                    ? (editingLocation ? updateLocationMutation.error : createLocationMutation.error)?.message
                    : t(editingLocation ? "warehouse.stock.updateLocationError" : "warehouse.stock.createLocationError")}
                </p>
              )}
              <Button
                type="submit"
                className="w-full"
                disabled={editingLocation ? updateLocationMutation.isPending : createLocationMutation.isPending}
              >
                {editingLocation
                  ? updateLocationMutation.isPending
                    ? t("warehouse.stock.updatingLocation")
                    : t("warehouse.stock.updateLocation")
                  : createLocationMutation.isPending
                    ? t("warehouse.stock.creating")
                    : t("warehouse.stock.createLocation")}
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("warehouse.stock.stat.skus")} value={visibleItems.length} icon={<Boxes className="h-5 w-5" />} />
        <UnitBreakdownStat
          label={t("warehouse.stock.stat.onHand")}
          icon={<PackageCheck className="h-5 w-5" />}
          accent="success"
          breakdown={onHandBreakdown}
        />
        <UnitBreakdownStat
          label={t("warehouse.stock.stat.reserved")}
          icon={<PackageMinus className="h-5 w-5" />}
          accent="warning"
          breakdown={reservedBreakdown}
        />
      </div>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>{t("warehouse.stock.table.title")}</CardTitle>
            <p className="mt-0.5 text-sm text-muted-foreground">{t("warehouse.stock.table.subtitle")}</p>
          </div>
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button disabled={locations.length === 0} title={locations.length === 0 ? t("warehouse.stock.createLocationFirst") : undefined}>
                <Plus className="h-4 w-4" />
                {t("warehouse.stock.reserveStock")}
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{t("warehouse.stock.dialog.reserve.title")}</DialogTitle>
                <DialogDescription>{t("warehouse.stock.dialog.reserve.description")}</DialogDescription>
              </DialogHeader>
              <form className="space-y-4" onSubmit={handleSubmit((input) => reserveMutation.mutate(input))}>
                <div className="space-y-1.5">
                  <Label htmlFor="location_id">{t("warehouse.stock.field.location")}</Label>
                  <Select id="location_id" {...register("location_id")}>
                    <option value="">—</option>
                    {locations.map((location) => (
                      <option key={location.id} value={location.id}>
                        {location.name}
                      </option>
                    ))}
                  </Select>
                  {errors.location_id && <p className="text-sm text-destructive">{errors.location_id.message}</p>}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="product_id">{t("warehouse.stock.field.productId")}</Label>
                  <Select id="product_id" {...register("product_id")}>
                    <option value="">—</option>
                    {products.map((product) => (
                      <option key={product.id} value={product.id}>
                        {product.name}
                      </option>
                    ))}
                  </Select>
                  {errors.product_id && <p className="text-sm text-destructive">{errors.product_id.message}</p>}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="quantity">
                    {t("warehouse.stock.field.quantity")}
                    {reserveProductId && <span className="text-muted-foreground"> ({quantityLabelSuffix(reserveProductId)})</span>}
                  </Label>
                  <Input
                    id="quantity"
                    type="number"
                    step={productRequiresIntegerQuantity(reserveProductId, products, uoms) ? "1" : "any"}
                    {...register("quantity")}
                  />
                  {errors.quantity && <p className="text-sm text-destructive">{errors.quantity.message}</p>}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="reference">{t("warehouse.stock.field.reference")}</Label>
                  <Input id="reference" placeholder="e.g. sales_order:123" {...register("reference")} />
                  {errors.reference && <p className="text-sm text-destructive">{errors.reference.message}</p>}
                </div>
                {reserveMutation.isError && (
                  <p className="text-sm text-destructive">
                    {reserveMutation.error instanceof ApiError ? reserveMutation.error.message : t("warehouse.stock.reserveError")}
                  </p>
                )}
                <Button type="submit" className="w-full" disabled={reserveMutation.isPending}>
                  {reserveMutation.isPending ? t("warehouse.stock.reserving") : t("warehouse.stock.reserve")}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
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
              {!isLoading && visibleItems.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <EmptyState
                      icon={<PackageSearch className="h-5 w-5" />}
                      title={t("warehouse.stock.empty.title")}
                      description={t("warehouse.stock.empty.description")}
                    />
                  </TableCell>
                </TableRow>
              )}
              <AnimatePresence initial={false}>
                {sortedItems.map((item, i) => (
                  <motion.tr
                    key={`${item.location_id}:${item.product_id}`}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i * 0.04, 0.3) } }}
                    exit={{ opacity: 0 }}
                    className="border-b border-border last:border-0 hover:bg-muted/50"
                  >
                    {visibleColumns.map((column) => (
                      <TableCell key={column.key} className={column.cellClassName}>
                        {column.cell(item)}
                      </TableCell>
                    ))}
                  </motion.tr>
                ))}
              </AnimatePresence>
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={historyProductId !== null} onOpenChange={(open) => !open && setHistoryProductId(null)}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{historyProductId ? productName(historyProductId) : ""}</DialogTitle>
            <DialogDescription>{t("warehouse.stock.history.description")}</DialogDescription>
          </DialogHeader>
          <StockMoveHistoryTable
            tableKey="warehouse.stock.productHistory"
            moves={historyMoves}
            isLoading={historyLoading}
            locationName={locationName}
          />
        </DialogContent>
      </Dialog>

      <Dialog open={rowAction?.action === "adjust"} onOpenChange={(open) => !open && setRowAction(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("warehouse.stockHistory.dialog.title")}</DialogTitle>
            <DialogDescription>
              {rowAction ? `${productName(rowAction.item.product_id)} · ${locationName(rowAction.item.location_id)}` : ""}
            </DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={rowAdjustForm.handleSubmit((input) => rowAdjustMutation.mutate(input))}>
            <div className="space-y-1.5">
              <Label htmlFor="row_adjust_delta">
                {t("warehouse.stockHistory.field.delta")}
                {rowAction && <span className="text-muted-foreground"> ({quantityLabelSuffix(rowAction.item.product_id)})</span>}
              </Label>
              <Input
                id="row_adjust_delta"
                type="number"
                step={rowAction && productRequiresIntegerQuantity(rowAction.item.product_id, products, uoms) ? "1" : "any"}
                placeholder="e.g. -5 or 3.2"
                {...rowAdjustForm.register("delta")}
              />
              {rowAdjustForm.formState.errors.delta && (
                <p className="text-sm text-destructive">{rowAdjustForm.formState.errors.delta.message}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="row_adjust_reason">{t("warehouse.stockHistory.field.reason")}</Label>
              <Input id="row_adjust_reason" placeholder="e.g. Physical count correction" {...rowAdjustForm.register("reason")} />
              {rowAdjustForm.formState.errors.reason && (
                <p className="text-sm text-destructive">{rowAdjustForm.formState.errors.reason.message}</p>
              )}
            </div>
            {rowAdjustMutation.isError && (
              <p className="text-sm text-destructive">
                {rowAdjustMutation.error instanceof ApiError ? rowAdjustMutation.error.message : t("warehouse.stockHistory.adjustError")}
              </p>
            )}
            <Button type="submit" className="w-full" disabled={rowAdjustMutation.isPending}>
              {rowAdjustMutation.isPending ? t("warehouse.stockHistory.adjusting") : t("warehouse.stockHistory.adjust")}
            </Button>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={rowAction?.action === "edit"} onOpenChange={(open) => !open && setRowAction(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("warehouse.stock.action.editDirectly")}</DialogTitle>
            <DialogDescription>
              {rowAction ? `${productName(rowAction.item.product_id)} · ${locationName(rowAction.item.location_id)}` : ""}
            </DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={adminSetForm.handleSubmit((input) => adminSetMutation.mutate(input))}>
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="admin_on_hand">
                  {t("warehouse.stock.column.onHand")}
                  {rowAction && <span className="text-muted-foreground"> ({quantityLabelSuffix(rowAction.item.product_id)})</span>}
                </Label>
                <Input
                  id="admin_on_hand"
                  type="number"
                  step={rowAction && productRequiresIntegerQuantity(rowAction.item.product_id, products, uoms) ? "1" : "any"}
                  {...adminSetForm.register("quantity_on_hand")}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="admin_reserved" className="inline-flex items-center gap-1">
                  {t("warehouse.stock.column.reserved")}
                  <HelpTooltip text={t("warehouse.stock.help.reserved")} />
                </Label>
                <Input
                  id="admin_reserved"
                  type="number"
                  step={rowAction && productRequiresIntegerQuantity(rowAction.item.product_id, products, uoms) ? "1" : "any"}
                  {...adminSetForm.register("quantity_reserved")}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="admin_in_production" className="inline-flex items-center gap-1">
                  {t("warehouse.stock.column.inProduction")}
                  <HelpTooltip text={t("warehouse.stock.help.inProduction")} />
                </Label>
                <Input
                  id="admin_in_production"
                  type="number"
                  step={rowAction && productRequiresIntegerQuantity(rowAction.item.product_id, products, uoms) ? "1" : "any"}
                  {...adminSetForm.register("quantity_in_production")}
                />
              </div>
            </div>
            {adminSetMutation.isError && (
              <p className="text-sm text-destructive">
                {adminSetMutation.error instanceof ApiError ? adminSetMutation.error.message : t("warehouse.stock.adminUpdateError")}
              </p>
            )}
            <Button type="submit" className="w-full" disabled={adminSetMutation.isPending}>
              {adminSetMutation.isPending ? t("warehouse.stock.saving") : t("common.save")}
            </Button>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={rowAction?.action === "move"} onOpenChange={(open) => !open && setRowAction(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("warehouse.stock.action.move")}</DialogTitle>
            <DialogDescription>
              {rowAction ? `${productName(rowAction.item.product_id)} · ${locationName(rowAction.item.location_id)}` : ""}
            </DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={transferForm.handleSubmit((input) => transferMutation.mutate(input))}>
            <div className="space-y-1.5">
              <Label htmlFor="transfer_to">{t("warehouse.stock.field.destination")}</Label>
              <Select id="transfer_to" {...transferForm.register("to_location_id")}>
                <option value="">—</option>
                {locations
                  .filter((location) => location.id !== rowAction?.item.location_id)
                  .map((location) => (
                    <option key={location.id} value={location.id}>
                      {location.name}
                    </option>
                  ))}
              </Select>
              {transferForm.formState.errors.to_location_id && (
                <p className="text-sm text-destructive">{transferForm.formState.errors.to_location_id.message}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-3">
                <Label htmlFor="transfer_quantity">
                  {t("warehouse.stock.field.quantity")}
                  {rowAction && <span className="text-muted-foreground"> ({quantityLabelSuffix(rowAction.item.product_id)})</span>}
                </Label>
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Checkbox
                    checked={transferAll}
                    disabled={!rowAction || rowAction.item.quantity_available <= 0}
                    onCheckedChange={(checked) => {
                      transferForm.setValue("quantity", checked ? rowAction?.item.quantity_available ?? 0 : 0, {
                        shouldValidate: true,
                      });
                    }}
                  />
                  {t("warehouse.stock.field.moveAll")}
                  <span className="tabular-nums">({rowAction?.item.quantity_available ?? 0})</span>
                </label>
              </div>
              <Input
                id="transfer_quantity"
                type="number"
                step={rowAction && productRequiresIntegerQuantity(rowAction.item.product_id, products, uoms) ? "1" : "any"}
                {...transferForm.register("quantity")}
              />
              {transferForm.formState.errors.quantity && (
                <p className="text-sm text-destructive">{transferForm.formState.errors.quantity.message}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="transfer_reference">{t("warehouse.stock.field.reference")}</Label>
              <Input id="transfer_reference" placeholder="e.g. rebalancing" {...transferForm.register("reference")} />
              {transferForm.formState.errors.reference && (
                <p className="text-sm text-destructive">{transferForm.formState.errors.reference.message}</p>
              )}
            </div>
            {transferMutation.isError && (
              <p className="text-sm text-destructive">
                {transferMutation.error instanceof ApiError ? transferMutation.error.message : t("warehouse.stock.transferError")}
              </p>
            )}
            <Button type="submit" className="w-full" disabled={transferMutation.isPending}>
              {transferMutation.isPending ? t("warehouse.stock.transferring") : t("warehouse.stock.transferSubmit")}
            </Button>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={rowAction?.action === "delete"} onOpenChange={(open) => !open && setRowAction(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("warehouse.stock.action.delete")}</DialogTitle>
            <DialogDescription>
              {rowAction ? `${productName(rowAction.item.product_id)} · ${locationName(rowAction.item.location_id)}` : ""}
            </DialogDescription>
          </DialogHeader>
          {rowAction && (
            <div className="space-y-4">
              <div className="space-y-1 rounded-lg border border-border p-3 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">{t("warehouse.stock.column.onHand")}</span>
                  <span className="tabular-nums">{rowAction.item.quantity_on_hand}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">{t("warehouse.stock.column.reserved")}</span>
                  <span className="tabular-nums">{rowAction.item.quantity_reserved}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">{t("warehouse.stock.column.inProduction")}</span>
                  <span className="tabular-nums">{rowAction.item.quantity_in_production}</span>
                </div>
              </div>
              <p className="text-sm text-destructive">{t("warehouse.stock.deleteWarning")}</p>
              {deleteMutation.isError && (
                <p className="text-sm text-destructive">
                  {deleteMutation.error instanceof ApiError ? deleteMutation.error.message : t("warehouse.stock.deleteError")}
                </p>
              )}
              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={() => setRowAction(null)}>
                  {t("common.cancel")}
                </Button>
                <Button variant="destructive" onClick={() => deleteMutation.mutate()} disabled={deleteMutation.isPending}>
                  {deleteMutation.isPending ? t("warehouse.stock.deleting") : t("warehouse.stock.action.delete")}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
