import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Boxes, CheckCircle2, Package, Pencil, Plus, Send } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
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
import { ShiftTeamFields } from "../../components/patterns/ShiftTeamFields";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import {
  WasteLinesField,
  fromWasteLineForms,
  toWasteLineForms,
  type WasteLineForm,
} from "./WasteLinesField";
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { ReportDetailDialog, type FigureRow } from "./ReportDetailDialog";
import {
  correctConditionnementReport,
  correctValidatedConditionnementReport,
  createConditionnementReport,
  deleteReport,
  getReport,
  getReportPackagingVariance,
  listProducts,
  listReports,
  listWorkOrders,
  submitReport,
  updateConditionnementReport,
  type ConditionnementReportDetail,
  type ProductionReport,
  type ReportStatus,
} from "./api";
import { listLocations, listUoms } from "../warehouse/api";
import { productUnit, formatQuantity } from "../../lib/units";
import { PackagingVariancePanel } from "./PackagingVariancePanel";

// The packing report. This is the one that puts finished product into stock and
// takes packaging out — the only place packaging is ever deducted.
const detailSchema = z.object({
  // Decision 24/25: cartons decide the finished-goods quantity for a product
  // with a carton tier; the machine's own tally sits beside it. Tonnage is no
  // longer typed here at all -- it comes from the daily report (decision 25).
  packets_counted: z.coerce.number().min(0),
  finished_goods_location_id: z.string().optional(),
  film_quantity: z.coerce.number().min(0),
  film_product_id: z.string().optional(),
  carton_quantity: z.coerce.number().min(0),
  carton_product_id: z.string().optional(),
  tape_quantity: z.coerce.number().min(0),
  tape_product_id: z.string().optional(),
  packaging_location_id: z.string().optional(),
  // Déchets. A list, so scotch -- which had no column at all -- can finally
  // be recorded, and every figure names the item that gives it a unit.
  waste_lines: z.array(
    z.object({
      category: z.enum(["product", "packaging"]),
      product_id: z.string(),
      quantity: z.coerce.number().min(0),
      note: z.string(),
    }),
  ),
  machine_speed: z.coerce.number().min(0).optional(),
  production_minutes: z.coerce.number().int().min(0),
  downtime_minutes: z.coerce.number().int().min(0),
  downtime_reason: z.string().optional(),
  lot_number: z.string().optional(),
  dlc_date: z.string().optional(),
});

const createSchema = detailSchema.extend({
  of_id: z.string().min(1, "Required"),
  report_date: z.string().min(1, "Required"),
  team: z.string().optional(),
  shift: z.string().optional(),
  // Only required when the chosen order has no product yet — this report is
  // then what names one.
  product_id: z.string().optional(),
});
type CreateForm = z.infer<typeof createSchema>;

const QUERY_KEY = ["production", "reports", "conditionnement"] as const;
const WORK_ORDERS_QUERY_KEY = ["production", "work-orders"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;
const UOMS_QUERY_KEY = ["core", "uoms"] as const;

type StatusFilter = "all" | ReportStatus;

const EMPTY_DETAIL = {
  packets_counted: 0,
  finished_goods_location_id: "",
  film_quantity: 0,
  film_product_id: "",
  carton_quantity: 0,
  carton_product_id: "",
  tape_quantity: 0,
  tape_product_id: "",
  packaging_location_id: "",
  waste_lines: [] as WasteLineForm<"product" | "packaging">[],
  machine_speed: undefined,
  production_minutes: 0,
  downtime_minutes: 0,
  downtime_reason: "",
  lot_number: "",
  dlc_date: "",
};

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function toDetail(input: CreateForm): Partial<ConditionnementReportDetail> {
  return {
    packets_counted: input.packets_counted,
    finished_goods_location_id: input.finished_goods_location_id || undefined,
    film_quantity: input.film_quantity,
    film_product_id: input.film_product_id || undefined,
    carton_quantity: input.carton_quantity,
    carton_product_id: input.carton_product_id || undefined,
    tape_quantity: input.tape_quantity,
    tape_product_id: input.tape_product_id || undefined,
    packaging_location_id: input.packaging_location_id || undefined,
    waste_lines: fromWasteLineForms(input.waste_lines),
    machine_speed: input.machine_speed,
    production_minutes: input.production_minutes,
    downtime_minutes: input.downtime_minutes,
    downtime_reason: input.downtime_reason || undefined,
    lot_number: input.lot_number || undefined,
    dlc_date: input.dlc_date || undefined,
  } as Partial<ConditionnementReportDetail>;
}

export function ConditionnementTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [openReport, setOpenReport] = useState<ProductionReport | null>(null);
  // Which report is open lives in the URL as well as in state, so the OF
  // details page can link straight to one instead of landing on the list.
  const [searchParams, setSearchParams] = useSearchParams();
  const linkedId = searchParams.get("report");

  const { data: reports = [], isLoading } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => listReports(token, { report_type: "conditionnement" }),
  });
  // A link may name a report that has since been deleted; a miss opens
  // nothing rather than an empty dialog.
  const focusedReport = openReport ?? reports.find((r) => r.id === linkedId) ?? null;
  const { data: workOrders = [] } = useQuery({
    queryKey: WORK_ORDERS_QUERY_KEY,
    queryFn: () => listWorkOrders(token),
  });
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: locations = [] } = useQuery({ queryKey: LOCATIONS_QUERY_KEY, queryFn: () => listLocations(token) });
  const { data: uoms = [] } = useQuery({ queryKey: UOMS_QUERY_KEY, queryFn: () => listUoms(token) });

  const openWorkOrders = workOrders.filter((o) => ["planned", "ongoing", "suspended"].includes(o.status));
  const referenceOf = (ofId: string) => workOrders.find((o) => o.id === ofId)?.reference ?? ofId;
  // The packed article is the order's product; the report never names it again,
  // except its very first filing, which is what names one if the OF has none yet.
  const productOfOrder = (ofId: string) => workOrders.find((o) => o.id === ofId)?.product_id ?? undefined;

  const form = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    defaultValues: { of_id: "", report_date: todayIso(), team: "", shift: "", product_id: "", ...EMPTY_DETAIL },
  });
  const selectedOfId = form.watch("of_id");
  const selectedOrderHasNoProduct = !!selectedOfId && !workOrders.find((o) => o.id === selectedOfId)?.product_id;

  const createMutation = useMutation({
    mutationFn: (input: CreateForm) =>
      createConditionnementReport(token, {
        of_id: input.of_id,
        report_date: input.report_date,
        team: input.team || undefined,
        shift: input.shift || undefined,
        product_id: input.product_id || undefined,
        detail: toDetail(input),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setDialogOpen(false);
      form.reset({ of_id: "", report_date: todayIso(), team: "", shift: "", product_id: "", ...EMPTY_DETAIL });
      toast.success(t("production.conditionnement.created"));
    },
    onError: (error) => {
      toast.error(t("production.conditionnement.createError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const submitMutation = useMutation({
    mutationFn: (reportId: string) => submitReport(token, reportId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      toast.success(t("production.reports.submitted"));
    },
    onError: (error) => {
      toast.error(t("production.reports.submitError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const filterFields: FilterField<ProductionReport>[] = [
    { key: "of", kind: "text", getValue: (r) => referenceOf(r.of_id) },
    { key: "date", kind: "text", getValue: (r) => r.report_date },
    { key: "team", kind: "text", getValue: (r) => r.team },
    { key: "shift", kind: "text", getValue: (r) => r.shift },
  ];
  const columnFilters = useColumnFilters<ProductionReport>(filterFields);
  const visible = columnFilters.apply(
    statusFilter === "all" ? reports : reports.filter((r) => r.status === statusFilter),
  );

  const columns: ColumnDef<ProductionReport>[] = [
    {
      key: "of",
      header: t("production.reports.column.of"),
      defaultWidth: 150,
      cell: (r) => <span className="font-medium">{referenceOf(r.of_id)}</span>,
      filterCell: {
        type: "text",
        placeholder: t("common.filter"),
        value: columnFilters.text.of ?? "",
        onChange: (v) => columnFilters.setTextValue("of", v),
      },
      sortValue: (r) => referenceOf(r.of_id),
    },
    {
      key: "date",
      header: t("production.reports.column.date"),
      defaultWidth: 130,
      cell: (r) => <span className="whitespace-nowrap text-muted-foreground">{r.report_date}</span>,
      filterCell: {
        type: "text",
        placeholder: t("common.filter"),
        value: columnFilters.text.date ?? "",
        onChange: (v) => columnFilters.setTextValue("date", v),
      },
      sortValue: (r) => r.report_date,
    },
    {
      key: "team",
      header: t("production.reports.column.team"),
      defaultWidth: 120,
      cell: (r) => <span className="text-muted-foreground">{r.team ?? "—"}</span>,
      filterCell: {
        type: "text",
        placeholder: t("common.filter"),
        value: columnFilters.text.team ?? "",
        onChange: (v) => columnFilters.setTextValue("team", v),
      },
      sortValue: (r) => r.team,
    },
    {
      key: "shift",
      header: t("production.reports.column.shift"),
      defaultWidth: 120,
      cell: (r) => <span className="text-muted-foreground">{r.shift ?? "—"}</span>,
      filterCell: {
        type: "text",
        placeholder: t("common.filter"),
        value: columnFilters.text.shift ?? "",
        onChange: (v) => columnFilters.setTextValue("shift", v),
      },
      sortValue: (r) => r.shift,
    },
    {
      key: "status",
      header: t("production.reports.column.status"),
      defaultWidth: 130,
      cell: (r) => <StatusBadge status={r.status} />,
      filterCell: { type: "blank" },
      sortValue: (r) => r.status,
    },
    {
      key: "action",
      header: t("production.reports.column.action"),
      defaultWidth: 220,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right",
      filterCell: { type: "blank" },
      cell: (r) => (
        <PackingRowActions
          report={r}
          products={products}
          locations={locations}
          uoms={uoms}
          finishedProductId={productOfOrder(r.of_id)}
          isEditing={editingId === r.id}
          onOpenEdit={(open) => setEditingId(open ? r.id : null)}
          onSubmitReport={() => submitMutation.mutate(r.id)}
          isSubmitting={submitMutation.isPending && submitMutation.variables === r.id}
        />
      ),
    },
  ];
  const table = useTableColumns("production.conditionnement", columns);
  const sortedReports = table.sortRows(visible);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard
          label={t("production.dailyReports.stat.drafts")}
          value={reports.filter((r) => r.status === "draft").length}
          icon={<Pencil className="h-5 w-5" />}
        />
        <StatCard
          label={t("production.dailyReports.stat.awaiting")}
          value={reports.filter((r) => r.status === "submitted").length}
          icon={<Send className="h-5 w-5" />}
          accent="warning"
        />
        <StatCard
          label={t("production.dailyReports.stat.validated")}
          value={reports.filter((r) => r.status === "validated").length}
          icon={<CheckCircle2 className="h-5 w-5" />}
          accent="success"
        />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("production.conditionnement.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("production.conditionnement.subtitle")}</p>
            </div>
            <FilterTabs
              options={[
                { value: "all", label: t("common.all") },
                { value: "draft", label: t("status.draft") },
                { value: "submitted", label: t("status.submitted") },
                { value: "validated", label: t("status.validated") },
                { value: "rejected", label: t("status.rejected") },
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
                  <Button size="sm" disabled={openWorkOrders.length === 0}>
                    <Plus className="h-4 w-4" />
                    {t("production.conditionnement.new")}
                  </Button>
                </DialogTrigger>
                <DialogContent className="max-w-4xl">
                  <DialogHeader>
                    <DialogTitle>{t("production.conditionnement.dialog.create.title")}</DialogTitle>
                    <DialogDescription>{t("production.conditionnement.dialog.create.description")}</DialogDescription>
                  </DialogHeader>
                  <form
                    className="space-y-4"
                    onSubmit={form.handleSubmit((input) => {
                      if (selectedOrderHasNoProduct && !input.product_id) {
                        form.setError("product_id", { message: "Required" });
                        return;
                      }
                      createMutation.mutate(input);
                    })}
                  >
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      <div className="space-y-1.5">
                        <Label htmlFor="c_of_id">{t("production.reports.field.of")}</Label>
                        <Select id="c_of_id" {...form.register("of_id")}>
                          <option value="">—</option>
                          {openWorkOrders.map((o) => (
                            <option key={o.id} value={o.id}>
                              {o.reference}
                            </option>
                          ))}
                        </Select>
                        {form.formState.errors.of_id && (
                          <p className="text-sm text-destructive">{form.formState.errors.of_id.message}</p>
                        )}
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="c_report_date">{t("production.reports.field.date")}</Label>
                        <Input id="c_report_date" type="date" {...form.register("report_date")} />
                      </div>
                      <ShiftTeamFields
                        idPrefix="c_"
                        teamField={form.register("team")}
                        shiftField={form.register("shift")}
                      />
                    </div>
                    {selectedOrderHasNoProduct && (
                      <div className="space-y-1.5 rounded-lg border border-border bg-muted/30 p-3">
                        <Label htmlFor="c_product_id">{t("production.conditionnement.field.product")}</Label>
                        <Select id="c_product_id" {...form.register("product_id")}>
                          <option value="">—</option>
                          {products.map((product) => (
                            <option key={product.id} value={product.id}>
                              {product.name}
                            </option>
                          ))}
                        </Select>
                        {form.formState.errors.product_id && (
                          <p className="text-sm text-destructive">{form.formState.errors.product_id.message}</p>
                        )}
                        <p className="text-xs text-muted-foreground">{t("production.conditionnement.help.product")}</p>
                      </div>
                    )}
                    <PackingDetailFields
                form={form}
                products={products}
                locations={locations}
                uoms={uoms}
                finishedProductId={productOfOrder(form.watch("of_id"))}
              />
                    <Button type="submit" className="w-full" disabled={createMutation.isPending}>
                      {createMutation.isPending ? t("common.saving") : t("production.conditionnement.create")}
                    </Button>
                  </form>
                </DialogContent>
              </Dialog>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="space-y-2 p-6">
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
            </div>
          ) : visible.length === 0 ? (
            <EmptyState
              icon={<Boxes className="h-5 w-5" />}
              title={t("production.conditionnement.empty.title")}
              description={t("production.conditionnement.empty.description")}
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
                  {sortedReports.map((report) => (
                    <motion.tr
                      key={report.id}
                      layout
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="cursor-pointer border-b border-border transition-colors hover:bg-muted/40"
                      onClick={() => setOpenReport(report)}
                    >
                      {table.visibleColumns.map((column) => (
                        <TableCell
                          key={column.key}
                          className={column.cellClassName}
                          onClick={column.key === "action" ? (event) => event.stopPropagation() : undefined}
                        >
                          {column.cell(report)}
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

      {focusedReport && (
        <PackingReportDialog
          report={focusedReport}
          reference={referenceOf(focusedReport.of_id)}
          finishedProductId={productOfOrder(focusedReport.of_id)}
          products={products}
          locations={locations}
          uoms={uoms}
          onClose={() => {
            setOpenReport(null);
            // Drop the deep link too, or closing reopens it next render.
            if (linkedId) {
              const next = new URLSearchParams(searchParams);
              next.delete("report");
              setSearchParams(next, { replace: true });
            }
          }}
        />
      )}
    </div>
  );
}

/**
 * The opened packing report. A validated one has already put finished goods into
 * stock and taken packaging out, so editing or deleting it reverses those
 * movements first - both ask for a reason that lands in the audit trail.
 */
function PackingReportDialog({
  report,
  reference,
  finishedProductId,
  products,
  locations,
  uoms,
  onClose,
}: {
  report: ProductionReport;
  reference: string;
  finishedProductId: string | undefined;
  products: { id: string; name: string; uom_id: string }[];
  locations: { id: string; name: string }[];
  uoms: { id: string; code: string }[];
  onClose: () => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");

  const { data: full } = useQuery({
    queryKey: ["production", "reports", report.id],
    queryFn: () => getReport(token, report.id),
  });
  const detail = full?.detail as ConditionnementReportDetail | undefined;

  const form = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    values: {
      of_id: report.of_id,
      report_date: report.report_date,
      team: report.team ?? "",
      shift: report.shift ?? "",
      ...EMPTY_DETAIL,
      ...(detail ?? {}),
      waste_lines: toWasteLineForms<"product" | "packaging">(detail?.waste_lines),
      finished_goods_location_id: detail?.finished_goods_location_id ?? "",
      packaging_location_id: detail?.packaging_location_id ?? "",
      film_product_id: detail?.film_product_id ?? "",
      carton_product_id: detail?.carton_product_id ?? "",
      tape_product_id: detail?.tape_product_id ?? "",
      downtime_reason: detail?.downtime_reason ?? "",
      lot_number: detail?.lot_number ?? "",
      dlc_date: detail?.dlc_date ?? "",
    } as CreateForm,
  });

  function invalidate() {
    for (const key of [
      QUERY_KEY,
      ["production", "reports", report.id],
      ["production", "reports", "pending"],
      ["warehouse", "stock"],
      ["warehouse", "stock", "moves"],
      ["production", "work-order-yields"],
    ]) {
      queryClient.invalidateQueries({ queryKey: key });
    }
  }

  const saveMutation = useMutation({
    mutationFn: (input: CreateForm) => {
      if (report.status === "validated") {
        return correctValidatedConditionnementReport(token, report.id, toDetail(input), reason);
      }
      if (report.status === "submitted") {
        return correctConditionnementReport(token, report.id, toDetail(input), reason);
      }
      return updateConditionnementReport(token, report.id, toDetail(input));
    },
    onSuccess: () => {
      invalidate();
      toast.success(t("production.reports.updated"));
      onClose();
    },
    onError: (error) => {
      toast.error(t("production.reports.updateError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const goodsUnit = productUnit(finishedProductId, products, uoms);
  const filmUnit = productUnit(detail?.film_product_id, products, uoms);
  const cartonUnit = productUnit(detail?.carton_product_id, products, uoms);
  const tapeUnit = productUnit(detail?.tape_product_id, products, uoms);

  const figures: FigureRow[] = [
    // Decision 24/25: cartons lead -- for a product with a carton tier, this is
    // what decides the finished-goods quantity, not the machine's own tally
    // beside it.
    { label: t("production.conditionnement.field.carton"), value: detail?.carton_quantity, unit: cartonUnit },
    {
      label: t("production.conditionnement.field.packetsCounted"),
      value: detail?.packets_counted,
      unit: goodsUnit,
    },
    { label: t("production.conditionnement.field.film"), value: detail?.film_quantity, unit: filmUnit },
    { label: t("production.conditionnement.field.tape"), value: detail?.tape_quantity, unit: tapeUnit },
    // One row per déchet, each labelled with its own item and unit. Scotch
    // shows up here on its own now instead of having nowhere to go.
    ...(detail?.waste_lines ?? []).map((line) => ({
      label: `${t(`production.waste.category.${line.category}` as Parameters<typeof t>[0])} — ${
        (line.product_id && products.find((p) => p.id === line.product_id)?.name) ||
        t("production.waste.unknownItem")
      }`,
      value: line.quantity,
      unit: productUnit(line.product_id, products, uoms),
    })),
    { label: t("production.conditionnement.field.machineSpeed"), value: detail?.machine_speed, unit: "u/min" },
    { label: t("production.ofDetails.time.production"), value: detail?.production_minutes, duration: true },
    { label: t("production.ofDetails.time.downtime"), value: detail?.downtime_minutes, duration: true },
    { label: t("production.reports.field.downtimeReason"), value: detail?.downtime_reason ?? "—" },
    { label: t("production.conditionnement.field.lotNumber"), value: detail?.lot_number ?? "—" },
    { label: t("production.conditionnement.field.dlc"), value: detail?.dlc_date ?? "—" },
  ];

  const needsReason = report.status !== "draft";

  return (
    <ReportDetailDialog
      open
      onOpenChange={(next) => !next && onClose()}
      title={`${reference} · ${report.report_date}`}
      subtitle={[report.shift, report.team].filter(Boolean).join(" · ") || t("common.none")}
      status={report.status}
      revision={report.revision}
      reportId={report.id}
      banner={<ReportVarianceBanner reportId={report.id} />}
      figures={figures}
      onDelete={async (deleteReason) => {
        await deleteReport(token, report.id, deleteReason);
        invalidate();
      }}
      editForm={
        <form className="space-y-4" onSubmit={form.handleSubmit((input) => saveMutation.mutate(input))}>
          <PackingDetailFields
            form={form}
            products={products}
            locations={locations}
            uoms={uoms}
            finishedProductId={finishedProductId}
          />
          {needsReason && (
            <div className="space-y-1.5">
              <Label htmlFor="c_correction_reason">{t("production.reports.correctionReason")}</Label>
              <Input
                id="c_correction_reason"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder={t("production.reports.correctionReasonPlaceholder")}
              />
              <p className="text-xs text-muted-foreground">
                {report.status === "validated"
                  ? t("production.reports.correctionValidatedHelp")
                  : t("production.reports.correctionHelp")}
              </p>
            </div>
          )}
          <Button
            type="submit"
            className="w-full"
            disabled={saveMutation.isPending || (needsReason && !reason.trim())}
          >
            {saveMutation.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      }
    />
  );
}

function PackingDetailFields({
  form,
  products,
  locations,
  uoms,
  finishedProductId,
}: {
  form: ReturnType<typeof useForm<CreateForm>>;
  products: { id: string; name: string; uom_id: string; packets_per_carton?: number | null }[];
  locations: { id: string; name: string }[];
  uoms: { id: string; code: string }[];
  finishedProductId: string | undefined;
}) {
  const { t } = useI18n();
  // Packaging leaves stock in its own unit and finished goods enter in theirs,
  // so every quantity here states the unit the warehouse will move.
  const goodsUnit = productUnit(finishedProductId, products, uoms);
  const filmUnit = productUnit(form.watch("film_product_id"), products, uoms);
  const cartonUnit = productUnit(form.watch("carton_product_id"), products, uoms);
  const tapeUnit = productUnit(form.watch("tape_product_id"), products, uoms);
  const withUnit = (label: string, unit: string | null) => (unit ? `${label} (${unit})` : label);

  // Decision 24: the live cross-check between what the floor boxed and what the
  // machine tallied, shown while typing rather than only after saving.
  const packetsPerCarton = products.find((p) => p.id === finishedProductId)?.packets_per_carton ?? null;
  const cartonsEntered = Number(form.watch("carton_quantity")) || 0;
  const packetsEntered = Number(form.watch("packets_counted")) || 0;
  const realPacketsFromCartons = packetsPerCarton ? cartonsEntered * packetsPerCarton : null;
  const estimatedCartonsFromMachine = packetsPerCarton ? packetsEntered / packetsPerCarton : null;
  const productOptions = (
    <>
      <option value="">—</option>
      {products.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}
        </option>
      ))}
    </>
  );

  return (
    <div className="space-y-3">
      <section className="space-y-2">
        <div className="flex items-center gap-1.5">
          <Package className="h-4 w-4 text-muted-foreground" />
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t("production.conditionnement.section.output")}
          </p>
          <HelpTooltip text={t("production.conditionnement.help.output")} />
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="carton_quantity" className="flex items-center gap-1">
              {withUnit(t("production.conditionnement.field.carton"), cartonUnit)}
              <HelpTooltip text={t("production.conditionnement.help.cartonQuantity")} />
            </Label>
            <Input id="carton_quantity" type="number" step="any" {...form.register("carton_quantity")} />
            {realPacketsFromCartons !== null && (
              <p className="text-xs text-muted-foreground">
                {t("production.conditionnement.hint.realPacketsFromCartons")}{" "}
                {formatQuantity(realPacketsFromCartons)}
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="packets_counted" className="flex items-center gap-1">
              {withUnit(t("production.conditionnement.field.packetsCounted"), goodsUnit)}
              <HelpTooltip text={t("production.conditionnement.help.packetsCounted")} />
            </Label>
            <Input id="packets_counted" type="number" step="any" {...form.register("packets_counted")} />
            {estimatedCartonsFromMachine !== null && (
              <p className="text-xs text-muted-foreground">
                {t("production.conditionnement.hint.estimatedCartonsFromMachine")}{" "}
                {formatQuantity(estimatedCartonsFromMachine)}
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="carton_product_id">{t("production.conditionnement.field.cartonProduct")}</Label>
            <Select id="carton_product_id" {...form.register("carton_product_id")}>
              {productOptions}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="finished_goods_location_id">{t("production.conditionnement.field.finishedGoodsStore")}</Label>
            <Select id="finished_goods_location_id" {...form.register("finished_goods_location_id")}>
              <option value="">—</option>
              {locations.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </Select>
          </div>
        </div>
      </section>

      <section className="space-y-2">
        <div className="flex items-center gap-1.5">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t("production.conditionnement.section.packaging")}
          </p>
          <HelpTooltip text={t("production.conditionnement.help.packaging")} />
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1.5">
            <Label htmlFor="film_quantity">{withUnit(t("production.conditionnement.field.film"), filmUnit)}</Label>
            <Input id="film_quantity" type="number" step="any" {...form.register("film_quantity")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="film_product_id">{t("production.conditionnement.field.filmProduct")}</Label>
            <Select id="film_product_id" {...form.register("film_product_id")}>
              {productOptions}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tape_quantity">{withUnit(t("production.conditionnement.field.tape"), tapeUnit)}</Label>
            <Input id="tape_quantity" type="number" step="any" {...form.register("tape_quantity")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tape_product_id">{t("production.conditionnement.field.tapeProduct")}</Label>
            <Select id="tape_product_id" {...form.register("tape_product_id")}>
              {productOptions}
            </Select>
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="packaging_location_id">{t("production.conditionnement.field.packagingStore")}</Label>
            <Select id="packaging_location_id" {...form.register("packaging_location_id")}>
              <option value="">—</option>
              {locations.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </Select>
          </div>
        </div>
      </section>

      <section className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t("production.dailyReports.section.waste")}
        </p>
        <WasteLinesField
          form={form}
          name="waste_lines"
          categories={["product", "packaging"]}
          products={products}
          uoms={uoms}
          defaultProductFor={(category) =>
            // Déchet produit is the OF's own product by definition. Packaging
            // waste could be film, carton or scotch, so it is left to the shift
            // -- picking one of three would be a guess, not a default.
            category === "product" ? finishedProductId || undefined : undefined
          }
        />
      </section>

      <section className="space-y-2">
        <div className="flex items-center gap-1.5">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t("production.conditionnement.section.dlc")}
          </p>
          <HelpTooltip text={t("production.conditionnement.help.dlc")} />
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
          <div className="space-y-1.5">
            <Label htmlFor="lot_number">{t("production.conditionnement.field.lotNumber")}</Label>
            <Input id="lot_number" {...form.register("lot_number")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="dlc_date">{t("production.conditionnement.field.dlc")}</Label>
            <Input id="dlc_date" type="date" {...form.register("dlc_date")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="machine_speed">{t("production.conditionnement.field.machineSpeed")} (u/min)</Label>
            <Input id="machine_speed" type="number" step="any" {...form.register("machine_speed")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="c_production_minutes">{t("production.reports.field.productionMinutes")} (min)</Label>
            <Input id="c_production_minutes" type="number" {...form.register("production_minutes")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="c_downtime_minutes">{t("production.reports.field.downtimeMinutes")} (min)</Label>
            <Input id="c_downtime_minutes" type="number" {...form.register("downtime_minutes")} />
          </div>
          <div className="space-y-1.5 sm:col-span-3">
            <Label htmlFor="c_downtime_reason">{t("production.reports.field.downtimeReason")}</Label>
            <Input id="c_downtime_reason" {...form.register("downtime_reason")} />
          </div>
        </div>
      </section>
    </div>
  );
}

function PackingRowActions({
  report,
  products,
  locations,
  uoms,
  finishedProductId,
  isEditing,
  onOpenEdit,
  onSubmitReport,
  isSubmitting,
}: {
  report: ProductionReport;
  products: { id: string; name: string; uom_id: string }[];
  locations: { id: string; name: string }[];
  uoms: { id: string; code: string }[];
  finishedProductId: string | undefined;
  isEditing: boolean;
  onOpenEdit: (open: boolean) => void;
  onSubmitReport: () => void;
  isSubmitting: boolean;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();

  // Fetched only once the dialog is actually open — the row renders this
  // component for every visible report, and most of them never get edited.
  const { data: full } = useQuery({
    queryKey: ["production", "reports", report.id],
    queryFn: () => getReport(token, report.id),
    enabled: isEditing,
  });
  const detail = full?.detail as ConditionnementReportDetail | undefined;

  const form = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    values: {
      of_id: report.of_id,
      report_date: report.report_date,
      ...EMPTY_DETAIL,
      ...(detail ?? {}),
      waste_lines: toWasteLineForms<"product" | "packaging">(detail?.waste_lines),
      finished_goods_location_id: detail?.finished_goods_location_id ?? "",
      packaging_location_id: detail?.packaging_location_id ?? "",
      film_product_id: detail?.film_product_id ?? "",
      carton_product_id: detail?.carton_product_id ?? "",
      tape_product_id: detail?.tape_product_id ?? "",
      downtime_reason: detail?.downtime_reason ?? "",
      lot_number: detail?.lot_number ?? "",
      dlc_date: detail?.dlc_date ?? "",
    } as CreateForm,
  });

  const updateMutation = useMutation({
    mutationFn: (input: CreateForm) => updateConditionnementReport(token, report.id, toDetail(input)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      onOpenEdit(false);
      toast.success(t("production.reports.updated"));
    },
    onError: (error) => {
      toast.error(t("production.reports.updateError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  return (
    <div className="flex justify-end gap-2">
      {report.status === "draft" && (
        <>
          <Dialog open={isEditing} onOpenChange={onOpenEdit}>
            <DialogTrigger asChild>
              <Button size="sm" variant="ghost">
                <Pencil className="h-3.5 w-3.5" />
                {t("common.edit")}
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-4xl">
              <DialogHeader>
                <DialogTitle>{t("production.conditionnement.dialog.edit.title")}</DialogTitle>
                <DialogDescription>{t("production.dailyReports.dialog.edit.description")}</DialogDescription>
              </DialogHeader>
              <form className="space-y-4" onSubmit={form.handleSubmit((input) => updateMutation.mutate(input))}>
                <PackingDetailFields
                  form={form}
                  products={products}
                  locations={locations}
                  uoms={uoms}
                  finishedProductId={finishedProductId}
                />
                <Button type="submit" className="w-full" disabled={updateMutation.isPending}>
                  {updateMutation.isPending ? t("common.saving") : t("common.save")}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
          <Button size="sm" variant="outline" onClick={onSubmitReport} disabled={isSubmitting}>
            <Send className="h-3.5 w-3.5" />
            {isSubmitting ? t("production.reports.submitting") : t("production.reports.submit")}
          </Button>
        </>
      )}
      {report.status === "rejected" && (
        <span className="text-xs text-destructive">{report.rejection_reason ?? t("status.rejected")}</span>
      )}
    </div>
  );
}

/**
 * The écart for one packing report: the tonnage's expected packets against the
 * tally. Gross by design — at this point quality has usually raised nothing yet,
 * and labelling a gross figure as net would be a lie the screen tells silently.
 */
function ReportVarianceBanner({ reportId }: { reportId: string }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const { data: variance } = useQuery({
    queryKey: ["production", "packaging-variance", "report", reportId],
    queryFn: () => getReportPackagingVariance(session!.token, reportId),
  });

  if (!variance) return null;

  return (
    <div className="space-y-1">
      <PackagingVariancePanel variance={variance} />
      {!variance.parameters_frozen && (
        <p className="text-xs text-muted-foreground">{t("production.packagingVariance.notFrozen")}</p>
      )}
    </div>
  );
}
