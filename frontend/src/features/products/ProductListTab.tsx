import { useEffect, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, type UseFormReturn } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Package, Pencil, Plus, Tag as TagIcon } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { Skeleton } from "../../components/ui/skeleton";
import { Badge } from "../../components/ui/badge";
import { Dialog, DialogTrigger, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../components/ui/dialog";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { listProducts, listUoms, listLocations, type Product } from "../warehouse/api";
import {
  createProduct,
  createProductTag,
  listProductTags,
  listTagsForProduct,
  setProductTags,
  updateProduct,
} from "./api";

const PRODUCTS_QUERY_KEY = ["core", "products"] as const;
const UOMS_QUERY_KEY = ["core", "uoms"] as const;
const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;
const TAGS_QUERY_KEY = ["core", "product-tags"] as const;

// is_sellable/is_purchasable are driven by native <select> elements, so the form state
// holds "true"/"false" strings throughout (register, defaultValues, reset) -- they're only
// converted to real booleans once, at the API-call boundary in the mutation functions below.
//
// blankToUndefined: an empty number input reaches zod as "" (react-hook-form doesn't turn
// that into undefined itself), and z.coerce.number() on "" produces 0 -- so a blank optional
// field like net weight would coerce to 0 and fail a `.positive()` check, blocking submit
// even though the user left it blank on purpose. Preprocessing "" (and null) to undefined
// first lets `.optional()` short-circuit before the number coercion ever runs.
function blankToUndefined<T extends z.ZodTypeAny>(schema: T) {
  return z.preprocess((value) => (value === "" || value === null ? undefined : value), schema);
}

const productSchema = z.object({
  sku: z.string().min(1, "Required"),
  name: z.string().min(1, "Required"),
  uom_id: z.string().min(1, "Required"),
  net_weight_grams: blankToUndefined(z.coerce.number().positive().optional()),
  is_sellable: z.enum(["true", "false"]),
  is_purchasable: z.enum(["true", "false"]),
  lot_serial_tracking: z.enum(["none", "lot", "serial"]),
  expiry_date_policy: z.enum(["none", "sell_by", "eat_by"]),
  description: z.string().optional(),
  default_location_id: z.string().optional(),
  stock_alert_threshold: blankToUndefined(z.coerce.number().min(0).optional()),
  internal_note: z.string().optional(),
  selling_price: blankToUndefined(z.coerce.number().min(0).optional()),
  min_selling_price: blankToUndefined(z.coerce.number().min(0).optional()),
  purchase_price: blankToUndefined(z.coerce.number().min(0).optional()),
  tax_rate: blankToUndefined(z.coerce.number().min(0).optional()),
  accounting_code_sale: z.string().optional(),
  accounting_code_sale_export: z.string().optional(),
  accounting_code_purchase: z.string().optional(),
  accounting_code_purchase_import: z.string().optional(),
});
type ProductForm = z.infer<typeof productSchema>;

const EMPTY_DEFAULTS: ProductForm = {
  sku: "",
  name: "",
  uom_id: "",
  net_weight_grams: undefined,
  is_sellable: "true",
  is_purchasable: "true",
  lot_serial_tracking: "none",
  expiry_date_policy: "none",
  description: "",
  default_location_id: "",
  stock_alert_threshold: undefined,
  internal_note: "",
  selling_price: 0,
  min_selling_price: undefined,
  purchase_price: 0,
  tax_rate: 0,
  accounting_code_sale: "",
  accounting_code_sale_export: "",
  accounting_code_purchase: "",
  accounting_code_purchase_import: "",
};

function toApiInput(input: ProductForm) {
  return {
    ...input,
    is_sellable: input.is_sellable === "true",
    is_purchasable: input.is_purchasable === "true",
    net_weight_grams: input.net_weight_grams || undefined,
    default_location_id: input.default_location_id || undefined,
    stock_alert_threshold: input.stock_alert_threshold ?? undefined,
    selling_price: input.selling_price ?? 0,
    min_selling_price: input.min_selling_price ?? undefined,
    purchase_price: input.purchase_price ?? 0,
    tax_rate: input.tax_rate ?? 0,
  };
}

function productToFormDefaults(product: Product): ProductForm {
  return {
    sku: product.sku,
    name: product.name,
    uom_id: product.uom_id,
    net_weight_grams: product.net_weight_grams ?? undefined,
    is_sellable: product.is_sellable ? "true" : "false",
    is_purchasable: product.is_purchasable ? "true" : "false",
    lot_serial_tracking: product.lot_serial_tracking,
    expiry_date_policy: product.expiry_date_policy,
    description: product.description ?? "",
    default_location_id: product.default_location_id ?? "",
    stock_alert_threshold: product.stock_alert_threshold ?? undefined,
    internal_note: product.internal_note ?? "",
    selling_price: product.selling_price,
    min_selling_price: product.min_selling_price ?? undefined,
    purchase_price: product.purchase_price,
    tax_rate: product.tax_rate,
    accounting_code_sale: product.accounting_code_sale ?? "",
    accounting_code_sale_export: product.accounting_code_sale_export ?? "",
    accounting_code_purchase: product.accounting_code_purchase ?? "",
    accounting_code_purchase_import: product.accounting_code_purchase_import ?? "",
  };
}

type FormFieldsProps = Pick<UseFormReturn<ProductForm>, "register" | "formState" | "watch">;

export function ProductListTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [lotTrackingFilter, setLotTrackingFilter] = useState<"all" | "none" | "lot" | "serial">("all");

  const { data: products = [], isLoading } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const { data: uoms = [] } = useQuery({ queryKey: UOMS_QUERY_KEY, queryFn: () => listUoms(token) });
  const { data: locations = [] } = useQuery({ queryKey: LOCATIONS_QUERY_KEY, queryFn: () => listLocations(token) });
  const { data: tags = [] } = useQuery({ queryKey: TAGS_QUERY_KEY, queryFn: () => listProductTags(token) });

  const topLevelProducts = products
    .filter((p) => !p.parent_product_id)
    .filter((p) => lotTrackingFilter === "all" || p.lot_serial_tracking === lotTrackingFilter);

  const newForm = useForm<ProductForm>({ resolver: zodResolver(productSchema), defaultValues: EMPTY_DEFAULTS });
  const [selectedTagIds, setSelectedTagIds] = useState<string[]>([]);

  const createMutation = useMutation({
    mutationFn: async (input: ProductForm) => {
      const product = await createProduct(token, toApiInput(input));
      if (selectedTagIds.length > 0) await setProductTags(token, product.id, selectedTagIds);
      return product;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PRODUCTS_QUERY_KEY });
      setDialogOpen(false);
      newForm.reset(EMPTY_DEFAULTS);
      setSelectedTagIds([]);
      toast.success(t("products.created"));
    },
    onError: (error) => {
      toast.error(t("products.createError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const editForm = useForm<ProductForm>({ resolver: zodResolver(productSchema) });
  const [editTagIds, setEditTagIds] = useState<string[]>([]);

  const { data: currentTags = [] } = useQuery({
    queryKey: ["core", "products", editingId, "tags"],
    queryFn: () => listTagsForProduct(token, editingId!),
    enabled: editingId !== null,
  });

  useEffect(() => {
    setEditTagIds(currentTags.map((tag) => tag.id));
  }, [currentTags]);

  const updateMutation = useMutation({
    mutationFn: async ({ id, input }: { id: string; input: ProductForm }) => {
      const product = await updateProduct(token, id, toApiInput(input));
      await setProductTags(token, id, editTagIds);
      return product;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PRODUCTS_QUERY_KEY });
      setEditingId(null);
      toast.success(t("products.updated"));
    },
    onError: (error) => {
      toast.error(t("products.updateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  function openEditDialog(product: Product | null) {
    if (!product) {
      setEditingId(null);
      return;
    }
    setEditingId(product.id);
    editForm.reset(productToFormDefaults(product));
  }

  const createTagMutation = useMutation({
    mutationFn: (name: string) => createProductTag(token, name),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TAGS_QUERY_KEY }),
  });
  const [newTagName, setNewTagName] = useState("");

  const columnFilterFields: FilterField<Product>[] = [
    { key: "sku", kind: "text", getValue: (p) => p.sku },
    { key: "name", kind: "text", getValue: (p) => p.name },
    { key: "selling_price", kind: "range", getValue: (p) => p.selling_price },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredProducts = columnFilters.apply(topLevelProducts);

  const columns: ColumnDef<Product>[] = [
    {
      key: "sku",
      header: t("products.column.ref"),
      defaultWidth: 140,
      cell: (product) => <span className="font-medium">{product.sku}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.sku ?? "",
        onChange: (v) => columnFilters.setTextValue("sku", v),
        placeholder: t("products.column.ref"),
      },
    },
    {
      key: "name",
      header: t("products.column.label"),
      defaultWidth: 220,
      cell: (product) => product.name,
      filterCell: {
        type: "text",
        value: columnFilters.text.name ?? "",
        onChange: (v) => columnFilters.setTextValue("name", v),
        placeholder: t("products.column.label"),
      },
    },
    {
      key: "sellPurchase",
      header: t("products.column.sellPurchase"),
      defaultWidth: 180,
      cell: (product) => (
        <div className="flex gap-1">
          <Badge variant={product.is_sellable ? "success" : "outline"}>{t("products.status.sell")}</Badge>
          <Badge variant={product.is_purchasable ? "success" : "outline"}>{t("products.status.purchase")}</Badge>
        </div>
      ),
    },
    {
      key: "lotTracking",
      header: t("products.column.lotTracking"),
      defaultWidth: 160,
      cell: (product) => (
        <span className="text-muted-foreground">
          {product.lot_serial_tracking === "none"
            ? "—"
            : t(`products.lotTracking.${product.lot_serial_tracking}` as Parameters<typeof t>[0])}
        </span>
      ),
    },
    {
      key: "sellingPrice",
      header: t("products.column.sellingPrice"),
      defaultWidth: 140,
      cell: (product) => <span className="tabular-nums text-muted-foreground">{product.selling_price}</span>,
      filterCell: {
        type: "range",
        min: columnFilters.range.selling_price?.min ?? "",
        max: columnFilters.range.selling_price?.max ?? "",
        onMinChange: (v) => columnFilters.setRangeValue("selling_price", "min", v),
        onMaxChange: (v) => columnFilters.setRangeValue("selling_price", "max", v),
      },
    },
    {
      key: "action",
      header: t("products.column.action"),
      defaultWidth: 140,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right",
      cell: (product) => (
        <Dialog open={editingId === product.id} onOpenChange={(open) => openEditDialog(open ? product : null)}>
          <DialogTrigger asChild>
            <Button size="sm" variant="outline">
              <Pencil className="h-3.5 w-3.5" />
              {t("products.edit")}
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>{t("products.dialog.editTitle")}</DialogTitle>
              <DialogDescription>{t("products.dialog.editDescription")}</DialogDescription>
            </DialogHeader>
            <form className="space-y-4" onSubmit={editForm.handleSubmit((input) => updateMutation.mutate({ id: product.id, input }))}>
              {renderFormFields(editForm, "edit", editTagIds, setEditTagIds)}
              <Button type="submit" className="w-full" disabled={updateMutation.isPending}>
                {updateMutation.isPending ? t("products.updating") : t("products.update")}
              </Button>
            </form>
          </DialogContent>
        </Dialog>
      ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll } = useTableColumns(
    "products.list",
    columns,
  );

  function renderTagPicker(ids: string[], onChange: (ids: string[]) => void) {
    return (
      <div className="space-y-1.5">
        <Label className="flex items-center gap-1.5">
          <TagIcon className="h-3.5 w-3.5" />
          {t("products.field.tags")}
        </Label>
        <div className="flex flex-wrap gap-1.5">
          {tags.map((tag) => {
            const selected = ids.includes(tag.id);
            return (
              <button key={tag.id} type="button" onClick={() => onChange(selected ? ids.filter((id) => id !== tag.id) : [...ids, tag.id])}>
                <Badge variant={selected ? "primary" : "outline"}>{tag.name}</Badge>
              </button>
            );
          })}
        </div>
        <div className="flex gap-1.5">
          <Input value={newTagName} onChange={(e) => setNewTagName(e.target.value)} placeholder={t("products.field.newTag")} className="h-8 text-xs" />
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              if (!newTagName.trim()) return;
              createTagMutation.mutate(newTagName.trim());
              setNewTagName("");
            }}
          >
            <Plus className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    );
  }

  function renderFormFields(form: FormFieldsProps, idPrefix: string, tagIds: string[], onTagIdsChange: (ids: string[]) => void) {
    const errors = form.formState.errors;
    const isSellable = form.watch("is_sellable") !== "false";
    const isPurchasable = form.watch("is_purchasable") !== "false";
    return (
      <>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}_sku`}>{t("products.field.ref")}</Label>
            <Input id={`${idPrefix}_sku`} {...form.register("sku")} />
            {errors.sku && <p className="text-sm text-destructive">{errors.sku.message}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}_name`}>{t("products.field.label")}</Label>
            <Input id={`${idPrefix}_name`} {...form.register("name")} />
            {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}_uom`}>{t("products.field.uom")}</Label>
            <Select id={`${idPrefix}_uom`} {...form.register("uom_id")}>
              <option value="">—</option>
              {uoms.map((uom) => (
                <option key={uom.id} value={uom.id}>
                  {uom.code}
                </option>
              ))}
            </Select>
            {errors.uom_id && <p className="text-sm text-destructive">{errors.uom_id.message}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}_weight`}>{t("products.field.netWeight")}</Label>
            <Input id={`${idPrefix}_weight`} type="number" step="any" placeholder="N/A" {...form.register("net_weight_grams")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}_sellable`}>{t("products.field.statusSell")}</Label>
            <Select id={`${idPrefix}_sellable`} {...form.register("is_sellable")}>
              <option value="true">{t("products.status.forSale")}</option>
              <option value="false">{t("products.status.notForSale")}</option>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}_purchasable`}>{t("products.field.statusPurchase")}</Label>
            <Select id={`${idPrefix}_purchasable`} {...form.register("is_purchasable")}>
              <option value="true">{t("products.status.forPurchase")}</option>
              <option value="false">{t("products.status.notForPurchase")}</option>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}_lot`}>{t("products.field.lotSerialTracking")}</Label>
            <Select id={`${idPrefix}_lot`} {...form.register("lot_serial_tracking")}>
              <option value="none">{t("products.lotTracking.none")}</option>
              <option value="lot">{t("products.lotTracking.lot")}</option>
              <option value="serial">{t("products.lotTracking.serial")}</option>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}_expiry`}>{t("products.field.expiryDatePolicy")}</Label>
            <Select id={`${idPrefix}_expiry`} {...form.register("expiry_date_policy")}>
              <option value="none">{t("products.expiryPolicy.none")}</option>
              <option value="sell_by">{t("products.expiryPolicy.sellBy")}</option>
              <option value="eat_by">{t("products.expiryPolicy.eatBy")}</option>
            </Select>
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor={`${idPrefix}_description`}>{t("products.field.description")}</Label>
          <Input id={`${idPrefix}_description`} {...form.register("description")} />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}_location`}>{t("products.field.defaultWarehouse")}</Label>
            <Select id={`${idPrefix}_location`} {...form.register("default_location_id")}>
              <option value="">—</option>
              {locations.map((location) => (
                <option key={location.id} value={location.id}>
                  {location.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}_alert`}>{t("products.field.stockAlert")}</Label>
            <Input id={`${idPrefix}_alert`} type="number" step="any" {...form.register("stock_alert_threshold")} />
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor={`${idPrefix}_note`}>{t("products.field.note")}</Label>
          <Input id={`${idPrefix}_note`} {...form.register("internal_note")} />
        </div>

        {renderTagPicker(tagIds, onTagIdsChange)}

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}_price`}>{t("products.field.sellingPrice")}</Label>
            <Input id={`${idPrefix}_price`} type="number" step="any" disabled={!isSellable} placeholder={!isSellable ? "N/A" : undefined} {...form.register("selling_price")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}_minprice`}>{t("products.field.minSellingPrice")}</Label>
            <Input id={`${idPrefix}_minprice`} type="number" step="any" disabled={!isSellable} placeholder={!isSellable ? "N/A" : undefined} {...form.register("min_selling_price")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}_purchaseprice`}>{t("products.field.purchasePrice")}</Label>
            <Input id={`${idPrefix}_purchaseprice`} type="number" step="any" disabled={!isPurchasable} placeholder={!isPurchasable ? "N/A" : undefined} {...form.register("purchase_price")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}_tax`}>{t("products.field.taxRate")}</Label>
            <Input id={`${idPrefix}_tax`} type="number" step="any" {...form.register("tax_rate")} />
          </div>
        </div>

        <div className="space-y-1.5 rounded-lg border border-border p-3">
          <Label className="text-xs text-muted-foreground">{t("products.field.accountingCodes")}</Label>
          <div className="grid grid-cols-2 gap-2">
            <Input placeholder={t("products.field.accountingSale")} disabled={!isSellable} {...form.register("accounting_code_sale")} />
            <Input placeholder={t("products.field.accountingSaleExport")} disabled={!isSellable} {...form.register("accounting_code_sale_export")} />
            <Input placeholder={t("products.field.accountingPurchase")} disabled={!isPurchasable} {...form.register("accounting_code_purchase")} />
            <Input placeholder={t("products.field.accountingPurchaseImport")} disabled={!isPurchasable} {...form.register("accounting_code_purchase_import")} />
          </div>
        </div>
      </>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle>{t("products.table.title")}</CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("products.table.subtitle")}</p>
            </div>
            <FilterTabs
              value={lotTrackingFilter}
              onChange={setLotTrackingFilter}
              options={[
                { value: "all", label: t("common.all") },
                { value: "none", label: t("products.lotTracking.none") },
                { value: "lot", label: t("products.lotTracking.lot") },
                { value: "serial", label: t("products.lotTracking.serial") },
              ]}
            />
            {columnFilters.isActive && (
              <Button variant="ghost" size="sm" onClick={columnFilters.reset}>
                {t("common.clearFilters")}
              </Button>
            )}
            <ColumnVisibilityMenu columns={columns} isVisible={isVisible} onToggle={toggleVisible} onReset={resetAll} />
          </div>
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="h-4 w-4" />
                {t("products.new")}
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
              <DialogHeader>
                <DialogTitle>{t("products.dialog.title")}</DialogTitle>
                <DialogDescription>{t("products.dialog.description")}</DialogDescription>
              </DialogHeader>
              <form className="space-y-4" onSubmit={newForm.handleSubmit((input) => createMutation.mutate(input))}>
                {renderFormFields(newForm, "new", selectedTagIds, setSelectedTagIds)}
                {createMutation.isError && (
                  <p className="text-sm text-destructive">
                    {createMutation.error instanceof ApiError ? createMutation.error.message : t("products.createError")}
                  </p>
                )}
                <Button type="submit" className="w-full" disabled={createMutation.isPending}>
                  {createMutation.isPending ? t("products.creating") : t("products.create")}
                </Button>
              </form>
            </DialogContent>
          </Dialog>
        </CardHeader>
        <CardContent className="p-0">
          <Table colWidths={colWidths}>
            <TableHeader>
              <TableRow>
                {visibleColumns.map((column) => (
                  <ResizableTableHead
                    key={column.key}
                    width={getWidth(column.key)}
                    onResize={(width) => setWidth(column.key, width)}
                    className={column.headerClassName}
                  >
                    {column.header}
                  </ResizableTableHead>
                ))}
              </TableRow>
              <ColumnFilterRow cells={visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
            </TableHeader>
            <TableBody>
              {isLoading &&
                Array.from({ length: 3 }).map((_, i) => (
                  <TableRow key={i}>
                    <TableCell colSpan={visibleColumns.length}>
                      <Skeleton className="h-5 w-full" />
                    </TableCell>
                  </TableRow>
                ))}
              {!isLoading && filteredProducts.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <EmptyState icon={<Package className="h-5 w-5" />} title={t("products.empty.title")} description={t("products.empty.description")} />
                  </TableCell>
                </TableRow>
              )}
              <AnimatePresence initial={false}>
                {filteredProducts.map((product, i) => (
                  <motion.tr
                    key={product.id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i * 0.04, 0.3) } }}
                    exit={{ opacity: 0 }}
                    className="border-b border-border last:border-0 hover:bg-muted/50"
                  >
                    {visibleColumns.map((column) => (
                      <TableCell key={column.key} className={column.cellClassName}>
                        {column.cell(product)}
                      </TableCell>
                    ))}
                  </motion.tr>
                ))}
              </AnimatePresence>
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
