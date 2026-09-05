import { useEffect, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, ClipboardList, Droplets, Flame, Pencil, Plus, Send, Wheat } from "lucide-react";
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
import {
  SemolinaLinesField,
  fromSemolinaLineForms,
  toSemolinaLineForms,
  type SemolinaLineForm,
} from "./SemolinaLinesField";
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
  correctDailyReport,
  correctValidatedDailyReport,
  createDailyReport,
  deleteReport,
  getReport,
  listMolds,
  listProducts,
  listReports,
  listWorkOrders,
  submitReport,
  updateDailyReport,
  type DailyReportDetail,
  type Mold,
  type ProductionReport,
  type ReportStatus,
} from "./api";
import { listLocations, listUoms } from "../warehouse/api";
import { UTILITY_UNITS, productUnit } from "../../lib/units";

// A shift's daily report. Semolina is the one figure here that leaves stock when
// a supervisor validates it, which is why the form insists on naming the product
// and the store before the report can be handed over.
const detailSchema = z.object({
  // Semoule poured this shift, one line per quality — see SemolinaLinesField.
  semolina_lines: z.array(
    z.object({
      product_id: z.string(),
      quantity: z.coerce.number().min(0),
      location_id: z.string(),
    }),
  ),
  raw_material_location_id: z.string().optional(),
  regrind_input_quantity: z.coerce.number().min(0),
  regrind_input_product_id: z.string().optional(),
  dough_quantity: z.coerce.number().min(0),
  finished_product_quantity: z.coerce.number().min(0),
  regrind_quantity: z.coerce.number().min(0),
  regrind_product_id: z.string().optional(),
  // Which mold this shift ran — named per report, not on the OF.
  mold_id: z.string().optional(),
  // Déchets. A list, so a shift can record whatever it actually lost --
  // and each line names its item, which is what gives the figure a unit.
  waste_lines: z
    .array(
      z.object({
        category: z.enum(["raw_material", "press", "pouring", "cutting"]),
        product_id: z.string(),
        quantity: z.coerce.number().min(0),
        note: z.string(),
      }),
    ),
  water_quantity: z.coerce.number().min(0),
  // The operator's real input: water dosed as a percentage of the semoule
  // poured. water_quantity is derived from it — see DailyDetailFields.
  water_percentage: z.coerce.number().min(0).max(100),
  fuel_quantity: z.coerce.number().min(0),
  electricity_quantity: z.coerce.number().min(0),
  // Débit de semoule, tonnes/hour — recorded for future recipe statistics.
  semolina_flow_rate: z.coerce.number().min(0),
  production_minutes: z.coerce.number().int().min(0),
  downtime_minutes: z.coerce.number().int().min(0),
  downtime_reason: z.string().optional(),
});

const createSchema = detailSchema.extend({
  of_id: z.string().min(1, "Required"),
  report_date: z.string().min(1, "Required"),
  team: z.string().optional(),
  shift: z.string().optional(),
});
type CreateForm = z.infer<typeof createSchema>;

const QUERY_KEY = ["production", "reports", "daily"] as const;
const WORK_ORDERS_QUERY_KEY = ["production", "work-orders"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;
const UOMS_QUERY_KEY = ["core", "uoms"] as const;
const MOLDS_QUERY_KEY = ["production", "molds"] as const;

type StatusFilter = "all" | ReportStatus;

const EMPTY_DETAIL = {
  semolina_lines: [] as SemolinaLineForm[],
  raw_material_location_id: "",
  regrind_input_quantity: 0,
  regrind_input_product_id: "",
  dough_quantity: 0,
  finished_product_quantity: 0,
  regrind_quantity: 0,
  regrind_product_id: "",
  mold_id: "",
  waste_lines: [] as WasteLineForm<"raw_material" | "press" | "pouring" | "cutting">[],
  water_quantity: 0,
  water_percentage: 0,
  fuel_quantity: 0,
  electricity_quantity: 0,
  semolina_flow_rate: 0,
  production_minutes: 0,
  downtime_minutes: 0,
  downtime_reason: "",
};

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

export function DailyReportsTab() {
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
    queryFn: () => listReports(token, { report_type: "daily" }),
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
  const { data: molds = [] } = useQuery({ queryKey: MOLDS_QUERY_KEY, queryFn: () => listMolds(token) });

  // Only orders that still accept reports — a closed or cancelled OF does not.
  const openWorkOrders = workOrders.filter((o) => ["planned", "ongoing", "suspended"].includes(o.status));
  const referenceOf = (ofId: string) => workOrders.find((o) => o.id === ofId)?.reference ?? ofId;

  const form = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    defaultValues: { of_id: "", report_date: todayIso(), team: "", shift: "", ...EMPTY_DETAIL },
  });

  const createMutation = useMutation({
    mutationFn: (input: CreateForm) =>
      createDailyReport(token, {
        of_id: input.of_id,
        report_date: input.report_date,
        team: input.team || undefined,
        shift: input.shift || undefined,
        detail: toDetail(input),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setDialogOpen(false);
      form.reset({ of_id: "", report_date: todayIso(), team: "", shift: "", ...EMPTY_DETAIL });
      toast.success(t("production.dailyReports.created"));
    },
    onError: (error) => {
      toast.error(t("production.dailyReports.createError"), {
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

  const draftCount = reports.filter((r) => r.status === "draft").length;
  const submittedCount = reports.filter((r) => r.status === "submitted").length;
  const validatedCount = reports.filter((r) => r.status === "validated").length;

  const filterFields: FilterField<ProductionReport>[] = [
    { key: "of", kind: "text", getValue: (r) => referenceOf(r.of_id) },
    { key: "date", kind: "text", getValue: (r) => r.report_date },
    { key: "team", kind: "text", getValue: (r) => r.team },
    { key: "shift", kind: "text", getValue: (r) => r.shift },
    { key: "revision", kind: "range", getValue: (r) => r.revision },
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
      // Covered by the FilterTabs above the table — no second control for it.
      cell: (r) => <StatusBadge status={r.status} />,
      filterCell: { type: "blank" },
      sortValue: (r) => r.status,
    },
    {
      key: "revision",
      header: t("production.reports.column.revision"),
      defaultWidth: 110,
      cell: (r) => <span className="tabular-nums text-muted-foreground">{r.revision}</span>,
      filterCell: {
        type: "range",
        min: columnFilters.range.revision?.min ?? "",
        max: columnFilters.range.revision?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("revision", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("revision", "max", v),
      },
      sortValue: (r) => r.revision,
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
        <ReportRowActions
          report={r}
          products={products}
          locations={locations}
          uoms={uoms}
          workOrders={workOrders}
          molds={molds}
          isEditing={editingId === r.id}
          onOpenEdit={(open) => setEditingId(open ? r.id : null)}
          onSubmitReport={() => submitMutation.mutate(r.id)}
          isSubmitting={submitMutation.isPending && submitMutation.variables === r.id}
        />
      ),
    },
  ];
  const table = useTableColumns("production.dailyReports", columns);
  const sortedReports = table.sortRows(visible);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("production.dailyReports.stat.drafts")} value={draftCount} icon={<Pencil className="h-5 w-5" />} />
        <StatCard
          label={t("production.dailyReports.stat.awaiting")}
          value={submittedCount}
          icon={<Send className="h-5 w-5" />}
          accent="warning"
        />
        <StatCard
          label={t("production.dailyReports.stat.validated")}
          value={validatedCount}
          icon={<CheckCircle2 className="h-5 w-5" />}
          accent="success"
        />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("production.dailyReports.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("production.dailyReports.subtitle")}</p>
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
                    {t("production.dailyReports.new")}
                  </Button>
                </DialogTrigger>
                <DialogContent className="max-w-4xl">
                  <DialogHeader>
                    <DialogTitle>{t("production.dailyReports.dialog.create.title")}</DialogTitle>
                    <DialogDescription>{t("production.dailyReports.dialog.create.description")}</DialogDescription>
                  </DialogHeader>
                  <form
                    className="space-y-4"
                    onSubmit={form.handleSubmit((input) => createMutation.mutate(input))}
                  >
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      <div className="space-y-1.5">
                        <Label htmlFor="of_id">{t("production.reports.field.of")}</Label>
                        <Select id="of_id" {...form.register("of_id")}>
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
                        <Label htmlFor="report_date">{t("production.reports.field.date")}</Label>
                        <Input id="report_date" type="date" {...form.register("report_date")} />
                      </div>
                      <ShiftTeamFields
                        idPrefix=""
                        teamField={form.register("team")}
                        shiftField={form.register("shift")}
                      />
                    </div>

                    <DailyDetailFields form={form} products={products} locations={locations} uoms={uoms} workOrders={workOrders} molds={molds} />

                    <Button type="submit" className="w-full" disabled={createMutation.isPending}>
                      {createMutation.isPending ? t("common.saving") : t("production.dailyReports.create")}
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
              icon={<ClipboardList className="h-5 w-5" />}
              title={t("production.dailyReports.empty.title")}
              description={t("production.dailyReports.empty.description")}
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
                          // The action column has its own buttons; a click there
                          // should not also open the report behind them.
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
        <DailyReportDialog
          report={focusedReport}
          reference={referenceOf(focusedReport.of_id)}
          products={products}
          locations={locations}
          uoms={uoms}
          workOrders={workOrders}
          molds={molds}
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
 * The opened report. What can be done to it depends on where it is: a draft is
 * the team's to edit, a submitted one is corrected by a validator, and a
 * validated one reverses and re-posts its stock when changed or deleted.
 */
function DailyReportDialog({
  report,
  reference,
  products,
  locations,
  uoms,
  workOrders,
  molds,
  onClose,
}: {
  report: ProductionReport;
  reference: string;
  products: { id: string; name: string; uom_id: string }[];
  locations: { id: string; name: string }[];
  uoms: { id: string; code: string }[];
  workOrders: { id: string; product_type: string | null }[];
  molds: Mold[];
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
  const detail = full?.detail as DailyReportDetail | undefined;

  const form = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    values: {
      of_id: report.of_id,
      report_date: report.report_date,
      team: report.team ?? "",
      shift: report.shift ?? "",
      ...EMPTY_DETAIL,
      ...(detail ?? {}),
      semolina_lines: toSemolinaLineForms(detail?.semolina_lines),
      raw_material_location_id: detail?.raw_material_location_id ?? "",
      regrind_input_product_id: detail?.regrind_input_product_id ?? "",
      regrind_product_id: detail?.regrind_product_id ?? "",
      mold_id: detail?.mold_id ?? "",
      waste_lines: toWasteLineForms<"raw_material" | "press" | "pouring" | "cutting">(detail?.waste_lines),
      downtime_reason: detail?.downtime_reason ?? "",
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
        return correctValidatedDailyReport(token, report.id, toDetail(input), reason);
      }
      if (report.status === "submitted") {
        return correctDailyReport(token, report.id, toDetail(input), reason);
      }
      return updateDailyReport(token, report.id, toDetail(input));
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

  const semolinaUnit = productUnit(detail?.semolina_lines?.[0]?.product_id, products, uoms);
  const rebroyatUnit = productUnit(detail?.regrind_input_product_id, products, uoms);
  const regrindUnit = productUnit(detail?.regrind_product_id, products, uoms);
  const productName = (id: string | null) =>
    (id && products.find((p) => p.id === id)?.name) || t("production.waste.unknownItem");

  const figures: FigureRow[] = [
    // One row per quality poured, each in its own unit.
    ...(detail?.semolina_lines ?? []).map((line) => ({
      label:
        detail && detail.semolina_lines.length > 1
          ? `${t("production.dailyReports.field.semolina")} — ${productName(line.product_id)}`
          : t("production.dailyReports.field.semolina"),
      value: line.quantity,
      unit: productUnit(line.product_id, products, uoms),
    })),
    { label: t("production.dailyReports.field.regrindInput"), value: detail?.regrind_input_quantity, unit: rebroyatUnit },
    { label: t("production.dailyReports.field.dough"), value: detail?.dough_quantity, unit: semolinaUnit },
    {
      label: t("production.reports.field.finishedTonnage"),
      value: detail?.finished_product_quantity,
      unit: "t",
    },
    // One row per déchet, each labelled with its own item and therefore its
    // own unit. A single "waste" figure could only ever carry one of them.
    ...(detail?.waste_lines ?? []).map((line) => ({
      label: `${t(`production.waste.category.${line.category}` as Parameters<typeof t>[0])} — ${productName(line.product_id)}`,
      value: line.quantity,
      unit: productUnit(line.product_id, products, uoms),
    })),
    { label: t("production.dailyReports.field.regrind"), value: detail?.regrind_quantity, unit: regrindUnit },
    { label: t("production.dailyReports.field.waterPercentage"), value: detail?.water_percentage, unit: "%" },
    { label: t("production.dailyReports.field.water"), value: detail?.water_quantity, unit: UTILITY_UNITS.water },
    { label: t("production.dailyReports.field.fuel"), value: detail?.fuel_quantity, unit: UTILITY_UNITS.fuel },
    {
      label: t("production.dailyReports.field.electricity"),
      value: detail?.electricity_quantity,
      unit: UTILITY_UNITS.electricity,
    },
    {
      label: t("production.dailyReports.field.semolinaFlowRate"),
      value: detail?.semolina_flow_rate,
      unit: "t/h",
    },
    { label: t("production.ofDetails.time.production"), value: detail?.production_minutes, duration: true },
    { label: t("production.ofDetails.time.downtime"), value: detail?.downtime_minutes, duration: true },
    { label: t("production.reports.field.downtimeReason"), value: detail?.downtime_reason ?? "—" },
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
      figures={figures}
      onDelete={async (deleteReason) => {
        await deleteReport(token, report.id, deleteReason);
        invalidate();
      }}
      editForm={
        <form className="space-y-4" onSubmit={form.handleSubmit((input) => saveMutation.mutate(input))}>
          <DailyDetailFields form={form} products={products} locations={locations} uoms={uoms} workOrders={workOrders} molds={molds} />
          {needsReason && (
            <div className="space-y-1.5">
              <Label htmlFor="correction_reason">{t("production.reports.correctionReason")}</Label>
              <Input
                id="correction_reason"
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

function toDetail(input: CreateForm): Partial<DailyReportDetail> {
  return {
    semolina_lines: fromSemolinaLineForms(input.semolina_lines),
    raw_material_location_id: input.raw_material_location_id || undefined,
    regrind_input_quantity: input.regrind_input_quantity,
    regrind_input_product_id: input.regrind_input_product_id || undefined,
    dough_quantity: input.dough_quantity,
    finished_product_quantity: input.finished_product_quantity,
    regrind_quantity: input.regrind_quantity,
    regrind_product_id: input.regrind_product_id || undefined,
    mold_id: input.mold_id || undefined,
    waste_lines: fromWasteLineForms(input.waste_lines),
    water_quantity: input.water_quantity,
    water_percentage: input.water_percentage,
    fuel_quantity: input.fuel_quantity,
    electricity_quantity: input.electricity_quantity,
    semolina_flow_rate: input.semolina_flow_rate,
    production_minutes: input.production_minutes,
    downtime_minutes: input.downtime_minutes,
    downtime_reason: input.downtime_reason || undefined,
  } as Partial<DailyReportDetail>;
}

/** The figure grid, shared by the create dialog and the draft editor. */
function DailyDetailFields({
  form,
  products,
  locations,
  uoms,
  workOrders,
  molds,
}: {
  form: ReturnType<typeof useForm<CreateForm>>;
  products: { id: string; name: string; uom_id: string }[];
  locations: { id: string; name: string }[];
  uoms: { id: string; code: string }[];
  workOrders: { id: string; product_type: string | null }[];
  molds: Mold[];
}) {
  const { t } = useI18n();
  // Every figure is entered in its product's own stock unit — the same unit the
  // warehouse deducts in — so the label states it rather than offering a choice.
  // The first line stands in for "the semoule unit" where one figure (dough)
  // needs a single unit to show — dough is the mix of whatever was poured.
  const semolinaUnit = productUnit(form.watch("semolina_lines.0.product_id"), products, uoms);
  const rebroyatUnit = productUnit(form.watch("regrind_input_product_id"), products, uoms);
  // What the shift *produced* as rebroyat, which is a different item again --
  // ground pasta weighed in kilos, not semoule and not wrapped packets.
  const regrindUnit = productUnit(form.watch("regrind_product_id"), products, uoms);
  const withUnit = (label: string, unit: string | null) => (unit ? `${label} (${unit})` : label);
  // The mold list narrows to the order's own PC/PL once it's known; before
  // that (or if the order predates the field) every mold stays offered.
  const orderProductType = workOrders.find((o) => o.id === form.watch("of_id"))?.product_type;
  const moldsForOrder = molds.filter((m) => !orderProductType || m.type === orderProductType);

  // The plant doses water as a percentage of the semoule poured, set on the
  // mixer -- not read off a meter in litres. So the percentage is the real
  // input, and water_quantity (still what consolidation and the cockpit read)
  // is kept in sync from it here rather than typed twice. Summed across every
  // quality poured: unlike a waste line's item, every semoule line is the
  // same commodity by weight, so adding them is meaningful.
  const watchedSemolinaLines = form.watch("semolina_lines");
  const totalSemoule = (watchedSemolinaLines ?? []).reduce((sum, line) => sum + (Number(line.quantity) || 0), 0);
  const watchedWaterPercentage = form.watch("water_percentage");
  useEffect(() => {
    if (!watchedWaterPercentage) return;
    const computed = Math.round(((watchedWaterPercentage / 100) * totalSemoule + Number.EPSILON) * 100) / 100;
    form.setValue("water_quantity", computed);
    // form.setValue is stable across renders; watching it would refire on
    // every keystroke elsewhere in the form.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watchedWaterPercentage, totalSemoule]);
  return (
    <div className="space-y-3">
      <section className="space-y-2">
        <div className="flex items-center gap-1.5">
          <Wheat className="h-4 w-4 text-muted-foreground" />
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t("production.dailyReports.section.material")}
          </p>
          <HelpTooltip text={t("production.dailyReports.help.material")} />
        </div>

        {/* Its own line, not sharing the grid below it — a moule choice reads
            oddly squeezed between two quantities in the same row. */}
        <div className="max-w-xs space-y-1.5">
          <Label htmlFor="mold_id">{t("production.dailyReports.field.mold")}</Label>
          <Select id="mold_id" {...form.register("mold_id")}>
            <option value="">—</option>
            {moldsForOrder.map((mold) => (
              <option key={mold.id} value={mold.id}>
                {mold.code} — {mold.name}
              </option>
            ))}
          </Select>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1.5">
            <Label htmlFor="raw_material_location_id" className="flex min-h-[2rem] items-start">
              {t("production.dailyReports.field.rawMaterialLocation")}
            </Label>
            <Select id="raw_material_location_id" {...form.register("raw_material_location_id")}>
              <option value="">—</option>
              {locations.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="regrind_input_quantity" className="flex min-h-[2rem] items-start gap-1">
              {withUnit(t("production.dailyReports.field.regrindInput"), rebroyatUnit)}
              <HelpTooltip text={t("production.dailyReports.help.regrindInput")} />
            </Label>
            <Input id="regrind_input_quantity" type="number" step="any" {...form.register("regrind_input_quantity")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="regrind_input_product_id" className="flex min-h-[2rem] items-start">
              {t("production.dailyReports.field.regrindInputProduct")}
            </Label>
            <Select id="regrind_input_product_id" {...form.register("regrind_input_product_id")}>
              <option value="">—</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="dough_quantity" className="flex min-h-[2rem] items-start gap-1">
              {withUnit(t("production.dailyReports.field.dough"), semolinaUnit)}
              <HelpTooltip text={t("production.dailyReports.help.dough")} />
            </Label>
            <Input id="dough_quantity" type="number" step="any" {...form.register("dough_quantity")} />
          </div>
        </div>

        <div className="space-y-1.5">
          <Label className="flex items-center gap-1">
            {t("production.dailyReports.field.semolina")}
            <HelpTooltip text={t("production.semolina.help")} />
          </Label>
          <SemolinaLinesField form={form} name="semolina_lines" products={products} locations={locations} uoms={uoms} />
        </div>

        <div className="max-w-xs space-y-1.5">
          <Label htmlFor="semolina_flow_rate" className="flex items-center gap-1">
            {t("production.dailyReports.field.semolinaFlowRate")}
            <HelpTooltip text={t("production.dailyReports.help.semolinaFlowRate")} />
          </Label>
          <Input id="semolina_flow_rate" type="number" step="any" {...form.register("semolina_flow_rate")} />
        </div>
      </section>

      {/* An output, not a matière — its own row so it never reads as an input
          the way it did sitting inside the MP grid. */}
      <section className="space-y-2">
        <div className="max-w-xs space-y-1.5">
          <Label htmlFor="finished_product_quantity" className="flex items-center gap-1">
            {/* A tonnage, and now labelled as one (decision 17). It showed no
                unit at all before, while its own help text called it a tonnage. */}
            {t("production.reports.field.finishedTonnage")}
            <HelpTooltip text={t("production.dailyReports.help.finishedProduct")} />
          </Label>
          <Input
            id="finished_product_quantity"
            type="number"
            step="any"
            {...form.register("finished_product_quantity")}
          />
        </div>
      </section>

      <section className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t("production.dailyReports.section.waste")}
        </p>
        <WasteLinesField
          form={form}
          name="waste_lines"
          categories={["raw_material", "press", "pouring", "cutting"]}
          products={products}
          uoms={uoms}
          defaultProductFor={(category) =>
            // Déchet matière is semoule by definition, so the report's first
            // semoule line is the right first guess. Déchet presse, versement
            // and découpe name no other field -- better an empty box the
            // shift fills in than a product nobody chose.
            category === "raw_material" ? form.getValues("semolina_lines.0.product_id") || undefined : undefined
          }
        />
      </section>

      <section className="space-y-2">
        <div className="flex items-center gap-1.5">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t("production.dailyReports.section.regrind")}
          </p>
          <HelpTooltip text={t("production.dailyReports.help.regrind")} />
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1.5">
            <Label htmlFor="regrind_product_id" className="flex items-center gap-1">
              {t("production.dailyReports.field.regrindProduct")}
              <HelpTooltip text={t("production.dailyReports.help.regrindProduct")} />
            </Label>
            <Select id="regrind_product_id" {...form.register("regrind_product_id")}>
              <option value="">—</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="regrind_quantity">{withUnit(t("production.dailyReports.field.regrind"), regrindUnit)}</Label>
            <Input id="regrind_quantity" type="number" step="any" {...form.register("regrind_quantity")} />
          </div>
        </div>
      </section>

      <section className="space-y-2">
        <div className="flex items-center gap-1.5">
          <Flame className="h-4 w-4 text-muted-foreground" />
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t("production.dailyReports.section.utilities")}
          </p>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1.5">
            <Label htmlFor="water_percentage" className="flex items-center gap-1">
              <Droplets className="h-3.5 w-3.5" />
              {t("production.dailyReports.field.waterPercentage")}
              <HelpTooltip text={t("production.dailyReports.help.waterPercentage")} />
            </Label>
            <Input
              id="water_percentage"
              type="number"
              step="any"
              min={0}
              max={100}
              {...form.register("water_percentage")}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="water_quantity">
              {t("production.dailyReports.field.water")} ({UTILITY_UNITS.water})
            </Label>
            <Input id="water_quantity" type="number" step="any" {...form.register("water_quantity")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="fuel_quantity">
              {t("production.dailyReports.field.fuel")} ({UTILITY_UNITS.fuel})
            </Label>
            <Input id="fuel_quantity" type="number" step="any" {...form.register("fuel_quantity")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="electricity_quantity">
              {t("production.dailyReports.field.electricity")} ({UTILITY_UNITS.electricity})
            </Label>
            <Input id="electricity_quantity" type="number" step="any" {...form.register("electricity_quantity")} />
          </div>
        </div>
      </section>

      <section className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t("production.dailyReports.section.time")}
        </p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="space-y-1.5">
            <Label htmlFor="production_minutes">{t("production.reports.field.productionMinutes")}</Label>
            <Input id="production_minutes" type="number" {...form.register("production_minutes")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="downtime_minutes">{t("production.reports.field.downtimeMinutes")}</Label>
            <Input id="downtime_minutes" type="number" {...form.register("downtime_minutes")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="downtime_reason">{t("production.reports.field.downtimeReason")}</Label>
            <Input id="downtime_reason" {...form.register("downtime_reason")} />
          </div>
        </div>
      </section>
    </div>
  );
}

/**
 * Per-row actions. A real subcomponent rather than a function called inside
 * `.map()`, because it owns its own form state — calling hooks from a plain
 * helper would break the Rules of Hooks as the row count changes.
 */
function ReportRowActions({
  report,
  products,
  locations,
  uoms,
  workOrders,
  molds,
  isEditing,
  onOpenEdit,
  onSubmitReport,
  isSubmitting,
}: {
  report: ProductionReport;
  products: { id: string; name: string; uom_id: string }[];
  locations: { id: string; name: string }[];
  uoms: { id: string; code: string }[];
  workOrders: { id: string; product_type: string | null }[];
  molds: Mold[];
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
  const detail = full?.detail as DailyReportDetail | undefined;

  const form = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    values: {
      of_id: report.of_id,
      report_date: report.report_date,
      ...EMPTY_DETAIL,
      ...(detail ?? {}),
      semolina_lines: toSemolinaLineForms(detail?.semolina_lines),
      raw_material_location_id: detail?.raw_material_location_id ?? "",
      regrind_input_product_id: detail?.regrind_input_product_id ?? "",
      regrind_product_id: detail?.regrind_product_id ?? "",
      mold_id: detail?.mold_id ?? "",
      waste_lines: toWasteLineForms<"raw_material" | "press" | "pouring" | "cutting">(detail?.waste_lines),
      downtime_reason: detail?.downtime_reason ?? "",
    } as CreateForm,
  });

  const updateMutation = useMutation({
    mutationFn: (input: CreateForm) => updateDailyReport(token, report.id, toDetail(input)),
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
                <DialogTitle>{t("production.dailyReports.dialog.edit.title")}</DialogTitle>
                <DialogDescription>{t("production.dailyReports.dialog.edit.description")}</DialogDescription>
              </DialogHeader>
              <form className="space-y-4" onSubmit={form.handleSubmit((input) => updateMutation.mutate(input))}>
                <DailyDetailFields form={form} products={products} locations={locations} uoms={uoms} workOrders={workOrders} molds={molds} />
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
