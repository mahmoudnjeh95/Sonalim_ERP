import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Pencil, Plus, Save, Tags, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { formatXofWithCode } from "../../lib/currency";
import { useI18n } from "../../lib/i18n";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "../../components/ui/dialog";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { ResizableTableHead, Table, TableBody, TableCell, TableHeader, TableRow } from "../../components/ui/table";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ProductSelect } from "../../components/patterns/ProductSelect";
import { listPartners } from "../partners/api";
import { useProductCatalog } from "../products/catalog";
import {
  createPriceList,
  CUSTOMER_PRICING_QUERY_KEY,
  deletePriceList,
  exportPriceList,
  getPriceList,
  importPriceItems,
  listCustomerPricing,
  listPriceLists,
  PRICE_LISTS_QUERY_KEY,
  replacePriceItems,
  SALES_SETTINGS_QUERY_KEY,
  setCustomerPricing,
  updatePriceList,
  updateSalesSettings,
  type ImportPreview,
  type PriceList,
  type PriceListInput,
} from "./pricingApi";
import { useSalesSettings } from "./PricedLinesFields";

type Key = Parameters<ReturnType<typeof useI18n>["t"]>[0];
type ItemRow = { key: string; product_id: string; min_quantity: string; unit_price: string };

const EMPTY_LIST: PriceListInput = { name: "", valid_from: null, valid_to: null, is_default: false, active: true, note: null };

function toBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export function PriceListsPage() {
  const { session, hasPermission } = useAuth();
  const { t, language } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const canManage = hasPermission("sales.manage_price_lists");
  const canSettings = hasPermission("sales.admin_orders");
  const [activeFilter, setActiveFilter] = useState<"all" | "active" | "inactive">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<PriceList | null>(null);
  const [form, setForm] = useState<PriceListInput | null>(null);
  const [rows, setRows] = useState<ItemRow[]>([]);
  const [preview, setPreview] = useState<{ file: File; result: ImportPreview } | null>(null);

  const { data: lists = [] } = useQuery({ queryKey: PRICE_LISTS_QUERY_KEY, queryFn: () => listPriceLists(token) });
  const selected = useQuery({ queryKey: [...PRICE_LISTS_QUERY_KEY, selectedId], queryFn: () => getPriceList(token, selectedId!), enabled: !!selectedId });
  const { catalog } = useProductCatalog();
  const products = catalog.filter((product) => product.is_sellable);
  const fail = (key: Key) => (error: unknown) => toast.error(t(key), { description: error instanceof ApiError ? error.message : undefined });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: PRICE_LISTS_QUERY_KEY });

  useEffect(() => {
    if (!selected.data) return;
    setRows(
      selected.data.items.map((item) => ({ key: item.id, product_id: item.product_id, min_quantity: String(Number(item.min_quantity)), unit_price: String(Number(item.unit_price)) })),
    );
  }, [selected.data]);

  const saveListMutation = useMutation({
    mutationFn: (input: PriceListInput) => (editing ? updatePriceList(token, editing.id, input) : createPriceList(token, input)),
    onSuccess: (list) => {
      invalidate();
      setForm(null);
      setSelectedId(list.id);
      toast.success(t("sales.priceLists.saved"));
    },
    onError: fail("sales.priceLists.saveError"),
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deletePriceList(token, id),
    onSuccess: () => {
      invalidate();
      queryClient.invalidateQueries({ queryKey: CUSTOMER_PRICING_QUERY_KEY });
      setSelectedId(null);
      toast.success(t("sales.priceLists.deleted"));
    },
    onError: fail("sales.priceLists.saveError"),
  });
  const saveItemsMutation = useMutation({
    mutationFn: () =>
      replacePriceItems(
        token,
        selectedId!,
        rows.filter((row) => row.product_id).map((row) => ({ product_id: row.product_id, min_quantity: Number(row.min_quantity) || 1, unit_price: Number(row.unit_price) })),
      ),
    onSuccess: () => {
      invalidate();
      toast.success(t("sales.priceLists.pricesSaved"));
    },
    onError: fail("sales.priceLists.saveError"),
  });
  const importMutation = useMutation({
    mutationFn: async ({ file, commit }: { file: File; commit: boolean }) =>
      ({ file, result: await importPriceItems(token, selectedId!, { filename: file.name, content_base64: await toBase64(file), commit }), commit }),
    onSuccess: ({ file, result, commit }) => {
      if (commit) {
        setPreview(null);
        invalidate();
        toast.success(t("sales.priceLists.imported"));
      } else {
        setPreview({ file, result });
      }
    },
    onError: fail("sales.priceLists.importError"),
  });

  async function download(format: "csv" | "xlsx") {
    try {
      const blob = await exportPriceList(token, selectedId!, format, language);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${selected.data?.name ?? "price-list"}.${format}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      fail("sales.priceLists.exportError")(error);
    }
  }

  const productName = (id: string) => products.find((p) => p.id === id)?.name ?? id;
  const catalogPrice = (id: string) => catalog.find((p) => p.id === id)?.selling_price;

  const statusFiltered = activeFilter === "all" ? lists : lists.filter((list) => (activeFilter === "active" ? list.active : !list.active));
  const filterFields: FilterField<PriceList>[] = [
    { key: "name", kind: "text", getValue: (l) => l.name },
    { key: "items", kind: "range", getValue: (l) => l.item_count },
    { key: "customers", kind: "range", getValue: (l) => l.customer_count },
  ];
  const columnFilters = useColumnFilters(filterFields);
  const filtered = columnFilters.apply(statusFiltered);
  const columns: ColumnDef<PriceList>[] = [
    {
      key: "name",
      header: t("sales.priceLists.column.name"),
      defaultWidth: 220,
      cell: (l) => (
        <button type="button" className="text-left font-medium text-primary underline-offset-2 hover:underline" onClick={() => setSelectedId(l.id)}>
          {l.name} {l.is_default && <Badge variant="primary">{t("sales.priceLists.default")}</Badge>}
        </button>
      ),
      filterCell: { type: "text", value: columnFilters.text.name ?? "", onChange: (v) => columnFilters.setTextValue("name", v), placeholder: t("sales.priceLists.column.name") },
      sortValue: (l) => l.name,
    },
    {
      key: "validity",
      header: t("sales.priceLists.column.validity"),
      defaultWidth: 200,
      cell: (l) => (l.valid_from || l.valid_to ? `${l.valid_from ?? "…"} → ${l.valid_to ?? "…"}` : t("sales.priceLists.always")),
    },
    {
      key: "items",
      header: t("sales.priceLists.column.items"),
      defaultWidth: 110,
      cellClassName: "tabular-nums",
      cell: (l) => l.item_count,
      filterCell: { type: "range", min: columnFilters.range.items?.min ?? "", max: columnFilters.range.items?.max ?? "", onMinChange: (v) => columnFilters.setRangeValue("items", "min", v), onMaxChange: (v) => columnFilters.setRangeValue("items", "max", v) },
      sortValue: (l) => l.item_count,
    },
    {
      key: "customers",
      header: t("sales.priceLists.column.customers"),
      defaultWidth: 110,
      cellClassName: "tabular-nums",
      cell: (l) => l.customer_count,
      filterCell: { type: "range", min: columnFilters.range.customers?.min ?? "", max: columnFilters.range.customers?.max ?? "", onMinChange: (v) => columnFilters.setRangeValue("customers", "min", v), onMaxChange: (v) => columnFilters.setRangeValue("customers", "max", v) },
      sortValue: (l) => l.customer_count,
    },
    { key: "active", header: t("sales.priceLists.column.status"), defaultWidth: 100, cell: (l) => <Badge variant={l.active ? "success" : "outline"}>{t(l.active ? "sales.priceLists.active" : "sales.priceLists.inactive")}</Badge> },
    {
      key: "action",
      header: t("sales.column.action"),
      defaultWidth: 120,
      alwaysVisible: true,
      headerClassName: "text-right",
      cell: (l) =>
        canManage ? (
          <div className="flex justify-end gap-1">
            <Button size="sm" variant="ghost" aria-label={t("sales.edit")} onClick={() => { setEditing(l); setForm({ name: l.name, valid_from: l.valid_from, valid_to: l.valid_to, is_default: l.is_default, active: l.active, note: l.note }); }}>
              <Pencil className="h-3.5 w-3.5" />
            </Button>
            <Button size="sm" variant="ghost" aria-label={t("sales.priceLists.delete")} onClick={() => { if (window.confirm(t("sales.priceLists.deleteConfirm"))) deleteMutation.mutate(l.id); }}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        ) : null,
    },
  ];
  const table = useTableColumns("sales.priceLists", columns);
  const sorted = table.sortRows(filtered);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{t("sales.priceLists.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("sales.priceLists.subtitle")}</p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <CardTitle>{t("sales.priceLists.lists")}</CardTitle>
            <FilterTabs
              value={activeFilter}
              onChange={setActiveFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "active", label: t("sales.priceLists.active") },
                { value: "inactive", label: t("sales.priceLists.inactive") },
              ]}
            />
            {columnFilters.isActive && (
              <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                {t("common.clearFilters")}
              </Button>
            )}
            <ColumnVisibilityMenu columns={columns} isVisible={table.isVisible} onToggle={table.toggleVisible} onReset={table.resetAll} />
            {canManage && (
              <Button className="ml-auto" onClick={() => { setEditing(null); setForm({ ...EMPTY_LIST }); }}>
                <Plus className="h-4 w-4" />
                {t("sales.priceLists.new")}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          <Table colWidths={table.colWidths}>
            <TableHeader>
              <TableRow>
                {table.visibleColumns.map((column) => (
                  <ResizableTableHead key={column.key} width={table.getWidth(column.key)} onResize={(width) => table.setWidth(column.key, width)}
                    className={column.headerClassName} sortDirection={table.sortDirectionFor(column.key)}
                    onSort={column.sortValue ? () => table.toggleSort(column.key) : undefined}>
                    {column.header}
                  </ResizableTableHead>
                ))}
              </TableRow>
              <ColumnFilterRow cells={table.visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
            </TableHeader>
            <TableBody>
              {sorted.length === 0 && (
                <TableRow>
                  <TableCell colSpan={table.visibleColumns.length} className="p-0">
                    <EmptyState icon={<Tags className="h-5 w-5" />} title={t("sales.priceLists.empty.title")} description={t("sales.priceLists.empty.description")} />
                  </TableCell>
                </TableRow>
              )}
              {sorted.map((list) => (
                <TableRow key={list.id} className={list.id === selectedId ? "bg-muted/50" : undefined}>
                  {table.visibleColumns.map((column) => (
                    <TableCell key={column.key} className={column.cellClassName}>
                      {column.cell(list)}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {selectedId && selected.data && (
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle>
                {t("sales.priceLists.prices")} — {selected.data.name}
              </CardTitle>
              <div className="ml-auto flex flex-wrap gap-2">
                <Button size="sm" variant="outline" onClick={() => download("xlsx")}>
                  <Download className="h-3.5 w-3.5" /> Excel
                </Button>
                <Button size="sm" variant="outline" onClick={() => download("csv")}>
                  <Download className="h-3.5 w-3.5" /> CSV
                </Button>
                {canManage && (
                  <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm hover:bg-muted">
                    <Upload className="h-3.5 w-3.5" />
                    {t("sales.priceLists.import")}
                    <input type="file" accept=".csv,.txt,.xlsx" className="hidden" onChange={(e) => { const file = e.target.files?.[0]; if (file) importMutation.mutate({ file, commit: false }); e.target.value = ""; }} />
                  </label>
                )}
              </div>
            </div>
            <p className="text-sm text-muted-foreground">{t("sales.priceLists.pricesHint")}</p>
          </CardHeader>
          <CardContent className="space-y-2">
            {rows.map((row, index) => (
              <div key={row.key} className="grid grid-cols-2 items-end gap-2 sm:grid-cols-[minmax(0,1fr)_7rem_9rem_7rem_auto]">
                <div className="col-span-2 space-y-1 sm:col-span-1">
                  <span className="block text-xs text-muted-foreground">{t("sales.field.productId")}</span>
                  <ProductSelect products={products} disabled={!canManage} value={row.product_id}
                    onChange={(e) => setRows(rows.map((r, i) => (i === index ? { ...r, product_id: e.target.value } : r)))} />
                </div>
                <div className="space-y-1">
                  <span className="block text-xs text-muted-foreground">{t("sales.priceLists.fromQuantity")}</span>
                  <Input type="number" step="any" min={0} disabled={!canManage} value={row.min_quantity}
                    onChange={(e) => setRows(rows.map((r, i) => (i === index ? { ...r, min_quantity: e.target.value } : r)))} />
                </div>
                <div className="space-y-1">
                  <span className="block text-xs text-muted-foreground">{t("sales.field.unitPrice")}</span>
                  <Input type="number" step="any" min={0} disabled={!canManage} value={row.unit_price}
                    onChange={(e) => setRows(rows.map((r, i) => (i === index ? { ...r, unit_price: e.target.value } : r)))} />
                </div>
                <span className="pb-2 text-xs text-muted-foreground">
                  {row.product_id && catalogPrice(row.product_id) != null ? `${t("sales.priceLists.catalog")} ${formatXofWithCode(Number(catalogPrice(row.product_id)))}` : ""}
                </span>
                {canManage && (
                  <Button size="sm" variant="ghost" aria-label={t("sales.removeLine")} onClick={() => setRows(rows.filter((_, i) => i !== index))}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                )}
              </div>
            ))}
            {rows.length === 0 && <p className="text-sm text-muted-foreground">{t("sales.priceLists.noPrices")}</p>}
            {canManage && (
              <div className="flex flex-wrap gap-2 pt-2">
                <Button size="sm" variant="ghost" onClick={() => setRows([...rows, { key: crypto.randomUUID(), product_id: "", min_quantity: "1", unit_price: "0" }])}>
                  <Plus className="h-3.5 w-3.5" />
                  {t("sales.priceLists.addPrice")}
                </Button>
                <Button size="sm" onClick={() => saveItemsMutation.mutate()} disabled={saveItemsMutation.isPending}>
                  <Save className="h-3.5 w-3.5" />
                  {t("sales.priceLists.savePrices")}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <CustomerPricingCard lists={lists} canManage={canManage} />
      {canSettings && <SalesSettingsCard />}

      <Dialog open={!!form} onOpenChange={(open) => !open && setForm(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{editing ? t("sales.priceLists.editTitle") : t("sales.priceLists.new")}</DialogTitle>
            <DialogDescription>{t("sales.priceLists.formHint")}</DialogDescription>
          </DialogHeader>
          {form && (
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); saveListMutation.mutate(form); }}>
              <div className="space-y-1.5">
                <Label htmlFor="pl_name">{t("sales.priceLists.column.name")}</Label>
                <Input id="pl_name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1.5">
                  <Label htmlFor="pl_from">{t("sales.priceLists.validFrom")}</Label>
                  <Input id="pl_from" type="date" value={form.valid_from ?? ""} onChange={(e) => setForm({ ...form, valid_from: e.target.value || null })} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="pl_to">{t("sales.priceLists.validTo")}</Label>
                  <Input id="pl_to" type="date" value={form.valid_to ?? ""} onChange={(e) => setForm({ ...form, valid_to: e.target.value || null })} />
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.is_default} onChange={(e) => setForm({ ...form, is_default: e.target.checked })} />
                {t("sales.priceLists.makeDefault")}
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} />
                {t("sales.priceLists.active")}
              </label>
              <div className="space-y-1.5">
                <Label htmlFor="pl_note">{t("sales.quotes.field.note")}</Label>
                <Input id="pl_note" value={form.note ?? ""} onChange={(e) => setForm({ ...form, note: e.target.value || null })} />
              </div>
              <Button type="submit" className="w-full" disabled={saveListMutation.isPending}>
                {t("sales.priceLists.save")}
              </Button>
            </form>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={!!preview} onOpenChange={(open) => !open && setPreview(null)}>
        <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("sales.priceLists.importPreview")}</DialogTitle>
            <DialogDescription>{t("sales.priceLists.importHint")}</DialogDescription>
          </DialogHeader>
          {preview && (
            <div className="space-y-3 text-sm">
              <p>
                {preview.result.items.length} {t("sales.priceLists.importRows")}
              </p>
              {preview.result.errors.map((error) => (
                <p key={error.row} className="text-destructive">
                  {t("sales.priceLists.row")} {error.row} : {language === "fr" ? error.message_fr : error.message}
                </p>
              ))}
              <ul className="max-h-60 space-y-0.5 overflow-y-auto">
                {preview.result.items.map((item, i) => (
                  <li key={i} className="flex justify-between gap-2">
                    <span>{productName(item.product_id)} (≥ {Number(item.min_quantity)})</span>
                    <span className="tabular-nums">{formatXofWithCode(Number(item.unit_price))}</span>
                  </li>
                ))}
              </ul>
              <Button className="w-full" disabled={preview.result.errors.length > 0 || importMutation.isPending}
                onClick={() => importMutation.mutate({ file: preview.file, commit: true })}>
                {t("sales.priceLists.importConfirm")}
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function CustomerPricingCard({ lists, canManage }: { lists: PriceList[]; canManage: boolean }) {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const { data: partners = [] } = useQuery({ queryKey: ["core", "partners"], queryFn: () => listPartners(token) });
  const { data: assigned = [] } = useQuery({ queryKey: CUSTOMER_PRICING_QUERY_KEY, queryFn: () => listCustomerPricing(token) });
  const [search, setSearch] = useState("");
  const [drafts, setDrafts] = useState<Record<string, { price_list_id: string; discount_rate: string }>>({});
  const customers = partners.filter((p) => (p.kind === "customer" || p.kind === "both") && p.name.toLowerCase().includes(search.toLowerCase()));
  const current = (partnerId: string) => {
    const row = assigned.find((a) => a.partner_id === partnerId);
    return drafts[partnerId] ?? { price_list_id: row?.price_list_id ?? "", discount_rate: String(Number(row?.discount_rate ?? 0)) };
  };
  const saveMutation = useMutation({
    mutationFn: (partnerId: string) => {
      const value = current(partnerId);
      return setCustomerPricing(token, partnerId, { price_list_id: value.price_list_id || null, discount_rate: Number(value.discount_rate) || 0 });
    },
    onSuccess: (_, partnerId) => {
      queryClient.invalidateQueries({ queryKey: CUSTOMER_PRICING_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: PRICE_LISTS_QUERY_KEY });
      setDrafts(({ [partnerId]: _done, ...rest }) => rest);
      toast.success(t("sales.priceLists.customerSaved"));
    },
    onError: (error) => toast.error(t("sales.priceLists.saveError"), { description: error instanceof ApiError ? error.message : undefined }),
  });

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-3">
          <CardTitle>{t("sales.priceLists.customers")}</CardTitle>
          <Input className="ml-auto w-56" placeholder={t("sales.column.partner")} value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <p className="text-sm text-muted-foreground">{t("sales.priceLists.customersHint")}</p>
      </CardHeader>
      <CardContent className="space-y-2">
        {customers.map((customer) => {
          const value = current(customer.id);
          const dirty = !!drafts[customer.id];
          return (
            <div key={customer.id} className="grid grid-cols-2 items-center gap-2 sm:grid-cols-[minmax(0,1fr)_14rem_7rem_auto]">
              <span className="col-span-2 font-medium sm:col-span-1">{customer.name}</span>
              <Select aria-label={t("sales.priceLists.list")} disabled={!canManage} value={value.price_list_id}
                onChange={(e) => setDrafts({ ...drafts, [customer.id]: { ...value, price_list_id: e.target.value } })}>
                <option value="">{t("sales.priceLists.useDefault")}</option>
                {lists.map((list) => (
                  <option key={list.id} value={list.id}>
                    {list.name}
                  </option>
                ))}
              </Select>
              <Input type="number" step="any" min={0} max={100} aria-label={t("sales.priceLists.customerDiscount")} disabled={!canManage}
                value={value.discount_rate} onChange={(e) => setDrafts({ ...drafts, [customer.id]: { ...value, discount_rate: e.target.value } })} />
              {canManage && (
                <Button size="sm" variant={dirty ? "default" : "ghost"} disabled={!dirty || saveMutation.isPending} onClick={() => saveMutation.mutate(customer.id)}>
                  <Save className="h-3.5 w-3.5" />
                </Button>
              )}
            </div>
          );
        })}
        <p className="text-xs text-muted-foreground">{t("sales.priceLists.customerDiscountHint")}</p>
      </CardContent>
    </Card>
  );
}

function SalesSettingsCard() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const settings = useSalesSettings().data;
  const [values, setValues] = useState<{ default_vat_rate: string; max_discount_rate: string; quote_validity_days: string } | null>(null);
  useEffect(() => {
    if (settings) {
      setValues({
        default_vat_rate: String(Number(settings.default_vat_rate)),
        max_discount_rate: String(Number(settings.max_discount_rate)),
        quote_validity_days: String(settings.quote_validity_days),
      });
    }
  }, [settings]);
  const saveMutation = useMutation({
    mutationFn: () =>
      updateSalesSettings(token, {
        default_vat_rate: values!.default_vat_rate,
        max_discount_rate: values!.max_discount_rate,
        quote_validity_days: Number(values!.quote_validity_days),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: SALES_SETTINGS_QUERY_KEY });
      toast.success(t("sales.settings.saved"));
    },
    onError: (error) => toast.error(t("sales.priceLists.saveError"), { description: error instanceof ApiError ? error.message : undefined }),
  });
  if (!values) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("sales.settings.title")}</CardTitle>
      </CardHeader>
      <CardContent>
        <form className="grid gap-3 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end" onSubmit={(e) => { e.preventDefault(); saveMutation.mutate(); }}>
          <div className="space-y-1.5">
            <Label htmlFor="ss_vat">{t("sales.settings.defaultVat")}</Label>
            <Input id="ss_vat" type="number" step="any" min={0} max={100} value={values.default_vat_rate} onChange={(e) => setValues({ ...values, default_vat_rate: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ss_disc">{t("sales.settings.maxDiscount")}</Label>
            <Input id="ss_disc" type="number" step="any" min={0} max={100} value={values.max_discount_rate} onChange={(e) => setValues({ ...values, max_discount_rate: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ss_days">{t("sales.settings.validityDays")}</Label>
            <Input id="ss_days" type="number" step="1" min={1} value={values.quote_validity_days} onChange={(e) => setValues({ ...values, quote_validity_days: e.target.value })} />
          </div>
          <Button type="submit" disabled={saveMutation.isPending}>
            <Save className="h-4 w-4" />
            {t("sales.priceLists.save")}
          </Button>
        </form>
        <p className="mt-2 text-xs text-muted-foreground">{t("sales.settings.hint")}</p>
      </CardContent>
    </Card>
  );
}
