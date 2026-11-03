import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, CheckCheck, Eye, FileText, Plus, Printer, Trash2 } from "lucide-react";
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
import { useProductCatalog } from "../products/catalog";
import { listLocations, listStock } from "./api";
import { cancelVoucher, createVoucher, getVoucher, listVouchers, postVoucher, type VoucherInput, type VoucherType } from "./stockDocumentsApi";

type Key = Parameters<ReturnType<typeof useI18n>["t"]>[0];
type Filter = "all" | VoucherType;
type DraftLine = { product_id: string; quantity: number; unit_cost?: number };

const TYPES: VoucherType[] = ["receipt", "issue", "return", "transfer"];

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
  const [lines, setLines] = useState<DraftLine[]>([{ product_id: "", quantity: 0 }]);
  const [viewing, setViewing] = useState<string | null>(null);

  const { data: vouchers = [], isLoading } = useQuery({ queryKey: ["warehouse", "vouchers"], queryFn: () => listVouchers(token) });
  const { data: locations = [] } = useQuery({ queryKey: ["warehouse", "locations"], queryFn: () => listLocations(token) });
  const { data: stock = [] } = useQuery({ queryKey: ["warehouse", "stock"], queryFn: () => listStock(token) });
  const availableAt = (productId: string) => stock.find((s) => s.location_id === source && s.product_id === productId)?.quantity_available ?? 0;
  const locationName = (id: string | null) => locations.find((l) => l.id === id)?.name ?? "—";
  const visible = filter === "all" ? vouchers : vouchers.filter((v) => v.type === filter);
  const postedIssues = vouchers.filter((v) => v.type === "issue" && v.status === "posted");
  const { data: viewed } = useQuery({ queryKey: ["warehouse", "voucher", viewing], queryFn: () => getVoucher(token, viewing!), enabled: viewing !== null });
  const productName = (id: string) => catalog.find((p) => p.id === id)?.name ?? id;

  const needsSource = type === "issue" || type === "transfer";
  const needsDest = type === "receipt" || type === "return" || type === "transfer";

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["warehouse"] });
  };
  const fail = (key: Key) => (error: unknown) =>
    toast.error(t(key), { description: error instanceof ApiError ? error.message : undefined });

  const createMutation = useMutation({
    mutationFn: () => {
      const input: VoucherInput = {
        type,
        source_location_id: needsSource ? source : undefined,
        dest_location_id: needsDest ? dest : undefined,
        return_of_voucher_id: type === "return" ? returnOf : undefined,
        lines: lines.filter((l) => l.product_id && l.quantity > 0),
      };
      return createVoucher(token, input);
    },
    onSuccess: () => {
      refresh();
      setOpen(false);
      setLines([{ product_id: "", quantity: 0 }]);
      toast.success(t("voucher.created"));
    },
    onError: fail("voucher.createError"),
  });
  const postMutation = useMutation({
    mutationFn: (id: string) => postVoucher(token, id),
    onSuccess: (voucher) => {
      refresh();
      toast.success(t("voucher.posted"));
      (voucher.warnings ?? []).forEach(() => toast.warning(t("voucher.belowMinimum")));
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
              options={[{ value: "all", label: t("common.all") }, ...TYPES.map((v) => ({ value: v, label: t(`voucher.type.${v}` as Key) }))]}
            />
          </div>
          {canManage && (
            <Button onClick={() => setOpen(true)}>
              <Plus className="h-4 w-4" />
              {t("voucher.new")}
            </Button>
          )}
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("voucher.column.number")}</TableHead>
                <TableHead>{t("voucher.column.type")}</TableHead>
                <TableHead>{t("voucher.column.from")}</TableHead>
                <TableHead>{t("voucher.column.to")}</TableHead>
                <TableHead>{t("voucher.column.status")}</TableHead>
                <TableHead className="text-right">{t("voucher.column.action")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading && <TableLoadingRow colSpan={6} />}
              {!isLoading && visible.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="p-0">
                    <EmptyState icon={<FileText className="h-5 w-5" />} title={t("voucher.empty.title")} description={t("voucher.empty.description")} />
                  </TableCell>
                </TableRow>
              )}
              {visible.map((voucher) => (
                <TableRow key={voucher.id}>
                  <TableCell className="font-mono text-xs">{voucher.number ?? "—"}</TableCell>
                  <TableCell>{t(`voucher.type.${voucher.type}` as Key)}</TableCell>
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
            <DialogTitle>{t("voucher.new")}</DialogTitle>
            <DialogDescription>{t("voucher.dialogDescription")}</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); createMutation.mutate(); }}>
            <div className="space-y-1.5">
              <Label htmlFor="v_type">{t("voucher.column.type")}</Label>
              <Select id="v_type" value={type} onChange={(e) => setType(e.target.value as VoucherType)}>
                {TYPES.map((v) => (
                  <option key={v} value={v}>{t(`voucher.type.${v}` as Key)}</option>
                ))}
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-3">
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
                <Select id="v_return" required value={returnOf} onChange={(e) => setReturnOf(e.target.value)}>
                  <option value="">—</option>
                  {postedIssues.map((v) => (
                    <option key={v.id} value={v.id}>{v.number}</option>
                  ))}
                </Select>
              </div>
            )}
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
              {viewed && `${viewed.source_location_id ? locationName(viewed.source_location_id) : ""}${viewed.source_location_id && viewed.dest_location_id ? " → " : ""}${viewed.dest_location_id ? locationName(viewed.dest_location_id) : ""}`}
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
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(viewed.lines ?? []).map((line) => (
                    <TableRow key={line.id}>
                      <TableCell>{productName(line.product_id)}</TableCell>
                      <TableCell className="text-right tabular-nums">{Number(line.quantity)}</TableCell>
                      <TableCell className="text-right tabular-nums">{line.unit_cost ? Number(line.unit_cost) : "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <Button variant="outline" className="print:hidden" onClick={() => window.print()}>
                <Printer className="h-4 w-4" />
                {t("voucher.print")}
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
