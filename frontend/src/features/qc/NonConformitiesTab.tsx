import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useFieldArray, useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { AlertOctagon, CheckCircle2, Plus, ShieldAlert, Split, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../../lib/auth";
import { listUoms } from "../warehouse/api";
import { formatQuantity, productUnit } from "../../lib/units";
import { NonConformityDetailDialog } from "./NonConformityDetailDialog";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Checkbox } from "../../components/ui/checkbox";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
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
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { BulkActionBar } from "../../components/patterns/BulkActionBar";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { useSelection } from "../../lib/useSelection";
import { listProducts, listWorkOrders } from "../production/api";
import { listLocations } from "../warehouse/api";
import {
  closeNonConformity,
  dispositionNonConformity,
  listNonConformities,
  raiseNonConformity,
  type NcComponent,
  type NcDisposition,
  type NonConformity,
  type NonConformityStatus,
} from "./api";

const raiseSchema = z.object({
  of_id: z.string().min(1, "Required"),
  product_id: z.string().min(1, "Required"),
  quantity: z.coerce.number().positive("Must be > 0"),
  source_location_id: z.string().min(1, "Required"),
  quarantine_location_id: z.string().min(1, "Required"),
  defect_type: z.string().min(1, "Required"),
  severity: z.enum(["minor", "major", "critical"]),
  description: z.string().optional(),
});
type RaiseForm = z.infer<typeof raiseSchema>;

const dispositionSchema = z.object({
  lines: z
    .array(
      z.object({
        component: z.enum(["product", "film", "carton", "tape"]),
        disposition: z.enum(["regrind", "dechet", "rework", "return_to_stock"]),
        quantity: z.coerce.number().positive("Must be > 0"),
        note: z.string().optional(),
      }),
    )
    .min(1, "At least one line"),
});
type DispositionForm = z.infer<typeof dispositionSchema>;

const QUERY_KEY = ["qc", "non-conformities"] as const;
const WORK_ORDERS_QUERY_KEY = ["production", "work-orders"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;

type StatusFilter = "all" | NonConformityStatus;

const COMPONENTS: NcComponent[] = ["product", "film", "carton", "tape"];
const DISPOSITIONS: NcDisposition[] = ["regrind", "dechet", "rework", "return_to_stock"];

export function NonConformitiesTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [actioningId, setActioningId] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  // A case can be linked to from anywhere it is mentioned -- an OF's quality
  // panel, a cockpit alert, a message to a colleague -- so which one is open
  // lives in the URL rather than only in this component.
  const [searchParams, setSearchParams] = useSearchParams();
  const linkedId = searchParams.get("nc");
  const focusedId = openId ?? linkedId;

  const { data: items = [], isLoading } = useQuery({ queryKey: QUERY_KEY, queryFn: () => listNonConformities(token) });
  const { data: workOrders = [] } = useQuery({
    queryKey: WORK_ORDERS_QUERY_KEY,
    queryFn: () => listWorkOrders(token),
  });
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: locations = [] } = useQuery({ queryKey: LOCATIONS_QUERY_KEY, queryFn: () => listLocations(token) });
  const { data: uoms = [] } = useQuery({ queryKey: ["core", "uoms"], queryFn: () => listUoms(token) });

  const referenceOf = (ofId: string) => workOrders.find((o) => o.id === ofId)?.reference ?? "—";
  // A link may name a case that has since been deleted, or one this filter
  // hides -- so the lookup is against everything loaded, and a miss simply
  // opens nothing rather than showing an empty dialog.
  const focused = items.find((n) => n.id === focusedId) ?? null;
  const productName = (id: string) => products.find((p) => p.id === id)?.name ?? "—";

  const form = useForm<RaiseForm>({
    resolver: zodResolver(raiseSchema),
    defaultValues: { severity: "minor" },
  });

  const raiseMutation = useMutation({
    mutationFn: (input: RaiseForm) =>
      raiseNonConformity(token, {
        of_id: input.of_id,
        product_id: input.product_id,
        quantity: input.quantity,
        source_location_id: input.source_location_id,
        quarantine_location_id: input.quarantine_location_id,
        defect_type: input.defect_type,
        severity: input.severity,
        description: input.description || undefined,
        correlation_id: crypto.randomUUID(),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      // Raising pulls product out of sellable stock, so inventory views change too.
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock"] });
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock", "moves"] });
      setDialogOpen(false);
      form.reset({ severity: "minor" });
      toast.success(t("qc.nc.raised"));
    },
    onError: (error) => {
      toast.error(t("qc.nc.raiseError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const filterFields: FilterField<NonConformity>[] = [
    { key: "reference", kind: "text", getValue: (n) => n.reference },
    { key: "of", kind: "text", getValue: (n) => referenceOf(n.of_id) },
    { key: "product", kind: "text", getValue: (n) => productName(n.product_id) },
    { key: "defect", kind: "text", getValue: (n) => n.defect_type },
    { key: "quantity", kind: "range", getValue: (n) => n.quantity },
  ];
  const columnFilters = useColumnFilters<NonConformity>(filterFields);
  const visible = columnFilters.apply(
    statusFilter === "all" ? items : items.filter((n) => n.status === statusFilter),
  );

  // Only a dispositioned case is ready to close -- one still quarantined has
  // no corrective action to record yet.
  const selection = useSelection(items.filter((n) => n.status === "dispositioned").map((n) => n.id));
  const selectedNonConformities = items.filter((n) => selection.isSelected(n.id));
  const [bulkCloseOpen, setBulkCloseOpen] = useState(false);
  const [bulkCorrectiveAction, setBulkCorrectiveAction] = useState("");

  const bulkCloseMutation = useMutation({
    mutationFn: async (correctiveAction: string) => {
      const settled = await Promise.allSettled(
        selectedNonConformities.map((n) => closeNonConformity(token, n.id, correctiveAction)),
      );
      return { succeeded: settled.filter((r) => r.status === "fulfilled").length, total: settled.length };
    },
    onSuccess: ({ succeeded, total }) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock"] });
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock", "moves"] });
      queryClient.invalidateQueries({ queryKey: ["production", "scrap-records"] });
      const failed = total - succeeded;
      if (succeeded > 0) toast.success(`${succeeded} ${t("qc.nc.bulkCloseSucceeded")}`);
      if (failed > 0) toast.error(`${failed} ${t("qc.nc.bulkCloseFailed")}`);
      setBulkCloseOpen(false);
      setBulkCorrectiveAction("");
      selection.clear();
    },
  });

  const columns: ColumnDef<NonConformity>[] = [
    {
      key: "select",
      header: (
        <Checkbox checked={selection.allSelected} onCheckedChange={() => selection.toggleAll()} aria-label={t("common.selectAll")} />
      ),
      defaultWidth: 40,
      alwaysVisible: true,
      filterCell: { type: "blank" },
      cell: (n) =>
        n.status === "dispositioned" && (
          <Checkbox
            checked={selection.isSelected(n.id)}
            onCheckedChange={() => selection.toggle(n.id)}
            aria-label={t("qc.nc.close")}
          />
        ),
    },
    {
      key: "reference",
      header: t("qc.nc.column.reference"),
      defaultWidth: 140,
      cell: (n) => <span className="font-medium">{n.reference}</span>,
      filterCell: {
        type: "text",
        placeholder: t("common.filter"),
        value: columnFilters.text.reference ?? "",
        onChange: (v) => columnFilters.setTextValue("reference", v),
      },
      sortValue: (n) => n.reference,
    },
    {
      key: "of",
      header: t("production.reports.column.of"),
      defaultWidth: 140,
      cell: (n) => <span className="text-muted-foreground">{referenceOf(n.of_id)}</span>,
      filterCell: {
        type: "text",
        placeholder: t("common.filter"),
        value: columnFilters.text.of ?? "",
        onChange: (v) => columnFilters.setTextValue("of", v),
      },
      sortValue: (n) => referenceOf(n.of_id),
    },
    {
      key: "product",
      header: t("qc.nc.column.product"),
      defaultWidth: 170,
      cell: (n) => <span className="text-muted-foreground">{productName(n.product_id)}</span>,
      filterCell: {
        type: "text",
        placeholder: t("common.filter"),
        value: columnFilters.text.product ?? "",
        onChange: (v) => columnFilters.setTextValue("product", v),
      },
      sortValue: (n) => productName(n.product_id),
    },
    {
      key: "quantity",
      header: t("qc.nc.column.quantity"),
      defaultWidth: 120,
      cell: (n) => (
        <span className="tabular-nums text-muted-foreground">
          {formatQuantity(n.quantity, productUnit(n.product_id, products, uoms))}
        </span>
      ),
      filterCell: {
        type: "range",
        min: columnFilters.range.quantity?.min ?? "",
        max: columnFilters.range.quantity?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("quantity", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("quantity", "max", v),
      },
      sortValue: (n) => n.quantity,
    },
    {
      key: "defect",
      header: t("qc.nc.column.defect"),
      defaultWidth: 180,
      cell: (n) => <span className="text-muted-foreground">{n.defect_type}</span>,
      filterCell: {
        type: "text",
        placeholder: t("common.filter"),
        value: columnFilters.text.defect ?? "",
        onChange: (v) => columnFilters.setTextValue("defect", v),
      },
      sortValue: (n) => n.defect_type,
    },
    {
      key: "severity",
      header: t("qc.nc.column.severity"),
      defaultWidth: 120,
      filterCell: { type: "blank" },
      cell: (n) => (
        <span
          className={
            n.severity === "critical"
              ? "text-sm font-medium text-destructive"
              : n.severity === "major"
                ? "text-sm font-medium text-warning"
                : "text-sm text-muted-foreground"
          }
        >
          {t(`qc.nc.severity.${n.severity}` as Parameters<typeof t>[0])}
        </span>
      ),
      sortValue: (n) => n.severity,
    },
    {
      key: "status",
      header: t("production.reports.column.status"),
      defaultWidth: 140,
      cell: (n) => <StatusBadge status={n.status} />,
      filterCell: { type: "blank" },
      sortValue: (n) => n.status,
    },
    {
      key: "action",
      header: t("production.reports.column.action"),
      defaultWidth: 200,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right",
      filterCell: { type: "blank" },
      cell: (n) => (
        <NcRowActions
          nonConformity={n}
          products={products}
          uoms={uoms}
          isOpen={actioningId === n.id}
          onOpenChange={(open) => setActioningId(open ? n.id : null)}
        />
      ),
    },
  ];
  const table = useTableColumns("qc.nonConformities", columns);
  const sortedVisible = table.sortRows(visible);

  // Only a blocked location can hold quarantined stock — the backend refuses
  // anything else, so the picker offers only those.
  const blockedLocations = locations.filter((l) => l.is_blocked);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard
          label={t("qc.nc.stat.quarantined")}
          value={items.filter((n) => n.status === "quarantined").length}
          icon={<ShieldAlert className="h-5 w-5" />}
          accent="destructive"
        />
        <StatCard
          label={t("qc.nc.stat.awaitingClosure")}
          value={items.filter((n) => n.status === "dispositioned").length}
          icon={<Split className="h-5 w-5" />}
          accent="primary"
        />
        <StatCard
          label={t("qc.nc.stat.closed")}
          value={items.filter((n) => n.status === "closed").length}
          icon={<CheckCircle2 className="h-5 w-5" />}
          accent="success"
        />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("qc.nc.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("qc.nc.subtitle")}</p>
            </div>
            <FilterTabs
              options={[
                { value: "all", label: t("common.all") },
                { value: "quarantined", label: t("status.quarantined") },
                { value: "dispositioned", label: t("status.dispositioned") },
                { value: "closed", label: t("status.closed") },
              ]}
              value={statusFilter}
              onChange={setStatusFilter}
            />
            {columnFilters.isActive && (
              <Button size="sm" variant="ghost" onClick={columnFilters.reset}>
                {t("common.clearFilters")}
              </Button>
            )}
            <div className="ml-auto flex items-center gap-2">
              <ColumnVisibilityMenu
                columns={columns}
                isVisible={table.isVisible}
                onToggle={table.toggleVisible}
                onReset={table.resetAll}
              />
              <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                <DialogTrigger asChild>
                  <Button size="sm">
                    <Plus className="h-4 w-4" />
                    {t("qc.nc.new")}
                  </Button>
                </DialogTrigger>
                <DialogContent className="max-w-xl">
                  <DialogHeader>
                    <DialogTitle>{t("qc.nc.dialog.raise.title")}</DialogTitle>
                    <DialogDescription>{t("qc.nc.dialog.raise.description")}</DialogDescription>
                  </DialogHeader>
                  <form className="space-y-4" onSubmit={form.handleSubmit((input) => raiseMutation.mutate(input))}>
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      <div className="space-y-1.5">
                        <Label htmlFor="nc_of_id">{t("production.reports.field.of")}</Label>
                        <Select id="nc_of_id" {...form.register("of_id")}>
                          <option value="">—</option>
                          {workOrders.map((o) => (
                            <option key={o.id} value={o.id}>
                              {o.reference}
                            </option>
                          ))}
                        </Select>
                        <p className="text-xs text-muted-foreground">{t("qc.nc.help.closedOf")}</p>
                        {form.formState.errors.of_id && (
                          <p className="text-sm text-destructive">{form.formState.errors.of_id.message}</p>
                        )}
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="nc_product_id">{t("qc.nc.field.product")}</Label>
                        <Select id="nc_product_id" {...form.register("product_id")}>
                          <option value="">—</option>
                          {products.map((p) => (
                            <option key={p.id} value={p.id}>
                              {p.name}
                            </option>
                          ))}
                        </Select>
                        {form.formState.errors.product_id && (
                          <p className="text-sm text-destructive">{form.formState.errors.product_id.message}</p>
                        )}
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="nc_quantity">
                          {t("qc.nc.field.quantity")}
                          {(() => {
                            const unit = productUnit(form.watch("product_id"), products, uoms);
                            return unit ? ` (${unit})` : "";
                          })()}
                        </Label>
                        <Input id="nc_quantity" type="number" step="any" {...form.register("quantity")} />
                        {form.formState.errors.quantity && (
                          <p className="text-sm text-destructive">{form.formState.errors.quantity.message}</p>
                        )}
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="nc_severity">{t("qc.nc.column.severity")}</Label>
                        <Select id="nc_severity" {...form.register("severity")}>
                          <option value="minor">{t("qc.nc.severity.minor")}</option>
                          <option value="major">{t("qc.nc.severity.major")}</option>
                          <option value="critical">{t("qc.nc.severity.critical")}</option>
                        </Select>
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="nc_source">{t("qc.nc.field.pulledFrom")}</Label>
                        <Select id="nc_source" {...form.register("source_location_id")}>
                          <option value="">—</option>
                          {locations.map((l) => (
                            <option key={l.id} value={l.id}>
                              {l.name}
                            </option>
                          ))}
                        </Select>
                        {form.formState.errors.source_location_id && (
                          <p className="text-sm text-destructive">
                            {form.formState.errors.source_location_id.message}
                          </p>
                        )}
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="nc_quarantine">{t("qc.nc.field.quarantine")}</Label>
                        <Select id="nc_quarantine" {...form.register("quarantine_location_id")}>
                          <option value="">—</option>
                          {blockedLocations.map((l) => (
                            <option key={l.id} value={l.id}>
                              {l.name}
                            </option>
                          ))}
                        </Select>
                        <p className="text-xs text-muted-foreground">
                          {blockedLocations.length === 0
                            ? t("qc.nc.help.noBlockedLocation")
                            : t("qc.nc.help.quarantine")}
                        </p>
                        {form.formState.errors.quarantine_location_id && (
                          <p className="text-sm text-destructive">
                            {form.formState.errors.quarantine_location_id.message}
                          </p>
                        )}
                      </div>
                      <div className="space-y-1.5 sm:col-span-2">
                        <Label htmlFor="nc_defect">{t("qc.nc.field.defectType")}</Label>
                        <Input id="nc_defect" {...form.register("defect_type")} />
                        {form.formState.errors.defect_type && (
                          <p className="text-sm text-destructive">{form.formState.errors.defect_type.message}</p>
                        )}
                      </div>
                      <div className="space-y-1.5 sm:col-span-2">
                        <Label htmlFor="nc_description">{t("qc.nc.field.description")}</Label>
                        <Input id="nc_description" {...form.register("description")} />
                      </div>
                    </div>
                    <Button type="submit" className="w-full" disabled={raiseMutation.isPending}>
                      {raiseMutation.isPending ? t("common.saving") : t("qc.nc.raise")}
                    </Button>
                  </form>
                </DialogContent>
              </Dialog>
            </div>
          </div>
          <BulkActionBar count={selection.count} onClear={selection.clear}>
            <Dialog
              open={bulkCloseOpen}
              onOpenChange={(open) => {
                setBulkCloseOpen(open);
                if (open) setBulkCorrectiveAction("");
              }}
            >
              <DialogTrigger asChild>
                <Button size="sm">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  {t("qc.nc.bulkClose")}
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>{t("qc.nc.dialog.bulkClose.title")}</DialogTitle>
                  <DialogDescription>{t("qc.nc.dialog.bulkClose.description")}</DialogDescription>
                </DialogHeader>
                <div className="max-h-56 space-y-1 overflow-y-auto rounded-md border border-border p-2">
                  {selectedNonConformities.map((n) => (
                    <div key={n.id} className="flex items-center justify-between gap-2 text-sm">
                      <span className="font-medium">{n.reference}</span>
                      <span className="text-muted-foreground">
                        {productName(n.product_id)} · {formatQuantity(n.quantity, productUnit(n.product_id, products, uoms))}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="bulk_corrective">{t("qc.nc.field.correctiveAction")}</Label>
                  <Input
                    id="bulk_corrective"
                    value={bulkCorrectiveAction}
                    onChange={(e) => setBulkCorrectiveAction(e.target.value)}
                  />
                </div>
                <Button
                  className="w-full"
                  onClick={() => bulkCloseMutation.mutate(bulkCorrectiveAction)}
                  disabled={bulkCloseMutation.isPending || !bulkCorrectiveAction.trim()}
                >
                  {bulkCloseMutation.isPending ? t("qc.nc.bulkClosing") : t("qc.nc.bulkClose")}
                </Button>
              </DialogContent>
            </Dialog>
          </BulkActionBar>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="space-y-2 p-6">
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
            </div>
          ) : visible.length === 0 ? (
            <EmptyState
              icon={<AlertOctagon className="h-5 w-5" />}
              title={t("qc.nc.empty.title")}
              description={t("qc.nc.empty.description")}
            />
          ) : (
            <Table colWidths={table.colWidths}>
              <TableHeader>
                <TableRow>
                  {table.visibleColumns.map((column) => (
                    <ResizableTableHead
                      key={column.key}
                      width={table.getWidth(column.key)}
                      onResize={(width) => table.setWidth(column.key, width)}
                      className={column.headerClassName}
                      sortDirection={table.sortDirectionFor(column.key)}
                      onSort={column.sortValue ? () => table.toggleSort(column.key) : undefined}
                    >
                      {column.header}
                    </ResizableTableHead>
                  ))}
                </TableRow>
                <ColumnFilterRow cells={table.visibleColumns.map((c) => c.filterCell ?? { type: "blank" })} />
              </TableHeader>
              <TableBody>
                <AnimatePresence initial={false}>
                  {sortedVisible.map((item) => (
                    <motion.tr
                      key={item.id}
                      layout
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="cursor-pointer border-b border-border transition-colors hover:bg-muted/40"
                      onClick={() => setOpenId(item.id)}
                    >
                      {table.visibleColumns.map((column) => (
                        <TableCell
                          key={column.key}
                          className={column.cellClassName}
                          // The action and select cells decide about the case;
                          // the rest of the row reads it. Clicking "disposition"
                          // or the checkbox must not also open the panel.
                          onClick={
                            column.key === "action" || column.key === "select"
                              ? (event) => event.stopPropagation()
                              : undefined
                          }
                        >
                          {column.cell(item)}
                        </TableCell>
                      ))}
                    </motion.tr>
                  ))}
                </AnimatePresence>
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {focused && (
        <NonConformityDetailDialog
          nonConformity={focused}
          ofReference={referenceOf(focused.of_id)}
          products={products}
          uoms={uoms}
          locations={locations}
          onClose={() => {
            setOpenId(null);
            // Clear the deep link too, or the case reopens on every render.
            if (linkedId) {
              const next = new URLSearchParams(searchParams);
              next.delete("nc");
              setSearchParams(next, { replace: true });
            }
          }}
        />
      )}
    </div>
  );
}

/**
 * Disposition and closure. The disposition dialog is where a rejected packet gets
 * broken into its components: the pasta back to rebroyat, the film and carton
 * recorded as déchet — never deducted a second time, because their stock already
 * left when the conditionnement report was validated.
 */
// Film, carton and tape are never product-tracked per disposition line -- they
// come off the same fixed packaging vocabulary every plant uses, so their unit
// is a fixed label rather than resolved from a product. Mirrors the backend's
// _COMPONENT_FIXED_UNIT in modules/qc/api/router.py.
const COMPONENT_FIXED_UNIT: Partial<Record<NcComponent, string>> = { film: "kg", carton: "pièce", tape: "pièce" };

function NcRowActions({
  nonConformity,
  products,
  uoms,
  isOpen,
  onOpenChange,
}: {
  nonConformity: NonConformity;
  products: { id: string; name: string; uom_id: string }[];
  uoms: { id: string; code: string; symbol?: string | null }[];
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [correctiveAction, setCorrectiveAction] = useState("");
  const productUnitLabel = productUnit(nonConformity.product_id, products, uoms);
  const unitForComponent = (component: NcComponent) =>
    component === "product" ? productUnitLabel : COMPONENT_FIXED_UNIT[component] ?? null;

  const form = useForm<DispositionForm>({
    resolver: zodResolver(dispositionSchema),
    defaultValues: {
      lines: [{ component: "product", disposition: "regrind", quantity: nonConformity.quantity, note: "" }],
    },
  });
  const { fields, append, remove } = useFieldArray({ control: form.control, name: "lines" });
  const watchedLines = form.watch("lines");

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    queryClient.invalidateQueries({ queryKey: ["warehouse", "stock"] });
    queryClient.invalidateQueries({ queryKey: ["warehouse", "stock", "moves"] });
    queryClient.invalidateQueries({ queryKey: ["production", "scrap-records"] });
  }

  const dispositionMutation = useMutation({
    mutationFn: (input: DispositionForm) =>
      dispositionNonConformity(
        token,
        nonConformity.id,
        input.lines.map((l) => ({
          component: l.component,
          disposition: l.disposition,
          quantity: l.quantity,
          note: l.note || undefined,
        })),
        crypto.randomUUID(),
      ),
    onSuccess: () => {
      invalidate();
      onOpenChange(false);
      toast.success(t("qc.nc.dispositioned"));
    },
    onError: (error) => {
      toast.error(t("qc.nc.dispositionError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const closeMutation = useMutation({
    mutationFn: () => closeNonConformity(token, nonConformity.id, correctiveAction),
    onSuccess: () => {
      invalidate();
      onOpenChange(false);
      toast.success(t("qc.nc.closed"));
    },
    onError: (error) => {
      toast.error(t("qc.nc.closeError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  if (nonConformity.status === "closed") {
    return <span className="text-xs text-muted-foreground">{nonConformity.corrective_action ?? "—"}</span>;
  }

  return (
    <div className="flex justify-end gap-2">
      <Dialog open={isOpen} onOpenChange={onOpenChange}>
        <DialogTrigger asChild>
          <Button size="sm" variant="outline">
            {nonConformity.status === "quarantined" ? (
              <>
                <Split className="h-3.5 w-3.5" />
                {t("qc.nc.disposition")}
              </>
            ) : (
              <>
                <CheckCircle2 className="h-3.5 w-3.5" />
                {t("qc.nc.close")}
              </>
            )}
          </Button>
        </DialogTrigger>
        <DialogContent className="max-w-2xl">
          {nonConformity.status === "quarantined" ? (
            <>
              <DialogHeader>
                <DialogTitle>{t("qc.nc.dialog.disposition.title")}</DialogTitle>
                <DialogDescription>{t("qc.nc.dialog.disposition.description")}</DialogDescription>
              </DialogHeader>
              <form
                className="space-y-4"
                onSubmit={form.handleSubmit((input) => dispositionMutation.mutate(input))}
              >
                <div className="space-y-2">
                  {fields.map((field, index) => (
                    <div key={field.id} className="flex flex-wrap items-end gap-2">
                      <div className="min-w-[7rem] flex-1 space-y-1">
                        <Label className="text-xs">{t("qc.nc.field.component")}</Label>
                        <Select {...form.register(`lines.${index}.component` as const)}>
                          {COMPONENTS.map((c) => (
                            <option key={c} value={c}>
                              {t(`qc.nc.component.${c}` as Parameters<typeof t>[0])}
                            </option>
                          ))}
                        </Select>
                      </div>
                      <div className="min-w-[7rem] flex-1 space-y-1">
                        <Label className="text-xs">{t("qc.nc.field.disposition")}</Label>
                        <Select {...form.register(`lines.${index}.disposition` as const)}>
                          {DISPOSITIONS.map((d) => (
                            <option key={d} value={d}>
                              {t(`qc.nc.disposition.${d}` as Parameters<typeof t>[0])}
                            </option>
                          ))}
                        </Select>
                      </div>
                      <div className="w-24 space-y-1">
                        <Label className="text-xs">
                          {t("qc.nc.field.quantity")}
                          {unitForComponent(watchedLines[index]?.component) && (
                            <span className="text-muted-foreground"> ({unitForComponent(watchedLines[index]?.component)})</span>
                          )}
                        </Label>
                        <Input type="number" step="any" {...form.register(`lines.${index}.quantity` as const)} />
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => remove(index)}
                        aria-label={t("common.delete")}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  ))}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => append({ component: "film", disposition: "dechet", quantity: 1, note: "" })}
                  >
                    <Plus className="h-3.5 w-3.5" />
                    {t("qc.nc.addLine")}
                  </Button>
                </div>
                <div className="flex items-start gap-1.5 rounded-lg bg-muted/50 p-3">
                  <HelpTooltip text={t("qc.nc.help.dechet")} />
                  <p className="text-xs text-muted-foreground">{t("qc.nc.help.dechetShort")}</p>
                </div>
                <Button type="submit" className="w-full" disabled={dispositionMutation.isPending}>
                  {dispositionMutation.isPending ? t("common.saving") : t("qc.nc.disposition")}
                </Button>
              </form>
            </>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle>{t("qc.nc.dialog.close.title")}</DialogTitle>
                <DialogDescription>{t("qc.nc.dialog.close.description")}</DialogDescription>
              </DialogHeader>
              <div className="space-y-4">
                <div className="space-y-1.5">
                  <Label htmlFor="corrective">{t("qc.nc.field.correctiveAction")}</Label>
                  <Input
                    id="corrective"
                    value={correctiveAction}
                    onChange={(e) => setCorrectiveAction(e.target.value)}
                  />
                </div>
                <Button
                  className="w-full"
                  onClick={() => closeMutation.mutate()}
                  disabled={closeMutation.isPending || !correctiveAction.trim()}
                >
                  {closeMutation.isPending ? t("common.saving") : t("qc.nc.close")}
                </Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
