import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  CalendarClock,
  ChevronDown,
  ChevronRight,
  FlaskConical,
  History,
  Pencil,
  Plus,
  Send,
  ShieldAlert,
  Tags,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { rowEnterProps } from "../../components/motion/rowMotion";
import { formatQuantity, productUnit } from "../../lib/units";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Skeleton } from "../../components/ui/skeleton";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Popover, PopoverContent, PopoverTrigger } from "../../components/ui/popover";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
  ResizableTableHead,
} from "../../components/ui/table";
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
import { GroupHeaderRow } from "../../components/patterns/GroupHeaderRow";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { groupRows, type GroupSpec } from "../../lib/groupRows";
import { listProducts, listWorkCenters, listWorkOrders, type Product } from "../production/api";
import { listShiftReports, SHIFT_REPORTS_QUERY_KEY } from "../production/shift/shiftApi";
import { listLocations, listUoms } from "../warehouse/api";
import { ReportDetailDialog, type FigureRow } from "../production/ReportDetailDialog";
import { NonConformityDetailDialog } from "./NonConformityDetailDialog";
import {
  adminUpdateQualityReport,
  createQualityReport,
  deleteParameterEntry,
  deleteQualityReport,
  getQualityReport,
  listFollowUps,
  listInspectableShiftReports,
  listNonConformities,
  listParameters,
  listQualityReports,
  raiseNonConformity,
  reviseQualityReport,
  saveParameterEntry,
  submitQualityReport,
  updateQualityReport,
  type ConformityLine,
  type NonConformity,
  type NonConformitySeverity,
  type ParameterEntry,
  type QualityReport,
  type QualityReportStatus,
} from "./api";
import { AppLoader } from "../../components/patterns/AppLoader";

// One row per packing row of the inspected shift -- the backend seeds them at
// creation, so the form only ever edits counts, never adds or drops a product.
const lineSchema = z
  .object({
    shift_packing_row_id: z.string(),
    conforming_cartons: z.coerce.number().min(0).int("Must be a whole number"),
    non_conforming_cartons: z.coerce.number().min(0).int("Must be a whole number"),
    defect_details: z.string().optional(),
  })
  // Same rule the backend's validate_conformity_line enforces, caught before
  // the round trip so the error lands on the row that needs it.
  .refine((line) => line.non_conforming_cartons === 0 || !!line.defect_details?.trim(), {
    path: ["defect_details"],
    message: "Required",
  });

const editSchema = z.object({
  lines: z.array(lineSchema),
  comments: z.string().optional(),
  corrective_action: z.string().optional(),
});
type EditForm = z.infer<typeof editSchema>;

const createSchema = z.object({
  shift_report_id: z.string().min(1, "Required"),
});
type CreateForm = z.infer<typeof createSchema>;

const QUERY_KEY = ["qc", "quality-reports"] as const;
const FOLLOW_UPS_QUERY_KEY = ["qc", "follow-ups"] as const;
const WORK_ORDERS_QUERY_KEY = ["production", "work-orders"] as const;
const WORK_CENTERS_QUERY_KEY = ["production", "work-centers"] as const;
const INSPECTABLE_QUERY_KEY = ["qc", "shift-reports"] as const;
// Same key the Non-conformities tab lists under, so the report dialog's
// linked-NC lookup is a cache hit there and is refreshed by its mutations.
const NC_QUERY_KEY = ["qc", "non-conformities"] as const;
const parametersQueryKey = (reportId: string) => ["qc", "parameters", reportId] as const;

type StatusFilter = "all" | QualityReportStatus;
type GroupByOption = "none" | "workCenter" | "shift";

const DEFECT_CODES = [
  {
    category: "qc.quality.defectCode.packaging",
    items: [
      { key: "packaging.crushed", label: "qc.quality.defectCode.packaging.crushed" },
      { key: "packaging.wet", label: "qc.quality.defectCode.packaging.wet" },
      { key: "packaging.sealing", label: "qc.quality.defectCode.packaging.sealing" },
    ],
  },
  {
    category: "qc.quality.defectCode.labeling",
    items: [
      { key: "labeling.missing", label: "qc.quality.defectCode.labeling.missing" },
      { key: "labeling.unreadable", label: "qc.quality.defectCode.labeling.unreadable" },
      { key: "labeling.barcode", label: "qc.quality.defectCode.labeling.barcode" },
    ],
  },
  {
    category: "qc.quality.defectCode.content",
    items: [
      { key: "content.quantity", label: "qc.quality.defectCode.content.quantity" },
      { key: "content.reference", label: "qc.quality.defectCode.content.reference" },
      { key: "content.damaged", label: "qc.quality.defectCode.content.damaged" },
    ],
  },
  {
    category: "qc.quality.defectCode.other",
    items: [{ key: "other.comments", label: "qc.quality.defectCode.other.comments" }],
  },
] as const;

/**
 * The nine groups of the paper "Contrôle des paramètres" sheet. Mirrors
 * backend/modules/qc/domain/parameters.py's PARAMETER_GROUPS (the backend
 * refuses any field not listed there) -- kept client-side because it is small
 * and static. `entryLabel` says what keys one row of the group: a reading time
 * for most, a press / compressor number, or the PL/PC line for additif.
 */
const PARAMETER_GROUPS = [
  { key: "presse", entryLabel: "press", fields: ["pression", "debit_bar", "niveau_moulange_percent"] },
  { key: "pompe_vide", entryLabel: "time", fields: ["niveau_huile", "temperature_c", "niveau_vide_bar"] },
  { key: "sechage", entryLabel: "time", fields: ["temperature_c", "delta"] },
  {
    key: "chaudiere",
    entryLabel: "time",
    fields: [
      "t_aller_c",
      "p_aller_bar",
      "t_retour_c",
      "p_retour_bar",
      "t_digit_c",
      "signal_a_elec",
      "niveau_bac_exp",
      "niveau_bac_alim",
      "compteur_cuve1",
      "compteur_cuve2",
    ],
  },
  { key: "compresseurs", entryLabel: "compressor", fields: ["pression_bar", "temperature_c"] },
  {
    key: "traitement_eau",
    entryLabel: "time",
    fields: ["niveau_cuve1", "niveau_cuve2", "niveau_sel", "niveau_bicore", "niveau_bache", "niveau_chateau"],
  },
  {
    key: "chiller",
    entryLabel: "time",
    fields: [
      "t_entree_c",
      "t_sortie_c",
      "p_entree_bar",
      "p_sortie_bar",
      "t_digit_entree_c",
      "t_digit_sortie_c",
      "proprete_radiateur",
      "observation",
    ],
  },
  { key: "additif", entryLabel: "line", fields: ["tableau", "niveau_tremie", "observation"] },
  {
    key: "proprete_locaux",
    entryLabel: "time",
    fields: ["lave_m", "chaud", "tri_eau", "compr", "b_eau", "presse", "pres_en_h", "sech_en_h", "silo"],
  },
] as const;
type ParameterGroup = (typeof PARAMETER_GROUPS)[number];

/** A typed reading is stored as a number when it reads as one, as text otherwise; blank is left out. */
function parameterValue(raw: string): number | string | undefined {
  const trimmed = raw.trim();
  if (!trimmed) return undefined;
  const asNumber = Number(trimmed.replace(",", "."));
  return Number.isFinite(asNumber) ? asNumber : trimmed;
}

function hasPacketsPerCarton(product: Product | undefined): boolean {
  return !!product?.packets_per_carton && product.packets_per_carton > 0;
}

export function QualityReportsTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  // QC inspects one shift of one line at a time, so seeing every quality
  // report for the same work center together -- instead of interleaved by
  // date -- is the default: it's what makes a line's repeat defects visible.
  const [groupBy, setGroupBy] = useState<GroupByOption>("workCenter");
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  // Only the first group starts open; re-collapse the rest each time the
  // grouping changes rather than only on first mount.
  const collapseInitializedFor = useRef<GroupByOption | null>(null);
  const [openReport, setOpenReport] = useState<QualityReport | null>(null);
  const [openMode, setOpenMode] = useState<"view" | "edit" | "history" | "delete">("view");
  const [autoResubmit, setAutoResubmit] = useState(false);
  // Which report is open lives in the URL as well as in state, so an OF's
  // quality panel can link straight to one instead of landing on the list.
  const [searchParams, setSearchParams] = useSearchParams();
  const linkedId = searchParams.get("report");
  function openReportAt(report: QualityReport, mode: "view" | "edit" | "history" | "delete", options?: { autoResubmit?: boolean }) {
    setOpenReport(report);
    setOpenMode(mode);
    setAutoResubmit(options?.autoResubmit ?? false);
  }

  const { data: reports = [], isLoading } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => listQualityReports(token),
  });
  const { data: followUps = [] } = useQuery({
    queryKey: FOLLOW_UPS_QUERY_KEY,
    queryFn: () => listFollowUps(token),
  });
  const { data: workCenters = [] } = useQuery({
    queryKey: WORK_CENTERS_QUERY_KEY,
    queryFn: () => listWorkCenters(token),
  });
  // A quality report only carries its shift report's id; which line (work
  // center) that shift ran on is production's to say.
  const { data: shiftReports = [] } = useQuery({
    queryKey: [...SHIFT_REPORTS_QUERY_KEY, "qc-lookup"],
    queryFn: () => listShiftReports(token),
  });
  // Validated shift reports not yet inspected. QC always inspects one shift
  // of one line -- every packing row of it at once -- so this backs the
  // create form's only selector.
  const { data: inspectable = [] } = useQuery({
    queryKey: INSPECTABLE_QUERY_KEY,
    queryFn: () => listInspectableShiftReports(token),
  });

  const workCenterName = (workCenterId: string | undefined) =>
    workCenterId ? workCenters.find((w) => w.id === workCenterId)?.name ?? null : null;
  const workCenterOf = (r: QualityReport) =>
    workCenterName(shiftReports.find((s) => s.id === r.shift_report_id)?.work_center_id) ?? "—";
  const inspectableLabel = (row: (typeof inspectable)[number]) =>
    [workCenterName(row.work_center_id), row.report_date, row.shift, row.team].filter(Boolean).join(" · ");
  // A link may name a report that no longer exists; a miss opens nothing rather
  // than an empty dialog.
  const focusedReport = openReport ?? reports.find((r) => r.id === linkedId) ?? null;

  const form = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    defaultValues: { shift_report_id: "" },
  });

  const createMutation = useMutation({
    mutationFn: (input: CreateForm) => createQualityReport(token, input.shift_report_id),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: INSPECTABLE_QUERY_KEY });
      setDialogOpen(false);
      form.reset({ shift_report_id: "" });
      toast.success(t("qc.quality.created"));
      // The new report arrives with one zeroed line per packed product; the
      // inspector's next step is always filling them in, so land there.
      openReportAt(created, "edit");
    },
    onError: (error) => {
      toast.error(t("qc.quality.createError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const submitMutation = useMutation({
    mutationFn: (reportId: string) => submitQualityReport(token, reportId),
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

  const reviseMutation = useMutation({
    mutationFn: (reportId: string) => reviseQualityReport(token, reportId),
    onSuccess: (revised) => {
      openReportAt(revised, "edit", { autoResubmit: true });
    },
    onError: (error) => {
      toast.error(t("production.reports.resubmitError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const filterFields: FilterField<QualityReport>[] = [
    { key: "workCenter", kind: "text", getValue: (r) => workCenterOf(r) },
    { key: "date", kind: "text", getValue: (r) => r.report_date },
    { key: "shift", kind: "text", getValue: (r) => r.shift },
  ];
  const columnFilters = useColumnFilters<QualityReport>(filterFields);
  const visible = columnFilters.apply(
    statusFilter === "all" ? reports : reports.filter((r) => r.status === statusFilter),
  );

  const columns: ColumnDef<QualityReport>[] = [
    {
      key: "workCenter",
      header: t("production.workOrders.column.workCenter"),
      defaultWidth: 220,
      cell: (r) => (
        <span className="block min-w-0 truncate font-medium" title={workCenterOf(r)}>
          {workCenterOf(r)}
        </span>
      ),
      filterCell: {
        type: "text",
        placeholder: t("common.filter"),
        value: columnFilters.text.workCenter ?? "",
        onChange: (v) => columnFilters.setTextValue("workCenter", v),
      },
      sortValue: (r) => workCenterOf(r),
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
      key: "followUp",
      header: t("qc.quality.column.followUp"),
      defaultWidth: 160,
      filterCell: { type: "blank" },
      cell: (r) => {
        const window = followUps.find((f) => f.quality_report_id === r.id);
        if (!window) return <span className="text-muted-foreground">—</span>;
        return (
          <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
            <CalendarClock className="h-3.5 w-3.5" />
            {window.window_ends_on}
          </span>
        );
      },
      sortValue: (r) => followUps.find((f) => f.quality_report_id === r.id)?.window_ends_on,
    },
    {
      key: "action",
      header: t("production.reports.column.action"),
      defaultWidth: 200,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right",
      filterCell: { type: "blank" },
      cell: (r) => (
        <QualityRowActions
          report={r}
          onOpenReport={(mode) => openReportAt(r, mode)}
          onSubmitReport={() => submitMutation.mutate(r.id)}
          isSubmitting={submitMutation.isPending && submitMutation.variables === r.id}
          onReviseReport={() => reviseMutation.mutate(r.id)}
          isResubmitting={reviseMutation.isPending && reviseMutation.variables === r.id}
        />
      ),
    },
  ];
  const table = useTableColumns("qc.qualityReports", columns);
  const sortedVisible = table.sortRows(visible);

  function toggleGroup(key: string) {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const groupSpec: GroupSpec<QualityReport> | undefined =
    groupBy === "none"
      ? undefined
      : groupBy === "workCenter"
        ? {
            key: "workCenter",
            label: t("production.workOrders.column.workCenter"),
            getGroupKey: (r) => workCenterOf(r),
            getGroupLabel: (r) => workCenterOf(r),
          }
        : { key: "shift", label: t("production.reports.groupBy.shift"), getGroupKey: (r) => r.shift ?? "", getGroupLabel: (r) => r.shift || t("common.none") };
  const rowGroups = groupRows(sortedVisible, groupSpec);

  useEffect(() => {
    if (groupBy === "none" || rowGroups.length === 0) return;
    if (collapseInitializedFor.current === groupBy) return;
    collapseInitializedFor.current = groupBy;
    setCollapsedGroups(new Set(rowGroups.slice(1).map((g) => g.key)));
  }, [groupBy, rowGroups]);

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
          label={t("qc.quality.stat.openFollowUps")}
          value={followUps.filter((f) => f.status !== "completed").length}
          icon={<CalendarClock className="h-5 w-5" />}
          accent="accent"
        />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("qc.quality.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("qc.quality.subtitle")}</p>
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
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">{t("production.reports.groupBy.label")}:</span>
              <FilterTabs
                options={[
                  { value: "none", label: t("production.reports.groupBy.none") },
                  { value: "workCenter", label: t("production.workOrders.column.workCenter") },
                  { value: "shift", label: t("production.reports.groupBy.shift") },
                ]}
                value={groupBy}
                onChange={setGroupBy}
              />
            </div>
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
                  <Button size="sm" disabled={inspectable.length === 0}>
                    <Plus className="h-4 w-4" />
                    {t("qc.quality.new")}
                  </Button>
                </DialogTrigger>
                <DialogContent className="max-w-2xl">
                  <DialogHeader>
                    <DialogTitle>{t("qc.quality.dialog.create.title")}</DialogTitle>
                    <DialogDescription>{t("qc.quality.dialog.create.description")}</DialogDescription>
                  </DialogHeader>
                  <form className="space-y-4" onSubmit={form.handleSubmit((input) => createMutation.mutate(input))}>
                    <div className="space-y-1.5">
                      <Label htmlFor="q_shift_report_id">{t("qc.quality.field.shiftReport")}</Label>
                      <Select id="q_shift_report_id" {...form.register("shift_report_id")}>
                        <option value="">—</option>
                        {inspectable.map((row) => (
                          <option key={row.shift_report_id} value={row.shift_report_id}>
                            {inspectableLabel(row)}
                          </option>
                        ))}
                      </Select>
                      {form.formState.errors.shift_report_id && (
                        <p className="text-sm text-destructive">{form.formState.errors.shift_report_id.message}</p>
                      )}
                      <p className="text-xs text-muted-foreground">{t("qc.quality.help.shiftReport")}</p>
                    </div>
                    <Button type="submit" className="w-full" disabled={createMutation.isPending}>
                      {createMutation.isPending ? t("common.saving") : t("qc.quality.create")}
                    </Button>
                  </form>
                </DialogContent>
              </Dialog>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <AppLoader className="py-8" />
          ) : visible.length === 0 ? (
            <EmptyState
              icon={<FlaskConical className="h-5 w-5" />}
              title={t("qc.quality.empty.title")}
              description={t("qc.quality.empty.description")}
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
                  {(() => {
                    let rowIndex = 0;
                    return rowGroups.flatMap((group) => {
                      const collapsed = groupSpec !== undefined && collapsedGroups.has(group.key);
                      const rows: ReactNode[] = [];
                      if (groupSpec) {
                        rows.push(
                          <GroupHeaderRow
                            key={`group-${group.key}`}
                            label={group.label}
                            count={group.rows.length}
                            collapsed={collapsed}
                            onToggle={() => toggleGroup(group.key)}
                            colSpan={table.visibleColumns.length}
                          />,
                        );
                      }
                      if (!collapsed) {
                        for (const report of group.rows) {
                          rows.push(
                            <motion.tr
                              key={report.id}
                              {...rowEnterProps(rowIndex++)}
                              className="cursor-pointer border-b border-border transition-colors hover:bg-muted/40"
                              onClick={() => openReportAt(report, "view")}
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
                            </motion.tr>,
                          );
                        }
                      }
                      return rows;
                    });
                  })()}
                </AnimatePresence>
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {focusedReport && (
        <QualityReportDialog
          // Remount per report so a row's Edit/History/Delete action always
          // lands the dialog on the right tab instead of reusing whatever
          // tab a previous report was left on.
          key={focusedReport.id}
          report={focusedReport}
          reference={workCenterOf(focusedReport)}
          initialMode={openMode}
          autoResubmit={autoResubmit}
          onClose={() => {
            setOpenReport(null);
            setOpenMode("view");
            setAutoResubmit(false);
            // Drop the deep link too, or closing reopens it on the next render.
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
 * The opened quality report. Nothing here moves stock, so a correction is a
 * straight edit; what a validated report *does* hold is its follow-up windows
 * (one per conformity line), which the backend takes away with the report
 * when it is deleted.
 */
export function QualityReportDialog({
  report,
  reference,
  initialMode,
  autoResubmit,
  onClose,
}: {
  report: QualityReport;
  /** What the title leads with: the line (work center) here, the OF reference on an OF's page. */
  reference: string;
  /**
   * @deprecated Ignored. Units and product now come from each conformity
   * line's own product -- one shift can pack several. Still accepted so
   * existing callers keep compiling until they drop it.
   */
  packetsPerCarton?: number | null;
  /** @deprecated Ignored, see `packetsPerCarton`. */
  productId?: string;
  initialMode?: "view" | "edit" | "history" | "delete";
  autoResubmit?: boolean;
  onClose: () => void;
}) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  // A linked NC opens stacked on top of this dialog rather than navigating to
  // the Non-conformities tab — closing it returns here instead of losing
  // whatever page this dialog itself was opened from.
  const [openLinkedNc, setOpenLinkedNc] = useState<NonConformity | null>(null);

  const { data: full } = useQuery({
    queryKey: ["qc", "quality-reports", report.id],
    queryFn: () => getQualityReport(token, report.id),
  });
  const detail = full?.detail ?? null;
  const lines = full?.lines ?? [];

  // NCs carry their quality_report_id; the backend's list has no filter by
  // report, so the full list (shared with the Non-conformities tab's cache) is
  // narrowed here.
  const { data: allNonConformities = [] } = useQuery({
    queryKey: NC_QUERY_KEY,
    queryFn: () => listNonConformities(token),
  });
  const linkedNonConformities = allNonConformities.filter((n) => n.quality_report_id === report.id);
  // The NC unit is (report, OF, product): one shift can pack the same product
  // for the same OF on several rows, and one NC covers them all (the backend
  // sums their non-conforming cartons). Defective lines are grouped that way
  // into one entry carrying the group's total; a group whose OF+product already
  // has a ticket on this report is covered, the rest still need one raised.
  const defectiveLinesWithoutNc = Object.values(
    lines
      .filter((line) => line.non_conforming_cartons > 0)
      .reduce<Record<string, ConformityLine>>((groups, line) => {
        const key = `${line.of_id}:${line.product_id}`;
        const group = groups[key];
        groups[key] = group
          ? {
              ...group,
              non_conforming_cartons: group.non_conforming_cartons + line.non_conforming_cartons,
              defect_details: [group.defect_details, line.defect_details].filter(Boolean).join(" / ") || null,
            }
          : line;
        return groups;
      }, {}),
  ).filter(
    (group) => !linkedNonConformities.some((nc) => nc.of_id === group.of_id && nc.product_id === group.product_id),
  );

  // Reference data — a plain useQuery, so it's a cache hit (no extra request)
  // wherever the page that opened this dialog already loaded the same lists.
  const { data: ncProducts = [] } = useQuery({ queryKey: ["core", "products"], queryFn: () => listProducts(token) });
  const { data: ncUoms = [] } = useQuery({ queryKey: ["core", "uoms"], queryFn: () => listUoms(token) });
  const { data: ncLocations = [] } = useQuery({ queryKey: ["warehouse", "locations"], queryFn: () => listLocations(token) });
  const { data: workOrders = [] } = useQuery({ queryKey: WORK_ORDERS_QUERY_KEY, queryFn: () => listWorkOrders(token) });

  const productOf = (line: ConformityLine) => ncProducts.find((p) => p.id === line.product_id);
  // The product is what the inspector recognizes; the OF reference tells two
  // runs of the same product in one shift apart.
  const lineLabel = (line: ConformityLine) => {
    const productName = productOf(line)?.name ?? line.product_id;
    const ofReference = workOrders.find((o) => o.id === line.of_id)?.reference;
    return ofReference ? `${productName} — ${ofReference}` : productName;
  };
  // A carton tier is a property of the product: one with no packets_per_carton
  // is counted in sacs (a sac is its own sellable unit, see packaging_estimate.py).
  const lineUnit = (line: ConformityLine) =>
    t(hasPacketsPerCarton(productOf(line)) ? "qc.quality.unit.cartons" : "qc.quality.unit.sacs");

  const form = useForm<EditForm>({
    resolver: zodResolver(editSchema),
    values: {
      lines: lines.map((line) => ({
        shift_packing_row_id: line.shift_packing_row_id,
        conforming_cartons: line.conforming_cartons,
        non_conforming_cartons: line.non_conforming_cartons,
        defect_details: line.defect_details ?? "",
      })),
      comments: detail?.comments ?? "",
      corrective_action: detail?.corrective_action ?? "",
    },
  });

  function invalidate() {
    for (const key of [QUERY_KEY, ["qc", "quality-reports", report.id], FOLLOW_UPS_QUERY_KEY]) {
      queryClient.invalidateQueries({ queryKey: key });
    }
  }

  const saveMutation = useMutation({
    mutationFn: async (input: EditForm) => {
      const payload = {
        lines: input.lines.map((line) => ({
          shift_packing_row_id: line.shift_packing_row_id,
          conforming_cartons: line.conforming_cartons,
          non_conforming_cartons: line.non_conforming_cartons,
          defect_details: line.defect_details?.trim() || null,
        })),
        detail: {
          comments: input.comments?.trim() || null,
          corrective_action: input.corrective_action?.trim() || null,
        },
      };
      const updated =
        report.status === "draft"
          ? await updateQualityReport(token, report.id, payload)
          : await adminUpdateQualityReport(token, report.id, { ...payload, reason });

      // If this is a resubmit flow, chain a submit call after save succeeds
      if (autoResubmit) {
        await submitQualityReport(token, report.id);
      }

      return updated;
    },
    onSuccess: () => {
      invalidate();
      toast.success(autoResubmit ? t("production.reports.resubmitted") : t("production.reports.updated"));
      onClose();
    },
    onError: (error) => {
      toast.error(autoResubmit ? t("production.reports.resubmitError") : t("production.reports.updateError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  // Conformity is per product now (see the lines table in the banner); what
  // stays report-level is the inspector's own notes.
  const figures: FigureRow[] = [
    { label: t("qc.quality.field.comments"), value: detail?.comments ?? "—" },
    { label: t("qc.quality.field.correctiveAction"), value: detail?.corrective_action ?? "—" },
  ];

  const needsReason = report.status !== "draft";
  // Mirrors the backend: parameter entries are writable on a draft, otherwise
  // only by an admin correcting the report in place.
  const parametersEditable = report.status === "draft" || hasPermission("qc.admin_quality_reports");

  return (
    <>
    <ReportDetailDialog
      open
      onOpenChange={(next) => !next && onClose()}
      title={`${reference} · ${report.report_date}`}
      subtitle={[report.shift, report.team].filter(Boolean).join(" · ") || t("common.none")}
      status={report.status}
      revision={report.revision}
      reportId={report.id}
      historyEntityType="quality_report"
      figures={figures}
      banner={
        <div className="space-y-4">
          <ConformityLinesView lines={lines} lineLabel={lineLabel} lineUnit={lineUnit} isLoading={!full} />
          {linkedNonConformities.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t("qc.quality.nc.linkedTitle")}
              </p>
              {linkedNonConformities.map((nc, index) => (
                <motion.button
                  key={nc.id}
                  type="button"
                  initial={{ opacity: 0, scale: 0.94 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ duration: 0.28, ease: [0.2, 0.8, 0.2, 1], delay: Math.min(index, 8) * 0.03 }}
                  onClick={() => setOpenLinkedNc(nc)}
                  className="flex w-full items-center gap-3 rounded-lg border border-border p-3 text-left transition-colors hover:border-destructive/30 hover:bg-muted/40"
                >
                  <AlertTriangle className="h-4 w-4 shrink-0 text-destructive" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{nc.reference}</p>
                    <p className="truncate text-xs text-muted-foreground">{nc.defect_type}</p>
                  </div>
                  <StatusBadge status={nc.status} />
                </motion.button>
              ))}
            </div>
          )}
          {defectiveLinesWithoutNc.map((line) => (
            <RaiseNcFromReportBanner
              key={`${line.of_id}:${line.product_id}`}
              report={report}
              line={line}
              lineLabel={lineLabel(line)}
              comments={detail?.comments ?? null}
            />
          ))}
          <QualityParametersSection reportId={report.id} editable={false} />
        </div>
      }
      initialMode={initialMode}
      onDelete={async (deleteReason) => {
        await deleteQualityReport(token, report.id, deleteReason);
        invalidate();
      }}
      editForm={
        <form className="space-y-4" onSubmit={form.handleSubmit((input) => saveMutation.mutate(input))}>
          <QualityDetailFields form={form} lines={lines} lineLabel={lineLabel} lineUnit={lineUnit} />
          <QualityParametersSection reportId={report.id} editable={parametersEditable} />
          {needsReason && (
            <div className="space-y-1.5">
              <Label htmlFor="q_correction_reason">{t("production.reports.correctionReason")}</Label>
              <Input
                id="q_correction_reason"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder={t("production.reports.correctionReasonPlaceholder")}
              />
              <p className="text-xs text-muted-foreground">{t("production.reports.correctionHelp")}</p>
            </div>
          )}
          <Button
            type="submit"
            className="w-full"
            disabled={saveMutation.isPending || !full || (needsReason && !reason.trim())}
          >
            {saveMutation.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      }
    />
    {openLinkedNc && (
      <NonConformityDetailDialog
        nonConformity={openLinkedNc}
        ofReference={workOrders.find((o) => o.id === openLinkedNc.of_id)?.reference ?? reference}
        products={ncProducts}
        uoms={ncUoms}
        locations={ncLocations}
        onClose={() => setOpenLinkedNc(null)}
      />
    )}
    </>
  );
}

/** The conformity lines, read-only: one row per product the shift packed. */
function ConformityLinesView({
  lines,
  lineLabel,
  lineUnit,
  isLoading,
}: {
  lines: ConformityLine[];
  lineLabel: (line: ConformityLine) => string;
  lineUnit: (line: ConformityLine) => string;
  isLoading: boolean;
}) {
  const { t } = useI18n();
  return (
    <section className="space-y-2">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {t("qc.quality.section.conformity")}
      </p>
      {isLoading ? (
        <Skeleton className="h-16 w-full" />
      ) : lines.length === 0 ? (
        <p className="rounded-lg border border-border p-3 text-sm text-muted-foreground">{t("qc.quality.lines.empty")}</p>
      ) : (
        <div className="rounded-lg border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="px-3">{t("qc.quality.line.product")}</TableHead>
                <TableHead className="px-3 text-right">{t("qc.quality.line.conforming")}</TableHead>
                <TableHead className="px-3 text-right">{t("qc.quality.line.nonConforming")}</TableHead>
                <TableHead className="px-3">{t("qc.quality.field.defectDetails")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {lines.map((line) => (
                <TableRow key={line.id}>
                  <TableCell className="px-3 py-2 font-medium">{lineLabel(line)}</TableCell>
                  <TableCell className="px-3 py-2 text-right tabular-nums">
                    {formatQuantity(line.conforming_cartons, lineUnit(line))}
                  </TableCell>
                  <TableCell
                    className={`px-3 py-2 text-right tabular-nums ${line.non_conforming_cartons > 0 ? "text-destructive" : ""}`}
                  >
                    {formatQuantity(line.non_conforming_cartons, lineUnit(line))}
                  </TableCell>
                  <TableCell className="px-3 py-2 text-muted-foreground">{line.defect_details || "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  );
}

/**
 * A validated report can carry non-conforming cartons with no non-conformity
 * ticket ever raised for them — the only automatic path is the Validation
 * Center's reject step, which is unavailable once the report is already
 * validated. This lets someone raise one after the fact for one conformity
 * line, straight from the report they found the defect on, pre-filled and
 * linked via `quality_report_id` so it shows up back here next time.
 */
function RaiseNcFromReportBanner({
  report,
  line,
  lineLabel,
  comments,
}: {
  report: QualityReport;
  line: ConformityLine;
  lineLabel: string;
  comments: string | null;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [sourceLocationId, setSourceLocationId] = useState("");
  const [quarantineLocationId, setQuarantineLocationId] = useState("");
  const [defectType, setDefectType] = useState(line.defect_details ?? "");
  const [severity, setSeverity] = useState<NonConformitySeverity>("minor");

  const { data: products = [] } = useQuery({ queryKey: ["core", "products"], queryFn: () => listProducts(token) });
  const { data: locations = [] } = useQuery({ queryKey: ["warehouse", "locations"], queryFn: () => listLocations(token) });
  const { data: uoms = [] } = useQuery({ queryKey: ["core", "uoms"], queryFn: () => listUoms(token) });
  const blockedLocations = locations.filter((l) => l.is_blocked);

  const product = products.find((p) => p.id === line.product_id);
  const packetsPerCarton = hasPacketsPerCarton(product) ? product!.packets_per_carton! : null;
  const cartonCount = Number(line.non_conforming_cartons ?? 0);
  const quantity = packetsPerCarton ? cartonCount * packetsPerCarton : cartonCount;
  const unit = productUnit(line.product_id, products, uoms);

  const raiseMutation = useMutation({
    mutationFn: () =>
      raiseNonConformity(token, {
        of_id: line.of_id,
        product_id: line.product_id,
        quantity,
        source_location_id: sourceLocationId,
        quarantine_location_id: quarantineLocationId,
        defect_type: defectType || "Non-conformity",
        severity,
        quality_report_id: report.id,
        description: comments || undefined,
        correlation_id: crypto.randomUUID(),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: NC_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock"] });
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock", "moves"] });
      toast.success(t("qc.nc.raised"));
      setOpen(false);
    },
    onError: (error) => {
      toast.error(t("qc.nc.raiseError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  return (
    <div className="flex items-start gap-3 rounded-lg border border-warning/30 bg-warning-soft p-3">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
      <div className="flex-1 space-y-2">
        <p className="text-sm text-warning">
          <span className="font-medium">{lineLabel}</span> — {t("qc.quality.nc.noneYet")}
        </p>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm" variant="outline">
              <ShieldAlert className="h-3.5 w-3.5" />
              {t("qc.quality.nc.openTicket")}
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{t("qc.nc.dialog.raise.title")}</DialogTitle>
              <DialogDescription>{t("qc.nc.dialog.raise.description")}</DialogDescription>
            </DialogHeader>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div>
                  <p className="text-xs text-muted-foreground">{t("qc.nc.field.product")}</p>
                  <p className="font-medium">{product?.name ?? "—"}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">{t("qc.nc.field.quantity")}</p>
                  <p className="font-medium">{formatQuantity(quantity, unit)}</p>
                </div>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="rn_defect">{t("qc.nc.field.defectType")}</Label>
                <Input id="rn_defect" value={defectType} onChange={(e) => setDefectType(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="rn_severity">{t("qc.nc.column.severity")}</Label>
                <Select
                  id="rn_severity"
                  value={severity}
                  onChange={(e) => setSeverity(e.target.value as NonConformitySeverity)}
                >
                  <option value="minor">{t("qc.nc.severity.minor")}</option>
                  <option value="major">{t("qc.nc.severity.major")}</option>
                  <option value="critical">{t("qc.nc.severity.critical")}</option>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="rn_source">{t("qc.nc.field.pulledFrom")}</Label>
                <Select id="rn_source" value={sourceLocationId} onChange={(e) => setSourceLocationId(e.target.value)}>
                  <option value="">—</option>
                  {locations.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.name}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="rn_quarantine">{t("qc.nc.field.quarantine")}</Label>
                <Select
                  id="rn_quarantine"
                  value={quarantineLocationId}
                  onChange={(e) => setQuarantineLocationId(e.target.value)}
                >
                  <option value="">—</option>
                  {blockedLocations.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.name}
                    </option>
                  ))}
                </Select>
                <p className="text-xs text-muted-foreground">
                  {blockedLocations.length === 0 ? t("qc.nc.help.noBlockedLocation") : t("qc.nc.help.quarantine")}
                </p>
              </div>
              <Button
                className="w-full"
                onClick={() => raiseMutation.mutate()}
                disabled={raiseMutation.isPending || !sourceLocationId || !quarantineLocationId || !defectType.trim()}
              >
                {raiseMutation.isPending ? t("common.saving") : t("qc.nc.raise")}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  );
}

/**
 * The editable part of a report: one conformity row per packed product, then
 * the report-level notes. Rows come from the report itself (seeded by the
 * backend from the shift's packing rows) and are addressed by index in the
 * form, carrying their shift_packing_row_id through to the save.
 */
function QualityDetailFields({
  form,
  lines,
  lineLabel,
  lineUnit,
}: {
  form: ReturnType<typeof useForm<EditForm>>;
  lines: ConformityLine[];
  lineLabel: (line: ConformityLine) => string;
  lineUnit: (line: ConformityLine) => string;
}) {
  const { t } = useI18n();
  const lineErrors = form.formState.errors.lines;

  const addDefectCode = (index: number, label: string) => {
    const current = (form.getValues(`lines.${index}.defect_details`) ?? "").trim();
    form.setValue(`lines.${index}.defect_details`, current ? `${current}; ${label}` : label, {
      shouldDirty: true,
      shouldValidate: form.formState.isSubmitted,
    });
  };

  return (
    <div className="space-y-4">
      <section className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t("qc.quality.section.conformity")}
        </p>
        {lines.length === 0 ? (
          <p className="rounded-lg border border-border p-3 text-sm text-muted-foreground">{t("qc.quality.lines.empty")}</p>
        ) : (
          <div className="rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="px-3">{t("qc.quality.line.product")}</TableHead>
                  <TableHead className="w-28 px-2">{t("qc.quality.line.conforming")}</TableHead>
                  <TableHead className="w-28 px-2">{t("qc.quality.line.nonConforming")}</TableHead>
                  <TableHead className="px-2">{t("qc.quality.field.defectDetails")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {lines.map((line, index) => {
                  const errors = lineErrors?.[index];
                  return (
                    <TableRow key={line.shift_packing_row_id} className="align-top hover:bg-transparent">
                      <TableCell className="px-3 py-2">
                        <p className="font-medium">{lineLabel(line)}</p>
                        <p className="text-xs text-muted-foreground">{lineUnit(line)}</p>
                      </TableCell>
                      <TableCell className="px-2 py-2">
                        <Input
                          type="number"
                          step="1"
                          min="0"
                          aria-label={`${t("qc.quality.line.conforming")} — ${lineLabel(line)}`}
                          {...form.register(`lines.${index}.conforming_cartons`)}
                        />
                        {errors?.conforming_cartons && (
                          <p className="mt-1 text-xs text-destructive">{errors.conforming_cartons.message}</p>
                        )}
                      </TableCell>
                      <TableCell className="px-2 py-2">
                        <Input
                          type="number"
                          step="1"
                          min="0"
                          aria-label={`${t("qc.quality.line.nonConforming")} — ${lineLabel(line)}`}
                          {...form.register(`lines.${index}.non_conforming_cartons`)}
                        />
                        {errors?.non_conforming_cartons && (
                          <p className="mt-1 text-xs text-destructive">{errors.non_conforming_cartons.message}</p>
                        )}
                      </TableCell>
                      <TableCell className="overflow-visible px-2 py-2">
                        <div className="flex items-center gap-1">
                          <Input
                            aria-label={`${t("qc.quality.field.defectDetails")} — ${lineLabel(line)}`}
                            {...form.register(`lines.${index}.defect_details`)}
                          />
                          <Popover>
                            <PopoverTrigger asChild>
                              <Button
                                type="button"
                                size="sm"
                                variant="ghost"
                                aria-label={t("qc.quality.defectCodes.title")}
                                title={t("qc.quality.defectCodes.title")}
                              >
                                <Tags className="h-3.5 w-3.5" />
                              </Button>
                            </PopoverTrigger>
                            <PopoverContent className="w-72 space-y-3">
                              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                                {t("qc.quality.defectCodes.title")}
                              </p>
                              {DEFECT_CODES.map((section) => (
                                <div key={section.category} className="space-y-1.5">
                                  <p className="text-xs font-medium text-muted-foreground">
                                    {t(section.category as TranslationKey)}
                                  </p>
                                  <div className="flex flex-wrap gap-1.5">
                                    {section.items.map((item) => (
                                      <Button
                                        key={item.key}
                                        type="button"
                                        size="sm"
                                        variant="outline"
                                        className="text-xs"
                                        onClick={() => addDefectCode(index, t(item.label as TranslationKey))}
                                      >
                                        {t(item.label as TranslationKey)}
                                      </Button>
                                    ))}
                                  </div>
                                </div>
                              ))}
                            </PopoverContent>
                          </Popover>
                        </div>
                        {errors?.defect_details && (
                          <p className="mt-1 text-xs text-destructive">{t("qc.quality.help.defectDetails")}</p>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
        {lines.length > 0 && <p className="text-xs text-muted-foreground">{t("qc.quality.help.defectDetails")}</p>}
      </section>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="comments">{t("qc.quality.field.comments")}</Label>
          <Input id="comments" {...form.register("comments")} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="corrective_action">{t("qc.quality.field.correctiveAction")}</Label>
          <Input id="corrective_action" {...form.register("corrective_action")} />
        </div>
      </div>
    </div>
  );
}

/**
 * Contrôle des paramètres: the nine instrument groups of the paper sheet, each
 * a list of readings. Entries are saved (and deleted) one at a time straight
 * against the backend -- they are not part of the report form's Save, so the
 * section works the same whether it sits in the edit form or the read-only view.
 */
function QualityParametersSection({ reportId, editable }: { reportId: string; editable: boolean }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());

  const { data: entries = [], isLoading } = useQuery({
    queryKey: parametersQueryKey(reportId),
    queryFn: () => listParameters(token, reportId),
  });

  function toggle(key: string) {
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <section className="space-y-2">
      <div className="flex items-center gap-1.5">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t("qc.quality.params.title")}
        </p>
        <HelpTooltip text={t("qc.quality.params.help")} />
      </div>
      {isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : (
        <div className="divide-y divide-border rounded-lg border border-border">
          {PARAMETER_GROUPS.map((group) => {
            const groupEntries = entries.filter((entry) => entry.group_key === group.key);
            // A read-only report only lists the groups someone actually filled.
            if (!editable && groupEntries.length === 0) return null;
            const isOpen = openGroups.has(group.key);
            return (
              <div key={group.key}>
                <button
                  type="button"
                  onClick={() => toggle(group.key)}
                  aria-expanded={isOpen}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-muted/40"
                >
                  {isOpen ? (
                    <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                  )}
                  <span className="font-medium">{t(`qc.quality.params.group.${group.key}` as TranslationKey)}</span>
                  <span className="ml-auto text-xs tabular-nums text-muted-foreground">{groupEntries.length}</span>
                </button>
                <AnimatePresence initial={false}>
                  {isOpen && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.2, ease: "easeOut" }}
                      className="overflow-hidden"
                    >
                      <ParameterGroupTable
                        reportId={reportId}
                        group={group}
                        entries={groupEntries}
                        editable={editable}
                      />
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          })}
          {!editable && entries.length === 0 && (
            <p className="p-3 text-sm text-muted-foreground">{t("qc.quality.params.empty")}</p>
          )}
        </div>
      )}
    </section>
  );
}

function ParameterGroupTable({
  reportId,
  group,
  entries,
  editable,
}: {
  reportId: string;
  group: ParameterGroup;
  entries: ParameterEntry[];
  editable: boolean;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const emptyDraft = () => ({ label: "", fields: {} as Record<string, string> });
  const [draft, setDraft] = useState(emptyDraft);

  const saveMutation = useMutation({
    mutationFn: () => {
      const fields: Record<string, number | string | null> = {};
      for (const field of group.fields) {
        const value = parameterValue(draft.fields[field] ?? "");
        if (value !== undefined) fields[field] = value;
      }
      return saveParameterEntry(token, reportId, {
        group_key: group.key,
        entry_label: draft.label.trim() || null,
        fields,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: parametersQueryKey(reportId) });
      setDraft(emptyDraft());
    },
    onError: (error) => {
      toast.error(t("qc.quality.params.saveError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (entryId: string) => deleteParameterEntry(token, reportId, entryId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: parametersQueryKey(reportId) });
    },
    onError: (error) => {
      toast.error(t("qc.quality.params.deleteError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const draftIsEmpty = !draft.label.trim() && group.fields.every((field) => !(draft.fields[field] ?? "").trim());
  // The add row sits inside the report's edit <form>; Enter adds the entry
  // instead of submitting the whole report.
  const onDraftKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    if (!draftIsEmpty && !saveMutation.isPending) saveMutation.mutate();
  };
  const entryLabelHeader = t(`qc.quality.params.entryLabel.${group.entryLabel}` as TranslationKey);
  const fieldHeader = (field: string) => t(`qc.quality.params.field.${field}` as TranslationKey);

  return (
    <div className="border-t border-border bg-muted/20">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="whitespace-nowrap px-2 normal-case">{entryLabelHeader}</TableHead>
            {group.fields.map((field) => (
              <TableHead key={field} className="whitespace-nowrap px-2 normal-case">
                {fieldHeader(field)}
              </TableHead>
            ))}
            {editable && <TableHead className="w-10 px-2" />}
          </TableRow>
        </TableHeader>
        <TableBody>
          {entries.map((entry) => (
            <TableRow key={entry.id}>
              <TableCell className="whitespace-nowrap px-2 py-1.5 font-medium">{entry.entry_label || "—"}</TableCell>
              {group.fields.map((field) => {
                const value = entry.fields[field];
                return (
                  <TableCell key={field} className="whitespace-nowrap px-2 py-1.5 tabular-nums">
                    {value === null || value === undefined || value === "" ? "—" : String(value)}
                  </TableCell>
                );
              })}
              {editable && (
                <TableCell className="px-2 py-1.5 text-right">
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    aria-label={t("common.delete")}
                    disabled={deleteMutation.isPending && deleteMutation.variables === entry.id}
                    onClick={() => deleteMutation.mutate(entry.id)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </TableCell>
              )}
            </TableRow>
          ))}
          {editable && (
            <TableRow className="hover:bg-transparent">
              <TableCell className="min-w-[6rem] px-2 py-1.5">
                <Input
                  type={group.entryLabel === "time" ? "time" : "text"}
                  aria-label={entryLabelHeader}
                  value={draft.label}
                  onChange={(event) => setDraft((prev) => ({ ...prev, label: event.target.value }))}
                  onKeyDown={onDraftKeyDown}
                />
              </TableCell>
              {group.fields.map((field) => (
                <TableCell key={field} className="min-w-[5.5rem] px-2 py-1.5">
                  <Input
                    aria-label={fieldHeader(field)}
                    value={draft.fields[field] ?? ""}
                    onChange={(event) =>
                      setDraft((prev) => ({ ...prev, fields: { ...prev.fields, [field]: event.target.value } }))
                    }
                    onKeyDown={onDraftKeyDown}
                  />
                </TableCell>
              ))}
              <TableCell className="px-2 py-1.5 text-right">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  aria-label={t("qc.quality.params.addEntry")}
                  title={t("qc.quality.params.addEntry")}
                  disabled={draftIsEmpty || saveMutation.isPending}
                  onClick={() => saveMutation.mutate()}
                >
                  <Plus className="h-3.5 w-3.5" />
                </Button>
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      {editable && entries.length === 0 && (
        <p className="px-3 pb-2 text-xs text-muted-foreground">{t("qc.quality.params.addHint")}</p>
      )}
    </div>
  );
}

/**
 * Per-row actions. Edit/History/Delete all jump into the same detail dialog
 * used when a row itself is clicked (see `QualityReportDialog` above) — that
 * dialog already knows how each status behaves, so the row buttons only need
 * to say which tab to land on, not re-implement any of that.
 */
function QualityRowActions({
  report,
  onOpenReport,
  onSubmitReport,
  isSubmitting,
  onReviseReport,
  isResubmitting,
}: {
  report: QualityReport;
  onOpenReport: (mode: "edit" | "history" | "delete") => void;
  onSubmitReport: () => void;
  isSubmitting: boolean;
  onReviseReport: () => void;
  isResubmitting: boolean;
}) {
  const { t } = useI18n();

  return (
    <div className="flex justify-end items-center gap-1">
      {report.status === "rejected" && report.rejection_reason && (
        <span className="mr-1 text-xs text-destructive">{report.rejection_reason}</span>
      )}
      <Button
        size="sm"
        variant="ghost"
        aria-label={t("common.edit")}
        onClick={() => (report.status === "rejected" ? onReviseReport() : onOpenReport("edit"))}
        disabled={report.status === "rejected" && isResubmitting}
      >
        <Pencil className="h-3.5 w-3.5" />
      </Button>
      {report.status === "draft" && (
        <Button size="sm" variant="outline" onClick={onSubmitReport} disabled={isSubmitting}>
          <Send className="h-3.5 w-3.5" />
          {isSubmitting ? t("production.reports.submitting") : t("production.reports.submit")}
        </Button>
      )}
      {report.status === "rejected" && (
        <Button size="sm" variant="outline" onClick={onReviseReport} disabled={isResubmitting}>
          <Send className="h-3.5 w-3.5" />
          {isResubmitting ? t("production.reports.resubmitting") : t("production.reports.resubmit")}
        </Button>
      )}
      <Button
        size="sm"
        variant="ghost"
        aria-label={t("production.reports.history.title")}
        onClick={() => onOpenReport("history")}
      >
        <History className="h-3.5 w-3.5" />
      </Button>
      <Button size="sm" variant="ghost" aria-label={t("common.delete")} onClick={() => onOpenReport("delete")}>
        <Trash2 className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}
