import { useEffect, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, type UseFormReturn } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Package, Pencil, Plus, Tag as TagIcon, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { Badge } from "../../components/ui/badge";
import { Dialog, DialogTrigger, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../../components/ui/dialog";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { CategoryIcon } from "../../components/patterns/CategoryIcon";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { listUoms, listLocations } from "../warehouse/api";
import { CATEGORY_ORDER, CLASSIFICATIONS_QUERY_KEY, PRODUCTS_QUERY_KEY, useCatalogLabels, useProductCatalog, type CatalogProduct } from "./catalog";
import { setClassification, type ProductCategory } from "../production/api";
import { CategoryBadge } from "../../components/patterns/StatusBadge";
import {
  createProduct,
  createProductTag,
  deleteProduct,
  listProductTags,
  listTagsForProduct,
  setProductTags,
  updateProduct,
} from "./api";
import { ClassificationFields, ProductWizard, productWizardSchema, type ProductWizardForm } from "./ProductWizard";
import { TableLoadingRow } from "../../components/patterns/AppLoader";

const UOMS_QUERY_KEY = ["core", "uoms"] as const;
const LOCATIONS_QUERY_KEY = ["warehouse", "locations"] as const;
const TAGS_QUERY_KEY = ["core", "product-tags"] as const;

// Convert wizard form to API input (handles string-to-boolean conversions)
function toApiInput(input: ProductWizardForm) {
  // category / packaging_kind go to the production module's classification, not the product row.
  const { category: _category, packaging_kind: _packagingKind, ...productFields } = input;
  return {
    ...productFields,
    is_sellable: input.is_sellable === "true",
    is_purchasable: input.is_purchasable === "true",
    default_location_id: input.default_location_id || undefined,
    product_family: input.product_family || undefined,
  };
}

// Convert Product entity to form defaults for edit mode (would need to add this to wizard)
function productToFormDefaults(product: CatalogProduct): ProductWizardForm {
  return {
    category: product.category ?? undefined,
    packaging_kind: product.packaging_kind ?? undefined,
    sku: product.sku,
    name: product.name,
    product_type: (product as any).product_type ?? "PL",
    product_family: (product as any).product_family ?? "",
    uom_id: product.uom_id,
    net_weight_grams: product.net_weight_grams ?? undefined,
    empty_packaging_weight_grams: (product as any).empty_packaging_weight_grams ?? undefined,
    sachets_per_package: (product as any).sachets_per_package ?? undefined,
    packets_per_carton: product.packets_per_carton ?? undefined,
    carton_weight_grams: (product as any).carton_weight_grams ?? undefined,
    cartons_per_pallet: (product as any).cartons_per_pallet ?? undefined,
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

type FormFieldsProps = Pick<UseFormReturn<ProductWizardForm>, "register" | "formState" | "watch">;

export function ProductListTab() {
  const { session, hasPermission } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [wizardOpen, setWizardOpen] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState<"all" | "unclassified" | ProductCategory>("all");
  const catalogLabels = useCatalogLabels();
  // Classifying needs production's permission; without it the product is still
  // created, it just stays "Unclassified" until someone with the right does it.
  const canClassify = hasPermission("production.manage_product_classifications");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [lotTrackingFilter, setLotTrackingFilter] = useState<"all" | "none" | "lot" | "serial">("all");
  const [sellableFilter, setSellableFilter] = useState<"sellable" | "all">("sellable");

  const { catalog: products, isLoading } = useProductCatalog();
  const { data: uoms = [] } = useQuery({ queryKey: UOMS_QUERY_KEY, queryFn: () => listUoms(token) });
  const { data: locations = [] } = useQuery({ queryKey: LOCATIONS_QUERY_KEY, queryFn: () => listLocations(token) });
  const { data: tags = [] } = useQuery({ queryKey: TAGS_QUERY_KEY, queryFn: () => listProductTags(token) });

  const topLevelProducts = products
    .filter((p) => !p.parent_product_id)
    .filter((p) => lotTrackingFilter === "all" || p.lot_serial_tracking === lotTrackingFilter)
    .filter((p) => sellableFilter === "all" || p.is_sellable)
    .filter((p) => categoryFilter === "all" || (categoryFilter === "unclassified" ? p.category === null : p.category === categoryFilter));

  const [selectedTagIds, setSelectedTagIds] = useState<string[]>([]);

  async function saveClassification(productId: string, input: ProductWizardForm, existing?: CatalogProduct) {
    if (!canClassify || !input.category) return;
    const unchanged =
      existing && existing.category === input.category && (existing.packaging_kind ?? undefined) === (input.category === "packaging_component" ? input.packaging_kind : undefined);
    if (unchanged) return;
    // Flags production owns (regrind, water, energy, packet/carton format) are kept as
    // they are: this form only sets the category, it must not silently reset them.
    const keepsCategory = existing?.category === input.category;
    await setClassification(token, {
      product_id: productId,
      category: input.category,
      is_regrind: keepsCategory ? (existing?.is_regrind ?? false) : false,
      is_water: keepsCategory ? (existing?.is_water ?? false) : false,
      is_energy: keepsCategory ? (existing?.is_energy ?? false) : false,
      packaging_format: keepsCategory && input.category === "finished_good" ? (existing?.packaging_format ?? undefined) : undefined,
      packaging_kind: input.category === "packaging_component" ? input.packaging_kind : undefined,
    });
  }

  const createMutation = useMutation({
    mutationFn: async (input: ProductWizardForm) => {
      const product = await createProduct(token, toApiInput(input));
      if (selectedTagIds.length > 0) await setProductTags(token, product.id, selectedTagIds);
      await saveClassification(product.id, input);
      return product;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PRODUCTS_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: CLASSIFICATIONS_QUERY_KEY });
      setWizardOpen(false);
      setSelectedTagIds([]);
      toast.success(t("products.created"));
    },
    onError: (error) => {
      toast.error(t("products.createError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const editForm = useForm<ProductWizardForm>({ resolver: zodResolver(productWizardSchema) });
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
    mutationFn: async ({ id, input }: { id: string; input: ProductWizardForm }) => {
      const product = await updateProduct(token, id, toApiInput(input));
      await setProductTags(token, id, editTagIds);
      await saveClassification(id, input, products.find((p) => p.id === id));
      return product;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PRODUCTS_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: CLASSIFICATIONS_QUERY_KEY });
      setEditingId(null);
      toast.success(t("products.updated"));
    },
    onError: (error) => {
      toast.error(t("products.updateError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteProduct(token, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PRODUCTS_QUERY_KEY });
      setDeletingId(null);
      toast.success(t("products.deleted"));
    },
    onError: (error) => {
      toast.error(t("products.deleteError"), { description: error instanceof ApiError ? error.message : undefined });
    },
  });

  function openEditDialog(product: CatalogProduct | null) {
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

  const columnFilterFields: FilterField<CatalogProduct>[] = [
    { key: "sku", kind: "text", getValue: (p) => p.sku },
    { key: "name", kind: "text", getValue: (p) => p.name },
    { key: "selling_price", kind: "range", getValue: (p) => p.selling_price },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredProducts = columnFilters.apply(topLevelProducts);

  const columns: ColumnDef<CatalogProduct>[] = [
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
      sortValue: (product) => product.sku,
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
      sortValue: (product) => product.name,
    },
    {
      key: "category",
      header: (
        <span className="inline-flex items-center gap-1">
          {t("products.column.category")}
          <HelpTooltip text={t("products.help.category")} />
        </span>
      ),
      defaultWidth: 200,
      cell: (product) =>
        product.category ? (
          <span className="inline-flex flex-wrap items-center gap-1">
            <CategoryBadge category={product.category} />
            {product.packaging_kind && <Badge variant="outline">{catalogLabels.packagingKind[product.packaging_kind]}</Badge>}
          </span>
        ) : (
          <Badge variant="warning">{catalogLabels.unclassified}</Badge>
        ),
      sortValue: (product) => (product.category ? `${product.category}:${product.packaging_kind ?? ""}` : "~"),
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
      header: (
        <span className="inline-flex items-center gap-1">
          {t("products.column.lotTracking")}
          <HelpTooltip text={t("products.help.lotTracking")} />
        </span>
      ),
      defaultWidth: 160,
      cell: (product) => (
        <span className="text-muted-foreground">
          {product.lot_serial_tracking === "none"
            ? "—"
            : t(`products.lotTracking.${product.lot_serial_tracking}` as Parameters<typeof t>[0])}
        </span>
      ),
      sortValue: (product) => product.lot_serial_tracking,
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
      sortValue: (product) => product.selling_price,
    },
    {
      key: "action",
      header: t("products.column.action"),
      defaultWidth: 200,
      alwaysVisible: true,
      headerClassName: "text-right",
      cellClassName: "text-right",
      cell: (product) => (
        <div className="flex gap-2 justify-end">
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
          <Dialog open={deletingId === product.id} onOpenChange={(open) => setDeletingId(open ? product.id : null)}>
            <DialogTrigger asChild>
              <Button size="sm" variant="outline" className="text-destructive hover:text-destructive">
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{t("products.dialog.deleteTitle")}</DialogTitle>
                <DialogDescription>{t("products.dialog.deleteDescription")}</DialogDescription>
              </DialogHeader>
              <div className="space-y-4">
                <p className="text-sm text-muted-foreground">
                  {t("products.dialog.deleteConfirm")}
                </p>
                <div className="flex gap-2 justify-end">
                  <Button variant="outline" onClick={() => setDeletingId(null)}>
                    {t("common.cancel")}
                  </Button>
                  <Button variant="destructive" onClick={() => deleteMutation.mutate(product.id)} disabled={deleteMutation.isPending}>
                    {deleteMutation.isPending ? t("products.deleting") : t("products.delete")}
                  </Button>
                </div>
              </div>
            </DialogContent>
          </Dialog>
        </div>
      ),
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("products.list", columns);
  const sortedProducts = sortRows(filteredProducts);

  function renderTagPicker(ids: string[], onChange: (ids: string[]) => void) {
    return (
      <div className="space-y-1.5">
        <Label className="flex items-center gap-1.5">
          <TagIcon className="h-3.5 w-3.5" />
          {t("products.field.tags")}
          <HelpTooltip text={t("products.help.tags")} />
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
                  {uom.symbol || uom.code}
                </option>
              ))}
            </Select>
            {errors.uom_id && <p className="text-sm text-destructive">{errors.uom_id.message}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}_type`}>{t("products.field.type")}</Label>
            <Select id={`${idPrefix}_type`} {...form.register("product_type")}>
              <option value="PL">Pâte Longues (PL)</option>
              <option value="PC">Pâte Courte (PC)</option>
            </Select>
            {errors.product_type && <p className="text-sm text-destructive">{errors.product_type.message}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}_family`}>{t("products.field.family")}</Label>
            <Input id={`${idPrefix}_family`} placeholder="e.g., Spaghetti 1,1" {...form.register("product_family")} />
          </div>
          {canClassify && (
            <div className="col-span-2">
              <ClassificationFields form={form} idPrefix={idPrefix} t={t} />
            </div>
          )}
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
            <Label htmlFor={`${idPrefix}_lot`} className="flex items-center gap-1.5">
              {t("products.field.lotSerialTracking")}
              <HelpTooltip text={t("products.help.lotTracking")} />
            </Label>
            <Select id={`${idPrefix}_lot`} {...form.register("lot_serial_tracking")}>
              <option value="none">{t("products.lotTracking.none")}</option>
              <option value="lot">{t("products.lotTracking.lot")}</option>
              <option value="serial">{t("products.lotTracking.serial")}</option>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${idPrefix}_expiry`} className="flex items-center gap-1.5">
              {t("products.field.expiryDatePolicy")}
              <HelpTooltip text={t("products.help.expiryDatePolicy")} />
            </Label>
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

        <div className="space-y-1.5 rounded-lg border border-border p-3">
          <Label className="text-xs text-muted-foreground">{t("products.statistics.packaging.title")} — {t("common.optional")}</Label>
          <div className="grid grid-cols-2 gap-2">
            <Input
              placeholder={t("products.field.emptyPackagingWeight")}
              type="number"
              step="any"
              {...form.register("empty_packaging_weight_grams")}
              error={errors.empty_packaging_weight_grams?.message}
            />
            <Input
              placeholder={t("products.field.sachetsPerPackage")}
              type="number"
              step="any"
              {...form.register("sachets_per_package")}
              error={errors.sachets_per_package?.message}
            />
            <Input
              placeholder={t("products.field.packetsPerCarton")}
              type="number"
              step="any"
              {...form.register("packets_per_carton")}
              error={errors.packets_per_carton?.message}
            />
            <Input
              placeholder={t("products.field.cartonWeight")}
              type="number"
              step="any"
              {...form.register("carton_weight_grams")}
              error={errors.carton_weight_grams?.message}
            />
            <Input
              placeholder={t("products.field.cartonsPerPallet")}
              type="number"
              step="any"
              {...form.register("cartons_per_pallet")}
              error={errors.cartons_per_pallet?.message}
            />
          </div>
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
            <Label htmlFor={`${idPrefix}_alert`} className="flex items-center gap-1.5">
              {t("products.field.stockAlert")}
              <HelpTooltip text={t("products.help.stockAlert")} />
            </Label>
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
            <Label htmlFor={`${idPrefix}_minprice`} className="flex items-center gap-1.5">
              {t("products.field.minSellingPrice")}
              <HelpTooltip text={t("products.help.minSellingPrice")} />
            </Label>
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
              value={sellableFilter}
              onChange={setSellableFilter}
              options={[
                { value: "sellable", label: t("products.filter.sellableOnly") },
                { value: "all", label: t("common.all") },
              ]}
            />
            <FilterTabs
              value={categoryFilter}
              onChange={setCategoryFilter}
              options={[
                { value: "all", label: t("common.all") },
                ...CATEGORY_ORDER.map((category) => ({ value: category, label: catalogLabels.category[category], icon: <CategoryIcon category={category} /> })),
                { value: "unclassified", label: catalogLabels.unclassified },
              ]}
            />
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
          <Button onClick={() => setWizardOpen(true)}>
            <Plus className="h-4 w-4" />
            {t("products.new")}
          </Button>

          <ProductWizard
            open={wizardOpen}
            onOpenChange={setWizardOpen}
            uoms={uoms}
            locations={locations}
            onSubmit={(input) => createMutation.mutate(input)}
            isLoading={createMutation.isPending}
            canClassify={canClassify}
            t={t}
          />
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
                    sortDirection={sortDirectionFor(column.key)}
                    onSort={column.sortValue ? () => toggleSort(column.key) : undefined}
                  >
                    {column.header}
                  </ResizableTableHead>
                ))}
              </TableRow>
              <ColumnFilterRow cells={visibleColumns.map((column) => column.filterCell ?? { type: "blank" })} />
            </TableHeader>
            <TableBody>
              {isLoading && <TableLoadingRow colSpan={visibleColumns.length} />}
              {!isLoading && filteredProducts.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <EmptyState icon={<Package className="h-5 w-5" />} title={t("products.empty.title")} description={t("products.empty.description")} />
                  </TableCell>
                </TableRow>
              )}
              <AnimatePresence initial={false}>
                {sortedProducts.map((product, i) => (
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
