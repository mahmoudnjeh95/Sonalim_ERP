import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { PackageCheck } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Checkbox } from "../../components/ui/checkbox";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { EmptyState } from "../../components/patterns/EmptyState";
import type { Partner } from "../partners/api";
import { formatXof, plain } from "./invoiceFormat";
import { createFromReceipts, listInvoiceableReceipts, type PurchaseInvoiceDetail } from "./invoicesApi";

export const INVOICEABLE_RECEIPTS_KEY = ["procurement", "invoiceable-receipts"] as const;

/** A draft invoice from one supplier's confirmed goods receipts, prefilled with what they brought in and
 *  no invoice billed yet, at the goods value each receipt recorded. */
export function FromReceiptsDialog({
  open,
  onOpenChange,
  suppliers,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  suppliers: Partner[];
  onCreated: (invoice: PurchaseInvoiceDetail) => void;
}) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const [supplierId, setSupplierId] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [reference, setReference] = useState("");
  const [invoiceDate, setInvoiceDate] = useState("");
  const [dueDate, setDueDate] = useState("");

  useEffect(() => {
    if (!open) return;
    setChosen([]);
    setReference("");
    setInvoiceDate(new Date().toISOString().slice(0, 10));
    setDueDate("");
  }, [open]);

  const { data: receipts = [] } = useQuery({
    queryKey: [...INVOICEABLE_RECEIPTS_KEY, supplierId],
    queryFn: () => listInvoiceableReceipts(token, supplierId || undefined),
    enabled: open,
  });
  const supplierName = (id: string) => suppliers.find((p) => p.id === id)?.name ?? "—";
  // One invoice, one supplier: once a receipt is ticked, only that supplier's receipts can join it.
  const lockedSupplier = receipts.find((r) => chosen.includes(r.receipt_id))?.supplier_id;

  const mutation = useMutation({
    mutationFn: () =>
      createFromReceipts(token, { receipt_ids: chosen, supplier_invoice_number: reference, invoice_date: invoiceDate, due_date: dueDate || null }),
    onSuccess: (invoice) => {
      toast.success(t("purchaseInvoice.created"));
      onCreated(invoice);
    },
    onError: (error: unknown) =>
      toast.error(t("purchaseInvoice.createError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("purchaseInvoice.fromReceipts.title")}</DialogTitle>
          <DialogDescription>{t("purchaseInvoice.fromReceipts.description")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="fr_supplier">{t("purchaseInvoice.field.supplier")}</Label>
            <Select id="fr_supplier" value={supplierId} onChange={(e) => { setSupplierId(e.target.value); setChosen([]); }}>
              <option value="">{t("common.all")}</option>
              {suppliers.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </Select>
          </div>
          {receipts.length === 0 ? (
            <EmptyState icon={<PackageCheck className="h-5 w-5" />} title={t("purchaseInvoice.fromReceipts.empty.title")}
              description={t("purchaseInvoice.fromReceipts.empty.description")} />
          ) : (
            <ul className="space-y-2">
              {receipts.map((receipt) => {
                const disabled = !!lockedSupplier && lockedSupplier !== receipt.supplier_id;
                const checked = chosen.includes(receipt.receipt_id);
                return (
                  <li key={receipt.receipt_id} className={`rounded-md border p-3 ${disabled ? "opacity-50" : ""}`}>
                    <label className="flex cursor-pointer items-start gap-3">
                      <Checkbox
                        checked={checked}
                        disabled={disabled}
                        onCheckedChange={(value) =>
                          setChosen((all) => (value ? [...all, receipt.receipt_id] : all.filter((id) => id !== receipt.receipt_id)))
                        }
                        aria-label={t("purchaseInvoice.fromReceipts.pick")}
                      />
                      <span className="flex-1 space-y-1">
                        <span className="block font-medium">
                          {supplierName(receipt.supplier_id)}
                          <span className="ml-2 text-xs font-normal text-muted-foreground">
                            {receipt.confirmed_at ? new Date(receipt.confirmed_at).toLocaleDateString() : ""}
                            {receipt.supplier_document ? ` · ${t("purchaseInvoice.fromReceipts.document")} ${receipt.supplier_document}` : ""}
                          </span>
                        </span>
                        {receipt.lines.map((line) => (
                          <span key={line.receipt_line_id} className="flex justify-between gap-2 text-xs text-muted-foreground">
                            <span>{line.product_name} · {plain(line.to_invoice)} / {plain(line.received)}</span>
                            <span className="tabular-nums">
                              {line.order_unit_price !== null ? formatXof(line.order_unit_price) : t("purchaseInvoice.fromReceipts.noPrice")}
                            </span>
                          </span>
                        ))}
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1.5">
              <Label htmlFor="fr_ref">{t("purchaseInvoice.field.supplierRef")}</Label>
              <Input id="fr_ref" value={reference} onChange={(e) => setReference(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="fr_date">{t("purchaseInvoice.field.invoiceDate")}</Label>
              <Input id="fr_date" type="date" value={invoiceDate} onChange={(e) => setInvoiceDate(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="fr_due">{t("purchaseInvoice.field.dueDate")}</Label>
              <Input id="fr_due" type="date" value={dueDate} min={invoiceDate} onChange={(e) => setDueDate(e.target.value)} />
            </div>
          </div>
          <Button className="w-full" disabled={chosen.length === 0 || !reference.trim() || !invoiceDate || mutation.isPending}
            onClick={() => mutation.mutate()}>
            {mutation.isPending ? t("purchaseInvoice.saving") : t("purchaseInvoice.fromReceipts.create")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
