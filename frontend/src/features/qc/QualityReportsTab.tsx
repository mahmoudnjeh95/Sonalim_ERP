import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { CalendarClock, FlaskConical, Pencil, Plus, Send } from "lucide-react";
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
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { listWorkOrders } from "../production/api";
import { ReportDetailDialog, type FigureRow } from "../production/ReportDetailDialog";
import {
  adminUpdateQualityReport,
  createQualityReport,
  deleteQualityReport,
  getQualityReport,
  listFollowUps,
  listQualityReports,
  submitQualityReport,
  updateQualityReport,
  type QualityReport,
  type QualityReportDetail,
  type QualityReportStatus,
} from "./api";

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
  of_id: z.string().min(1, "Required"),
  report_date: z.string().min(1, "Required"),
  team: z.string().optional(),
  shift: z.string().optional(),
});
type CreateForm = z.infer<typeof createSchema>;

const QUERY_KEY = ["qc", "quality-reports"] as const;
const FOLLOW_UPS_QUERY_KEY = ["qc", "follow-ups"] as const;
const WORK_ORDERS_QUERY_KEY = ["production", "work-orders"] as const;

type StatusFilter = "all" | QualityReportStatus;

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

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

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
  const [editingId, setEditingId] = useState<string | null>(null);
  const [openReport, setOpenReport] = useState<QualityReport | null>(null);
  // Which report is open lives in the URL as well as in state, so an OF's
  // quality panel can link straight to one instead of landing on the list.
  const [searchParams, setSearchParams] = useSearchParams();
  const linkedId = searchParams.get("report");

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

  // Quality outlives production, so a closed OF is still a legitimate target.
  const referenceOf = (ofId: string) => workOrders.find((o) => o.id === ofId)?.reference ?? ofId;
  // A link may name a report that no longer exists; a miss opens nothing rather
  // than an empty dialog.
  const focusedReport = openReport ?? reports.find((r) => r.id === linkedId) ?? null;

  const form = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    defaultValues: { of_id: "", report_date: todayIso(), team: "", shift: "", ...EMPTY_DETAIL },
  });

  const createMutation = useMutation({
    mutationFn: (input: CreateForm) =>
      createQualityReport(token, {
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
          isEditing={editingId === r.id}
          onOpenEdit={(open) => setEditingId(open ? r.id : null)}
          onSubmitReport={() => submitMutation.mutate(r.id)}
          isSubmitting={submitMutation.isPending && submitMutation.variables === r.id}
        />
      ),
    },
  ];
  const table = useTableColumns("qc.qualityReports", columns);
  const sortedVisible = table.sortRows(visible);

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
                  <Button size="sm" disabled={workOrders.length === 0}>
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
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      <div className="space-y-1.5">
                        <Label htmlFor="q_of_id">{t("production.reports.field.of")}</Label>
                        <Select id="q_of_id" {...form.register("of_id")}>
                          <option value="">—</option>
                          {workOrders.map((o) => (
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
                        <Label htmlFor="q_report_date">{t("production.reports.field.date")}</Label>
                        <Input id="q_report_date" type="date" {...form.register("report_date")} />
                      </div>
                      <ShiftTeamFields
                        idPrefix="q_"
                        teamField={form.register("team")}
                        shiftField={form.register("shift")}
                      />
                    </div>
                    <QualityDetailFields form={form} />
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
            <div className="space-y-2 p-6">
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
            </div>
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
                  {sortedVisible.map((report) => (
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
        <QualityReportDialog
          report={focusedReport}
          reference={referenceOf(focusedReport.of_id)}
          onClose={() => {
            setOpenReport(null);
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
function QualityReportDialog({
  report,
  reference,
  onClose,
}: {
  report: QualityReport;
  reference: string;
  onClose: () => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");

  const { data: full } = useQuery({
    queryKey: ["qc", "quality-reports", report.id],
    queryFn: () => getQualityReport(token, report.id),
  });
  const detail = full?.detail as QualityReportDetail | undefined;

  const form = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    values: {
      of_id: report.of_id,
      report_date: report.report_date,
      team: report.team ?? "",
      shift: report.shift ?? "",
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
    mutationFn: (input: CreateForm) =>
      report.status === "draft"
        ? updateQualityReport(token, report.id, toDetail(input))
        : adminUpdateQualityReport(token, report.id, { detail: toDetail(input), reason }),
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

  const figures: FigureRow[] = [
    { label: t("qc.quality.field.preDryer"), value: detail?.pre_dryer_index },
    { label: t("qc.quality.field.humidity"), value: detail?.humidity_percentage, unit: "%" },
    { label: t("qc.quality.field.cooling"), value: detail?.cooling_index },
    { label: t("qc.quality.field.pf"), value: detail?.pf_index },
    { label: t("qc.quality.field.sumo"), value: detail?.sumo_index },
    { label: t("qc.quality.field.conforming"), value: detail?.conforming_cartons, unit: t("qc.quality.unit.cartons") },
    {
      label: t("qc.quality.field.nonConforming"),
      value: detail?.non_conforming_cartons,
      unit: t("qc.quality.unit.cartons"),
    },
    { label: t("qc.quality.field.defectDetails"), value: detail?.defect_details ?? "\u2014" },
    { label: t("qc.quality.field.comments"), value: detail?.comments ?? "\u2014" },
    { label: t("qc.quality.field.correctiveAction"), value: detail?.corrective_action ?? "\u2014" },
  ];

  const needsReason = report.status !== "draft";

  return (
    <ReportDetailDialog
      open
      onOpenChange={(next) => !next && onClose()}
      title={`${reference} \u00b7 ${report.report_date}`}
      subtitle={[report.shift, report.team].filter(Boolean).join(" \u00b7 ") || t("common.none")}
      status={report.status}
      revision={report.revision}
      figures={figures}
      onDelete={async (deleteReason) => {
        await deleteQualityReport(token, report.id, deleteReason);
        invalidate();
      }}
      editForm={
        <form className="space-y-4" onSubmit={form.handleSubmit((input) => saveMutation.mutate(input))}>
          <QualityDetailFields form={form} />
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
  );
}

function QualityDetailFields({ form }: { form: ReturnType<typeof useForm<CreateForm>> }) {
  const { t } = useI18n();
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
              {t("qc.quality.field.conforming")} ({t("qc.quality.unit.cartons")})
            </Label>
            <Input id="conforming_cartons" type="number" step="1" {...form.register("conforming_cartons")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="non_conforming_cartons">
              {t("qc.quality.field.nonConforming")} ({t("qc.quality.unit.cartons")})
            </Label>
            <Input id="non_conforming_cartons" type="number" step="1" {...form.register("non_conforming_cartons")} />
          </div>
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="defect_details">{t("qc.quality.field.defectDetails")}</Label>
            <Input id="defect_details" {...form.register("defect_details")} />
            <p className="text-xs text-muted-foreground">{t("qc.quality.help.defectDetails")}</p>
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

function QualityRowActions({
  report,
  isEditing,
  onOpenEdit,
  onSubmitReport,
  isSubmitting,
}: {
  report: QualityReport;
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
    queryKey: ["qc", "quality-reports", report.id],
    queryFn: () => getQualityReport(token, report.id),
    enabled: isEditing,
  });
  const detail = full?.detail as QualityReportDetail | undefined;

  const form = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    values: {
      of_id: report.of_id,
      report_date: report.report_date,
      ...EMPTY_DETAIL,
      ...(detail ?? {}),
      defect_details: detail?.defect_details ?? "",
      comments: detail?.comments ?? "",
      corrective_action: detail?.corrective_action ?? "",
    } as CreateForm,
  });

  const updateMutation = useMutation({
    mutationFn: (input: CreateForm) => updateQualityReport(token, report.id, toDetail(input)),
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
            <DialogContent className="max-w-2xl">
              <DialogHeader>
                <DialogTitle>{t("qc.quality.dialog.edit.title")}</DialogTitle>
                <DialogDescription>{t("production.dailyReports.dialog.edit.description")}</DialogDescription>
              </DialogHeader>
              <form className="space-y-4" onSubmit={form.handleSubmit((input) => updateMutation.mutate(input))}>
                <QualityDetailFields form={form} />
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
