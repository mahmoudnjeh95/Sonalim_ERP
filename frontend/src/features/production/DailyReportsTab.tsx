import { useEffect, useRef, useState, type ReactNode } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, ClipboardList, Droplets, Flame, History, Pencil, Plus, Send, Trash2, Wheat } from "lucide-react";
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
import {
  DowntimeLinesField,
  fromDowntimeLineForms,
  toDowntimeLineForms,
  type DowntimeLineForm,
} from "./DowntimeLinesField";
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
import { ReportDetailDialog, type FigureRow } from "./ReportDetailDialog";
import { OfConsolidationHint } from "./OfConsolidationHint";
import {
  correctDailyReport,
  correctValidatedDailyReport,
  createDailyReport,
  deleteReport,
  getReport,
  listMachines,
  listMolds,
  listProducts,
  listRegrindDefaults,
  listReports,
  listWorkOrders,
  reviseReport,
  submitReport,
  updateDailyReport,
  type DailyReportDetail,
  type Mold,
  type ProductionReport,
  type ReportStatus,
} from "./api";
import { listLocations, listUoms } from "../warehouse/api";
import { listPartners, type Partner } from "../partners/api";
import { UTILITY_UNITS, productUnit, totalsByUomCategory } from "../../lib/units";

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
        category: z.enum(["raw_material", "press", "pouring", "cross", "kneading", "finished_product_conditioning"]),
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
  fuel_supplier_id: z.string().optional(),
  // Gasoil (diesel) — a separate fuel from fuel_quantity (fioul).
  gasoil_quantity: z.coerce.number().min(0),
  gasoil_supplier_id: z.string().optional(),
  electricity_quantity: z.coerce.number().min(0),
  // Débit de semoule, tonnes/hour — recorded for future recipe statistics.
  semolina_flow_rate: z.coerce.number().min(0),
  // HH:MM from a native time input, or "" when not entered.
  start_time: z.string().optional(),
  production_minutes: z.coerce.number().int().min(0),
  // Arrêts. A list, so a shift can record more than one stoppage and more
  // than one reason -- see DowntimeLinesField.
  downtime_lines: z.array(
    z.object({
      motif: z.string(),
      minutes: z.coerce.number().int().min(0),
      note: z.string(),
    }),
  ),
});

const createSchema = detailSchema.extend({
  of_id: z.string().min(1, "Required"),
  report_date: z.string().min(1, "Required"),
  team: z.string().optional(),
  shift: z.string().optional(),
  // Which machine within the OF's line ran this shift. Optional here (a
  // draft may be saved before the team knows) but required to submit.
  equipment_id: z.string().optional(),
});
type CreateForm = z.infer<typeof createSchema>;

const QUERY_KEY = ["production", "reports", "daily"] as const;
const WORK_ORDERS_QUERY_KEY = ["production", "work-orders"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;
const UOMS_QUERY_KEY = ["core", "uoms"] as const;
const MOLDS_QUERY_KEY = ["production", "molds"] as const;
const PARTNERS_QUERY_KEY = ["core", "partners"] as const;
const MACHINES_QUERY_KEY = ["production", "machines", "all"] as const;
const REGRIND_DEFAULTS_QUERY_KEY = ["production", "regrind-defaults"] as const;

type StatusFilter = "all" | ReportStatus;
type GroupByOption = "none" | "of" | "team" | "shift";

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
  waste_lines: [] as WasteLineForm<"raw_material" | "press" | "pouring" | "cross" | "kneading" | "finished_product_conditioning">[],
  water_quantity: 0,
  water_percentage: 0,
  fuel_quantity: 0,
  fuel_supplier_id: "",
  gasoil_quantity: 0,
  gasoil_supplier_id: "",
  electricity_quantity: 0,
  semolina_flow_rate: 0,
  start_time: "",
  production_minutes: 0,
  downtime_lines: [] as DowntimeLineForm[],
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
  // Grouped by work order by default, matching the other report lists — it's
  // what makes every report for one OF findable at a glance.
  const [groupBy, setGroupBy] = useState<GroupByOption>("of");
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  // Only the first group starts open; re-collapse the rest each time the
  // grouping changes rather than only on first mount.
  const collapseInitializedFor = useRef<GroupByOption | null>(null);
  const [openReport, setOpenReport] = useState<ProductionReport | null>(null);
  const [openMode, setOpenMode] = useState<"view" | "edit" | "history" | "delete">("view");
  const [autoResubmit, setAutoResubmit] = useState(false);
  // Which report is open lives in the URL as well as in state, so the OF
  // details page can link straight to one instead of landing on the list.
  const [searchParams, setSearchParams] = useSearchParams();
  const linkedId = searchParams.get("report");
  function openReportAt(report: ProductionReport, mode: "view" | "edit" | "history" | "delete", options?: { autoResubmit?: boolean }) {
    setOpenReport(report);
    setOpenMode(mode);
    setAutoResubmit(options?.autoResubmit ?? false);
  }

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
  const { data: partners = [] } = useQuery({ queryKey: PARTNERS_QUERY_KEY, queryFn: () => listPartners(token) });
  const suppliers = partners.filter((p) => p.kind === "supplier" || p.kind === "both");
  // Tenant-wide: there is only ever one rebroyat product (see regrind_service.py),
  // so this is what regrind_product_id resolves to for every report — never a
  // per-shift choice among unrelated raw materials.
  const { data: regrindDefaults = [] } = useQuery({ queryKey: REGRIND_DEFAULTS_QUERY_KEY, queryFn: () => listRegrindDefaults(token) });
  const regrindOutputProductId = regrindDefaults.find((d) => d.input_product_id === null)?.output_product_id ?? null;
  // Tenant-wide, for resolving a report's equipment_id to a name in the table —
  // distinct from the create form's own line-scoped machines query below.
  const { data: allMachines = [] } = useQuery({ queryKey: MACHINES_QUERY_KEY, queryFn: () => listMachines(token) });
  const machineLabel = (machineId: string | null) => {
    if (!machineId) return "—";
    const machine = allMachines.find((m) => m.id === machineId);
    return machine ? `${machine.code} — ${machine.name}` : "—";
  };

  // Only orders that still accept reports — a closed or cancelled OF does not.
  const openWorkOrders = workOrders.filter((o) => ["planned", "ongoing", "suspended"].includes(o.status));
  const referenceOf = (ofId: string) => workOrders.find((o) => o.id === ofId)?.reference ?? ofId;

  const form = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    defaultValues: { of_id: "", report_date: todayIso(), team: "", shift: "", equipment_id: "", ...EMPTY_DETAIL },
  });

  // Machines the chosen OF's line can be attributed to — a line like Line_1_PL
  // can carry more than one at once, so the report must say which one it ran on.
  const selectedWorkCenterId = workOrders.find((o) => o.id === form.watch("of_id"))?.work_center_id;
  const { data: machines = [] } = useQuery({
    queryKey: ["production", "machines", selectedWorkCenterId],
    queryFn: () => listMachines(token, selectedWorkCenterId!),
    enabled: !!selectedWorkCenterId,
  });

  const createMutation = useMutation({
    mutationFn: (input: CreateForm) =>
      createDailyReport(token, {
        of_id: input.of_id,
        report_date: input.report_date,
        team: input.team || undefined,
        shift: input.shift || undefined,
        equipment_id: input.equipment_id || undefined,
        detail: toDetail(input),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setDialogOpen(false);
      form.reset({ of_id: "", report_date: todayIso(), team: "", shift: "", equipment_id: "", ...EMPTY_DETAIL });
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

  const reviseMutation = useMutation({
    mutationFn: (reportId: string) => reviseReport(token, reportId),
    onSuccess: (revised) => {
      openReportAt(revised, "edit", { autoResubmit: true });
    },
    onError: (error) => {
      toast.error(t("production.reports.resubmitError"), {
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
    { key: "machine", kind: "text", getValue: (r) => machineLabel(r.equipment_id) },
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
      key: "machine",
      header: t("production.reports.column.machine"),
      defaultWidth: 160,
      cell: (r) => <span className="text-muted-foreground">{machineLabel(r.equipment_id)}</span>,
      filterCell: {
        type: "text",
        placeholder: t("common.filter"),
        value: columnFilters.text.machine ?? "",
        onChange: (v) => columnFilters.setTextValue("machine", v),
      },
      sortValue: (r) => machineLabel(r.equipment_id),
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
          onOpenReport={(mode) => openReportAt(r, mode)}
          onSubmitReport={() => submitMutation.mutate(r.id)}
          isSubmitting={submitMutation.isPending && submitMutation.variables === r.id}
          onReviseReport={() => reviseMutation.mutate(r.id)}
          isResubmitting={reviseMutation.isPending && reviseMutation.variables === r.id}
        />
      ),
    },
  ];
  const table = useTableColumns("production.dailyReports", columns);
  const sortedReports = table.sortRows(visible);

  function toggleGroup(key: string) {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const groupSpec: GroupSpec<ProductionReport> | undefined =
    groupBy === "none"
      ? undefined
      : groupBy === "of"
        ? { key: "of", label: t("production.reports.groupBy.of"), getGroupKey: (r) => r.of_id, getGroupLabel: (r) => referenceOf(r.of_id) }
        : groupBy === "team"
          ? { key: "team", label: t("production.reports.groupBy.team"), getGroupKey: (r) => r.team ?? "", getGroupLabel: (r) => r.team || t("common.none") }
          : { key: "shift", label: t("production.reports.groupBy.shift"), getGroupKey: (r) => r.shift ?? "", getGroupLabel: (r) => r.shift || t("common.none") };
  const rowGroups = groupRows(sortedReports, groupSpec);

  useEffect(() => {
    if (groupBy === "none" || rowGroups.length === 0) return;
    if (collapseInitializedFor.current === groupBy) return;
    collapseInitializedFor.current = groupBy;
    setCollapsedGroups(new Set(rowGroups.slice(1).map((g) => g.key)));
  }, [groupBy, rowGroups]);

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
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">{t("production.reports.groupBy.label")}:</span>
              <FilterTabs
                options={[
                  { value: "none", label: t("production.reports.groupBy.none") },
                  { value: "of", label: t("production.reports.groupBy.of") },
                  { value: "team", label: t("production.reports.groupBy.team") },
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
                      <div className="space-y-1.5">
                        <Label htmlFor="equipment_id" className="flex items-center gap-1">
                          {t("production.reports.field.machine")}
                          <HelpTooltip text={t("production.reports.help.machine")} />
                        </Label>
                        <Select id="equipment_id" {...form.register("equipment_id")} disabled={!selectedWorkCenterId}>
                          <option value="">—</option>
                          {machines.map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.code} — {m.name}
                            </option>
                          ))}
                        </Select>
                      </div>
                    </div>

                    <OfConsolidationHint workOrderId={form.watch("of_id") || undefined} />

                    <DailyDetailFields
                      form={form}
                      products={products}
                      locations={locations}
                      uoms={uoms}
                      workOrders={workOrders}
                      molds={molds}
                      regrindOutputProductId={regrindOutputProductId}
                      suppliers={suppliers}
                    />

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
                  {rowGroups.flatMap((group) => {
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
                            layout
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            exit={{ opacity: 0 }}
                            className="cursor-pointer border-b border-border transition-colors hover:bg-muted/40"
                            onClick={() => openReportAt(report, "view")}
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
                          </motion.tr>,
                        );
                      }
                    }
                    return rows;
                  })}
                </AnimatePresence>
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {focusedReport && (
        <DailyReportDialog
          // Remount per report so a row's Edit/History/Delete action always
          // lands the dialog on the right tab instead of reusing whatever
          // tab a previous report was left on.
          key={focusedReport.id}
          report={focusedReport}
          reference={referenceOf(focusedReport.of_id)}
          products={products}
          locations={locations}
          uoms={uoms}
          workOrders={workOrders}
          molds={molds}
          regrindOutputProductId={regrindOutputProductId}
          suppliers={suppliers}
          initialMode={openMode}
          autoResubmit={autoResubmit}
          onClose={() => {
            setOpenReport(null);
            setOpenMode("view");
            setAutoResubmit(false);
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
export function DailyReportDialog({
  report,
  reference,
  products,
  locations,
  uoms,
  workOrders,
  molds,
  regrindOutputProductId,
  suppliers,
  initialMode,
  autoResubmit,
  onClose,
}: {
  report: ProductionReport;
  reference: string;
  products: { id: string; name: string; uom_id: string }[];
  locations: { id: string; name: string }[];
  uoms: { id: string; code: string; category: string; ratio_to_base: number }[];
  workOrders: { id: string; product_id: string | null; product_type: string | null }[];
  molds: Mold[];
  regrindOutputProductId: string | null;
  suppliers: Partner[];
  initialMode?: "view" | "edit" | "history" | "delete";
  autoResubmit?: boolean;
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
      waste_lines: toWasteLineForms<"raw_material" | "press" | "pouring" | "cross" | "kneading" | "finished_product_conditioning">(detail?.waste_lines),
      start_time: detail?.start_time ?? "",
      downtime_lines: toDowntimeLineForms(detail?.downtime_lines),
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
    mutationFn: async ({ input, force }: { input: CreateForm; force?: boolean }) => {
      let updated: ProductionReport;
      if (report.status === "validated") {
        updated = await correctValidatedDailyReport(token, report.id, toDetail(input), reason, force);
      } else if (report.status === "submitted") {
        updated = await correctDailyReport(token, report.id, toDetail(input), reason);
      } else {
        updated = await updateDailyReport(token, report.id, toDetail(input));
      }

      // If this is a resubmit flow, chain a submit call after save succeeds
      if (autoResubmit) {
        await submitReport(token, report.id);
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
  const regrindDeltaConfirmRequired =
    saveMutation.error instanceof ApiError && saveMutation.error.code === "REGRIND_DELTA_REQUIRES_NEW_ORDER";

  const semolinaUnit = productUnit(detail?.semolina_lines?.[0]?.product_id, products, uoms);
  const rebroyatUnit = productUnit(detail?.regrind_input_product_id, products, uoms);
  const regrindUnit = productUnit(detail?.regrind_product_id, products, uoms);
  const productName = (id: string | null) =>
    (id && products.find((p) => p.id === id)?.name) || t("production.waste.unknownItem");
  const supplierName = (id: string | null) => (id && suppliers.find((s) => s.id === id)?.name) || null;
  const withSupplier = (label: string, supplierId: string | null) => {
    const name = supplierName(supplierId);
    return name ? `${label} — ${name}` : label;
  };

  const figures: FigureRow[] = [
    // What the shift poured in this shift.
    // One row per quality poured, each in its own unit.
    ...(detail?.semolina_lines ?? []).map((line) => ({
      label:
        detail && detail.semolina_lines.length > 1
          ? `${t("production.dailyReports.field.semolina")} — ${productName(line.product_id)}`
          : t("production.dailyReports.field.semolina"),
      value: line.quantity,
      unit: productUnit(line.product_id, products, uoms),
      group: "in" as const,
    })),
    {
      label: t("production.dailyReports.field.regrindInput"),
      value: detail?.regrind_input_quantity,
      unit: rebroyatUnit,
      group: "in" as const,
    },
    {
      label: t("production.dailyReports.field.waterPercentage"),
      value: detail?.water_percentage,
      unit: "%",
      group: "in" as const,
    },
    {
      label: t("production.dailyReports.field.water"),
      value: detail?.water_quantity,
      unit: UTILITY_UNITS.water,
      group: "in" as const,
    },
    {
      label: withSupplier(t("production.dailyReports.field.fuel"), detail?.fuel_supplier_id ?? null),
      value: detail?.fuel_quantity,
      unit: UTILITY_UNITS.fuel,
      group: "in" as const,
    },
    {
      label: withSupplier(t("production.dailyReports.field.gasoil"), detail?.gasoil_supplier_id ?? null),
      value: detail?.gasoil_quantity,
      unit: UTILITY_UNITS.gasoil,
      group: "in" as const,
    },
    {
      label: t("production.dailyReports.field.electricity"),
      value: detail?.electricity_quantity,
      unit: UTILITY_UNITS.electricity,
      group: "in" as const,
    },

    // What came out of it.
    {
      // The tonnage off the scale, not the finished good's own stocking unit
      // (which may be pieces) -- see the daily_reports migration comment.
      label: t("production.reports.field.finishedProduct"),
      value: detail?.finished_product_quantity,
      unit: semolinaUnit,
      group: "out" as const,
    },
    // One row per déchet, each labelled with its own item. The daily report's
    // déchets are always weighed in kg (see WasteLinesField's fixedUnit), so
    // the unit here is fixed too rather than resolved per product.
    ...(detail?.waste_lines ?? []).map((line) => ({
      label: `${t(`production.waste.category.${line.category}` as Parameters<typeof t>[0])} — ${productName(line.product_id)}`,
      value: line.quantity,
      unit: "kg",
      group: "out" as const,
    })),
    {
      label: t("production.dailyReports.field.regrind"),
      value: detail?.regrind_quantity,
      unit: regrindUnit,
      group: "out" as const,
    },

    // How long it took, not a material flow either way.
    {
      label: t("production.dailyReports.field.semolinaFlowRate"),
      value: detail?.semolina_flow_rate,
      unit: "t/h",
      group: "time" as const,
    },
    { label: t("production.dailyReports.field.startTime"), value: detail?.start_time ?? "—", group: "time" as const },
    {
      label: t("production.ofDetails.time.production"),
      value: detail?.production_minutes,
      duration: true,
      group: "time" as const,
    },
    // One row per arrêt, each with its own motif, plus the total lost.
    ...(detail?.downtime_lines ?? []).map((line) => ({
      label: `${t("production.ofDetails.time.downtime")} — ${line.motif ?? t("production.waste.unknownItem")}`,
      value: line.minutes,
      duration: true,
      group: "time" as const,
    })),
    ...(detail && detail.downtime_lines.length > 1
      ? [
          {
            label: t("production.downtime.total"),
            value: detail.downtime_lines.reduce((sum, line) => sum + line.minutes, 0),
            duration: true,
            group: "time" as const,
          },
        ]
      : []),
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
      figures={figures}
      initialMode={initialMode}
      onDelete={async (deleteReason, force) => {
        await deleteReport(token, report.id, deleteReason, force);
        invalidate();
      }}
      editForm={
        <form
          className="space-y-4"
          onSubmit={form.handleSubmit((input) => saveMutation.mutate({ input }))}
        >
          <DailyDetailFields
            form={form}
            products={products}
            locations={locations}
            uoms={uoms}
            workOrders={workOrders}
            molds={molds}
            regrindOutputProductId={regrindOutputProductId}
            suppliers={suppliers}
          />
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

          {regrindDeltaConfirmRequired && (
            <div className="flex items-start gap-3 rounded-lg border border-destructive/20 bg-destructive-soft p-3">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
              <div>
                <p className="text-sm font-medium text-destructive">
                  {t("production.reports.correction.regrindDeltaWarning")}
                </p>
                <p className="text-sm text-muted-foreground">
                  {saveMutation.error instanceof ApiError ? saveMutation.error.message : undefined}
                </p>
              </div>
            </div>
          )}

          <Button
            type="submit"
            className="w-full"
            disabled={saveMutation.isPending || (needsReason && !reason.trim())}
          >
            {saveMutation.isPending ? t("common.saving") : t("common.save")}
          </Button>

          {regrindDeltaConfirmRequired && (
            <Button
              type="button"
              variant="destructive"
              className="w-full"
              disabled={saveMutation.isPending}
              onClick={() => saveMutation.mutate({ input: form.getValues(), force: true })}
            >
              {saveMutation.isPending
                ? t("common.saving")
                : t("production.reports.correction.regrindDeltaConfirmButton")}
            </Button>
          )}
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
    fuel_supplier_id: input.fuel_supplier_id || undefined,
    gasoil_quantity: input.gasoil_quantity,
    gasoil_supplier_id: input.gasoil_supplier_id || undefined,
    electricity_quantity: input.electricity_quantity,
    semolina_flow_rate: input.semolina_flow_rate,
    start_time: input.start_time || undefined,
    production_minutes: input.production_minutes,
    downtime_lines: fromDowntimeLineForms(input.downtime_lines),
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
  regrindOutputProductId,
  suppliers,
}: {
  form: ReturnType<typeof useForm<CreateForm>>;
  products: { id: string; name: string; uom_id: string }[];
  locations: { id: string; name: string }[];
  uoms: { id: string; code: string; category: string; ratio_to_base: number }[];
  workOrders: { id: string; product_id: string | null; product_type: string | null }[];
  molds: Mold[];
  /** The tenant's one rebroyat product (production.regrind_defaults, input_product_id IS NULL). */
  regrindOutputProductId: string | null;
  suppliers: Partner[];
}) {
  const { t } = useI18n();
  // Every figure is entered in its product's own stock unit — the same unit the
  // warehouse deducts in — so the label states it rather than offering a choice.
  // The first line stands in for "the semoule unit" where one figure (dough)
  // needs a single unit to show — dough is the mix of whatever was poured.
  const semolinaUnit = productUnit(form.watch("semolina_lines.0.product_id"), products, uoms);
  const rebroyatUnit = productUnit(form.watch("regrind_input_product_id"), products, uoms);
  // What the shift *produced* as rebroyat is always the tenant's one rebroyat
  // product -- never a choice per report. It used to be: an operator could
  // name any product here (to give the figure *some* weight unit), and would
  // routinely pick the raw semolina actually in use that shift. That mixed a
  // purchased raw material's identity into what is supposed to become
  // rebroyat stock, and mismatched units (semolina in tonnes vs. rebroyat in
  // kg) the same way the regrind-batch scale bug did. Forcing it here removes
  // both problems at the source instead of relying on the operator picking
  // right.
  useEffect(() => {
    if (regrindOutputProductId) form.setValue("regrind_product_id", regrindOutputProductId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [regrindOutputProductId]);
  const regrindUnit = productUnit(regrindOutputProductId, products, uoms);
  const withUnit = (label: string, unit: string | null) => (unit ? `${label} (${unit})` : label);
  // The mold list narrows to the order's own PC/PL once it's known; before
  // that (or if the order predates the field) every mold stays offered.
  const orderProductType = workOrders.find((o) => o.id === form.watch("of_id"))?.product_type;
  const moldsForOrder = molds.filter((m) => !orderProductType || m.type === orderProductType);

  // "Produit rebroyat" and semoule "Qualité" pick from the same MP product
  // list as everything else on this form, which also holds packaging
  // (carton, film, scotch) and finished goods -- neither picker should ever
  // land on one of those. Name-matching keeps this working even for tenants
  // whose product_classifications rows are incomplete (regrindOutputProductId
  // itself, e.g., has none): every rebroyat product's name says so, so
  // "rebroyat" in the name is excluded from the semoule list to keep it from
  // also matching "Rebroyat Semoule".
  const regrindInputProducts = products.filter(
    (p) => p.id === regrindOutputProductId || /rebroyat/i.test(p.name),
  );
  const semouleProducts = products.filter((p) => /semoule/i.test(p.name) && !/rebroyat/i.test(p.name));

  // The plant doses water as a percentage of what actually goes into the mix:
  // the semoule poured plus any rebroyat poured back in alongside it. So the
  // percentage is the real input, and water_quantity (still what consolidation
  // and the cockpit read) is kept in sync from it here rather than typed
  // twice -- and is read-only below, since it is entirely derived.
  //
  // Semoule and rebroyat are not necessarily stocked in the same unit --
  // semoule is poured in tonnes here, rebroyat versé in kg -- so raw
  // quantities can't just be added; each is converted to the weight
  // category's base unit (kg) via its own product's ratio_to_base first.
  // Water is metered in litres, and the plant treats 1 kg of dosed water as
  // 1 L, so that kg total is used directly against the percentage.
  const watchedSemolinaLines = form.watch("semolina_lines");
  const watchedRegrindInput = form.watch("regrind_input_quantity");
  const watchedRegrindInputProductId = form.watch("regrind_input_product_id");
  const watchedWaterPercentage = form.watch("water_percentage");
  const { totals: mixedInputTotals } = totalsByUomCategory(
    [
      ...(watchedSemolinaLines ?? []).map((line) => ({
        product_id: line.product_id || null,
        quantity: Number(line.quantity) || 0,
      })),
      { product_id: watchedRegrindInputProductId || null, quantity: Number(watchedRegrindInput) || 0 },
    ],
    products,
    uoms,
  );
  const mixedInputKg = mixedInputTotals.find((total) => total.unit === "kg")?.value ?? 0;
  useEffect(() => {
    const computed = Math.round(((watchedWaterPercentage / 100) * mixedInputKg + Number.EPSILON) * 100) / 100;
    form.setValue("water_quantity", computed);
    // form.setValue is stable across renders; watching it would refire on
    // every keystroke elsewhere in the form.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watchedWaterPercentage, mixedInputKg]);
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

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div className="space-y-2.5">
            <Label htmlFor="raw_material_location_id" className="flex min-h-[2.5rem] items-start">
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
          <div className="space-y-2.5">
            <Label htmlFor="regrind_input_quantity" className="flex min-h-[2.5rem] items-start gap-1">
              {withUnit(t("production.dailyReports.field.regrindInput"), rebroyatUnit)}
              <HelpTooltip text={t("production.dailyReports.help.regrindInput")} />
            </Label>
            <Input id="regrind_input_quantity" type="number" step="any" {...form.register("regrind_input_quantity")} />
          </div>
          <div className="space-y-2.5">
            <Label htmlFor="regrind_input_product_id" className="flex min-h-[2.5rem] items-start">
              {t("production.dailyReports.field.regrindInputProduct")}
            </Label>
            <Select id="regrind_input_product_id" {...form.register("regrind_input_product_id")}>
              <option value="">—</option>
              {regrindInputProducts.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </div>
        </div>

        <div className="space-y-1.5">
          <Label className="flex items-center gap-1">
            {t("production.dailyReports.field.semolina")}
            <HelpTooltip text={t("production.semolina.help")} />
          </Label>
          <SemolinaLinesField form={form} name="semolina_lines" products={semouleProducts} locations={locations} uoms={uoms} />
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
            {/* The tonnage off the scale, not the finished good's own stocking
                unit (which may be pieces) -- see the daily_reports migration
                comment. Same unit as the semoule it was made from. */}
            {withUnit(t("production.reports.field.finishedProduct"), semolinaUnit)}
            <HelpTooltip text={t("production.dailyReports.help.finishedProduct")} />
          </Label>
          <Input id="finished_product_quantity" type="number" step="any" {...form.register("finished_product_quantity")} />
        </div>
      </section>

      <section className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t("production.dailyReports.section.waste")}
        </p>
        <WasteLinesField
          form={form}
          name="waste_lines"
          categories={["raw_material", "press", "pouring", "cross", "kneading", "finished_product_conditioning"]}
          products={products}
          uoms={uoms}
          // The daily report's déchets are always weighed in kg -- every stage
          // here is loss of a weight-type material, and a fixed unit avoids
          // silently mislabelling a line if the chosen product happens to be
          // configured in a different unit.
          fixedUnit="kg"
          defaultProductFor={(category) =>
            // Déchet matière is semoule by definition, so the report's first
            // semoule line is the right first guess. The other stages name no
            // other field -- better an empty box the shift fills in than a
            // product nobody chose.
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
            <Label className="flex items-center gap-1">
              {t("production.dailyReports.field.regrindProduct")}
              <HelpTooltip text={t("production.dailyReports.help.regrindProduct")} />
            </Label>
            <p className="flex h-9 items-center text-sm text-muted-foreground">
              {regrindOutputProductId
                ? (products.find((p) => p.id === regrindOutputProductId)?.name ?? regrindOutputProductId)
                : t("production.dailyReports.help.regrindProductMissing")}
            </p>
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
            <Label htmlFor="water_quantity" className="flex items-center gap-1">
              {t("production.dailyReports.field.water")} ({UTILITY_UNITS.water})
              <HelpTooltip text={t("production.dailyReports.help.waterQuantity")} />
            </Label>
            <Input id="water_quantity" type="number" step="any" readOnly disabled {...form.register("water_quantity")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="fuel_quantity">
              {t("production.dailyReports.field.fuel")} ({UTILITY_UNITS.fuel})
            </Label>
            <Input id="fuel_quantity" type="number" step="any" {...form.register("fuel_quantity")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="fuel_supplier_id">{t("production.dailyReports.field.fuelSupplier")}</Label>
            <Select id="fuel_supplier_id" {...form.register("fuel_supplier_id")}>
              <option value="">—</option>
              {suppliers.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="gasoil_quantity">
              {t("production.dailyReports.field.gasoil")} ({UTILITY_UNITS.gasoil})
            </Label>
            <Input id="gasoil_quantity" type="number" step="any" {...form.register("gasoil_quantity")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="gasoil_supplier_id">{t("production.dailyReports.field.gasoilSupplier")}</Label>
            <Select id="gasoil_supplier_id" {...form.register("gasoil_supplier_id")}>
              <option value="">—</option>
              {suppliers.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
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
            <Label htmlFor="start_time">{t("production.dailyReports.field.startTime")}</Label>
            <Input id="start_time" type="time" {...form.register("start_time")} />
          </div>
          <ProductionDurationField form={form} />
        </div>
        <div className="space-y-1.5">
          <Label className="flex items-center gap-1">
            {t("production.reports.field.downtimeLines")}
            <HelpTooltip text={t("production.downtime.help")} />
          </Label>
          <DowntimeLinesField form={form} name="downtime_lines" />
        </div>
      </section>
    </div>
  );
}

/**
 * Production time as hours + minutes, the way a shift actually reads a clock,
 * composed into the single `production_minutes` the backend stores. Local
 * state rather than two more zod fields: only the composed total is ever
 * submitted, so the split only needs to exist here.
 */
function ProductionDurationField({ form }: { form: ReturnType<typeof useForm<CreateForm>> }) {
  const { t } = useI18n();
  const totalMinutes = form.watch("production_minutes") ?? 0;
  const [hours, setHours] = useState(Math.floor(totalMinutes / 60));
  const [minutes, setMinutes] = useState(totalMinutes % 60);

  // The form's own value can change out from under this component -- a report
  // switching under the same dialog, or a draft loading in -- so it stays the
  // source of truth and the boxes resync to it rather than the other way round.
  useEffect(() => {
    setHours(Math.floor(totalMinutes / 60));
    setMinutes(totalMinutes % 60);
    // Only resync when the form's own value changes, not on every local edit
    // -- see the effect below, which is what pushes local edits back into it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [totalMinutes]);

  useEffect(() => {
    form.setValue("production_minutes", Math.max(0, hours) * 60 + Math.max(0, minutes));
    // form.setValue is stable across renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hours, minutes]);

  return (
    <div className="grid grid-cols-2 gap-2">
      <div className="space-y-1.5">
        <Label htmlFor="production_hours">{t("production.dailyReports.field.productionHours")}</Label>
        <Input
          id="production_hours"
          type="number"
          min={0}
          value={hours}
          onChange={(event) => setHours(Number(event.target.value) || 0)}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="production_minutes_only">{t("production.dailyReports.field.productionMinutesOnly")}</Label>
        <Input
          id="production_minutes_only"
          type="number"
          min={0}
          max={59}
          value={minutes}
          onChange={(event) => setMinutes(Number(event.target.value) || 0)}
        />
      </div>
    </div>
  );
}

/**
 * Per-row actions. Edit/History/Delete all jump into the same detail dialog
 * used when a row itself is clicked (see `DailyReportDialog` above) — that
 * dialog already knows how each status behaves (a draft edits freely, a
 * submitted or validated report needs a correction reason, deleting a
 * validated one reverses its stock) — so the row buttons only need to say
 * which tab to land on, not re-implement any of that.
 */
function ReportRowActions({
  report,
  onOpenReport,
  onSubmitReport,
  isSubmitting,
  onReviseReport,
  isResubmitting,
}: {
  report: ProductionReport;
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
      <Button size="sm" variant="ghost" aria-label={t("common.edit")} onClick={() => onOpenReport("edit")}>
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
