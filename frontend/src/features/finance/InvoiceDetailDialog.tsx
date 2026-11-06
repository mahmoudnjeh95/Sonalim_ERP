import { useQuery } from "@tanstack/react-query";
import { Eye, Printer } from "lucide-react";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { formatXofWithCode } from "../../lib/currency";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { Button } from "../../components/ui/button";
import { openDocument } from "../warehouse/printDocument";
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
  const hasVat = (invoice?.vat_amount ?? 0) > 0 || (invoice?.lines ?? []).some((line) => (line.vat_rate ?? 0) > 0);

  function print(printNow: boolean) {
    if (!invoice) return;
    const money = (value: number) => formatXofWithCode(value);
    openDocument(
      {
        title: `${t("finance.detail.invoice")} ${invoice.number ?? ""}`.trim(),
        fields: [
          [t("finance.detail.date"), invoice.invoice_date ?? ""],
          [t("finance.detail.source"), invoiceSourceLabel(t, invoice)],
        ],
        headers: [t("finance.detail.product"), t("finance.detail.quantity"), t("finance.detail.unitPrice"), t("finance.detail.discount"), t("finance.detail.vatRate"), t("finance.detail.amountExclTax")],
        rows: invoice.lines.map((line) => [
          productName(line.product_id),
          line.quantity,
          money(line.unit_price),
          line.discount_rate ? `${Number(line.discount_rate.toFixed(2))} %` : "—",
          `${line.vat_rate ?? 0} %`,
          money(line.amount),
        ]),
        footer: [
          `${t("finance.detail.amountExclTax")} : ${money(invoice.amount_excl_tax ?? invoice.total ?? invoice.amount)}`,
          `${t("finance.detail.vat")} : ${money(invoice.vat_amount ?? 0)}`,
          `${t("finance.detail.total")} : ${money(invoice.total ?? invoice.amount)}`,
        ].join("\n"),
      },
      { print: printNow },
    );
  }

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
              <span className="ml-auto flex gap-2">
                <Button size="sm" variant="outline" onClick={() => print(false)}>
                  <Eye className="h-3.5 w-3.5" />
                  {t("finance.detail.preview")}
                </Button>
                <Button size="sm" variant="outline" onClick={() => print(true)}>
                  <Printer className="h-3.5 w-3.5" />
                  {t("finance.detail.print")}
                </Button>
              </span>
            </div>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-3">
              {hasVat && (
                <>
                  <dt className="text-muted-foreground">{t("finance.detail.amountExclTax")}</dt>
                  <dd className="tabular-nums sm:col-span-2">{formatXofWithCode(invoice.amount_excl_tax ?? 0)}</dd>
                  <dt className="text-muted-foreground">{t("finance.detail.vat")}</dt>
                  <dd className="tabular-nums sm:col-span-2">{formatXofWithCode(invoice.vat_amount ?? 0)}</dd>
                </>
              )}
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
                      <TableHead className="text-right">{t("finance.detail.discount")}</TableHead>
                      <TableHead className="text-right">{t("finance.detail.vatRate")}</TableHead>
                      <TableHead className="text-right">{t("finance.detail.amountExclTax")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {invoice.lines.map((line, i) => (
                      <TableRow key={i}>
                        <TableCell>{productName(line.product_id)}</TableCell>
                        <TableCell className="text-right tabular-nums">{line.quantity}</TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatXofWithCode(line.unit_price)}
                          {line.list_price && line.discount_rate ? (
                            <span className="block text-xs text-muted-foreground line-through">{formatXofWithCode(line.list_price)}</span>
                          ) : null}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{line.discount_rate ? `${Number(line.discount_rate.toFixed(2))} %` : "—"}</TableCell>
                        <TableCell className="text-right tabular-nums">{line.vat_rate ?? 0} %</TableCell>
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
