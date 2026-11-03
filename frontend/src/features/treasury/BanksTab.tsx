import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Landmark, Plus } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { EmptyState } from "../../components/patterns/EmptyState";
import { addBranch, createBank, listBanks, type Bank } from "./api";

const BANKS_KEY = ["treasury", "banks"] as const;

export function BanksTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canManage = hasPermission("treasury.manage_accounts");
  const [bankDialog, setBankDialog] = useState(false);
  const [bankName, setBankName] = useState("");
  const [branchBank, setBranchBank] = useState<Bank | null>(null);
  const [branchName, setBranchName] = useState("");
  const [branchCity, setBranchCity] = useState("");

  const { data: banks = [] } = useQuery({ queryKey: BANKS_KEY, queryFn: () => listBanks(token) });

  const fail = (error: unknown) =>
    toast.error(t("treasury.bank.saveError"), { description: error instanceof ApiError ? error.message : undefined });

  const bankMutation = useMutation({
    mutationFn: () => createBank(token, { name: bankName }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: BANKS_KEY });
      setBankDialog(false);
      setBankName("");
      toast.success(t("treasury.bank.created"));
    },
    onError: fail,
  });
  const branchMutation = useMutation({
    mutationFn: () => addBranch(token, branchBank!.id, { name: branchName, city: branchCity || undefined }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: BANKS_KEY });
      setBranchBank(null);
      setBranchName("");
      setBranchCity("");
      toast.success(t("treasury.branch.created"));
    },
    onError: fail,
  });

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t("treasury.banks.title")}</CardTitle>
          {canManage && (
            <Button onClick={() => setBankDialog(true)}>
              <Plus className="h-4 w-4" />
              {t("treasury.bank.new")}
            </Button>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          {banks.length === 0 && <EmptyState icon={<Landmark className="h-5 w-5" />} title={t("treasury.banks.empty.title")} description={t("treasury.banks.empty.description")} />}
          {banks.map((bank) => (
            <div key={bank.id} className="rounded-md border border-border p-3">
              <div className="flex items-center justify-between">
                <p className="font-medium">{bank.name}</p>
                {canManage && (
                  <Button size="sm" variant="outline" onClick={() => setBranchBank(bank)}>
                    <Plus className="h-3.5 w-3.5" />
                    {t("treasury.branch.new")}
                  </Button>
                )}
              </div>
              {bank.branches.length === 0 ? (
                <p className="mt-1 text-sm text-muted-foreground">{t("treasury.branch.none")}</p>
              ) : (
                <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
                  {bank.branches.map((branch) => (
                    <li key={branch.id}>
                      {branch.name}
                      {branch.city && ` · ${branch.city}`}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </CardContent>
      </Card>

      <Dialog open={bankDialog} onOpenChange={setBankDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("treasury.bank.new")}</DialogTitle>
            <DialogDescription>{t("treasury.bank.dialogDescription")}</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); bankMutation.mutate(); }}>
            <div className="space-y-1.5">
              <Label htmlFor="bank_name">{t("treasury.column.name")}</Label>
              <Input id="bank_name" required value={bankName} onChange={(e) => setBankName(e.target.value)} />
            </div>
            <Button type="submit" className="w-full" disabled={bankMutation.isPending}>
              {t("treasury.bank.create")}
            </Button>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={branchBank !== null} onOpenChange={(open) => !open && setBranchBank(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("treasury.branch.new")}</DialogTitle>
            <DialogDescription>{branchBank?.name}</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); branchMutation.mutate(); }}>
            <div className="space-y-1.5">
              <Label htmlFor="branch_name">{t("treasury.column.name")}</Label>
              <Input id="branch_name" required value={branchName} onChange={(e) => setBranchName(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="branch_city">{t("treasury.field.city")}</Label>
              <Input id="branch_city" value={branchCity} onChange={(e) => setBranchCity(e.target.value)} />
            </div>
            <Button type="submit" className="w-full" disabled={branchMutation.isPending}>
              {t("treasury.branch.create")}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
