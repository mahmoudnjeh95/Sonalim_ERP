import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Disc3, Pencil, Plus } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Badge } from "../../components/ui/badge";
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
import { createMold, listMolds, updateMold, type Mold, type MoldType } from "./api";
import { TableLoadingRow } from "../../components/patterns/AppLoader";

const newMoldSchema = z.object({
  code: z.string().min(1, "Required"),
  name: z.string().min(1, "Required"),
  type: z.enum(["PC", "PL"]),
});
type NewMoldForm = z.infer<typeof newMoldSchema>;

const MOLDS_QUERY_KEY = ["production", "molds"] as const;
type TypeFilter = "all" | MoldType;

export function MoldsTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingMold, setEditingMold] = useState<Mold | null>(null);
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");

  const { data: molds = [], isLoading } = useQuery({
    queryKey: MOLDS_QUERY_KEY,
    queryFn: () => listMolds(token),
  });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<NewMoldForm>({ resolver: zodResolver(newMoldSchema), defaultValues: { type: "PC" } });

  const createMutation = useMutation({
    mutationFn: (input: NewMoldForm) => createMold(token, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: MOLDS_QUERY_KEY });
      setDialogOpen(false);
      reset({ code: "", name: "", type: "PC" });
      toast.success(t("production.molds.created"));
    },
    onError: (error) => {
      toast.error(t("production.molds.createError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (input: NewMoldForm) => updateMold(token, editingMold!.id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: MOLDS_QUERY_KEY });
      setDialogOpen(false);
      setEditingMold(null);
      reset({ code: "", name: "", type: "PC" });
      toast.success(t("production.molds.updated"));
    },
    onError: (error) => {
      toast.error(t("production.molds.updateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  function openCreateDialog() {
    setEditingMold(null);
    reset({ code: "", name: "", type: "PC" });
    setDialogOpen(true);
  }

  function openEditDialog(mold: Mold) {
    setEditingMold(mold);
    reset({ code: mold.code, name: mold.name, type: mold.type });
    setDialogOpen(true);
  }

  const pcCount = molds.filter((m) => m.type === "PC").length;
  const plCount = molds.filter((m) => m.type === "PL").length;
  const typeFilteredMolds = typeFilter === "all" ? molds : molds.filter((m) => m.type === typeFilter);

  const columnFilterFields: FilterField<Mold>[] = [
    { key: "code", kind: "text", getValue: (m) => m.code },
    { key: "name", kind: "text", getValue: (m) => m.name },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredMolds = columnFilters.apply(typeFilteredMolds);

  const columns: ColumnDef<Mold>[] = [
    {
      key: "code",
      header: t("production.molds.column.code"),
      defaultWidth: 140,
      cell: (mold) => <span className="font-medium">{mold.code}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.code ?? "",
        onChange: (v) => columnFilters.setTextValue("code", v),
        placeholder: t("production.molds.column.code"),
      },
      sortValue: (mold) => mold.code,
    },
    {
      key: "name",
      header: t("production.molds.column.name"),
      defaultWidth: 220,
      cell: (mold) => mold.name,
      filterCell: {
        type: "text",
        value: columnFilters.text.name ?? "",
        onChange: (v) => columnFilters.setTextValue("name", v),
        placeholder: t("production.molds.column.name"),
      },
      sortValue: (mold) => mold.name,
    },
    {
      key: "type",
      header: t("production.molds.column.type"),
      defaultWidth: 120,
      cell: (mold) => <Badge variant={mold.type === "PC" ? "primary" : "outline"}>{mold.type}</Badge>,
      sortValue: (mold) => mold.type,
    },
    {
      key: "action",
      header: t("production.molds.column.action"),
      defaultWidth: 140,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right",
      cell: (mold) => (
        <Button size="sm" variant="outline" onClick={() => openEditDialog(mold)}>
          <Pencil className="h-3.5 w-3.5" />
          {t("production.molds.edit")}
        </Button>
      ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("production.molds", columns);
  const sortedMolds = sortRows(filteredMolds);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("production.molds.stat.total")} value={molds.length} icon={<Disc3 className="h-5 w-5" />} />
        <StatCard label={t("production.molds.stat.pc")} value={pcCount} icon={<Disc3 className="h-5 w-5" />} />
        <StatCard label={t("production.molds.stat.pl")} value={plCount} icon={<Disc3 className="h-5 w-5" />} />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("production.molds.table.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("production.molds.table.subtitle")}</p>
            </div>
            <FilterTabs
              value={typeFilter}
              onChange={setTypeFilter}
              options={[
                { value: "all", label: t("common.all") },
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
          <Dialog
            open={dialogOpen}
            onOpenChange={(open) => {
              setDialogOpen(open);
              if (!open) setEditingMold(null);
            }}
          >
            <DialogTrigger asChild>
              <Button onClick={openCreateDialog}>
                <Plus className="h-4 w-4" />
                {t("production.molds.new")}
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{editingMold ? t("production.molds.dialog.editTitle") : t("production.molds.dialog.new.title")}</DialogTitle>
                <DialogDescription>
                  {editingMold ? t("production.molds.dialog.editDescription") : t("production.molds.dialog.new.description")}
                </DialogDescription>
              </DialogHeader>
              <form
                className="space-y-4"
                onSubmit={handleSubmit((input) => (editingMold ? updateMutation.mutate(input) : createMutation.mutate(input)))}
              >
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="code">{t("production.molds.field.code")}</Label>
                    <Input id="code" placeholder="e.g. MLD-PC-500" {...register("code")} />
                    {errors.code && <p className="text-sm text-destructive">{errors.code.message}</p>}
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="type">{t("production.molds.field.type")}</Label>
                    <Select id="type" {...register("type")}>
                      <option value="PC">PC</option>
                      <option value="PL">PL</option>
                    </Select>
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="name">{t("production.molds.field.name")}</Label>
                  <Input id="name" placeholder="e.g. Moule 500g PC" {...register("name")} />
                  {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
                </div>
                {(editingMold ? updateMutation.isError : createMutation.isError) && (
                  <p className="text-sm text-destructive">
                    {(editingMold ? updateMutation.error : createMutation.error) instanceof ApiError
                      ? (editingMold ? updateMutation.error : createMutation.error)?.message
                      : t(editingMold ? "production.molds.updateError" : "production.molds.createError")}
                  </p>
                )}
                <Button type="submit" className="w-full" disabled={editingMold ? updateMutation.isPending : createMutation.isPending}>
                  {editingMold
                    ? updateMutation.isPending
                      ? t("production.molds.updating")
                      : t("production.molds.update")
                    : createMutation.isPending
                      ? t("production.molds.creating")
                      : t("production.molds.create")}
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
              {!isLoading && filteredMolds.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <EmptyState
                      icon={<Disc3 className="h-5 w-5" />}
                      title={t("production.molds.empty.title")}
                      description={t("production.molds.empty.description")}
                    />
                  </TableCell>
                </TableRow>
              )}
              <AnimatePresence initial={false}>
                {sortedMolds.map((mold, i) => (
                  <motion.tr
                    key={mold.id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i * 0.04, 0.3) } }}
                    exit={{ opacity: 0 }}
                    className="border-b border-border last:border-0 hover:bg-muted/50"
                  >
                    {visibleColumns.map((column) => (
                      <TableCell key={column.key} className={column.cellClassName}>
                        {column.cell(mold)}
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
