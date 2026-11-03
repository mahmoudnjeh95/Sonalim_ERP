import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, Plus, Power, Wallet } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { currentLocale, useI18n } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import {
  createAccount,
  listAccounts,
  listBanks,
  listMovements,
  updateAccount,
  type AccountInput,
  type AccountKind,
  type TreasuryAccount,
} from "./api";

const ACCOUNTS_KEY = ["treasury", "accounts"] as const;

function money(value: string, currency: string) {
  try {
    return new Intl.NumberFormat(currentLocale(), { style: "currency", currency, maximumFractionDigits: 0 }).format(Number(value));
  } catch {
    return `${value} ${currency}`;
  }
}

const EMPTY: AccountInput = { kind: "bank", name: "", currency: "XOF" };

export function AccountsTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canManage = hasPermission("treasury.manage_accounts");
  const [kindFilter, setKindFilter] = useState<"all" | AccountKind>("all");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<AccountInput>(EMPTY);
  const [movementsFor, setMovementsFor] = useState<TreasuryAccount | null>(null);

  const { data: accounts = [], isLoading } = useQuery({ queryKey: ACCOUNTS_KEY, queryFn: () => listAccounts(token, true) });
  const { data: banks = [] } = useQuery({ queryKey: ["treasury", "banks"], queryFn: () => listBanks(token) });
  const { data: movements = [] } = useQuery({
    queryKey: ["treasury", "movements", movementsFor?.id],
    queryFn: () => listMovements(token, movementsFor!.id),
    enabled: movementsFor !== null,
  });

  const branches = banks.flatMap((bank) => bank.branches.map((branch) => ({ ...branch, bankName: bank.name })));
  const visible = kindFilter === "all" ? accounts : accounts.filter((a) => a.kind === kindFilter);

  const fail = (key: Parameters<typeof t>[0]) => (error: unknown) =>
    toast.error(t(key), { description: error instanceof ApiError ? error.message : undefined });

  const createMutation = useMutation({
    mutationFn: () => createAccount(token, form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ACCOUNTS_KEY });
      setDialogOpen(false);
      setForm(EMPTY);
      toast.success(t("treasury.account.created"));
    },
    onError: fail("treasury.account.createError"),
  });
  const toggleMutation = useMutation({
    mutationFn: (account: TreasuryAccount) => updateAccount(token, account.id, { is_active: !account.is_active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ACCOUNTS_KEY }),
    onError: fail("treasury.account.updateError"),
  });

  const set = <K extends keyof AccountInput>(key: K, value: AccountInput[K]) => setForm((f) => ({ ...f, [key]: value }));

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <CardTitle>{t("treasury.accounts.title")}</CardTitle>
            <FilterTabs
              value={kindFilter}
              onChange={setKindFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "bank", label: t("treasury.kind.bank") },
                { value: "cash", label: t("treasury.kind.cash") },
                { value: "mobile_money", label: t("treasury.kind.mobile_money") },
              ]}
            />
          </div>
          {canManage && (
            <Button onClick={() => setDialogOpen(true)}>
              <Plus className="h-4 w-4" />
              {t("treasury.account.new")}
            </Button>
          )}
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("treasury.column.name")}</TableHead>
                <TableHead>{t("treasury.column.kind")}</TableHead>
                <TableHead>{t("treasury.column.details")}</TableHead>
                <TableHead className="text-right">{t("treasury.column.balance")}</TableHead>
                <TableHead className="text-right">{t("treasury.column.action")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && <TableLoadingRow colSpan={5} />}
              {!isLoading && visible.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="p-0">
                    <EmptyState icon={<Wallet className="h-5 w-5" />} title={t("treasury.accounts.empty.title")} description={t("treasury.accounts.empty.description")} />
                  </TableCell>
                </TableRow>
              )}
              {visible.map((account) => (
                <TableRow key={account.id} className={account.is_active ? undefined : "opacity-50"}>
                  <TableCell className="font-medium">{account.name}</TableCell>
                  <TableCell>{t(`treasury.kind.${account.kind}`)}</TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {account.kind === "bank" && (account.account_number ?? "—")}
                    {account.kind === "mobile_money" && `${account.operator ?? ""} ${account.phone ?? ""}`}
                    {account.kind === "cash" && "—"}
                    {account.ledger_account_code && ` · ${account.ledger_account_code}`}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{money(account.balance, account.currency)}</TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      <Button size="sm" variant="outline" onClick={() => setMovementsFor(account)}>
                        <History className="h-3.5 w-3.5" />
                        {t("treasury.account.movements")}
                      </Button>
                      {canManage && (
                        <Button size="sm" variant="outline" onClick={() => toggleMutation.mutate(account)}>
                          <Power className="h-3.5 w-3.5" />
                          {account.is_active ? t("treasury.account.deactivate") : t("treasury.account.activate")}
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("treasury.account.dialogTitle")}</DialogTitle>
            <DialogDescription>{t("treasury.account.dialogDescription")}</DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              createMutation.mutate();
            }}
          >
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="acc_kind">{t("treasury.column.kind")}</Label>
                <Select id="acc_kind" value={form.kind} onChange={(e) => set("kind", e.target.value as AccountKind)}>
                  <option value="bank">{t("treasury.kind.bank")}</option>
                  <option value="cash">{t("treasury.kind.cash")}</option>
                  <option value="mobile_money">{t("treasury.kind.mobile_money")}</option>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="acc_currency">{t("treasury.field.currency")}</Label>
                <Input id="acc_currency" value="F CFA" disabled />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="acc_name">{t("treasury.column.name")}</Label>
              <Input id="acc_name" required value={form.name} onChange={(e) => set("name", e.target.value)} />
            </div>
            {form.kind === "bank" && (
              <>
                <div className="space-y-1.5">
                  <Label htmlFor="acc_branch">{t("treasury.field.branch")}</Label>
                  <Select id="acc_branch" required value={form.branch_id ?? ""} onChange={(e) => set("branch_id", e.target.value)}>
                    <option value="">—</option>
                    {branches.map((branch) => (
                      <option key={branch.id} value={branch.id}>
                        {branch.bankName} — {branch.name}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="acc_number">{t("treasury.field.accountNumber")}</Label>
                    <Input id="acc_number" required value={form.account_number ?? ""} onChange={(e) => set("account_number", e.target.value)} />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="acc_iban">IBAN</Label>
                    <Input id="acc_iban" value={form.iban ?? ""} onChange={(e) => set("iban", e.target.value)} />
                  </div>
                </div>
              </>
            )}
            {form.kind === "mobile_money" && (
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label htmlFor="acc_operator">{t("treasury.field.operator")}</Label>
                  <Input id="acc_operator" required placeholder="orange_money / moov_money" value={form.operator ?? ""} onChange={(e) => set("operator", e.target.value)} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="acc_phone">{t("treasury.field.phone")}</Label>
                  <Input id="acc_phone" required value={form.phone ?? ""} onChange={(e) => set("phone", e.target.value)} />
                </div>
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="acc_opening">{t("treasury.field.openingBalance")}</Label>
                <Input id="acc_opening" type="number" step="1" value={form.opening_balance ?? 0} onChange={(e) => set("opening_balance", Number(e.target.value))} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="acc_ledger">{t("treasury.field.ledgerAccount")}</Label>
                <Input id="acc_ledger" placeholder="521" value={form.ledger_account_code ?? ""} onChange={(e) => set("ledger_account_code", e.target.value)} />
              </div>
            </div>
            <Button type="submit" className="w-full" disabled={createMutation.isPending}>
              {createMutation.isPending ? t("treasury.account.creating") : t("treasury.account.create")}
            </Button>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={movementsFor !== null} onOpenChange={(open) => !open && setMovementsFor(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{movementsFor?.name}</DialogTitle>
            <DialogDescription>{t("treasury.account.movementsDescription")}</DialogDescription>
          </DialogHeader>
          {movements.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("treasury.account.noMovements")}</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("treasury.column.date")}</TableHead>
                  <TableHead>{t("treasury.column.source")}</TableHead>
                  <TableHead className="text-right">{t("treasury.column.amount")}</TableHead>
                  <TableHead className="text-right">{t("treasury.column.balance")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {movements.map((m) => (
                  <TableRow key={m.id}>
                    <TableCell>{m.occurred_on}</TableCell>
                    <TableCell>{m.source_type}</TableCell>
                    <TableCell className="text-right tabular-nums">{money(m.amount, movementsFor!.currency)}</TableCell>
                    <TableCell className="text-right tabular-nums">{money(m.balance_after, movementsFor!.currency)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
