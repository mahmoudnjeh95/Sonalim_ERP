import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import type { Partner } from "../partners/api";
import type { Product } from "../warehouse/api";
import { computeTotals, lineNet, lineVat } from "./invoiceMath";
import { formatXof } from "./invoiceFormat";
import {
  createPurchaseInvoice,
  updatePurchaseInvoice,
  type InvoiceLineInput,
  type PurchaseInvoiceDetail,
} from "./invoicesApi";

interface DraftLine {
  product_id: string;
  description: string;
  quantity: string;
  unit_price: string;
  discount_rate: string;
  vat_rate: string;
  uom_id: string | null;
  purchase_order_line_id: string | null;
  receipt_id: string | null;
}

function emptyLine(defaultVat: number): DraftLine {
  return { product_id: "", description: "", quantity: "1", unit_price: "0", discount_rate: "0", vat_rate: String(defaultVat),
    uom_id: null, purchase_order_line_id: null, receipt_id: null };
}

const asNumbers = (line: DraftLine) => ({
  quantity: Number(line.quantity) || 0,
  unit_price: Number(line.unit_price) || 0,
  discount_rate: Number(line.discount_rate) || 0,
  vat_rate: Number(line.vat_rate) || 0,
});

/** Create a purchase invoice or edit a draft one: the header and its priced lines, with live totals. */
export function PurchaseInvoiceFormDialog({
  open,
  onOpenChange,
  invoice,
  suppliers,
  products,
  defaultVat,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  invoice: PurchaseInvoiceDetail | null;
  suppliers: Partner[];
  products: Product[];
  defaultVat: number;
  onSaved: (invoice: PurchaseInvoiceDetail) => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [partnerId, setPartnerId] = useState("");
  const [reference, setReference] = useState("");
  const [invoiceDate, setInvoiceDate] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [note, setNote] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([]);

  useEffect(() => {
    if (!open) return;
    setPartnerId(invoice?.partner_id ?? "");
    setReference(invoice?.supplier_invoice_number ?? "");
    setInvoiceDate(invoice?.invoice_date ?? new Date().toISOString().slice(0, 10));
    setDueDate(invoice?.due_date ?? "");
    setNote(invoice?.note ?? "");
    setLines(
      invoice
        ? invoice.lines.map((l) => ({
            product_id: l.product_id ?? "",
            description: l.description,
            quantity: String(Number(l.quantity)),
            unit_price: String(Number(l.unit_price)),
            discount_rate: String(Number(l.discount_rate)),
            vat_rate: String(Number(l.vat_rate)),
            uom_id: l.uom_id,
            purchase_order_line_id: l.purchase_order_line_id,
            receipt_id: l.receipt_id,
          }))
        : [emptyLine(defaultVat)],
    );
  }, [open, invoice, defaultVat]);

  const totals = computeTotals(lines.map(asNumbers), defaultVat);
  const change = (index: number, patch: Partial<DraftLine>) => setLines((all) => all.map((l, i) => (i === index ? { ...l, ...patch } : l)));

  const mutation = useMutation({
    mutationFn: () => {
      const body = {
        partner_id: partnerId,
        supplier_invoice_number: reference,
        invoice_date: invoiceDate,
        due_date: dueDate || null,
        note: note || null,
        lines: lines.map<InvoiceLineInput>((l) => ({
          ...asNumbers(l),
          product_id: l.product_id || null,
          description: l.description,
          uom_id: l.uom_id,
          purchase_order_line_id: l.purchase_order_line_id,
          receipt_id: l.receipt_id,
        })),
      };
      return invoice ? updatePurchaseInvoice(token, invoice.id, body) : createPurchaseInvoice(token, body);
    },
    onSuccess: (saved) => {
      toast.success(t(invoice ? "purchaseInvoice.updated" : "purchaseInvoice.created"));
      onSaved(saved);
    },
    onError: (error: unknown) =>
      toast.error(t(invoice ? "purchaseInvoice.updateError" : "purchaseInvoice.createError"), {
        description: error instanceof ApiError ? error.message : undefined,
      }),
  });

  const ready = partnerId && reference.trim() && invoiceDate && lines.length > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-5xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t(invoice ? "purchaseInvoice.dialog.editTitle" : "purchaseInvoice.dialog.title")}</DialogTitle>
          <DialogDescription>{t("purchaseInvoice.dialog.description")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (ready) mutation.mutate();
          }}
        >
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="space-y-1.5">
              <Label htmlFor="pi_partner">{t("purchaseInvoice.field.supplier")}</Label>
              <Select id="pi_partner" value={partnerId} onChange={(e) => setPartnerId(e.target.value)}>
                <option value="">—</option>
                {suppliers.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pi_ref">{t("purchaseInvoice.field.supplierRef")}</Label>
              <Input id="pi_ref" value={reference} onChange={(e) => setReference(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pi_date">{t("purchaseInvoice.field.invoiceDate")}</Label>
              <Input id="pi_date" type="date" value={invoiceDate} onChange={(e) => setInvoiceDate(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pi_due">{t("purchaseInvoice.field.dueDate")}</Label>
              <Input id="pi_due" type="date" value={dueDate} min={invoiceDate} onChange={(e) => setDueDate(e.target.value)} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pi_note">{t("purchaseInvoice.field.note")}</Label>
            <Input id="pi_note" value={note} onChange={(e) => setNote(e.target.value)} />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>{t("purchaseInvoice.field.lines")}</Label>
              <Button type="button" size="sm" variant="outline" onClick={() => setLines((all) => [...all, emptyLine(defaultVat)])}>
                <Plus className="h-3.5 w-3.5" />
                {t("purchaseInvoice.line.add")}
              </Button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-sm">
                <thead className="text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="pb-1 pr-2 font-medium">{t("purchaseInvoice.line.product")}</th>
                    <th className="pb-1 pr-2 font-medium">{t("purchaseInvoice.line.description")}</th>
                    <th className="w-20 pb-1 pr-2 font-medium">{t("purchaseInvoice.line.quantity")}</th>
                    <th className="w-28 pb-1 pr-2 font-medium">{t("purchaseInvoice.line.unitPrice")}</th>
                    <th className="w-20 pb-1 pr-2 font-medium">{t("purchaseInvoice.line.discount")}</th>
                    <th className="w-20 pb-1 pr-2 font-medium">{t("purchaseInvoice.line.vat")}</th>
                    <th className="w-28 pb-1 pr-2 text-right font-medium">{t("purchaseInvoice.line.totalExcl")}</th>
                    <th className="w-10" />
                  </tr>
                </thead>
                <tbody>
                  {lines.map((line, index) => {
                    const amounts = asNumbers(line);
                    return (
                      <tr key={index} className="align-top">
                        <td className="py-1 pr-2">
                          <Select
                            aria-label={t("purchaseInvoice.line.product")}
                            value={line.product_id}
                            onChange={(e) => {
                              const product = products.find((p) => p.id === e.target.value);
                              change(index, {
                                product_id: e.target.value,
                                uom_id: product?.uom_id ?? null,
                                description: line.description || product?.name || "",
                              });
                            }}
                          >
                            <option value="">{t("purchaseInvoice.line.freeText")}</option>
                            {products.map((p) => (
                              <option key={p.id} value={p.id}>{p.sku} · {p.name}</option>
                            ))}
                          </Select>
                        </td>
                        <td className="py-1 pr-2">
                          <Input aria-label={t("purchaseInvoice.line.description")} value={line.description}
                            onChange={(e) => change(index, { description: e.target.value })} />
                        </td>
                        <td className="py-1 pr-2">
                          <Input aria-label={t("purchaseInvoice.line.quantity")} type="number" step="any" min="0" value={line.quantity}
                            onChange={(e) => change(index, { quantity: e.target.value })} />
                        </td>
                        <td className="py-1 pr-2">
                          <Input aria-label={t("purchaseInvoice.line.unitPrice")} type="number" step="any" min="0" value={line.unit_price}
                            onChange={(e) => change(index, { unit_price: e.target.value })} />
                        </td>
                        <td className="py-1 pr-2">
                          <Input aria-label={t("purchaseInvoice.line.discount")} type="number" step="any" min="0" max="100" value={line.discount_rate}
                            onChange={(e) => change(index, { discount_rate: e.target.value })} />
                        </td>
                        <td className="py-1 pr-2">
                          <Input aria-label={t("purchaseInvoice.line.vat")} type="number" step="any" min="0" max="100" value={line.vat_rate}
                            onChange={(e) => change(index, { vat_rate: e.target.value })} />
                        </td>
                        <td className="py-1 pr-2 text-right tabular-nums">
                          {formatXof(lineNet(amounts))}
                          <div className="text-xs text-muted-foreground">+ {formatXof(lineVat(amounts, defaultVat))}</div>
                        </td>
                        <td className="py-1">
                          <Button type="button" size="sm" variant="ghost" aria-label={t("purchaseInvoice.line.remove")}
                            disabled={lines.length === 1} onClick={() => setLines((all) => all.filter((_, i) => i !== index))}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <dl className="ml-auto grid w-full max-w-xs grid-cols-2 gap-x-4 gap-y-1 text-sm">
            <dt className="text-muted-foreground">{t("purchaseInvoice.total.gross")}</dt>
            <dd className="text-right tabular-nums">{formatXof(totals.gross)}</dd>
            <dt className="text-muted-foreground">{t("purchaseInvoice.total.discount")}</dt>
            <dd className="text-right tabular-nums">− {formatXof(totals.discount)}</dd>
            <dt className="text-muted-foreground">{t("purchaseInvoice.total.excl")}</dt>
            <dd className="text-right tabular-nums">{formatXof(totals.excl)}</dd>
            <dt className="text-muted-foreground">{t("purchaseInvoice.total.vat")}</dt>
            <dd className="text-right tabular-nums">{formatXof(totals.vat)}</dd>
            <dt className="font-medium">{t("purchaseInvoice.total.incl")}</dt>
            <dd className="text-right font-semibold tabular-nums">{formatXof(totals.incl)}</dd>
          </dl>

          <Button type="submit" className="w-full" disabled={!ready || mutation.isPending}>
            {mutation.isPending ? t("purchaseInvoice.saving") : t(invoice ? "purchaseInvoice.save" : "purchaseInvoice.create")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
