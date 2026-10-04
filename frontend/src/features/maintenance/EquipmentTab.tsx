import { useState } from "react";
import { Link } from "react-router-dom";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, Archive, ArchiveRestore, CheckCircle2, MapPin, Pencil, Plus, Settings2, Wrench } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../lib/auth";
import { useHasPermission } from "./hooks";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Badge, type BadgeProps } from "../../components/ui/badge";
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
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import {
  PRODUCTION_STAGES,
  archiveEquipment,
  createEquipment,
  listEquipment,
  listWorkCenters,
  setEquipmentStatus,
  unarchiveEquipment,
  updateEquipment,
  type Equipment,
  type EquipmentStatus,
  type ProductionStage,
} from "./api";
import { TableLoadingRow } from "../../components/patterns/AppLoader";

const newEquipmentSchema = z.object({
  work_center_id: z.string().min(1, "Required"),
  code: z.string().min(1, "Required"),
  name: z.string().min(1, "Required"),
  // "" is a machine that works at none of the stages.
  production_stage: z.string(),
});
type NewEquipmentForm = z.infer<typeof newEquipmentSchema>;

/** The form's "" becomes null, which is what clears a stage on the server. */
function toInput(form: NewEquipmentForm) {
  return { ...form, production_stage: (form.production_stage || null) as ProductionStage | null };
}

const EQUIPMENT_QUERY_KEY = ["maintenance", "equipment"] as const;
const WORK_CENTERS_QUERY_KEY = ["production", "work-centers"] as const;
type StatusFilter = "all" | EquipmentStatus;
type StageFilter = "all" | ProductionStage | "none";

const STATUS_VARIANT: Record<EquipmentStatus, BadgeProps["variant"]> = {
  operational: "success",
  down: "destructive",
  maintenance: "warning",
};

const NEXT_STATUS: Record<EquipmentStatus, EquipmentStatus[]> = {
  operational: ["down", "maintenance"],
  down: ["operational", "maintenance"],
  maintenance: ["operational"],
};

export function EquipmentTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canManageCheckpoints = useHasPermission("maintenance.manage_checkpoints");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingEquipment, setEditingEquipment] = useState<Equipment | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [stageFilter, setStageFilter] = useState<StageFilter>("all");

  const STATUS_LABEL: Record<EquipmentStatus, string> = {
    operational: t("maintenance.equipment.status.operational"),
    down: t("maintenance.equipment.status.down"),
    maintenance: t("maintenance.equipment.status.maintenance"),
  };
  const STAGE_LABEL: Record<ProductionStage, string> = {
    versement: t("maintenance.equipment.stage.versement"),
    extrusion: t("maintenance.equipment.stage.extrusion"),
    conditionnement: t("maintenance.equipment.stage.conditionnement"),
  };

  const { data: equipment = [], isLoading } = useQuery({ queryKey: EQUIPMENT_QUERY_KEY, queryFn: () => listEquipment(token) });
  const { data: workCenters = [] } = useQuery({ queryKey: WORK_CENTERS_QUERY_KEY, queryFn: () => listWorkCenters(token) });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<NewEquipmentForm>({ resolver: zodResolver(newEquipmentSchema) });

  const createMutation = useMutation({
    mutationFn: (input: NewEquipmentForm) => createEquipment(token, toInput(input)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: EQUIPMENT_QUERY_KEY });
      setDialogOpen(false);
      reset();
      toast.success(t("maintenance.equipment.created"));
    },
    onError: (error) => {
      toast.error(t("maintenance.equipment.createError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (input: NewEquipmentForm) => updateEquipment(token, editingEquipment!.id, toInput(input)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: EQUIPMENT_QUERY_KEY });
      setDialogOpen(false);
      setEditingEquipment(null);
      reset();
      toast.success(t("maintenance.equipment.saved"));
    },
    onError: (error) => {
      toast.error(t("maintenance.equipment.saveError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  function openCreateDialog() {
    setEditingEquipment(null);
    reset({ work_center_id: "", code: "", name: "", production_stage: "" });
    setDialogOpen(true);
  }

  function openEditDialog(item: Equipment) {
    setEditingEquipment(item);
    reset({ work_center_id: item.work_center_id, code: item.code, name: item.name, production_stage: item.production_stage ?? "" });
    setDialogOpen(true);
  }

  const transitionMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: EquipmentStatus }) => setEquipmentStatus(token, id, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: EQUIPMENT_QUERY_KEY });
      toast.success(t("maintenance.equipment.updated"));
    },
    onError: (error) => {
      toast.error(t("maintenance.equipment.updateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const archiveMutation = useMutation({
    mutationFn: (id: string) => archiveEquipment(token, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: EQUIPMENT_QUERY_KEY });
      toast.success(t("maintenance.equipment.archived"));
    },
    onError: (error) => {
      toast.error(t("maintenance.equipment.archiveError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const unarchiveMutation = useMutation({
    mutationFn: (id: string) => unarchiveEquipment(token, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: EQUIPMENT_QUERY_KEY });
      toast.success(t("maintenance.equipment.unarchived"));
    },
    onError: (error) => {
      toast.error(t("maintenance.equipment.unarchiveError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const activeEquipment = equipment.filter((m) => !m.archived_at);
  const operationalCount = activeEquipment.filter((m) => m.status === "operational").length;
  const attentionCount = activeEquipment.filter((m) => m.status !== "operational").length;
  const statusFilteredEquipment = statusFilter === "all" ? equipment : equipment.filter((m) => m.status === statusFilter);
  const stageFilteredEquipment =
    stageFilter === "all"
      ? statusFilteredEquipment
      : statusFilteredEquipment.filter((m) => (stageFilter === "none" ? m.production_stage === null : m.production_stage === stageFilter));

  const columnFilterFields: FilterField<Equipment>[] = [
    { key: "code", kind: "text", getValue: (m) => m.code },
    { key: "name", kind: "text", getValue: (m) => m.name },
    { key: "work_center", kind: "text", getValue: (m) => workCenters.find((wc) => wc.id === m.work_center_id)?.code ?? m.work_center_id },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredEquipment = columnFilters.apply(stageFilteredEquipment);

  const columns: ColumnDef<Equipment>[] = [
    {
      key: "code",
      header: t("maintenance.equipment.column.code"),
      defaultWidth: 140,
      cell: (item) => <span className="font-medium">{item.code}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.code ?? "",
        onChange: (v) => columnFilters.setTextValue("code", v),
        placeholder: t("maintenance.equipment.column.code"),
      },
      sortValue: (item) => item.code,
    },
    {
      key: "name",
      header: t("maintenance.equipment.column.name"),
      defaultWidth: 200,
      cell: (item) => item.name,
      filterCell: {
        type: "text",
        value: columnFilters.text.name ?? "",
        onChange: (v) => columnFilters.setTextValue("name", v),
        placeholder: t("maintenance.equipment.column.name"),
      },
      sortValue: (item) => item.name,
    },
    {
      key: "work_center",
      header: t("maintenance.equipment.column.workCenter"),
      defaultWidth: 160,
      cell: (item) => (
        <span className="text-muted-foreground">
          {workCenters.find((wc) => wc.id === item.work_center_id)?.code ?? item.work_center_id}
        </span>
      ),
      filterCell: {
        type: "text",
        value: columnFilters.text.work_center ?? "",
        onChange: (v) => columnFilters.setTextValue("work_center", v),
        placeholder: t("maintenance.equipment.column.workCenter"),
      },
      sortValue: (item) => workCenters.find((wc) => wc.id === item.work_center_id)?.code ?? item.work_center_id,
    },
    {
      key: "stage",
      header: t("maintenance.equipment.column.stage"),
      defaultWidth: 160,
      cell: (item) =>
        item.production_stage ? <span>{STAGE_LABEL[item.production_stage]}</span> : <span className="text-muted-foreground">—</span>,
      sortValue: (item) => item.production_stage ?? "",
    },
    {
      key: "status",
      header: t("maintenance.equipment.column.status"),
      defaultWidth: 160,
      cell: (item) =>
        item.archived_at ? (
          <Badge variant="outline" dot>
            {t("maintenance.equipment.archived.badge")}
          </Badge>
        ) : (
          <Badge variant={STATUS_VARIANT[item.status]} dot>
            {STATUS_LABEL[item.status]}
          </Badge>
        ),
      sortValue: (item) => (item.archived_at ? "archived" : item.status),
    },
    {
      key: "action",
      header: t("maintenance.equipment.column.action"),
      defaultWidth: 260,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "space-x-2 text-right",
      cell: (item) =>
        item.archived_at ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => unarchiveMutation.mutate(item.id)}
            disabled={unarchiveMutation.isPending && unarchiveMutation.variables === item.id}
          >
            <ArchiveRestore className="h-3.5 w-3.5" />
            {t("maintenance.equipment.unarchive")}
          </Button>
        ) : (
          <>
            <Button size="sm" variant="outline" onClick={() => openEditDialog(item)}>
              <Pencil className="h-3.5 w-3.5" />
              {t("maintenance.equipment.edit")}
            </Button>
            {canManageCheckpoints && (
              <Button size="sm" variant="outline" asChild>
                <Link to={`/maintenance/equipment/${item.id}/map`}>
                  <MapPin className="h-3.5 w-3.5" />
                  {t("maintenance.equipment.checkpointMap")}
                </Link>
              </Button>
            )}
            {NEXT_STATUS[item.status].map((status) => (
              <Button
                key={status}
                size="sm"
                variant="outline"
                onClick={() => transitionMutation.mutate({ id: item.id, status })}
                disabled={transitionMutation.isPending && transitionMutation.variables?.id === item.id}
              >
                {STATUS_LABEL[status]}
              </Button>
            ))}
            <Button
              size="sm"
              variant="outline"
              onClick={() => archiveMutation.mutate(item.id)}
              disabled={archiveMutation.isPending && archiveMutation.variables === item.id}
            >
              <Archive className="h-3.5 w-3.5" />
              {t("maintenance.equipment.archive")}
            </Button>
          </>
        ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("maintenance.equipment", columns);
  const sortedEquipment = sortRows(filteredEquipment);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("maintenance.equipment.stat.total")} value={activeEquipment.length} icon={<Settings2 className="h-5 w-5" />} />
        <StatCard label={t("maintenance.equipment.stat.operational")} value={operationalCount} icon={<CheckCircle2 className="h-5 w-5" />} accent="success" />
        <StatCard label={t("maintenance.equipment.stat.attention")} value={attentionCount} icon={<AlertTriangle className="h-5 w-5" />} accent="warning" />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("maintenance.equipment.table.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("maintenance.equipment.table.subtitle")}</p>
            </div>
            <FilterTabs
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "operational", label: t("maintenance.equipment.status.operational") },
                { value: "down", label: t("maintenance.equipment.status.down") },
                { value: "maintenance", label: t("maintenance.equipment.status.maintenance") },
              ]}
            />
            <FilterTabs
              value={stageFilter}
              onChange={setStageFilter}
              options={[
                { value: "all", label: t("maintenance.equipment.stage.all") },
                ...PRODUCTION_STAGES.map((stage) => ({ value: stage, label: STAGE_LABEL[stage] })),
                { value: "none", label: t("maintenance.equipment.stage.none") },
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
              if (!open) setEditingEquipment(null);
            }}
          >
            <DialogTrigger asChild>
              <Button
                onClick={openCreateDialog}
                disabled={workCenters.length === 0}
                title={workCenters.length === 0 ? t("maintenance.equipment.createWorkCenterFirst") : undefined}
              >
                <Plus className="h-4 w-4" />
                {t("maintenance.equipment.new")}
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>
                  {editingEquipment ? t("maintenance.equipment.dialog.editTitle") : t("maintenance.equipment.dialog.title")}
                </DialogTitle>
                <DialogDescription>
                  {editingEquipment ? t("maintenance.equipment.dialog.editDescription") : t("maintenance.equipment.dialog.description")}
                </DialogDescription>
              </DialogHeader>
              <form
                className="space-y-4"
                onSubmit={handleSubmit((input) =>
                  editingEquipment ? updateMutation.mutate(input) : createMutation.mutate(input),
                )}
              >
                <div className="space-y-1.5">
                  <Label htmlFor="work_center_id">{t("maintenance.equipment.field.workCenter")}</Label>
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
                    <Label htmlFor="code">{t("maintenance.equipment.field.code")}</Label>
                    <Input id="code" placeholder="e.g. M-1" {...register("code")} />
                    {errors.code && <p className="text-sm text-destructive">{errors.code.message}</p>}
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="name">{t("maintenance.equipment.field.name")}</Label>
                    <Input id="name" placeholder="e.g. Extruder Motor" {...register("name")} />
                    {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="production_stage">{t("maintenance.equipment.field.stage")}</Label>
                  <Select id="production_stage" {...register("production_stage")}>
                    <option value="">{t("maintenance.equipment.stage.none")}</option>
                    {PRODUCTION_STAGES.map((stage) => (
                      <option key={stage} value={stage}>
                        {STAGE_LABEL[stage]}
                      </option>
                    ))}
                  </Select>
                  <p className="text-xs text-muted-foreground">{t("maintenance.equipment.field.stage.hint")}</p>
                </div>
                {(editingEquipment ? updateMutation.isError : createMutation.isError) && (
                  <p className="text-sm text-destructive">
                    {(editingEquipment ? updateMutation.error : createMutation.error) instanceof ApiError
                      ? (editingEquipment ? updateMutation.error : createMutation.error)?.message
                      : t(editingEquipment ? "maintenance.equipment.saveError" : "maintenance.equipment.createError")}
                  </p>
                )}
                <Button
                  type="submit"
                  className="w-full"
                  disabled={editingEquipment ? updateMutation.isPending : createMutation.isPending}
                >
                  {editingEquipment
                    ? updateMutation.isPending
                      ? t("maintenance.equipment.saving")
                      : t("maintenance.equipment.saveChanges")
                    : createMutation.isPending
                      ? t("maintenance.equipment.creating")
                      : t("maintenance.equipment.create")}
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
                    sortDirection={sortDirectionFor(column.key)}
                    onSort={column.sortValue ? () => toggleSort(column.key) : undefined}
                  >
                    {column.header}
                  </ResizableTableHead>
                ))}
              </TableRow>
              <ColumnFilterRow cells={visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
            </TableHeader>
            <TableBody>
              {isLoading && <TableLoadingRow colSpan={visibleColumns.length} />}
              {!isLoading && filteredEquipment.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <EmptyState
                      icon={<Wrench className="h-5 w-5" />}
                      title={t("maintenance.equipment.empty.title")}
                      description={t("maintenance.equipment.empty.description")}
                    />
                  </TableCell>
                </TableRow>
              )}
              <AnimatePresence initial={false}>
                {sortedEquipment.map((item, i) => (
                  <motion.tr
                    key={item.id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i * 0.04, 0.3) } }}
                    exit={{ opacity: 0 }}
                    className="border-b border-border last:border-0 hover:bg-muted/50"
                  >
                    {visibleColumns.map((column) => (
                      <TableCell key={column.key} className={column.cellClassName}>
                        {column.cell(item)}
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
