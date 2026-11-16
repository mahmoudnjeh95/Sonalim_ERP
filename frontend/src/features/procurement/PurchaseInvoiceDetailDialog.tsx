import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Ban, CheckCheck, Download, Eye, Paperclip, Pencil, Printer, ReceiptText, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { fileToBase64 } from "../treasury/statementsApi";
import { LedgerStatusBadge, useLedgerStatuses } from "../finance/ledgerStatus";
import { openDocument } from "../warehouse/printDocument";
import { formatXof, plain } from "./invoiceFormat";
import {
  addInvoiceAttachment,
  cancelCreditNote,
  cancelPurchaseInvoice,
  createCreditNote,
  deleteInvoiceAttachment,
  downloadInvoiceAttachment,
  getInvoiceActivity,
  getPurchaseInvoice,
  listInvoiceAttachments,
  validateCreditNote,
  validatePurchaseInvoice,
  type PurchaseInvoiceDetail,
} from "./invoicesApi";

type Key = Parameters<ReturnType<typeof useI18n>["t"]>[0];
export const PURCHASE_INVOICES_KEY = ["procurement", "purchase-invoices"] as const;

/** One purchase invoice: its lines and totals, the three-way-match warnings, credit notes, payments seen
 *  by treasury, attachments, and the actions its status allows. */
export function PurchaseInvoiceDetailDialog({
  invoiceId,
  onOpenChange,
  partnerName,
  onEdit,
}: {
  invoiceId: string | null;
  onOpenChange: (open: boolean) => void;
  partnerName: (id: string) => string;
  onEdit: (invoice: PurchaseInvoiceDetail) => void;
}) {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canManage = hasPermission("procurement.manage_purchase_invoices");
  const canSeeTreasury = hasPermission("treasury.view");
  const detailKey = [...PURCHASE_INVOICES_KEY, invoiceId] as const;

  const { data: invoice } = useQuery({ queryKey: detailKey, queryFn: () => getPurchaseInvoice(token, invoiceId!), enabled: !!invoiceId });
  const ledgerStatuses = useLedgerStatuses("procurement", invoiceId ? [invoiceId] : []);
  const { data: attachments = [] } = useQuery({
    queryKey: [...detailKey, "attachments"],
    queryFn: () => listInvoiceAttachments(token, invoiceId!),
    enabled: !!invoiceId,
  });
  const { data: activity } = useQuery({
    queryKey: ["treasury", "invoice-activity", invoiceId],
    queryFn: () => getInvoiceActivity(token, invoiceId!),
    enabled: !!invoiceId && canSeeTreasury && !!invoice && invoice.status !== "draft",
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: PURCHASE_INVOICES_KEY });
    queryClient.invalidateQueries({ queryKey: ["procurement", "invoiceable-receipts"] });
  };
  const fail = (key: Key) => (error: unknown) => toast.error(t(key), { description: error instanceof ApiError ? error.message : undefined });

  const validateMutation = useMutation({
    mutationFn: () => validatePurchaseInvoice(token, invoiceId!),
    onSuccess: () => { refresh(); toast.success(t("purchaseInvoice.validatedToast")); },
    onError: fail("purchaseInvoice.validateError"),
  });
  const cancelMutation = useMutation({
    mutationFn: () => cancelPurchaseInvoice(token, invoiceId!),
    onSuccess: () => { refresh(); toast.success(t("purchaseInvoice.cancelledToast")); },
    onError: fail("purchaseInvoice.cancelError"),
  });
  const uploadMutation = useMutation({
    mutationFn: async (file: File) =>
      addInvoiceAttachment(token, invoiceId!, { filename: file.name, content_type: file.type || undefined, content_base64: await fileToBase64(file) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [...detailKey, "attachments"] }),
    onError: fail("purchaseInvoice.attachment.error"),
  });
  const deleteMutation = useMutation({
    mutationFn: (attachmentId: string) => deleteInvoiceAttachment(token, invoiceId!, attachmentId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [...detailKey, "attachments"] }),
    onError: fail("purchaseInvoice.attachment.error"),
  });

  async function openAttachment(attachmentId: string, filename: string) {
    try {
      const blob = await downloadInvoiceAttachment(token, invoiceId!, attachmentId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      fail("purchaseInvoice.attachment.error")(error);
    }
  }

  function print(withDialog: boolean) {
    if (!invoice) return;
    const opened = openDocument(
      {
        title: `${t("purchaseInvoice.print.title")} ${invoice.number ?? t("status.draft")}`,
        fields: [
          [t("purchaseInvoice.field.supplier"), partnerName(invoice.partner_id)],
          [t("purchaseInvoice.field.supplierRef"), invoice.supplier_invoice_number],
          [t("purchaseInvoice.field.invoiceDate"), invoice.invoice_date],
          [t("purchaseInvoice.field.dueDate"), invoice.due_date ?? "—"],
        ],
        headers: [t("purchaseInvoice.line.description"), t("purchaseInvoice.line.quantity"), t("purchaseInvoice.line.unitPrice"),
          t("purchaseInvoice.line.discount"), t("purchaseInvoice.line.vat"), t("purchaseInvoice.line.totalExcl")],
        rows: invoice.lines.map((l) => [l.description, plain(l.quantity), formatXof(l.unit_price), `${plain(l.discount_rate)} %`,
          `${plain(l.vat_rate)} %`, formatXof(l.total_excl_tax)]),
        footer: [
          `${t("purchaseInvoice.total.excl")} : ${formatXof(invoice.total_excl_tax)}`,
          `${t("purchaseInvoice.total.vat")} : ${formatXof(invoice.total_vat)}`,
          `${t("purchaseInvoice.total.incl")} : ${formatXof(invoice.total_incl_tax)}`,
          Number(invoice.credited_amount) ? `${t("purchaseInvoice.total.credited")} : − ${formatXof(invoice.credited_amount)}` : "",
          `${t("purchaseInvoice.total.due")} : ${formatXof(invoice.amount)}`,
          invoice.note ?? "",
        ].filter(Boolean).join("\n"),
      },
      { print: withDialog },
    );
    if (!opened) toast.error(t("purchaseInvoice.print.blocked"));
  }

  const open = !!invoiceId;
  const lineName = (id: string) => invoice?.lines.find((l) => l.id === id)?.description ?? "—";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-5xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            {t("purchaseInvoice.detail.title")} {invoice?.number ?? ""}
            {invoice && <StatusBadge status={invoice.status} />}
            {invoice && <LedgerStatusBadge status={ledgerStatuses[invoice.id]} />}
          </DialogTitle>
          <DialogDescription>
            {invoice ? `${partnerName(invoice.partner_id)} · ${invoice.supplier_invoice_number}` : t("purchaseInvoice.detail.loading")}
          </DialogDescription>
        </DialogHeader>
        {invoice && (
          <div className="space-y-5">
            <div className="flex flex-wrap gap-2">
              {canManage && invoice.status === "draft" && (
                <>
                  <Button size="sm" variant="outline" onClick={() => onEdit(invoice)}>
                    <Pencil className="h-3.5 w-3.5" />
                    {t("purchaseInvoice.edit")}
                  </Button>
                  <Button size="sm" onClick={() => validateMutation.mutate()} disabled={validateMutation.isPending}>
                    <CheckCheck className="h-3.5 w-3.5" />
                    {t("purchaseInvoice.validate")}
                  </Button>
                </>
              )}
              {canManage && (invoice.status === "draft" || invoice.status === "validated") &&
                Number(invoice.amount_paid) === 0 && invoice.credit_notes.every((n) => n.status === "cancelled") && (
                <Button size="sm" variant="outline" onClick={() => { if (window.confirm(t("purchaseInvoice.cancelConfirm"))) cancelMutation.mutate(); }}
                  disabled={cancelMutation.isPending}>
                  <Ban className="h-3.5 w-3.5" />
                  {t("purchaseInvoice.cancel")}
                </Button>
              )}
              <Button size="sm" variant="outline" onClick={() => print(false)}>
                <Eye className="h-3.5 w-3.5" />
                {t("purchaseInvoice.print.preview")}
              </Button>
              <Button size="sm" variant="outline" onClick={() => print(true)}>
                <Printer className="h-3.5 w-3.5" />
                {t("purchaseInvoice.print.print")}
              </Button>
            </div>

            {invoice.warnings.length > 0 && (
              <ul className="space-y-1 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100">
                {invoice.warnings.map((w, index) => (
                  <li key={index} className="flex gap-2">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>
                      {lineName(w.line)} :{" "}
                      {w.code === "QUANTITY_OVER_RECEIVED"
                        ? `${t("purchaseInvoice.warning.overReceived")} (${plain(w.invoiced ?? 0)} / ${plain(w.receivable ?? 0)})`
                        : `${t("purchaseInvoice.warning.price")} (${formatXof(w.unit_price)} / ${formatXof(w.order_unit_price)})`}
                    </span>
                  </li>
                ))}
              </ul>
            )}

            <div className="grid gap-4 md:grid-cols-[1fr_auto]">
              <dl className="grid grid-cols-[auto_1fr] content-start gap-x-6 gap-y-1 text-sm">
                <dt className="text-muted-foreground">{t("purchaseInvoice.field.invoiceDate")}</dt>
                <dd>{invoice.invoice_date}</dd>
                <dt className="text-muted-foreground">{t("purchaseInvoice.field.dueDate")}</dt>
                <dd>{invoice.due_date ?? "—"}</dd>
                <dt className="text-muted-foreground">{t("purchaseInvoice.detail.receipts")}</dt>
                <dd>{invoice.receipt_ids.length ? invoice.receipt_ids.length : "—"}</dd>
                {invoice.note && (
                  <>
                    <dt className="text-muted-foreground">{t("purchaseInvoice.field.note")}</dt>
                    <dd>{invoice.note}</dd>
                  </>
                )}
              </dl>
              <dl className="grid min-w-[16rem] grid-cols-2 gap-x-4 gap-y-1 text-sm">
                <dt className="text-muted-foreground">{t("purchaseInvoice.total.excl")}</dt>
                <dd className="text-right tabular-nums">{formatXof(invoice.total_excl_tax)}</dd>
                <dt className="text-muted-foreground">{t("purchaseInvoice.total.vat")}</dt>
                <dd className="text-right tabular-nums">{formatXof(invoice.total_vat)}</dd>
                <dt className="text-muted-foreground">{t("purchaseInvoice.total.incl")}</dt>
                <dd className="text-right tabular-nums">{formatXof(invoice.total_incl_tax)}</dd>
                {Number(invoice.credited_amount) > 0 && (
                  <>
                    <dt className="text-muted-foreground">{t("purchaseInvoice.total.credited")}</dt>
                    <dd className="text-right tabular-nums">− {formatXof(invoice.credited_amount)}</dd>
                  </>
                )}
                <dt className="font-medium">{t("purchaseInvoice.total.due")}</dt>
                <dd className="text-right font-semibold tabular-nums">{formatXof(invoice.amount)}</dd>
                <dt className="text-muted-foreground">{t("purchaseInvoice.total.paid")}</dt>
                <dd className="text-right tabular-nums">{formatXof(invoice.amount_paid)}</dd>
                <dt className="text-muted-foreground">{t("purchaseInvoice.column.remaining")}</dt>
                <dd className="text-right tabular-nums">{formatXof(invoice.remaining)}</dd>
                {Number(invoice.supplier_credit) > 0 && (
                  <>
                    <dt className="text-muted-foreground">{t("purchaseInvoice.total.supplierCredit")}</dt>
                    <dd className="text-right font-medium tabular-nums text-amber-700 dark:text-amber-300">{formatXof(invoice.supplier_credit)}</dd>
                  </>
                )}
              </dl>
            </div>

            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("purchaseInvoice.line.description")}</TableHead>
                    <TableHead className="text-right">{t("purchaseInvoice.line.quantity")}</TableHead>
                    <TableHead className="text-right">{t("purchaseInvoice.line.unitPrice")}</TableHead>
                    <TableHead className="text-right">{t("purchaseInvoice.line.discount")}</TableHead>
                    <TableHead className="text-right">{t("purchaseInvoice.line.vat")}</TableHead>
                    <TableHead className="text-right">{t("purchaseInvoice.line.totalExcl")}</TableHead>
                    <TableHead className="text-right">{t("purchaseInvoice.line.totalIncl")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {invoice.lines.map((line) => (
                    <TableRow key={line.id}>
                      <TableCell>{line.description}</TableCell>
                      <TableCell className="text-right tabular-nums">{plain(line.quantity)}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatXof(line.unit_price)}</TableCell>
                      <TableCell className="text-right tabular-nums">{plain(line.discount_rate)} %</TableCell>
                      <TableCell className="text-right tabular-nums">{plain(line.vat_rate)} %</TableCell>
                      <TableCell className="text-right tabular-nums">{formatXof(line.total_excl_tax)}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatXof(line.total_incl_tax)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            <CreditNotesSection invoice={invoice} canManage={canManage} onChanged={refresh} />

            {canSeeTreasury && activity && (activity.documents.length > 0 || activity.payment_orders.length > 0) && (
              <section className="space-y-2">
                <h3 className="text-sm font-semibold">{t("purchaseInvoice.detail.payments")}</h3>
                <ul className="space-y-1 text-sm">
                  {activity.documents.map((d) => (
                    <li key={d.document_id} className="flex justify-between gap-2">
                      <span>{d.number} · {d.doc_date} · <StatusBadge status={d.status} /></span>
                      <span className="tabular-nums">{formatXof(Number(d.amount) - Number(d.reversed))}</span>
                    </li>
                  ))}
                  {activity.payment_orders.map((o) => (
                    <li key={o.id} className="flex justify-between gap-2 text-muted-foreground">
                      <span>{o.number} · {t("purchaseInvoice.detail.paymentOrder")}</span>
                      <span>{o.due_date}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <section className="space-y-2">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold">{t("purchaseInvoice.attachment.title")}</h3>
                {canManage && (
                  <label className="inline-flex cursor-pointer items-center gap-1 text-sm text-primary">
                    <Paperclip className="h-3.5 w-3.5" />
                    {t("purchaseInvoice.attachment.add")}
                    <input type="file" className="sr-only" onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) uploadMutation.mutate(file);
                      e.target.value = "";
                    }} />
                  </label>
                )}
              </div>
              {attachments.length === 0 ? (
                <p className="text-sm text-muted-foreground">{t("purchaseInvoice.attachment.none")}</p>
              ) : (
                <ul className="space-y-1 text-sm">
                  {attachments.map((file) => (
                    <li key={file.id} className="flex items-center justify-between gap-2">
                      <span className="truncate">{file.filename}</span>
                      <span className="flex shrink-0 gap-1">
                        <Button size="sm" variant="ghost" aria-label={t("purchaseInvoice.attachment.open")} onClick={() => openAttachment(file.id, file.filename)}>
                          <Download className="h-3.5 w-3.5" />
                        </Button>
                        {canManage && (
                          <Button size="sm" variant="ghost" aria-label={t("purchaseInvoice.attachment.delete")} disabled={deleteMutation.isPending}
                            onClick={() => {
                              if (window.confirm(t("attachment.deleteConfirm").replace("{name}", file.filename))) deleteMutation.mutate(file.id);
                            }}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Credit notes of one invoice, and a form for a new one: per invoice line, the quantity to credit and,
 *  for a price correction, a lower unit price. */
function CreditNotesSection({ invoice, canManage, onChanged }: { invoice: PurchaseInvoiceDetail; canManage: boolean; onChanged: () => void }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [formOpen, setFormOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [noteDate, setNoteDate] = useState("");
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [prices, setPrices] = useState<Record<string, string>>({});
  const creditable = ["validated", "partially_paid", "paid"].includes(invoice.status);
  const noteStatuses = useLedgerStatuses("procurement", invoice.credit_notes.map((note) => note.id));

  useEffect(() => {
    setFormOpen(false);
    setReason("");
    setNoteDate(new Date().toISOString().slice(0, 10));
    setQuantities({});
    setPrices({});
  }, [invoice.id]);

  const fail = (key: Key) => (error: unknown) => toast.error(t(key), { description: error instanceof ApiError ? error.message : undefined });
  const createMutation = useMutation({
    mutationFn: () =>
      createCreditNote(token, {
        invoice_id: invoice.id,
        note_date: noteDate,
        reason,
        lines: invoice.lines
          .filter((l) => Number(quantities[l.id]) > 0)
          .map((l) => ({ invoice_line_id: l.id, quantity: Number(quantities[l.id]), unit_price: prices[l.id] ? Number(prices[l.id]) : null })),
      }),
    onSuccess: () => {
      setFormOpen(false);
      setQuantities({});
      setPrices({});
      setReason("");
      onChanged();
      toast.success(t("purchaseInvoice.creditNote.created"));
    },
    onError: fail("purchaseInvoice.creditNote.error"),
  });
  const validateMutation = useMutation({
    mutationFn: (id: string) => validateCreditNote(token, id),
    onSuccess: () => { onChanged(); toast.success(t("purchaseInvoice.creditNote.validated")); },
    onError: fail("purchaseInvoice.creditNote.error"),
  });
  const cancelMutation = useMutation({
    mutationFn: (id: string) => cancelCreditNote(token, id),
    onSuccess: onChanged,
    onError: fail("purchaseInvoice.creditNote.error"),
  });

  if (!creditable && invoice.credit_notes.length === 0) return null;
  const anyQuantity = invoice.lines.some((l) => Number(quantities[l.id]) > 0);

  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">{t("purchaseInvoice.creditNote.title")}</h3>
        {canManage && creditable && !formOpen && (
          <Button size="sm" variant="outline" onClick={() => setFormOpen(true)}>
            <ReceiptText className="h-3.5 w-3.5" />
            {t("purchaseInvoice.creditNote.new")}
          </Button>
        )}
      </div>
      {invoice.credit_notes.length > 0 && (
        <ul className="space-y-1 text-sm">
          {invoice.credit_notes.map((note) => (
            <li key={note.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2">
              <span>
                <span className="font-medium">{note.number ?? t("status.draft")}</span> · {note.note_date} · {note.reason}{" "}
                <StatusBadge status={note.status} /> <LedgerStatusBadge status={noteStatuses[note.id]} />
              </span>
              <span className="flex items-center gap-2">
                <span className="tabular-nums">− {formatXof(note.total_incl_tax)}</span>
                {canManage && note.status === "draft" && (
                  <>
                    <Button size="sm" variant="outline" disabled={validateMutation.isPending} onClick={() => validateMutation.mutate(note.id)}>
                      {t("purchaseInvoice.validate")}
                    </Button>
                    <Button size="sm" variant="ghost" disabled={cancelMutation.isPending} onClick={() => cancelMutation.mutate(note.id)}>
                      {t("purchaseInvoice.cancel")}
                    </Button>
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      {formOpen && (
        <div className="space-y-3 rounded-md border p-3">
          <div className="grid gap-3 sm:grid-cols-[1fr_12rem]">
            <div className="space-y-1.5">
              <Label htmlFor="cn_reason">{t("purchaseInvoice.creditNote.reason")}</Label>
              <Input id="cn_reason" value={reason} onChange={(e) => setReason(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cn_date">{t("purchaseInvoice.creditNote.date")}</Label>
              <Input id="cn_date" type="date" value={noteDate} onChange={(e) => setNoteDate(e.target.value)} />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">{t("purchaseInvoice.creditNote.hint")}</p>
          <div className="space-y-2">
            {invoice.lines.map((line) => (
              <div key={line.id} className="grid items-center gap-2 text-sm sm:grid-cols-[1fr_7rem_9rem]">
                <span>{line.description} <span className="text-muted-foreground">({plain(line.quantity)} × {formatXof(line.unit_price)})</span></span>
                <Input aria-label={t("purchaseInvoice.creditNote.quantity")} placeholder={t("purchaseInvoice.creditNote.quantity")}
                  type="number" step="any" min="0" value={quantities[line.id] ?? ""}
                  onChange={(e) => setQuantities((q) => ({ ...q, [line.id]: e.target.value }))} />
                <Input aria-label={t("purchaseInvoice.creditNote.unitPrice")} placeholder={t("purchaseInvoice.creditNote.unitPrice")}
                  type="number" step="any" min="0" value={prices[line.id] ?? ""}
                  onChange={(e) => setPrices((p) => ({ ...p, [line.id]: e.target.value }))} />
              </div>
            ))}
          </div>
          <div className="flex gap-2">
            <Button size="sm" disabled={!reason.trim() || !anyQuantity || createMutation.isPending} onClick={() => createMutation.mutate()}>
              {t("purchaseInvoice.creditNote.save")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setFormOpen(false)}>{t("common.cancel")}</Button>
          </div>
        </div>
      )}
    </section>
  );
}
