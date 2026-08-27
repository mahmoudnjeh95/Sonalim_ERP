import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useAuth } from "../../../lib/auth";
import { useI18n } from "../../../lib/i18n";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../../components/ui/table";
import { ColumnVisibilityMenu } from "../../../components/patterns/ColumnVisibilityMenu";
import { useTableColumns, type ColumnDef } from "../../../lib/useTableColumns";
import { grantPermission, listPermissionCatalog, listUsers, revokePermission, type UserSummary } from "./api";

const USERS_QUERY_KEY = ["core", "users"] as const;
const CATALOG_QUERY_KEY = ["core", "permissions", "catalog"] as const;

function GrantControl({ user, available }: { user: UserSummary; available: string[] }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState(available[0] ?? "");

  const grantMutation = useMutation({
    mutationFn: (permission: string) => grantPermission(token, user.id, permission),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY }),
  });

  if (available.length === 0) {
    return <span className="text-sm text-muted-foreground">{t("admin.users.allGranted")}</span>;
  }

  return (
    <div className="flex items-center gap-2">
      <select
        className="h-8 rounded-md border border-border bg-background px-2 text-sm"
        value={available.includes(selected) ? selected : available[0]}
        onChange={(event) => setSelected(event.target.value)}
      >
        {available.map((permission) => (
          <option key={permission} value={permission}>
            {permission}
          </option>
        ))}
      </select>
      <Button
        size="sm"
        variant="outline"
        onClick={() => grantMutation.mutate(available.includes(selected) ? selected : available[0])}
        disabled={grantMutation.isPending}
      >
        {t("admin.users.grant")}
      </Button>
    </div>
  );
}

export function UsersPage() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
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

  const revokeMutation = useMutation({
    mutationFn: ({ userId, permission }: { userId: string; permission: string }) =>
      revokePermission(token, userId, permission),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY }),
  });

  const allPermissions = catalog.map((entry) => entry.permission);
  const filteredUsers = search.trim()
    ? users.filter((user) => user.email.toLowerCase().includes(search.trim().toLowerCase()))
    : users;

  const columns: ColumnDef<UserSummary>[] = [
    { key: "email", header: t("admin.users.column.email"), defaultWidth: 220, cell: (user) => user.email },
    {
      key: "permissions",
      header: t("admin.users.column.permissions"),
      defaultWidth: 320,
      cell: (user) => (
        <div className="flex flex-wrap gap-1.5">
          {user.permissions.length === 0 && <span className="text-sm text-muted-foreground">{t("admin.users.none")}</span>}
          {user.permissions.map((permission) => (
            <span key={permission} className="inline-flex items-center gap-1.5 rounded-md bg-muted px-2 py-1 text-xs">
              {permission}
              <button
                type="button"
                aria-label={`${t("admin.users.revoke")} ${permission}`}
                className="text-muted-foreground hover:text-destructive"
                onClick={() => revokeMutation.mutate({ userId: user.id, permission })}
                disabled={revokeMutation.isPending}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      ),
    },
    {
      key: "grant",
      header: t("admin.users.column.grant"),
      defaultWidth: 220,
      alwaysVisible: true,
      cell: (user) => (
        <GrantControl user={user} available={allPermissions.filter((permission) => !user.permissions.includes(permission))} />
      ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "admin.users",
    columns,
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">{t("admin.users.title")}</h1>
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
                  >
                    {column.header}
                  </ResizableTableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="py-8 text-center text-muted-foreground">
                    {t("admin.users.loading")}
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
                filteredUsers.map((user) => (
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
