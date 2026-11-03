import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Label } from "../../../components/ui/label";
import { Checkbox } from "../../../components/ui/checkbox";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../../components/ui/table";
import { ColumnFilterRow } from "../../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../../components/patterns/ColumnVisibilityMenu";
import { HelpTooltip } from "../../../components/patterns/HelpTooltip";
import { EmptyState } from "../../../components/patterns/EmptyState";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../../components/ui/dialog";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { useColumnFilters, type FilterField } from "../../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import {
  createRole,
  deleteRole,
  listPermissionCatalog,
  listRoles,
  updateRole,
  type PermissionCatalogEntry,
  type Role,
} from "../users/api";

const ROLES_QUERY_KEY = ["core", "roles"] as const;
const CATALOG_QUERY_KEY = ["core", "permissions", "catalog"] as const;

interface FormState {
  code: string;
  name: string;
  description: string;
  permissions: Set<string>;
}

const EMPTY_FORM: FormState = { code: "", name: "", description: "", permissions: new Set() };

function groupByModule(catalog: PermissionCatalogEntry[]): Map<string, string[]> {
  const map = new Map<string, string[]>();
  for (const entry of catalog) {
    const list = map.get(entry.module) ?? [];
    list.push(entry.permission);
    map.set(entry.module, list);
  }
  for (const list of map.values()) list.sort();
  return map;
}

function RoleFormDialog({
  open,
  onOpenChange,
  isEditing,
  form,
  setForm,
  catalog,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  isEditing: boolean;
  form: FormState;
  setForm: (updater: (prev: FormState) => FormState) => void;
  catalog: PermissionCatalogEntry[];
  onSubmit: () => void;
  isPending: boolean;
}) {
  const { t } = useI18n();

  const MODULE_LABELS: Record<string, string> = {
    core: t("admin.roles.module.core"),
    crm: t("admin.roles.module.crm"),
    finance: t("admin.roles.module.finance"),
    hr: t("admin.roles.module.hr"),
    procurement: t("admin.roles.module.procurement"),
    production: t("admin.roles.module.production"),
    qc: t("admin.roles.module.qc"),
    sales: t("admin.roles.module.sales"),
    warehouse: t("admin.roles.module.warehouse"),
  };

  const grouped = groupByModule(catalog);

  function toggleModule(permissions: string[], checked: boolean) {
    setForm((prev) => {
      const next = new Set(prev.permissions);
      for (const permission of permissions) {
        if (checked) next.add(permission);
        else next.delete(permission);
      }
      return { ...prev, permissions: next };
    });
  }

  function togglePermission(permission: string, checked: boolean) {
    setForm((prev) => {
      const next = new Set(prev.permissions);
      if (checked) next.add(permission);
      else next.delete(permission);
      return { ...prev, permissions: next };
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t(isEditing ? "admin.roles.dialog.editTitle" : "admin.roles.dialog.createTitle")}</DialogTitle>
          <DialogDescription>{t("admin.roles.dialog.description")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="role-code">{t("admin.roles.field.code")}</Label>
              <Input
                id="role-code"
                value={form.code}
                disabled={isEditing}
                onChange={(event) => setForm((prev) => ({ ...prev, code: event.target.value }))}
              />
              {!isEditing && <p className="text-xs text-muted-foreground">{t("admin.roles.field.codeHelp")}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="role-name">{t("admin.roles.field.name")}</Label>
              <Input
                id="role-name"
                value={form.name}
                onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="role-description">{t("admin.roles.field.description")}</Label>
            <textarea
              id="role-description"
              value={form.description}
              onChange={(event) => setForm((prev) => ({ ...prev, description: event.target.value }))}
              rows={2}
              className="flex w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          <div className="space-y-2">
            <Label>{t("admin.roles.field.permissions")}</Label>
            <div className="max-h-80 space-y-3 overflow-y-auto rounded-md border border-border p-3">
              {[...grouped.entries()].map(([module, permissions]) => {
                const allChecked = permissions.every((p) => form.permissions.has(p));
                return (
                  <div key={module}>
                    <div className="mb-1.5 flex items-center gap-2">
                      <Checkbox
                        checked={allChecked}
                        onCheckedChange={(checked) => toggleModule(permissions, checked === true)}
                      />
                      <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        {MODULE_LABELS[module] ?? module}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1 pl-6">
                      {permissions.map((permission) => (
                        <label key={permission} className="flex items-center gap-2 text-sm">
                          <Checkbox
                            checked={form.permissions.has(permission)}
                            onCheckedChange={(checked) => togglePermission(permission, checked === true)}
                          />
                          <span className="truncate">{permission}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button onClick={onSubmit} disabled={isPending || !form.code || !form.name}>
              {isPending
                ? t(isEditing ? "common.saving" : "admin.roles.creating")
                : t(isEditing ? "admin.roles.save" : "admin.roles.create")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function RolesPage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingRole, setEditingRole] = useState<Role | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);

  const {
    data: roles = [],
    isLoading,
    isError,
  } = useQuery({ queryKey: ROLES_QUERY_KEY, queryFn: () => listRoles(token) });

  const { data: catalog = [] } = useQuery({
    queryKey: CATALOG_QUERY_KEY,
    queryFn: () => listPermissionCatalog(token),
  });

  function openCreateDialog() {
    setEditingRole(null);
    setForm(EMPTY_FORM);
    setDialogOpen(true);
  }

  function openEditDialog(role: Role) {
    setEditingRole(role);
    setForm({ code: role.code, name: role.name, description: role.description ?? "", permissions: new Set(role.permissions) });
    setDialogOpen(true);
  }

  const createMutation = useMutation({
    mutationFn: () =>
      createRole(token, { code: form.code, name: form.name, description: form.description || null, permissions: [...form.permissions] }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ROLES_QUERY_KEY });
      setDialogOpen(false);
      toast.success(t("admin.roles.saved"));
    },
    onError: (error) => {
      toast.error(t("admin.roles.saveError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const updateMutation = useMutation({
    mutationFn: () =>
      updateRole(token, editingRole!.id, {
        name: form.name,
        description: form.description || null,
        permissions: [...form.permissions],
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ROLES_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["core", "users"] });
      setDialogOpen(false);
      toast.success(t("admin.roles.saved"));
    },
    onError: (error) => {
      toast.error(t("admin.roles.saveError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (roleId: string) => deleteRole(token, roleId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ROLES_QUERY_KEY });
      toast.success(t("admin.roles.deleted"));
    },
    onError: (error) => {
      toast.error(t("admin.roles.deleteError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const columnFilterFields: FilterField<Role>[] = [
    { key: "name", kind: "text", getValue: (role) => role.name },
    { key: "code", kind: "text", getValue: (role) => role.code },
    { key: "description", kind: "text", getValue: (role) => role.description ?? "" },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredRoles = columnFilters.apply(roles);

  const columns: ColumnDef<Role>[] = [
    {
      key: "name",
      header: t("admin.roles.column.name"),
      defaultWidth: 220,
      cell: (role) => <span className="font-medium">{role.name}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.name ?? "",
        onChange: (v) => columnFilters.setTextValue("name", v),
        placeholder: t("admin.roles.column.name"),
      },
    },
    {
      key: "code",
      header: t("admin.roles.column.code"),
      defaultWidth: 160,
      cell: (role) => <span className="text-muted-foreground">{role.code}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.code ?? "",
        onChange: (v) => columnFilters.setTextValue("code", v),
        placeholder: t("admin.roles.column.code"),
      },
    },
    {
      key: "description",
      header: t("admin.roles.column.description"),
      defaultWidth: 320,
      cell: (role) => <span className="text-muted-foreground">{role.description || "—"}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.description ?? "",
        onChange: (v) => columnFilters.setTextValue("description", v),
        placeholder: t("admin.roles.column.description"),
      },
    },
    {
      key: "permissionCount",
      header: t("admin.roles.column.permissionCount"),
      defaultWidth: 120,
      cell: (role) => role.permissions.length,
    },
    {
      key: "actions",
      header: t("admin.roles.column.actions"),
      defaultWidth: 100,
      alwaysVisible: true,
      cell: (role) => (
        <div className="flex items-center gap-1">
          <Button size="sm" variant="ghost" aria-label={t("common.edit")} onClick={() => openEditDialog(role)}>
            <Pencil className="h-3.5 w-3.5" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label={t("common.delete")}
            onClick={() => deleteMutation.mutate(role.id)}
            disabled={deleteMutation.isPending}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "admin.roles",
    columns,
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">{t("admin.roles.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("admin.roles.subtitle")}</p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-1.5">
                {t("admin.roles.table.title")}
                <HelpTooltip text={t("admin.roles.dialog.description")} />
              </CardTitle>
            </div>
            <div className="flex items-center gap-2">
              {columnFilters.isActive && (
                <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                  {t("common.clearFilters")}
                </Button>
              )}
              <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
              <Button onClick={openCreateDialog}>
                <Plus className="h-4 w-4" />
                {t("admin.roles.new")}
              </Button>
            </div>
          </div>
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
              {isLoading && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <AppLoader label={t("admin.roles.loading")} className="py-8" />
                  </TableCell>
                </TableRow>
              )}
              {isError && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="py-8 text-center text-destructive">
                    {t("admin.roles.loadError")}
                  </TableCell>
                </TableRow>
              )}
              {!isLoading && !isError && filteredRoles.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length}>
                    <EmptyState
                      icon={<KeyRound className="h-5 w-5" />}
                      title={t("admin.roles.empty.title")}
                      description={t("admin.roles.empty.description")}
                    />
                  </TableCell>
                </TableRow>
              )}
              {!isLoading &&
                !isError &&
                filteredRoles.map((role) => (
                  <TableRow key={role.id}>
                    {visibleColumns.map((column) => (
                      <TableCell key={column.key} className={column.cellClassName}>
                        {column.cell(role)}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <RoleFormDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        isEditing={editingRole !== null}
        form={form}
        setForm={setForm}
        catalog={catalog}
        onSubmit={() => (editingRole ? updateMutation.mutate() : createMutation.mutate())}
        isPending={editingRole ? updateMutation.isPending : createMutation.isPending}
      />
    </div>
  );
}
