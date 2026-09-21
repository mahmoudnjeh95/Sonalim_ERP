import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { rowEnterProps } from "../../components/motion/rowMotion";
import { AlertTriangle, CheckCircle2, Recycle, Plus, Scale, Trash2, Users } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { listReportOptions, optionsFor } from "../../lib/reportOptions";
import { formatQuantity, productKgRatio, productUnit, productRequiresIntegerQuantity } from "../../lib/units";
import { formatWeightKg, fromKg, useWeightUnit } from "../../lib/weightUnit";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Checkbox } from "../../components/ui/checkbox";
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
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { GroupHeaderRow } from "../../components/patterns/GroupHeaderRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { useSelection } from "../../lib/useSelection";
import { groupRows, type GroupSpec } from "../../lib/groupRows";
import { useScrapTypeLabels } from "../../lib/scrapTypes";
import { BulkActionBar } from "../../components/patterns/BulkActionBar";
import {
  assignRegrindBatch,
  completeRegrindBatch,
  createRegrindBatch,
  listProducts,
  listRegrindBatches,
  listRegrindDefaults,
  listScrapRecords,
  listWorkCenters,
  listWorkOrders,
  recordScrap,
  type RegrindBatchSummary,
  type RegrindStage,
  type ScrapRecord,
} from "./api";
import { listLocations, listUoms } from "../warehouse/api";
import { TableLoadingRow } from "../../components/patterns/AppLoader";

const completeBatchSchema = z.object({
  location_id: z.string().min(1, "Required"),
  actual_output_quantity: z.coerce.number().positive("Must be > 0").optional(),
});
type CompleteBatchForm = z.infer<typeof completeBatchSchema>;

const assignBatchSchema = z.object({ team: z.string().min(1, "Required") });
type AssignBatchForm = z.infer<typeof assignBatchSchema>;

const scrapSchema = z
  .object({
    scrap_type: z.enum(["filling_dosing", "cutting"]),
    product_id: z.string().min(1, "Required"),
    quantity: z.coerce.number().positive("Must be > 0"),
    work_order_id: z.string().optional(),
    work_center_id: z.string().optional(),
    source_note: z.string().optional(),
  })
  .refine((data) => !!data.work_order_id || !!data.source_note?.trim(), {
    message: "Provide a work order or describe the source",
    path: ["source_note"],
  });
type ScrapForm = z.infer<typeof scrapSchema>;

const batchSchema = z.object({
  output_quantity: z.coerce.number().positive("Must be > 0"),
  // A regrind run names its line like any other OF.
  work_center_id: z.string().min(1, "Required"),
});
type BatchForm = z.infer<typeof batchSchema>;

// A loss is input minus output in floating point, so an exact match can leave a
// residue of 1e-16; this only absorbs that, it is not a size below which a loss is ignored.
const FLOAT_EPSILON = 1e-9;

const SCRAP_QUERY_KEY = ["production", "scrap-records"] as const;
const WORK_CENTERS_QUERY_KEY = ["production", "work-centers"] as const;
const WORK_ORDERS_QUERY_KEY = ["production", "work-orders"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const REGRIND_BATCHES_QUERY_KEY = ["production", "regrind-batches"] as const;
const REGRIND_DEFAULTS_QUERY_KEY = ["production", "regrind-defaults"] as const;
const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;
const REPORT_OPTIONS_QUERY_KEY = ["core", "report-options"] as const;
type RegrindFilter = "all" | "available" | "reground";
type GroupByOption = "none" | "of";

const REGRIND_STAGE_VARIANT: Record<RegrindStage, "default" | "warning" | "success" | "accent" | "destructive"> = {
  new: "default",
  assigned: "warning",
  finished: "success",
  suspended: "accent",
  cancelled: "destructive",
};

export function RegrindTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const SCRAP_TYPE_LABEL = useScrapTypeLabels();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [scrapDialogOpen, setScrapDialogOpen] = useState(false);
  const [batchDialogOpen, setBatchDialogOpen] = useState(false);
  const [selectedScrapIds, setSelectedScrapIds] = useState<string[]>([]);
  const [regrindFilter, setRegrindFilter] = useState<RegrindFilter>("all");
  const [sourceUncertain, setSourceUncertain] = useState(false);
  // Only chooses how weights are shown; the stored figures never change.
  const [weightUnit, setWeightUnit] = useWeightUnit();
  // Grouped by source OF by default, like the report lists: every OFR that
  // consumed scrap from an OF sits under that OF instead of repeating it per row.
  const [groupBy, setGroupBy] = useState<GroupByOption>("of");
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const collapseInitializedFor = useRef<GroupByOption | null>(null);

  const { data: scrapRecords = [], isLoading } = useQuery({ queryKey: SCRAP_QUERY_KEY, queryFn: () => listScrapRecords(token) });
  const { data: workCenters = [] } = useQuery({ queryKey: WORK_CENTERS_QUERY_KEY, queryFn: () => listWorkCenters(token) });
  const { data: workOrders = [] } = useQuery({ queryKey: WORK_ORDERS_QUERY_KEY, queryFn: () => listWorkOrders(token) });
  const ongoingWorkOrders = workOrders.filter((wo) => wo.status === "ongoing");
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: regrindBatches = [] } = useQuery({ queryKey: REGRIND_BATCHES_QUERY_KEY, queryFn: () => listRegrindBatches(token) });
  const { data: locations = [] } = useQuery({ queryKey: LOCATIONS_QUERY_KEY, queryFn: () => listLocations(token) });
  const { data: uoms = [] } = useQuery({ queryKey: ["core", "uoms"], queryFn: () => listUoms(token) });
  // Every regrind batch lands on this one product, always — see the backend
  // comment on create_regrind_batch. There is nothing left to choose here.
  const { data: regrindDefaults = [] } = useQuery({ queryKey: REGRIND_DEFAULTS_QUERY_KEY, queryFn: () => listRegrindDefaults(token) });
  const regrindOutputProductId = regrindDefaults.find((d) => d.input_product_id === null)?.output_product_id ?? null;
  const { data: reportOptions = [] } = useQuery({ queryKey: REPORT_OPTIONS_QUERY_KEY, queryFn: () => listReportOptions(token) });
  const teamOptions = optionsFor(reportOptions, "team");
  const canAssign = hasPermission("production.assign_regrind");
  // A batch's quantities are in its output product's own unit (tonnes for
  // rebroyat), not a fixed kg, so the view converts through that unit's ratio.
  const kgPerUnit = (productId: string | null | undefined): number | null => productKgRatio(productId, products, uoms);
  // Not a weight unit (or not loaded yet): show the number as stored, unconverted.
  const weightText = (productId: string | null | undefined, quantity: number) => {
    const ratio = kgPerUnit(productId);
    return ratio === null ? formatQuantity(quantity) : formatWeightKg(quantity * ratio, weightUnit);
  };
  const productName = (productId: string | null) => (productId ? products.find((p) => p.id === productId)?.name ?? productId : "—");
  const workOrderRef = (workOrderId: string) => workOrders.find((wo) => wo.id === workOrderId)?.reference ?? workOrderId;
  // The OFR that consumed a scrap record — null while it is still available.
  const regrindOrderRef = (scrap: ScrapRecord) => (scrap.regrind_work_order_id ? workOrderRef(scrap.regrind_work_order_id) : null);

  const scrapForm = useForm<ScrapForm>({ resolver: zodResolver(scrapSchema), defaultValues: { scrap_type: "cutting" } });

  const recordScrapMutation = useMutation({
    mutationFn: (input: ScrapForm) =>
      recordScrap(token, {
        scrap_type: input.scrap_type,
        product_id: input.product_id,
        quantity: input.quantity,
        work_order_id: sourceUncertain ? undefined : input.work_order_id || undefined,
        work_center_id: sourceUncertain ? undefined : input.work_center_id || undefined,
        source_note: sourceUncertain ? input.source_note?.trim() || undefined : undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: SCRAP_QUERY_KEY });
      setScrapDialogOpen(false);
      setSourceUncertain(false);
      scrapForm.reset({ scrap_type: "cutting" });
      toast.success(t("production.regrind.recorded"));
    },
    onError: (error) => toast.error(t("production.regrind.recordError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const batchForm = useForm<BatchForm>({ resolver: zodResolver(batchSchema) });

  const [assigningBatchId, setAssigningBatchId] = useState<string | null>(null);
  const assignBatchForm = useForm<AssignBatchForm>({ resolver: zodResolver(assignBatchSchema), defaultValues: { team: "" } });

  // The one step a responsable performs before a team can touch a regrind
  // batch: hands it to a team and starts its work order.
  const assignBatchMutation = useMutation({
    mutationFn: ({ id, team }: { id: string; team: string }) => assignRegrindBatch(token, id, team),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: REGRIND_BATCHES_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: WORK_ORDERS_QUERY_KEY });
      setAssigningBatchId(null);
      assignBatchForm.reset({ team: "" });
      toast.success(t("production.regrind.batches.assignedToast"));
    },
    onError: (error) => {
      toast.error(t("production.regrind.batches.assignError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  // Bulk assign: only a batch still in "new" is eligible -- an assigned or
  // finished one has nothing left for this action to do.
  const [bulkAssignOpen, setBulkAssignOpen] = useState(false);
  const batchSelection = useSelection(
    canAssign ? regrindBatches.filter((b) => b.stage === "new").map((b) => b.work_order_id) : [],
  );
  const bulkAssignForm = useForm<AssignBatchForm>({ resolver: zodResolver(assignBatchSchema), defaultValues: { team: "" } });

  const bulkAssignMutation = useMutation({
    mutationFn: async (input: AssignBatchForm) => {
      const ids = batchSelection.selectedIds;
      const settled = await Promise.allSettled(ids.map((id) => assignRegrindBatch(token, id, input.team)));
      return settled.filter((r) => r.status === "fulfilled").length;
    },
    onSuccess: (succeededCount) => {
      queryClient.invalidateQueries({ queryKey: REGRIND_BATCHES_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: WORK_ORDERS_QUERY_KEY });
      const failedCount = batchSelection.selectedIds.length - succeededCount;
      if (succeededCount > 0) toast.success(`${succeededCount} ${t("production.regrind.batches.bulkAssignSucceeded")}`);
      if (failedCount > 0) toast.error(`${failedCount} ${t("production.regrind.batches.bulkAssignFailed")}`);
      setBulkAssignOpen(false);
      bulkAssignForm.reset({ team: "" });
      batchSelection.clear();
    },
  });

  const [completingBatchId, setCompletingBatchId] = useState<string | null>(null);
  const completeBatchForm = useForm<CompleteBatchForm>({
    resolver: zodResolver(completeBatchSchema),
    defaultValues: { location_id: "", actual_output_quantity: undefined },
  });

  // Rebroyat is the one production output still received on its own work order:
  // a regrind batch has no report behind it, only the scrap it was built from.
  const completeBatchMutation = useMutation({
    mutationFn: ({ id, input }: { id: string; input: CompleteBatchForm }) =>
      completeRegrindBatch(token, id, {
        correlationId: crypto.randomUUID(),
        locationId: input.location_id,
        actualOutputQuantity: input.actual_output_quantity,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: REGRIND_BATCHES_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: WORK_ORDERS_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock"] });
      queryClient.invalidateQueries({ queryKey: ["warehouse", "stock", "moves"] });
      setCompletingBatchId(null);
      completeBatchForm.reset({ location_id: "", actual_output_quantity: undefined });
      toast.success(t("production.regrind.batches.completedToast"));
    },
    onError: (error) => {
      toast.error(t("production.regrind.batches.completeError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const createBatchMutation = useMutation({
    mutationFn: (input: { output_quantity: number; work_center_id: string }) =>
      createRegrindBatch(token, { ...input, scrap_record_ids: selectedScrapIds }),
    onSuccess: (batch) => {
      queryClient.invalidateQueries({ queryKey: SCRAP_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: REGRIND_BATCHES_QUERY_KEY });
      setBatchDialogOpen(false);
      setSelectedScrapIds([]);
      batchForm.reset();
      toast.success(t("production.regrind.batchCreated"), {
        description: `${productName(batch.work_order.product_id)} · ${t("production.regrind.inputTotal")}: ${weightText(batch.work_order.product_id, batch.input_quantity_total)} ${weightUnit}`,
      });
    },
    onError: (error) => toast.error(t("production.regrind.createBatchError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  function handleBatchSubmit(input: BatchForm) {
    createBatchMutation.mutate({
      output_quantity: input.output_quantity,
      work_center_id: input.work_center_id,
    });
  }

  const availableCount = scrapRecords.filter((s) => !s.is_reground).length;
  const regroundCount = scrapRecords.filter((s) => s.is_reground).length;
  // Only a finished batch has a measured écart — a batch still new or assigned
  // has not been weighed yet, so it contributes nothing to the total.
  const totalLossKg = regrindBatches.reduce((sum, b) => sum + (b.loss_quantity ?? 0) * (kgPerUnit(b.output_product_id) ?? 0), 0);
  const regrindFilteredRecords =
    regrindFilter === "all"
      ? scrapRecords
      : scrapRecords.filter((s) => (regrindFilter === "reground" ? s.is_reground : !s.is_reground));

  function scrapTypeLabel(record: ScrapRecord): string {
    return SCRAP_TYPE_LABEL[record.scrap_type];
  }

  function workCenterLabel(workCenterId: string | null): string {
    if (!workCenterId) return "—";
    return workCenters.find((wc) => wc.id === workCenterId)?.code ?? workCenterId;
  }

  const columnFilterFields: FilterField<ScrapRecord>[] = [
    { key: "work_order_id", kind: "text", getValue: (s) => (s.work_order_id ? workOrderRef(s.work_order_id) : s.source_note) },
    { key: "regrind_work_order_id", kind: "text", getValue: (s) => regrindOrderRef(s) },
    { key: "scrap_type", kind: "text", getValue: (s) => scrapTypeLabel(s) },
    { key: "product_id", kind: "text", getValue: (s) => productName(s.product_id) },
    { key: "quantity", kind: "range", getValue: (s) => s.quantity },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredScrapRecords = columnFilters.apply(regrindFilteredRecords);

  function toggleSelected(id: string) {
    setSelectedScrapIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  const scrapColumns: ColumnDef<ScrapRecord>[] = [
    {
      key: "select",
      header: "",
      defaultWidth: 40,
      alwaysVisible: true,
      cell: (scrap) =>
        !scrap.is_reground && (
          <Checkbox
            checked={selectedScrapIds.includes(scrap.id)}
            onCheckedChange={() => toggleSelected(scrap.id)}
            aria-label={t("production.regrind.selectForRegrind")}
          />
        ),
    },
    {
      key: "work_order_id",
      header: t("production.regrind.column.workOrder"),
      defaultWidth: 180,
      cell: (scrap) => {
        const label = scrap.work_order_id ? workOrderRef(scrap.work_order_id) : scrap.source_note ?? "—";
        return (
          <span className="block truncate font-medium" title={label}>
            {label}
          </span>
        );
      },
      filterCell: {
        type: "text",
        value: columnFilters.text.work_order_id ?? "",
        onChange: (v) => columnFilters.setTextValue("work_order_id", v),
        placeholder: t("production.regrind.column.workOrder"),
      },
      sortValue: (scrap) => (scrap.work_order_id ? workOrderRef(scrap.work_order_id) : scrap.source_note ?? null),
    },
    {
      key: "regrind_work_order_id",
      header: t("production.regrind.column.regrindOrder"),
      defaultWidth: 180,
      cell: (scrap) => {
        const label = regrindOrderRef(scrap);
        return label ? (
          <span className="block truncate font-medium" title={label}>
            {label}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        );
      },
      filterCell: {
        type: "text",
        value: columnFilters.text.regrind_work_order_id ?? "",
        onChange: (v) => columnFilters.setTextValue("regrind_work_order_id", v),
        placeholder: t("production.regrind.column.regrindOrder"),
      },
      sortValue: (scrap) => regrindOrderRef(scrap),
    },
    {
      key: "line",
      header: t("production.regrind.field.line"),
      defaultWidth: 140,
      cell: (scrap) => <span className="text-muted-foreground">{workCenterLabel(scrap.work_center_id)}</span>,
      sortValue: (scrap) => workCenterLabel(scrap.work_center_id),
    },
    {
      key: "scrap_type",
      header: t("production.regrind.column.type"),
      defaultWidth: 160,
      cell: (scrap) => <span className="text-muted-foreground">{scrapTypeLabel(scrap)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.scrap_type ?? "",
        onChange: (v) => columnFilters.setTextValue("scrap_type", v),
        placeholder: t("production.regrind.column.type"),
      },
      sortValue: (scrap) => scrapTypeLabel(scrap),
    },
    {
      key: "product_id",
      header: t("production.regrind.column.product"),
      defaultWidth: 180,
      cell: (scrap) => productName(scrap.product_id),
      filterCell: {
        type: "text",
        value: columnFilters.text.product_id ?? "",
        onChange: (v) => columnFilters.setTextValue("product_id", v),
        placeholder: t("production.regrind.column.product"),
      },
      sortValue: (scrap) => productName(scrap.product_id),
    },
    {
      key: "quantity",
      header: t("production.regrind.column.quantity"),
      defaultWidth: 140,
      cell: (scrap) => <span className="tabular-nums text-muted-foreground">{scrap.quantity}</span>,
      filterCell: {
        type: "range",
        min: columnFilters.range.quantity?.min ?? "",
        max: columnFilters.range.quantity?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("quantity", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("quantity", "max", v),
      },
      sortValue: (scrap) => scrap.quantity,
    },
    {
      key: "status",
      header: t("production.regrind.column.status"),
      defaultWidth: 140,
      cell: (scrap) =>
        scrap.is_reground ? (
          <Badge variant="success" dot>
            {t("production.regrind.reground")}
          </Badge>
        ) : (
          <Badge variant="warning" dot>
            {t("production.regrind.available")}
          </Badge>
        ),
      sortValue: (scrap) => scrap.is_reground,
    },
  ];
  const scrapTable = useTableColumns("production.regrind.scrap", scrapColumns);
  const sortedScrapRecords = scrapTable.sortRows(filteredScrapRecords);

  function toggleGroup(key: string) {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  // Scrap of uncertain origin has no source OF — it all lands in one group.
  const groupSpec: GroupSpec<ScrapRecord> | undefined =
    groupBy === "none"
      ? undefined
      : {
          key: "of",
          label: t("production.reports.groupBy.of"),
          getGroupKey: (s) => s.work_order_id ?? "",
          getGroupLabel: (s) => (s.work_order_id ? workOrderRef(s.work_order_id) : t("common.none")),
        };
  const scrapGroups = groupRows(sortedScrapRecords, groupSpec);

  // Only the first group starts open; re-collapse the rest each time the
  // grouping changes rather than only on first mount.
  useEffect(() => {
    if (groupBy === "none" || scrapGroups.length === 0) return;
    if (collapseInitializedFor.current === groupBy) return;
    collapseInitializedFor.current = groupBy;
    setCollapsedGroups(new Set(scrapGroups.slice(1).map((g) => g.key)));
  }, [groupBy, scrapGroups]);

  const batchColumns: ColumnDef<RegrindBatchSummary>[] = [
    ...(canAssign
      ? [
          {
            key: "select",
            header: (
              <Checkbox
                checked={batchSelection.allSelected}
                onCheckedChange={() => batchSelection.toggleAll()}
                aria-label={t("common.selectAll")}
              />
            ),
            defaultWidth: 40,
            alwaysVisible: true,
            cell: (batch) =>
              batch.stage === "new" && (
                <Checkbox
                  checked={batchSelection.isSelected(batch.work_order_id)}
                  onCheckedChange={() => batchSelection.toggle(batch.work_order_id)}
                  aria-label={t("production.regrind.batches.assign")}
                />
              ),
          } satisfies ColumnDef<RegrindBatchSummary>,
        ]
      : []),
    {
      key: "output",
      header: t("production.regrind.batches.column.output"),
      defaultWidth: 200,
      cell: (batch) => <span className="font-medium">{productName(batch.output_product_id)}</span>,
      sortValue: (batch) => productName(batch.output_product_id),
    },
    {
      key: "outputQuantity",
      header: `${t("production.regrind.batches.column.outputQuantity")} (${weightUnit})`,
      defaultWidth: 160,
      cell: (batch) =>
        batch.actual_output_quantity !== null ? (
          <span className="tabular-nums text-muted-foreground">{weightText(batch.output_product_id, batch.actual_output_quantity)}</span>
        ) : (
          <span className="tabular-nums text-muted-foreground">
            {weightText(batch.output_product_id, batch.output_quantity)} <span className="text-xs italic">({t("production.regrind.batches.estimated")})</span>
          </span>
        ),
      sortValue: (batch) => batch.actual_output_quantity ?? batch.output_quantity,
    },
    {
      key: "inputTotal",
      header: `${t("production.regrind.batches.column.inputTotal")} (${weightUnit})`,
      defaultWidth: 140,
      cell: (batch) => <span className="tabular-nums text-muted-foreground">{weightText(batch.output_product_id, batch.input_quantity_total)}</span>,
      sortValue: (batch) => batch.input_quantity_total,
    },
    {
      key: "loss",
      header: `${t("production.regrind.batches.column.loss")} (${weightUnit})`,
      defaultWidth: 150,
      // Only known once the batch is finished — before that there is nothing to
      // highlight yet, only a plan. Any écart, once measured, is called out in red
      // with a warning icon rather than blending into the row; no size is "too small".
      cell: (batch) =>
        batch.loss_quantity === null ? (
          <span className="text-muted-foreground" title={t("production.regrind.batches.pending")}>
            —
          </span>
        ) : Math.abs(batch.loss_quantity) > FLOAT_EPSILON ? (
          <span className="inline-flex items-center gap-1 font-medium text-destructive">
            <AlertTriangle className="h-3.5 w-3.5" />
            <span className="tabular-nums">{weightText(batch.output_product_id, batch.loss_quantity)}</span>
          </span>
        ) : (
          <span className="tabular-nums text-muted-foreground">{weightText(batch.output_product_id, batch.loss_quantity)}</span>
        ),
      sortValue: (batch) => batch.loss_quantity ?? Number.NEGATIVE_INFINITY,
    },
    {
      key: "status",
      header: t("production.regrind.batches.column.status"),
      defaultWidth: 130,
      cell: (batch) => (
        <Badge variant={REGRIND_STAGE_VARIANT[batch.stage]} dot>
          {t(`production.regrind.batches.stage.${batch.stage}`)}
        </Badge>
      ),
      sortValue: (batch) => batch.stage,
    },
    {
      key: "team",
      header: t("production.regrind.batches.column.team"),
      defaultWidth: 150,
      cell: (batch) => <span className="text-muted-foreground">{batch.assigned_team ?? "—"}</span>,
      sortValue: (batch) => batch.assigned_team,
    },
    {
      key: "date",
      header: t("production.regrind.batches.column.date"),
      defaultWidth: 160,
      cell: (batch) => <span className="whitespace-nowrap text-muted-foreground">{new Date(batch.created_at).toLocaleDateString()}</span>,
      sortValue: (batch) => batch.created_at,
    },
    {
      key: "action",
      header: t("production.regrind.batches.column.action"),
      defaultWidth: 160,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right",
      cell: (batch) => {
        if (batch.stage === "new") {
          return canAssign ? (
            <Dialog
              open={assigningBatchId === batch.work_order_id}
              onOpenChange={(open) => {
                setAssigningBatchId(open ? batch.work_order_id : null);
                if (open) assignBatchForm.reset({ team: "" });
              }}
            >
              <DialogTrigger asChild>
                <Button size="sm" variant="outline">
                  <Users className="h-3.5 w-3.5" />
                  {t("production.regrind.batches.assign")}
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>{t("production.regrind.batches.dialog.assign.title")}</DialogTitle>
                  <DialogDescription>{t("production.regrind.batches.dialog.assign.description")}</DialogDescription>
                </DialogHeader>
                {teamOptions.length === 0 ? (
                  <div className="rounded-lg border border-warning/20 bg-warning-soft p-3 text-sm text-warning">
                    {t("production.regrind.batches.noTeamsConfigured")}
                  </div>
                ) : (
                  <form
                    className="space-y-4"
                    onSubmit={assignBatchForm.handleSubmit((input) =>
                      assignBatchMutation.mutate({ id: batch.work_order_id, team: input.team }),
                    )}
                  >
                    <div className="space-y-1.5">
                      <Label htmlFor={`batch_team_${batch.work_order_id}`}>{t("production.regrind.batches.field.team")}</Label>
                      <Select id={`batch_team_${batch.work_order_id}`} {...assignBatchForm.register("team")}>
                        <option value="">—</option>
                        {teamOptions.map((team) => (
                          <option key={team} value={team}>
                            {team}
                          </option>
                        ))}
                      </Select>
                      {assignBatchForm.formState.errors.team && (
                        <p className="text-sm text-destructive">{assignBatchForm.formState.errors.team.message}</p>
                      )}
                    </div>
                    <Button type="submit" className="w-full" disabled={assignBatchMutation.isPending}>
                      {assignBatchMutation.isPending ? t("production.regrind.batches.assigning") : t("production.regrind.batches.assign")}
                    </Button>
                  </form>
                )}
              </DialogContent>
            </Dialog>
          ) : null;
        }

        if (batch.stage !== "assigned") return null;

        return (
          <Dialog
            open={completingBatchId === batch.work_order_id}
            onOpenChange={(open) => {
              setCompletingBatchId(open ? batch.work_order_id : null);
              if (open) completeBatchForm.reset({ location_id: "", actual_output_quantity: batch.output_quantity });
            }}
          >
            <DialogTrigger asChild>
              <Button size="sm" variant="outline">
                <CheckCircle2 className="h-3.5 w-3.5" />
                {t("production.regrind.batches.complete")}
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{t("production.regrind.batches.dialog.complete.title")}</DialogTitle>
                <DialogDescription>{t("production.regrind.batches.dialog.complete.description")}</DialogDescription>
              </DialogHeader>
              <form
                className="space-y-4"
                onSubmit={completeBatchForm.handleSubmit((input) =>
                  completeBatchMutation.mutate({ id: batch.work_order_id, input }),
                )}
              >
                <div className="space-y-1.5">
                  <Label htmlFor={`batch_location_${batch.work_order_id}`}>
                    {t("production.regrind.batches.field.destinationLocation")}
                  </Label>
                  <Select id={`batch_location_${batch.work_order_id}`} {...completeBatchForm.register("location_id")}>
                    <option value="">—</option>
                    {locations.map((location) => (
                      <option key={location.id} value={location.id}>
                        {location.name}
                      </option>
                    ))}
                  </Select>
                  {completeBatchForm.formState.errors.location_id && (
                    <p className="text-sm text-destructive">{completeBatchForm.formState.errors.location_id.message}</p>
                  )}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`batch_output_${batch.work_order_id}`}>
                    {t("production.regrind.batches.field.actualOutput")}
                    {productUnit(batch.output_product_id, products, uoms) && (
                      <span className="text-muted-foreground"> ({productUnit(batch.output_product_id, products, uoms)})</span>
                    )}
                  </Label>
                  <Input
                    id={`batch_output_${batch.work_order_id}`}
                    type="number"
                    step={productRequiresIntegerQuantity(batch.output_product_id, products, uoms) ? "1" : "any"}
                    {...completeBatchForm.register("actual_output_quantity")}
                  />
                </div>
                <Button type="submit" className="w-full" disabled={completeBatchMutation.isPending}>
                  {completeBatchMutation.isPending
                    ? t("production.regrind.batches.completing")
                    : t("production.regrind.batches.complete")}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
        );
      },
    },
  ];
  const batchTable = useTableColumns("production.regrind.batches", batchColumns);
  const sortedRegrindBatches = batchTable.sortRows(regrindBatches);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
        <StatCard label={t("production.regrind.stat.total")} value={scrapRecords.length} icon={<Recycle className="h-5 w-5" />} />
        <StatCard label={t("production.regrind.stat.available")} value={availableCount} icon={<Trash2 className="h-5 w-5" />} accent="warning" />
        <StatCard label={t("production.regrind.stat.reground")} value={regroundCount} icon={<CheckCircle2 className="h-5 w-5" />} accent="success" />
        <StatCard
          label={`${t("production.regrind.stat.totalLossLabel")} (${weightUnit})`}
          value={fromKg(totalLossKg, weightUnit)}
          decimals={weightUnit === "t" ? 5 : 2}
          icon={<Scale className="h-5 w-5" />}
          accent="destructive"
        />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("production.regrind.table.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("production.regrind.table.subtitle")}</p>
            </div>
            <FilterTabs
              value={regrindFilter}
              onChange={setRegrindFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "available", label: t("production.regrind.available") },
                { value: "reground", label: t("production.regrind.reground") },
              ]}
            />
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">{t("production.reports.groupBy.label")}:</span>
              <FilterTabs
                value={groupBy}
                onChange={setGroupBy}
                options={[
                  { value: "none", label: t("production.reports.groupBy.none") },
                  { value: "of", label: t("production.reports.groupBy.of") },
                ]}
              />
            </div>
            {columnFilters.isActive && (
              <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                {t("common.clearFilters")}
              </Button>
            )}
            <ColumnVisibilityMenu
              columns={scrapColumns}
              isVisible={scrapTable.isVisible}
              onToggle={scrapTable.toggleVisible}
              onReset={scrapTable.resetAll}
            />
          </div>
          <div className="flex gap-2">
            <Dialog
              open={scrapDialogOpen}
              onOpenChange={(open) => {
                setScrapDialogOpen(open);
                if (!open) {
                  setSourceUncertain(false);
                }
              }}
            >
              <DialogTrigger asChild>
                <Button variant="outline">
                  <Plus className="h-4 w-4" />
                  {t("production.regrind.recordScrap")}
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>{t("production.regrind.dialog.scrap.title")}</DialogTitle>
                  <DialogDescription>{t("production.regrind.dialog.scrap.description")}</DialogDescription>
                </DialogHeader>
                <form className="space-y-4" onSubmit={scrapForm.handleSubmit((input) => recordScrapMutation.mutate(input))}>
                  <div className="flex items-center justify-between">
                    <Label>{sourceUncertain ? t("production.regrind.sourceUncertain") : t("production.regrind.sourceKnown")}</Label>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setSourceUncertain((prev) => !prev);
                        scrapForm.setValue("work_order_id", "");
                        scrapForm.setValue("work_center_id", "");
                        scrapForm.setValue("source_note", "");
                      }}
                    >
                      {sourceUncertain ? t("production.regrind.sourceKnown") : t("production.regrind.sourceUncertain")}
                    </Button>
                  </div>

                  {!sourceUncertain && (
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1.5">
                        <Label htmlFor="work_order_id">{t("production.regrind.field.workOrderId")}</Label>
                        <Select id="work_order_id" {...scrapForm.register("work_order_id")}>
                          <option value="">—</option>
                          {ongoingWorkOrders.map((wo) => (
                            <option key={wo.id} value={wo.id}>
                              {wo.reference} · {productName(wo.product_id)} · {wo.planned_quantity}
                            </option>
                          ))}
                        </Select>
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor="work_center_id">{t("production.regrind.field.line")}</Label>
                        <Select id="work_center_id" {...scrapForm.register("work_center_id")}>
                          <option value="">—</option>
                          {workCenters.map((wc) => (
                            <option key={wc.id} value={wc.id}>
                              {wc.code} — {wc.name}
                            </option>
                          ))}
                        </Select>
                      </div>
                    </div>
                  )}

                  {sourceUncertain && (
                    <div className="space-y-1.5">
                      <Label htmlFor="source_note">{t("production.regrind.field.sourceNote")}</Label>
                      <Input
                        id="source_note"
                        placeholder={t("production.regrind.field.sourceNotePlaceholder")}
                        {...scrapForm.register("source_note")}
                      />
                      {scrapForm.formState.errors.source_note && (
                        <p className="text-sm text-destructive">{scrapForm.formState.errors.source_note.message}</p>
                      )}
                    </div>
                  )}

                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label htmlFor="scrap_type">{t("production.regrind.field.scrapType")}</Label>
                      <Select id="scrap_type" {...scrapForm.register("scrap_type")}>
                        <option value="cutting">{t("production.regrind.scrapType.cutting")}</option>
                        <option value="filling_dosing">{t("production.regrind.scrapType.fillingDosing")}</option>
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="quantity">
                        {t("production.regrind.field.quantity")}
                        {productUnit(scrapForm.watch("product_id"), products, uoms) && (
                          <span className="text-muted-foreground"> ({productUnit(scrapForm.watch("product_id"), products, uoms)})</span>
                        )}
                      </Label>
                      <Input
                        id="quantity"
                        type="number"
                        step={productRequiresIntegerQuantity(scrapForm.watch("product_id"), products, uoms) ? "1" : "any"}
                        {...scrapForm.register("quantity")}
                      />
                      {scrapForm.formState.errors.quantity && (
                        <p className="text-sm text-destructive">{scrapForm.formState.errors.quantity.message}</p>
                      )}
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <Label htmlFor="product_id">{t("production.regrind.field.scrapProductId")}</Label>
                    {/* product_id has a real FK to core.products (scrap_records_product_id_fkey) --
                        free text here used to reach the backend as-is and crash the request with an
                        unhandled ForeignKeyViolation, which the browser then misreported as CORS
                        blocked. Only a value that actually exists in this list can be submitted. */}
                    <Select id="product_id" {...scrapForm.register("product_id")}>
                      <option value="">—</option>
                      {products.map((product) => (
                        <option key={product.id} value={product.id}>
                          {product.name}
                        </option>
                      ))}
                    </Select>
                    {scrapForm.formState.errors.product_id && (
                      <p className="text-sm text-destructive">{scrapForm.formState.errors.product_id.message}</p>
                    )}
                  </div>

                  {recordScrapMutation.isError && (
                    <p className="text-sm text-destructive">
                      {recordScrapMutation.error instanceof ApiError ? recordScrapMutation.error.message : t("production.regrind.recordError")}
                    </p>
                  )}
                  <Button type="submit" className="w-full" disabled={recordScrapMutation.isPending}>
                    {recordScrapMutation.isPending ? t("production.regrind.recording") : t("production.regrind.recordScrap")}
                  </Button>
                </form>
              </DialogContent>
            </Dialog>

            <Dialog open={batchDialogOpen} onOpenChange={setBatchDialogOpen}>
              <DialogTrigger asChild>
                <Button disabled={selectedScrapIds.length === 0} title={selectedScrapIds.length === 0 ? t("production.regrind.selectScrapFirst") : undefined}>
                  <Recycle className="h-4 w-4" />
                  {t("production.regrind.createBatch")} ({selectedScrapIds.length})
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>{t("production.regrind.dialog.batch.title")}</DialogTitle>
                  <DialogDescription>
                    {t("production.regrind.dialog.batch.consumes")} {selectedScrapIds.length}{" "}
                    {selectedScrapIds.length === 1 ? t("production.regrind.dialog.batch.recordSingular") : t("production.regrind.dialog.batch.recordPlural")}{" "}
                    {t("production.regrind.dialog.batch.intoWorkOrder")}
                  </DialogDescription>
                </DialogHeader>

                {regrindOutputProductId === null ? (
                  <div className="space-y-3 rounded-lg border border-warning/20 bg-warning-soft p-3 text-sm text-warning">
                    <p>{t("production.regrind.noDefaultConfigured")}</p>
                    <Link
                      to="/production?tab=settings"
                      className="inline-block font-medium underline underline-offset-2"
                      onClick={() => setBatchDialogOpen(false)}
                    >
                      {t("production.regrind.goToSettings")}
                    </Link>
                  </div>
                ) : (
                  <form className="space-y-4" onSubmit={batchForm.handleSubmit(handleBatchSubmit)}>
                    <div className="space-y-1.5">
                      {/* Not a choice: every regrind batch lands on this one product. */}
                      <Label>{t("production.regrind.field.output")}</Label>
                      <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm font-medium">
                        {productName(regrindOutputProductId)}
                      </p>
                    </div>

                    <div className="space-y-1.5">
                      <Label htmlFor="output_quantity">
                        {t("production.regrind.field.outputQuantity")}
                        {productUnit(regrindOutputProductId, products, uoms) && (
                          <span className="text-muted-foreground"> ({productUnit(regrindOutputProductId, products, uoms)})</span>
                        )}
                      </Label>
                      <Input
                        id="output_quantity"
                        type="number"
                        step={productRequiresIntegerQuantity(regrindOutputProductId, products, uoms) ? "1" : "any"}
                        {...batchForm.register("output_quantity")}
                      />
                      {batchForm.formState.errors.output_quantity && (
                        <p className="text-sm text-destructive">{batchForm.formState.errors.output_quantity.message}</p>
                      )}
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="work_center_id">{t("production.regrind.field.workCenter")}</Label>
                      <Select id="work_center_id" {...batchForm.register("work_center_id")}>
                        <option value="">—</option>
                        {workCenters.map((wc) => (
                          <option key={wc.id} value={wc.id}>
                            {wc.code} — {wc.name}
                          </option>
                        ))}
                      </Select>
                      {batchForm.formState.errors.work_center_id && (
                        <p className="text-sm text-destructive">{batchForm.formState.errors.work_center_id.message}</p>
                      )}
                    </div>
                    {createBatchMutation.isError && (
                      <p className="text-sm text-destructive">
                        {createBatchMutation.error instanceof ApiError ? createBatchMutation.error.message : t("production.regrind.createBatchError")}
                      </p>
                    )}
                    <Button type="submit" className="w-full" disabled={createBatchMutation.isPending}>
                      {createBatchMutation.isPending ? t("production.regrind.creatingBatch") : t("production.regrind.createBatchButton")}
                    </Button>
                  </form>
                )}
              </DialogContent>
            </Dialog>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <Table colWidths={scrapTable.colWidths}>
            <TableHeader>
              <TableRow>
                {scrapTable.visibleColumns.map((column) => (
                  <ResizableTableHead
                    key={column.key}
                    width={scrapTable.getWidth(column.key)}
                    onResize={(width) => scrapTable.setWidth(column.key, width)}
                    className={column.headerClassName}
                    sortDirection={scrapTable.sortDirectionFor(column.key)}
                    onSort={column.sortValue ? () => scrapTable.toggleSort(column.key) : undefined}
                  >
                    {column.header}
                  </ResizableTableHead>
                ))}
              </TableRow>
              <ColumnFilterRow cells={scrapTable.visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
            </TableHeader>
            <TableBody>
              {isLoading && <TableLoadingRow colSpan={scrapTable.visibleColumns.length} />}
              {!isLoading && filteredScrapRecords.length === 0 && (
                <TableRow>
                  <TableCell colSpan={scrapTable.visibleColumns.length} className="p-0">
                    <EmptyState
                      icon={<Recycle className="h-5 w-5" />}
                      title={t("production.regrind.empty.title")}
                      description={t("production.regrind.empty.description")}
                    />
                  </TableCell>
                </TableRow>
              )}
              <AnimatePresence initial={false}>
                {(() => {
                  let rowIndex = 0;
                  return scrapGroups.flatMap((group) => {
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
                          colSpan={scrapTable.visibleColumns.length}
                        />,
                      );
                    }
                    if (!collapsed) {
                      for (const scrap of group.rows) {
                        rows.push(
                          <motion.tr
                            key={scrap.id}
                            {...rowEnterProps(rowIndex++)}
                            className="border-b border-border last:border-0 hover:bg-muted/50"
                          >
                            {scrapTable.visibleColumns.map((column) => (
                              <TableCell key={column.key} className={column.cellClassName}>
                                {column.cell(scrap)}
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
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("production.regrind.batches.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("production.regrind.batches.subtitle")}</p>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">{t("production.regrind.unit.label")}:</span>
              <FilterTabs
                value={weightUnit}
                onChange={setWeightUnit}
                options={[
                  { value: "kg", label: t("production.regrind.unit.kg") },
                  { value: "t", label: t("production.regrind.unit.tonne") },
                ]}
              />
            </div>
            <ColumnVisibilityMenu
              columns={batchColumns}
              isVisible={batchTable.isVisible}
              onToggle={batchTable.toggleVisible}
              onReset={batchTable.resetAll}
            />
          </div>
          {canAssign && (
            <BulkActionBar count={batchSelection.count} onClear={batchSelection.clear}>
              <Dialog
                open={bulkAssignOpen}
                onOpenChange={(open) => {
                  setBulkAssignOpen(open);
                  if (open) bulkAssignForm.reset({ team: "" });
                }}
              >
                <DialogTrigger asChild>
                  <Button size="sm">
                    <Users className="h-3.5 w-3.5" />
                    {t("production.regrind.batches.bulkAssign")}
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>{t("production.regrind.batches.dialog.bulkAssign.title")}</DialogTitle>
                    <DialogDescription>{t("production.regrind.batches.dialog.bulkAssign.description")}</DialogDescription>
                  </DialogHeader>
                  {/* The review step: what "bulk" actually means here, spelled out
                      row by row, before one team gets handed all of it at once. */}
                  <div className="max-h-48 space-y-1 overflow-y-auto rounded-md border border-border p-2">
                    {regrindBatches
                      .filter((batch) => batchSelection.isSelected(batch.work_order_id))
                      .map((batch) => (
                        <div key={batch.work_order_id} className="flex items-center justify-between gap-2 text-sm">
                          <span className="font-medium">{productName(batch.output_product_id)}</span>
                          <span className="tabular-nums text-muted-foreground">{weightText(batch.output_product_id, batch.output_quantity)} {weightUnit}</span>
                        </div>
                      ))}
                  </div>
                  {teamOptions.length === 0 ? (
                    <div className="rounded-lg border border-warning/20 bg-warning-soft p-3 text-sm text-warning">
                      {t("production.regrind.batches.noTeamsConfigured")}
                    </div>
                  ) : (
                    <form
                      className="space-y-4"
                      onSubmit={bulkAssignForm.handleSubmit((input) => bulkAssignMutation.mutate(input))}
                    >
                      <div className="space-y-1.5">
                        <Label htmlFor="bulk_batch_team">{t("production.regrind.batches.field.team")}</Label>
                        <Select id="bulk_batch_team" {...bulkAssignForm.register("team")}>
                          <option value="">—</option>
                          {teamOptions.map((team) => (
                            <option key={team} value={team}>
                              {team}
                            </option>
                          ))}
                        </Select>
                        {bulkAssignForm.formState.errors.team && (
                          <p className="text-sm text-destructive">{bulkAssignForm.formState.errors.team.message}</p>
                        )}
                      </div>
                      <Button type="submit" className="w-full" disabled={bulkAssignMutation.isPending}>
                        {bulkAssignMutation.isPending
                          ? t("production.regrind.batches.bulkAssigning")
                          : t("production.regrind.batches.bulkAssign")}
                      </Button>
                    </form>
                  )}
                </DialogContent>
              </Dialog>
            </BulkActionBar>
          )}
        </CardHeader>
        <CardContent className="p-0">
          <Table colWidths={batchTable.colWidths}>
            <TableHeader>
              <TableRow>
                {batchTable.visibleColumns.map((column) => (
                  <ResizableTableHead
                    key={column.key}
                    width={batchTable.getWidth(column.key)}
                    onResize={(width) => batchTable.setWidth(column.key, width)}
                    className={column.headerClassName}
                    sortDirection={batchTable.sortDirectionFor(column.key)}
                    onSort={column.sortValue ? () => batchTable.toggleSort(column.key) : undefined}
                  >
                    {column.header}
                  </ResizableTableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {regrindBatches.length === 0 && (
                <TableRow>
                  <TableCell colSpan={batchTable.visibleColumns.length} className="py-8 text-center text-muted-foreground">
                    {t("production.regrind.batches.empty")}
                  </TableCell>
                </TableRow>
              )}
              {sortedRegrindBatches.map((batch) => (
                <TableRow key={batch.work_order_id}>
                  {batchTable.visibleColumns.map((column) => (
                    <TableCell key={column.key} className={column.cellClassName}>
                      {column.cell(batch)}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
