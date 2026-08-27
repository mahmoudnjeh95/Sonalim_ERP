import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Pencil, Plus, Settings2, Wrench } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Badge, type BadgeProps } from "../../components/ui/badge";
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
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import {
  createMachine,
  listMachines,
  listWorkCenters,
  setMachineStatus,
  updateMachine,
  type Machine,
  type MachineStatus,
} from "./api";

const newMachineSchema = z.object({
  work_center_id: z.string().min(1, "Required"),
  code: z.string().min(1, "Required"),
  name: z.string().min(1, "Required"),
});
type NewMachineForm = z.infer<typeof newMachineSchema>;

const MACHINES_QUERY_KEY = ["production", "machines"] as const;
const WORK_CENTERS_QUERY_KEY = ["production", "work-centers"] as const;
type StatusFilter = "all" | MachineStatus;

const STATUS_VARIANT: Record<MachineStatus, BadgeProps["variant"]> = {
  operational: "success",
  down: "destructive",
  maintenance: "warning",
};

const NEXT_STATUS: Record<MachineStatus, MachineStatus[]> = {
  operational: ["down", "maintenance"],
  down: ["operational", "maintenance"],
  maintenance: ["operational"],
};

export function MachinesTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingMachine, setEditingMachine] = useState<Machine | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const STATUS_LABEL: Record<MachineStatus, string> = {
    operational: t("production.machines.status.operational"),
    down: t("production.machines.status.down"),
    maintenance: t("production.machines.status.maintenance"),
  };

  const { data: machines = [], isLoading } = useQuery({ queryKey: MACHINES_QUERY_KEY, queryFn: () => listMachines(token) });
  const { data: workCenters = [] } = useQuery({ queryKey: WORK_CENTERS_QUERY_KEY, queryFn: () => listWorkCenters(token) });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<NewMachineForm>({ resolver: zodResolver(newMachineSchema) });

  const createMutation = useMutation({
    mutationFn: (input: NewMachineForm) => createMachine(token, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: MACHINES_QUERY_KEY });
      setDialogOpen(false);
      reset();
      toast.success(t("production.machines.created"));
    },
    onError: (error) => {
      toast.error(t("production.machines.createError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (input: NewMachineForm) => updateMachine(token, editingMachine!.id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: MACHINES_QUERY_KEY });
      setDialogOpen(false);
      setEditingMachine(null);
      reset();
      toast.success(t("production.machines.saved"));
    },
    onError: (error) => {
      toast.error(t("production.machines.saveError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  function openCreateDialog() {
    setEditingMachine(null);
    reset({ work_center_id: "", code: "", name: "" });
    setDialogOpen(true);
  }

  function openEditDialog(machine: Machine) {
    setEditingMachine(machine);
    reset({ work_center_id: machine.work_center_id, code: machine.code, name: machine.name });
    setDialogOpen(true);
  }

  const transitionMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: MachineStatus }) => setMachineStatus(token, id, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: MACHINES_QUERY_KEY });
      toast.success(t("production.machines.updated"));
    },
    onError: (error) => {
      toast.error(t("production.machines.updateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const operationalCount = machines.filter((m) => m.status === "operational").length;
  const attentionCount = machines.filter((m) => m.status !== "operational").length;
  const statusFilteredMachines = statusFilter === "all" ? machines : machines.filter((m) => m.status === statusFilter);

  const columnFilterFields: FilterField<Machine>[] = [
    { key: "code", kind: "text", getValue: (m) => m.code },
    { key: "name", kind: "text", getValue: (m) => m.name },
    { key: "work_center", kind: "text", getValue: (m) => workCenters.find((wc) => wc.id === m.work_center_id)?.code ?? m.work_center_id },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredMachines = columnFilters.apply(statusFilteredMachines);

  const columns: ColumnDef<Machine>[] = [
    {
      key: "code",
      header: t("production.machines.column.code"),
      defaultWidth: 140,
      cell: (machine) => <span className="font-medium">{machine.code}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.code ?? "",
        onChange: (v) => columnFilters.setTextValue("code", v),
        placeholder: t("production.machines.column.code"),
      },
    },
    {
      key: "name",
      header: t("production.machines.column.name"),
      defaultWidth: 200,
      cell: (machine) => machine.name,
      filterCell: {
        type: "text",
        value: columnFilters.text.name ?? "",
        onChange: (v) => columnFilters.setTextValue("name", v),
        placeholder: t("production.machines.column.name"),
      },
    },
    {
      key: "work_center",
      header: t("production.machines.column.workCenter"),
      defaultWidth: 160,
      cell: (machine) => (
        <span className="text-muted-foreground">
          {workCenters.find((wc) => wc.id === machine.work_center_id)?.code ?? machine.work_center_id}
        </span>
      ),
      filterCell: {
        type: "text",
        value: columnFilters.text.work_center ?? "",
        onChange: (v) => columnFilters.setTextValue("work_center", v),
        placeholder: t("production.machines.column.workCenter"),
      },
    },
    {
      key: "status",
      header: t("production.machines.column.status"),
      defaultWidth: 160,
      cell: (machine) => (
        <Badge variant={STATUS_VARIANT[machine.status]} dot>
          {STATUS_LABEL[machine.status]}
        </Badge>
      ),
    },
    {
      key: "action",
      header: t("production.machines.column.action"),
      defaultWidth: 260,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "space-x-2 text-right",
      cell: (machine) => (
        <>
          <Button size="sm" variant="outline" onClick={() => openEditDialog(machine)}>
            <Pencil className="h-3.5 w-3.5" />
            {t("production.machines.edit")}
          </Button>
          {NEXT_STATUS[machine.status].map((status) => (
            <Button
              key={status}
              size="sm"
              variant="outline"
              onClick={() => transitionMutation.mutate({ id: machine.id, status })}
              disabled={transitionMutation.isPending && transitionMutation.variables?.id === machine.id}
            >
              {STATUS_LABEL[status]}
            </Button>
          ))}
        </>
      ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "production.machines",
    columns,
  );

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("production.machines.stat.total")} value={machines.length} icon={<Settings2 className="h-5 w-5" />} />
        <StatCard label={t("production.machines.stat.operational")} value={operationalCount} icon={<CheckCircle2 className="h-5 w-5" />} accent="success" />
        <StatCard label={t("production.machines.stat.attention")} value={attentionCount} icon={<AlertTriangle className="h-5 w-5" />} accent="warning" />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("production.machines.table.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("production.machines.table.subtitle")}</p>
            </div>
            <FilterTabs
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "operational", label: t("production.machines.status.operational") },
                { value: "down", label: t("production.machines.status.down") },
                { value: "maintenance", label: t("production.machines.status.maintenance") },
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
              if (!open) setEditingMachine(null);
            }}
          >
            <DialogTrigger asChild>
              <Button
                onClick={openCreateDialog}
                disabled={workCenters.length === 0}
                title={workCenters.length === 0 ? t("production.machines.createWorkCenterFirst") : undefined}
              >
                <Plus className="h-4 w-4" />
                {t("production.machines.new")}
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>
                  {editingMachine ? t("production.machines.dialog.editTitle") : t("production.machines.dialog.title")}
                </DialogTitle>
                <DialogDescription>
                  {editingMachine ? t("production.machines.dialog.editDescription") : t("production.machines.dialog.description")}
                </DialogDescription>
              </DialogHeader>
              <form
                className="space-y-4"
                onSubmit={handleSubmit((input) =>
                  editingMachine ? updateMutation.mutate(input) : createMutation.mutate(input),
                )}
              >
                <div className="space-y-1.5">
                  <Label htmlFor="work_center_id">{t("production.machines.field.workCenter")}</Label>
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
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="code">{t("production.machines.field.code")}</Label>
                    <Input id="code" placeholder="e.g. M-1" {...register("code")} />
                    {errors.code && <p className="text-sm text-destructive">{errors.code.message}</p>}
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="name">{t("production.machines.field.name")}</Label>
                    <Input id="name" placeholder="e.g. Extruder Motor" {...register("name")} />
                    {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
                  </div>
                </div>
                {(editingMachine ? updateMutation.isError : createMutation.isError) && (
                  <p className="text-sm text-destructive">
                    {(editingMachine ? updateMutation.error : createMutation.error) instanceof ApiError
                      ? (editingMachine ? updateMutation.error : createMutation.error)?.message
                      : t(editingMachine ? "production.machines.saveError" : "production.machines.createError")}
                  </p>
                )}
                <Button
                  type="submit"
                  className="w-full"
                  disabled={editingMachine ? updateMutation.isPending : createMutation.isPending}
                >
                  {editingMachine
                    ? updateMutation.isPending
                      ? t("production.machines.saving")
                      : t("production.machines.saveChanges")
                    : createMutation.isPending
                      ? t("production.machines.creating")
                      : t("production.machines.create")}
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
              {!isLoading && filteredMachines.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <EmptyState
                      icon={<Wrench className="h-5 w-5" />}
                      title={t("production.machines.empty.title")}
                      description={t("production.machines.empty.description")}
                    />
                  </TableCell>
                </TableRow>
              )}
              <AnimatePresence initial={false}>
                {filteredMachines.map((machine, i) => (
                  <motion.tr
                    key={machine.id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i * 0.04, 0.3) } }}
                    exit={{ opacity: 0 }}
                    className="border-b border-border last:border-0 hover:bg-muted/50"
                  >
                    {visibleColumns.map((column) => (
                      <TableCell key={column.key} className={column.cellClassName}>
                        {column.cell(machine)}
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
