import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Landmark, Undo2 } from "lucide-react";
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
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { listPartners } from "../partners/api";
import { listAccounts } from "./api";
import { listInstruments, markUnpaid, postDepositSlip, type Instrument } from "./instrumentsApi";

type Key = Parameters<ReturnType<typeof useI18n>["t"]>[0];
type Direction = Instrument["direction"];

function money(value: string, currency: string) {
  try {
    return new Intl.NumberFormat(currentLocale(), { style: "currency", currency, maximumFractionDigits: 0 }).format(Number(value));
  } catch {
    return `${value} ${currency}`;
  }
}

const today = () => new Date().toISOString().slice(0, 10);
const COLUMNS: Instrument["status"][] = ["pending", "collected", "unpaid"];
// The account a payment may be collected into depends on how it was paid.
const ACCOUNT_KINDS: Record<Instrument["method"], string[]> = {
  cash: ["cash"],
  transfer: ["bank"],
  mobile_money: ["mobile_money"],
  cheque: ["bank", "cash"],
  draft: ["bank", "cash"],
};

/** The manual's deposit slip: payments in three columns, moved from pending to collected, and a cheque to unpaid. */
export function InstrumentsTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canCollect = hasPermission("treasury.collect_instruments");
  const [direction, setDirection] = useState<Direction>("in");
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [slipOpen, setSlipOpen] = useState(false);
  const [accountId, setAccountId] = useState("");
  const [slipDate, setSlipDate] = useState(today());
  const [unpaidTarget, setUnpaidTarget] = useState<Instrument | null>(null);
  const [feeAmount, setFeeAmount] = useState("");
  const [feeAccountId, setFeeAccountId] = useState("");

  const { data: instruments = [] } = useQuery({ queryKey: ["treasury", "instruments"], queryFn: () => listInstruments(token) });
  const { data: partners = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token) });
  const { data: accounts = [] } = useQuery({ queryKey: ["treasury", "accounts"], queryFn: () => listAccounts(token) });
  const partnerName = (id: string) => partners.find((p) => p.id === id)?.name ?? "—";

  const visible = instruments.filter((i) => i.direction === direction);
  const chosen = visible.filter((i) => selected[i.id] && i.status === "pending");
  const needsAccount = chosen.some((i) => !i.account_id);
  const eligibleAccounts = accounts.filter((a) => a.is_active && chosen.every((i) => ACCOUNT_KINDS[i.method].includes(a.kind)));
  const feeAccounts = accounts.filter((a) => (a.kind === "bank" || a.kind === "cash") && a.is_active);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["treasury", "instruments"] });
    queryClient.invalidateQueries({ queryKey: ["treasury", "accounts"] });
    queryClient.invalidateQueries({ queryKey: ["treasury", "alerts"] });
    queryClient.invalidateQueries({ queryKey: ["treasury", "cash-journal"] });
  };
  const fail = (key: Key) => (error: unknown) =>
    toast.error(t(key), { description: error instanceof ApiError ? error.message : undefined });

  const slipMutation = useMutation({
    mutationFn: () =>
      postDepositSlip(token, {
        account_id: accountId || undefined,
        slip_date: slipDate,
        items: chosen.map((i) => ({ instrument_id: i.id, outcome: "collected" as const })),
      }),
    onSuccess: () => {
      refresh();
      setSlipOpen(false);
      setSelected({});
      setAccountId("");
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
              value={direction}
              onChange={(value) => {
                setDirection(value);
                setSelected({});
              }}
              options={[
                { value: "in", label: t("treasury.tabs.receipts") },
                { value: "out", label: t("treasury.tabs.disbursements") },
              ]}
            />
          </div>
          {canCollect && (
            <Button disabled={chosen.length === 0} onClick={() => setSlipOpen(true)}>
              <ArrowRight className="h-4 w-4" />
              {t("treasury.instruments.collect")} ({chosen.length})
            </Button>
          )}
        </CardHeader>
        <CardContent>
          <p className="mb-3 text-sm text-muted-foreground">{t("treasury.instruments.boardHelp")}</p>
          <div className="grid gap-4 lg:grid-cols-3">
            {COLUMNS.map((column) => {
              const items = visible.filter((i) => i.status === column);
              return (
                <section key={column} className="rounded-md border border-border" aria-label={t(`treasury.instruments.status.${column}` as Key)}>
                  <h3 className="border-b border-border px-3 py-2 text-center text-sm font-semibold">
                    {t(`treasury.instruments.status.${column}` as Key)} ({items.length})
                  </h3>
                  <ul className="max-h-[32rem] divide-y divide-border overflow-y-auto">
                    {items.length === 0 && <li className="px-3 py-6 text-center text-sm text-muted-foreground">{t("treasury.instruments.columnEmpty")}</li>}
                    {items.map((instrument) => {
                      const overdue = column === "pending" && instrument.due_date < today();
                      const canReject = canCollect && instrument.method === "cheque" && column !== "unpaid";
                      return (
                        <li key={instrument.id} className="flex items-start gap-2 px-3 py-2 text-sm">
                          {canCollect && column === "pending" && (
                            <Checkbox
                              aria-label={instrument.number}
                              checked={!!selected[instrument.id]}
                              onCheckedChange={(value) => setSelected((s) => ({ ...s, [instrument.id]: value === true }))}
                            />
                          )}
                          <div className="min-w-0 flex-1">
                            <p className="font-medium">
                              {instrument.document_number} : {t(`treasury.method.${instrument.method}` as Key)}
                              {instrument.number !== instrument.document_number && ` ${instrument.number}`}
                            </p>
                            <p className="text-muted-foreground">
                              {partnerName(instrument.partner_id)} | <span className="tabular-nums">{money(instrument.amount, instrument.currency)}</span>
                              {instrument.account_name && ` | ${instrument.account_name}`}
                            </p>
                            {(instrument.method === "cheque" || instrument.method === "draft") && (
                              <p className={overdue ? "font-medium text-destructive" : "text-muted-foreground"}>
                                {t("treasury.instruments.column.due")} : {instrument.due_date}
                                {instrument.bank_name && ` · ${instrument.bank_name}`}
                                {instrument.branch_name && ` · ${instrument.branch_name}`}
                              </p>
                            )}
                            {instrument.slip_reference && (
                              <p className="text-xs text-muted-foreground">
                                {t("treasury.instruments.slip")} {instrument.slip_reference}
                                {instrument.deposit_date && ` · ${instrument.deposit_date}`}
                              </p>
                            )}
                            {instrument.rejection_fee && (
                              <p className="text-xs text-muted-foreground">
                                {t("treasury.instruments.rejectionFee")} : {money(instrument.rejection_fee, instrument.currency)}
                              </p>
                            )}
                          </div>
                          {canReject && (
                            <Button size="sm" variant="ghost" title={t("treasury.instruments.markUnpaid")} aria-label={t("treasury.instruments.markUnpaid")} onClick={() => openUnpaid(instrument)}>
                              <Undo2 className="h-3.5 w-3.5" />
                            </Button>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </section>
              );
            })}
          </div>
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
                  <option value="">{needsAccount ? "—" : t("treasury.instruments.ownAccount")}</option>
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
                <li key={i.id} className="flex justify-between gap-2">
                  <span>{i.document_number} · {t(`treasury.method.${i.method}` as Key)} {i.account_name ? `· ${i.account_name}` : ""}</span>
                  <span className="tabular-nums">{money(i.amount, i.currency)}</span>
                </li>
              ))}
            </ul>
            <Button className="w-full" disabled={(needsAccount && !accountId) || slipMutation.isPending} onClick={() => slipMutation.mutate()}>
              <Landmark className="h-4 w-4" />
              {t("treasury.instruments.collect")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
