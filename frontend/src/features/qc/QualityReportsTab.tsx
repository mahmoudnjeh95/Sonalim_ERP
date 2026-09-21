import { useEffect, useRef, useState, type ReactNode } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  CalendarClock,
  FlaskConical,
  History,
  Pencil,
  Plus,
  Send,
  ShieldAlert,
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
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
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
import { listProducts, listWorkOrders } from "../production/api";
import { listLocations, listUoms } from "../warehouse/api";
import { ReportDetailDialog, type FigureRow } from "../production/ReportDetailDialog";
import { NonConformityDetailDialog } from "./NonConformityDetailDialog";
import {
  adminUpdateQualityReport,
  createQualityReport,
  deleteQualityReport,
  getQualityReport,
  listFollowUps,
  listInspectableConditionnementReports,
  listNonConformities,
  listQualityReports,
  raiseNonConformity,
  reviseQualityReport,
  submitQualityReport,
  updateQualityReport,
  type InspectableConditionnementReport,
  type NonConformity,
  type NonConformitySeverity,
  type QualityReport,
  type QualityReportDetail,
  type QualityReportStatus,
} from "./api";
import { AppLoader } from "../../components/patterns/AppLoader";

const detailSchema = z.object({
  pre_dryer_index: z.coerce.number().min(0).optional(),
  humidity_percentage: z.coerce.number().min(0).max(100).optional(),
  cooling_index: z.coerce.number().min(0).optional(),
  pf_index: z.coerce.number().min(0).optional(),
  sumo_index: z.coerce.number().min(0).optional(),
  conforming_cartons: z.coerce.number().min(0).int("Must be a whole number"),
  non_conforming_cartons: z.coerce.number().min(0).int("Must be a whole number"),
  defect_details: z.string().optional(),
  comments: z.string().optional(),
  corrective_action: z.string().optional(),
});

const createSchema = detailSchema.extend({
  conditionnement_report_id: z.string().min(1, "Required"),
});
type CreateForm = z.infer<typeof createSchema>;

const QUERY_KEY = ["qc", "quality-reports"] as const;
const FOLLOW_UPS_QUERY_KEY = ["qc", "follow-ups"] as const;
const WORK_ORDERS_QUERY_KEY = ["production", "work-orders"] as const;
const INSPECTABLE_QUERY_KEY = ["qc", "conditionnement-reports"] as const;

function conditionnementLabel(
  row: InspectableConditionnementReport,
  referenceOf: (ofId: string) => string,
  t: (key: TranslationKey) => string,
): string {
  return [referenceOf(row.of_id), row.report_date, row.shift, row.team, t(`status.${row.status}` as TranslationKey)]
    .filter(Boolean)
    .join(" · ");
}

type StatusFilter = "all" | QualityReportStatus;
type GroupByOption = "none" | "of" | "shift";

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

const EMPTY_DETAIL = {
  pre_dryer_index: undefined,
  humidity_percentage: undefined,
  cooling_index: undefined,
  pf_index: undefined,
  sumo_index: undefined,
  conforming_cartons: 0,
  non_conforming_cartons: 0,
  defect_details: "",
  comments: "",
  corrective_action: "",
};

function toDetail(input: CreateForm): Partial<QualityReportDetail> {
  return {
    pre_dryer_index: input.pre_dryer_index,
    humidity_percentage: input.humidity_percentage,
    cooling_index: input.cooling_index,
    pf_index: input.pf_index,
    sumo_index: input.sumo_index,
    conforming_cartons: input.conforming_cartons,
    non_conforming_cartons: input.non_conforming_cartons,
    defect_details: input.defect_details || undefined,
    comments: input.comments || undefined,
    corrective_action: input.corrective_action || undefined,
  } as Partial<QualityReportDetail>;
}

export function QualityReportsTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  // QC validates one packaging run at a time, so seeing every quality report
  // for the same OF together — instead of interleaved by submission date — is
  // the default: it's what makes a repeat non-conformity on one order visible
  // at a glance.
  const [groupBy, setGroupBy] = useState<GroupByOption>("of");
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
  const { data: workOrders = [] } = useQuery({
    queryKey: WORK_ORDERS_QUERY_KEY,
    queryFn: () => listWorkOrders(token),
  });
  const { data: products = [] } = useQuery({
    queryKey: ["core", "products"],
    queryFn: () => listProducts(token),
  });
  // A carton tier is a property of the product, not of one run of it -- so the
  // "cartons" the rapport counts should read "sacs" for a product with no
  // packets_per_carton (a sac is its own sellable unit, see packaging_estimate.py).
  const packetsPerCartonForOf = (ofId: string | undefined): number | null => {
    const productId = ofId ? workOrders.find((o) => o.id === ofId)?.product_id : undefined;
    const product = productId ? products.find((p) => p.id === productId) : undefined;
    return product?.packets_per_carton && product.packets_per_carton > 0 ? product.packets_per_carton : null;
  };
  // Conditionnement reports not yet inspected, enriched with the hint figures
  // (packets, cartons, regrind) shown once one is picked. QC always inspects a
  // specific packaging run -- never just "an OF" -- so this backs the create
  // form's only selector.
  const { data: inspectable = [] } = useQuery({
    queryKey: INSPECTABLE_QUERY_KEY,
    queryFn: () => listInspectableConditionnementReports(token),
  });

  // Quality outlives production, so a closed OF is still a legitimate target.
  const referenceOf = (ofId: string) => workOrders.find((o) => o.id === ofId)?.reference ?? ofId;
  // A link may name a report that no longer exists; a miss opens nothing rather
  // than an empty dialog.
  const focusedReport = openReport ?? reports.find((r) => r.id === linkedId) ?? null;

  const form = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    defaultValues: { conditionnement_report_id: "", ...EMPTY_DETAIL },
  });
  const selectedConditionnementId = form.watch("conditionnement_report_id");
  const selectedConditionnement = inspectable.find((r) => r.conditionnement_report_id === selectedConditionnementId);

  const createMutation = useMutation({
    mutationFn: (input: CreateForm) =>
      createQualityReport(token, {
        conditionnement_report_id: input.conditionnement_report_id,
        detail: toDetail(input),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: INSPECTABLE_QUERY_KEY });
      setDialogOpen(false);
      form.reset({ conditionnement_report_id: "", ...EMPTY_DETAIL });
      toast.success(t("qc.quality.created"));
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
    { key: "of", kind: "text", getValue: (r) => referenceOf(r.of_id) },
    { key: "date", kind: "text", getValue: (r) => r.report_date },
    { key: "shift", kind: "text", getValue: (r) => r.shift },
  ];
  const columnFilters = useColumnFilters<QualityReport>(filterFields);
  const visible = columnFilters.apply(
    statusFilter === "all" ? reports : reports.filter((r) => r.status === statusFilter),
  );

  const columns: ColumnDef<QualityReport>[] = [
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
      : groupBy === "of"
        ? { key: "of", label: t("production.reports.groupBy.of"), getGroupKey: (r) => r.of_id, getGroupLabel: (r) => referenceOf(r.of_id) }
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
                  { value: "of", label: t("production.reports.groupBy.of") },
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
                    <div className="grid grid-cols-1 gap-3">
                      <div className="space-y-1.5">
                        <Label htmlFor="q_conditionnement_report_id">
                          {t("qc.quality.field.conditionnementReport")}
                        </Label>
                        <Select id="q_conditionnement_report_id" {...form.register("conditionnement_report_id")}>
                          <option value="">—</option>
                          {inspectable.map((row) => (
                            <option key={row.conditionnement_report_id} value={row.conditionnement_report_id}>
                              {conditionnementLabel(row, referenceOf, t)}
                            </option>
                          ))}
                        </Select>
                        {form.formState.errors.conditionnement_report_id && (
                          <p className="text-sm text-destructive">
                            {form.formState.errors.conditionnement_report_id.message}
                          </p>
                        )}
                      </div>
                      {selectedConditionnement && (
                        <div className="rounded-md border border-border bg-muted/30 p-3">
                          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                            {t("qc.quality.hint.title")}
                          </p>
                          <div className="grid grid-cols-3 gap-2 text-sm">
                            <div>
                              <span className="text-muted-foreground">{t("qc.quality.hint.packets")}: </span>
                              {selectedConditionnement.packets_counted}
                            </div>
                            <div>
                              <span className="text-muted-foreground">{t("qc.quality.hint.cartons")}: </span>
                              {selectedConditionnement.carton_quantity}
                            </div>
                            <div>
                              <span className="text-muted-foreground">{t("qc.quality.hint.regrind")}: </span>
                              {selectedConditionnement.regrind_quantity ?? t("qc.quality.hint.regrindUnavailable")}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                    <QualityDetailFields form={form} isSac={!packetsPerCartonForOf(selectedConditionnement?.of_id)} />
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
          reference={referenceOf(focusedReport.of_id)}
          packetsPerCarton={packetsPerCartonForOf(focusedReport.of_id)}
          productId={workOrders.find((o) => o.id === focusedReport.of_id)?.product_id ?? undefined}
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
 * straight edit; what a validated report *does* hold is its follow-up window,
 * which the backend takes away with the report when it is deleted.
 */
export function QualityReportDialog({
  report,
  reference,
  packetsPerCarton,
  productId,
  initialMode,
  autoResubmit,
  onClose,
}: {
  report: QualityReport;
  reference: string;
  packetsPerCarton: number | null;
  productId?: string;
  initialMode?: "view" | "edit" | "history" | "delete";
  autoResubmit?: boolean;
  onClose: () => void;
}) {
  const isSac = !packetsPerCarton;
  const { session } = useAuth();
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
  const detail = full?.detail as QualityReportDetail | undefined;

  // A report's own defect count says whether an NC belongs to it; the
  // non-conformities list is fetched by OF (the only filter the backend
  // offers) and narrowed to this report client-side.
  const { data: ofNonConformities = [] } = useQuery({
    queryKey: ["qc", "non-conformities", "of", report.of_id],
    queryFn: () => listNonConformities(token, { of_id: report.of_id }),
  });
  const linkedNonConformities = ofNonConformities.filter((n) => n.quality_report_id === report.id);
  const hasDefects = Number(detail?.non_conforming_cartons ?? 0) > 0;

  // Reference data the linked-NC dialog needs — a plain useQuery, so it's a
  // cache hit (no extra request) wherever the page that opened this dialog
  // already loaded the same lists.
  const { data: ncProducts = [] } = useQuery({ queryKey: ["core", "products"], queryFn: () => listProducts(token) });
  const { data: ncUoms = [] } = useQuery({ queryKey: ["core", "uoms"], queryFn: () => listUoms(token) });
  const { data: ncLocations = [] } = useQuery({ queryKey: ["warehouse", "locations"], queryFn: () => listLocations(token) });

  const form = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    values: {
      conditionnement_report_id: report.conditionnement_report_id ?? "",
      ...EMPTY_DETAIL,
      ...(detail ?? {}),
      defect_details: detail?.defect_details ?? "",
      comments: detail?.comments ?? "",
      corrective_action: detail?.corrective_action ?? "",
    } as CreateForm,
  });

  function invalidate() {
    for (const key of [QUERY_KEY, ["qc", "quality-reports", report.id], FOLLOW_UPS_QUERY_KEY]) {
      queryClient.invalidateQueries({ queryKey: key });
    }
  }

  const saveMutation = useMutation({
    mutationFn: async (input: CreateForm) => {
      const updated =
        report.status === "draft"
          ? await updateQualityReport(token, report.id, toDetail(input))
          : await adminUpdateQualityReport(token, report.id, { detail: toDetail(input), reason });

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

  const figures: FigureRow[] = [
    { label: t("qc.quality.field.preDryer"), value: detail?.pre_dryer_index },
    { label: t("qc.quality.field.humidity"), value: detail?.humidity_percentage, unit: "%" },
    { label: t("qc.quality.field.cooling"), value: detail?.cooling_index },
    { label: t("qc.quality.field.pf"), value: detail?.pf_index },
    { label: t("qc.quality.field.sumo"), value: detail?.sumo_index },
    {
      label: t(isSac ? "qc.quality.field.conformingSacs" : "qc.quality.field.conforming"),
      value: detail?.conforming_cartons,
      unit: t(isSac ? "qc.quality.unit.sacs" : "qc.quality.unit.cartons"),
    },
    {
      label: t(isSac ? "qc.quality.field.nonConformingSacs" : "qc.quality.field.nonConforming"),
      value: detail?.non_conforming_cartons,
      unit: t(isSac ? "qc.quality.unit.sacs" : "qc.quality.unit.cartons"),
    },
    { label: t("qc.quality.field.defectDetails"), value: detail?.defect_details ?? "\u2014" },
    { label: t("qc.quality.field.comments"), value: detail?.comments ?? "\u2014" },
    { label: t("qc.quality.field.correctiveAction"), value: detail?.corrective_action ?? "\u2014" },
  ];

  const needsReason = report.status !== "draft";

  return (
    <>
    <ReportDetailDialog
      open
      onOpenChange={(next) => !next && onClose()}
      title={`${reference} \u00b7 ${report.report_date}`}
      subtitle={[report.shift, report.team].filter(Boolean).join(" \u00b7 ") || t("common.none")}
      status={report.status}
      revision={report.revision}
      reportId={report.id}
      historyEntityType="quality_report"
      figures={figures}
      banner={
        hasDefects ? (
          linkedNonConformities.length > 0 ? (
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
          ) : (
            <RaiseNcFromReportBanner report={report} detail={detail} productId={productId} />
          )
        ) : undefined
      }
      initialMode={initialMode}
      onDelete={async (deleteReason) => {
        await deleteQualityReport(token, report.id, deleteReason);
        invalidate();
      }}
      editForm={
        <form className="space-y-4" onSubmit={form.handleSubmit((input) => saveMutation.mutate(input))}>
          <QualityDetailFields form={form} isSac={isSac} />
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
            disabled={saveMutation.isPending || (needsReason && !reason.trim())}
          >
            {saveMutation.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      }
    />
    {openLinkedNc && (
      <NonConformityDetailDialog
        nonConformity={openLinkedNc}
        ofReference={reference}
        products={ncProducts}
        uoms={ncUoms}
        locations={ncLocations}
        onClose={() => setOpenLinkedNc(null)}
      />
    )}
    </>
  );
}

/**
 * A validated report can carry non-conforming cartons with no non-conformity
 * ticket ever raised for them — the only automatic path is the Validation
 * Center's reject step, which is unavailable once the report is already
 * validated. This lets someone raise one after the fact, straight from the
 * report they found the defect on, pre-filled and linked via
 * `quality_report_id` so it shows up back here next time.
 */
function RaiseNcFromReportBanner({
  report,
  detail,
  productId,
}: {
  report: QualityReport;
  detail: QualityReportDetail | undefined;
  productId: string | undefined;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [sourceLocationId, setSourceLocationId] = useState("");
  const [quarantineLocationId, setQuarantineLocationId] = useState("");
  const [defectType, setDefectType] = useState(detail?.defect_details ?? "");
  const [severity, setSeverity] = useState<NonConformitySeverity>("minor");

  const { data: products = [] } = useQuery({ queryKey: ["core", "products"], queryFn: () => listProducts(token) });
  const { data: locations = [] } = useQuery({ queryKey: ["warehouse", "locations"], queryFn: () => listLocations(token) });
  const { data: uoms = [] } = useQuery({ queryKey: ["core", "uoms"], queryFn: () => listUoms(token) });
  const blockedLocations = locations.filter((l) => l.is_blocked);

  const product = products.find((p) => p.id === productId);
  const packetsPerCarton = product?.packets_per_carton && product.packets_per_carton > 0 ? product.packets_per_carton : null;
  const cartonCount = Number(detail?.non_conforming_cartons ?? 0);
  const quantity = packetsPerCarton ? cartonCount * packetsPerCarton : cartonCount;
  const unit = productUnit(productId, products, uoms);

  const raiseMutation = useMutation({
    mutationFn: () =>
      raiseNonConformity(token, {
        of_id: report.of_id,
        product_id: productId!,
        quantity,
        source_location_id: sourceLocationId,
        quarantine_location_id: quarantineLocationId,
        defect_type: defectType || "Non-conformity",
        severity,
        quality_report_id: report.id,
        description: detail?.comments || undefined,
        correlation_id: crypto.randomUUID(),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["qc", "non-conformities"] });
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
        <p className="text-sm text-warning">{t("qc.quality.nc.noneYet")}</p>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm" variant="outline" disabled={!productId}>
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

function QualityDetailFields({
  form,
  isSac = false,
}: {
  form: ReturnType<typeof useForm<CreateForm>>;
  isSac?: boolean;
}) {
  const { t } = useI18n();
  const defectDetails = form.watch("defect_details") ?? "";

  const addDefectCode = (label: string) => {
    const current = defectDetails.trim();
    const newText = current ? `${current}; ${label}` : label;
    form.setValue("defect_details", newText);
  };

  return (
    <div className="space-y-4">
      <section className="space-y-2">
        <div className="flex items-center gap-1.5">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t("qc.quality.section.indices")}
          </p>
          <HelpTooltip text={t("qc.quality.help.indices")} />
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="space-y-1.5">
            <Label htmlFor="pre_dryer_index">{t("qc.quality.field.preDryer")}</Label>
            <Input id="pre_dryer_index" type="number" step="any" {...form.register("pre_dryer_index")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="humidity_percentage">{t("qc.quality.field.humidity")} (%)</Label>
            <Input id="humidity_percentage" type="number" step="any" {...form.register("humidity_percentage")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="cooling_index">{t("qc.quality.field.cooling")}</Label>
            <Input id="cooling_index" type="number" step="any" {...form.register("cooling_index")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pf_index">{t("qc.quality.field.pf")}</Label>
            <Input id="pf_index" type="number" step="any" {...form.register("pf_index")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sumo_index">{t("qc.quality.field.sumo")}</Label>
            <Input id="sumo_index" type="number" step="any" {...form.register("sumo_index")} />
          </div>
        </div>
      </section>

      <section className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t("qc.quality.section.conformity")}
        </p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="conforming_cartons">
              {t(isSac ? "qc.quality.field.conformingSacs" : "qc.quality.field.conforming")} (
              {t(isSac ? "qc.quality.unit.sacs" : "qc.quality.unit.cartons")})
            </Label>
            <Input id="conforming_cartons" type="number" step="1" {...form.register("conforming_cartons")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="non_conforming_cartons">
              {t(isSac ? "qc.quality.field.nonConformingSacs" : "qc.quality.field.nonConforming")} (
              {t(isSac ? "qc.quality.unit.sacs" : "qc.quality.unit.cartons")})
            </Label>
            <Input id="non_conforming_cartons" type="number" step="1" {...form.register("non_conforming_cartons")} />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="defect_details">{t("qc.quality.field.defectDetails")}</Label>
            <Input id="defect_details" {...form.register("defect_details")} />
            <p className="text-xs text-muted-foreground">{t("qc.quality.help.defectDetails")}</p>
          </div>

          <div className="space-y-1.5 sm:col-span-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {t("qc.quality.defectCodes.title")}
            </p>
            <div className="space-y-3">
              {DEFECT_CODES.map((section) => (
                <div key={section.category} className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground">{t(section.category as TranslationKey)}</p>
                  <div className="flex flex-wrap gap-2">
                    {section.items.map((item) => (
                      <Button
                        key={item.key}
                        type="button"
                        size="sm"
                        variant="outline"
                        className="text-xs"
                        onClick={() => addDefectCode(t(item.label as TranslationKey))}
                      >
                        {t(item.label as TranslationKey)}
                      </Button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="comments">{t("qc.quality.field.comments")}</Label>
            <Input id="comments" {...form.register("comments")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="corrective_action">{t("qc.quality.field.correctiveAction")}</Label>
            <Input id="corrective_action" {...form.register("corrective_action")} />
          </div>
        </div>
      </section>
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
