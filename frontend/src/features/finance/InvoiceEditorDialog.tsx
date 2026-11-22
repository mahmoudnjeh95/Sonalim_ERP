import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
import { listPartners } from "../partners/api";
import { listProducts } from "../warehouse/api";
import { formatAmount } from "./ledgerFormat";
import { useTaxCodes } from "../taxes/api";
import { createInvoiceWithLines, getInvoice, replaceInvoiceLines, type InvoiceLineInput } from "./api";

interface DraftLine {
  key: number;
  product_id: string;
  description: string;
  quantity: string;
  unit_price: string;
  discount_rate: string;
  tax_code: string;
}

let nextKey = 1;
const blankLine = (taxCode: string): DraftLine => ({
  key: nextKey++,
  product_id: "",
  description: "",
  quantity: "1",
  unit_price: "",
  discount_rate: "0",
  tax_code: taxCode,
});

/** Totals as the server computes them: excluding tax and VAT in whole francs, on the net lines. */
function totals(lines: DraftLine[], rateOf: (code: string) => number) {
  let excl = 0;
  let vat = 0;
  for (const line of lines) {
    const net = Number(line.quantity || 0) * Number(line.unit_price || 0) * (1 - Number(line.discount_rate || 0) / 100);
    excl += net;
    vat += (net * rateOf(line.tax_code)) / 100;
  }
  return { excl: Math.round(excl), vat: Math.round(vat), incl: Math.round(excl) + Math.round(vat) };
}

/** Create an invoice by hand, or (given `invoiceId`, a draft) re-type its lines. */
export function InvoiceEditorDialog({
  open,
  onOpenChange,
  invoiceId,
  invalidateKey,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  invoiceId: string | null;
  invalidateKey: readonly unknown[];
}) {
  const { session } = useAuth();
  const { t, language } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const { data: partners = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token), enabled: open });
  const { data: products = [] } = useQuery({ queryKey: ["warehouse", "products"], queryFn: () => listProducts(token), enabled: open });
  const { data: existing } = useQuery({
    queryKey: ["finance", "invoices", "detail", invoiceId],
    queryFn: () => getInvoice(token, invoiceId!),
    enabled: open && invoiceId !== null,
  });
  // The active codes usable on sales (core.tax_codes). A new line starts on the first taxable one (TVA18 by
  // default); the server still checks the code against the line, its customer and its product.
  const { codes: salesCodes } = useTaxCodes("sales");
  const defaultCode = salesCodes.find((code) => !code.exempt)?.code ?? salesCodes[0]?.code ?? "";
  const rateOf = (code: string) => salesCodes.find((c) => c.code === code)?.rate ?? 0;

  const [partnerId, setPartnerId] = useState("");
  const [invoiceDate, setInvoiceDate] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([]);

  // Load the draft being edited, or start a blank invoice with one line, each time the dialog opens.
  useEffect(() => {
    if (!open) return;
    if (invoiceId === null) {
      setPartnerId("");
      setInvoiceDate("");
      setLines([blankLine(defaultCode)]);
    } else if (existing) {
      setPartnerId(existing.partner_id);
      setInvoiceDate(existing.invoice_date ?? "");
      setLines(
        existing.lines.map((line) => {
          // Lines keep the code they were given; older lines without one are matched on their rate.
          const code = salesCodes.find((c) => c.code === line.tax_code) ??
            salesCodes.find((c) => c.rate === (line.vat_rate ?? 0) && (line.vat_rate !== 0 || c.exempt)) ??
            salesCodes.find((c) => c.rate === (line.vat_rate ?? 0));
          return {
            key: nextKey++,
            product_id: line.product_id ?? "",
            description: line.description ?? "",
            quantity: String(line.quantity),
            unit_price: String(line.list_price ?? line.unit_price),
            discount_rate: String(line.discount_rate ?? 0),
            tax_code: code?.code ?? defaultCode,
          };
        }),
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, invoiceId, existing?.id, defaultCode]);

  const update = (key: number, patch: Partial<DraftLine>) => setLines((rows) => rows.map((row) => (row.key === key ? { ...row, ...patch } : row)));
  const pickProduct = (key: number, productId: string) => {
    const product = products.find((p) => p.id === productId);
    const current = lines.find((l) => l.key === key);
    update(key, { product_id: productId, ...(product && !current?.description ? { description: product.name } : {}) });
  };

  const payload = (): InvoiceLineInput[] =>
    lines.map((line) => ({
      product_id: line.product_id || null,
      description: line.description || null,
      quantity: Number(line.quantity),
      unit_price: Number(line.unit_price),
      discount_rate: Number(line.discount_rate || 0),
      tax_code: line.tax_code,
    }));
  const complete =
    partnerId !== "" &&
    lines.length > 0 &&
    lines.every((line) => (line.product_id || line.description.trim()) && Number(line.quantity) > 0 && line.unit_price !== "" && Number(line.unit_price) >= 0);

  const save = useMutation({
    mutationFn: () =>
      invoiceId === null
        ? createInvoiceWithLines(token, { partner_id: partnerId, invoice_date: invoiceDate || null, lines: payload() })
        : replaceInvoiceLines(token, invoiceId, { invoice_date: invoiceDate || null, lines: payload() }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: invalidateKey });
      toast.success(t(invoiceId === null ? "finance.created" : "finance.updated"));
      onOpenChange(false);
    },
    onError: (error) => toast.error(t("finance.editor.saveError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  const sums = totals(lines, rateOf);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t(invoiceId === null ? "finance.dialog.title" : "finance.editor.editTitle")}</DialogTitle>
          <DialogDescription>{t("finance.editor.description")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="inv-partner">{t("finance.editor.customer")}</Label>
              <Select id="inv-partner" value={partnerId} disabled={invoiceId !== null} onChange={(e) => setPartnerId(e.target.value)}>
                <option value="">—</option>
                {partners
                  .filter((p) => p.status === "active" || p.id === partnerId)
                  .map((partner) => (
                    <option key={partner.id} value={partner.id}>
                      {partner.name}
                    </option>
                  ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="inv-date">{t("finance.editor.invoiceDate")}</Label>
              <Input id="inv-date" type="date" value={invoiceDate} onChange={(e) => setInvoiceDate(e.target.value)} />
            </div>
          </div>
          <div className="space-y-2">
            {lines.map((line) => (
              <div key={line.key} className="grid items-end gap-2 rounded-md border p-2 sm:grid-cols-[1.4fr_1.6fr_5rem_7rem_5rem_8rem_auto]">
                <div className="space-y-1">
                  <Label className="text-xs">{t("finance.editor.product")}</Label>
                  <Select value={line.product_id} onChange={(e) => pickProduct(line.key, e.target.value)}>
                    <option value="">{t("finance.editor.freeLine")}</option>
                    {products.map((product) => (
                      <option key={product.id} value={product.id}>
                        {product.name}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">{t("finance.editor.descriptionField")}</Label>
                  <Input value={line.description} onChange={(e) => update(line.key, { description: e.target.value })} />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">{t("finance.editor.quantity")}</Label>
                  <Input type="number" min="0" step="any" value={line.quantity} onChange={(e) => update(line.key, { quantity: e.target.value })} />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">{t("finance.editor.unitPrice")}</Label>
                  <Input type="number" min="0" step="any" value={line.unit_price} onChange={(e) => update(line.key, { unit_price: e.target.value })} />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">{t("finance.editor.discount")}</Label>
                  <Input type="number" min="0" max="100" step="any" value={line.discount_rate} onChange={(e) => update(line.key, { discount_rate: e.target.value })} />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">{t("finance.editor.tax")}</Label>
                  <Select value={line.tax_code} onChange={(e) => update(line.key, { tax_code: e.target.value })}>
                    {salesCodes.map((code) => (
                      <option key={code.id} value={code.code}>
                        {language === "fr" ? code.name_fr : code.name_en}
                      </option>
                    ))}
                  </Select>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-label={t("finance.editor.removeLine")}
                  disabled={lines.length === 1}
                  onClick={() => setLines((rows) => rows.filter((row) => row.key !== line.key))}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
            <Button type="button" variant="outline" size="sm" onClick={() => setLines((rows) => [...rows, blankLine(defaultCode)])}>
              <Plus className="h-4 w-4" />
              {t("finance.editor.addLine")}
            </Button>
          </div>
          <dl className="ml-auto grid w-full max-w-xs grid-cols-2 gap-1 text-sm">
            <dt className="text-muted-foreground">{t("finance.editor.totalExcl")}</dt>
            <dd className="text-right tabular-nums">{formatAmount(sums.excl)}</dd>
            <dt className="text-muted-foreground">{t("finance.editor.totalVat")}</dt>
            <dd className="text-right tabular-nums">{formatAmount(sums.vat)}</dd>
            <dt className="font-medium">{t("finance.editor.totalIncl")}</dt>
            <dd className="text-right font-medium tabular-nums">{formatAmount(sums.incl)}</dd>
          </dl>
          <Button className="w-full" disabled={!complete || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? t("finance.creating") : t(invoiceId === null ? "finance.create" : "common.save")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
