import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Layers, Plus, Recycle, Tag } from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { useAuth } from "../../lib/auth";
import { useI18n } from "../../lib/i18n";
import { ApiError } from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Label } from "../../components/ui/label";
import { Select } from "../../components/ui/select";
import { Checkbox } from "../../components/ui/checkbox";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableCell, ResizableTableHead } from "../../components/ui/table";
import { Skeleton } from "../../components/ui/skeleton";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "../../components/ui/dialog";
import {
  listClassifications,
  listProducts,
  setClassification,
  type PackagingFormat,
  type ProductCategory,
  type ProductClassification,
} from "./api";
import { CategoryBadge } from "../../components/patterns/StatusBadge";
import { StatCard } from "../../components/patterns/StatCard";
import { EmptyState } from "../../components/patterns/EmptyState";
import { FilterTabs } from "../../components/patterns/FilterTabs";
import { ColumnFilterRow } from "../../components/patterns/ColumnFilterRow";
import { ColumnVisibilityMenu } from "../../components/patterns/ColumnVisibilityMenu";
import { HelpTooltip } from "../../components/patterns/HelpTooltip";
import { useColumnFilters, type FilterField } from "../../lib/useColumnFilters";
import { useTableColumns, type ColumnDef } from "../../lib/useTableColumns";
import { Badge } from "../../components/ui/badge";

const CATEGORY_VALUES: ProductCategory[] = ["raw_material", "semi_finished", "packaging_component", "finished_good"];
type CategoryFilter = "all" | ProductCategory;

const PACKAGING_FORMAT_VALUES: PackagingFormat[] = ["packet", "carton", "sac"];

const formSchema = z
  .object({
    product_id: z.string().min(1, "Required"),
    category: z.enum(["raw_material", "semi_finished", "packaging_component", "finished_good"]),
    is_regrind: z.boolean(),
    is_water: z.boolean(),
    packaging_format: z.enum(["packet", "carton", "sac"]).optional(),
  })
  .refine((data) => !(data.is_regrind && data.is_water), {
    message: "A product cannot be both regrind and water/humidity",
    path: ["is_water"],
  });
type FormValues = z.infer<typeof formSchema>;

const QUERY_KEY = ["production", "product-classifications"] as const;
const PRODUCTS_QUERY_KEY = ["core", "products"] as const;

export function ProductClassificationsTab() {
  const { session } = useAuth();
  const { t } = useI18n();
  const token = session!.token;
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("all");

  const CATEGORY_LABEL: Record<ProductCategory, string> = {
    raw_material: t("production.classifications.category.raw_material"),
    semi_finished: t("production.classifications.category.semi_finished"),
    packaging_component: t("production.classifications.category.packaging_component"),
    finished_good: t("production.classifications.category.finished_good"),
  };

  const PACKAGING_FORMAT_LABEL: Record<PackagingFormat, string> = {
    packet: t("production.classifications.packagingFormat.packet"),
    carton: t("production.classifications.packagingFormat.carton"),
    sac: t("production.classifications.packagingFormat.sac"),
  };

  const { data: classifications = [], isLoading } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => listClassifications(token),
  });
  const { data: products = [] } = useQuery({ queryKey: PRODUCTS_QUERY_KEY, queryFn: () => listProducts(token) });
  const productName = (id: string) => products.find((p) => p.id === id)?.name ?? "—";

  const {
    register,
    control,
    handleSubmit,
    watch,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: { product_id: "", category: "raw_material", is_regrind: false, is_water: false },
  });
  const category = watch("category");

  const mutation = useMutation({
    mutationFn: (input: FormValues) =>
      setClassification(token, {
        ...input,
        packaging_format: input.category === "finished_good" ? input.packaging_format : undefined,
      }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      setDialogOpen(false);
      reset({ product_id: "", category: "raw_material", is_regrind: false, is_water: false });
      toast.success(t("production.classifications.saved"), { description: result.product_id });
    },
    onError: (error) => {
      toast.error(t("production.classifications.saveError"), {
        description: error instanceof ApiError ? error.message : undefined,
      });
    },
  });

  const regrindCount = classifications.filter((c) => c.is_regrind).length;
  const categoriesUsed = new Set(classifications.map((c) => c.category)).size;
  const categoryFilteredClassifications =
    categoryFilter === "all" ? classifications : classifications.filter((c) => c.category === categoryFilter);

  const columnFilterFields: FilterField<ProductClassification>[] = [
    { key: "product_id", kind: "text", getValue: (c) => productName(c.product_id) },
  ];
  const columnFilters = useColumnFilters(columnFilterFields);
  const filteredClassifications = columnFilters.apply(categoryFilteredClassifications);

  const columns: ColumnDef<ProductClassification>[] = [
    {
      key: "product_id",
      header: t("production.classifications.column.productId"),
      defaultWidth: 200,
      cell: (c) => <span className="font-medium">{productName(c.product_id)}</span>,
      filterCell: {
        type: "text",
        value: columnFilters.text.product_id ?? "",
        onChange: (v) => columnFilters.setTextValue("product_id", v),
        placeholder: t("production.classifications.column.productId"),
      },
      sortValue: (c) => productName(c.product_id),
    },
    {
      key: "category",
      header: t("production.classifications.column.category"),
      defaultWidth: 180,
      cell: (c) => <CategoryBadge category={c.category} />,
      sortValue: (c) => c.category,
    },
    {
      key: "packagingFormat",
      header: t("production.classifications.column.packagingFormat"),
      defaultWidth: 160,
      cell: (c) => <span className="text-muted-foreground">{c.packaging_format ? PACKAGING_FORMAT_LABEL[c.packaging_format] : "—"}</span>,
      sortValue: (c) => (c.packaging_format ? PACKAGING_FORMAT_LABEL[c.packaging_format] : null),
    },
    {
      key: "regrind",
      header: t("production.classifications.column.regrind"),
      defaultWidth: 140,
      cell: (c) =>
        c.is_regrind ? (
          <Badge variant="success" dot>
            {t("production.classifications.regrindBadge")}
          </Badge>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
      sortValue: (c) => c.is_regrind,
    },
    {
      key: "water",
      header: t("production.classifications.column.water"),
      defaultWidth: 140,
      cell: (c) =>
        c.is_water ? (
          <Badge variant="success" dot>
            {t("production.classifications.waterBadge")}
          </Badge>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
      sortValue: (c) => c.is_water,
    },
  ];
  const { visibleColumns, colWidths, isVisible, toggleVisible, getWidth, setWidth, resetAll, sortDirectionFor, toggleSort, sortRows } =
    useTableColumns("production.classifications", columns);
  const sortedClassifications = sortRows(filteredClassifications);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label={t("production.classifications.stat.total")} value={classifications.length} icon={<Tag className="h-5 w-5" />} />
        <StatCard label={t("production.classifications.stat.categories")} value={categoriesUsed} icon={<Layers className="h-5 w-5" />} accent="accent" />
        <StatCard label={t("production.classifications.stat.regrind")} value={regrindCount} icon={<Recycle className="h-5 w-5" />} accent="success" />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <CardTitle className="flex items-center gap-1.5">
                {t("production.classifications.table.title")}
                <HelpTooltip text={t("production.classifications.help.table")} />
              </CardTitle>
              <p className="mt-0.5 text-sm text-muted-foreground">{t("production.classifications.table.subtitle")}</p>
            </div>
            <FilterTabs
              value={categoryFilter}
              onChange={setCategoryFilter}
              options={[
                { value: "all", label: t("common.all") },
                ...CATEGORY_VALUES.map((value) => ({ value, label: CATEGORY_LABEL[value] })),
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
                {t("production.classifications.classify")}
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{t("production.classifications.dialog.title")}</DialogTitle>
                <DialogDescription>{t("production.classifications.dialog.description")}</DialogDescription>
              </DialogHeader>
              <form className="space-y-4" onSubmit={handleSubmit((input) => mutation.mutate(input))}>
                <div className="space-y-1.5">
                  <Label htmlFor="product_id">{t("production.classifications.field.productId")}</Label>
                  <Select id="product_id" {...register("product_id")}>
                    <option value="">—</option>
                    {products.map((product) => (
                      <option key={product.id} value={product.id}>
                        {product.name}
                      </option>
                    ))}
                  </Select>
                  {errors.product_id && <p className="text-sm text-destructive">{errors.product_id.message}</p>}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="category">{t("production.classifications.field.category")}</Label>
                  <Controller
                    control={control}
                    name="category"
                    render={({ field }) => (
                      <Select id="category" {...field}>
                        {CATEGORY_VALUES.map((value) => (
                          <option key={value} value={value}>
                            {CATEGORY_LABEL[value]}
                          </option>
                        ))}
                      </Select>
                    )}
                  />
                </div>
                <AnimatePresence initial={false}>
                  {category === "raw_material" && (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.18 }}
                      className="space-y-2"
                    >
                      <div className="flex items-center gap-2">
                        <Controller
                          control={control}
                          name="is_regrind"
                          render={({ field }) => (
                            <Checkbox id="is_regrind" checked={field.value} onCheckedChange={field.onChange} />
                          )}
                        />
                        <Label htmlFor="is_regrind" className="cursor-pointer font-normal text-muted-foreground">
                          {t("production.classifications.isRegrindLabel")}
                        </Label>
                      </div>
                      <div className="flex items-center gap-2">
                        <Controller
                          control={control}
                          name="is_water"
                          render={({ field }) => (
                            <Checkbox id="is_water" checked={field.value} onCheckedChange={field.onChange} />
                          )}
                        />
                        <Label htmlFor="is_water" className="cursor-pointer font-normal text-muted-foreground">
                          {t("production.classifications.isWaterLabel")}
                        </Label>
                      </div>
                      {errors.is_water && <p className="text-sm text-destructive">{errors.is_water.message}</p>}
                    </motion.div>
                  )}
                  {category === "finished_good" && (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.18 }}
                      className="space-y-1.5"
                    >
                      <Label htmlFor="packaging_format">{t("production.classifications.field.packagingFormat")}</Label>
                      <Select id="packaging_format" {...register("packaging_format")}>
                        <option value="">—</option>
                        {PACKAGING_FORMAT_VALUES.map((value) => (
                          <option key={value} value={value}>
                            {PACKAGING_FORMAT_LABEL[value]}
                          </option>
                        ))}
                      </Select>
                    </motion.div>
                  )}
                </AnimatePresence>

                {mutation.isError && (
                  <p className="text-sm text-destructive">
                    {mutation.error instanceof ApiError ? mutation.error.message : t("production.classifications.saveError")}
                  </p>
                )}
                <Button type="submit" className="w-full" disabled={mutation.isPending}>
                  {mutation.isPending ? t("production.classifications.saving") : t("production.classifications.save")}
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
              {isLoading &&
                Array.from({ length: 3 }).map((_, i) => (
                  <TableRow key={i}>
                    <TableCell colSpan={visibleColumns.length}>
                      <Skeleton className="h-5 w-full" />
                    </TableCell>
                  </TableRow>
                ))}
              {!isLoading && filteredClassifications.length === 0 && (
                <TableRow>
                  <TableCell colSpan={visibleColumns.length} className="p-0">
                    <EmptyState
                      icon={<Tag className="h-5 w-5" />}
                      title={t("production.classifications.empty.title")}
                      description={t("production.classifications.empty.description")}
                    />
                  </TableCell>
                </TableRow>
              )}
              <AnimatePresence initial={false}>
                {sortedClassifications.map((c, i) => (
                  <motion.tr
                    key={c.product_id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0, transition: { delay: Math.min(i * 0.03, 0.3) } }}
                    exit={{ opacity: 0 }}
                    className="border-b border-border last:border-0 hover:bg-muted/50"
                  >
                    {visibleColumns.map((column) => (
                      <TableCell key={column.key} className={column.cellClassName}>
                        {column.cell(c)}
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
