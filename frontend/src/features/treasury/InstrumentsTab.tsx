import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Banknote, Landmark, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { currentLocale, useI18n } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Checkbox } from "../../components/ui/checkbox";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import { listPartners } from "../partners/api";
import { listAccounts } from "./api";
import { listInstruments, markUnpaid, postDepositSlip, type Instrument } from "./instrumentsApi";

type Key = Parameters<ReturnType<typeof useI18n>["t"]>[0];
type StatusFilter = "all" | Instrument["status"];

function money(value: string, currency: string) {
  try {
    return new Intl.NumberFormat(currentLocale(), { style: "currency", currency, maximumFractionDigits: 0 }).format(Number(value));
  } catch {
    return `${value} ${currency}`;
  }
}

const today = () => new Date().toISOString().slice(0, 10);

export function InstrumentsTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canCollect = hasPermission("treasury.collect_instruments");
  const [filter, setFilter] = useState<StatusFilter>("pending");
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [slipOpen, setSlipOpen] = useState(false);
  const [accountId, setAccountId] = useState("");
  const [slipDate, setSlipDate] = useState(today());
  const [unpaidTarget, setUnpaidTarget] = useState<Instrument | null>(null);
  const [feeAmount, setFeeAmount] = useState("");
  const [feeAccountId, setFeeAccountId] = useState("");

  const { data: instruments = [], isLoading } = useQuery({ queryKey: ["treasury", "instruments"], queryFn: () => listInstruments(token) });
  const { data: partners = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token) });
  const { data: accounts = [] } = useQuery({ queryKey: ["treasury", "accounts"], queryFn: () => listAccounts(token) });
  const partnerName = (id: string) => partners.find((p) => p.id === id)?.name ?? "—";

  const visible = filter === "all" ? instruments : instruments.filter((i) => i.status === filter);
  const chosen = instruments.filter((i) => selected[i.id] && i.status === "pending");

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["treasury", "instruments"] });
    queryClient.invalidateQueries({ queryKey: ["treasury", "accounts"] });
    queryClient.invalidateQueries({ queryKey: ["treasury", "alerts"] });
  };
  const fail = (key: Key) => (error: unknown) =>
    toast.error(t(key), { description: error instanceof ApiError ? error.message : undefined });

  const slipMutation = useMutation({
    mutationFn: (outcome: "collected" | "unpaid") =>
      postDepositSlip(token, { account_id: accountId, slip_date: slipDate, items: chosen.map((i) => ({ instrument_id: i.id, outcome })) }),
    onSuccess: () => {
      refresh();
      setSlipOpen(false);
      setSelected({});
      toast.success(t("treasury.instruments.slipPosted"));
    },
    onError: fail("treasury.instruments.slipError"),
  });
  const unpaidMutation = useMutation({
    mutationFn: (id: string) =>
      markUnpaid(token, id, feeAmount.trim() ? { rejection_fee: Number(feeAmount), rejection_fee_account_id: feeAccountId } : undefined),
    onSuccess: () => {
      refresh();
      setUnpaidTarget(null);
      toast.success(t("treasury.instruments.markedUnpaid"));
    },
    onError: fail("treasury.instruments.unpaidError"),
  });

  const eligibleAccounts = accounts.filter((a) => (a.kind === "bank" || a.kind === "cash") && a.is_active);
  const feeAccounts = eligibleAccounts;
  const feeEntered = feeAmount.trim() !== "";
  const feeValid = !feeEntered || (Number.isInteger(Number(feeAmount)) && Number(feeAmount) > 0 && feeAccountId !== "");
  const openUnpaid = (instrument: Instrument) => {
    setUnpaidTarget(instrument);
    setFeeAmount("");
    setFeeAccountId(instrument.account_id ?? "");
  };

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <CardTitle>{t("treasury.instruments.title")}</CardTitle>
            <FilterTabs
              value={filter}
              onChange={setFilter}
              options={[
                { value: "pending", label: t("treasury.instruments.status.pending") },
                { value: "collected", label: t("treasury.instruments.status.collected") },
                { value: "unpaid", label: t("treasury.instruments.status.unpaid") },
                { value: "all", label: t("common.all") },
              ]}
            />
          </div>
          {canCollect && (
            <Button disabled={chosen.length === 0} onClick={() => setSlipOpen(true)}>
              <Landmark className="h-4 w-4" />
              {t("treasury.instruments.slip")} ({chosen.length})
            </Button>
          )}
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10" />
                <TableHead>{t("treasury.instruments.column.instrument")}</TableHead>
                <TableHead>{t("treasury.column.partner")}</TableHead>
                <TableHead>{t("treasury.instruments.column.due")}</TableHead>
                <TableHead className="text-right">{t("treasury.column.amount")}</TableHead>
                <TableHead>{t("treasury.column.status")}</TableHead>
                <TableHead className="text-right">{t("treasury.column.action")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && <TableLoadingRow colSpan={7} />}
              {!isLoading && visible.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="p-0">
                    <EmptyState icon={<Banknote className="h-5 w-5" />} title={t("treasury.instruments.empty.title")} description={t("treasury.instruments.empty.description")} />
                  </TableCell>
                </TableRow>
              )}
              {visible.map((instrument) => {
                const overdue = instrument.status === "pending" && instrument.due_date < today();
                return (
                  <TableRow key={instrument.id}>
                    <TableCell>
                      {instrument.status === "pending" && (
                        <Checkbox
                          checked={!!selected[instrument.id]}
                          onCheckedChange={(value) => setSelected((s) => ({ ...s, [instrument.id]: value === true }))}
                        />
                      )}
                    </TableCell>
                    <TableCell>
                      <span className="font-medium">{t(`treasury.method.${instrument.method}` as Key)} {instrument.number}</span>
                      <span className="block text-xs text-muted-foreground">
                        {t(instrument.direction === "in" ? "treasury.instruments.received" : "treasury.instruments.issued")} · {instrument.bank_name}
                      </span>
                    </TableCell>
                    <TableCell>{partnerName(instrument.partner_id)}</TableCell>
                    <TableCell className={overdue ? "font-medium text-destructive" : undefined}>{instrument.due_date}</TableCell>
                    <TableCell className="text-right tabular-nums">{money(instrument.amount, instrument.currency)}</TableCell>
                    <TableCell>
                      {t(`treasury.instruments.status.${instrument.status}` as Key)}
                      {instrument.rejection_fee && (
                        <span className="block text-xs text-muted-foreground">
                          {t("treasury.instruments.rejectionFee")} : {money(instrument.rejection_fee, instrument.currency)}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {canCollect && instrument.method === "cheque" && (instrument.status === "collected" || instrument.status === "pending") && (
                        <Button size="sm" variant="outline" onClick={() => openUnpaid(instrument)} disabled={unpaidMutation.isPending}>
                          <Undo2 className="h-3.5 w-3.5" />
                          {t("treasury.instruments.markUnpaid")}
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={unpaidTarget !== null} onOpenChange={(open) => !open && setUnpaidTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("treasury.instruments.markUnpaid")} {unpaidTarget?.number}</DialogTitle>
            <DialogDescription>{t("treasury.instruments.unpaidDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="rejection_fee">{t("treasury.instruments.rejectionFeeOptional")}</Label>
                <Input id="rejection_fee" type="number" min="1" step="1" value={feeAmount} onChange={(e) => setFeeAmount(e.target.value)} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="rejection_fee_account">{t("treasury.instruments.rejectionFeeAccount")}</Label>
                <Select id="rejection_fee_account" value={feeAccountId} disabled={!feeEntered} onChange={(e) => setFeeAccountId(e.target.value)}>
                  <option value="">—</option>
                  {feeAccounts.map((a) => (
                    <option key={a.id} value={a.id}>{a.name}</option>
                  ))}
                </Select>
              </div>
            </div>
            {feeEntered && !feeValid && <p className="text-sm text-destructive">{t("treasury.instruments.rejectionFeeInvalid")}</p>}
            <Button className="w-full" disabled={!feeValid || unpaidMutation.isPending} onClick={() => unpaidTarget && unpaidMutation.mutate(unpaidTarget.id)}>
              {t("treasury.instruments.markUnpaid")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={slipOpen} onOpenChange={setSlipOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("treasury.instruments.slip")}</DialogTitle>
            <DialogDescription>{t("treasury.instruments.slipDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="slip_account">{t("treasury.instruments.slipAccount")}</Label>
                <Select id="slip_account" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
                  <option value="">—</option>
                  {eligibleAccounts.map((a) => (
                    <option key={a.id} value={a.id}>{a.name}</option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="slip_date">{t("treasury.column.date")}</Label>
                <Input id="slip_date" type="date" value={slipDate} onChange={(e) => setSlipDate(e.target.value)} />
              </div>
            </div>
            <ul className="space-y-1 text-sm">
              {chosen.map((i) => (
                <li key={i.id} className="flex justify-between">
                  <span>{i.number}</span>
                  <span className="tabular-nums">{money(i.amount, i.currency)}</span>
                </li>
              ))}
            </ul>
            <div className="flex gap-2">
              <Button className="flex-1" disabled={!accountId || slipMutation.isPending} onClick={() => slipMutation.mutate("collected")}>
                {t("treasury.instruments.collect")}
              </Button>
              <Button className="flex-1" variant="outline" disabled={!accountId || slipMutation.isPending || chosen.some((i) => i.method !== "cheque")} onClick={() => slipMutation.mutate("unpaid")}>
                {t("treasury.instruments.rejectAll")}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
