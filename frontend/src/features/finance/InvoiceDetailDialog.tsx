import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { formatXofWithCode } from "../../lib/currency";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { listProducts } from "../warehouse/api";
import { getInvoice, type Invoice } from "./api";
import { LedgerStatusBadge, useLedgerStatuses } from "./ledgerStatus";

type T = ReturnType<typeof useI18n>["t"];

/** Where an invoice came from: the delivery it bills, or the order under the old rule. */
export function invoiceSourceLabel(t: T, invoice: Pick<Invoice, "source_type" | "source_number">): string {
  if (invoice.source_type === "delivery_note") return `${t("finance.source.deliveryNote")} ${invoice.source_number ?? ""}`.trim();
  if (invoice.source_type === "shipment") return `${t("finance.source.shipment")} ${invoice.source_number ?? ""}`.trim();
  if (invoice.source_type === "order") return t("finance.source.order");
  return t("finance.source.manual");
}

export function InvoiceDetailDialog({ invoiceId, onClose }: { invoiceId: string | null; onClose: () => void }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const { data: invoice } = useQuery({
    queryKey: ["finance", "invoice", invoiceId],
    queryFn: () => getInvoice(token, invoiceId!),
    enabled: invoiceId !== null,
  });
  const { data: products = [] } = useQuery({ queryKey: ["core", "products"], queryFn: () => listProducts(token), enabled: invoiceId !== null });
  const ledgerStatuses = useLedgerStatuses("finance", invoice ? [invoice.id, ...invoice.credit_notes.map((note) => note.id)] : []);
  const productName = (id: string) => products.find((p) => p.id === id)?.name ?? id;

  return (
    <Dialog open={invoiceId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{invoice?.number ?? t("finance.detail.title")}</DialogTitle>
          <DialogDescription>{invoice ? invoiceSourceLabel(t, invoice) : ""}</DialogDescription>
        </DialogHeader>
        {invoice && (
          <div className="space-y-4 text-sm">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
              <StatusBadge status={invoice.status} />
              <LedgerStatusBadge status={ledgerStatuses[invoice.id]} />
              <span>{t("finance.detail.date")} : {invoice.invoice_date}</span>
            </div>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-3">
              <dt className="text-muted-foreground">{t("finance.detail.total")}</dt>
              <dd className="tabular-nums sm:col-span-2">{formatXofWithCode(invoice.total ?? invoice.amount)}</dd>
              <dt className="text-muted-foreground">{t("finance.detail.credited")}</dt>
              <dd className="tabular-nums sm:col-span-2">{formatXofWithCode(invoice.amount_credited ?? 0)}</dd>
              <dt className="text-muted-foreground">{t("finance.detail.due")}</dt>
              <dd className="tabular-nums font-medium sm:col-span-2">{formatXofWithCode(invoice.amount)}</dd>
              <dt className="text-muted-foreground">{t("finance.column.amountPaid")}</dt>
              <dd className="tabular-nums sm:col-span-2">{formatXofWithCode(invoice.amount_paid)}</dd>
              {(invoice.customer_credit ?? 0) > 0 && (
                <>
                  <dt className="text-muted-foreground">{t("finance.detail.customerCredit")}</dt>
                  <dd className="tabular-nums font-medium text-amber-700 dark:text-amber-400 sm:col-span-2">
                    {formatXofWithCode(invoice.customer_credit ?? 0)}
                  </dd>
                </>
              )}
            </dl>

            <div>
              <h3 className="mb-1 font-medium">{t("finance.detail.lines")}</h3>
              {invoice.lines.length === 0 ? (
                <p className="text-muted-foreground">{t("finance.detail.noLines")}</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("finance.detail.product")}</TableHead>
                      <TableHead className="text-right">{t("finance.detail.quantity")}</TableHead>
                      <TableHead className="text-right">{t("finance.detail.unitPrice")}</TableHead>
                      <TableHead className="text-right">{t("finance.column.amount")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {invoice.lines.map((line, i) => (
                      <TableRow key={i}>
                        <TableCell>{productName(line.product_id)}</TableCell>
                        <TableCell className="text-right tabular-nums">{line.quantity}</TableCell>
                        <TableCell className="text-right tabular-nums">{formatXofWithCode(line.unit_price)}</TableCell>
                        <TableCell className="text-right tabular-nums">{formatXofWithCode(line.amount)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </div>

            <div>
              <h3 className="mb-1 font-medium">{t("finance.creditNotes.title")}</h3>
              {invoice.credit_notes.length === 0 ? (
                <p className="text-muted-foreground">{t("finance.creditNotes.none")}</p>
              ) : (
                <ul className="space-y-1">
                  {invoice.credit_notes.map((note) => (
                    <li key={note.id} className="flex flex-wrap justify-between gap-2">
                      <span>
                        <span className="font-medium">{note.number}</span> · {note.credit_date}
                        {note.return_number ? ` · ${t("finance.creditNotes.fromReturn")} ${note.return_number}` : ""}
                      </span>
                      <span className="flex items-center gap-2">
                        <LedgerStatusBadge status={ledgerStatuses[note.id]} />
                        <span className="tabular-nums">−{formatXofWithCode(note.amount)}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
