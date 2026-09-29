import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ListTree, Pencil, Plus, WandSparkles } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n, type TranslationKey } from "../../lib/i18n";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import type { ColumnDef } from "../../lib/useTableColumns";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { LedgerTable, textFilter } from "./LedgerTable";
import { errorText } from "./ledgerFormat";
import {
  ACCOUNT_TYPES,
  LEDGER_KEYS,
  createAccount,
  listAccounts,
  setupLedger,
  updateAccount,
  type AccountType,
  type LedgerAccount,
} from "./ledgerApi";

export const ACCOUNT_TYPE_KEYS: Record<AccountType, TranslationKey> = {
  asset: "finance.accounts.type.asset",
  liability: "finance.accounts.type.liability",
  equity: "finance.accounts.type.equity",
  income: "finance.accounts.type.income",
  expense: "finance.accounts.type.expense",
};

const CLASSES = ["1", "2", "3", "4", "5", "6", "7", "8", "9"] as const;
type ClassFilter = "all" | (typeof CLASSES)[number];

export function AccountsPage() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [classFilter, setClassFilter] = useState<ClassFilter>("all");
  const [editing, setEditing] = useState<LedgerAccount | "new" | null>(null);
  const { data: accounts = [], isLoading } = useQuery({ queryKey: LEDGER_KEYS.accounts, queryFn: () => listAccounts(token) });

  const setupMutation = useMutation({
    mutationFn: () => setupLedger(token),
    onSuccess: () => {
      for (const queryKey of [LEDGER_KEYS.accounts, LEDGER_KEYS.journals, LEDGER_KEYS.rules]) {
        void queryClient.invalidateQueries({ queryKey });
      }
      toast.success(t("finance.accounts.setupDone"));
    },
    onError: (error) => toast.error(t("finance.accounts.setupError"), { description: errorText(error) }),
  });

  const fields: FilterField<LedgerAccount>[] = [
    { key: "code", kind: "text", getValue: (account) => account.code },
    { key: "name", kind: "text", getValue: (account) => account.name },
    { key: "account_type", kind: "text", getValue: (account) => t(ACCOUNT_TYPE_KEYS[account.account_type]) },
    { key: "parent_code", kind: "text", getValue: (account) => account.parent_code ?? "" },
  ];
  const columnFilters = useColumnFilters(fields);
  const byClass = classFilter === "all" ? accounts : accounts.filter((account) => String(account.class_no) === classFilter);
  const rows = columnFilters.apply(byClass);

  const columns: ColumnDef<LedgerAccount>[] = [
    {
      key: "code",
      header: t("finance.accounts.column.code"),
      defaultWidth: 120,
      cell: (account) => (
        <span className="font-mono tabular-nums" style={{ paddingLeft: `${(account.code.length - 1) * 10}px` }}>
          {account.code}
        </span>
      ),
      filterCell: textFilter(columnFilters, "code", t("finance.accounts.column.code")),
      sortValue: (account) => account.code,
    },
    {
      key: "name",
      header: t("finance.accounts.column.name"),
      defaultWidth: 340,
      cell: (account) => <span className={account.is_postable ? undefined : "font-semibold"}>{account.name}</span>,
      filterCell: textFilter(columnFilters, "name", t("finance.accounts.column.name")),
      sortValue: (account) => account.name,
    },
    {
      key: "account_type",
      header: t("finance.accounts.column.type"),
      defaultWidth: 140,
      cell: (account) => t(ACCOUNT_TYPE_KEYS[account.account_type]),
      filterCell: textFilter(columnFilters, "account_type", t("finance.accounts.column.type")),
      sortValue: (account) => account.account_type,
    },
    {
      key: "is_postable",
      header: t("finance.accounts.column.postable"),
      defaultWidth: 130,
      cell: (account) =>
        account.is_postable ? (
          <Badge variant="success">{t("finance.accounts.postable")}</Badge>
        ) : (
          <Badge>{t("finance.accounts.heading")}</Badge>
        ),
      sortValue: (account) => account.is_postable,
    },
    {
      key: "parent_code",
      header: t("finance.accounts.column.parent"),
      defaultWidth: 110,
      cell: (account) => <span className="font-mono">{account.parent_code ?? "—"}</span>,
      filterCell: textFilter(columnFilters, "parent_code", t("finance.accounts.column.parent")),
      sortValue: (account) => account.parent_code ?? "",
    },
    {
      key: "actions",
      header: t("finance.column.action"),
      defaultWidth: 120,
      alwaysVisible: true,
      headerClassName: "text-right",
      cell: (account) =>
        hasPermission("finance.admin_accounts") ? (
          <div className="flex justify-end">
            <Button size="sm" variant="outline" onClick={() => setEditing(account)}>
              <Pencil className="h-3.5 w-3.5" />
              {t("common.edit")}
            </Button>
          </div>
        ) : null,
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{t("finance.accounts.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("finance.accounts.subtitle")}</p>
        </div>
        <div className="flex gap-2">
          {hasPermission("finance.admin_accounts") && (
            <Button variant="outline" onClick={() => setupMutation.mutate()} disabled={setupMutation.isPending}>
              <WandSparkles className="h-4 w-4" />
              {t("finance.accounts.setup")}
            </Button>
          )}
          {hasPermission("finance.manage_accounts") && (
            <Button onClick={() => setEditing("new")}>
              <Plus className="h-4 w-4" />
              {t("finance.accounts.new")}
            </Button>
          )}
        </div>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>{t("finance.accounts.tableTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="p-0 pb-2">
          <LedgerTable
            tableKey="finance.accounts"
            columns={columns}
            rows={rows}
            rowKey={(account) => account.code}
            isLoading={isLoading}
            emptyIcon={<ListTree className="h-5 w-5" />}
            emptyTitle={t("finance.accounts.emptyTitle")}
            emptyDescription={t("finance.accounts.emptyDescription")}
            toolbar={
              <>
                <FilterTabs
                  value={classFilter}
                  onChange={setClassFilter}
                  options={[
                    { value: "all", label: t("common.all") },
                    ...CLASSES.map((classNo) => ({ value: classNo, label: `${t("finance.accounts.classShort")} ${classNo}` })),
                  ]}
                />
                {columnFilters.isActive && (
                  <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                    {t("common.clearFilters")}
                  </Button>
                )}
              </>
            }
          />
        </CardContent>
      </Card>
      {editing !== null && (
        <AccountDialog account={editing === "new" ? null : editing} accounts={accounts} onClose={() => setEditing(null)} />
      )}
    </div>
  );
}

function AccountDialog({
  account,
  accounts,
  onClose,
}: {
  account: LedgerAccount | null;
  accounts: LedgerAccount[];
  onClose: () => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const schema = useMemo(
    () =>
      z.object({
        code: z.string().trim().regex(/^[1-9][0-9]{0,9}$/, t("finance.accounts.codeInvalid")),
        name: z.string().trim().min(1, t("common.required")),
        account_type: z.enum(ACCOUNT_TYPES),
        is_postable: z.boolean(),
        parent_code: z.string(),
      }),
    [t],
  );
  type AccountForm = z.infer<typeof schema>;
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<AccountForm>({
    resolver: zodResolver(schema),
    defaultValues: account
      ? {
          code: account.code,
          name: account.name,
          account_type: account.account_type,
          is_postable: account.is_postable,
          parent_code: account.parent_code ?? "",
        }
      : { code: "", name: "", account_type: "asset", is_postable: true, parent_code: "" },
  });
  const mutation = useMutation({
    mutationFn: (form: AccountForm) =>
      account
        ? updateAccount(token, account.code, {
            name: form.name,
            account_type: form.account_type,
            is_postable: form.is_postable,
            parent_code: form.parent_code,
          })
        : createAccount(token, {
            code: form.code,
            name: form.name,
            account_type: form.account_type,
            is_postable: form.is_postable,
            parent_code: form.parent_code || null,
          }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: LEDGER_KEYS.accounts });
      toast.success(t(account ? "finance.accounts.updated" : "finance.accounts.created"));
      onClose();
    },
    onError: (error) => toast.error(t("finance.accounts.saveError"), { description: errorText(error) }),
  });
  const parents = accounts.filter((candidate) => candidate.code !== account?.code);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(account ? "finance.accounts.editTitle" : "finance.accounts.newTitle")}</DialogTitle>
          <DialogDescription>{t("finance.accounts.dialogDescription")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit((form) => mutation.mutate(form))}>
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="account_code">{t("finance.accounts.column.code")}</Label>
              {/* readOnly, not disabled: a disabled field is left out of the submitted values. */}
              <Input id="account_code" readOnly={account !== null} {...register("code")} />
              {errors.code && <p className="text-sm text-destructive">{errors.code.message}</p>}
            </div>
            <div className="col-span-2 space-y-1.5">
              <Label htmlFor="account_name">{t("finance.accounts.column.name")}</Label>
              <Input id="account_name" {...register("name")} />
              {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="account_type">{t("finance.accounts.column.type")}</Label>
              <Select id="account_type" {...register("account_type")}>
                {ACCOUNT_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {t(ACCOUNT_TYPE_KEYS[type])}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="account_parent">{t("finance.accounts.column.parent")}</Label>
              <Select id="account_parent" {...register("parent_code")}>
                <option value="">{t("common.none")}</option>
                {parents.map((candidate) => (
                  <option key={candidate.code} value={candidate.code}>
                    {candidate.code} · {candidate.name}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="h-4 w-4" {...register("is_postable")} />
            {t("finance.accounts.postableHint")}
          </label>
          <Button type="submit" className="w-full" disabled={mutation.isPending}>
            {mutation.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
