import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, CheckCheck, Eye, FileText, PackageCheck, Pencil, Plus, Printer, Trash2, Truck } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ProductSelect } from "../../components/patterns/ProductSelect";
import { StatusBadge } from "../../components/patterns/StatusBadge";
import { TableLoadingRow } from "../../components/patterns/AppLoader";
import { listPartners } from "../partners/api";
import { useProductCatalog } from "../products/catalog";
import { listLocations, listStock } from "./api";
import { getValuation } from "./valuation/api";
import { DocumentAttachments } from "./DocumentAttachments";
import { openDocument } from "./printDocument";
import {
  cancelVoucher,
  createReceiptFromPurchaseReceipt,
  createVoucher,
  generateDeliveryNote,
  getVoucher,
  listUnvoucheredPurchaseReceipts,
  listVouchers,
  postVoucher,
  updateVoucher,
  type Voucher,
  type VoucherInput,
  type VoucherType,
} from "./stockDocumentsApi";

type Key = Parameters<ReturnType<typeof useI18n>["t"]>[0];
type Filter = "all" | VoucherType;
type DraftLine = { product_id: string; quantity: number; unit_cost?: number };

const TYPES: VoucherType[] = ["receipt", "issue", "return", "transfer"];
const FILTERS: VoucherType[] = [...TYPES, "delivery"];
const today = () => new Date().toISOString().slice(0, 10);

export function VouchersTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canManage = hasPermission("warehouse.manage_vouchers");
  const canPost = hasPermission("warehouse.post_vouchers");
  const { catalog } = useProductCatalog();
  const [filter, setFilter] = useState<Filter>("all");
  const [open, setOpen] = useState(false);
  const [type, setType] = useState<VoucherType>("receipt");
  const [source, setSource] = useState("");
  const [dest, setDest] = useState("");
  const [returnOf, setReturnOf] = useState("");
  const [partner, setPartner] = useState("");
  const [note, setNote] = useState("");
  const [documentDate, setDocumentDate] = useState(today());
  const [editing, setEditing] = useState<string | null>(null);
  const [lines, setLines] = useState<DraftLine[]>([{ product_id: "", quantity: 0 }]);
  const [viewing, setViewing] = useState<string | null>(null);

  const { data: vouchers = [], isLoading } = useQuery({ queryKey: ["warehouse", "vouchers"], queryFn: () => listVouchers(token) });
  const { data: locations = [] } = useQuery({ queryKey: ["warehouse", "locations"], queryFn: () => listLocations(token) });
  const { data: stock = [] } = useQuery({ queryKey: ["warehouse", "stock"], queryFn: () => listStock(token) });
  const availableAt = (productId: string) => stock.find((s) => s.location_id === source && s.product_id === productId)?.quantity_available ?? 0;
  const locationName = (id: string | null) => locations.find((l) => l.id === id)?.name ?? "—";
  const visible = filter === "all" ? vouchers : vouchers.filter((v) => v.type === filter);
  // The manual returns against a delivery note; an issue voucher with no note yet stands in for it.
  const returnable = vouchers.filter((v) => (v.type === "issue" || v.type === "delivery") && v.status === "posted");
  // The manual's entry voucher shows each product's weighted average cost next to its cost.
  const canSeeValuation = hasPermission("warehouse.view_valuation");
  const { data: valuations = [] } = useQuery({ queryKey: ["warehouse", "valuation"], queryFn: () => getValuation(token), enabled: canSeeValuation });
  const averageCost = (productId: string) => valuations.find((v) => v.product_id === productId)?.average_unit_cost ?? null;
  const { data: partners = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token) });
  const partnerName = (id: string | null) => partners.find((p) => p.id === id)?.name ?? "—";
  const { data: purchaseReceipts = [] } = useQuery({
    queryKey: ["warehouse", "vouchers", "purchase-receipts"],
    queryFn: () => listUnvoucheredPurchaseReceipts(token),
    enabled: canManage,
  });
  const { data: viewed } = useQuery({ queryKey: ["warehouse", "voucher", viewing], queryFn: () => getVoucher(token, viewing!), enabled: viewing !== null });
  const productName = (id: string) => catalog.find((p) => p.id === id)?.name ?? id;

  const needsSource = type === "issue" || type === "transfer";
  const needsDest = type === "receipt" || type === "return" || type === "transfer";

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["warehouse"] });
  };
  const fail = (key: Key) => (error: unknown) =>
    toast.error(t(key), { description: error instanceof ApiError ? error.message : undefined });
  const warnBelowMinimum = (voucher: Voucher) => (voucher.warnings ?? []).forEach(() => toast.warning(t("voucher.belowMinimum")));

  const openNew = () => {
    setEditing(null);
    setType("receipt");
    setSource("");
    setDest("");
    setReturnOf("");
    setPartner("");
    setNote("");
    setDocumentDate(today());
    setLines([{ product_id: "", quantity: 0 }]);
    setOpen(true);
  };
  const openEdit = async (id: string) => {
    try {
      const voucher = await getVoucher(token, id);
      setEditing(id);
      setType(voucher.type);
      setSource(voucher.source_location_id ?? "");
      setDest(voucher.dest_location_id ?? "");
      setReturnOf(voucher.return_of_voucher_id ?? "");
      setPartner(voucher.partner_id ?? "");
      setNote(voucher.note ?? "");
      setDocumentDate(String(voucher.document_date).slice(0, 10));
      setLines((voucher.lines ?? []).map((l) => ({ product_id: l.product_id, quantity: Number(l.quantity), unit_cost: l.unit_cost == null ? undefined : Number(l.unit_cost) })));
      setOpen(true);
    } catch (error) {
      fail("voucher.createError")(error);
    }
  };

  const createMutation = useMutation({
    mutationFn: () => {
      const fields = {
        source_location_id: needsSource ? source : undefined,
        dest_location_id: needsDest ? dest : undefined,
        partner_id: partner || undefined,
        note: note || undefined,
        document_date: documentDate,
        lines: lines.filter((l) => l.product_id && l.quantity > 0),
      };
      if (editing) return updateVoucher(token, editing, fields);
      const input: VoucherInput = { type, return_of_voucher_id: type === "return" ? returnOf : undefined, ...fields };
      return createVoucher(token, input);
    },
    onSuccess: (voucher) => {
      refresh();
      setOpen(false);
      setLines([{ product_id: "", quantity: 0 }]);
      toast.success(t("voucher.created"));
      warnBelowMinimum(voucher);
    },
    onError: fail("voucher.createError"),
  });
  const deliveryMutation = useMutation({
    mutationFn: (id: string) => generateDeliveryNote(token, id),
    onSuccess: (voucher) => {
      refresh();
      toast.success(`${t("voucher.deliveryGenerated")} ${voucher.number ?? ""}`);
      setViewing(voucher.id);
    },
    onError: fail("voucher.deliveryError"),
  });
  const fromReceiptMutation = useMutation({
    mutationFn: (receiptId: string) => createReceiptFromPurchaseReceipt(token, receiptId),
    onSuccess: (voucher) => {
      refresh();
      toast.success(`${t("voucher.posted")} ${voucher.number ?? ""}`);
      setViewing(voucher.id);
    },
    onError: fail("voucher.createError"),
  });
  const printVoucher = (voucher: Voucher, print: boolean) => {
    const showCost = voucher.type === "receipt";
    const opened = openDocument(
      {
        title: `${t(`voucher.type.${voucher.type}` as Key)} ${voucher.number ?? t("voucher.draftLabel")}`,
        fields: [
          [t("voucher.date"), String(voucher.document_date).slice(0, 10)],
          [t("voucher.column.from"), locationName(voucher.source_location_id)],
          [t("voucher.column.to"), locationName(voucher.dest_location_id)],
          [t("voucher.partner"), partnerName(voucher.partner_id)],
          ...(voucher.type === "delivery" && !voucher.billable ? ([[t("voucher.billing"), t("voucher.notBillable")]] as [string, string][]) : []),
        ],
        headers: [t("inventory.column.product"), t("voucher.quantity"), ...(showCost ? [t("voucher.unitCost")] : [])],
        rows: (voucher.lines ?? []).map((line) => [
          productName(line.product_id),
          Number(line.quantity),
          ...(showCost ? [line.unit_cost == null ? "—" : Number(line.unit_cost)] : []),
        ]),
        footer: voucher.note ? `${t("voucher.note")} : ${voucher.note}` : undefined,
      },
      { print },
    );
    if (!opened) toast.error(t("voucher.popupBlocked"));
  };
  const postMutation = useMutation({
    mutationFn: (id: string) => postVoucher(token, id),
    onSuccess: (voucher) => {
      refresh();
      toast.success(t("voucher.posted"));
      warnBelowMinimum(voucher);
    },
    onError: fail("voucher.postError"),
  });
  const cancelMutation = useMutation({
    mutationFn: (id: string) => cancelVoucher(token, id),
    onSuccess: () => {
      refresh();
      toast.success(t("voucher.cancelled"));
    },
    onError: fail("voucher.cancelError"),
  });

  const updateLine = (index: number, patch: Partial<DraftLine>) => setLines((list) => list.map((l, i) => (i === index ? { ...l, ...patch } : l)));

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <CardTitle>{t("voucher.title")}</CardTitle>
            <FilterTabs
              value={filter}
              onChange={setFilter}
              options={[{ value: "all", label: t("common.all") }, ...FILTERS.map((v) => ({ value: v, label: t(`voucher.type.${v}` as Key) }))]}
            />
          </div>
          {canManage && (
            <Button onClick={openNew}>
              <Plus className="h-4 w-4" />
              {t("voucher.new")}
            </Button>
          )}
        </CardHeader>
        {canManage && purchaseReceipts.length > 0 && (
          <CardContent className="flex flex-wrap items-center gap-2 border-b text-sm">
            <span className="text-muted-foreground">{t("voucher.fromReception")}</span>
            {purchaseReceipts.map((receipt) => (
              <Button key={receipt.receipt_id} size="sm" variant="outline" className="h-auto py-1.5" disabled={fromReceiptMutation.isPending} onClick={() => fromReceiptMutation.mutate(receipt.receipt_id)}>
                <PackageCheck className="h-3.5 w-3.5" />
                <span className="flex flex-col items-start text-left leading-tight">
                  <span className="font-medium">{receipt.supplier_name ?? t("voucher.receipt.unknownSupplier")}</span>
                  <span className="text-xs text-muted-foreground">
                    {[
                      new Date(receipt.received_at).toLocaleDateString(),
                      receipt.invoice_number ? t("voucher.receipt.invoice").replace("{number}", receipt.invoice_number) : null,
                      t(receipt.lines === 1 ? "voucher.receipt.oneLine" : "voucher.receipt.lineCount").replace("{count}", String(receipt.lines)),
                    ].filter(Boolean).join(" · ")}
                  </span>
                </span>
              </Button>
            ))}
          </CardContent>
        )}
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("voucher.column.number")}</TableHead>
                <TableHead>{t("voucher.column.type")}</TableHead>
                <TableHead>{t("voucher.date")}</TableHead>
                <TableHead>{t("voucher.column.from")}</TableHead>
                <TableHead>{t("voucher.column.to")}</TableHead>
                <TableHead>{t("voucher.column.status")}</TableHead>
                <TableHead className="text-right">{t("voucher.column.action")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && <TableLoadingRow colSpan={7} />}
              {!isLoading && visible.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="p-0">
                    <EmptyState icon={<FileText className="h-5 w-5" />} title={t("voucher.empty.title")} description={t("voucher.empty.description")} />
                  </TableCell>
                </TableRow>
              )}
              {visible.map((voucher) => (
                <TableRow key={voucher.id}>
                  <TableCell className="font-mono text-xs">{voucher.number ?? "—"}</TableCell>
                  <TableCell>{t(`voucher.type.${voucher.type}` as Key)}</TableCell>
                  <TableCell>{String(voucher.document_date).slice(0, 10)}</TableCell>
                  <TableCell>{voucher.source_location_id ? locationName(voucher.source_location_id) : "—"}</TableCell>
                  <TableCell>{voucher.dest_location_id ? locationName(voucher.dest_location_id) : "—"}</TableCell>
                  <TableCell>
                    <StatusBadge status={voucher.status === "posted" ? "confirmed" : voucher.status} />
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      <Button size="sm" variant="ghost" onClick={() => setViewing(voucher.id)}>
                        <Eye className="h-3.5 w-3.5" />
                      </Button>
                      {canManage && voucher.status === "draft" && (
                        <Button size="sm" variant="ghost" aria-label={t("voucher.edit")} onClick={() => openEdit(voucher.id)}>
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                      )}
                      {canPost && voucher.status === "posted" && (voucher.type === "issue" || voucher.type === "return") && (
                        <Button size="sm" variant="outline" disabled={deliveryMutation.isPending} onClick={() => deliveryMutation.mutate(voucher.id)}>
                          <Truck className="h-3.5 w-3.5" />
                          {t("voucher.generateDelivery")}
                        </Button>
                      )}
                      {canPost && voucher.status === "draft" && (
                        <>
                          <Button size="sm" variant="outline" disabled={postMutation.isPending} onClick={() => postMutation.mutate(voucher.id)}>
                            <CheckCheck className="h-3.5 w-3.5" />
                            {t("voucher.post")}
                          </Button>
                          <Button size="sm" variant="outline" disabled={cancelMutation.isPending} onClick={() => cancelMutation.mutate(voucher.id)}>
                            <Ban className="h-3.5 w-3.5" />
                            {t("voucher.cancel")}
                          </Button>
                        </>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editing ? t("voucher.edit") : t("voucher.new")}</DialogTitle>
            <DialogDescription>{t("voucher.dialogDescription")}</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); createMutation.mutate(); }}>
            <div className="space-y-1.5">
              <Label htmlFor="v_type">{t("voucher.column.type")}</Label>
              <Select id="v_type" value={type} disabled={editing !== null} onChange={(e) => setType(e.target.value as VoucherType)}>
                {TYPES.map((v) => (
                  <option key={v} value={v}>{t(`voucher.type.${v}` as Key)}</option>
                ))}
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="v_date">{t("voucher.date")}</Label>
                <Input id="v_date" type="date" required value={documentDate} onChange={(e) => setDocumentDate(e.target.value)} />
              </div>
              {type !== "transfer" && (
                <div className="space-y-1.5">
                  <Label htmlFor="v_partner">{t("voucher.partner")}</Label>
                  <Select id="v_partner" value={partner} onChange={(e) => setPartner(e.target.value)}>
                    <option value="">—</option>
                    {partners.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </Select>
                </div>
              )}
              {needsSource && (
                <div className="space-y-1.5">
                  <Label htmlFor="v_source">{t("voucher.column.from")}</Label>
                  <Select id="v_source" required value={source} onChange={(e) => setSource(e.target.value)}>
                    <option value="">—</option>
                    {locations.map((l) => (
                      <option key={l.id} value={l.id}>{l.name}</option>
                    ))}
                  </Select>
                </div>
              )}
              {needsDest && (
                <div className="space-y-1.5">
                  <Label htmlFor="v_dest">{t("voucher.column.to")}</Label>
                  <Select id="v_dest" required value={dest} onChange={(e) => setDest(e.target.value)}>
                    <option value="">—</option>
                    {locations.map((l) => (
                      <option key={l.id} value={l.id}>{l.name}</option>
                    ))}
                  </Select>
                </div>
              )}
            </div>
            {type === "return" && (
              <div className="space-y-1.5">
                <Label htmlFor="v_return">{t("voucher.returnOf")}</Label>
                <Select id="v_return" required disabled={editing !== null} value={returnOf} onChange={(e) => setReturnOf(e.target.value)}>
                  <option value="">—</option>
                  {returnable.map((v) => (
                    <option key={v.id} value={v.id}>{v.number}</option>
                  ))}
                </Select>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="v_note">{type === "return" ? t("voucher.returnReason") : t("voucher.note")}</Label>
              <Input id="v_note" required={type === "return"} value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>{t("voucher.lines")}</Label>
                <Button type="button" size="sm" variant="outline" onClick={() => setLines((l) => [...l, { product_id: "", quantity: 0 }])}>
                  <Plus className="h-3.5 w-3.5" />
                </Button>
              </div>
              {lines.map((line, index) => (
                <div key={index} className="space-y-1">
                <div className={`grid gap-2 ${type === "receipt" ? "grid-cols-[1fr_6rem_6rem_auto]" : "grid-cols-[1fr_6rem_auto]"}`}>
                  <ProductSelect products={catalog} value={line.product_id} onChange={(e) => updateLine(index, { product_id: e.target.value })} />
                  <Input type="number" step="any" min="0" placeholder={t("voucher.quantity")} value={line.quantity || ""} onChange={(e) => updateLine(index, { quantity: Number(e.target.value) })} />
                  {type === "receipt" && (
                    <Input type="number" step="any" min="0" required placeholder={t("voucher.unitCost")} value={line.unit_cost ?? ""} onChange={(e) => updateLine(index, { unit_cost: Number(e.target.value) })} />
                  )}
                  <Button type="button" size="sm" variant="ghost" disabled={lines.length === 1} onClick={() => setLines((l) => l.filter((_, i) => i !== index))}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
                {(type === "issue" || type === "transfer") && source && line.product_id && (
                  <p className={`text-xs ${line.quantity > availableAt(line.product_id) ? "text-destructive" : "text-muted-foreground"}`}>
                    {t("voucher.available")}: {availableAt(line.product_id)}
                  </p>
                )}
                </div>
              ))}
            </div>
            <Button type="submit" className="w-full" disabled={createMutation.isPending}>
              {t("voucher.saveDraft")}
            </Button>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={viewing !== null} onOpenChange={(value) => !value && setViewing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{viewed ? `${t(`voucher.type.${viewed.type}` as Key)} ${viewed.number ?? ""}` : ""}</DialogTitle>
            <DialogDescription>
              {viewed && `${String(viewed.document_date).slice(0, 10)} · ${viewed.source_location_id ? locationName(viewed.source_location_id) : ""}${viewed.source_location_id && viewed.dest_location_id ? " → " : ""}${viewed.dest_location_id ? locationName(viewed.dest_location_id) : ""}${viewed.partner_id ? ` · ${partnerName(viewed.partner_id)}` : ""}`}
              {viewed?.type === "delivery" && !viewed.billable ? ` · ${t("voucher.notBillable")}` : ""}
            </DialogDescription>
          </DialogHeader>
          {viewed && (
            <div className="space-y-4">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("inventory.column.product")}</TableHead>
                    <TableHead className="text-right">{t("voucher.quantity")}</TableHead>
                    <TableHead className="text-right">{t("voucher.unitCost")}</TableHead>
                    {viewed.type === "receipt" && canSeeValuation && <TableHead className="text-right">{t("voucher.averageCost")}</TableHead>}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(viewed.lines ?? []).map((line) => (
                    <TableRow key={line.id}>
                      <TableCell>{productName(line.product_id)}</TableCell>
                      <TableCell className="text-right tabular-nums">{Number(line.quantity)}</TableCell>
                      <TableCell className="text-right tabular-nums">{line.unit_cost ? Number(line.unit_cost) : "—"}</TableCell>
                      {viewed.type === "receipt" && canSeeValuation && (
                        <TableCell className="text-right tabular-nums">{averageCost(line.product_id)?.toFixed(2) ?? "—"}</TableCell>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {viewed.note && <p className="text-sm"><span className="font-medium">{t("voucher.note")} :</span> {viewed.note}</p>}
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => printVoucher(viewed, false)}>
                  <Eye className="h-4 w-4" />
                  {t("voucher.preview")}
                </Button>
                <Button variant="outline" onClick={() => printVoucher(viewed, true)}>
                  <Printer className="h-4 w-4" />
                  {t("voucher.print")}
                </Button>
              </div>
              <DocumentAttachments entityType="voucher" entityId={viewed.id} canManage={canManage} />
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
