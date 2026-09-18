import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, Plus } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { productUnit, productRequiresIntegerQuantity } from "../../lib/units";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { Skeleton } from "../../components/ui/skeleton";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "../../components/ui/dialog";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { StockMoveDetailDialog } from "../../components/patterns/StockMoveDetailDialog";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { MOVE_TYPE_VARIANT, formatMoveReference, signedMoveQuantity, useMoveTypeLabels, useReferenceKindLabels } from "../../lib/stockMoveTypes";
import { rowEnterProps } from "../../components/motion/rowMotion";
import MovementInIcon from "../../assets/icons/warehouse/movement-in.svg?react";
import MovementOutIcon from "../../assets/icons/warehouse/movement-out.svg?react";
import { adjustStock, listLocations, listProducts, listStockMoves, listUoms, type StockMove, type StockMoveType } from "./api";
import { listWorkOrders } from "../production/api";

const adjustSchema = z.object({
  product_id: z.string().min(1, "Required"),
  location_id: z.string().min(1, "Required"),
  delta: z.coerce.number().refine((v) => v !== 0, "Must not be zero"),
  reason: z.string().min(1, "Required"),
});
type AdjustForm = z.infer<typeof adjustSchema>;

const MOVES_QUERY_KEY = ["warehouse", "stock", "moves"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;
type MoveTypeFilter = "all" | StockMoveType;

function formatWhen(iso: string, language: string) {
  return new Date(iso).toLocaleString(language === "fr" ? "fr-FR" : "en-US", { dateStyle: "medium", timeStyle: "short" });
}

export function StockHistoryTab() {
  const { session } = useAuth();
  const { t, language } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [moveTypeFilter, setMoveTypeFilter] = useState<MoveTypeFilter>("all");
  const [selectedMove, setSelectedMove] = useState<StockMove | null>(null);

  const MOVE_TYPE_LABEL = useMoveTypeLabels();
  const REFERENCE_KIND_LABEL = useReferenceKindLabels();

  const { data: moves = [], isLoading } = useQuery({ queryKey: MOVES_QUERY_KEY, queryFn: () => listStockMoves(token) });
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: locations = [] } = useQuery({ queryKey: LOCATIONS_QUERY_KEY, queryFn: () => listLocations(token) });
  // Best-effort: a role without production.view_work_orders just doesn't get the
  // "work order" row in the move-detail dialog, rather than an error anywhere.
  const { data: workOrders = [] } = useQuery({
    queryKey: ["production", "work-orders"],
    queryFn: () => listWorkOrders(token),
  });
  const { data: uoms = [] } = useQuery({ queryKey: ["core", "uoms"], queryFn: () => listUoms(token) });
  const productName = (id: string) => products.find((p) => p.id === id)?.name ?? "—";
  const locationName = (id: string) => locations.find((l) => l.id === id)?.name ?? "—";
  const moveTypeFilteredMoves = moveTypeFilter === "all" ? moves : moves.filter((m) => m.move_type === moveTypeFilter);

  const columnFilterFields: FilterField<StockMove>[] = [
    { key: "product", kind: "text", getValue: (m) => productName(m.product_id) },
    { key: "location", kind: "text", getValue: (m) => locationName(m.location_id) },
    { key: "quantity", kind: "range", getValue: (m) => m.quantity },
    { key: "reference", kind: "text", getValue: (m) => m.reference },
    { key: "reason", kind: "text", getValue: (m) => m.reason },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredMoves = columnFilters.apply(moveTypeFilteredMoves);

  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors },
  } = useForm<AdjustForm>({ resolver: zodResolver(adjustSchema) });
  const adjustProductId = watch("product_id");

  const adjustMutation = useMutation({
    mutationFn: (input: AdjustForm) => adjustStock(token, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: MOVES_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock"] });
      setDialogOpen(false);
      reset();
      toast.success(t("warehouse.stockHistory.adjusted"));
    },
    onError: (error) => {
      toast.error(t("warehouse.stockHistory.adjustError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const columns: ColumnDef<StockMove>[] = [
    {
      key: "when",
      header: t("warehouse.stockHistory.column.when"),
      defaultWidth: 180,
      cell: (move) => <span className="whitespace-nowrap text-muted-foreground">{formatWhen(move.created_at, language)}</span>,
      sortValue: (move) => move.created_at,
    },
    {
      key: "product",
      header: t("warehouse.stockHistory.column.product"),
      defaultWidth: 200,
      cell: (move) => <span className="font-medium">{productName(move.product_id)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.product ?? "",
        onChange: (v) => columnFilters.setTextValue("product", v),
        placeholder: t("warehouse.stockHistory.column.product"),
      },
      sortValue: (move) => productName(move.product_id),
    },
    {
      key: "location",
      header: t("warehouse.stockHistory.column.location"),
      defaultWidth: 160,
      cell: (move) => <span className="text-muted-foreground">{locationName(move.location_id)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.location ?? "",
        onChange: (v) => columnFilters.setTextValue("location", v),
        placeholder: t("warehouse.stockHistory.column.location"),
      },
      sortValue: (move) => locationName(move.location_id),
    },
    {
      key: "type",
      header: t("warehouse.stockHistory.column.type"),
      defaultWidth: 220,
      cell: (move) => (
        <Badge variant={MOVE_TYPE_VARIANT[move.move_type]} dot className="max-w-full" title={MOVE_TYPE_LABEL[move.move_type]}>
          <span className="min-w-0 truncate">{MOVE_TYPE_LABEL[move.move_type]}</span>
        </Badge>
      ),
      sortValue: (move) => MOVE_TYPE_LABEL[move.move_type],
    },
    {
      key: "quantity",
      header: t("warehouse.stockHistory.column.quantity"),
      defaultWidth: 140,
      cell: (move) => {
        const signed = signedMoveQuantity(move);
        const Icon = signed < 0 ? MovementOutIcon : MovementInIcon;
        return (
          <span className={`inline-flex items-center gap-1 tabular-nums ${signed < 0 ? "text-destructive" : "text-success"}`}>
            <Icon className="h-3.5 w-3.5 shrink-0" />
            {signed > 0 ? "+" : ""}
            {signed}
          </span>
        );
      },
      filterCell: {
        type: "range",
        min: columnFilters.range.quantity?.min ?? "",
        max: columnFilters.range.quantity?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("quantity", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("quantity", "max", v),
      },
      sortValue: (move) => signedMoveQuantity(move),
    },
    {
      key: "reference",
      header: t("warehouse.stockHistory.column.reference"),
      defaultWidth: 220,
      cell: (move) => {
        const { label, suffix } = formatMoveReference(move.reference, REFERENCE_KIND_LABEL);
        return (
          <span className="flex min-w-0 items-baseline gap-1 text-muted-foreground" title={move.reference}>
            <span className="min-w-0 truncate">{label}</span>
            {suffix && <span className="shrink-0 font-mono text-xs text-muted-foreground/70">#{suffix}</span>}
          </span>
        );
      },
      filterCell: {
        type: "text",
        value: columnFilters.text.reference ?? "",
        onChange: (v) => columnFilters.setTextValue("reference", v),
        placeholder: t("warehouse.stockHistory.column.reference"),
      },
      sortValue: (move) => move.reference,
    },
    {
      key: "reason",
      header: t("warehouse.stockHistory.column.reason"),
      defaultWidth: 200,
      cell: (move) => <span className="text-muted-foreground">{move.reason ?? "—"}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.reason ?? "",
        onChange: (v) => columnFilters.setTextValue("reason", v),
        placeholder: t("warehouse.stockHistory.column.reason"),
      },
      sortValue: (move) => move.reason,
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("warehouse.stockHistory", columns);
  const sortedMoves = sortRows(filteredMoves);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <CardTitle>{t("warehouse.stockHistory.title")}</CardTitle>
            <CardDescription>{t("warehouse.stockHistory.subtitle")}</CardDescription>
          </div>
          <FilterTabs
            value={moveTypeFilter}
            onChange={setMoveTypeFilter}
            options={[
              { value: "all", label: t("common.all") },
              { value: "receipt", label: t("warehouse.stockHistory.type.receipt") },
              { value: "issue", label: t("warehouse.stockHistory.type.issue") },
              { value: "adjustment", label: t("warehouse.stockHistory.type.adjustment") },
              { value: "reservation", label: t("warehouse.stockHistory.type.reservation") },
              { value: "production", label: t("warehouse.stockHistory.type.production") },
            ]}
          />
          {columnFilters.isActive && (
            <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
              {t("common.clearFilters")}
            </Button>
          )}
          <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button variant="outline" size="sm" disabled={products.length === 0 || locations.length === 0}>
              <Plus className="h-3.5 w-3.5" />
              {t("warehouse.stockHistory.adjustStock")}
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{t("warehouse.stockHistory.dialog.title")}</DialogTitle>
              <DialogDescription>{t("warehouse.stockHistory.dialog.description")}</DialogDescription>
            </DialogHeader>
            <form className="space-y-4" onSubmit={handleSubmit((input) => adjustMutation.mutate(input))}>
              <div className="space-y-1.5">
                <Label htmlFor="adjust_product_id">{t("warehouse.stockHistory.field.product")}</Label>
                <Select id="adjust_product_id" {...register("product_id")}>
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
                <Label htmlFor="adjust_location_id">{t("warehouse.stockHistory.field.location")}</Label>
                <Select id="adjust_location_id" {...register("location_id")}>
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
                <Label htmlFor="adjust_delta">
                  {t("warehouse.stockHistory.field.delta")}
                  {productUnit(adjustProductId, products, uoms) && (
                    <span className="text-muted-foreground"> ({productUnit(adjustProductId, products, uoms)})</span>
                  )}
                </Label>
                <Input
                  id="adjust_delta"
                  type="number"
                  step={productRequiresIntegerQuantity(adjustProductId, products, uoms) ? "1" : "any"}
                  placeholder="e.g. -5 or 3.2"
                  {...register("delta")}
                />
                {errors.delta && <p className="text-sm text-destructive">{errors.delta.message}</p>}
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="adjust_reason">{t("warehouse.stockHistory.field.reason")}</Label>
                <Input id="adjust_reason" placeholder="e.g. Physical count correction" {...register("reason")} />
                {errors.reason && <p className="text-sm text-destructive">{errors.reason.message}</p>}
              </div>
              {adjustMutation.isError && (
                <p className="text-sm text-destructive">
                  {adjustMutation.error instanceof ApiError ? adjustMutation.error.message : t("warehouse.stockHistory.adjustError")}
                </p>
              )}
              <Button type="submit" className="w-full" disabled={adjustMutation.isPending}>
                {adjustMutation.isPending ? t("warehouse.stockHistory.adjusting") : t("warehouse.stockHistory.adjust")}
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
              Array.from({ length: 4 }).map((_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={visibleColumns.length}>
                    <Skeleton className="h-5 w-full" />
                  </TableCell>
                </TableRow>
              ))}
            {!isLoading && filteredMoves.length === 0 && (
              <TableRow>
                <TableCell colSpan={visibleColumns.length} className="p-0">
                  <EmptyState icon={<History className="h-5 w-5" />} title={t("warehouse.stockHistory.empty.title")} description={t("warehouse.stockHistory.empty.description")} />
                </TableCell>
              </TableRow>
            )}
            <AnimatePresence initial={false}>
              {sortedMoves.map((move, index) => (
                <motion.tr
                  key={move.id}
                  {...rowEnterProps(index)}
                  className="cursor-pointer border-b border-border transition-colors hover:bg-muted/50"
                  onClick={() => setSelectedMove(move)}
                >
                  {visibleColumns.map((column) => (
                    <TableCell key={column.key} className={column.cellClassName}>
                      {column.cell(move)}
                    </TableCell>
                  ))}
                </motion.tr>
              ))}
            </AnimatePresence>
          </TableBody>
        </Table>
      </CardContent>

      {selectedMove && (
        <StockMoveDetailDialog
          move={selectedMove}
          moveTypeLabel={MOVE_TYPE_LABEL[selectedMove.move_type]}
          productLabel={productName(selectedMove.product_id)}
          productSku={products.find((p) => p.id === selectedMove.product_id)?.sku}
          locationLabel={locationName(selectedMove.location_id)}
          locationCode={locations.find((l) => l.id === selectedMove.location_id)?.code}
          unit={productUnit(selectedMove.product_id, products, uoms)}
          workOrders={workOrders}
          onClose={() => setSelectedMove(null)}
        />
      )}
    </Card>
  );
}
