import { useEffect, useRef, useState, type ReactNode } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Boxes, CheckCircle2, History, Package, Pencil, Plus, Send, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { rowEnterProps } from "../../components/motion/rowMotion";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Badge } from "../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, TableHead, ResizableTableHead } from "../../components/ui/table";
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
import { DowntimeOptionField, downtimeLabel } from "./downtimeOptions";
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
import {
  correctConditionnementReport,
  correctValidatedConditionnementReport,
  createConditionnementReport,
  deleteReport,
  getReport,
  getReportPackagingVariance,
  listMachines,
  listProducts,
  listReports,
  listWorkOrders,
  reviseReport,
  submitReport,
  updateConditionnementReport,
  type ConditionnementReportDetail,
  type DailyReportDetail,
  type Product,
  type ProductionReport,
  type ReportStatus,
} from "./api";
import { listLocations, listSuggestedVendors, listUoms, type SuggestedVendor } from "../warehouse/api";
import { listPartners, type Partner } from "../partners/api";
import { listProductTags, type ProductTag } from "../products/api";
import { productUnit, formatQuantity } from "../../lib/units";
import { PackagingVariancePanel } from "./PackagingVariancePanel";
import { OfConsolidationHint } from "./OfConsolidationHint";
import { useWasteTypes } from "./wasteTypes";

// A product qualifies for a packaging role (Film/Carton/Ruban) by tag, and for a
// PC-only or PL-only variant by product_family -- see
// scripts/fix_packaging_product_tags_and_family.py for how both are populated.
// A product with no product_family is generic and fits either order type.
function packagingRoleOptions(
  products: Product[],
  tagId: string | undefined,
  orderType: string | null | undefined,
  selectedId: string | undefined,
): Product[] {
  // Tags not loaded yet, or the role tag doesn't exist -- fall back to the
  // unfiltered list rather than hiding every option.
  if (!tagId) return products;
  const filtered = products.filter(
    (p) => p.tag_ids.includes(tagId) && (!p.product_family || !orderType || p.product_family === orderType),
  );
  // An already-saved report may reference a product the current filter would
  // exclude (order type changed, tagging changed since) -- keep it selectable
  // so editing the report doesn't silently blank out its own value.
  if (selectedId && !filtered.some((p) => p.id === selectedId)) {
    const selected = products.find((p) => p.id === selectedId);
    if (selected) return [...filtered, selected];
  }
  return filtered;
}

function finishedGoodOptions(products: Product[], orderType: string | null | undefined, selectedId: string | undefined): Product[] {
  const filtered = products.filter((p) => p.is_sellable && (!orderType || p.product_type === orderType));
  if (selectedId && !filtered.some((p) => p.id === selectedId)) {
    const selected = products.find((p) => p.id === selectedId);
    if (selected) return [...filtered, selected];
  }
  return filtered;
}

// `category` is a built-in kind or the id of one the plant added.
type WasteLine = { category: string; product_id: string; quantity: number; note: string };
type CreateForm = {
  packets_counted: number;
  finished_goods_location_id?: string;
  film_quantity: number;
  film_product_id?: string;
  film_supplier_id?: string;
  carton_quantity: number;
  waste_carton_quantity: number;
  carton_product_id?: string;
  carton_supplier_id?: string;
  scotch_quantity: number;
  scotch_product_id?: string;
  scotch_supplier_id?: string;
  ruban_quantity: number;
  ruban_product_id?: string;
  ruban_supplier_id?: string;
  packaging_location_id?: string;
  waste_lines: WasteLine[];
  machine_speed?: number;
  production_minutes: number;
  downtime_minutes: number;
  downtime_reason?: string;
  downtime_note?: string;
  lot_number?: string;
  dlc_date?: string;
  of_id: string;
  report_date: string;
  team?: string;
  shift?: string;
  product_id?: string;
  equipment_id?: string;
  daily_report_id?: string;
};

const QUERY_KEY = ["production", "reports", "conditionnement"] as const;
const WORK_ORDERS_QUERY_KEY = ["production", "work-orders"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const PRODUCT_TAGS_QUERY_KEY = ["core", "product-tags"] as const;
const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;
const UOMS_QUERY_KEY = ["core", "uoms"] as const;
const MACHINES_QUERY_KEY = ["production", "machines", "all"] as const;
const PARTNERS_QUERY_KEY = ["core", "partners"] as const;

type StatusFilter = "all" | ReportStatus;
type GroupByOption = "none" | "of" | "team" | "shift";

const EMPTY_DETAIL = {
  packets_counted: 0,
  finished_goods_location_id: "",
  film_quantity: 0,
  film_product_id: "",
  film_supplier_id: "",
  carton_quantity: 0,
  waste_carton_quantity: 0,
  carton_product_id: "",
  carton_supplier_id: "",
  scotch_quantity: 0,
  scotch_product_id: "",
  scotch_supplier_id: "",
  ruban_quantity: 0,
  ruban_product_id: "",
  ruban_supplier_id: "",
  packaging_location_id: "",
  waste_lines: [] as WasteLineForm[],
  machine_speed: undefined,
  production_minutes: 0,
  downtime_minutes: 0,
  downtime_reason: "",
  downtime_note: "",
  lot_number: "",
  dlc_date: "",
  daily_report_id: "",
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
    film_supplier_id: input.film_supplier_id || undefined,
    carton_quantity: input.carton_quantity,
    waste_carton_quantity: input.waste_carton_quantity,
    carton_product_id: input.carton_product_id || undefined,
    carton_supplier_id: input.carton_supplier_id || undefined,
    scotch_quantity: input.scotch_quantity,
    scotch_product_id: input.scotch_product_id || undefined,
    scotch_supplier_id: input.scotch_supplier_id || undefined,
    ruban_quantity: input.ruban_quantity,
    ruban_product_id: input.ruban_product_id || undefined,
    ruban_supplier_id: input.ruban_supplier_id || undefined,
    packaging_location_id: input.packaging_location_id || undefined,
    waste_lines: fromWasteLineForms(input.waste_lines),
    machine_speed: input.machine_speed,
    production_minutes: input.production_minutes,
    downtime_minutes: input.downtime_minutes,
    downtime_reason: input.downtime_reason || undefined,
    downtime_note: input.downtime_note || undefined,
    lot_number: input.lot_number || undefined,
    dlc_date: input.dlc_date || undefined,
    daily_report_id: input.daily_report_id || undefined,
  } as Partial<ConditionnementReportDetail>;
}

export function ConditionnementTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();

  const detailSchema = z.object({
    packets_counted: z.coerce.number().min(0),
    finished_goods_location_id: z.string().optional(),
    film_quantity: z.coerce.number().min(0),
    film_product_id: z.string().optional(),
    film_supplier_id: z.string().optional(),
    carton_quantity: z.coerce.number().min(0),
    waste_carton_quantity: z.coerce.number().min(0),
    carton_product_id: z.string().optional(),
    carton_supplier_id: z.string().optional(),
    scotch_quantity: z.coerce.number().min(0),
    scotch_product_id: z.string().optional(),
    scotch_supplier_id: z.string().optional(),
    ruban_quantity: z.coerce.number().min(0),
    ruban_product_id: z.string().optional(),
    ruban_supplier_id: z.string().optional(),
    packaging_location_id: z.string().optional(),
    waste_lines: z.array(
      z.object({
        // A built-in kind or the id of one the plant added; the backend refuses
        // one the packing report does not have.
        category: z.string().min(1),
        product_id: z.string(),
        quantity: z.coerce.number().min(0),
        note: z.string(),
      }),
    ),
    machine_speed: z.coerce.number().min(0).optional(),
    production_minutes: z.coerce.number().int().min(0),
    downtime_minutes: z.coerce.number().int().min(0),
    downtime_reason: z.string().optional(),
    downtime_note: z.string().optional(),
    lot_number: z.string().optional(),
    dlc_date: z.string().optional(),
  });

  const createSchema = detailSchema.extend({
    of_id: z.string().min(1, t("common.required")),
    report_date: z.string().min(1, t("common.required")),
    team: z.string().optional(),
    shift: z.string().optional(),
    product_id: z.string().optional(),
    equipment_id: z.string().optional(),
    daily_report_id: z.string().optional(),
  });

  const [dialogOpen, setDialogOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  // Conditionnement is the OF's final stage, so tracking one order's packing
  // runs together end-to-end is the default view.
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
  const { data: productTags = [] } = useQuery({ queryKey: PRODUCT_TAGS_QUERY_KEY, queryFn: () => listProductTags(token) });
  const { data: locations = [] } = useQuery({ queryKey: LOCATIONS_QUERY_KEY, queryFn: () => listLocations(token) });
  const { data: uoms = [] } = useQuery({ queryKey: UOMS_QUERY_KEY, queryFn: () => listUoms(token) });
  const { data: partners = [] } = useQuery({ queryKey: PARTNERS_QUERY_KEY, queryFn: () => listPartners(token) });
  const suppliers = partners.filter((p) => p.kind === "supplier" || p.kind === "both");
  // Tenant-wide, for resolving a report's equipment_id to a name in the table —
  // distinct from the create form's own line-scoped machines query below.
  const { data: allMachines = [] } = useQuery({ queryKey: MACHINES_QUERY_KEY, queryFn: () => listMachines(token) });
  const machineLabel = (machineId: string | null) => {
    if (!machineId) return "—";
    const machine = allMachines.find((m) => m.id === machineId);
    return machine ? `${machine.code} — ${machine.name}` : "—";
  };

  const openWorkOrders = workOrders.filter((o) => ["planned", "ongoing", "suspended"].includes(o.status));
  const referenceOf = (ofId: string) => workOrders.find((o) => o.id === ofId)?.reference ?? ofId;
  // The packed article is the order's product; the report never names it again,
  // except its very first filing, which is what names one if the OF has none yet.
  const productOfOrder = (ofId: string) => workOrders.find((o) => o.id === ofId)?.product_id ?? undefined;
  const orderTypeOf = (ofId: string) => workOrders.find((o) => o.id === ofId)?.product_type ?? null;

  const form = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    defaultValues: { of_id: "", report_date: todayIso(), team: "", shift: "", product_id: "", equipment_id: "", ...EMPTY_DETAIL },
  });
  const selectedOfId = form.watch("of_id");
  const selectedOrderHasNoProduct = !!selectedOfId && !workOrders.find((o) => o.id === selectedOfId)?.product_id;
  // Machines the chosen OF's line can be attributed to — a line like Line_1_PL
  // can carry more than one at once, so the report must say which one it ran on.
  const selectedWorkCenterId = workOrders.find((o) => o.id === selectedOfId)?.work_center_id;
  const { data: machines = [] } = useQuery({
    queryKey: ["production", "machines", selectedWorkCenterId],
    queryFn: () => listMachines(token, selectedWorkCenterId!),
    enabled: !!selectedWorkCenterId,
  });
  // The chosen OF's daily reports, to link this packing run back to the one
  // whose output it packaged — see daily_report_id's docstring.
  const { data: dailyReports = [] } = useQuery({
    queryKey: ["production", "reports", "daily", selectedOfId],
    queryFn: () => listReports(token, { of_id: selectedOfId, report_type: "daily" }),
    enabled: !!selectedOfId,
  });

  const createMutation = useMutation({
    mutationFn: (input: CreateForm) =>
      createConditionnementReport(token, {
        of_id: input.of_id,
        report_date: input.report_date,
        team: input.team || undefined,
        shift: input.shift || undefined,
        product_id: input.product_id || undefined,
        equipment_id: input.equipment_id || undefined,
        detail: toDetail(input),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setDialogOpen(false);
      form.reset({ of_id: "", report_date: todayIso(), team: "", shift: "", product_id: "", equipment_id: "", ...EMPTY_DETAIL });
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

  const filterFields: FilterField<ProductionReport>[] = [
    { key: "of", kind: "text", getValue: (r) => referenceOf(r.of_id) },
    { key: "date", kind: "text", getValue: (r) => r.report_date },
    { key: "team", kind: "text", getValue: (r) => r.team },
    { key: "shift", kind: "text", getValue: (r) => r.shift },
    { key: "machine", kind: "text", getValue: (r) => machineLabel(r.equipment_id) },
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
          onOpenReport={(mode) => openReportAt(r, mode)}
          onSubmitReport={() => submitMutation.mutate(r.id)}
          isSubmitting={submitMutation.isPending && submitMutation.variables === r.id}
          onReviseReport={() => reviseMutation.mutate(r.id)}
          isResubmitting={reviseMutation.isPending && reviseMutation.variables === r.id}
        />
      ),
    },
  ];
  const table = useTableColumns("production.conditionnement", columns);
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
                      <div className="space-y-1.5">
                        <Label htmlFor="c_equipment_id" className="flex items-center gap-1">
                          {t("production.reports.field.machine")}
                          <HelpTooltip text={t("production.reports.help.machine")} />
                        </Label>
                        <Select id="c_equipment_id" {...form.register("equipment_id")} disabled={!selectedWorkCenterId}>
                          <option value="">—</option>
                          {machines.map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.code} — {m.name}
                            </option>
                          ))}
                        </Select>
                      </div>
                    </div>
                    <OfConsolidationHint workOrderId={selectedOfId || undefined} />
                    {selectedOrderHasNoProduct && (
                      <div className="space-y-1.5 rounded-lg border border-border bg-muted/30 p-3">
                        <Label htmlFor="c_product_id">{t("production.conditionnement.field.product")}</Label>
                        <Select id="c_product_id" {...form.register("product_id")}>
                          <option value="">—</option>
                          {finishedGoodOptions(products, orderTypeOf(selectedOfId), form.watch("product_id")).map((product) => (
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
                productTags={productTags}
                orderType={orderTypeOf(selectedOfId)}
                locations={locations}
                uoms={uoms}
                // The OF may not have a product yet -- that's exactly when the
                // "Produit fini" picker above is shown, so fall back to whatever
                // it's been set to instead of leaving the carton/sac tier blank.
                finishedProductId={productOfOrder(form.watch("of_id")) || form.watch("product_id") || undefined}
                suppliers={suppliers}
                dailyReports={dailyReports}
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
        <PackingReportDialog
          // Remount per report so a row's Edit/History/Delete action always
          // lands the dialog on the right tab instead of reusing whatever
          // tab a previous report was left on.
          key={focusedReport.id}
          report={focusedReport}
          reference={referenceOf(focusedReport.of_id)}
          finishedProductId={productOfOrder(focusedReport.of_id)}
          orderType={orderTypeOf(focusedReport.of_id)}
          products={products}
          locations={locations}
          uoms={uoms}
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
 * The opened packing report. A validated one has already put finished goods into
 * stock and taken packaging out, so editing or deleting it reverses those
 * movements first - both ask for a reason that lands in the audit trail.
 */
export function PackingReportDialog({
  report,
  reference,
  finishedProductId,
  orderType,
  products,
  locations,
  uoms,
  suppliers,
  initialMode,
  autoResubmit,
  onClose,
}: {
  report: ProductionReport;
  reference: string;
  finishedProductId: string | undefined;
  orderType: string | null;
  products: Product[];
  locations: { id: string; name: string }[];
  uoms: { id: string; code: string }[];
  suppliers: Partner[];
  initialMode?: "view" | "edit" | "history" | "delete";
  autoResubmit?: boolean;
  onClose: () => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const { label: wasteLabel } = useWasteTypes();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");

  const detailSchema = z.object({
    packets_counted: z.coerce.number().min(0),
    finished_goods_location_id: z.string().optional(),
    film_quantity: z.coerce.number().min(0),
    film_product_id: z.string().optional(),
    film_supplier_id: z.string().optional(),
    carton_quantity: z.coerce.number().min(0),
    waste_carton_quantity: z.coerce.number().min(0),
    carton_product_id: z.string().optional(),
    carton_supplier_id: z.string().optional(),
    scotch_quantity: z.coerce.number().min(0),
    scotch_product_id: z.string().optional(),
    scotch_supplier_id: z.string().optional(),
    ruban_quantity: z.coerce.number().min(0),
    ruban_product_id: z.string().optional(),
    ruban_supplier_id: z.string().optional(),
    packaging_location_id: z.string().optional(),
    waste_lines: z.array(
      z.object({
        // A built-in kind or the id of one the plant added; the backend refuses
        // one the packing report does not have.
        category: z.string().min(1),
        product_id: z.string(),
        quantity: z.coerce.number().min(0),
        note: z.string(),
      }),
    ),
    machine_speed: z.coerce.number().min(0).optional(),
    production_minutes: z.coerce.number().int().min(0),
    downtime_minutes: z.coerce.number().int().min(0),
    downtime_reason: z.string().optional(),
    downtime_note: z.string().optional(),
    lot_number: z.string().optional(),
    dlc_date: z.string().optional(),
  });

  const createSchema = detailSchema.extend({
    of_id: z.string().min(1, t("common.required")),
    report_date: z.string().min(1, t("common.required")),
    team: z.string().optional(),
    shift: z.string().optional(),
    product_id: z.string().optional(),
    equipment_id: z.string().optional(),
    daily_report_id: z.string().optional(),
  });

  const { data: full } = useQuery({
    queryKey: ["production", "reports", report.id],
    queryFn: () => getReport(token, report.id),
  });
  const detail = full?.detail as ConditionnementReportDetail | undefined;
  const { data: dailyReports = [] } = useQuery({
    queryKey: ["production", "reports", "daily", report.of_id],
    queryFn: () => listReports(token, { of_id: report.of_id, report_type: "daily" }),
  });
  const { data: productTags = [] } = useQuery({ queryKey: PRODUCT_TAGS_QUERY_KEY, queryFn: () => listProductTags(token) });

  const form = useForm<CreateForm>({
    resolver: zodResolver(createSchema),
    values: {
      of_id: report.of_id,
      report_date: report.report_date,
      team: report.team ?? "",
      shift: report.shift ?? "",
      ...EMPTY_DETAIL,
      ...(detail ?? {}),
      waste_lines: toWasteLineForms(detail?.waste_lines),
      finished_goods_location_id: detail?.finished_goods_location_id ?? "",
      packaging_location_id: detail?.packaging_location_id ?? "",
      film_product_id: detail?.film_product_id ?? "",
      carton_product_id: detail?.carton_product_id ?? "",
      scotch_product_id: detail?.scotch_product_id ?? "",
      ruban_product_id: detail?.ruban_product_id ?? "",
      film_supplier_id: detail?.film_supplier_id ?? "",
      carton_supplier_id: detail?.carton_supplier_id ?? "",
      scotch_supplier_id: detail?.scotch_supplier_id ?? "",
      ruban_supplier_id: detail?.ruban_supplier_id ?? "",
      downtime_reason: detail?.downtime_reason ?? "",
      downtime_note: detail?.downtime_note ?? "",
      lot_number: detail?.lot_number ?? "",
      dlc_date: detail?.dlc_date ?? "",
      daily_report_id: detail?.daily_report_id ?? "",
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
    mutationFn: async (input: CreateForm) => {
      let updated: ProductionReport;
      if (report.status === "validated") {
        updated = await correctValidatedConditionnementReport(token, report.id, toDetail(input), reason);
      } else if (report.status === "submitted") {
        updated = await correctConditionnementReport(token, report.id, toDetail(input), reason);
      } else {
        updated = await updateConditionnementReport(token, report.id, toDetail(input));
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

  const goodsUnit = productUnit(finishedProductId, products, uoms);

  const figures: FigureRow[] = [
    {
      label: t("production.conditionnement.field.packetsCounted"),
      value: detail?.packets_counted,
      unit: goodsUnit,
    },
    // One row per déchet, each labelled with its own item and unit. Scotch
    // shows up here on its own now instead of having nowhere to go.
    ...(detail?.waste_lines ?? []).map((line) => ({
      label: `${wasteLabel(line.category)} — ${
        (line.product_id && products.find((p) => p.id === line.product_id)?.name) ||
        t("production.waste.unknownItem")
      }`,
      value: line.quantity,
      unit: productUnit(line.product_id, products, uoms),
    })),
    { label: t("production.conditionnement.field.machineSpeed"), value: detail?.machine_speed, unit: "u/min" },
    { label: t("production.ofDetails.time.production"), value: detail?.production_minutes, duration: true },
    { label: t("production.ofDetails.time.downtime"), value: detail?.downtime_minutes, duration: true },
    {
      label: t("production.downtime.field.motif"),
      value: detail?.downtime_reason
        ? downtimeLabel(t, "motif", detail.downtime_reason)
        : "—",
    },
    { label: t("production.downtime.field.note"), value: detail?.downtime_note ?? "—" },
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
      banner={
        <>
          <ReportVarianceBanner reportId={report.id} />
          <PackagingConsumptionSummary detail={detail} products={products} uoms={uoms} suppliers={suppliers} />
        </>
      }
      figures={figures}
      initialMode={initialMode}
      onDelete={async (deleteReason) => {
        await deleteReport(token, report.id, deleteReason);
        invalidate();
      }}
      editForm={
        <form className="space-y-4" onSubmit={form.handleSubmit((input) => saveMutation.mutate(input))}>
          <PackingDetailFields
            form={form}
            products={products}
            productTags={productTags}
            orderType={orderType}
            locations={locations}
            uoms={uoms}
            finishedProductId={finishedProductId}
            suppliers={suppliers}
            dailyReports={dailyReports}
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

/**
 * The view-mode read-out of what packaging this report consumed: one row per
 * item (Film/Carton/Scotch/Ruban) with its quantity, product and fournisseur
 * side by side, rather than the supplier name squeezed into a figure's label
 * with no product name at all. Items with nothing recorded are left out.
 */
function PackagingConsumptionSummary({
  detail,
  products,
  uoms,
  suppliers,
}: {
  detail: ConditionnementReportDetail | undefined;
  products: Product[];
  uoms: { id: string; code: string }[];
  suppliers: Partner[];
}) {
  const { t } = useI18n();
  if (!detail) return null;

  const productName = (id: string | null | undefined) => (id && products.find((p) => p.id === id)?.name) || "—";
  const supplierName = (id: string | null | undefined) => (id && suppliers.find((s) => s.id === id)?.name) || "—";

  const rows = [
    {
      label: t("production.conditionnement.field.film"),
      quantity: detail.film_quantity,
      unit: productUnit(detail.film_product_id, products, uoms),
      productId: detail.film_product_id,
      supplierId: detail.film_supplier_id,
    },
    {
      label: t("production.conditionnement.field.carton"),
      quantity: detail.carton_quantity,
      unit: productUnit(detail.carton_product_id, products, uoms),
      productId: detail.carton_product_id,
      supplierId: detail.carton_supplier_id,
    },
    {
      label: t("production.conditionnement.field.scotch"),
      quantity: detail.scotch_quantity,
      unit: productUnit(detail.scotch_product_id, products, uoms),
      productId: detail.scotch_product_id,
      supplierId: detail.scotch_supplier_id,
    },
    {
      label: t("production.conditionnement.field.ruban"),
      quantity: detail.ruban_quantity,
      unit: productUnit(detail.ruban_product_id, products, uoms),
      productId: detail.ruban_product_id,
      supplierId: detail.ruban_supplier_id,
    },
  ].filter((row) => row.quantity > 0 || row.productId || row.supplierId);

  if (rows.length === 0) return null;

  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <p className="border-b border-border bg-muted/30 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {t("production.conditionnement.section.packaging")}
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("production.conditionnement.summary.item")}</TableHead>
            <TableHead>{t("production.conditionnement.summary.quantity")}</TableHead>
            <TableHead>{t("production.conditionnement.summary.product")}</TableHead>
            <TableHead>{t("production.conditionnement.summary.supplier")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.label}>
              <TableCell className="font-medium">{row.label}</TableCell>
              <TableCell className="tabular-nums">{formatQuantity(row.quantity, row.unit)}</TableCell>
              <TableCell>{productName(row.productId)}</TableCell>
              <TableCell>{supplierName(row.supplierId)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/**
 * Which fournisseur a packaging item came from. Film, carton, scotch and
 * ruban can each be delivered by more than one supplier, so this pairs a
 * supplier picker narrowed to the ones actually tagged for that item with a
 * hint of which are preferred -- the same vendor-suggestion match (by
 * product tag) the purchase order screen already uses, reused here rather
 * than reinvented.
 */
function PackagingSupplierField({
  form,
  name,
  label,
  productId,
  suppliers,
}: {
  form: ReturnType<typeof useForm<CreateForm>>;
  name: "film_supplier_id" | "carton_supplier_id" | "scotch_supplier_id" | "ruban_supplier_id";
  label: string;
  productId: string | undefined;
  suppliers: Partner[];
}) {
  const { session } = useAuth();
  const token = session!.token;
  const { data: suggested = [] } = useQuery({
    queryKey: ["core", "products", productId, "suggested-vendors"],
    queryFn: () => listSuggestedVendors(token, productId!),
    enabled: !!productId,
  });

  // Once a product names its role (film/carton/scotch/ruban), narrow the
  // dropdown to suppliers actually tagged for that role instead of every
  // supplier in the system -- the same tag match that produces the "suggested"
  // chips above. Falls back to the full list when no product is chosen yet or
  // nothing is tagged for it, so the field is never a dead end.
  const selectedId = form.watch(name);
  const options: (Partner | SuggestedVendor)[] =
    suggested.length > 0
      ? suggested.some((v) => v.partner_id === selectedId)
        ? suggested
        : [...suggested, ...suppliers.filter((s) => s.id === selectedId)]
      : suppliers;

  return (
    <div className="space-y-1.5">
      <Label htmlFor={name}>{label}</Label>
      {suggested.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {suggested.map((vendor: SuggestedVendor) => (
            <button key={vendor.partner_id} type="button" onClick={() => form.setValue(name, vendor.partner_id)}>
              <Badge variant="outline" className="gap-1">
                <Sparkles className="h-3 w-3" />
                {vendor.name}
              </Badge>
            </button>
          ))}
        </div>
      )}
      <Select id={name} {...form.register(name)}>
        <option value="">—</option>
        {options.map((s) => (
          <option key={"partner_id" in s ? s.partner_id : s.id} value={"partner_id" in s ? s.partner_id : s.id}>
            {s.name}
          </option>
        ))}
      </Select>
    </div>
  );
}

/** What a packaging run should expect to bag, pulled from the specific daily
 * report it's linked to -- the same per-item hint pattern QC uses once it
 * picks which conditionnement run to inspect. */
function DailyReportPackagingHint({ dailyReportId }: { dailyReportId: string | undefined }) {
  const { session } = useAuth();
  const token = session!.token;
  const { t } = useI18n();

  const { data: dailyReport } = useQuery({
    queryKey: ["production", "report", dailyReportId],
    queryFn: () => getReport(token, dailyReportId!),
    enabled: !!dailyReportId,
  });

  if (!dailyReport?.detail) return null;
  const detail = dailyReport.detail as DailyReportDetail;

  return (
    <div className="rounded-md border border-border bg-muted/30 p-3">
      <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {t("production.conditionnement.hint.dailyReport.title")}
      </p>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <span className="text-muted-foreground">
            {t("production.conditionnement.hint.dailyReport.finishedProduct")}:{" "}
          </span>
          {formatQuantity(detail.finished_product_quantity, "t")}
        </div>
        <div>
          <span className="text-muted-foreground">{t("production.conditionnement.hint.dailyReport.regrind")}: </span>
          {formatQuantity(detail.regrind_quantity, "kg")}
        </div>
      </div>
    </div>
  );
}

function PackingDetailFields({
  form,
  products,
  productTags,
  orderType,
  locations,
  uoms,
  finishedProductId,
  suppliers,
  dailyReports = [],
}: {
  form: ReturnType<typeof useForm<CreateForm>>;
  products: Product[];
  productTags: ProductTag[];
  orderType: string | null;
  locations: { id: string; name: string }[];
  uoms: { id: string; code: string }[];
  finishedProductId: string | undefined;
  suppliers: Partner[];
  dailyReports?: ProductionReport[];
}) {
  const { t } = useI18n();
  const { categoriesFor } = useWasteTypes();
  const tagId = (name: string) => productTags.find((tag) => tag.name === name)?.id;
  const filmOptions = packagingRoleOptions(products, tagId("FILM"), orderType, form.watch("film_product_id"));
  const cartonOptions = packagingRoleOptions(products, tagId("CARTON"), orderType, form.watch("carton_product_id"));
  const scotchOptions = packagingRoleOptions(products, tagId("SCOTCH"), orderType, form.watch("scotch_product_id"));
  // Ruban's own list can include several models (e.g. TB200, Videojet) as
  // distinct tagged products -- which one applies is just whichever the
  // operator picks here, not a separate field.
  const rubanOptions = packagingRoleOptions(products, tagId("RUBAN"), orderType, form.watch("ruban_product_id"));
  // The déchet "Emballage" dropdown can only ever be one of these -- never a
  // finished good or an unrelated raw material, and never the whole catalog.
  const packagingWasteProducts = Array.from(
    new Map(
      [...filmOptions, ...cartonOptions, ...scotchOptions, ...rubanOptions].map((p) => [p.id, p]),
    ).values(),
  );
  // Packaging leaves stock in its own unit and finished goods enter in theirs,
  // so every quantity here states the unit the warehouse will move.
  const goodsUnit = productUnit(finishedProductId, products, uoms);
  const filmUnit = productUnit(form.watch("film_product_id"), products, uoms);
  const cartonUnit = productUnit(form.watch("carton_product_id"), products, uoms);
  const scotchUnit = productUnit(form.watch("scotch_product_id"), products, uoms);
  const rubanUnit = productUnit(form.watch("ruban_product_id"), products, uoms);
  const withUnit = (label: string, unit: string | null) => (unit ? `${label} (${unit})` : label);

  // Decision 24: the live cross-check between what the floor boxed and what the
  // machine tallied, shown while typing rather than only after saving.
  const finishedProduct = products.find((p) => p.id === finishedProductId);
  const packetsPerCarton = finishedProduct?.packets_per_carton ?? null;
  const netWeightGrams = finishedProduct?.net_weight_grams ?? null;
  // A sac (or any product with no carton tier at all) has nothing to box, so
  // the carton fields are meaningless for it — see the sac branch below.
  const hasCartonTier = !!(packetsPerCarton && packetsPerCarton > 0);
  const cartonsEntered = Number(form.watch("carton_quantity")) || 0;
  const wasteCartonsEntered = Number(form.watch("waste_carton_quantity")) || 0;
  // Empty/damaged cartons hold no packets, so the "real packets" and
  // finished-goods figures below are judged against good cartons only — the
  // same subtraction the backend applies (packaging_estimate.finished_
  // quantity_from_count / tonnage_from_count).
  const goodCartonsEntered = Math.max(cartonsEntered - wasteCartonsEntered, 0);
  const packetsEntered = Number(form.watch("packets_counted")) || 0;
  const realPacketsFromCartons = packetsPerCarton ? goodCartonsEntered * packetsPerCarton : null;
  const estimatedCartonsFromMachine = packetsPerCarton ? packetsEntered / packetsPerCarton : null;
  // Same decision-24 rule the backend persists at validation
  // (packaging_estimate.tonnage_from_count): cartons lead when there's a
  // carton tier and some were counted, otherwise the tally itself — a sac's
  // count — is the finished-goods figure. Shown live so a team sees the
  // tonnage their count implies before it is ever saved.
  const unitsFromCount = hasCartonTier && cartonsEntered > 0 ? goodCartonsEntered * (packetsPerCarton as number) : packetsEntered;
  const estimatedTonnage = netWeightGrams && netWeightGrams > 0 ? (unitsFromCount * netWeightGrams) / 1_000_000 : null;
  const renderProductOptions = (list: Product[]) => (
    <>
      <option value="">—</option>
      {list.map((p) => (
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
          {hasCartonTier && (
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
          )}
          {hasCartonTier && (
            <div className="space-y-1.5">
              <Label htmlFor="waste_carton_quantity" className="flex items-center gap-1">
                {t("production.conditionnement.field.wasteCarton")}
                <HelpTooltip text={t("production.conditionnement.help.wasteCarton")} />
              </Label>
              <Input
                id="waste_carton_quantity"
                type="number"
                step="any"
                {...form.register("waste_carton_quantity")}
              />
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="packets_counted" className="flex items-center gap-1">
              {withUnit(
                t(
                  hasCartonTier
                    ? "production.conditionnement.field.packetsCounted"
                    : "production.conditionnement.field.sacsCounted",
                ),
                goodsUnit,
              )}
              <HelpTooltip text={t("production.conditionnement.help.packetsCounted")} />
            </Label>
            <Input id="packets_counted" type="number" step="any" {...form.register("packets_counted")} />
            {hasCartonTier && estimatedCartonsFromMachine !== null && (
              <p className="text-xs text-muted-foreground">
                {t("production.conditionnement.hint.estimatedCartonsFromMachine")}{" "}
                {formatQuantity(estimatedCartonsFromMachine)}
              </p>
            )}
            {estimatedTonnage !== null && (
              <p className="text-xs text-muted-foreground">
                {t("production.conditionnement.hint.estimatedTonnage")} {formatQuantity(estimatedTonnage, "t")}
              </p>
            )}
          </div>
          {hasCartonTier && (
            <div className="space-y-1.5">
              <Label htmlFor="carton_product_id">{t("production.conditionnement.field.cartonProduct")}</Label>
              <Select id="carton_product_id" {...form.register("carton_product_id")}>
                {renderProductOptions(cartonOptions)}
              </Select>
            </div>
          )}
          {hasCartonTier && (
            <PackagingSupplierField
              form={form}
              name="carton_supplier_id"
              label={t("production.conditionnement.field.cartonSupplier")}
              productId={form.watch("carton_product_id")}
              suppliers={suppliers}
            />
          )}
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
          <div className="space-y-1.5">
            <Label htmlFor="daily_report_id" className="flex items-center gap-1">
              {t("production.conditionnement.field.dailyReport")}
              <HelpTooltip text={t("production.conditionnement.help.dailyReport")} />
            </Label>
            <Select id="daily_report_id" {...form.register("daily_report_id")}>
              <option value="">—</option>
              {dailyReports.map((r) => (
                <option key={r.id} value={r.id}>
                  {[r.report_date, r.shift, r.team].filter(Boolean).join(" · ")}
                </option>
              ))}
            </Select>
          </div>
          <DailyReportPackagingHint dailyReportId={form.watch("daily_report_id") || undefined} />
        </div>
      </section>

      <section className="space-y-2">
        <div className="flex items-center gap-1.5">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t("production.conditionnement.section.packaging")}
          </p>
          <HelpTooltip text={t("production.conditionnement.help.packaging")} />
        </div>
        <div className="space-y-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="film_quantity">{withUnit(t("production.conditionnement.field.film"), filmUnit)}</Label>
              <Input id="film_quantity" type="number" step="any" {...form.register("film_quantity")} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="film_product_id">{t("production.conditionnement.field.filmProduct")}</Label>
              <Select id="film_product_id" {...form.register("film_product_id")}>
                {renderProductOptions(filmOptions)}
              </Select>
            </div>
            <PackagingSupplierField
              form={form}
              name="film_supplier_id"
              label={t("production.conditionnement.field.filmSupplier")}
              productId={form.watch("film_product_id")}
              suppliers={suppliers}
            />
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="scotch_quantity">{withUnit(t("production.conditionnement.field.scotch"), scotchUnit)}</Label>
              <Input id="scotch_quantity" type="number" step="any" {...form.register("scotch_quantity")} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="scotch_product_id">{t("production.conditionnement.field.scotchProduct")}</Label>
              <Select id="scotch_product_id" {...form.register("scotch_product_id")}>
                {renderProductOptions(scotchOptions)}
              </Select>
            </div>
            <PackagingSupplierField
              form={form}
              name="scotch_supplier_id"
              label={t("production.conditionnement.field.scotchSupplier")}
              productId={form.watch("scotch_product_id")}
              suppliers={suppliers}
            />
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="ruban_quantity">{withUnit(t("production.conditionnement.field.ruban"), rubanUnit)}</Label>
              <Input id="ruban_quantity" type="number" step="any" {...form.register("ruban_quantity")} />
            </div>
            <div className="space-y-1.5">
              {/* Model (TB200, Videojet, ...) is whichever RUBAN-tagged product is picked here -- not a separate field. */}
              <Label htmlFor="ruban_product_id">{t("production.conditionnement.field.rubanProduct")}</Label>
              <Select id="ruban_product_id" {...form.register("ruban_product_id")}>
                {renderProductOptions(rubanOptions)}
              </Select>
            </div>
            <PackagingSupplierField
              form={form}
              name="ruban_supplier_id"
              label={t("production.conditionnement.field.rubanSupplier")}
              productId={form.watch("ruban_product_id")}
              suppliers={suppliers}
            />
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
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
        </div>
      </section>

      <section className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t("production.dailyReports.section.waste")}
        </p>
        <WasteLinesField
          form={form}
          name="waste_lines"
          categories={categoriesFor(
            "conditionnement",
            (form.watch("waste_lines") ?? []).map((line) => line.category),
          )}
          products={products}
          uoms={uoms}
          defaultProductFor={(category) =>
            // Déchet produit is the OF's own product by definition. Packaging
            // waste could be film, carton or scotch, so it is left to the shift
            // -- picking one of three would be a guess, not a default.
            category === "product" ? finishedProductId || undefined : undefined
          }
          productsFor={(category) => (category === "packaging" ? packagingWasteProducts : products)}
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
          <DowntimeOptionField
            id="c_downtime_reason"
            field="motif"
            registration={form.register("downtime_reason")}
            current={form.watch("downtime_reason")}
            onPick={(value) => form.setValue("downtime_reason", value, { shouldDirty: true })}
          />
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="c_downtime_note">{t("production.downtime.field.note")}</Label>
            <Input id="c_downtime_note" placeholder={t("production.waste.notePlaceholder")} {...form.register("downtime_note")} />
          </div>
        </div>
      </section>
    </div>
  );
}

/**
 * Per-row actions. Edit/History/Delete all jump into the same detail dialog
 * used when a row itself is clicked (see `PackingReportDialog` above) — that
 * dialog already knows how each status behaves, so the row buttons only need
 * to say which tab to land on, not re-implement any of that.
 */
function PackingRowActions({
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
