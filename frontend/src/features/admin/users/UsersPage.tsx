import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { ApiError } from "../../../lib/api";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Badge } from "../../../components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../../components/ui/table";
import { ColumnVisibilityMenu } from "../../../components/patterns/ColumnVisibilityMenu";
import { HelpTooltip } from "../../../components/patterns/HelpTooltip";
import { AppLoader } from "../../../components/patterns/AppLoader";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import {
  assignRole,
  grantPermission,
  listPermissionCatalog,
  listRoles,
  listUsers,
  revokePermission,
  unassignRole,
  updateUserName,
  type Role,
  type UserSummary,
} from "./api";

const USERS_QUERY_KEY = ["core", "users"] as const;
const CATALOG_QUERY_KEY = ["core", "permissions", "catalog"] as const;
const ROLES_QUERY_KEY = ["core", "roles"] as const;

function PermissionGrantControl({ user, available }: { user: UserSummary; available: string[] }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState(available[0] ?? "");

  const grantMutation = useMutation({
    mutationFn: (permission: string) => grantPermission(token, user.id, permission),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY }),
    onError: (error) => toast.error(t("admin.users.grant"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  if (available.length === 0) {
    return <span className="text-sm text-muted-foreground">{t("admin.users.allGranted")}</span>;
  }

  const value = available.includes(selected) ? selected : available[0];

  return (
    <div className="flex items-center gap-2">
      <select
        className="h-8 rounded-md border border-border bg-background px-2 text-sm"
        value={value}
        onChange={(event) => setSelected(event.target.value)}
      >
        {available.map((permission) => (
          <option key={permission} value={permission}>
            {permission}
          </option>
        ))}
      </select>
      <Button size="sm" variant="outline" onClick={() => grantMutation.mutate(value)} disabled={grantMutation.isPending}>
        {t("admin.users.grant")}
      </Button>
    </div>
  );
}

function RoleAssignControl({ user, availableRoles }: { user: UserSummary; availableRoles: Role[] }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState(availableRoles[0]?.id ?? "");

  const assignMutation = useMutation({
    mutationFn: (roleId: string) => assignRole(token, user.id, roleId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY }),
    onError: (error) => toast.error(t("admin.users.assignRole"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  if (availableRoles.length === 0) {
    return <span className="text-sm text-muted-foreground">{t("admin.users.noRolesAvailable")}</span>;
  }

  const value = availableRoles.some((role) => role.id === selected) ? selected : availableRoles[0].id;

  return (
    <div className="flex items-center gap-2">
      <select
        className="h-8 rounded-md border border-border bg-background px-2 text-sm"
        value={value}
        onChange={(event) => setSelected(event.target.value)}
      >
        {availableRoles.map((role) => (
          <option key={role.id} value={role.id}>
            {role.name}
          </option>
        ))}
      </select>
      <Button size="sm" variant="outline" onClick={() => assignMutation.mutate(value)} disabled={assignMutation.isPending}>
        {t("admin.users.assignRole")}
      </Button>
    </div>
  );
}

// Editable inline rather than a separate dialog: a name is one short field,
// and every other user picker in the app (an OF's supervisor, first) reads it
// straight off core.users, so getting one on file is meant to be a two-second
// action from the same table an admin already manages permissions from.
function NameCell({ user }: { user: UserSummary }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [value, setValue] = useState(user.full_name ?? "");

  const saveMutation = useMutation({
    mutationFn: (fullName: string) => updateUserName(token, user.id, fullName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY });
      toast.success(t("admin.users.nameUpdated"));
    },
    onError: (error) => {
      toast.error(t("admin.users.nameUpdateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const trimmed = value.trim();
  const isDirty = trimmed !== (user.full_name ?? "");

  return (
    <div className="flex items-center gap-2">
      <Input
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder={t("admin.users.namePlaceholder")}
        className="h-8"
      />
      {isDirty && (
        <Button size="sm" variant="outline" onClick={() => saveMutation.mutate(trimmed)} disabled={saveMutation.isPending}>
          {t("common.save")}
        </Button>
      )}
    </div>
  );
}

function AccessCell({ user }: { user: UserSummary }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();

  const unassignRoleMutation = useMutation({
    mutationFn: (roleId: string) => unassignRole(token, user.id, roleId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY }),
    onError: (error) => toast.error(t("admin.users.unassignRole"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const revokeMutation = useMutation({
    mutationFn: (permission: string) => revokePermission(token, user.id, permission),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY }),
    onError: (error) => toast.error(t("admin.users.revoke"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  if (user.roles.length === 0 && user.permissions.length === 0) {
    return <span className="text-sm text-muted-foreground">{t("admin.users.none")}</span>;
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      {user.roles.map((role) => (
        <Badge key={role.id} variant="primary" className="gap-1.5 pr-1.5">
          {role.name}
          <button
            type="button"
            aria-label={`${t("admin.users.unassignRole")} ${role.name}`}
            className="text-primary/70 hover:text-destructive"
            onClick={() => unassignRoleMutation.mutate(role.id)}
            disabled={unassignRoleMutation.isPending}
          >
            ×
          </button>
        </Badge>
      ))}
      {user.permissions.map((permission) => (
        <span key={permission} className="inline-flex items-center gap-1.5 rounded-md bg-muted px-2 py-1 text-xs">
          {permission}
          <button
            type="button"
            aria-label={`${t("admin.users.revoke")} ${permission}`}
            className="text-muted-foreground hover:text-destructive"
            onClick={() => revokeMutation.mutate(permission)}
            disabled={revokeMutation.isPending}
          >
            ×
          </button>
        </span>
      ))}
    </div>
  );
}

function GrantCell({ user, allRoles, allPermissions }: { user: UserSummary; allRoles: Role[]; allPermissions: string[] }) {
  const { t } = useI18n();
  const [showDirect, setShowDirect] = useState(false);

  const assignedRoleIds = new Set(user.roles.map((role) => role.id));
  const availableRoles = allRoles.filter((role) => !assignedRoleIds.has(role.id));
  const availablePermissions = allPermissions.filter((permission) => !user.permissions.includes(permission));

  return (
    <div className="space-y-1.5">
      <RoleAssignControl user={user} availableRoles={availableRoles} />
      <button
        type="button"
        className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        onClick={() => setShowDirect((prev) => !prev)}
      >
        {t(showDirect ? "admin.users.directGrant.hide" : "admin.users.directGrant.show")}
      </button>
      {showDirect && <PermissionGrantControl user={user} available={availablePermissions} />}
    </div>
  );
}

export function UsersPage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [search, setSearch] = useState("");

  const {
    data: users = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: USERS_QUERY_KEY,
    queryFn: () => listUsers(token),
  });

  const { data: catalog = [] } = useQuery({
    queryKey: CATALOG_QUERY_KEY,
    queryFn: () => listPermissionCatalog(token),
  });

  const { data: roles = [] } = useQuery({
    queryKey: ROLES_QUERY_KEY,
    queryFn: () => listRoles(token),
  });

  const allPermissions = catalog.map((entry) => entry.permission);
  const filteredUsers = search.trim()
    ? users.filter((user) => user.email.toLowerCase().includes(search.trim().toLowerCase()))
    : users;

  const columns: ColumnDef<UserSummary>[] = [
    {
      key: "name",
      header: t("admin.users.column.name"),
      defaultWidth: 200,
      cell: (user) => <NameCell user={user} />,
      sortValue: (user) => user.full_name ?? "",
    },
    { key: "email", header: t("admin.users.column.email"), defaultWidth: 220, cell: (user) => user.email, sortValue: (user) => user.email },
    {
      key: "permissions",
      header: t("admin.users.column.permissions"),
      defaultWidth: 360,
      cell: (user) => <AccessCell user={user} />,
    },
    {
      key: "grant",
      header: t("admin.users.column.grant"),
      defaultWidth: 240,
      alwaysVisible: true,
      cell: (user) => <GrantCell user={user} allRoles={roles} allPermissions={allPermissions} />,
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("admin.users", columns);
  const sortedUsers = sortRows(filteredUsers);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-1.5 text-xl font-semibold">
          {t("admin.users.title")}
          <HelpTooltip text={t("admin.users.help.permissions")} />
        </h1>
        <p className="text-sm text-muted-foreground">{t("admin.users.subtitle")}</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("admin.users.table.title")}</CardTitle>
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative w-full max-w-xs">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder={t("admin.users.searchPlaceholder")}
                className="pl-8"
              />
            </div>
            <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
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
                    sortDirection={sortDirectionFor(column.key)}
                    onSort={column.sortValue ? () => toggleSort(column.key) : undefined}
                  >
                    {column.header}
                  </ResizableTableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <AppLoader label={t("admin.users.loading")} className="py-8" />
                  </TableCell>
                </TableRow>
              )}
              {isError && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="py-8 text-center text-destructive">
                    {t("admin.users.loadError")}
                  </TableCell>
                </TableRow>
              )}
              {!isLoading && !isError && filteredUsers.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="py-8 text-center text-muted-foreground">
                    {t("admin.users.none")}
                  </TableCell>
                </TableRow>
              )}
              {!isLoading &&
                !isError &&
                sortedUsers.map((user) => (
                  <TableRow key={user.id}>
                    {visibleColumns.map((column) => (
                      <TableCell key={column.key} className={column.cellClassName}>
                        {column.cell(user)}
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
