import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Factory, Lock, LockOpen, Pencil, Plus, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
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
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import {
  blockWorkCenter,
  createWorkCenter,
  listWorkCenters,
  unblockWorkCenter,
  updateWorkCenter,
  type WorkCenter,
} from "./api";

const newWorkCenterSchema = z.object({
  code: z.string().min(1, "Required"),
  name: z.string().min(1, "Required"),
  hourly_rate: z.coerce.number().min(0, "Must be >= 0"),
});
type NewWorkCenterForm = z.infer<typeof newWorkCenterSchema>;

const blockSchema = z.object({
  reason: z.string().min(1, "A reason is required"),
});
type BlockForm = z.infer<typeof blockSchema>;

const WORK_CENTERS_QUERY_KEY = ["production", "work-centers"] as const;
type BlockedFilter = "all" | "available" | "blocked";

export function WorkCentersTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingWorkCenter, setEditingWorkCenter] = useState<WorkCenter | null>(null);
  const [blockingId, setBlockingId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<BlockedFilter>("all");

  const { data: workCenters = [], isLoading } = useQuery({
    queryKey: WORK_CENTERS_QUERY_KEY,
    queryFn: () => listWorkCenters(token),
  });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<NewWorkCenterForm>({ resolver: zodResolver(newWorkCenterSchema), defaultValues: { hourly_rate: 0 } });

  const createMutation = useMutation({
    mutationFn: (input: NewWorkCenterForm) => createWorkCenter(token, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: WORK_CENTERS_QUERY_KEY });
      setDialogOpen(false);
      reset({ hourly_rate: 0 });
      toast.success(t("production.workCenters.created"));
    },
    onError: (error) => {
      toast.error(t("production.workCenters.createError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (input: NewWorkCenterForm) => updateWorkCenter(token, editingWorkCenter!.id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: WORK_CENTERS_QUERY_KEY });
      setDialogOpen(false);
      setEditingWorkCenter(null);
      reset({ hourly_rate: 0 });
      toast.success(t("production.workCenters.updated"));
    },
    onError: (error) => {
      toast.error(t("production.workCenters.updateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  function openCreateDialog() {
    setEditingWorkCenter(null);
    reset({ code: "", name: "", hourly_rate: 0 });
    setDialogOpen(true);
  }

  function openEditDialog(workCenter: WorkCenter) {
    setEditingWorkCenter(workCenter);
    reset({ code: workCenter.code, name: workCenter.name, hourly_rate: workCenter.hourly_rate });
    setDialogOpen(true);
  }

  const blockForm = useForm<BlockForm>({ resolver: zodResolver(blockSchema) });

  const blockMutation = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => blockWorkCenter(token, id, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: WORK_CENTERS_QUERY_KEY });
      setBlockingId(null);
      blockForm.reset();
      toast.success(t("production.workCenters.blockedToast"));
    },
    onError: (error) => {
      toast.error(t("production.workCenters.blockError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const unblockMutation = useMutation({
    mutationFn: (id: string) => unblockWorkCenter(token, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: WORK_CENTERS_QUERY_KEY });
      toast.success(t("production.workCenters.unblocked"));
    },
    onError: (error) => {
      toast.error(t("production.workCenters.unblockError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const blockedCount = workCenters.filter((wc) => wc.is_blocked).length;
  const statusFilteredWorkCenters =
    statusFilter === "all"
      ? workCenters
      : workCenters.filter((wc) => (statusFilter === "blocked" ? wc.is_blocked : !wc.is_blocked));

  const columnFilterFields: FilterField<WorkCenter>[] = [
    { key: "code", kind: "text", getValue: (wc) => wc.code },
    { key: "name", kind: "text", getValue: (wc) => wc.name },
    { key: "hourly_rate", kind: "range", getValue: (wc) => wc.hourly_rate },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredWorkCenters = columnFilters.apply(statusFilteredWorkCenters);

  const columns: ColumnDef<WorkCenter>[] = [
    {
      key: "code",
      header: t("production.workCenters.column.code"),
      defaultWidth: 140,
      cell: (wc) => <span className="font-medium">{wc.code}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.code ?? "",
        onChange: (v) => columnFilters.setTextValue("code", v),
        placeholder: t("production.workCenters.column.code"),
      },
    },
    {
      key: "name",
      header: t("production.workCenters.column.name"),
      defaultWidth: 200,
      cell: (wc) => wc.name,
      filterCell: {
        type: "text",
        value: columnFilters.text.name ?? "",
        onChange: (v) => columnFilters.setTextValue("name", v),
        placeholder: t("production.workCenters.column.name"),
      },
    },
    {
      key: "hourly_rate",
      header: t("production.workCenters.column.hourlyRate"),
      defaultWidth: 140,
      cell: (wc) => <span className="tabular-nums text-muted-foreground">${wc.hourly_rate.toFixed(2)}/hr</span>,
      filterCell: {
        type: "range",
        min: columnFilters.range.hourly_rate?.min ?? "",
        max: columnFilters.range.hourly_rate?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("hourly_rate", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("hourly_rate", "max", v),
      },
    },
    {
      key: "status",
      header: t("production.workCenters.column.status"),
      defaultWidth: 200,
      cell: (wc) =>
        wc.is_blocked ? (
          <Badge variant="destructive" dot>
            {t("production.workCenters.blocked")}
            {wc.blocked_reason ? ` — ${wc.blocked_reason}` : ""}
          </Badge>
        ) : (
          <Badge variant="success" dot>
            {t("production.workCenters.available")}
          </Badge>
        ),
    },
    {
      key: "action",
      header: t("production.workCenters.column.action"),
      defaultWidth: 220,
      alwaysVisible: true,
      headerClassName: "text-right",
      cell: (wc) => (
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="outline" onClick={() => openEditDialog(wc)}>
            <Pencil className="h-3.5 w-3.5" />
            {t("production.workCenters.edit")}
          </Button>
          {wc.is_blocked ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => unblockMutation.mutate(wc.id)}
              disabled={unblockMutation.isPending && unblockMutation.variables === wc.id}
            >
              <LockOpen className="h-3.5 w-3.5" />
              {unblockMutation.isPending && unblockMutation.variables === wc.id
                ? t("production.workCenters.unblocking")
                : t("production.workCenters.unblock")}
            </Button>
          ) : (
            <Dialog open={blockingId === wc.id} onOpenChange={(open) => setBlockingId(open ? wc.id : null)}>
              <DialogTrigger asChild>
                <Button size="sm" variant="ghost">
                  <Lock className="h-3.5 w-3.5" />
                  {t("production.workCenters.block")}
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>
                    {t("production.workCenters.dialog.block.titlePrefix")} {wc.name}
                  </DialogTitle>
                  <DialogDescription>{t("production.workCenters.dialog.block.description")}</DialogDescription>
                </DialogHeader>
                <form
                  className="space-y-4"
                  onSubmit={blockForm.handleSubmit((input) => blockMutation.mutate({ id: wc.id, reason: input.reason }))}
                >
                  <div className="space-y-1.5">
                    <Label htmlFor="reason">{t("production.workCenters.field.reason")}</Label>
                    <Input id="reason" placeholder="e.g. Screw jam, awaiting repair" {...blockForm.register("reason")} />
                    {blockForm.formState.errors.reason && (
                      <p className="text-sm text-destructive">{blockForm.formState.errors.reason.message}</p>
                    )}
                  </div>
                  <Button type="submit" variant="destructive" className="w-full" disabled={blockMutation.isPending}>
                    {blockMutation.isPending ? t("production.workCenters.blocking") : t("production.workCenters.blockButton")}
                  </Button>
                </form>
              </DialogContent>
            </Dialog>
          )}
        </div>
      ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "production.workCenters",
    columns,
  );

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("production.workCenters.stat.total")} value={workCenters.length} icon={<Factory className="h-5 w-5" />} />
        <StatCard label={t("production.workCenters.stat.available")} value={workCenters.length - blockedCount} icon={<ShieldCheck className="h-5 w-5" />} accent="success" />
        <StatCard label={t("production.workCenters.stat.blocked")} value={blockedCount} icon={<Lock className="h-5 w-5" />} accent="destructive" />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("production.workCenters.table.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("production.workCenters.table.subtitle")}</p>
            </div>
            <FilterTabs
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "available", label: t("production.workCenters.available") },
                { value: "blocked", label: t("production.workCenters.blocked") },
              ]}
            />
            {columnFilters.isActive && (
              <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                {t("common.clearFilters")}
              </Button>
            )}
            <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
          </div>
          <Dialog
            open={dialogOpen}
            onOpenChange={(open) => {
              setDialogOpen(open);
              if (!open) setEditingWorkCenter(null);
            }}
          >
            <DialogTrigger asChild>
              <Button onClick={openCreateDialog}>
                <Plus className="h-4 w-4" />
                {t("production.workCenters.new")}
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>
                  {editingWorkCenter ? t("production.workCenters.dialog.editTitle") : t("production.workCenters.dialog.new.title")}
                </DialogTitle>
                <DialogDescription>
                  {editingWorkCenter
                    ? t("production.workCenters.dialog.editDescription")
                    : t("production.workCenters.dialog.new.description")}
                </DialogDescription>
              </DialogHeader>
              <form
                className="space-y-4"
                onSubmit={handleSubmit((input) =>
                  editingWorkCenter ? updateMutation.mutate(input) : createMutation.mutate(input),
                )}
              >
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="code">{t("production.workCenters.field.code")}</Label>
                    <Input id="code" placeholder="e.g. EXT-1" {...register("code")} />
                    {errors.code && <p className="text-sm text-destructive">{errors.code.message}</p>}
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="hourly_rate">{t("production.workCenters.field.hourlyRate")}</Label>
                    <Input id="hourly_rate" type="number" step="any" {...register("hourly_rate")} />
                    {errors.hourly_rate && <p className="text-sm text-destructive">{errors.hourly_rate.message}</p>}
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="name">{t("production.workCenters.field.name")}</Label>
                  <Input id="name" placeholder="e.g. Extruder Line 1" {...register("name")} />
                  {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
                </div>
                {(editingWorkCenter ? updateMutation.isError : createMutation.isError) && (
                  <p className="text-sm text-destructive">
                    {(editingWorkCenter ? updateMutation.error : createMutation.error) instanceof ApiError
                      ? (editingWorkCenter ? updateMutation.error : createMutation.error)?.message
                      : t(editingWorkCenter ? "production.workCenters.updateError" : "production.workCenters.createError")}
                  </p>
                )}
                <Button
                  type="submit"
                  className="w-full"
                  disabled={editingWorkCenter ? updateMutation.isPending : createMutation.isPending}
                >
                  {editingWorkCenter
                    ? updateMutation.isPending
                      ? t("production.workCenters.updating")
                      : t("production.workCenters.update")
                    : createMutation.isPending
                      ? t("production.workCenters.creating")
                      : t("production.workCenters.create")}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
        </CardHeader>
        <CardContent className="p-0">
          <Table colWidths={colWidths}>
            <TableHeader>
              <TableRow>
                {visibleColumns.map((column) => (
                  <ResizableTableHead
                    key={column.key}
                    width={getWidth(column.key)}
                    onResize={(width) => setWidth(column.key, width)}
                    className={column.headerClassName}
                  >
                    {column.header}
                  </ResizableTableHead>
                ))}
              </TableRow>
              <ColumnFilterRow cells={visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
            </TableHeader>
            <TableBody>
              {isLoading &&
                Array.from({ length: 3 }).map((_, i) => (
                  <TableRow key={i}>
                    <TableCell colSpan={visibleColumns.length}>
                      <Skeleton className="h-5 w-full" />
                    </TableCell>
                  </TableRow>
                ))}
              {!isLoading && filteredWorkCenters.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <EmptyState
                      icon={<Factory className="h-5 w-5" />}
                      title={t("production.workCenters.empty.title")}
                      description={t("production.workCenters.empty.description")}
                    />
                  </TableCell>
                </TableRow>
              )}
              <AnimatePresence initial={false}>
                {filteredWorkCenters.map((wc, i) => (
                  <motion.tr
                    key={wc.id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i * 0.04, 0.3) } }}
                    exit={{ opacity: 0 }}
                    className="border-b border-border last:border-0 hover:bg-muted/50"
                  >
                    {visibleColumns.map((column) => (
                      <TableCell key={column.key} className={column.cellClassName}>
                        {column.cell(wc)}
                      </TableCell>
                    ))}
                  </motion.tr>
                ))}
              </AnimatePresence>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
