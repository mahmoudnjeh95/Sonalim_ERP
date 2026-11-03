import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, FileText, Plus, Trash2, Wallet } from "lucide-react";
import { createPaymentOrder } from "./paymentOrdersApi";
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
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import { listPartners } from "../partners/api";
import { listAccounts } from "./api";
import {
  cancelDocument,
  createDocument,
  listDocuments,
  listOpenInvoices,
  type Direction,
  type PaymentInput,
  type PaymentMethod,
} from "./paymentsApi";

type Key = Parameters<ReturnType<typeof useI18n>["t"]>[0];

const METHODS: PaymentMethod[] = ["cash", "transfer", "mobile_money", "cheque", "draft"];
const ACCOUNT_KIND: Partial<Record<PaymentMethod, string>> = { cash: "cash", transfer: "bank", mobile_money: "mobile_money" };

function money(value: string | number, currency: string) {
  try {
    return new Intl.NumberFormat(currentLocale(), { style: "currency", currency, maximumFractionDigits: 0 }).format(Number(value));
  } catch {
    return `${value} ${currency}`;
  }
}

const today = () => new Date().toISOString().slice(0, 10);
const blankPayment = (): PaymentInput => ({ method: "cash", amount: 0 });

export function PaymentsTab({ direction }: { direction: Direction }) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canManage = hasPermission(direction === "in" ? "treasury.manage_receipts" : "treasury.manage_disbursements");
  const key = ["treasury", "documents", direction] as const;
  const prefix = direction === "in" ? "treasury.receipts" : "treasury.disbursements";

  const [open, setOpen] = useState(false);
  const [partnerId, setPartnerId] = useState("");
  const [docDate, setDocDate] = useState(today());
  const [reason, setReason] = useState<"full" | "advance">("full");
  const [withDetails, setWithDetails] = useState(true);
  const [payments, setPayments] = useState<PaymentInput[]>([blankPayment()]);
  const [allocations, setAllocations] = useState<Record<string, number>>({});

  const { data: documents = [], isLoading } = useQuery({ queryKey: key, queryFn: () => listDocuments(token, direction) });
  const { data: partners = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token) });
  const { data: accounts = [] } = useQuery({ queryKey: ["treasury", "accounts"], queryFn: () => listAccounts(token) });
  const { data: invoices = [] } = useQuery({
    queryKey: ["treasury", "open-invoices", direction, partnerId],
    queryFn: () => listOpenInvoices(token, direction, partnerId),
    enabled: open && partnerId !== "",
  });
  const partnerName = (id: string) => partners.find((p) => p.id === id)?.name ?? "—";

  const total = payments.reduce((sum, p) => sum + (Number(p.amount) || 0), 0);
  const allocated = Object.values(allocations).reduce((sum, v) => sum + (Number(v) || 0), 0);

  function reset() {
    setPartnerId("");
    setDocDate(today());
    setReason("full");
    setWithDetails(true);
    setPayments([blankPayment()]);
    setAllocations({});
  }

  const fail = (messageKey: Key) => (error: unknown) =>
    toast.error(t(messageKey), { description: error instanceof ApiError ? error.message : undefined });

  const createMutation = useMutation({
    mutationFn: () =>
      createDocument(token, direction, {
        partner_id: partnerId,
        doc_date: docDate,
        currency: "XOF",
        reason,
        with_details: withDetails,
        payments: payments.map((p) => ({ ...p, amount: Number(p.amount), due_date: p.due_date || undefined })),
        allocations: Object.entries(allocations)
          .filter(([, amount]) => Number(amount) > 0)
          .map(([invoice_id, amount]) => ({ invoice_id, amount: Number(amount) })),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: key });
      queryClient.invalidateQueries({ queryKey: ["treasury", "accounts"] });
      setOpen(false);
      reset();
      toast.success(t("treasury.document.created"));
    },
    onError: fail("treasury.document.createError"),
  });
  const cancelMutation = useMutation({
    mutationFn: (id: string) => cancelDocument(token, direction, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: key });
      queryClient.invalidateQueries({ queryKey: ["treasury", "accounts"] });
      toast.success(t("treasury.document.cancelled"));
    },
    onError: fail("treasury.document.cancelError"),
  });

  const orderMutation = useMutation({
    mutationFn: (id: string) => createPaymentOrder(token, id),
    onSuccess: (order) => {
      queryClient.invalidateQueries({ queryKey: ["treasury", "payment-orders"] });
      toast.success(`${t("treasury.order.created")} ${order.number}`);
    },
    onError: fail("treasury.order.createError"),
  });

  const updatePayment = (index: number, patch: Partial<PaymentInput>) =>
    setPayments((list) => list.map((p, i) => (i === index ? { ...p, ...patch } : p)));

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t(`${prefix}.title` as Key)}</CardTitle>
          {canManage && (
            <Button onClick={() => setOpen(true)}>
              <Plus className="h-4 w-4" />
              {t(`${prefix}.new` as Key)}
            </Button>
          )}
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("treasury.column.number")}</TableHead>
                <TableHead>{t("treasury.column.date")}</TableHead>
                <TableHead>{t("treasury.column.partner")}</TableHead>
                <TableHead className="text-right">{t("treasury.column.amount")}</TableHead>
                <TableHead>{t("treasury.column.status")}</TableHead>
                <TableHead className="text-right">{t("treasury.column.action")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && <TableLoadingRow colSpan={6} />}
              {!isLoading && documents.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="p-0">
                    <EmptyState
                      icon={<Wallet className="h-5 w-5" />}
                      title={t(`${prefix}.empty.title` as Key)}
                      description={t(`${prefix}.empty.description` as Key)}
                    />
                  </TableCell>
                </TableRow>
              )}
              {documents.map((doc) => (
                <TableRow key={doc.id} className={doc.status === "cancelled" ? "opacity-50" : undefined}>
                  <TableCell className="font-mono text-xs">{doc.number}</TableCell>
                  <TableCell>{doc.doc_date}</TableCell>
                  <TableCell>{partnerName(doc.partner_id)}</TableCell>
                  <TableCell className="text-right tabular-nums">{money(doc.total, doc.currency)}</TableCell>
                  <TableCell>
                    <StatusBadge status={doc.status === "posted" ? "confirmed" : "cancelled"} />
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      {canManage && direction === "out" && doc.status === "posted" && (
                        <Button size="sm" variant="outline" onClick={() => orderMutation.mutate(doc.id)} disabled={orderMutation.isPending}>
                          <FileText className="h-3.5 w-3.5" />
                          {t("treasury.order.create")}
                        </Button>
                      )}
                      {canManage && doc.status === "posted" && (
                        <Button size="sm" variant="outline" onClick={() => cancelMutation.mutate(doc.id)} disabled={cancelMutation.isPending}>
                          <Ban className="h-3.5 w-3.5" />
                          {t("treasury.document.cancel")}
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

      <Dialog
        open={open}
        onOpenChange={(value) => {
          setOpen(value);
          if (!value) reset();
        }}
      >
        <DialogContent className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t(`${prefix}.new` as Key)}</DialogTitle>
            <DialogDescription>{t("treasury.document.dialogDescription")}</DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              createMutation.mutate();
            }}
          >
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="doc_partner">{t("treasury.column.partner")}</Label>
                <Select
                  id="doc_partner"
                  required
                  value={partnerId}
                  onChange={(e) => {
                    setPartnerId(e.target.value);
                    setAllocations({});
                  }}
                >
                  <option value="">—</option>
                  {partners
                    .filter((p) => p.status === "active")
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="doc_date">{t("treasury.column.date")}</Label>
                <Input id="doc_date" type="date" required value={docDate} onChange={(e) => setDocDate(e.target.value)} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="doc_reason">{t("treasury.document.reason")}</Label>
                <Select id="doc_reason" value={reason} onChange={(e) => setReason(e.target.value as "full" | "advance")}>
                  <option value="full">{t("treasury.document.reason.full")}</option>
                  <option value="advance">{t("treasury.document.reason.advance")}</option>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="doc_details">{t("treasury.document.details")}</Label>
                <Select id="doc_details" value={withDetails ? "yes" : "no"} onChange={(e) => setWithDetails(e.target.value === "yes")}>
                  <option value="yes">{t("treasury.document.withDetails")}</option>
                  <option value="no">{t("treasury.document.withoutDetails")}</option>
                </Select>
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>{t("treasury.document.payments")}</Label>
                <Button type="button" size="sm" variant="outline" onClick={() => setPayments((list) => [...list, blankPayment()])}>
                  <Plus className="h-3.5 w-3.5" />
                </Button>
              </div>
              {payments.map((payment, index) => {
                const kind = ACCOUNT_KIND[payment.method];
                const isInstrument = payment.method === "cheque" || payment.method === "draft";
                return (
                  <div key={index} className="space-y-2 rounded-md border border-border p-2">
                    <div className="grid grid-cols-[1fr_1fr_auto] gap-2">
                      <Select
                        value={payment.method}
                        onChange={(e) => updatePayment(index, { method: e.target.value as PaymentMethod, account_id: undefined })}
                      >
                        {METHODS.map((m) => (
                          <option key={m} value={m}>
                            {t(`treasury.method.${m}` as Key)}
                          </option>
                        ))}
                      </Select>
                      <Input
                        type="number"
                        step="any"
                        min="0"
                        placeholder={t("treasury.column.amount")}
                        value={payment.amount || ""}
                        onChange={(e) => updatePayment(index, { amount: Number(e.target.value) })}
                      />
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        disabled={payments.length === 1}
                        onClick={() => setPayments((list) => list.filter((_, i) => i !== index))}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                    {kind && (
                      <Select required value={payment.account_id ?? ""} onChange={(e) => updatePayment(index, { account_id: e.target.value })}>
                        <option value="">{t("treasury.document.chooseAccount")}</option>
                        {accounts
                          .filter((a) => a.kind === kind && a.is_active && a.currency === "XOF")
                          .map((a) => (
                            <option key={a.id} value={a.id}>
                              {a.name}
                            </option>
                          ))}
                      </Select>
                    )}
                    {isInstrument && (
                      <div className="grid grid-cols-3 gap-2">
                        <Input required placeholder={t("treasury.document.instrumentNumber")} value={payment.number ?? ""} onChange={(e) => updatePayment(index, { number: e.target.value })} />
                        <Input required placeholder={t("treasury.document.instrumentBank")} value={payment.bank_name ?? ""} onChange={(e) => updatePayment(index, { bank_name: e.target.value })} />
                        <Input required type="date" value={payment.due_date ?? ""} onChange={(e) => updatePayment(index, { due_date: e.target.value })} />
                      </div>
                    )}
                  </div>
                );
              })}
              <p className="text-right text-sm tabular-nums">
                {t("treasury.document.total")}: {money(total, "XOF")}
              </p>
            </div>

            {withDetails && partnerId !== "" && (
              <div className="space-y-2">
                <Label>{t("treasury.document.invoices")}</Label>
                {invoices.length === 0 ? (
                  <p className="text-sm text-muted-foreground">{t("treasury.document.noOpenInvoices")}</p>
                ) : (
                  invoices.map((invoice) => (
                    <div key={invoice.id} className="grid grid-cols-[1fr_auto_8rem] items-center gap-2 text-sm">
                      <span>{invoice.number ?? invoice.supplier_invoice_number ?? invoice.id.slice(-6)}</span>
                      <span className="tabular-nums text-muted-foreground">{money(invoice.remaining, invoice.currency)}</span>
                      <Input
                        type="number"
                        step="any"
                        min="0"
                        max={invoice.remaining}
                        placeholder="0"
                        value={allocations[invoice.id] ?? ""}
                        onChange={(e) => setAllocations((a) => ({ ...a, [invoice.id]: Number(e.target.value) }))}
                      />
                    </div>
                  ))
                )}
                <p className="text-right text-sm tabular-nums">
                  {t("treasury.document.allocated")}: {money(allocated, "XOF")}
                </p>
              </div>
            )}

            <Button type="submit" className="w-full" disabled={createMutation.isPending || total <= 0}>
              {createMutation.isPending ? t("treasury.document.posting") : t("treasury.document.post")}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
