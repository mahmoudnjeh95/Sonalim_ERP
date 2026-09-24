import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence } from "framer-motion";
import {
  Boxes,
  CheckCircle2,
  ChevronDown,
  ClipboardList,
  Eye,
  Factory,
  PauseCircle,
  Pencil,
  PlayCircle,
  Plus,
  Search,
  Timer,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import ProductionEmptyStateIllustration from "../../assets/illustrations/production/production-empty-state.svg?react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Skeleton } from "../../components/ui/skeleton";
import { Dialog, DialogTrigger, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../components/ui/dialog";
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import type { RowAction } from "../../components/patterns/RowActionsMenu";
import {
  WORK_ORDER_OVERVIEW_QUERY_KEY,
  createWorkOrder,
  getWorkOrdersOverview,
  listPackagingBoms,
  listProducts,
  listRecipes,
  listSupervisorOptions,
  listWorkCenters,
  listWorkOrders,
  supervisorLabel,
  type SupervisorOption,
  type WorkCenter,
  type WorkOrder,
  type WorkOrderStatus,
} from "./api";
import { WorkOrderCard } from "./WorkOrderCard";
import { CloseWorkOrderDialog, EditWorkOrderDialog } from "./WorkOrderDialogs";
import { WORK_ORDERS_QUERY_KEY, useWorkOrderActions } from "./useWorkOrderActions";

const pad = (n: number) => String(n).padStart(2, "0");
const todayDateInputValue = () => {
  const now = new Date();
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
};
const clockNow = () => {
  const now = new Date();
  return `${pad(now.getHours())}:${pad(now.getMinutes())}`;
};

// Lightweight by design: work center, PC/PL and a start date. The product is not asked for: it appears
// once the order's first shift is validated, and lists every product the order packs.
type NewOrderForm = { work_center_id: string; product_type: "PC" | "PL"; start_date: string; supervisor_id?: string };

type StatusFilter = "all" | WorkOrderStatus;
type TypeFilter = "all" | "PC" | "PL";

const WORK_CENTERS_QUERY_KEY = ["production", "work-centers"] as const;
const RECIPES_QUERY_KEY = ["production", "recipes"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const PACKAGING_BOMS_QUERY_KEY = ["production", "packaging-boms"] as const;
const SUPERVISORS_QUERY_KEY = ["production", "work-order-supervisors"] as const;

// Running orders first: they are what a manager opens this screen for.
const STATUS_RANK: Record<WorkOrderStatus, number> = { ongoing: 0, suspended: 1, planned: 2, closed: 3, cancelled: 4 };
const isFinished = (status: WorkOrderStatus) => status === "closed" || status === "cancelled";

export function WorkOrdersTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const navigate = useNavigate();
  const [editing, setEditing] = useState<WorkOrder | null>(null);
  const [closing, setClosing] = useState<WorkOrder | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [search, setSearch] = useState("");
  const [showFinished, setShowFinished] = useState(false);
  // Draws the eye to the card that was just created, rather than leaving it to blend into the list.
  const [justCreatedId, setJustCreatedId] = useState<string | null>(null);

  const ordersQuery = useQuery({ queryKey: WORK_ORDERS_QUERY_KEY, queryFn: () => listWorkOrders(token) });
  const overviewQuery = useQuery({
    queryKey: WORK_ORDER_OVERVIEW_QUERY_KEY,
    queryFn: () => getWorkOrdersOverview(token, { date: todayDateInputValue(), at: clockNow() }),
    // "Live now" follows the clock, so the list refreshes itself while it stays open.
    refetchInterval: 60_000,
  });
  const { data: workCenters = [] } = useQuery({ queryKey: WORK_CENTERS_QUERY_KEY, queryFn: () => listWorkCenters(token) });
  const { data: recipes = [] } = useQuery({ queryKey: RECIPES_QUERY_KEY, queryFn: () => listRecipes(token) });
  const { data: products = [], isSuccess: productsReady } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: packagingBoms = [] } = useQuery({ queryKey: PACKAGING_BOMS_QUERY_KEY, queryFn: () => listPackagingBoms(token) });
  const { data: supervisorOptions = [] } = useQuery({ queryKey: SUPERVISORS_QUERY_KEY, queryFn: () => listSupervisorOptions(token) });

  const actions = useWorkOrderActions(token, { onUpdated: () => setEditing(null), onClosed: () => setClosing(null) });

  const overviewById = useMemo(() => new Map((overviewQuery.data ?? []).map((row) => [row.of_id, row])), [overviewQuery.data]);
  const productName = (id: string) => products.find((p) => p.id === id)?.name ?? "—";
  const workCenterOf = (order: WorkOrder) => workCenters.find((wc) => wc.id === order.work_center_id);
  const supervisorNameOf = (order: WorkOrder) => {
    const supervisor = supervisorOptions.find((s) => s.id === order.supervisor_id);
    return supervisor ? supervisorLabel(supervisor) : "";
  };
  // The overview lists the products of validated shifts; an order with none yet falls back to its own.
  // Null while the product list loads, so a name that is still coming is not shown as a missing one.
  const productNamesOf = (order: WorkOrder): string[] | null => {
    const ids = overviewById.get(order.id)?.products ?? (order.product_id ? [order.product_id] : []);
    if (ids.length > 0 && !productsReady) return null;
    return ids.map(productName);
  };

  const orders = (ordersQuery.data ?? []).filter((o) => !o.is_regrind);
  const ongoingCount = orders.filter((o) => o.status === "ongoing").length;
  const closedCount = orders.filter((o) => o.status === "closed").length;

  const needle = search.trim().toLowerCase();
  const matches = (order: WorkOrder) => {
    if (statusFilter !== "all" && order.status !== statusFilter) return false;
    if (typeFilter !== "all" && order.product_type !== typeFilter) return false;
    if (!needle) return true;
    const center = workCenterOf(order);
    return [order.reference, center?.code, center?.name, supervisorNameOf(order), ...(productNamesOf(order) ?? [])]
      .filter(Boolean)
      .some((field) => String(field).toLowerCase().includes(needle));
  };
  const visible = orders.filter(matches);
  // With the status filter on "all", finished orders stay folded away unless asked for.
  const folding = statusFilter === "all" && !showFinished;
  const foldedAway = folding ? visible.filter((o) => isFinished(o.status)).length : 0;
  const shown = folding ? visible.filter((o) => !isFinished(o.status)) : visible;

  const sortOrders = (list: WorkOrder[]) =>
    [...list].sort((a, b) => STATUS_RANK[a.status] - STATUS_RANK[b.status] || b.reference.localeCompare(a.reference));
  const groups = (["PC", "PL", null] as const)
    .map((type) => ({
      type,
      orders: sortOrders(shown.filter((o) => (o.product_type ?? null) === type)),
      // The header counts every order of the type the filters match, folded ones included.
      matching: visible.filter((o) => (o.product_type ?? null) === type),
    }))
    .filter((group) => (typeFilter === "all" ? group.type !== null || group.orders.length > 0 : group.type === typeFilter));

  const rowActionsFor = (order: WorkOrder): RowAction[] => {
    const busy = (mutation: { isPending: boolean; variables?: unknown }) => mutation.isPending && mutation.variables === order.id;
    const list: RowAction[] = [
      { key: "details", label: t("production.workOrders.details"), icon: <Eye className="h-4 w-4" />, onSelect: () => navigate(`/production/work-orders/${order.id}`) },
      { key: "edit", label: t("production.workOrders.edit"), icon: <Pencil className="h-4 w-4" />, onSelect: () => setEditing(order) },
    ];
    // Only the transitions this status allows are listed: an action the backend would refuse is worse than a missing one.
    if (order.status === "planned") {
      list.push({
        key: "start",
        label: busy(actions.start) ? t("production.workOrders.starting") : t("production.workOrders.start"),
        icon: <PlayCircle className="h-4 w-4" />,
        onSelect: () => actions.start.mutate(order.id),
        disabled: busy(actions.start),
      });
    }
    if (order.status === "ongoing") {
      list.push({
        key: "suspend",
        label: t("production.workOrders.suspend"),
        icon: <PauseCircle className="h-4 w-4" />,
        onSelect: () => actions.suspend.mutate(order.id),
        disabled: busy(actions.suspend),
      });
      list.push({ key: "close", label: t("production.workOrders.close"), icon: <CheckCircle2 className="h-4 w-4" />, onSelect: () => setClosing(order) });
    }
    if (order.status === "suspended") {
      list.push({
        key: "resume",
        label: t("production.workOrders.resume"),
        icon: <PlayCircle className="h-4 w-4" />,
        onSelect: () => actions.resume.mutate(order.id),
        disabled: busy(actions.resume),
      });
    }
    if (order.status === "planned" || order.status === "suspended") {
      list.push({
        key: "cancel",
        label: t("production.workOrders.cancel"),
        icon: <XCircle className="h-4 w-4" />,
        onSelect: () => actions.cancel.mutate(order.id),
        disabled: busy(actions.cancel),
        tone: "destructive",
      });
    }
    return list;
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("production.workOrders.stat.total")} value={orders.length} icon={<ClipboardList className="h-5 w-5" />} />
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
                { value: "all", label: t("production.workOrders.filter.allTypes") },
                { value: "PC", label: "PC" },
                { value: "PL", label: "PL" },
              ]}
            />
            <div className="relative min-w-[14rem] flex-1 sm:max-w-xs">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder={t("production.workOrders.search")}
                aria-label={t("production.workOrders.search")}
                className="pl-8"
              />
            </div>
          </div>
          <CreateWorkOrderDialog
            token={token}
            workCenters={workCenters}
            supervisorOptions={supervisorOptions}
            onCreated={(id) => {
              setJustCreatedId(id);
              setTimeout(() => setJustCreatedId(null), 2000);
            }}
          />
        </CardHeader>
        <CardContent className="p-4">
          {ordersQuery.isLoading ? (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="rounded-xl border border-border bg-card p-4">
                  <Skeleton className="h-5 w-32" />
                  <Skeleton className="mt-3 h-4 w-2/3" />
                  <Skeleton className="mt-4 h-2 w-full" />
                </div>
              ))}
            </div>
          ) : orders.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-border bg-muted/15 p-8">
              <EmptyState
                icon={<ProductionEmptyStateIllustration className="h-52 w-full max-w-md" />}
                title={t("production.workOrders.empty.title")}
                description={t("production.workOrders.empty.description")}
              />
            </div>
          ) : (
            <div className="space-y-4">
              {visible.length === 0 && (
                <p className="rounded-xl border border-dashed border-border bg-muted/10 px-4 py-6 text-sm text-muted-foreground">
                  {t("production.workOrders.empty.filtered")}
                </p>
              )}
              <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-2">
                {groups.map((group) => (
                  <section key={group.type ?? "none"} className="space-y-3 rounded-2xl border border-border/80 bg-muted/10 p-3">
                    <GroupHeader type={group.type} orders={group.matching} />
                    {group.orders.length === 0 ? (
                      <p className="rounded-xl border border-dashed border-border px-4 py-5 text-sm text-muted-foreground">
                        {group.matching.length > 0
                          ? `${group.matching.length} ${t("production.workOrders.group.hidden")}`
                          : t("production.workOrders.group.empty")}
                      </p>
                    ) : (
                      <div className="grid grid-cols-1 gap-3">
                        <AnimatePresence initial={false}>
                          {group.orders.map((order, index) => (
                            <WorkOrderCard
                              key={order.id}
                              order={order}
                              overview={overviewById.get(order.id)}
                              productNames={productNamesOf(order)}
                              workCenterName={workCenterOf(order)?.name ?? "—"}
                              supervisorName={supervisorNameOf(order)}
                              index={index}
                              highlighted={order.id === justCreatedId}
                              actions={rowActionsFor(order)}
                            />
                          ))}
                        </AnimatePresence>
                      </div>
                    )}
                  </section>
                ))}
              </div>
              {statusFilter === "all" && (showFinished || foldedAway > 0) && (
                <Button variant="ghost" size="sm" onClick={() => setShowFinished((open) => !open)}>
                  <ChevronDown className={`h-4 w-4 transition-transform ${showFinished ? "rotate-180" : ""}`} />
                  {showFinished ? t("production.workOrders.group.hideClosed") : `${t("production.workOrders.group.showClosed")} (${foldedAway})`}
                </Button>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <EditWorkOrderDialog
        order={editing}
        onClose={() => setEditing(null)}
        onSubmit={(id, input) => actions.update.mutate({ id, input })}
        isPending={actions.update.isPending}
        workCenters={workCenters}
        supervisorOptions={supervisorOptions}
        recipes={recipes}
        packagingBoms={packagingBoms}
        products={products}
      />
      <CloseWorkOrderDialog
        order={closing}
        onClose={() => setClosing(null)}
        onSubmit={(id, closedAt) => actions.close.mutate({ id, closedAt })}
        isPending={actions.close.isPending}
      />
    </div>
  );
}

/** A group's type and its counts, read from the orders it holds: nothing here is decoration. */
function GroupHeader({ type, orders }: { type: "PC" | "PL" | null; orders: WorkOrder[] }) {
  const { t } = useI18n();
  const count = (...statuses: WorkOrderStatus[]) => orders.filter((o) => statuses.includes(o.status)).length;
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2.5">
      <div className="flex items-center gap-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-background text-primary">
          {type === "PL" ? <Boxes className="h-4 w-4" /> : <Factory className="h-4 w-4" />}
        </div>
        <Badge variant={type === "PC" ? "primary" : "outline"}>{type ?? t("production.workOrders.group.noType")}</Badge>
        <span className="text-xs text-muted-foreground">{orders.length} OF</span>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>
          <span className="font-semibold tabular-nums text-foreground">{count("ongoing", "suspended")}</span> {t("status.ongoing")}
        </span>
        <span>
          <span className="font-semibold tabular-nums text-foreground">{count("planned")}</span> {t("status.planned")}
        </span>
        <span>
          <span className="font-semibold tabular-nums text-foreground">{count("closed")}</span> {t("status.closed")}
        </span>
      </div>
    </div>
  );
}

function CreateWorkOrderDialog({
  token,
  workCenters,
  supervisorOptions,
  onCreated,
}: {
  token: string;
  workCenters: WorkCenter[];
  supervisorOptions: SupervisorOption[];
  onCreated: (id: string) => void;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const blank = (): NewOrderForm => ({ work_center_id: "", product_type: "PC", start_date: todayDateInputValue(), supervisor_id: "" });
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<NewOrderForm>({
    resolver: zodResolver(
      z.object({
        work_center_id: z.string().min(1, t("common.required")),
        product_type: z.enum(["PC", "PL"]),
        start_date: z.string().min(1, t("common.required")),
        supervisor_id: z.string().optional(),
      }),
    ),
    defaultValues: blank(),
  });

  const create = useMutation({
    mutationFn: (input: NewOrderForm) =>
      createWorkOrder(token, {
        work_center_id: input.work_center_id,
        product_type: input.product_type,
        start_date: input.start_date,
        supervisor_id: input.supervisor_id || undefined,
      }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: WORK_ORDERS_QUERY_KEY });
      setOpen(false);
      reset(blank());
      toast.success(t("production.workOrders.created"));
      onCreated(created.id);
    },
    onError: (error) => {
      toast.error(t("production.workOrders.createError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
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
        <form className="space-y-4" onSubmit={handleSubmit((input) => create.mutate(input))}>
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
          <Button type="submit" className="w-full" disabled={create.isPending}>
            {create.isPending ? t("production.workOrders.creating") : t("production.workOrders.create")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
