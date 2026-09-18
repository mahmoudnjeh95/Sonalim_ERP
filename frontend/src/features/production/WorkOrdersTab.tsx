import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, type UseFormReturn } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  ArrowRight,
  Boxes,
  CheckCircle2,
  ClipboardList,
  Clock3,
  Eye,
  Factory,
  Gauge,
  PackageCheck,
  PauseCircle,
  Pencil,
  PlayCircle,
  Plus,
  ShieldCheck,
  Sparkles,
  Timer,
  TrendingUp,
  XCircle,
  Zap,
} from "lucide-react";
import { toast } from "sonner";
import EmptyOrdersIllustration from "../../assets/illustrations/empty-states/empty-no-orders.svg?react";
import ProductionEmptyStateIllustration from "../../assets/illustrations/production/production-empty-state.svg?react";
import ProductPackagingThumbIllustration from "../../assets/illustrations/production/product-packaging-thumb.svg?react";
import ProductionFlowIllustration from "../../assets/illustrations/production/production-flow.svg?react";
import PlannedStatusIcon from "../../assets/icons/status/status-planned.svg?react";
import OngoingStatusIcon from "../../assets/icons/status/status-ongoing.svg?react";
import SuspendedStatusIcon from "../../assets/icons/status/status-suspended.svg?react";
import ClosedStatusIcon from "../../assets/icons/status/status-closed.svg?react";
import CancelledStatusIcon from "../../assets/icons/status/status-cancelled.svg?react";
import { z } from "zod";
import { useAuth } from "../../lib/auth";
import { currentLocale, useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { rowEnterProps, highlightRowEnterProps } from "../../components/motion/rowMotion";
import { Badge } from "../../components/ui/badge";
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
import {
  cancelWorkOrder,
  closeWorkOrder,
  createWorkOrder,
  getWorkOrderConsolidation,
  getWorkOrderYield,
  listPackagingBoms,
  listProducts,
  listRecipes,
  listWorkCenters,
  listSupervisorOptions,
  listWorkOrderInputs,
  supervisorLabel,
  listWorkOrderYields,
  listWorkOrders,
  listRegrindBatches,
  listReports,
  resumeWorkOrder,
  startWorkOrder,
  suspendWorkOrder,
  updateWorkOrder,
  type PackagingBom,
  type Product,
  type Recipe,
  type SupervisorOption,
  type UpdateWorkOrderInput,
  type WorkCenter,
  type WorkOrder,
  type WorkOrderStatus,
} from "./api";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { RowActionsMenu, type RowAction } from "../../components/patterns/RowActionsMenu";
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { listQualityReports } from "../qc/api";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { cn } from "../../lib/utils";

function todayDateInputValue(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function nowDatetimeLocalValue(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

// Lightweight by design: work center, PC/PL and a start date. The product is
// named later by Conditionnement's first packaging report; the quantity is
// assigned later too, once known, via edit.
type NewOrderForm = {
  work_center_id: string;
  product_type: "PC" | "PL";
  start_date: string;
  supervisor_id?: string;
};

type EditOrderForm = {
  planned_quantity?: number;
  work_center_id?: string;
  supervisor_id?: string;
  recipe_id?: string;
  packaging_bom_id?: string;
  product_type?: string;
};

type CloseOrderForm = {
  closed_at: string;
};

const PROGRESS: Record<WorkOrderStatus, number> = {
  planned: 8,
  ongoing: 55,
  suspended: 55,
  closed: 100,
  cancelled: 100,
};
const QUERY_KEY = ["production", "work-orders"] as const;
const WORK_CENTERS_QUERY_KEY = ["production", "work-centers"] as const;
const RECIPES_QUERY_KEY = ["production", "recipes"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const PACKAGING_BOMS_QUERY_KEY = ["production", "packaging-boms"] as const;
const YIELDS_QUERY_KEY = ["production", "work-order-yields"] as const;
const REGRIND_BATCHES_QUERY_KEY = ["production", "regrind-batches"] as const;
const SUPERVISORS_QUERY_KEY = ["production", "work-order-supervisors"] as const;
type StatusFilter = "all" | WorkOrderStatus;

export function WorkOrdersTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [detailsId, setDetailsId] = useState<string | null>(null);
  const [closingId, setClosingId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [typeFilter, setTypeFilter] = useState<"all" | "PC" | "PL">("all");
  // Draws the eye to the row that was just created, rather than leaving the
  // new order to blend into the rest of the list.
  const [justCreatedId, setJustCreatedId] = useState<string | null>(null);
  const todayIso = todayDateInputValue();

  const { data: orders = [], isLoading } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => listWorkOrders(token),
  });
  const { data: workCenters = [] } = useQuery({ queryKey: WORK_CENTERS_QUERY_KEY, queryFn: () => listWorkCenters(token) });
  const { data: recipes = [] } = useQuery({ queryKey: RECIPES_QUERY_KEY, queryFn: () => listRecipes(token) });
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: packagingBoms = [] } = useQuery({ queryKey: PACKAGING_BOMS_QUERY_KEY, queryFn: () => listPackagingBoms(token) });
  const { data: workOrderYields = [] } = useQuery({ queryKey: YIELDS_QUERY_KEY, queryFn: () => listWorkOrderYields(token) });
  const { data: regrindBatches = [] } = useQuery({ queryKey: REGRIND_BATCHES_QUERY_KEY, queryFn: () => listRegrindBatches(token) });
  const { data: supervisorOptions = [] } = useQuery({ queryKey: SUPERVISORS_QUERY_KEY, queryFn: () => listSupervisorOptions(token) });
  const regrindWorkOrderIds = new Set(regrindBatches.map((b) => b.work_order_id));
  const yieldByWorkOrderId = new Map(workOrderYields.map((y) => [y.work_order_id, y.yield_ratio]));

  // Create schemas with i18n messages
  const newOrderSchema = z.object({
    work_center_id: z.string().min(1, t("common.required")),
    product_type: z.enum(["PC", "PL"]),
    start_date: z.string().min(1, t("common.required")),
    supervisor_id: z.string().optional(),
  });
  const editOrderSchema = z.object({
    planned_quantity: z.coerce.number().positive(t("common.mustBeGreaterThanZero")).optional(),
    work_center_id: z.string().optional(),
    supervisor_id: z.string().optional(),
    recipe_id: z.string().optional(),
    packaging_bom_id: z.string().optional(),
    product_type: z.string().optional(),
  });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<NewOrderForm>({
    resolver: zodResolver(newOrderSchema),
    defaultValues: { work_center_id: "", product_type: "PC", start_date: todayIso, supervisor_id: "" },
  });

  const createMutation = useMutation({
    mutationFn: (input: NewOrderForm) =>
      createWorkOrder(token, {
        work_center_id: input.work_center_id,
        product_type: input.product_type,
        start_date: input.start_date,
        supervisor_id: input.supervisor_id || undefined,
      }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setDialogOpen(false);
      reset({ work_center_id: "", product_type: "PC", start_date: todayDateInputValue(), supervisor_id: "" });
      toast.success(t("production.workOrders.created"));
      setJustCreatedId(created.id);
      setTimeout(() => setJustCreatedId(null), 2000);
    },
    onError: (error) => {
      toast.error(t("production.workOrders.createError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const startMutation = useMutation({
    mutationFn: (id: string) => startWorkOrder(token, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      toast.success(t("production.workOrders.started"));
    },
    onError: (error) => {
      toast.error(t("production.workOrders.startError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const editForm = useForm<EditOrderForm>({ resolver: zodResolver(editOrderSchema) });

  const updateMutation = useMutation({
    mutationFn: ({ id, input }: { id: string; input: UpdateWorkOrderInput }) => updateWorkOrder(token, id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setEditingId(null);
      editForm.reset();
      toast.success(t("production.workOrders.updated"));
    },
    onError: (error) => {
      toast.error(t("production.workOrders.updateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  function openEditDialog(order: WorkOrder | null) {
    if (!order) {
      setEditingId(null);
      return;
    }
    setEditingId(order.id);
    editForm.reset({
      planned_quantity: order.planned_quantity ?? undefined,
      work_center_id: order.work_center_id ?? "",
      supervisor_id: order.supervisor_id ?? "",
      recipe_id: order.recipe_id ?? "",
      packaging_bom_id: order.packaging_bom_id ?? "",
      product_type: order.product_type ?? "",
    });
  }

  function submitEdit(order: WorkOrder, input: EditOrderForm) {
    updateMutation.mutate({
      id: order.id,
      input: {
        planned_quantity: input.planned_quantity,
        work_center_id: input.work_center_id || undefined,
        supervisor_id: input.supervisor_id || undefined,
        recipe_id: input.recipe_id || undefined,
        packaging_bom_id: input.packaging_bom_id || undefined,
        product_type: input.product_type || undefined,
      },
    });
  }

  // The OF lifecycle posts no stock, so every one of these is a plain status
  // change. What was produced and consumed is recorded on the OF's reports and
  // posted when a supervisor validates them.
  function lifecycleMutation(
    action: (id: string) => Promise<unknown>,
    successKey: string,
    errorKey: string,
  ) {
    return {
      mutationFn: (id: string) => action(id),
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: QUERY_KEY });
        toast.success(t(successKey as Parameters<typeof t>[0]));
      },
      onError: (error: unknown) => {
        toast.error(t(errorKey as Parameters<typeof t>[0]), {
          description: error instanceof ApiError ? error.message : undefined,
        });
      },
    };
  }

  const suspendMutation = useMutation(
    lifecycleMutation(
      (id) => suspendWorkOrder(token, id),
      "production.workOrders.suspendedToast",
      "production.workOrders.suspendError",
    ),
  );

  const resumeMutation = useMutation(
    lifecycleMutation(
      (id) => resumeWorkOrder(token, id),
      "production.workOrders.resumedToast",
      "production.workOrders.resumeError",
    ),
  );

  const cancelMutation = useMutation(
    lifecycleMutation(
      (id) => cancelWorkOrder(token, id),
      "production.workOrders.cancelledToast",
      "production.workOrders.cancelError",
    ),
  );

  // Closing asks when the order actually finished (defaults to now, adjustable),
  // so a shift wrapped up and closed the next morning can record the real time.
  const closeMutation = useMutation({
    mutationFn: ({ id, closedAt }: { id: string; closedAt: string }) =>
      closeWorkOrder(token, id, crypto.randomUUID(), { closedAt }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setClosingId(null);
      toast.success(t("production.workOrders.closedToast"));
    },
    onError: (error) => {
      toast.error(t("production.workOrders.closeError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const supervisorNameFor = (supervisorId: string | null) => {
    const supervisor = supervisorOptions.find((s) => s.id === supervisorId);
    return supervisor ? supervisorLabel(supervisor) : "";
  };

  const nonRegrindOrders = orders.filter((o) => !regrindWorkOrderIds.has(o.id));
  const ongoingCount = nonRegrindOrders.filter((o) => o.status === "ongoing").length;
  const closedCount = nonRegrindOrders.filter((o) => o.status === "closed").length;
  const statusFilteredOrders = statusFilter === "all" ? nonRegrindOrders : nonRegrindOrders.filter((o) => o.status === statusFilter);
  const typeFilteredOrders = typeFilter === "all" ? statusFilteredOrders : statusFilteredOrders.filter((o) => o.product_type === typeFilter);

  const columnFilterFields: FilterField<WorkOrder>[] = [
    { key: "reference", kind: "text", getValue: (o) => o.reference },
    { key: "work_center", kind: "text", getValue: (o) => workCenters.find((wc) => wc.id === o.work_center_id)?.code ?? o.work_center_id },
    { key: "supervisor", kind: "text", getValue: (o) => supervisorNameFor(o.supervisor_id) },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredOrders = columnFilters.apply(statusFilteredOrders);

  const columns: ColumnDef<WorkOrder>[] = [
    {
      key: "reference",
      header: t("production.workOrders.column.reference"),
      defaultWidth: 140,
      // The reference is the way into the OF's own page — where the consolidated
      // result, its reports and its quality history live.
      cell: (order) => (
        <Link to={`/production/work-orders/${order.id}`} className="font-medium text-primary hover:underline">
          {order.reference}
        </Link>
      ),
      filterCell: {
        type: "text",
        value: columnFilters.text.reference ?? "",
        onChange: (v) => columnFilters.setTextValue("reference", v),
        placeholder: t("production.workOrders.column.reference"),
      },
      sortValue: (order) => order.reference,
    },
    {
      key: "productType",
      header: t("production.workOrders.column.type"),
      defaultWidth: 90,
      cell: (order) =>
        order.product_type ? <Badge variant={order.product_type === "PC" ? "primary" : "outline"}>{order.product_type}</Badge> : "—",
      sortValue: (order) => order.product_type,
    },
    {
      key: "startDate",
      header: t("production.workOrders.column.startDate"),
      defaultWidth: 160,
      cell: (order) => (
        <div className="flex items-center gap-1.5">
          <span className="tabular-nums text-muted-foreground">{order.start_date ?? "—"}</span>
          {order.status === "planned" && order.start_date === todayIso && (
            <Badge variant="warning">{t("production.workOrders.dueToday")}</Badge>
          )}
        </div>
      ),
      sortValue: (order) => order.start_date,
    },
    {
      key: "work_center",
      header: t("production.workOrders.column.workCenter"),
      defaultWidth: 160,
      cell: (order) => (
        <span className="text-muted-foreground">{workCenters.find((wc) => wc.id === order.work_center_id)?.code ?? "—"}</span>
      ),
      filterCell: {
        type: "text",
        value: columnFilters.text.work_center ?? "",
        onChange: (v) => columnFilters.setTextValue("work_center", v),
        placeholder: t("production.workOrders.column.workCenter"),
      },
      sortValue: (order) => workCenters.find((wc) => wc.id === order.work_center_id)?.code ?? "",
    },
    {
      key: "supervisor",
      header: t("production.workOrders.column.supervisor"),
      defaultWidth: 180,
      cell: (order) => (
        <span className="text-muted-foreground">{supervisorNameFor(order.supervisor_id) || "—"}</span>
      ),
      filterCell: {
        type: "text",
        value: columnFilters.text.supervisor ?? "",
        onChange: (v) => columnFilters.setTextValue("supervisor", v),
        placeholder: t("production.workOrders.column.supervisor"),
      },
      sortValue: (order) => supervisorNameFor(order.supervisor_id),
    },
    {
      key: "progress",
      header: t("production.workOrders.column.progress"),
      defaultWidth: 160,
      cell: (order) => (
        <div className="h-1.5 w-28 overflow-hidden rounded-full bg-muted">
          <motion.div
            className={cn(
              "h-full rounded-full",
              order.status === "closed" ? "bg-success" : order.status === "ongoing" ? "bg-warning" : "bg-border",
            )}
            initial={{ width: 0 }}
            animate={{ width: `${PROGRESS[order.status]}%` }}
            transition={{ duration: 0.5, ease: "easeOut" }}
          />
        </div>
      ),
      sortValue: (order) => PROGRESS[order.status],
    },
    {
      key: "status",
      header: (
        <span className="inline-flex items-center gap-1">
          {t("production.workOrders.column.status")}
          <HelpTooltip text={t("production.workOrders.help.status")} />
        </span>
      ),
      defaultWidth: 140,
      cell: (order) => <StatusBadge status={order.status} />,
      sortValue: (order) => order.status,
    },
    {
      key: "yield",
      header: t("production.workOrders.column.yield"),
      defaultWidth: 140,
      cell: (order) => {
        // No validated report yet means nothing has been divided by anything —
        // that reads as 0%, not as a missing value.
        const ratio = yieldByWorkOrderId.get(order.id) ?? 0;
        return <span className="tabular-nums text-muted-foreground">{`${(ratio * 100).toFixed(1)}%`}</span>;
      },
      sortValue: (order) => yieldByWorkOrderId.get(order.id) ?? 0,
    },
    {
      key: "action",
      header: t("production.workOrders.column.action"),
      defaultWidth: 90,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right",
      cell: (order) => (
        <OrderActions
          order={order}
          products={products}
          workCenters={workCenters}
          supervisorOptions={supervisorOptions}
          recipes={recipes}
          packagingBoms={packagingBoms}
          detailsId={detailsId}
          onOpenDetails={(open) => setDetailsId(open ? order.id : null)}
          onStart={() => startMutation.mutate(order.id)}
          onSuspend={() => suspendMutation.mutate(order.id)}
          onResume={() => resumeMutation.mutate(order.id)}
          onCancel={() => cancelMutation.mutate(order.id)}
          closingId={closingId}
          onOpenClose={(open) => setClosingId(open ? order.id : null)}
          onClose={(closedAt) => closeMutation.mutate({ id: order.id, closedAt })}
          isStarting={startMutation.isPending && startMutation.variables === order.id}
          isSuspending={suspendMutation.isPending && suspendMutation.variables === order.id}
          isResuming={resumeMutation.isPending && resumeMutation.variables === order.id}
          isCancelling={cancelMutation.isPending && cancelMutation.variables === order.id}
          isClosing={closeMutation.isPending && closeMutation.variables?.id === order.id}
          editingId={editingId}
          onOpenEdit={(open) => openEditDialog(open ? order : null)}
          editForm={editForm}
          onSubmitEdit={(input) => submitEdit(order, input)}
          isUpdating={updateMutation.isPending && updateMutation.variables?.id === order.id}
        />
      ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("production.workOrders", columns);
  const sortedOrders = sortRows(filteredOrders);
  const groupedOrders = (["PC", "PL"] as const).map((groupType) => ({
    type: groupType,
    orders: sortedOrders.filter((order) => order.product_type === groupType),
  }));

  const visibleGroups = typeFilter === "all" ? groupedOrders : [{ type: typeFilter, orders: sortedOrders.filter((order) => order.product_type === typeFilter) }];

  const productNameFor = (productId: string | null) => {
    if (!productId) return "—";
    return products.find((product) => product.id === productId)?.name ?? "—";
  };

  const workCenterNameFor = (order: WorkOrder) => workCenters.find((wc) => wc.id === order.work_center_id)?.name ?? "—";

  const cardAccent = (status: WorkOrderStatus) => {
    if (status === "closed") return "from-success/25 via-success/10 to-transparent text-success";
    if (status === "ongoing") return "from-warning/30 via-warning/10 to-transparent text-warning";
    if (status === "suspended") return "from-accent/30 via-accent/10 to-transparent text-accent";
    if (status === "cancelled") return "from-destructive/25 via-destructive/10 to-transparent text-destructive";
    return "from-primary/25 via-primary/10 to-transparent text-primary";
  };

  const StatusIconFor = (status: WorkOrderStatus) => {
    switch (status) {
      case "planned":
        return <PlannedStatusIcon className="h-4 w-4" />;
      case "ongoing":
        return <OngoingStatusIcon className="h-4 w-4" />;
      case "suspended":
        return <SuspendedStatusIcon className="h-4 w-4" />;
      case "closed":
        return <ClosedStatusIcon className="h-4 w-4" />;
      case "cancelled":
        return <CancelledStatusIcon className="h-4 w-4" />;
      default:
        return <PlannedStatusIcon className="h-4 w-4" />;
    }
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("production.workOrders.stat.total")} value={nonRegrindOrders.length} icon={<ClipboardList className="h-5 w-5" />} />
        <StatCard label={t("production.workOrders.stat.ongoing")} value={ongoingCount} icon={<Timer className="h-5 w-5" />} accent="warning" />
        <StatCard label={t("production.workOrders.stat.closed")} value={closedCount} icon={<CheckCircle2 className="h-5 w-5" />} accent="success" />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("production.workOrders.table.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("production.workOrders.table.subtitle")}</p>
            </div>
            <FilterTabs
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "planned", label: t("status.planned") },
                { value: "ongoing", label: t("status.ongoing") },
                { value: "suspended", label: t("status.suspended") },
                { value: "closed", label: t("status.closed") },
                { value: "cancelled", label: t("status.cancelled") },
              ]}
            />
            <FilterTabs
              value={typeFilter}
              onChange={setTypeFilter}
              options={[
                { value: "all", label: "All types" },
                { value: "PC", label: "PC" },
                { value: "PL", label: "PL" },
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
              <Button>
                <Plus className="h-4 w-4" />
                {t("production.workOrders.new")}
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-2xl">
              <DialogHeader>
                <DialogTitle>{t("production.workOrders.dialog.title")}</DialogTitle>
                <DialogDescription>{t("production.workOrders.dialog.description")}</DialogDescription>
              </DialogHeader>
              <form className="space-y-4" onSubmit={handleSubmit((input) => createMutation.mutate(input))}>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="product_type">{t("production.workOrders.field.productType")}</Label>
                    <Select id="product_type" {...register("product_type")}>
                      <option value="PC">PC</option>
                      <option value="PL">PL</option>
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="start_date">{t("production.workOrders.field.startDate")}</Label>
                    <Input id="start_date" type="date" {...register("start_date")} />
                    {errors.start_date && <p className="text-sm text-destructive">{errors.start_date.message}</p>}
                  </div>
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="work_center_id">{t("production.workOrders.field.workCenter")}</Label>
                  <Select id="work_center_id" {...register("work_center_id")}>
                    <option value="">—</option>
                    {workCenters.map((wc) => (
                      <option key={wc.id} value={wc.id}>
                        {wc.code} — {wc.name}
                      </option>
                    ))}
                  </Select>
                  {errors.work_center_id && <p className="text-sm text-destructive">{errors.work_center_id.message}</p>}
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="supervisor_id">{t("production.workOrders.field.supervisor")}</Label>
                  <Select id="supervisor_id" {...register("supervisor_id")}>
                    <option value="">—</option>
                    {supervisorOptions.map((s) => (
                      <option key={s.id} value={s.id}>
                        {supervisorLabel(s)}
                      </option>
                    ))}
                  </Select>
                </div>

                <p className="text-xs text-muted-foreground">{t("production.workOrders.productHint")}</p>

                {createMutation.isError && (
                  <p className="text-sm text-destructive">
                    {createMutation.error instanceof ApiError ? createMutation.error.message : t("production.workOrders.createError")}
                  </p>
                )}
                <Button type="submit" className="w-full" disabled={createMutation.isPending}>
                  {createMutation.isPending ? t("production.workOrders.creating") : t("production.workOrders.create")}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
        </CardHeader>
        <CardContent className="p-4">
          {isLoading ? (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="rounded-xl border border-border bg-card p-4">
                  <Skeleton className="h-6 w-24" />
                  <Skeleton className="mt-4 h-16 w-full" />
                  <Skeleton className="mt-4 h-4 w-full" />
                  <Skeleton className="mt-2 h-4 w-2/3" />
                </div>
              ))}
            </div>
          ) : typeFilteredOrders.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border bg-muted/15 p-8">
              <EmptyState
                icon={<ProductionEmptyStateIllustration className="h-52 w-full max-w-md" />}
                title={typeFilter === "all" ? t("production.workOrders.empty.title") : `No ${typeFilter} orders`}
                description={
                  typeFilter === "all"
                    ? t("production.workOrders.empty.description")
                    : `There are no ${typeFilter} work orders matching the current status and filters.`
                }
              />
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              {visibleGroups.map((group) => (
                <div key={group.type} className="space-y-3 rounded-2xl border border-border bg-muted/10 p-3">
                  <div className="space-y-2 border-b border-border pb-2">
                    <div className="flex items-center justify-between gap-3">
                      <motion.div
                        initial={{ opacity: 0, x: -8 }}
                        animate={{ opacity: 1, x: 0 }}
                        className="flex items-center gap-2"
                      >
                        <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-background text-primary shadow-sm">
                          {group.type === "PC" ? <Factory className="h-4 w-4" /> : <Boxes className="h-4 w-4" />}
                        </div>
                        <Badge variant={group.type === "PC" ? "primary" : "outline"}>{group.type}</Badge>
                        <span className="text-sm text-muted-foreground">{group.orders.length} orders</span>
                      </motion.div>
                      <motion.div
                        animate={{ rotate: [0, 4, -4, 0] }}
                        transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                        className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-primary"
                      >
                        <Sparkles className="h-3.5 w-3.5" />
                      </motion.div>
                    </div>

                    <div className="grid grid-cols-3 gap-2 text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                      <motion.div
                        whileHover={{ y: -1 }}
                        className="rounded-lg border border-border bg-background/80 px-2 py-1.5"
                      >
                        <div className="flex items-center gap-1.5"><Zap className="h-3 w-3 text-primary" /> Active</div>
                        <div className="mt-1 text-sm font-semibold text-foreground tabular-nums">
                          {group.orders.filter((o) => o.status === "ongoing" || o.status === "suspended").length}
                        </div>
                      </motion.div>
                      <motion.div
                        whileHover={{ y: -1 }}
                        className="rounded-lg border border-border bg-background/80 px-2 py-1.5"
                      >
                        <div className="flex items-center gap-1.5"><CheckCircle2 className="h-3 w-3 text-success" /> Closed</div>
                        <div className="mt-1 text-sm font-semibold text-foreground tabular-nums">
                          {group.orders.filter((o) => o.status === "closed").length}
                        </div>
                      </motion.div>
                      <motion.div
                        whileHover={{ y: -1 }}
                        className="rounded-lg border border-border bg-background/80 px-2 py-1.5"
                      >
                        <div className="flex items-center gap-1.5"><Clock3 className="h-3 w-3 text-warning" /> Planned</div>
                        <div className="mt-1 text-sm font-semibold text-foreground tabular-nums">
                          {group.orders.filter((o) => o.status === "planned").length}
                        </div>
                      </motion.div>
                    </div>
                  </div>

                  {group.orders.length === 0 ? (
                    <div className="rounded-xl border border-dashed border-border bg-muted/10 px-4 py-6 text-sm text-muted-foreground">
                      No {group.type} orders for this filter set.
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 gap-4">
                      <AnimatePresence initial={false}>
                        {group.orders.map((order, index) => {
                          const productName = productNameFor(order.product_id);
                          const visibleProgress = PROGRESS[order.status];
                          const badgeTone = cardAccent(order.status);

                          return (
                            <motion.article
                              key={order.id}
                              {...(order.id === justCreatedId ? highlightRowEnterProps(index) : rowEnterProps(index))}
                              layout
                              whileHover={{ y: -3, scale: 1.01 }}
                              transition={{ duration: 0.18, ease: "easeOut" }}
                              className="group overflow-hidden rounded-2xl border border-border bg-card shadow-sm"
                            >
                              <div className="flex items-start justify-between gap-3 border-b border-border bg-muted/20 p-4">
                                <div className="flex min-w-0 flex-1 items-center gap-2 text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                                  <motion.span
                                    animate={{ scale: [1, 1.12, 1] }}
                                    transition={{ duration: 2.2, repeat: Infinity, ease: "easeInOut" }}
                                    className="flex h-6 w-6 items-center justify-center rounded-md bg-primary/10 text-primary"
                                  >
                                    <Factory className="h-3.5 w-3.5" />
                                  </motion.span>
                                  <span>OF</span>
                                  <span className="text-primary">{order.reference}</span>
                                  <ArrowRight className="h-3 w-3 text-muted-foreground" />
                                </div>

                                <div className="flex items-center gap-2" onClick={(event) => event.stopPropagation()}>
                                  <StatusBadge status={order.status} />
                                  <OrderActions
                                    order={order}
                                    products={products}
                                    workCenters={workCenters}
                                    supervisorOptions={supervisorOptions}
                                    recipes={recipes}
                                    packagingBoms={packagingBoms}
                                    detailsId={detailsId}
                                    onOpenDetails={(open) => setDetailsId(open ? order.id : null)}
                                    onStart={() => startMutation.mutate(order.id)}
                                    onSuspend={() => suspendMutation.mutate(order.id)}
                                    onResume={() => resumeMutation.mutate(order.id)}
                                    onCancel={() => cancelMutation.mutate(order.id)}
                                    closingId={closingId}
                                    onOpenClose={(open) => setClosingId(open ? order.id : null)}
                                    onClose={(closedAt) => closeMutation.mutate({ id: order.id, closedAt })}
                                    isStarting={startMutation.isPending && startMutation.variables === order.id}
                                    isSuspending={suspendMutation.isPending && suspendMutation.variables === order.id}
                                    isResuming={resumeMutation.isPending && resumeMutation.variables === order.id}
                                    isCancelling={cancelMutation.isPending && cancelMutation.variables === order.id}
                                    isClosing={closeMutation.isPending && closeMutation.variables?.id === order.id}
                                    editingId={editingId}
                                    onOpenEdit={(open) => openEditDialog(open ? order : null)}
                                    editForm={editForm}
                                    onSubmitEdit={(input) => submitEdit(order, input)}
                                    isUpdating={updateMutation.isPending && updateMutation.variables?.id === order.id}
                                  />
                                </div>
                              </div>

                              <Link to={`/production/work-orders/${order.id}`} className="block p-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60">
                                <div className="space-y-4">
                                  <div className="flex items-center gap-3">
                                    <motion.div
                                      animate={{ y: [0, -3, 0], rotate: [0, 1, -1, 0] }}
                                      transition={{ duration: 3.4, repeat: Infinity, ease: "easeInOut" }}
                                      className="flex h-16 w-16 items-center justify-center overflow-hidden rounded-xl border border-border bg-gradient-to-br shadow-inner"
                                    >
                                      <ProductPackagingThumbIllustration className={cn("h-full w-full object-cover", badgeTone)} />
                                    </motion.div>
                                    <div className="flex-1 space-y-2">
                                      <div className="flex items-center justify-between text-xs text-muted-foreground">
                                        <span className="inline-flex items-center gap-1.5"><Factory className="h-3.5 w-3.5" /> {t("production.workOrders.column.workCenter")}</span>
                                        <span className="font-medium text-foreground">{workCenterNameFor(order)}</span>
                                      </div>
                                      <div className="flex items-center justify-between text-xs text-muted-foreground">
                                        <span className="inline-flex items-center gap-1.5"><Clock3 className="h-3.5 w-3.5" /> {t("production.workOrders.column.startDate")}</span>
                                        <span className="font-medium text-foreground">{order.start_date ?? "—"}</span>
                                      </div>
                                      <div className="flex items-center justify-between text-xs text-muted-foreground">
                                        <span className="inline-flex items-center gap-1.5"><Boxes className="h-3.5 w-3.5" /> {t("production.workOrders.column.type")}</span>
                                        <span className="font-medium text-foreground">{order.product_type ?? "—"}</span>
                                      </div>
                                    </div>
                                  </div>

                                  <div className="space-y-2">
                                    <div className="flex items-center justify-between text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">
                                      <span className="inline-flex items-center gap-1.5"><Gauge className="h-3.5 w-3.5" /> {t("production.workOrders.column.progress")}</span>
                                      <span className="text-foreground">{visibleProgress}%</span>
                                    </div>
                                    <div className="h-2.5 w-full overflow-hidden rounded-full bg-muted">
                                      <motion.div
                                        className={cn(
                                          "h-full rounded-full",
                                          order.status === "closed" ? "bg-success" : order.status === "ongoing" ? "bg-warning" : order.status === "cancelled" ? "bg-destructive" : "bg-primary",
                                        )}
                                        initial={{ width: 0 }}
                                        animate={{ width: `${visibleProgress}%` }}
                                        transition={{ duration: 0.5, ease: "easeOut" }}
                                      />
                                    </div>
                                  </div>

                                  <div className="grid grid-cols-3 gap-2 text-xs">
                                    <motion.div whileHover={{ y: -2 }} className="rounded-lg border border-border bg-muted/20 p-2">
                                      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                                        <Activity className="h-3 w-3 text-primary" />
                                        <span>Live</span>
                                      </div>
                                      <div className="mt-1 font-medium text-foreground">{order.status}</div>
                                    </motion.div>
                                    <motion.div whileHover={{ y: -2 }} className="rounded-lg border border-border bg-muted/20 p-2">
                                      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                                        <PackageCheck className="h-3 w-3 text-success" />
                                        <span>Yield</span>
                                      </div>
                                      <div className="mt-1 font-medium text-foreground">
                                        {`${((yieldByWorkOrderId.get(order.id) ?? 0) * 100).toFixed(1)}%`}
                                      </div>
                                    </motion.div>
                                    <motion.div whileHover={{ y: -2 }} className="rounded-lg border border-border bg-muted/20 p-2">
                                      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                                        {StatusIconFor(order.status)}
                                        <span>Lead</span>
                                      </div>
                                      <div className="mt-1 font-medium text-foreground">{supervisorNameFor(order.supervisor_id) || "—"}</div>
                                    </motion.div>
                                  </div>

                                  <div className="flex items-center justify-between gap-2 rounded-xl border border-border bg-muted/15 p-3">
                                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                                      <ShieldCheck className="h-3.5 w-3.5 text-success" />
                                      <span>{productName}</span>
                                    </div>
                                    <div className="flex items-center gap-1.5 text-xs font-medium text-primary">
                                      <Zap className="h-3.5 w-3.5" />
                                      <span>Open</span>
                                      <ArrowRight className="h-3.5 w-3.5" />
                                    </div>
                                  </div>

                                  <div className="rounded-xl border border-border bg-muted/15 p-3">
                                    <ProductionFlowIllustration className="h-16 w-full" />
                                  </div>
                                </div>
                              </Link>
                            </motion.article>
                          );
                        })}
                      </AnimatePresence>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function OrderActions({
  order,
  products,
  workCenters,
  supervisorOptions,
  recipes,
  packagingBoms,
  detailsId,
  onOpenDetails,
  onStart,
  onSuspend,
  onResume,
  onCancel,
  closingId,
  onOpenClose,
  onClose,
  isStarting,
  isSuspending,
  isResuming,
  isCancelling,
  isClosing,
  editingId,
  onOpenEdit,
  editForm,
  onSubmitEdit,
  isUpdating,
}: {
  order: WorkOrder;
  products: Product[];
  workCenters: WorkCenter[];
  supervisorOptions: SupervisorOption[];
  recipes: Recipe[];
  packagingBoms: PackagingBom[];
  detailsId: string | null;
  onOpenDetails: (open: boolean) => void;
  onStart: () => void;
  onSuspend: () => void;
  onResume: () => void;
  onCancel: () => void;
  closingId: string | null;
  onOpenClose: (open: boolean) => void;
  onClose: (closedAt: string) => void;
  isStarting: boolean;
  isSuspending: boolean;
  isResuming: boolean;
  isCancelling: boolean;
  isClosing: boolean;
  editingId: string | null;
  onOpenEdit: (open: boolean) => void;
  editForm: UseFormReturn<EditOrderForm>;
  onSubmitEdit: (input: EditOrderForm) => void;
  isUpdating: boolean;
}) {
  const { session } = useAuth();
  const token = session!.token;
  const { t } = useI18n();
  const navigate = useNavigate();

  const closeOrderSchema = z.object({
    closed_at: z.string().min(1, t("common.required")),
  });

  const productName = (productId: string | null) => {
    if (!productId) return "—";
    return products.find((p) => p.id === productId)?.name ?? "—";
  };
  const supervisorName = (supervisorId: string | null) => {
    const supervisor = supervisorOptions.find((s) => s.id === supervisorId);
    return supervisor ? supervisorLabel(supervisor) : "—";
  };
  const isDetailsDialogOpen = detailsId === order.id;
  const isCloseDialogOpen = closingId === order.id;
  const closeForm = useForm<CloseOrderForm>({ resolver: zodResolver(closeOrderSchema) });

  const { data: pouredInputs = [] } = useQuery({
    queryKey: ["production", "work-order-inputs", order.id],
    queryFn: () => listWorkOrderInputs(token, order.id),
    enabled: isDetailsDialogOpen,
  });
  const { data: reports = [] } = useQuery({
    queryKey: ["production", "reports", "of", order.id],
    queryFn: () => listReports(token, { of_id: order.id }),
    enabled: isDetailsDialogOpen,
  });
  const { data: qualityReports = [] } = useQuery({
    queryKey: ["qc", "quality-reports", "of", order.id],
    queryFn: () => listQualityReports(token, { of_id: order.id }),
    enabled: isDetailsDialogOpen,
  });
  // Consolidation and yield are both computed from validated reports, so they are
  // meaningful while the order is still running — no need to wait for closure.
  const { data: consolidation } = useQuery({
    queryKey: ["production", "of-consolidation", order.id],
    queryFn: () => getWorkOrderConsolidation(token, order.id),
    enabled: isDetailsDialogOpen,
  });
  const { data: yieldDetail } = useQuery({
    queryKey: ["production", "work-order-yield", order.id],
    queryFn: () => getWorkOrderYield(token, order.id),
    enabled: isDetailsDialogOpen,
  });

  // Only the transitions this status actually allows are listed. An action the
  // backend would refuse is worse than a missing one: it invites the click and
  // then explains why it failed.
  const rowActions: RowAction[] = [
    {
      key: "details",
      label: t("production.workOrders.details"),
      icon: <Eye className="h-4 w-4" />,
      onSelect: () => navigate(`/production/work-orders/${order.id}`),
    },
    {
      key: "edit",
      label: t("production.workOrders.edit"),
      icon: <Pencil className="h-4 w-4" />,
      onSelect: () => onOpenEdit(true),
    },
  ];
  if (order.status === "planned") {
    rowActions.push({
      key: "start",
      label: isStarting ? t("production.workOrders.starting") : t("production.workOrders.start"),
      icon: <PlayCircle className="h-4 w-4" />,
      onSelect: onStart,
      disabled: isStarting,
    });
  }
  if (order.status === "ongoing") {
    rowActions.push({
      key: "suspend",
      label: isSuspending ? t("production.workOrders.suspending") : t("production.workOrders.suspend"),
      icon: <PauseCircle className="h-4 w-4" />,
      onSelect: onSuspend,
      disabled: isSuspending,
    });
  }
  if (order.status === "suspended") {
    rowActions.push({
      key: "resume",
      label: isResuming ? t("production.workOrders.resuming") : t("production.workOrders.resume"),
      icon: <PlayCircle className="h-4 w-4" />,
      onSelect: onResume,
      disabled: isResuming,
    });
  }
  if (order.status === "ongoing") {
    rowActions.push({
      key: "close",
      label: isClosing ? t("production.workOrders.closing") : t("production.workOrders.close"),
      icon: <CheckCircle2 className="h-4 w-4" />,
      onSelect: () => {
        closeForm.reset({ closed_at: nowDatetimeLocalValue() });
        onOpenClose(true);
      },
      disabled: isClosing,
    });
  }
  if (order.status === "planned" || order.status === "suspended") {
    rowActions.push({
      key: "cancel",
      label: isCancelling ? t("production.workOrders.cancelling") : t("production.workOrders.cancel"),
      icon: <XCircle className="h-4 w-4" />,
      onSelect: onCancel,
      disabled: isCancelling,
      tone: "destructive",
    });
  }

  return (
        <div className="flex justify-end gap-2">
          <RowActionsMenu actions={rowActions} label={t("production.workOrders.column.action")} />
          <Dialog open={isDetailsDialogOpen} onOpenChange={onOpenDetails}>
            <DialogContent className="max-w-xl">
              <DialogHeader>
                <DialogTitle>{order.reference || order.id}</DialogTitle>
                <DialogDescription>{productName(order.product_id)}</DialogDescription>
              </DialogHeader>
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3 rounded-xl border border-border bg-muted/20 p-3 text-sm">
                  <div className="rounded-lg border border-border bg-background p-2.5">
                    <p className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">Production reports</p>
                    <p className="mt-1 text-lg font-semibold">{reports.length}</p>
                  </div>
                  <div className="rounded-lg border border-border bg-background p-2.5">
                    <p className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">Quality reports</p>
                    <p className="mt-1 text-lg font-semibold">{qualityReports.length}</p>
                  </div>
                  <div className="rounded-lg border border-border bg-background p-2.5">
                    <p className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">Produced</p>
                    <p className="mt-1 text-lg font-semibold tabular-nums">
                      {consolidation ? consolidation.produced_quantity : "—"}
                    </p>
                  </div>
                  <div className="rounded-lg border border-border bg-background p-2.5">
                    <p className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">Yield</p>
                    <p className="mt-1 text-lg font-semibold tabular-nums">
                      {yieldDetail ? `${(yieldDetail.yield_ratio * 100).toFixed(1)}%` : "—"}
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <span className="text-muted-foreground">{t("production.workOrders.column.status")}: </span>
                    <StatusBadge status={order.status} />
                  </div>
                  <div>
                    <span className="text-muted-foreground">{t("production.workOrders.column.type")}: </span>
                    <span className="font-medium">{order.product_type ?? "—"}</span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">{t("production.workOrders.column.startDate")}: </span>
                    <span className="font-medium">{order.start_date ?? "—"}</span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">{t("production.workOrders.column.workCenter")}: </span>
                    <span className="font-medium">{workCenters.find((wc) => wc.id === order.work_center_id)?.name ?? "—"}</span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">{t("production.workOrders.column.supervisor")}: </span>
                    <span className="font-medium">
                      {supervisorName(order.supervisor_id)}
                    </span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">{t("production.workOrders.details.produced")}: </span>
                    <span className="font-medium">{consolidation ? consolidation.produced_quantity : "—"}</span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">{t("production.workOrders.details.recipe")}: </span>
                    <span className="font-medium">
                      {order.recipe_id
                        ? `v${recipes.find((r) => r.id === order.recipe_id)?.version ?? "?"}`
                        : "—"}
                    </span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">{t("production.workOrders.details.packagingBom")}: </span>
                    <span className="font-medium">
                      {order.packaging_bom_id
                        ? `v${packagingBoms.find((b) => b.id === order.packaging_bom_id)?.version ?? "?"}`
                        : "—"}
                    </span>
                  </div>
                  {order.closed_at && (
                    <div>
                      <span className="text-muted-foreground">{t("production.workOrders.field.closedAt")}: </span>
                      <span className="font-medium">{new Date(order.closed_at).toLocaleString(currentLocale())}</span>
                    </div>
                  )}
                </div>

                {yieldDetail && (
                  <div className="space-y-1.5 rounded-lg border border-border p-3">
                    <p className="text-xs font-medium text-muted-foreground">{t("production.workOrders.details.yield")}</p>
                    <div className="grid grid-cols-2 gap-1 text-sm">
                      <span>{t("production.workOrders.column.yield")}: {(yieldDetail.yield_ratio * 100).toFixed(1)}%</span>
                      <span>{t("production.workOrders.details.rebroyat")}: {yieldDetail.rebroyat_quantity}</span>
                      <span>{t("production.workOrders.details.semoule")}: {yieldDetail.semoule_quantity_total}</span>
                    </div>
                  </div>
                )}

                <div className="space-y-1.5">
                  <p className="text-xs font-medium text-muted-foreground">{t("production.workOrders.details.pouredInputs")}</p>
                  {pouredInputs.length === 0 ? (
                    <p className="text-xs text-muted-foreground">{t("production.workOrders.details.pouredInputsEmpty")}</p>
                  ) : (
                    <ul className="space-y-1 text-sm">
                      {pouredInputs.map((line) => (
                        <li key={line.id} className="flex justify-between text-muted-foreground">
                          <span>{productName(line.product_id)}</span>
                          <span className="tabular-nums">{line.quantity}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

              </div>
            </DialogContent>
          </Dialog>
          <Dialog open={editingId === order.id} onOpenChange={onOpenEdit}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{t("production.workOrders.dialog.editTitle")}</DialogTitle>
                <DialogDescription>{t("production.workOrders.dialog.editDescription")}</DialogDescription>
              </DialogHeader>
              <form className="space-y-4" onSubmit={editForm.handleSubmit(onSubmitEdit)}>
                <div className="space-y-1.5">
                  <Label htmlFor={`edit_work_center_${order.id}`}>{t("production.workOrders.field.workCenter")}</Label>
                  <Select id={`edit_work_center_${order.id}`} {...editForm.register("work_center_id")}>
                    <option value="">—</option>
                    {workCenters.map((wc) => (
                      <option key={wc.id} value={wc.id}>
                        {wc.code} — {wc.name}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`edit_supervisor_${order.id}`}>{t("production.workOrders.field.supervisor")}</Label>
                  <Select id={`edit_supervisor_${order.id}`} {...editForm.register("supervisor_id")}>
                    <option value="">—</option>
                    {supervisorOptions.map((s) => (
                      <option key={s.id} value={s.id}>
                        {supervisorLabel(s)}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`edit_product_type_${order.id}`}>{t("production.workOrders.field.productType")}</Label>
                  <Select id={`edit_product_type_${order.id}`} {...editForm.register("product_type")}>
                    <option value="">—</option>
                    <option value="PC">PC</option>
                    <option value="PL">PL</option>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`edit_recipe_${order.id}`}>{t("production.workOrders.field.recipe")}</Label>
                  <Select id={`edit_recipe_${order.id}`} {...editForm.register("recipe_id")}>
                    <option value="">—</option>
                    {recipes.map((recipe) => (
                      <option key={recipe.id} value={recipe.id}>
                        {productName(recipe.target_product_id)} · v{recipe.version}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`edit_packaging_bom_${order.id}`}>{t("production.workOrders.field.packagingBom")}</Label>
                  <Select id={`edit_packaging_bom_${order.id}`} {...editForm.register("packaging_bom_id")}>
                    <option value="">—</option>
                    {packagingBoms.map((bom) => (
                      <option key={bom.id} value={bom.id}>
                        {productName(bom.target_product_id)} · v{bom.version}
                      </option>
                    ))}
                  </Select>
                </div>
                <Button type="submit" className="w-full" disabled={isUpdating}>
                  {isUpdating ? t("production.workOrders.updating") : t("production.workOrders.update")}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
          <Dialog open={isCloseDialogOpen} onOpenChange={onOpenClose}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{t("production.workOrders.dialog.closeTitle")}</DialogTitle>
                <DialogDescription>{t("production.workOrders.dialog.closeDescription")}</DialogDescription>
              </DialogHeader>
              <form
                className="space-y-4"
                onSubmit={closeForm.handleSubmit((input) => onClose(new Date(input.closed_at).toISOString()))}
              >
                <div className="space-y-1.5">
                  <Label htmlFor={`close_at_${order.id}`}>{t("production.workOrders.field.closedAt")}</Label>
                  <Input id={`close_at_${order.id}`} type="datetime-local" {...closeForm.register("closed_at")} />
                  {closeForm.formState.errors.closed_at && (
                    <p className="text-sm text-destructive">{closeForm.formState.errors.closed_at.message}</p>
                  )}
                </div>
                <Button type="submit" className="w-full" disabled={isClosing}>
                  {isClosing ? t("production.workOrders.closing") : t("production.workOrders.close")}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
        </div>
  );
}
