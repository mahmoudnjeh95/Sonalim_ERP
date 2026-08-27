import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useFieldArray, useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Boxes, CheckCircle2, FileStack, Package, Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
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
import {
  activatePackagingBom,
  archivePackagingBom,
  createPackagingBom,
  listPackagingBoms,
  listProducts,
  updatePackagingBom,
  type PackagingBom,
  type PackagingBomStatus,
} from "./api";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";

const lineSchema = z.object({
  component_product_id: z.string().min(1, "Required"),
  quantity_per_unit: z.coerce.number().positive("Must be > 0"),
});
const newBomSchema = z.object({
  target_product_id: z.string().min(1, "Required"),
  lines: z.array(lineSchema).min(1, "Add at least one component"),
});
type NewBomForm = z.infer<typeof newBomSchema>;

const BOMS_QUERY_KEY = ["production", "packaging-boms"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
type StatusFilter = "all" | PackagingBomStatus;

const rowVariants = {
  hidden: { opacity: 0, y: 8 },
  visible: (i: number) => ({ opacity: 1, y: 0, transition: { delay: Math.min(i * 0.04, 0.3), duration: 0.25 } }),
  exit: { opacity: 0, transition: { duration: 0.15 } },
};

export function PackagingBomsTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingBom, setEditingBom] = useState<PackagingBom | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const { data: boms = [], isLoading } = useQuery({
    queryKey: BOMS_QUERY_KEY,
    queryFn: () => listPackagingBoms(token),
  });
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });

  const {
    register,
    control,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<NewBomForm>({
    resolver: zodResolver(newBomSchema),
    defaultValues: { target_product_id: "", lines: [{ component_product_id: "", quantity_per_unit: 1 }] },
  });
  const { fields, append, remove } = useFieldArray({ control, name: "lines" });

  const createMutation = useMutation({
    mutationFn: (input: NewBomForm) => createPackagingBom(token, input),
    onSuccess: (bom) => {
      queryClient.invalidateQueries({ queryKey: BOMS_QUERY_KEY });
      setDialogOpen(false);
      reset({ target_product_id: "", lines: [{ component_product_id: "", quantity_per_unit: 1 }] });
      toast.success(t("production.packagingBoms.created"), { description: `${bom.target_product_id} · v${bom.version}` });
    },
    onError: (error) => {
      toast.error(t("production.packagingBoms.createError"), {
        description: error instanceof ApiError ? error.message : "Unexpected error",
      });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (input: NewBomForm) => updatePackagingBom(token, editingBom!.id, input),
    onSuccess: (bom) => {
      queryClient.invalidateQueries({ queryKey: BOMS_QUERY_KEY });
      setDialogOpen(false);
      setEditingBom(null);
      reset({ target_product_id: "", lines: [{ component_product_id: "", quantity_per_unit: 1 }] });
      toast.success(t("production.packagingBoms.updated"), { description: `${bom.target_product_id} · v${bom.version}` });
    },
    onError: (error) => {
      toast.error(t("production.packagingBoms.updateError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  function openCreateDialog() {
    setEditingBom(null);
    reset({ target_product_id: "", lines: [{ component_product_id: "", quantity_per_unit: 1 }] });
    setDialogOpen(true);
  }

  function openEditDialog(bom: PackagingBom) {
    setEditingBom(bom);
    reset({
      target_product_id: bom.target_product_id,
      lines: bom.lines.map((line) => ({ ...line })),
    });
    setDialogOpen(true);
  }

  const activateMutation = useMutation({
    mutationFn: (bomId: string) => activatePackagingBom(token, bomId),
    onSuccess: (bom) => {
      queryClient.invalidateQueries({ queryKey: BOMS_QUERY_KEY });
      toast.success(t("production.packagingBoms.activated"), { description: `${bom.target_product_id} · v${bom.version} ${t("production.packagingBoms.activatedLive")}` });
    },
    onError: (error) => {
      toast.error(t("production.packagingBoms.activateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const archiveMutation = useMutation({
    mutationFn: (bomId: string) => archivePackagingBom(token, bomId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: BOMS_QUERY_KEY });
      toast.success(t("production.packagingBoms.archived"));
    },
    onError: (error) => {
      toast.error(t("production.packagingBoms.archiveError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const activeCount = boms.filter((b) => b.status === "active").length;
  const draftCount = boms.filter((b) => b.status === "draft").length;
  const statusFilteredBoms = statusFilter === "all" ? boms : boms.filter((b) => b.status === statusFilter);

  const columnFilterFields: FilterField<PackagingBom>[] = [
    { key: "target_product_id", kind: "text", getValue: (b) => b.target_product_id },
    { key: "version", kind: "range", getValue: (b) => b.version },
    { key: "components", kind: "range", getValue: (b) => b.lines.length },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredBoms = columnFilters.apply(statusFilteredBoms);

  const columns: ColumnDef<PackagingBom>[] = [
    {
      key: "target_product_id",
      header: t("production.packagingBoms.column.targetProduct"),
      defaultWidth: 200,
      cell: (bom) => <span className="font-medium">{bom.target_product_id}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.target_product_id ?? "",
        onChange: (v) => columnFilters.setTextValue("target_product_id", v),
        placeholder: t("production.packagingBoms.column.targetProduct"),
      },
    },
    {
      key: "version",
      header: t("production.packagingBoms.column.version"),
      defaultWidth: 120,
      cell: (bom) => <span className="tabular-nums text-muted-foreground">v{bom.version}</span>,
      filterCell: {
        type: "range",
        min: columnFilters.range.version?.min ?? "",
        max: columnFilters.range.version?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("version", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("version", "max", v),
      },
    },
    { key: "status", header: t("production.packagingBoms.column.status"), defaultWidth: 140, cell: (bom) => <StatusBadge status={bom.status} /> },
    {
      key: "components",
      header: t("production.packagingBoms.column.components"),
      defaultWidth: 160,
      cell: (bom) => (
        <span className="text-muted-foreground">
          {bom.lines.length} {bom.lines.length === 1 ? t("production.packagingBoms.component") : t("production.packagingBoms.componentsPlural")}
        </span>
      ),
      filterCell: {
        type: "range",
        min: columnFilters.range.components?.min ?? "",
        max: columnFilters.range.components?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("components", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("components", "max", v),
      },
    },
    {
      key: "action",
      header: t("production.packagingBoms.column.action"),
      defaultWidth: 240,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right",
      cell: (bom) => (
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="outline" onClick={() => openEditDialog(bom)}>
            <Pencil className="h-3.5 w-3.5" />
            {t("production.packagingBoms.edit")}
          </Button>
          {bom.status === "draft" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => activateMutation.mutate(bom.id)}
              disabled={activateMutation.isPending && activateMutation.variables === bom.id}
            >
              {activateMutation.isPending && activateMutation.variables === bom.id
                ? t("production.packagingBoms.activating")
                : t("production.packagingBoms.activate")}
            </Button>
          )}
          {bom.status !== "archived" && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => archiveMutation.mutate(bom.id)}
              disabled={archiveMutation.isPending && archiveMutation.variables === bom.id}
            >
              {archiveMutation.isPending && archiveMutation.variables === bom.id
                ? t("production.packagingBoms.archiving")
                : t("production.packagingBoms.archive")}
            </Button>
          )}
        </div>
      ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "production.packagingBoms",
    columns,
  );

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("production.packagingBoms.stat.total")} value={boms.length} icon={<FileStack className="h-5 w-5" />} accent="primary" />
        <StatCard label={t("production.packagingBoms.stat.active")} value={activeCount} icon={<CheckCircle2 className="h-5 w-5" />} accent="success" />
        <StatCard label={t("production.packagingBoms.stat.draft")} value={draftCount} icon={<Package className="h-5 w-5" />} accent="warning" />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("production.packagingBoms.table.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("production.packagingBoms.table.subtitle")}</p>
            </div>
            <FilterTabs
              value={statusFilter}
              onChange={setStatusFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "draft", label: t("production.recipes.status.draft") },
                { value: "active", label: t("production.recipes.status.active") },
                { value: "archived", label: t("production.recipes.status.archived") },
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
              if (!open) setEditingBom(null);
            }}
          >
            <DialogTrigger asChild>
              <Button onClick={openCreateDialog}>
                <Plus className="h-4 w-4" />
                {t("production.packagingBoms.new")}
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-lg">
              <DialogHeader>
                <DialogTitle>
                  {editingBom ? t("production.packagingBoms.dialog.editTitle") : t("production.packagingBoms.dialog.title")}
                </DialogTitle>
                <DialogDescription>
                  {editingBom
                    ? t("production.packagingBoms.dialog.editDescription")
                    : t("production.packagingBoms.dialog.description")}
                </DialogDescription>
              </DialogHeader>
              <form
                className="space-y-4"
                onSubmit={handleSubmit((input) =>
                  editingBom ? updateMutation.mutate(input) : createMutation.mutate(input),
                )}
              >
                <div className="space-y-1.5">
                  <Label htmlFor="target_product_id">{t("production.packagingBoms.field.targetProduct")}</Label>
                  <Select id="target_product_id" {...register("target_product_id")}>
                    <option value="">—</option>
                    {products.map((product) => (
                      <option key={product.id} value={product.id}>
                        {product.name}
                      </option>
                    ))}
                  </Select>
                  {errors.target_product_id && (
                    <p className="text-sm text-destructive">{errors.target_product_id.message}</p>
                  )}
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label>{t("production.packagingBoms.field.components")}</Label>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => append({ component_product_id: "", quantity_per_unit: 1 })}
                    >
                      <Plus className="h-3.5 w-3.5" />
                      {t("production.packagingBoms.addLine")}
                    </Button>
                  </div>
                  <div className="space-y-2">
                    <AnimatePresence initial={false}>
                      {fields.map((field, index) => (
                        <motion.div
                          key={field.id}
                          initial={{ opacity: 0, height: 0 }}
                          animate={{ opacity: 1, height: "auto" }}
                          exit={{ opacity: 0, height: 0 }}
                          transition={{ duration: 0.18 }}
                          className="flex items-start gap-2"
                        >
                          <Select className="flex-1" {...register(`lines.${index}.component_product_id` as const)}>
                            <option value="">—</option>
                            {products.map((product) => (
                              <option key={product.id} value={product.id}>
                                {product.name}
                              </option>
                            ))}
                          </Select>
                          <Input
                            type="number"
                            step="any"
                            className="w-24"
                            placeholder={t("production.packagingBoms.field.qty")}
                            {...register(`lines.${index}.quantity_per_unit` as const)}
                          />
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            disabled={fields.length === 1}
                            onClick={() => remove(index)}
                            aria-label="Remove line"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </motion.div>
                      ))}
                    </AnimatePresence>
                  </div>
                  {errors.lines?.message && <p className="text-sm text-destructive">{errors.lines.message}</p>}
                </div>

                {(editingBom ? updateMutation.isError : createMutation.isError) && (
                  <p className="text-sm text-destructive">
                    {(editingBom ? updateMutation.error : createMutation.error) instanceof ApiError
                      ? (editingBom ? updateMutation.error : createMutation.error)?.message
                      : t(editingBom ? "production.packagingBoms.updateError" : "production.packagingBoms.createError")}
                  </p>
                )}
                <Button
                  type="submit"
                  className="w-full"
                  disabled={editingBom ? updateMutation.isPending : createMutation.isPending}
                >
                  {editingBom
                    ? updateMutation.isPending
                      ? t("production.packagingBoms.updating")
                      : t("production.packagingBoms.update")
                    : createMutation.isPending
                      ? t("production.packagingBoms.creating")
                      : t("production.packagingBoms.create")}
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
              {!isLoading && filteredBoms.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <EmptyState
                      icon={<Boxes className="h-5 w-5" />}
                      title={t("production.packagingBoms.empty.title")}
                      description={t("production.packagingBoms.empty.description")}
                    />
                  </TableCell>
                </TableRow>
              )}
              <AnimatePresence initial={false}>
                {filteredBoms.map((bom, i) => (
                  <motion.tr
                    key={bom.id}
                    layout
                    custom={i}
                    variants={rowVariants}
                    initial="hidden"
                    animate="visible"
                    exit="exit"
                    className="border-b border-border last:border-0 hover:bg-muted/50"
                  >
                    {visibleColumns.map((column) => (
                      <TableCell key={column.key} className={column.cellClassName}>
                        {column.cell(bom)}
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
